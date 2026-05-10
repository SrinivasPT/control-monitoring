"""tests/runtime/test_result_parser.py — result row parsing."""

from __future__ import annotations

from src.runtime.result_parser import parse_aggregate, parse_row_level

SEVERITY_MAP = {"chk_01": "high", "chk_02": "medium"}


class TestParseRowLevel:
    def test_basic_violation(self):
        row = {
            "result_type": "row_level",
            "check_id": "chk_01",
            "reason": "Terminated employee has active account",
            "employee_id": "E001",
            "status": "TERMINATED",
        }
        v = parse_row_level(row, "CTL_001", "grp_01", SEVERITY_MAP)
        assert v.check_id == "chk_01"
        assert v.severity == "high"
        assert v.reason == "Terminated employee has active account"
        assert v.evidence.get("employee_id") == "E001"
        assert "result_type" not in v.evidence

    def test_fallback_check_id(self):
        row = {"_check_id": "chk_02", "reason": "reason text"}
        v = parse_row_level(row, "CTL_001", "grp_01", SEVERITY_MAP)
        assert v.check_id == "chk_02"

    def test_unknown_check_defaults_to_medium_severity(self):
        row = {"check_id": "unknown_check", "reason": "x"}
        v = parse_row_level(row, "CTL", "grp", SEVERITY_MAP)
        assert v.severity == "medium"

    def test_missing_reason_has_default(self):
        row = {"check_id": "chk_01"}
        v = parse_row_level(row, "CTL", "grp", SEVERITY_MAP)
        assert isinstance(v.reason, str)
        assert len(v.reason) > 0


class TestParseAggregate:
    def test_basic_metric(self):
        row = {
            "result_type": "aggregate",
            "check_id": "chk_02",
            "passed": True,
            "sla_rate": 0.97,
        }
        m = parse_aggregate(row, "CTL_001", "grp_01", SEVERITY_MAP, [])
        assert m.check_id == "chk_02"
        assert m.severity == "medium"
        assert m.passed is True

    def test_failed_metric(self):
        row = {
            "result_type": "aggregate",
            "check_id": "chk_01",
            "passed": False,
            "sla_rate": 0.88,
        }
        m = parse_aggregate(row, "CTL_001", "grp_01", SEVERITY_MAP, [])
        assert m.passed is False
