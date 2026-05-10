"""FILTER primitive — apply WHERE conditions and tag with check_id."""

from __future__ import annotations

from src.models.dsl import FilterStep
from src.models.schema import DatasetSchema


def build_cte(step: FilterStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the FILTER step."""
    conditions_sql = "\n      AND ".join(step.conditions)

    check_annotation = ""
    if step.check_id:
        check_annotation = (
            f"\n        '{step.check_id}' AS check_id,"
            f"\n        'Violation detected by {step.check_id}' AS reason,"
        )

    body = (
        f"    SELECT\n"
        f"        *,{check_annotation}\n"
        f"        '{step.check_id or ''}' AS _check_id\n"
        f"    FROM {step.input}\n"
        f"    WHERE {conditions_sql}"
    )

    label = f" (check: {step.check_id})" if step.check_id else ""
    return f"{step.output_alias} AS (\n    -- {step.id}: FILTER{label}\n{body}\n)"
