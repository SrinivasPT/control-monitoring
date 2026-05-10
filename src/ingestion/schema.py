"""Schema YAML read/write with idempotency."""

from __future__ import annotations

from pathlib import Path

import yaml

from src.models.schema import DatasetSchema
from src.utils.filesystem import ensure_dir


def read_schema(path: str | Path) -> DatasetSchema:
    """Load a DatasetSchema from a YAML file."""
    with open(path, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return DatasetSchema.model_validate(raw)


def write_schema(path: str | Path, schema: DatasetSchema) -> bool:
    """Write *schema* to YAML at *path*.  Does nothing if the file exists.

    Returns True if written, False if skipped (idempotent).
    """
    p = Path(path)
    if p.exists():
        return False
    ensure_dir(p.parent)

    data = schema.model_dump()
    with open(p, "w", encoding="utf-8") as fh:
        yaml.dump(
            data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    return True


def write_schema_force(path: str | Path, schema: DatasetSchema) -> None:
    """Write *schema* to YAML at *path*, overwriting if it exists."""
    p = Path(path)
    ensure_dir(p.parent)
    data = schema.model_dump()
    with open(p, "w", encoding="utf-8") as fh:
        yaml.dump(
            data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
