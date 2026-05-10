"""COMPLETENESS primitive — flag NULL values in a required field."""

from __future__ import annotations

from src.models.dsl import CompletenessStep
from src.models.schema import DatasetSchema


def build_cte(step: CompletenessStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the COMPLETENESS step."""
    check_id_val = f"'{step.check_id}'" if step.check_id else "NULL"

    pre_filter = ""
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
        pre_filter = f"\n    WHERE {step.filter.field} {op_sql} {val_sql}"

    body = (
        f"    SELECT\n"
        f"        *,\n"
        f"        {check_id_val} AS check_id,\n"
        f"        'Required field {step.check_field} is NULL or missing' AS reason\n"
        f"    FROM {step.input}{pre_filter}\n"
        f"    AND {step.check_field} IS NULL"
    )

    # Rewrite: filter and null-check in WHERE
    where_parts = []
    if step.filter:
        op_map2 = {
            "eq": "=",
            "neq": "!=",
            "gt": ">",
            "lt": "<",
            "gte": ">=",
            "lte": "<=",
        }
        op_sql2 = op_map2.get(step.filter.op, step.filter.op)
        val2 = step.filter.value
        val_sql2 = f"'{val2}'" if isinstance(val2, str) else str(val2)
        where_parts.append(f"{step.filter.field} {op_sql2} {val_sql2}")
    where_parts.append(f"{step.check_field} IS NULL")

    where_sql = "\n    AND ".join(where_parts)

    body = (
        f"    SELECT\n"
        f"        *,\n"
        f"        {check_id_val} AS check_id,\n"
        f"        'Required field {step.check_field} is NULL or missing' AS reason\n"
        f"    FROM {step.input}\n"
        f"    WHERE {where_sql}"
    )

    return (
        f"{step.output_alias} AS (\n"
        f"    -- {step.id}: COMPLETENESS check on {step.check_field}\n"
        f"{body}\n"
        f")"
    )
