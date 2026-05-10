"""Pydantic models for the group decomposition manifest (decomposition.yaml)."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class GroupDefinition(BaseModel):
    id: str
    name: str
    description: str
    datasets: list[str]
    checks: list[str] = Field(default_factory=list)  # check IDs
    execution_order: int


class GroupManifest(BaseModel):
    """Contents of controls/<control_id>/decomposition.yaml."""

    control_id: str
    generated_at: str
    generator: Literal["llm", "manual"] = "llm"
    groups: list[GroupDefinition]

    def get_group(self, group_id: str) -> Optional[GroupDefinition]:
        for g in self.groups:
            if g.id == group_id:
                return g
        return None

    def ordered_groups(self) -> list[GroupDefinition]:
        return sorted(self.groups, key=lambda g: g.execution_order)
