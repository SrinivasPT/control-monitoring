"""tests/decomposer/test_validator.py — DSL plan validation rules."""

from __future__ import annotations

import pytest

from src.decomposer.validator import validate_dsl
from src.models.dsl import DSLPlan, FilterStep, NormalizeStep


def _plan(*steps) -> DSLPlan:
    return DSLPlan(
        control_id="CTL_TEST",
        group_id="grp_01",
        generated_at="2026-01-01T00:00:00+00:00",
        generator="test",
        steps=list(steps),
    )


def _norm(alias: str, dataset: str = "hr_roster") -> NormalizeStep:
    return NormalizeStep(
        id=f"s_{alias}", type="NORMALIZE", dataset=dataset, output_alias=alias
    )


def _filter(alias: str, input_alias: str, check_id: str = "chk_01") -> FilterStep:
    return FilterStep(
        id=f"s_{alias}",
        type="FILTER",
        input=input_alias,
        conditions=["status = 'TERMINATED'"],
        output_alias=alias,
        check_id=check_id,
    )


class TestDSLValidator:
    def test_valid_plan_no_errors(self):
        plan = _plan(
            _norm("norm_hr"),
            _filter("violations", "norm_hr"),
        )
        errs = validate_dsl(
            plan,
            allowed_datasets={"hr_roster"},
            allowed_check_ids={"chk_01"},
        )
        assert errs == []

    def test_unknown_input_alias_rejected(self):
        plan = _plan(
            _norm("norm_hr"),
            _filter("violations", "does_not_exist"),
        )
        errs = validate_dsl(
            plan,
            allowed_datasets={"hr_roster"},
            allowed_check_ids={"chk_01"},
        )
        assert len(errs) > 0
        assert any("does_not_exist" in str(e) for e in errs)

    def test_unknown_check_id_rejected(self):
        plan = _plan(
            _norm("norm_hr"),
            _filter("violations", "norm_hr", check_id="NOT_DECLARED"),
        )
        errs = validate_dsl(
            plan,
            allowed_datasets={"hr_roster"},
            allowed_check_ids={"chk_01"},
        )
        assert len(errs) > 0
        assert any("NOT_DECLARED" in str(e) for e in errs)

    def test_undeclared_dataset_rejected(self):
        plan = _plan(_norm("norm_other", dataset="secret_table"))
        errs = validate_dsl(
            plan,
            allowed_datasets={"hr_roster"},
            allowed_check_ids=set(),
        )
        assert len(errs) > 0
        assert any("secret_table" in str(e) for e in errs)

    def test_duplicate_output_aliases_rejected(self):
        plan = _plan(
            _norm("same_alias"),
            _norm("same_alias"),
        )
        errs = validate_dsl(
            plan,
            allowed_datasets={"hr_roster"},
            allowed_check_ids=set(),
        )
        assert len(errs) > 0

    def test_sql_injection_in_condition_rejected(self):
        """Conditions containing raw SQL keywords like DROP/SELECT should be rejected."""
        step = FilterStep(
            id="bad",
            type="FILTER",
            input="norm_hr",
            conditions=["1=1; DROP TABLE hr_roster; --"],
            output_alias="bad_out",
            check_id="chk_01",
        )
        plan = _plan(_norm("norm_hr"), step)
        errs = validate_dsl(
            plan,
            allowed_datasets={"hr_roster"},
            allowed_check_ids={"chk_01"},
        )
        assert len(errs) > 0
