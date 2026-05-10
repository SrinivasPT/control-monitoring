"""DATE_DIFF primitive — compute integer date difference."""

from __future__ import annotations

from src.models.dsl import DateDiffStep
from src.models.schema import DatasetSchema


_UNIT_MAP = {
    "days": "day",
    "day": "day",
    "hours": "hour",
    "hour": "hour",
    "months": "month",
    "month": "month",
    "years": "year",
    "year": "year",
}


def build_cte(step: DateDiffStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the DATE_DIFF step."""
    unit = _UNIT_MAP.get(step.unit.lower(), "day")
    diff_col = f"{step.from_field}_to_{step.to_field}_{unit}s"

    where_clause = ""
    if step.filter:
        op_map = {
            "eq": "=",
            "neq": "!=",
            "gt": ">",
            "lt": "<",
            "gte": ">=",
            "lte": "<=",
        }
        op_sql = op_map.get(step.filter.op, step.filter.op)
        val = step.filter.value
        val_sql = f"'{val}'" if isinstance(val, str) else str(val)
        where_clause = f"\n    WHERE {step.filter.field} {op_sql} {val_sql}"

    body = (
        f"    SELECT\n"
        f"        *,\n"
        f"        DATE_DIFF('{unit}', {step.from_field}, {step.to_field}) AS {diff_col}\n"
        f"    FROM {step.input}{where_clause}"
    )

    return (
        f"{step.output_alias} AS (\n"
        f"    -- {step.id}: DATE_DIFF {step.from_field} → {step.to_field} ({unit}s)\n"
        f"{body}\n"
        f")"
    )
