"""src/pipeline/instructor_decomposer.py

Unified LLM-based decomposer that reads a natural-language control instruction
(Markdown) + dataset schemas + sample rows and produces:
  - GroupManifest  (controls/<ID>/decomposition.yaml)
  - One DSLPlan per group  (controls/<ID>/groups/<gid>/dsl.yaml)

Uses DeepSeek via instructor (same pattern as scrap/llm.py).
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

import yaml
from pydantic import BaseModel, Field

from src.decomposer.llm_client import LLMClient, LLMError
from src.models.decomposition import GroupDefinition, GroupManifest
from src.models.dsl import (
    AggregateMetric,
    AggregateStep,
    CompletenessStep,
    DSLPlan,
    DateDiffStep,
    FilterConditionDef,
    FilterStep,
    JoinKey,
    JoinStep,
    NormalizeStep,
    ReconciliationStep,
    ThresholdStep,
    UniquenessStep,
)
from src.models.schema import DatasetSchema
from src.utils.filesystem import ensure_dir, load_yaml
from src.utils.logging import get_logger

log = get_logger(__name__)


# ---------------------------------------------------------------------------
# LLM output models (instructor enforces these via Pydantic)
# ---------------------------------------------------------------------------


class StepSpec(BaseModel):
    """Flat DSL step that the LLM generates — all fields optional except type/id/output_alias."""

    id: str = Field(description="Sequential step ID: step_01, step_02 ...")
    type: Literal[
        "NORMALIZE",
        "JOIN",
        "FILTER",
        "AGGREGATE",
        "DATE_DIFF",
        "THRESHOLD",
        "COMPLETENESS",
        "UNIQUENESS",
        "RECONCILIATION",
    ]
    output_alias: str = Field(description="Unique SQL alias for this CTE")

    # NORMALIZE
    dataset: Optional[str] = Field(None, description="[NORMALIZE] dataset ID (CSV filename stem)")

    # JOIN / RECONCILIATION
    left: Optional[str] = Field(None, description="[JOIN/RECONCILIATION] left input alias")
    right: Optional[str] = Field(None, description="[JOIN/RECONCILIATION] right input alias")
    join_type: Optional[str] = Field("inner", description="[JOIN] inner | left | full")
    left_key: Optional[str] = Field(None, description="[JOIN/RECONCILIATION] left join column")
    right_key: Optional[str] = Field(None, description="[JOIN/RECONCILIATION] right join column")

    # FILTER
    conditions: Optional[list[str]] = Field(
        None, description="[FILTER] SQL WHERE conditions (AND-ed together)"
    )

    # AGGREGATE
    metrics: Optional[list[dict]] = Field(
        None,
        description="[AGGREGATE] list of {name: str, formula: str, filter?: str}",
    )

    # DATE_DIFF
    from_field: Optional[str] = Field(None, description="[DATE_DIFF] start date column name")
    to_field: Optional[str] = Field(None, description="[DATE_DIFF] end date column name")
    unit: Optional[str] = Field("days", description="[DATE_DIFF] days | hours | months")

    # THRESHOLD
    condition: Optional[str] = Field(None, description="[THRESHOLD] SQL boolean expression")
    flag_field: Optional[str] = Field(None, description="[THRESHOLD] name for the added boolean column")

    # COMPLETENESS / FILTER / DATE_DIFF — optional pre-filter
    check_field: Optional[str] = Field(None, description="[COMPLETENESS] column that must not be null")

    # UNIQUENESS
    key_columns: Optional[list[str]] = Field(None, description="[UNIQUENESS] columns to check uniqueness on")

    # Pre-filter (COMPLETENESS, DATE_DIFF)
    filter_field: Optional[str] = Field(None, description="Pre-filter: field name")
    filter_op: Optional[str] = Field(None, description="Pre-filter: eq | neq | gt | lt | gte | lte")
    filter_value: Optional[str] = Field(None, description="Pre-filter: literal value as string")

    # Common — which check this step belongs to
    input: Optional[str] = Field(
        None,
        description="[FILTER/AGGREGATE/DATE_DIFF/THRESHOLD/COMPLETENESS/UNIQUENESS] input alias",
    )
    check_id: Optional[str] = Field(
        None,
        description="[FILTER/AGGREGATE/COMPLETENESS/UNIQUENESS/RECONCILIATION] check identifier",
    )


class GroupPlan(BaseModel):
    id: str = Field(description="Snake-case group ID, e.g. grp_01_access_violations")
    name: str = Field(description="Short human-readable name")
    description: str = Field(description="What this group checks")
    datasets: list[str] = Field(description="Dataset IDs used (CSV filename stems)")
    execution_order: int = Field(description="1-based execution order")
    steps: list[StepSpec] = Field(description="Ordered DSL steps")


class ControlPlan(BaseModel):
    """Full control execution plan returned by the LLM."""

    groups: list[GroupPlan] = Field(
        description="Logical execution groups. Each group compiles to one SQL file."
    )


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a data engineering expert specializing in financial controls and compliance automation.

Your task: given a control description (in Markdown) and the schemas of evidence datasets,
produce a ControlPlan — a list of execution groups, each with DSL steps that define what
to check and how to check it.

=== DSL STEP TYPES ===

NORMALIZE — Select and type-cast columns from a raw dataset.
  Required fields: dataset (dataset ID), output_alias
  Use this as the first step for every dataset referenced in a group.

JOIN — Combine two aliases via a SQL JOIN.
  Required fields: left, right, left_key, right_key, join_type (inner|left|full), output_alias

FILTER — Select rows that violate a condition. Each matching row becomes a violation.
  Required fields: input, conditions (list of SQL WHERE clauses, AND-ed), output_alias, check_id

AGGREGATE — Compute summary metrics. Produces a pass/fail result.
  Required fields: input, metrics (list of {name, formula} or {name, formula, filter}), output_alias, check_id
  metrics.formula must be valid DuckDB aggregate SQL (COUNT(*), SUM(col), ROUND(...), etc.)

DATE_DIFF — Add a computed column with the difference between two date fields.
  Required fields: input, from_field, to_field, unit (days|hours|months), output_alias
  Optional: filter_field, filter_op (eq|neq|gt|lt), filter_value

THRESHOLD — Add a boolean flag column based on a condition.
  Required fields: input, condition (SQL boolean expr), flag_field (new column name), output_alias

COMPLETENESS — Find rows where a required field is NULL or missing.
  Required fields: input, check_field, output_alias, check_id
  Optional: filter_field, filter_op, filter_value (to scope to a subset)

UNIQUENESS — Find duplicate rows by key columns.
  Required fields: input, key_columns (list), output_alias, check_id

RECONCILIATION — Find records in left that have no match in right.
  Required fields: left, right, left_key, right_key, output_alias, check_id

=== CRITICAL SQL RULES ===

1. Column names: Use EXACTLY the normalized column names shown in the schema (snake_case).
2. Date comparisons: ALWAYS cast date columns — CAST(date_col AS DATE)
   Example: CAST(trade_date AS DATE) >= CURRENT_DATE - INTERVAL '7 days'
3. NEVER use table-qualified names ANYWHERE in conditions — after a JOIN the output CTE
   has plain unqualified columns. Use bare column names only.
   WRONG: WHERE settlements_03.status = 'SETTLED'
   RIGHT: WHERE status = 'SETTLED'
4. FILTER conditions are SQL fragments that evaluate to TRUE for violations.
5. AGGREGATE formulas must be valid DuckDB aggregate expressions.
   For a pass/fail ratio: use ROUND(COUNT(*) FILTER (WHERE flag_col)::DOUBLE / NULLIF(COUNT(*), 0), 4)
6. String comparisons: use single quotes: status = 'TERMINATED'
7. NULL checks: field IS NULL or field IS NOT NULL
8. DATE_DIFF output column name: When you use a DATE_DIFF step with from_field=X, to_field=Y,
   unit=Z, the output column name is EXACTLY: {X}_to_{Y}_{Z}s
   Example: from_field=termination_date, to_field=disabled_date, unit=days
           → column name: termination_date_to_disabled_date_days
   A subsequent THRESHOLD or FILTER step MUST reference this exact column name.
9. JOIN column ambiguity: when two joined tables share the same column name (e.g. both have
   'status' or 'trade_id'), the JOIN output CTE will have duplicate columns. To disambiguate,
   use a FILTER condition referencing only the column that is unambiguous in context, or ensure
   the JOIN output only keeps needed columns via explicit aliases in the JOIN step if necessary.

=== GROUPING GUIDELINES ===

- Group checks by data dependency (same datasets, similar join patterns).
- Each group should be self-contained: start with NORMALIZE steps for all datasets used.
- Terminal steps that produce output: FILTER, AGGREGATE, COMPLETENESS, UNIQUENESS, RECONCILIATION.
- At least one terminal step per group. DO NOT create groups that only have NORMALIZE steps —
  include the checks in the same group as the NORMALIZE steps.
- execution_order must be unique integers starting at 1.
- Group IDs must be snake_case, e.g.: grp_01_data_prep, grp_02_row_checks, grp_03_aggregates.
- After a JOIN, use only unqualified column names in downstream FILTER/THRESHOLD/AGGREGATE steps.
- When DATE_DIFF is followed by THRESHOLD: the THRESHOLD condition MUST use the exact generated
  column name ({from_field}_to_{to_field}_{unit}s).
"""


