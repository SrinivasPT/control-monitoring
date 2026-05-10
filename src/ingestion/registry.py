"""Dataset registry — maps dataset IDs to raw file paths.

The registry is built from control definitions; it knows which datasets
belong to which controls and where their raw files live.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml

from src.models.control import ControlFile
from src.utils.filesystem import load_yaml


class DatasetEntry:
    __slots__ = (
        "dataset_id",
        "raw_file_path",
        "sheet",
        "control_id",
        "required_columns",
    )

    def __init__(
        self,
        dataset_id: str,
        raw_file_path: Path,
        sheet: Optional[str],
        control_id: str,
        required_columns: Optional[list[str]],
    ) -> None:
        self.dataset_id = dataset_id
        self.raw_file_path = raw_file_path
        self.sheet = sheet
        self.control_id = control_id
        self.required_columns = required_columns


class DatasetRegistry:
    """Collects dataset → file-path mappings from control definitions."""

    def __init__(self, data_raw_dir: Path) -> None:
        self._data_raw = data_raw_dir
        self._entries: dict[str, DatasetEntry] = {}

    def register_from_control(self, control: ControlFile) -> None:
        """Register all datasets declared in *control*."""
        for ds in control.datasets:
            raw_path = self._data_raw / ds.file
            entry = DatasetEntry(
                dataset_id=ds.id,
                raw_file_path=raw_path,
                sheet=ds.sheet,
                control_id=control.control.id,
                required_columns=ds.required_columns,
            )
            self._entries[ds.id] = entry

    def get(self, dataset_id: str) -> Optional[DatasetEntry]:
        return self._entries.get(dataset_id)

    def all_entries(self) -> list[DatasetEntry]:
        return list(self._entries.values())

    @staticmethod
    def load_control(control_yaml_path: Path) -> ControlFile:
        raw = load_yaml(control_yaml_path)
        return ControlFile.model_validate(raw)
