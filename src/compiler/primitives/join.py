"""JOIN primitive — inner / left / full join on declared keys."""

from __future__ import annotations

from src.models.dsl import JoinStep
from src.models.schema import DatasetSchema


def build_cte(step: JoinStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the JOIN step."""
    join_type = step.join_type.upper()
    lk = step.on.left_key
    rk = step.on.right_key

    body = (
        f"    SELECT l.*, r.*\n"
        f"    FROM {step.left} l\n"
        f"    {join_type} JOIN {step.right} r ON l.{lk} = r.{rk}"
    )

    return (
        f"{step.output_alias} AS (\n"
        f"    -- {step.id}: JOIN {step.left} {join_type} JOIN {step.right} ON {lk} = {rk}\n"
        f"{body}\n"
        f")"
    )
