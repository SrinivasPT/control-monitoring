"""scripts/execute.py — Execution Phase runner.

Usage:
  python scripts/execute.py --control HR_ACCESS_001
  python scripts/execute.py --control HR_ACCESS_001 --group grp_03_sla_metrics
  python scripts/execute.py
  python scripts/execute.py --dry-run
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.config import load_settings
from src.models.control import ControlFile
from src.models.decomposition import GroupManifest
from src.models.manifest import BuildManifest
from src.runtime.executor import execute_group
from src.runtime.result_merger import merge_results
from src.utils.filesystem import ensure_dir, file_exists, load_json, load_yaml
from src.utils.logging import get_logger, setup_logging


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the Execution Phase — execute compiled SQL against DuckDB."
    )
    p.add_argument(
        "--control", metavar="ID", help="Execute a specific control (default: all)."
    )
    p.add_argument(
        "--group",
        metavar="ID",
        help="Execute only a specific group within the control.",
    )
    p.add_argument(
        "--output-dir", metavar="PATH", help="Override default results/ directory."
    )
    p.add_argument(
        "--dry-run", action="store_true", help="Validate artifacts without executing."
    )
    return p.parse_args()


def load_controls(settings, control_id: str | None) -> list[ControlFile]:
    controls_path = settings.controls_path
    if not controls_path.exists():
        return []
    if control_id:
        yaml_path = controls_path / control_id / "control.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"Control not found: {yaml_path}")
        return [ControlFile.model_validate(load_yaml(yaml_path))]
    result = []
    for d in sorted(controls_path.iterdir()):
        p = d / "control.yaml"
        if p.exists():
            result.append(ControlFile.model_validate(load_yaml(p)))
    return result


def execute_control(
    control: ControlFile,
    settings,
    results_dir: Path,
    target_group: str | None,
    dry_run: bool,
    log,
) -> dict:
    """Execute all (or one) group(s) for a control."""
    cid = control.control.id
    controls_dir = settings.controls_path

    # Load build manifest
    manifest_path = controls_dir / cid / "build_manifest.json"
    if not manifest_path.exists():
        log.error(f"[{cid}] build_manifest.json not found. Run build phase first.")
        return {"control_id": cid, "status": "error", "reason": "missing_manifest"}

    build_manifest = BuildManifest.model_validate(load_json(manifest_path))

    # Load decomposition for execution order
    decomp_path = controls_dir / cid / "decomposition.yaml"
    if not decomp_path.exists():
        log.error(f"[{cid}] decomposition.yaml not found.")
        return {"control_id": cid, "status": "error", "reason": "missing_decomposition"}

    group_manifest = GroupManifest.model_validate(load_yaml(decomp_path))
    groups = group_manifest.ordered_groups()

    if target_group:
        groups = [g for g in groups if g.id == target_group]
        if not groups:
            log.error(f"[{cid}] Group '{target_group}' not found.")
            return {
                "control_id": cid,
                "status": "error",
                "reason": f"unknown_group:{target_group}",
            }

    if dry_run:
        log.info(f"[{cid}] DRY-RUN: validating {len(groups)} groups ...")
        for g in groups:
            entry = build_manifest.get_group(g.id)
            if not entry:
                log.warning(f"[{cid}/{g.id}] No manifest entry — group not built.")
                continue
            sql_path = Path(entry.compiled_sql_file)
            if not sql_path.is_absolute():
                sql_path = settings.project_root / sql_path
            if not sql_path.exists():
                log.warning(f"[{cid}/{g.id}] compiled.sql not found: {sql_path}")
            else:
                log.info(f"[{cid}/{g.id}] compiled.sql OK: {sql_path}")
        return {"control_id": cid, "status": "dry_run"}

    t0 = time.monotonic()
    group_audit_entries = []
    errors = 0

    for group in groups:
        entry = build_manifest.get_group(group.id)
        if not entry:
            log.warning(f"[{cid}/{group.id}] Skipping — not in build manifest.")
            continue

        audit_entry = execute_group(
            group=group,
            manifest_entry=entry,
            control=control,
            data_normalized_path=settings.data_normalized_path,
            controls_dir=controls_dir,
            results_dir=results_dir,
            duckdb_threads=settings.execution.duckdb_threads,
            duckdb_memory_limit=settings.execution.duckdb_memory_limit,
            expected_sql_sha256=entry.compiled_sql_sha256,
        )
        group_audit_entries.append(audit_entry)
        if audit_entry.status == "error":
            errors += 1

    # Merge results (even if some groups failed)
    audit = merge_results(cid, group_audit_entries, results_dir)

    elapsed = int((time.monotonic() - t0) * 1000)
    log.info(
        f"[{cid}] Execution done in {elapsed}ms — "
        f"{audit.total_violation_count} violations, {errors} group errors."
    )
    return {
        "control_id": cid,
        "status": "error" if errors == len(groups) else "ok",
        "violations": audit.total_violation_count,
        "group_errors": errors,
        "elapsed_ms": elapsed,
    }


def main() -> int:
    args = parse_args()
    settings = load_settings()
    setup_logging(settings.logging.level, settings.logging.format)
    log = get_logger("execute")

    log.info("=== Execution Phase starting ===")

    results_dir = Path(args.output_dir) if args.output_dir else settings.results_path

    try:
        controls = load_controls(settings, args.control)
    except FileNotFoundError as exc:
        log.error(str(exc))
        return 1

    if not controls:
        log.warning("No control definitions found — nothing to do.")
        return 0

    results = []
    errors = 0
    for ctrl in controls:
        r = execute_control(ctrl, settings, results_dir, args.group, args.dry_run, log)
        results.append(r)
        if r.get("status") == "error":
            errors += 1

    ok = sum(1 for r in results if r.get("status") == "ok")
    log.info(f"=== Execution complete: {ok} controls executed, {errors} errors ===")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
