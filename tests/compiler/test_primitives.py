"""tests/compiler/test_primitives.py — CTE SQL output correctness."""

from __future__ import annotations

import pytest

from src.models.dsl import (
    AggregateStep,
    CompletenessStep,
    DateDiffStep,
    FilterStep,
    JoinStep,
    NormalizeStep,
    ReconciliationStep,
    ThresholdStep,
    UniquenessStep,
)


def _sql(step, schemas=None) -> str:
    """Dispatch to the right build_cte and return normalized SQL."""
    t = step.type

    if t == "NORMALIZE":
        from src.compiler.primitives.normalize import build_cte
    elif t == "JOIN":
        from src.compiler.primitives.join import build_cte
    elif t == "FILTER":
        from src.compiler.primitives.filter import build_cte
    elif t == "AGGREGATE":
        from src.compiler.primitives.aggregate import build_cte
    elif t == "DATE_DIFF":
        from src.compiler.primitives.date_diff import build_cte
    elif t == "THRESHOLD":
        from src.compiler.primitives.threshold import build_cte
    elif t == "COMPLETENESS":
        from src.compiler.primitives.completeness import build_cte
    elif t == "UNIQUENESS":
        from src.compiler.primitives.uniqueness import build_cte
    elif t == "RECONCILIATION":
        from src.compiler.primitives.reconciliation import build_cte
    else:
        raise ValueError(f"Unknown type: {t}")

    return build_cte(step, schemas or {})


class TestNormalizeCTE:
    def test_fallback_without_schema(self):
        step = NormalizeStep(
            id="s1", type="NORMALIZE", dataset="hr_roster", output_alias="norm_hr"
        )
        sql = _sql(step)
        assert "SELECT *" in sql or "select *" in sql.lower()
        assert "hr_roster" in sql

    def test_produces_string_not_empty(self):
        step = NormalizeStep(
            id="s1", type="NORMALIZE", dataset="iam_accounts", output_alias="norm_iam"
        )
        sql = _sql(step)
        assert len(sql.strip()) > 0


class TestJoinCTE:
    def test_inner_join_syntax(self):
        step = JoinStep(
            id="s1",
            type="JOIN",
            left="norm_hr",
            right="norm_iam",
            on={"left_key": "employee_id", "right_key": "employee_id"},
            join_type="inner",
            output_alias="joined",
        )
        sql = _sql(step)
        assert "JOIN" in sql.upper()
        assert "norm_hr" in sql
        assert "norm_iam" in sql
        assert "employee_id" in sql

    def test_left_join_uses_left_keyword(self):
        step = JoinStep(
            id="s1",
            type="JOIN",
            left="a",
            right="b",
            on={"left_key": "id", "right_key": "id"},
            join_type="left",
            output_alias="out",
        )
        sql = _sql(step)
        assert "LEFT" in sql.upper()


class TestFilterCTE:
    def test_where_clause_present(self):
        step = FilterStep(
            id="s1",
            type="FILTER",
            input="joined",
            conditions=["status = 'TERMINATED'", "account_status = 'ACTIVE'"],
            output_alias="filtered",
            check_id="check_01",
        )
        sql = _sql(step)
        assert "WHERE" in sql.upper()
        assert "TERMINATED" in sql
        assert "ACTIVE" in sql

    def test_check_id_column_present(self):
        step = FilterStep(
            id="s1",
            type="FILTER",
            input="joined",
            conditions=["status = 'TERMINATED'"],
            output_alias="filtered",
            check_id="my_check",
        )
        sql = _sql(step)
        assert "my_check" in sql


class TestAggregateCTE:
    def test_count_metric(self):
        step = AggregateStep(
            id="s1",
            type="AGGREGATE",
            input="sla_evaluated",
            output_alias="agg",
            check_id="sla_check",
            metrics=[{"name": "total", "formula": "COUNT(*)"}],
        )
        sql = _sql(step)
        assert "COUNT(*)" in sql
        assert "sla_check" in sql

    def test_multiple_metrics(self):
        step = AggregateStep(
            id="s1",
            type="AGGREGATE",
            input="data",
            output_alias="agg",
            check_id="c1",
            metrics=[
                {"name": "n", "formula": "COUNT(*)"},
                {"name": "total", "formula": "SUM(amount)"},
            ],
        )
        sql = _sql(step)
        assert "COUNT(*)" in sql
        assert "SUM(amount)" in sql


class TestDateDiffCTE:
    def test_date_diff_column_added(self):
        step = DateDiffStep(
            id="s1",
            type="DATE_DIFF",
            input="joined",
            from_field="termination_date",
            to_field="last_modified",
            unit="days",
            output_alias="diffs",
        )
        sql = _sql(step)
        upper = sql.upper()
        assert (
            "DATE_DIFF" in upper
            or "DATEDIFF" in upper
            or "EPOCH" in upper
            or "day" in sql.lower()
        )
        assert "termination_date" in sql
        assert "last_modified" in sql


class TestThresholdCTE:
    def test_flag_column_added(self):
        step = ThresholdStep(
            id="s1",
            type="THRESHOLD",
            input="diffs",
            condition="days_diff <= 7",
            flag_field="within_sla",
            output_alias="evaluated",
        )
        sql = _sql(step)
        assert "within_sla" in sql
        assert "days_diff" in sql


class TestCompletenessCTE:
    def test_null_check_present(self):
        step = CompletenessStep(
            id="s1",
            type="COMPLETENESS",
            input="norm_hr",
            check_field="termination_date",
            output_alias="missing_dates",
            check_id="check_completeness",
        )
        sql = _sql(step)
        assert "IS NULL" in sql.upper()
        assert "termination_date" in sql

    def test_pre_filter_applied(self):
        step = CompletenessStep(
            id="s1",
            type="COMPLETENESS",
            input="norm_hr",
            check_field="termination_date",
            filter={"field": "status", "op": "eq", "value": "TERMINATED"},
            output_alias="missing_dates",
            check_id="check_c",
        )
        sql = _sql(step)
        assert "TERMINATED" in sql
        assert "IS NULL" in sql.upper()


class TestUniquenessCTE:
    def test_window_function_present(self):
        step = UniquenessStep(
            id="s1",
            type="UNIQUENESS",
            input="norm_hr",
            key_fields=["employee_id"],
            output_alias="dupes",
            check_id="check_u",
        )
        sql = _sql(step)
        upper = sql.upper()
        assert "PARTITION BY" in upper
        assert "employee_id" in sql


class TestReconciliationCTE:
    def test_left_join_null_check(self):
        step = ReconciliationStep(
            id="s1",
            type="RECONCILIATION",
            left="hr_roster",
            right="iam_accounts",
            on={"left_key": "employee_id", "right_key": "employee_id"},
            output_alias="unmatched",
            check_id="check_r",
        )
        sql = _sql(step)
        upper = sql.upper()
        assert "LEFT" in upper
        assert "IS NULL" in upper
