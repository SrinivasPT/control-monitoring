"""Idempotent file-system helpers.

Core rule: never overwrite an existing file unless explicitly requested.
"""

import json
from pathlib import Path
from typing import Any

import yaml


def ensure_dir(path: str | Path) -> Path:
    """Create directory (and parents) if it does not exist. Return Path."""
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def write_if_not_exists(path: str | Path, content: str) -> bool:
    """Write *content* to *path* only when the file does not already exist.

    Returns True if the file was written, False if it was skipped.
    """
    p = Path(path)
    if p.exists():
        return False
    ensure_dir(p.parent)
    p.write_text(content, encoding="utf-8")
    return True


def write_text(path: str | Path, content: str) -> None:
    """Unconditionally write text to *path*, creating parents as needed."""
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(content, encoding="utf-8")


def load_yaml(path: str | Path) -> Any:
    """Load a YAML file and return the parsed object."""
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def write_yaml_if_not_exists(path: str | Path, data: Any) -> bool:
    """Serialise *data* to YAML at *path*, skipping if file exists.

    Returns True if written, False if skipped.
    """
    p = Path(path)
    if p.exists():
        return False
    ensure_dir(p.parent)
    with open(p, "w", encoding="utf-8") as fh:
        yaml.dump(
            data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False
        )
    return True


def write_yaml(path: str | Path, data: Any) -> None:
    """Unconditionally serialise *data* to YAML at *path*."""
    p = Path(path)
    ensure_dir(p.parent)
    with open(p, "w", encoding="utf-8") as fh:
        yaml.dump(
            data, fh, default_flow_style=False, allow_unicode=True, sort_keys=False
        )


def load_json(path: str | Path) -> Any:
    """Load a JSON file and return the parsed object."""
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json_if_not_exists(path: str | Path, data: Any) -> bool:
    """Serialise *data* to JSON at *path*, skipping if file exists.

    Returns True if written, False if skipped.
    """
    p = Path(path)
    if p.exists():
        return False
    ensure_dir(p.parent)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)
    return True


def write_json(path: str | Path, data: Any) -> None:
    """Unconditionally serialise *data* to JSON at *path*."""
    p = Path(path)
    ensure_dir(p.parent)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, default=str)


def file_exists(path: str | Path) -> bool:
    """Return True if *path* exists on disk."""
    return Path(path).exists()


def delete_file(path: str | Path) -> bool:
    """Delete *path* if it exists. Returns True if deleted."""
    p = Path(path)
    if p.exists():
        p.unlink()
        return True
    return False