# ---------------------------------------------------------------------------
# User prompt builder
# ---------------------------------------------------------------------------


def _build_user_prompt(
    control_id: str,
    instruction: str,
    schemas: list[DatasetSchema],
    sample_rows: dict[str, list[dict]],
) -> str:
    schema_block = _format_schemas(schemas)
    samples_block = _format_samples(sample_rows)

    return (
        f"# Control ID: {control_id}\n\n"
        f"## Control Instruction\n\n{instruction}\n\n"
        f"## Dataset Schemas\n\n{schema_block}\n\n"
        f"## Sample Rows (first 5 per dataset)\n\n{samples_block}\n\n"
        "Generate the ControlPlan for this control."
    )


def _format_schemas(schemas: list[DatasetSchema]) -> str:
    lines = []
    for s in schemas:
        lines.append(f"### Dataset: `{s.dataset_id}`")
        lines.append(f"Source file: `{s.source_file}`")
        lines.append("Columns (normalized_name | type | nullable):")
        for col in s.columns:
            null_str = "nullable" if col.nullable else "required"
            lines.append(f"  - `{col.normalized_name}` | {col.type} | {null_str}")
        lines.append("")
    return "\n".join(lines)


def _format_samples(sample_rows: dict[str, list[dict]]) -> str:
    lines = []
    for ds_id, rows in sample_rows.items():
        lines.append(f"### `{ds_id}` (first {len(rows)} rows)")
        lines.append("```json")
        lines.append(json.dumps(rows[:5], default=str, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Step conversion: StepSpec → typed DSL step models
# ---------------------------------------------------------------------------


def _make_filter_def(spec: StepSpec) -> Optional[FilterConditionDef]:
    if spec.filter_field:
        return FilterConditionDef(
            field=spec.filter_field,
            op=spec.filter_op or "eq",
            value=spec.filter_value or "",
        )
    return None


def _spec_to_dsl_step(spec: StepSpec):
    """Convert a flat StepSpec to the typed DSL step Pydantic model."""
    base = {"id": spec.id, "output_alias": spec.output_alias}
    t = spec.type

    if t == "NORMALIZE":
        return NormalizeStep(**base, type="NORMALIZE", dataset=spec.dataset)

    if t == "JOIN":
        return JoinStep(
            **base,
            type="JOIN",
            left=spec.left,
            right=spec.right,
            on=JoinKey(left_key=spec.left_key or "", right_key=spec.right_key or ""),
            join_type=spec.join_type or "inner",
        )

    if t == "FILTER":
        return FilterStep(
            **base,
            type="FILTER",
            input=spec.input,
            conditions=spec.conditions or [],
            check_id=spec.check_id,
        )

    if t == "AGGREGATE":
        raw_metrics = spec.metrics or []
        metrics = [
            AggregateMetric(
                name=m["name"],
                formula=m["formula"],
                filter=m.get("filter"),
            )
            if isinstance(m, dict)
            else m
            for m in raw_metrics
        ]
        return AggregateStep(
            **base,
            type="AGGREGATE",
            input=spec.input,
            metrics=metrics,
            check_id=spec.check_id,
        )

    if t == "DATE_DIFF":
        return DateDiffStep(
            **base,
            type="DATE_DIFF",
            input=spec.input,
            from_field=spec.from_field or "",
            to_field=spec.to_field or "",
            unit=spec.unit or "days",
            filter=_make_filter_def(spec),
        )

    if t == "THRESHOLD":
        return ThresholdStep(
            **base,
            type="THRESHOLD",
            input=spec.input,
            condition=spec.condition or "",
            flag_field=spec.flag_field or "flag",
        )

    if t == "COMPLETENESS":
        return CompletenessStep(
            **base,
            type="COMPLETENESS",
            input=spec.input,
            check_field=spec.check_field or "",
            filter=_make_filter_def(spec),
            check_id=spec.check_id,
        )

    if t == "UNIQUENESS":
        return UniquenessStep(
            **base,
            type="UNIQUENESS",
            input=spec.input,
            key_columns=spec.key_columns or [],
            check_id=spec.check_id,
        )

    if t == "RECONCILIATION":
        return ReconciliationStep(
            **base,
            type="RECONCILIATION",
            left=spec.left,
            right=spec.right,
            left_key=spec.left_key or "",
            right_key=spec.right_key or "",
            check_id=spec.check_id,
        )

    raise ValueError(f"Unknown step type in StepSpec: {t}")


# ---------------------------------------------------------------------------
# Conversion: ControlPlan → GroupManifest + dict[group_id, DSLPlan]
# ---------------------------------------------------------------------------


def _plan_to_manifest_and_dsl(
    control_id: str,
    plan: ControlPlan,
) -> tuple[GroupManifest, dict[str, DSLPlan]]:
    now = datetime.now(timezone.utc).isoformat()

    groups: list[GroupDefinition] = []
    dsl_plans: dict[str, DSLPlan] = {}

    for gp in plan.groups:
        groups.append(
            GroupDefinition(
                id=gp.id,
                name=gp.name,
                description=gp.description,
                datasets=gp.datasets,
                checks=[],  # derived from step check_ids
                execution_order=gp.execution_order,
            )
        )

        # Build typed steps
        typed_steps = []
        for spec in gp.steps:
            try:
                typed_steps.append(_spec_to_dsl_step(spec))
            except Exception as exc:
                log.warning(
                    "[%s/%s] Could not convert step %s (%s): %s",
                    control_id,
                    gp.id,
                    spec.id,
                    spec.type,
                    exc,
                )

        dsl_plans[gp.id] = DSLPlan(
            control_id=control_id,
            group_id=gp.id,
            generated_at=now,
            generator="llm",
            steps=typed_steps,
        )

    manifest = GroupManifest(
        control_id=control_id,
        generated_at=now,
        generator="llm",
        groups=groups,
    )
    return manifest, dsl_plans


# ---------------------------------------------------------------------------
# Persistence helpers
# ---------------------------------------------------------------------------


def _save_manifest(manifest: GroupManifest, controls_dir: Path) -> None:
    path = controls_dir / manifest.control_id / "decomposition.yaml"
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(manifest.model_dump(), fh, default_flow_style=False, allow_unicode=True)
    log.info("[%s] decomposition.yaml written → %s", manifest.control_id, path)


def _save_dsl(control_id: str, group_id: str, plan: DSLPlan, controls_dir: Path) -> None:
    path = controls_dir / control_id / "groups" / group_id / "dsl.yaml"
    ensure_dir(path.parent)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(plan.model_dump(), fh, default_flow_style=False, allow_unicode=True)
    log.info("[%s/%s] dsl.yaml written → %s", control_id, group_id, path)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def decompose_control(
    control_id: str,
    instruction: str,
    schemas: list[DatasetSchema],
    sample_rows: dict[str, list[dict]],
    controls_dir: Path,
    llm_client: LLMClient,
    force: bool = False,
) -> tuple[GroupManifest, dict[str, DSLPlan]]:
    """Generate (or load) the full control plan via DeepSeek.

    Idempotent: if decomposition.yaml already exists and force=False,
    loads existing artifacts.

    Args:
        control_id:    Control identifier (e.g. "HR_ACCESS_001").
        instruction:   Contents of control-instruction.md.
        schemas:       Normalized dataset schemas.
        sample_rows:   Dict of dataset_id → first-N rows (for the LLM prompt).
        controls_dir:  Root controls/ directory.
        llm_client:    Configured LLMClient.
        force:         Regenerate even if artifacts exist.

    Returns:
        (GroupManifest, {group_id: DSLPlan})
    """
    decomp_path = controls_dir / control_id / "decomposition.yaml"

    if decomp_path.exists() and not force:
        log.info("[%s] decomposition.yaml exists — loading (skip LLM).", control_id)
        manifest = GroupManifest.model_validate(load_yaml(decomp_path))

        dsl_plans: dict[str, DSLPlan] = {}
        for g in manifest.groups:
            dsl_path = controls_dir / control_id / "groups" / g.id / "dsl.yaml"
            if dsl_path.exists():
                dsl_plans[g.id] = DSLPlan.model_validate(load_yaml(dsl_path))
            else:
                log.warning(
                    "[%s/%s] dsl.yaml missing — will regenerate this group only.",
                    control_id,
                    g.id,
                )
        return manifest, dsl_plans

    if force and decomp_path.exists():
        log.info("[%s] --force: regenerating decomposition.", control_id)

    # --- LLM call ---
    log.info("[%s] Calling DeepSeek to generate control plan …", control_id)

    user_prompt = _build_user_prompt(control_id, instruction, schemas, sample_rows)

    plan: ControlPlan = llm_client.call_model(
        system_prompt=_SYSTEM_PROMPT,
        user_prompt=user_prompt,
        response_model=ControlPlan,
    )

    log.info(
        "[%s] LLM returned %d groups with %d total steps.",
        control_id,
        len(plan.groups),
        sum(len(g.steps) for g in plan.groups),
    )

    manifest, dsl_plans = _plan_to_manifest_and_dsl(control_id, plan)

    # Persist artifacts
    _save_manifest(manifest, controls_dir)
    for gid, dsl_plan in dsl_plans.items():
        _save_dsl(control_id, gid, dsl_plan, controls_dir)

    return manifest, dsl_plans
