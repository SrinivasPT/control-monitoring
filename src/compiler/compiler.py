"""Main compiler — transforms a DSLPlan into a compiled SQL file.

One SQL file per group.  Idempotent: skips compilation if the file exists.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from src.compiler.cte_builder import _RESULT_TYPE_MAP, CTEBuilder
from src.compiler.primitives import (
    aggregate,
    completeness,
    date_diff,
    filter,
    join,
    normalize,
    reconciliation,
    threshold,
    uniqueness,
)
from src.models.dsl import (
    DSLPlan,
)
from src.models.schema import DatasetSchema
from src.utils.filesystem import ensure_dir
from src.utils.logging import get_logger

log = get_logger(__name__)

# Dispatch table: step type → primitive module build_cte function
_DISPATCH = {
    "NORMALIZE": normalize.build_cte,
    "JOIN": join.build_cte,
    "FILTER": filter.build_cte,
    "AGGREGATE": aggregate.build_cte,
    "DATE_DIFF": date_diff.build_cte,
    "THRESHOLD": threshold.build_cte,
    "COMPLETENESS": completeness.build_cte,
    "UNIQUENESS": uniqueness.build_cte,
    "RECONCILIATION": reconciliation.build_cte,
}


def compile_group(
    plan: DSLPlan,
    schemas: dict[str, DatasetSchema],
    controls_dir: Path,
    force: bool = False,
) -> str:
    """Compile *plan* into SQL and write it to disk.

    Args:
        plan:          DSLPlan for the group.
        schemas:       Map of dataset_id → DatasetSchema.
        controls_dir:  Root controls/ directory.
        force:         If True, overwrite existing compiled.sql.

    Returns:
        The compiled SQL string.
    """
    sql_path = (
        controls_dir / plan.control_id / "groups" / plan.group_id / "compiled.sql"
    )

    if sql_path.exists() and not force:
        log.info(
            f"[{plan.control_id}/{plan.group_id}] compiled.sql exists — "
            "loading (skip recompile)."
        )
        return sql_path.read_text(encoding="utf-8")

    if force and sql_path.exists():
        sql_path.unlink()
        log.info(f"[{plan.control_id}/{plan.group_id}] --force: deleted compiled.sql.")

    log.info(f"[{plan.control_id}/{plan.group_id}] Compiling DSL → SQL ...")

    builder = CTEBuilder()

    for step in plan.steps:
        build_fn = _DISPATCH.get(step.type)
        if build_fn is None:
            raise ValueError(
                f"No compiler registered for primitive type: '{step.type}'"
            )

        cte_block = build_fn(step, schemas)
        alias = getattr(step, "output_alias", step.id)
        builder.add_cte(alias, cte_block)

        result_type = _RESULT_TYPE_MAP.get(step.type)
        if result_type is not None:
            builder.mark_terminal(alias, result_type)

    sql = builder.build()

    # Prepend header comment
    now = datetime.now(timezone.utc).isoformat()
    header = (
        f"-- Compiled by control-monitoring compiler\n"
        f"-- Control: {plan.control_id}\n"
        f"-- Group:   {plan.group_id}\n"
        f"-- Generated: {now}\n"
        f"-- Source DSL: controls/{plan.control_id}/groups/{plan.group_id}/dsl.yaml\n"
        f"-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)\n\n"
    )
    full_sql = header + sql

    ensure_dir(sql_path.parent)
    sql_path.write_text(full_sql, encoding="utf-8")
    log.info(f"[{plan.control_id}/{plan.group_id}] compiled.sql written → {sql_path}")

    return full_sql
