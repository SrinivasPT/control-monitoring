"""Column normalisation and type coercion for evidence DataFrames."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

import polars as pl

from src.models.schema import ColumnSchema, DatasetSchema


# ---------------------------------------------------------------------------
# Column-name sanitisation
# ---------------------------------------------------------------------------


def sanitize_column_name(name: str) -> str:
    """Convert a raw column header to a clean SQL-safe identifier.

    Rules (applied in order):
    1. Strip leading/trailing whitespace.
    2. Lowercase.
    3. Replace spaces, hyphens, dots with underscores.
    4. Strip non-alphanumeric-underscore characters.
    5. Collapse consecutive underscores to one.
    6. Strip leading/trailing underscores.
    7. Prefix with ``col_`` if the result starts with a digit.
    """
    s = name.strip().lower()
    s = re.sub(r"[\s\-\.]", "_", s)
    s = re.sub(r"[^\w]", "", s)  # \w = [a-zA-Z0-9_]
    s = re.sub(r"_+", "_", s)
    s = s.strip("_")
    if s and s[0].isdigit():
        s = "col_" + s
    return s or "col"


def deduplicate_headers(headers: list[str]) -> list[str]:
    """Ensure all headers are unique by appending _1, _2 etc. to duplicates."""
    seen: dict[str, int] = {}
    result: list[str] = []
    for h in headers:
        if h not in seen:
            seen[h] = 0
            result.append(h)
        else:
            seen[h] += 1
            result.append(f"{h}_{seen[h]}")
    return result


# ---------------------------------------------------------------------------
# Type inference helpers
# ---------------------------------------------------------------------------

DATE_FORMATS = ["%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d", "%d/%m/%Y"]
NULL_STRINGS = {"", "n/a", "null", "none", "-"}


def _looks_like_date(series: pl.Series) -> bool:
    """Heuristic: does a string series look like it contains dates?"""
    non_null = series.drop_nulls()
    if len(non_null) == 0:
        return False
    sample = non_null.head(min(50, len(non_null))).to_list()
    hits = 0
    for val in sample:
        s = str(val).strip()
        if s.lower() in NULL_STRINGS:
            continue
        for fmt in DATE_FORMATS:
            try:
                datetime.strptime(s, fmt)
                hits += 1
                break
            except ValueError:
                pass
    return hits / max(len(sample), 1) >= 0.7


def _try_parse_date(series: pl.Series) -> Optional[pl.Series]:
    """Try each date format; return a Date series on success."""
    for fmt in DATE_FORMATS:
        try:
            parsed = series.str.strptime(pl.Date, fmt, strict=False)
            # Accept if at least 60% of non-null values parse successfully
            non_null_in = series.drop_nulls().len()
            non_null_out = parsed.drop_nulls().len()
            if non_null_in > 0 and non_null_out / non_null_in >= 0.6:
                return parsed
        except Exception:
            pass
    return None


def _infer_type_name(series: pl.Series) -> str:
    """Infer a schema type string for a Polars series."""
    dtype = series.dtype
    if dtype == pl.Date:
        return "date"
    if dtype == pl.Datetime:
        return "datetime"
    if dtype in (
        pl.Int8,
        pl.Int16,
        pl.Int32,
        pl.Int64,
        pl.UInt8,
        pl.UInt16,
        pl.UInt32,
        pl.UInt64,
    ):
        return "integer"
    if dtype in (pl.Float32, pl.Float64):
        return "float"
    if dtype == pl.Boolean:
        return "boolean"
    # String — check for date content
    if dtype == pl.Utf8 and _looks_like_date(series):
        return "date"
    return "string"


# ---------------------------------------------------------------------------
# Main normalisation entry point
# ---------------------------------------------------------------------------


def normalize_dataframe(
    df: pl.DataFrame,
    dataset_id: str,
    source_file: str,
    existing_schema: Optional[DatasetSchema] = None,
    null_strings: Optional[list[str]] = None,
) -> tuple[pl.DataFrame, DatasetSchema]:
    """Normalise a raw DataFrame and produce a DatasetSchema.

    Steps:
    1. Sanitize column names and deduplicate.
    2. Replace null-string values with real nulls.
    3. Trim whitespace from string columns.
    4. Infer or apply type coercions (dates, numerics).

    Args:
        df:              Raw DataFrame from the reader.
        dataset_id:      Identifier for this dataset.
        source_file:     Relative path to the source file (recorded in schema).
        existing_schema: If provided, use this schema for type coercions
                         instead of inferring.
        null_strings:    List of string values to treat as NULL.

    Returns:
        ``(normalized_df, schema)`` tuple.
    """
    if null_strings is None:
        null_strings = ["", "N/A", "NULL", "null", "None", "NONE", "-"]

    # Step 1: Sanitize column names
    raw_headers = df.columns
    sanitized = [sanitize_column_name(h) for h in raw_headers]
    sanitized = deduplicate_headers(sanitized)

    rename_map = dict(zip(raw_headers, sanitized))
    df = df.rename(rename_map)

    # Step 2 & 3: Process each column
    schema_columns: list[ColumnSchema] = []
    transformed: dict[str, pl.Series] = {}

    null_set_lower = {s.lower() for s in null_strings}

    for i, col in enumerate(df.columns):
        raw_name = raw_headers[i]
        series = df[col]

        # Replace null-string tokens with actual nulls for string columns
        if series.dtype == pl.Utf8:
            series = series.map_elements(
                lambda v, ns=null_set_lower: None
                if (v is not None and str(v).strip().lower() in ns)
                else v,
                return_dtype=pl.Utf8,
            )
            # Trim whitespace
            series = series.str.strip_chars()

        # Determine target type
        if existing_schema:
            sc = existing_schema.get_column(col)
            target_type = sc.type if sc else _infer_type_name(series)
        else:
            target_type = _infer_type_name(series)

        # Apply coercions
        if target_type == "date" and series.dtype == pl.Utf8:
            parsed = _try_parse_date(series)
            if parsed is not None:
                series = parsed
            else:
                target_type = "string"  # fallback

        elif target_type == "integer" and series.dtype == pl.Utf8:
            series = series.cast(pl.Int64, strict=False)

        elif target_type == "float" and series.dtype == pl.Utf8:
            series = series.cast(pl.Float64, strict=False)

        # Re-detect after coercion
        if series.dtype == pl.Date:
            target_type = "date"
        elif series.dtype == pl.Datetime:
            target_type = "datetime"
        elif series.dtype in (
            pl.Int8,
            pl.Int16,
            pl.Int32,
            pl.Int64,
            pl.UInt8,
            pl.UInt16,
            pl.UInt32,
            pl.UInt64,
        ):
            target_type = "integer"
        elif series.dtype in (pl.Float32, pl.Float64):
            target_type = "float"
        elif series.dtype == pl.Boolean:
            target_type = "boolean"
        else:
            target_type = "string"

        nullable = series.null_count() > 0 or series.dtype != pl.Boolean

        schema_columns.append(
            ColumnSchema(
                source_name=raw_name,
                normalized_name=col,
                type=target_type,
                nullable=nullable,
            )
        )
        transformed[col] = series

    normalized_df = pl.DataFrame(transformed)

    schema = DatasetSchema(
        dataset_id=dataset_id,
        source_file=source_file,
        generated_at=datetime.now(timezone.utc).isoformat(),
        columns=schema_columns,
    )

    return normalized_df, schema
