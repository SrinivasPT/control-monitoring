"""Result parser — converts raw DuckDB result rows into typed model objects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from src.models.result import Metric, Violation


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_row_level(
    row: dict[str, Any],
    control_id: str,
    group_id: str,
    severity_map: dict[str, str],
) -> Violation:
    """Parse a row-level / completeness / reconciliation result row."""
    check_id = str(row.get("check_id") or row.get("_check_id") or "unknown")
    reason = str(row.get("reason") or "Violation detected")

    # Exclude internal fields from evidence
    internal = {"result_type", "check_id", "_check_id", "reason", "result_type"}
    evidence = {k: v for k, v in row.items() if k not in internal}

    return Violation(
        control_id=control_id,
        group_id=group_id,
        check_id=check_id,
        severity=severity_map.get(check_id, "medium"),
        reason=reason,
        evidence=evidence,
        detected_at=_now(),
    )


def parse_aggregate(
    row: dict[str, Any],
    control_id: str,
    group_id: str,
    severity_map: dict[str, str],
    control_checks,
) -> Metric:
    """Parse an aggregate result row into a Metric."""
    check_id = str(row.get("check_id") or "unknown")

    # Find threshold from control checks
    threshold_op = None
    threshold_val = None
    passed = bool(row.get("passed", True))

    from src.models.control import CheckDefinition

    for chk in control_checks or []:
        if chk.id == check_id and chk.threshold:
            threshold_op = chk.threshold.operator
            threshold_val = chk.threshold.value
            break

    # Extract metric value (look for common column names)
    metric_name = "result"
    metric_value = None
    supporting_counts: dict[str, Any] = {}

    internal = {"result_type", "check_id", "passed"}
    for k, v in row.items():
        if k in internal:
            continue
        if isinstance(v, (int, float)) and metric_value is None:
            metric_name = k
            metric_value = float(v) if v is not None else None
        elif k not in internal:
            supporting_counts[k] = v

    # If explicit passed column exists, use it
    if "passed" in row:
        passed = bool(row["passed"])
    elif (
        threshold_op is not None
        and metric_value is not None
        and threshold_val is not None
    ):
        passed = _eval_threshold(metric_value, threshold_op, threshold_val)

    return Metric(
        control_id=control_id,
        group_id=group_id,
        check_id=check_id,
        severity=severity_map.get(check_id, "medium"),
        metric_name=metric_name,
        value=metric_value,
        threshold_operator=threshold_op,
        threshold_value=threshold_val,
        passed=passed,
        supporting_counts=supporting_counts,
        evaluated_at=_now(),
    )


def _eval_threshold(value: float, operator: str, threshold: float) -> bool:
    if operator == ">=":
        return value >= threshold
    if operator == ">":
        return value > threshold
    if operator == "<=":
        return value <= threshold
    if operator == "<":
        return value < threshold
    if operator in ("==", "="):
        return value == threshold
    if operator in ("!=", "<>"):
        return value != threshold
    return False
