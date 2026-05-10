"""NORMALIZE primitive — sanitize, cast, and trim a dataset view."""

from __future__ import annotations

from src.models.dsl import NormalizeStep
from src.models.schema import DatasetSchema


def build_cte(step: NormalizeStep, schemas: dict[str, DatasetSchema]) -> str:
    """Return a SQL CTE block for the NORMALIZE step.

    If a schema is available for the dataset, each column is explicitly
    cast to the right type and strings are trimmed.  Otherwise a simple
    ``SELECT *`` fallback is used.
    """
    schema = schemas.get(step.dataset)

    if not schema or not schema.columns:
        # Fallback: pass-through
        body = f"    SELECT * FROM {step.dataset}"
    else:
        col_exprs = []
        for col in schema.columns:
            n = col.normalized_name
            t = col.type

            if t == "string":
                col_exprs.append(f"        TRIM({n}) AS {n}")
            elif t == "date":
                col_exprs.append(f"        TRY_CAST({n} AS DATE) AS {n}")
            elif t == "datetime":
                col_exprs.append(f"        TRY_CAST({n} AS TIMESTAMP) AS {n}")
            elif t == "integer":
                col_exprs.append(f"        TRY_CAST({n} AS BIGINT) AS {n}")
            elif t == "float":
                col_exprs.append(f"        TRY_CAST({n} AS DOUBLE) AS {n}")
            elif t == "boolean":
                col_exprs.append(f"        TRY_CAST({n} AS BOOLEAN) AS {n}")
            else:
                col_exprs.append(f"        {n}")

        cols_sql = ",\n".join(col_exprs)
        body = f"    SELECT\n{cols_sql}\n    FROM {step.dataset}"

    return (
        f"{step.output_alias} AS (\n"
        f"    -- {step.id}: NORMALIZE {step.dataset}\n"
        f"{body}\n"
        f")"
    )
