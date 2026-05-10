"""Pydantic models for control definition (control.yaml)."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field


class JoinDefinition(BaseModel):
    left: str
    right: str
    type: Literal["inner", "left", "full"] = "inner"


class CheckCondition(BaseModel):
    field: str
    op: str
    value: Union[str, float, int, bool]


class MetricDefinition(BaseModel):
    numerator: str
    denominator: str


class ThresholdDefinition(BaseModel):
    operator: str
    value: float


class FilterDefinition(BaseModel):
    field: str
    op: str
    value: Union[str, float, int]


class DatasetDefinition(BaseModel):
    id: str
    description: Optional[str] = None
    file: str
    sheet: Optional[str] = None
    required_columns: Optional[list[str]] = None


class CheckDefinition(BaseModel):
    id: str
    type: Literal[
        "row_level", "aggregate", "completeness", "reconciliation", "temporal"
    ]
    description: str
    conditions: Optional[list[CheckCondition]] = None
    join: Optional[JoinDefinition] = None
    metric: Optional[MetricDefinition] = None
    threshold: Optional[ThresholdDefinition] = None
    sla_days: Optional[int] = None
    dataset: Optional[str] = None
    filter: Optional[FilterDefinition] = None
    check_field: Optional[str] = None
    severity: Literal["critical", "high", "medium", "low"] = "medium"


class ControlMeta(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    version: str = "1.0"
    owner: Optional[str] = None
    tags: list[str] = Field(default_factory=list)


class ControlFile(BaseModel):
    """Top-level structure of controls/<id>/control.yaml."""

    control: ControlMeta
    datasets: list[DatasetDefinition]
    checks: list[CheckDefinition]

    def get_check(self, check_id: str) -> Optional[CheckDefinition]:
        for c in self.checks:
            if c.id == check_id:
                return c
        return None

    def get_dataset(self, dataset_id: str) -> Optional[DatasetDefinition]:
        for d in self.datasets:
            if d.id == dataset_id:
                return d
        return None
