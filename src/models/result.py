"""Pydantic models for execution results."""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class Violation(BaseModel):
    """A single row-level, completeness, or reconciliation violation."""

    control_id: str
    group_id: str
    check_id: str
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    reason: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    detected_at: str


class Metric(BaseModel):
    """An aggregate check result."""

    control_id: str
    group_id: str
    check_id: str
    severity: Literal["critical", "high", "medium", "low"] = "medium"
    metric_name: str
    value: Optional[float] = None
    threshold_operator: Optional[str] = None
    threshold_value: Optional[float] = None
    passed: bool
    supporting_counts: dict[str, Any] = Field(default_factory=dict)
    evaluated_at: str


class CheckEvaluated(BaseModel):
    check_id: str
    type: str
    violation_count: Optional[int] = None
    passed: Optional[bool] = None
    # Additional fields for metric checks
    extra: dict[str, Any] = Field(default_factory=dict)


class DatasetUsed(BaseModel):
    id: str
    sha256: str
    row_count: int


class GroupAuditEntry(BaseModel):
    group_id: str
    execution_order: int
    compiled_sql_path: str
    compiled_sql_sha256: str
    manual_edit_warning: bool = False
    datasets_used: list[DatasetUsed] = Field(default_factory=list)
    execution_duration_ms: int
    status: Literal["success", "error", "skipped"]
    error_message: Optional[str] = None
    violation_count: int = 0
    checks_evaluated: list[CheckEvaluated] = Field(default_factory=list)


class AuditRecord(BaseModel):
    """Top-level audit output for a control execution."""

    control_id: str
    executed_at: str
    executor_version: str = "1.0"
    total_violation_count: int
    total_groups: int
    groups: list[GroupAuditEntry] = Field(default_factory=list)
