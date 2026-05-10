"""AGGREGATE primitive — compute whole-table or grouped metrics."""

from __future__ import annotations

from src.models.dsl import AggregateStep
from src.models.schema import DatasetSchema


def build_cte(step: AggregateStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the AGGREGATE step."""
    check_id_val = f"'{step.check_id}'" if step.check_id else "NULL"

    metric_exprs = []
    for m in step.metrics:
        filt = f" FILTER (WHERE {m.filter})" if m.filter else ""
        expr = m.formula
        # If formula references other metric names, wrap in a final SELECT — just emit as-is
        metric_exprs.append(f"        {expr}{filt} AS {m.name}")

    metrics_sql = ",\n".join(metric_exprs)

    body = (
        f"    SELECT\n"
        f"        {check_id_val} AS check_id,\n"
        f"{metrics_sql}\n"
        f"    FROM {step.input}"
    )

    return f"{step.output_alias} AS (\n    -- {step.id}: AGGREGATE\n{body}\n)"
