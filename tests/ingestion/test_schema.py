"""tests/ingestion/test_schema.py — schema idempotency tests."""

from __future__ import annotations

from src.ingestion.schema import read_schema, write_schema, write_schema_force
from src.models.schema import ColumnSchema, DatasetSchema


def _make_schema(dataset_id: str = "test_ds") -> DatasetSchema:
    return DatasetSchema(
        dataset_id=dataset_id,
        source_file="test.csv",
        generated_at="2026-01-01T00:00:00+00:00",
        columns=[
            ColumnSchema(
                source_name="Employee ID",
                normalized_name="employee_id",
                type="string",
                nullable=False,
            ),
            ColumnSchema(
                source_name="Status",
                normalized_name="status",
                type="string",
                nullable=False,
            ),
        ],
    )


class TestSchemaIdempotency:
    def test_write_schema_creates_file(self, tmp_path):
        schema = _make_schema()
        path = tmp_path / "test_ds.schema.yaml"
        write_schema(path, schema)
        assert path.exists()

    def test_write_schema_idempotent(self, tmp_path):
        schema = _make_schema()
        path = tmp_path / "test_ds.schema.yaml"
        write_schema(path, schema)
        mtime_1 = path.stat().st_mtime

        # Second write should be skipped — file unchanged
        write_schema(path, schema)
        mtime_2 = path.stat().st_mtime
        assert mtime_1 == mtime_2

    def test_write_schema_force_overwrites(self, tmp_path):
        schema = _make_schema()
        path = tmp_path / "test_ds.schema.yaml"
        write_schema(path, schema)
        mtime_1 = path.stat().st_mtime

        import time

        time.sleep(0.05)

        schema2 = _make_schema("other_ds")
        write_schema_force(path, schema2)
        mtime_2 = path.stat().st_mtime
        assert mtime_2 > mtime_1

    def test_read_schema_round_trip(self, tmp_path):
        schema = _make_schema()
        path = tmp_path / "test_ds.schema.yaml"
        write_schema(path, schema)

        loaded = read_schema(path)
        assert loaded.dataset_id == schema.dataset_id
        assert len(loaded.columns) == len(schema.columns)
        assert loaded.columns[0].normalized_name == "employee_id"
