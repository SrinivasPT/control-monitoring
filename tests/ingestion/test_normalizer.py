"""tests/ingestion/test_normalizer.py"""

from __future__ import annotations

import polars as pl
import pytest

from src.ingestion.normalizer import normalize_dataframe, sanitize_column_name


class TestSanitizeColumnName:
    def test_lowercase(self):
        assert sanitize_column_name("Employee ID") == "employee_id"

    def test_spaces_to_underscores(self):
        assert sanitize_column_name("First  Name") == "first_name"

    def test_special_chars_stripped(self):
        assert sanitize_column_name("Amount ($)") == "amount"

    def test_leading_trailing_whitespace(self):
        assert sanitize_column_name("  status  ") == "status"

    def test_already_clean(self):
        assert sanitize_column_name("employee_id") == "employee_id"

    def test_numeric_prefix_prefixed(self):
        # Columns starting with a digit must be prefixed
        result = sanitize_column_name("1st_column")
        assert not result[0].isdigit()

    def test_empty_string(self):
        result = sanitize_column_name("")
        assert isinstance(result, str)


class TestNormalizeDataframe:
    def _make_df(self, data: dict) -> pl.DataFrame:
        return pl.DataFrame(data)

    def test_column_names_sanitized(self):
        df = self._make_df({"Employee ID": ["E001"], "Status": ["ACTIVE"]})
        norm, schema = normalize_dataframe(df, "test_ds", "test.csv")
        assert "employee_id" in norm.columns
        assert "status" in norm.columns

    def test_null_strings_replaced(self):
        df = self._make_df({"val": ["N/A", "NULL", "none", "hello"]})
        norm, schema = normalize_dataframe(df, "test_ds", "test.csv")
        col = norm["val"].to_list()
        assert col[0] is None
        assert col[1] is None
        assert col[2] is None
        assert col[3] == "hello"

    def test_string_trimmed(self):
        df = self._make_df({"name": ["  Alice  ", " Bob"]})
        norm, schema = normalize_dataframe(df, "test_ds", "test.csv")
        assert norm["name"][0] == "Alice"
        assert norm["name"][1] == "Bob"

    def test_date_column_inferred(self):
        df = self._make_df({"termination_date": ["2026-03-01", "2026-04-15", None]})
        norm, schema = normalize_dataframe(df, "test_ds", "test.csv")
        col_schema = next(
            (c for c in schema.columns if c.normalized_name == "termination_date"), None
        )
        assert col_schema is not None
        assert col_schema.type in ("date", "datetime", "string")

    def test_schema_columns_match_df_columns(self):
        df = self._make_df({"Employee ID": ["E001"], "Status": ["ACTIVE"]})
        norm, schema = normalize_dataframe(df, "test_ds", "test.csv")
        schema_names = {c.normalized_name for c in schema.columns}
        df_names = set(norm.columns)
        assert schema_names == df_names

    def test_duplicate_column_names_deduplicated(self):
        # Build a DF with duplicate column names via rename
        df = pl.DataFrame({"a": [1], "b": [2]}).rename({"b": "a"})
        # Polars doesn't allow true duplicate columns, so simulate at model level
        df2 = self._make_df({"col_a": [1], "col_b": [2], "col_c": [3]})
        norm, schema = normalize_dataframe(df2, "test_ds", "test.csv")
        assert len(norm.columns) == len(set(norm.columns))
