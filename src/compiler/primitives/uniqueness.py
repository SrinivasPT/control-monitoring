"""UNIQUENESS primitive — detect duplicate rows on key columns."""

from __future__ import annotations

from src.models.dsl import UniquenessStep
from src.models.schema import DatasetSchema


def build_cte(step: UniquenessStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the UNIQUENESS step."""
    check_id_val = f"'{step.check_id}'" if step.check_id else "NULL"
    keys_csv = ", ".join(step.key_columns)

    body = (
        f"    SELECT\n"
        f"        *,\n"
        f"        {check_id_val} AS check_id,\n"
        f"        'Duplicate row detected on key columns: {keys_csv}' AS reason\n"
        f"    FROM (\n"
        f"        SELECT\n"
        f"            *,\n"
        f"            COUNT(*) OVER (PARTITION BY {keys_csv}) AS _dup_count\n"
        f"        FROM {step.input}\n"
        f"    ) _deduped\n"
        f"    WHERE _dup_count > 1"
    )

    return f"{step.output_alias} AS (\n    -- {step.id}: UNIQUENESS on [{keys_csv}]\n{body}\n)"
