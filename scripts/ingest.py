"""scripts/ingest.py — Ingestion Phase runner.

Usage:
  python scripts/ingest.py
  python scripts/ingest.py --control HR_ACCESS_001
  python scripts/ingest.py --dataset hr_roster --force
  python scripts/ingest.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))


from src.config import load_settings
from src.ingestion.normalizer import normalize_dataframe
from src.ingestion.reader import read_evidence
from src.ingestion.registry import DatasetRegistry
from src.ingestion.schema import read_schema, write_schema
from src.models.control import ControlFile
from src.utils.filesystem import ensure_dir, load_yaml
from src.utils.logging import get_logger, setup_logging


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the Ingestion Phase — normalise raw evidence files to Parquet."
    )
    p.add_argument(
        "--control", metavar="ID", help="Process only datasets for this control."
    )
    p.add_argument(
        "--dataset", metavar="NAME", help="Process a specific dataset by ID."
    )
    p.add_argument(
        "--force", action="store_true", help="Re-normalise even if Parquet exists."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without writing.",
    )
    return p.parse_args()


def load_control_files(settings, control_id: str | None) -> list[ControlFile]:
    """Load all control files (or just one) from the controls/ directory."""
    controls_path = settings.controls_path
    if not controls_path.exists():
        return []

    if control_id:
        yaml_path = controls_path / control_id / "control.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"Control definition not found: {yaml_path}")
        raw = load_yaml(yaml_path)
        return [ControlFile.model_validate(raw)]

    result = []
    for control_dir in sorted(controls_path.iterdir()):
        yaml_path = control_dir / "control.yaml"
        if yaml_path.exists():
            raw = load_yaml(yaml_path)
            result.append(ControlFile.model_validate(raw))
    return result


def ingest_dataset(
    dataset_id: str,
    entry,
    settings,
    force: bool,
    dry_run: bool,
    log,
) -> dict:
    """Normalise one dataset.  Returns a summary dict."""
    parquet_out = settings.data_normalized_path / f"{dataset_id}.parquet"
    schema_out = settings.data_schemas_path / f"{dataset_id}.schema.yaml"

    if parquet_out.exists() and not force:
        log.info(
            f"[{dataset_id}] Parquet exists — skipping (use --force to re-normalise)."
        )
        return {"dataset_id": dataset_id, "status": "skipped"}

    if not entry.raw_file_path.exists():
        log.error(f"[{dataset_id}] Raw file not found: {entry.raw_file_path}")
        return {"dataset_id": dataset_id, "status": "error", "reason": "file_not_found"}

    log.info(f"[{dataset_id}] Reading from {entry.raw_file_path} ...")

    if dry_run:
        log.info(f"[{dataset_id}] DRY-RUN: would normalise → {parquet_out}")
        return {"dataset_id": dataset_id, "status": "dry_run"}

    t0 = time.monotonic()

    # Read
    df_raw = read_evidence(entry.raw_file_path, sheet=entry.sheet)

    # Load existing schema if present (manual overrides honoured)
    existing_schema = None
    if schema_out.exists():
        existing_schema = read_schema(schema_out)
        log.info(f"[{dataset_id}] Using existing schema from {schema_out}")

    # Normalise
    df_norm, schema = normalize_dataframe(
        df_raw,
        dataset_id=dataset_id,
        source_file=str(entry.raw_file_path.relative_to(settings.project_root)),
        existing_schema=existing_schema,
        null_strings=settings.normalization.null_strings,
    )

    # Validate required columns
    if entry.required_columns:
        missing = [c for c in entry.required_columns if c not in df_norm.columns]
        if missing:
            log.error(
                f"[{dataset_id}] Missing required columns after normalisation: {missing}"
            )
            return {
                "dataset_id": dataset_id,
                "status": "error",
                "reason": f"missing_columns:{missing}",
            }

    # Write outputs (idempotent for schema)
    ensure_dir(parquet_out.parent)
    df_norm.write_parquet(parquet_out)

    written = write_schema(schema_out, schema)
    schema_status = "written" if written else "kept_existing"

    elapsed = int((time.monotonic() - t0) * 1000)
    log.info(
        f"[{dataset_id}] Done in {elapsed}ms — "
        f"{len(df_norm)} rows → {parquet_out}  schema={schema_status}"
    )
    return {
        "dataset_id": dataset_id,
        "status": "ok",
        "rows": len(df_norm),
        "columns": df_norm.columns,
        "parquet": str(parquet_out),
        "schema": schema_status,
        "elapsed_ms": elapsed,
    }


def main() -> int:
    args = parse_args()
    settings = load_settings()
    setup_logging(settings.logging.level, settings.logging.format)
    log = get_logger("ingest")

    log.info("=== Ingestion Phase starting ===")

    # Collect controls
    try:
        controls = load_control_files(settings, args.control)
    except FileNotFoundError as exc:
        log.error(str(exc))
        return 1

    if not controls:
        log.warning("No control definitions found — nothing to do.")
        return 0

    # Build registry
    registry = DatasetRegistry(settings.data_raw_path)
    for ctrl in controls:
        registry.register_from_control(ctrl)

    entries = registry.all_entries()
    if args.dataset:
        entry = registry.get(args.dataset)
        if not entry:
            log.error(f"Dataset '{args.dataset}' not found in any control definition.")
            return 1
        entries = [entry]

    results = []
    errors = 0
    for entry in entries:
        r = ingest_dataset(
            entry.dataset_id,
            entry,
            settings,
            force=args.force,
            dry_run=args.dry_run,
            log=log,
        )
        results.append(r)
        if r["status"] == "error":
            errors += 1

    # Summary
    ok = sum(1 for r in results if r["status"] == "ok")
    skipped = sum(1 for r in results if r["status"] in ("skipped", "dry_run"))
    log.info(
        f"=== Ingestion complete: {ok} normalised, {skipped} skipped, {errors} errors ==="
    )

    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
