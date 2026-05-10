"""Application settings loader.

Loads ``config/settings.yaml`` relative to the project root and exposes
a typed ``Settings`` model.  The project root is auto-detected as the
nearest ancestor directory containing ``config/settings.yaml``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, Field


def _find_project_root() -> Path:
    """Walk upward from cwd until we find config/settings.yaml."""
    cwd = Path(os.getcwd()).resolve()
    for parent in [cwd, *cwd.parents]:
        if (parent / "config" / "settings.yaml").exists():
            return parent
    # Fallback: use cwd
    return cwd


class PathsConfig(BaseModel):
    input_dir: str = "input/"
    controls_dir: str = "controls/"
    data_dir: str = "data/"
    results_dir: str = "results/"

    # Legacy flat paths (kept for backward compat with old scripts)
    data_raw_dir: str = "data/raw/"
    data_normalized_dir: str = "data/normalized/"
    data_schemas_dir: str = "data/schemas/"


class LLMConfig(BaseModel):
    provider: str = "openai"
    model: str = "gpt-4o"
    temperature: int = 0
    max_retries: int = 3
    timeout_seconds: int = 60


class NormalizationConfig(BaseModel):
    default_string_encoding: str = "utf-8"
    date_formats: list[str] = Field(
        default_factory=lambda: ["%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%Y%m%d"]
    )
    null_strings: list[str] = Field(
        default_factory=lambda: ["", "N/A", "NULL", "null", "None", "NONE", "-"]
    )


class ExecutionConfig(BaseModel):
    duckdb_threads: int = 4
    duckdb_memory_limit: str = "2GB"


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"


class Settings(BaseModel):
    paths: PathsConfig = Field(default_factory=PathsConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    normalization: NormalizationConfig = Field(default_factory=NormalizationConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)

    # Resolved at load time
    project_root: Path = Field(default_factory=_find_project_root)

    model_config = {"arbitrary_types_allowed": True}

    # ------------------------------------------------------------------
    # Convenience path resolvers
    # ------------------------------------------------------------------

    def resolve(self, relative: str) -> Path:
        return self.project_root / relative

    @property
    def input_path(self) -> Path:
        return self.resolve(self.paths.input_dir)

    @property
    def controls_path(self) -> Path:
        return self.resolve(self.paths.controls_dir)

    @property
    def results_path(self) -> Path:
        return self.resolve(self.paths.results_dir)

    # ------------------------------------------------------------------
    # Control-scoped path helpers (new per-control data layout)
    # ------------------------------------------------------------------

    def control_input_path(self, control_id: str) -> Path:
        """input/<control_id>/"""
        return self.resolve(self.paths.input_dir) / control_id

    def control_data_path(self, control_id: str) -> Path:
        """data/<control_id>/"""
        return self.resolve(self.paths.data_dir) / control_id

    def control_normalized_path(self, control_id: str) -> Path:
        """data/<control_id>/normalized/"""
        return self.control_data_path(control_id) / "normalized"

    def control_schemas_path(self, control_id: str) -> Path:
        """data/<control_id>/schemas/"""
        return self.control_data_path(control_id) / "schemas"

    def control_results_path(self, control_id: str) -> Path:
        """results/<control_id>/"""
        return self.resolve(self.paths.results_dir) / control_id

    # Legacy flat path helpers (kept for backward compat)
    @property
    def data_raw_path(self) -> Path:
        return self.resolve(self.paths.data_raw_dir)

    @property
    def data_normalized_path(self) -> Path:
        return self.resolve(self.paths.data_normalized_dir)

    @property
    def data_schemas_path(self) -> Path:
        return self.resolve(self.paths.data_schemas_dir)


_cached_settings: Optional[Settings] = None


def load_settings(config_path: Optional[str | Path] = None) -> Settings:
    """Load and validate settings from YAML.

    If *config_path* is omitted the default ``config/settings.yaml``
    relative to the auto-detected project root is used.

    The result is cached so repeated calls are cheap.
    """
    global _cached_settings
    if _cached_settings is not None:
        return _cached_settings

    root = _find_project_root()
    if config_path is None:
        config_path = root / "config" / "settings.yaml"

    config_path = Path(config_path)
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
    else:
        raw = {}

    _cached_settings = Settings(project_root=root, **raw)
    return _cached_settings
