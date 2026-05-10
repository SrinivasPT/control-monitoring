"""Pydantic models for per-group DSL plans (groups/<id>/dsl.yaml).

Each supported primitive type has its own model. The ``PrimitiveStep``
union uses Pydantic's discriminated-union mechanism so that YAML/dict
parsing dispatches to the correct model based on the ``type`` field.
"""

from __future__ import annotations

from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Shared sub-models
# ---------------------------------------------------------------------------


class JoinKey(BaseModel):
    left_key: str
    right_key: str


class FilterConditionDef(BaseModel):
    field: str
    op: str
    value: Union[str, float, int]


class AggregateMetric(BaseModel):
    name: str
    formula: str
    filter: Optional[str] = None


# ---------------------------------------------------------------------------
# Primitive step models
# ---------------------------------------------------------------------------


class NormalizeStep(BaseModel):
    id: str
    type: Literal["NORMALIZE"]
    dataset: str
    output_alias: str


class JoinStep(BaseModel):
    id: str
    type: Literal["JOIN"]
    left: str
    right: str
    on: JoinKey
    join_type: Literal["inner", "left", "full"] = "inner"
    output_alias: str


class FilterStep(BaseModel):
    id: str
    type: Literal["FILTER"]
    input: str
    conditions: list[str]
    output_alias: str
    check_id: Optional[str] = None


class AggregateStep(BaseModel):
    id: str
    type: Literal["AGGREGATE"]
    input: str
    metrics: list[AggregateMetric]
    output_alias: str = "agg_metrics"
    check_id: Optional[str] = None


class DateDiffStep(BaseModel):
    id: str
    type: Literal["DATE_DIFF"]
    input: str
    from_field: str
    to_field: str
    unit: str = "days"
    output_alias: str
    filter: Optional[FilterConditionDef] = None


class ThresholdStep(BaseModel):
    id: str
    type: Literal["THRESHOLD"]
    input: str
    condition: str
    flag_field: str
    output_alias: str


class CompletenessStep(BaseModel):
    id: str
    type: Literal["COMPLETENESS"]
    input: str
    check_field: str
    filter: Optional[FilterConditionDef] = None
    output_alias: str
    check_id: Optional[str] = None


class UniquenessStep(BaseModel):
    id: str
    type: Literal["UNIQUENESS"]
    input: str
    key_columns: list[str]
    output_alias: str
    check_id: Optional[str] = None


class ReconciliationStep(BaseModel):
    id: str
    type: Literal["RECONCILIATION"]
    left: str
    right: str
    left_key: str
    right_key: str
    output_alias: str
    check_id: Optional[str] = None


# Discriminated union — Pydantic dispatches on the ``type`` field
PrimitiveStep = Annotated[
    Union[
        NormalizeStep,
        JoinStep,
        FilterStep,
        AggregateStep,
        DateDiffStep,
        ThresholdStep,
        CompletenessStep,
        UniquenessStep,
        ReconciliationStep,
    ],
    Field(discriminator="type"),
]

ALLOWED_PRIMITIVE_TYPES = {
    "NORMALIZE",
    "JOIN",
    "FILTER",
    "AGGREGATE",
    "DATE_DIFF",
    "THRESHOLD",
    "COMPLETENESS",
    "UNIQUENESS",
    "RECONCILIATION",
}


class DSLPlan(BaseModel):
    """Contents of controls/<control_id>/groups/<group_id>/dsl.yaml."""

    control_id: str
    group_id: str
    generated_at: str
    generator: Literal["llm", "manual"] = "llm"
    steps: list[PrimitiveStep]
