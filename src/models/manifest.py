"""Pydantic models for the build manifest (build_manifest.json)."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class GroupManifestEntry(BaseModel):
    group_id: str
    dsl_file: str
    dsl_sha256: str
    compiled_sql_file: str
    compiled_sql_sha256: str
    datasets_required: list[str]
    checks: list[str]


class BuildManifest(BaseModel):
    """Contents of controls/<control_id>/build_manifest.json."""

    control_id: str
    built_at: str
    group_manifest_file: str
    group_manifest_sha256: str
    groups: list[GroupManifestEntry] = Field(default_factory=list)
    generator_version: str = "1.0"

    def get_group(self, group_id: str) -> Optional[GroupManifestEntry]:
        for g in self.groups:
            if g.group_id == group_id:
                return g
        return None
