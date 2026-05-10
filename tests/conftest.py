"""tests/conftest.py — shared pytest fixtures."""

from __future__ import annotations

import csv
import io
from pathlib import Path

import pytest


@pytest.fixture()
def tmp_csv(tmp_path) -> Path:
    """Write a small CSV and return its path."""
    path = tmp_path / "test.csv"
    path.write_text(
        "Employee ID,Status,Termination Date\n"
        "E001,ACTIVE,\n"
        "E002,TERMINATED,2026-03-01\n"
        "E003,TERMINATED,\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture()
def sample_rows() -> list[dict]:
    return [
        {"Employee ID": "E001", "Status": "ACTIVE", "Termination Date": ""},
        {
            "Employee ID": "E002",
            "Status": "TERMINATED",
            "Termination Date": "2026-03-01",
        },
        {"Employee ID": "E003", "Status": "TERMINATED", "Termination Date": ""},
    ]
