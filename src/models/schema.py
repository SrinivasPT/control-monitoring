"""Pydantic models for dataset schema (data/schemas/<dataset>.schema.yaml)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class ColumnSchema(BaseModel):
    source_name: str
    normalized_name: str
    type: Literal["string", "integer", "float", "date", "datetime", "boolean"]
    nullable: bool = True
    date_formats_tried: Optional[list[str]] = None


class DatasetSchema(BaseModel):
    """Contents of data/schemas/<dataset_id>.schema.yaml."""

    dataset_id: str
    source_file: str
    generated_at: str
    columns: list[ColumnSchema] = Field(default_factory=list)

    def get_column(self, normalized_name: str) -> Optional[ColumnSchema]:
        for col in self.columns:
            if col.normalized_name == normalized_name:
                return col
        return None
