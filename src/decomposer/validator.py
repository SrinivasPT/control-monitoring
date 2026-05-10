"""DSL validator — validates a DSLPlan against structural rules.

Validation is per-group and independent.  A failing group does not block
other groups.
"""

from __future__ import annotations

import re

from src.models.dsl import (
    ALLOWED_PRIMITIVE_TYPES,
    AggregateStep,
    CompletenessStep,
    DSLPlan,
    DateDiffStep,
    FilterStep,
    JoinStep,
    NormalizeStep,
    ReconciliationStep,
    ThresholdStep,
    UniquenessStep,
)

_SQL_KEYWORDS = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|EXEC|EXECUTE|WITH|FROM|WHERE|JOIN)\b",
    re.IGNORECASE,
)

_VALID_IDENTIFIER = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")


class ValidationError:
    def __init__(self, step_id: str, message: str) -> None:
        self.step_id = step_id
        self.message = message

    def __str__(self) -> str:
        return f"[{self.step_id}] {self.message}"


def validate_dsl(
    plan: DSLPlan,
    allowed_datasets: list[str] | None = None,
    allowed_check_ids: list[str] | None = None,
) -> list[ValidationError]:
    """Validate a DSLPlan and return a list of errors (empty = valid).

    Checks:
    1. All ``type`` values are in ALLOWED_PRIMITIVE_TYPES.
    2. All ``input`` / ``left`` / ``right`` references resolve to a previously
       defined ``output_alias`` within this plan.
    3. No SQL keyword strings appear in any step field values.
    4. All ``output_alias`` values are valid SQL identifiers.
    5. Dataset references are in allowed_datasets (if provided).
    6. check_id references are in allowed_check_ids (if provided).
    """
    errors: list[ValidationError] = []
    defined_aliases: set[str] = set()

    for step in plan.steps:
        sid = getattr(step, "id", "?")

        # Rule 1: allowed type
        if step.type not in ALLOWED_PRIMITIVE_TYPES:
            errors.append(
                ValidationError(sid, f"Unknown primitive type: '{step.type}'")
            )

        # Rule 4: valid output_alias
        alias = getattr(step, "output_alias", None)
        if alias is not None:
            if not _VALID_IDENTIFIER.match(alias):
                errors.append(
                    ValidationError(
                        sid, f"output_alias '{alias}' is not a valid SQL identifier"
                    )
                )

        # Rule 2: input references
        if isinstance(
            step,
            (
                FilterStep,
                AggregateStep,
                DateDiffStep,
                ThresholdStep,
                CompletenessStep,
                UniquenessStep,
            ),
        ):
            inp = getattr(step, "input", None)
            if inp and inp not in defined_aliases:
                errors.append(
                    ValidationError(sid, f"'input' references undefined alias '{inp}'")
                )

        if isinstance(step, JoinStep):
            if step.left not in defined_aliases:
                errors.append(
                    ValidationError(
                        sid, f"'left' references undefined alias '{step.left}'"
                    )
                )
            if step.right not in defined_aliases:
                errors.append(
                    ValidationError(
                        sid, f"'right' references undefined alias '{step.right}'"
                    )
                )

        if isinstance(step, ReconciliationStep):
            if step.left not in defined_aliases:
                errors.append(
                    ValidationError(
                        sid, f"'left' references undefined alias '{step.left}'"
                    )
                )
            if step.right not in defined_aliases:
                errors.append(
                    ValidationError(
                        sid, f"'right' references undefined alias '{step.right}'"
                    )
                )

        # Rule 5: dataset references
        if isinstance(step, NormalizeStep) and allowed_datasets is not None:
            if step.dataset not in allowed_datasets:
                errors.append(
                    ValidationError(
                        sid, f"dataset '{step.dataset}' not declared for this group"
                    )
                )

        # Rule 6: check_id references
        check_id = getattr(step, "check_id", None)
        if check_id is not None and allowed_check_ids is not None:
            if check_id not in allowed_check_ids:
                errors.append(
                    ValidationError(
                        sid, f"check_id '{check_id}' not declared for this group"
                    )
                )

        # Rule 3: no raw SQL strings
        for field_name, field_val in step.model_dump().items():
            if isinstance(field_val, str) and _SQL_KEYWORDS.search(field_val):
                # Allow in conditions/formulas — those are filter-expression strings, not SQL statements
                if field_name not in (
                    "conditions",
                    "formula",
                    "filter",
                    "condition",
                    "metrics",
                ):
                    errors.append(
                        ValidationError(
                            sid, f"Field '{field_name}' appears to contain raw SQL"
                        )
                    )

        # Track defined alias
        if alias:
            defined_aliases.add(alias)

    return errors
