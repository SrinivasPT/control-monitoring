"""THRESHOLD primitive — apply a numeric comparison, emit boolean flag."""

from __future__ import annotations

from src.models.dsl import ThresholdStep
from src.models.schema import DatasetSchema


def build_cte(step: ThresholdStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the THRESHOLD step."""
    body = (
        f"    SELECT\n"
        f"        *,\n"
        f"        ({step.condition}) AS {step.flag_field}\n"
        f"    FROM {step.input}"
    )

    return (
        f"{step.output_alias} AS (\n"
        f"    -- {step.id}: THRESHOLD — {step.condition}\n"
        f"{body}\n"
        f")"
    )
