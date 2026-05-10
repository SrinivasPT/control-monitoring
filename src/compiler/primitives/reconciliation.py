"""RECONCILIATION primitive — find records in one dataset absent from another."""

from __future__ import annotations

from src.models.dsl import ReconciliationStep
from src.models.schema import DatasetSchema


def build_cte(step: ReconciliationStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the RECONCILIATION step."""
    check_id_val = f"'{step.check_id}'" if step.check_id else "NULL"

    body = (
        f"    SELECT\n"
        f"        l.*,\n"
        f"        {check_id_val} AS check_id,\n"
        f"        'Record present in {step.left} but absent from {step.right}' AS reason\n"
        f"    FROM {step.left} l\n"
        f"    LEFT JOIN {step.right} r ON l.{step.left_key} = r.{step.right_key}\n"
        f"    WHERE r.{step.right_key} IS NULL"
    )

    return (
        f"{step.output_alias} AS (\n"
        f"    -- {step.id}: RECONCILIATION {step.left} vs {step.right} on {step.left_key}\n"
        f"{body}\n"
        f")"
    )
