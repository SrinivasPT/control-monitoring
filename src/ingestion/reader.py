"""Read raw evidence files into Polars DataFrames.

Supported formats: CSV, Excel (.xlsx), Parquet.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

import polars as pl


def read_evidence(
    file_path: str | Path,
    sheet: Optional[str] = None,
) -> pl.DataFrame:
    """Read a raw evidence file into a Polars DataFrame.

    Args:
        file_path: Path to the evidence file.
        sheet:     Sheet name for Excel files.  Required when the workbook
                   has multiple sheets and no default is obvious.

    Returns:
        A Polars DataFrame with the raw (un-normalised) data.

    Raises:
        ValueError: For unsupported formats or missing sheet specification.
        FileNotFoundError: If the file does not exist.
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Evidence file not found: {path}")

    suffix = path.suffix.lower()

    if suffix == ".csv":
        return pl.read_csv(
            path,
            infer_schema_length=1000,
            null_values=["", "N/A", "NULL", "null", "None", "NONE", "-"],
            try_parse_dates=False,
        )

    if suffix in (".xlsx", ".xls"):
        return _read_excel(path, sheet)

    if suffix == ".parquet":
        return pl.read_parquet(path)

    raise ValueError(
        f"Unsupported evidence file format '{suffix}'. "
        "Supported formats: .csv, .xlsx, .xls, .parquet"
    )


def _read_excel(path: Path, sheet: Optional[str]) -> pl.DataFrame:
    """Read a single worksheet from an Excel workbook."""
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    sheet_names = wb.sheetnames

    if sheet is None:
        if len(sheet_names) == 1:
            sheet = sheet_names[0]
        else:
            raise ValueError(
                f"Excel workbook '{path.name}' has multiple sheets and no sheet "
                f"was specified. Available sheets: {sheet_names}"
            )

    if sheet not in sheet_names:
        raise ValueError(
            f"Sheet '{sheet}' not found in '{path.name}'. "
            f"Available sheets: {sheet_names}"
        )

    ws = wb[sheet]
    rows = list(ws.values)
    wb.close()

    if not rows:
        raise ValueError(f"Sheet '{sheet}' in '{path.name}' is empty.")

    headers = [str(h) if h is not None else f"col_{i}" for i, h in enumerate(rows[0])]
    data_rows = rows[1:]

    # Build column-oriented dict for Polars
    col_data: dict[str, list] = {h: [] for h in headers}
    for row in data_rows:
        for i, h in enumerate(headers):
            val = row[i] if i < len(row) else None
            col_data[h].append(val)

    # Polars can infer types from Python-native lists
    return pl.DataFrame(col_data, infer_schema_length=1000)
