"""tests/compiler/test_idempotency.py — compile twice yields identical SQL."""

from __future__ import annotations

from src.models.dsl import DSLPlan, FilterStep, JoinStep, NormalizeStep
from src.utils.filesystem import ensure_dir


def _simple_plan(control_id: str, group_id: str) -> DSLPlan:
    return DSLPlan(
        control_id=control_id,
        group_id=group_id,
        generated_at="2026-01-01T00:00:00+00:00",
        generator="test",
        steps=[
            NormalizeStep(
                id="s1", type="NORMALIZE", dataset="hr_roster", output_alias="norm_hr"
            ),
            NormalizeStep(
                id="s2",
                type="NORMALIZE",
                dataset="iam_accounts",
                output_alias="norm_iam",
            ),
            JoinStep(
                id="s3",
                type="JOIN",
                left="norm_hr",
                right="norm_iam",
                on={"left_key": "employee_id", "right_key": "employee_id"},
                join_type="inner",
                output_alias="joined",
            ),
            FilterStep(
                id="s4",
                type="FILTER",
                input="joined",
                conditions=["status = 'TERMINATED'"],
                output_alias="violations",
                check_id="terminated_check",
            ),
        ],
    )


class TestCompilerIdempotency:
    def test_compile_twice_same_sql(self, tmp_path):
        from src.compiler.compiler import compile_group

        plan = _simple_plan("CTL_001", "grp_01")
        controls_dir = tmp_path / "controls"
        ensure_dir(controls_dir / "CTL_001" / "groups" / "grp_01")

        sql_1 = compile_group(plan, schemas={}, controls_dir=controls_dir, force=True)
        sql_2 = compile_group(plan, schemas={}, controls_dir=controls_dir, force=False)

        assert sql_1 == sql_2

    def test_force_overwrite_regenerates(self, tmp_path):
        from src.compiler.compiler import compile_group

        plan = _simple_plan("CTL_002", "grp_01")
        controls_dir = tmp_path / "controls"
        ensure_dir(controls_dir / "CTL_002" / "groups" / "grp_01")

        sql_1 = compile_group(plan, schemas={}, controls_dir=controls_dir, force=True)

        # Force should recompile and produce the same output deterministically
        sql_2 = compile_group(plan, schemas={}, controls_dir=controls_dir, force=True)
        assert sql_1 == sql_2
