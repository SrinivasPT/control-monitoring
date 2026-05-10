"""run.py — Consolidated pipeline runner.

Reads from input/<CONTROL_ID>/ (control-instruction.md + CSV files),
runs all three phases (Ingest → Build → Execute), and validates results.

Usage:
    python run.py                              # run all controls in input/
    python run.py --control HR_ACCESS_001      # single control
    python run.py --control HR_ACCESS_001 --force   # force LLM regeneration
    python run.py --skip-llm                   # use existing decomposition artifacts
    python run.py --dry-run                    # validate input without executing

Environment:
    DEEPSEEK_API_KEY   Required unless --skip-llm is set.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

import polars as pl

from src.compiler.compiler import compile_group
from src.config import load_settings
from src.decomposer.llm_client import LLMClient, LLMError
from src.decomposer.validator import validate_dsl
from src.ingestion.normalizer import normalize_dataframe
from src.ingestion.reader import read_evidence
from src.ingestion.schema import read_schema, write_schema
from src.models.decomposition import GroupManifest
from src.models.dsl import DSLPlan
from src.models.manifest import BuildManifest, GroupManifestEntry
from src.models.schema import DatasetSchema
from src.pipeline.instructor_decomposer import decompose_control
from src.runtime.executor import execute_group
from src.runtime.result_merger import merge_results
from src.utils.filesystem import ensure_dir, file_exists, load_json, load_yaml, write_json
from src.utils.hashing import sha256_file
from src.utils.logging import get_logger, setup_logging

log = get_logger("run")


# ===========================================================================
# CLI
# ===========================================================================


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Control Monitoring Engine — end-to-end pipeline runner.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--control", metavar="ID",
        help="Run a specific control from input/ (default: all).",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Force LLM regeneration and SQL recompilation.",
    )
    p.add_argument(
        "--skip-llm", action="store_true",
        help="Skip LLM calls; use existing decomposition.yaml / dsl.yaml artifacts.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Ingest and validate input without executing SQL.",
    )
    p.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity (default: INFO).",
    )
    return p.parse_args()


# ===========================================================================
# Phase 1 — Ingest
# ===========================================================================


def ingest_control(
    control_id: str,
    settings,
    force: bool = False,
) -> tuple[list[DatasetSchema], dict[str, list[dict]]]:
    """Read CSV files from input/<control_id>/ and normalise to Parquet.

    Returns:
        (schemas, sample_rows) — schemas per dataset, 10 sample rows per dataset.
    """
    input_dir = settings.control_input_path(control_id)
    normalized_dir = settings.control_normalized_path(control_id)
    schemas_dir = settings.control_schemas_path(control_id)
    ensure_dir(normalized_dir)
    ensure_dir(schemas_dir)

    csv_files = sorted(input_dir.glob("*.csv"))
    if not csv_files:
        raise FileNotFoundError(
            f"No CSV files found in {input_dir}. "
            "Add evidence CSV files alongside control-instruction.md."
        )

    schemas: list[DatasetSchema] = []
    sample_rows: dict[str, list[dict]] = {}

    for csv_path in csv_files:
        dataset_id = csv_path.stem
        parquet_out = normalized_dir / f"{dataset_id}.parquet"
        schema_out = schemas_dir / f"{dataset_id}.schema.yaml"

        if parquet_out.exists() and schema_out.exists() and not force:
            log.info(
                "[%s/%s] Parquet + schema exist — loading (use --force to re-ingest).",
                control_id, dataset_id,
            )
            schema = read_schema(schema_out)
            df = pl.read_parquet(parquet_out)
        else:
            log.info("[%s/%s] Ingesting %s …", control_id, dataset_id, csv_path.name)
            t0 = time.monotonic()

            df_raw = read_evidence(csv_path)
            log.info(
                "[%s/%s] Read %d rows × %d cols in %.2fs",
                control_id, dataset_id,
                len(df_raw), len(df_raw.columns),
                time.monotonic() - t0,
            )

            existing_schema = read_schema(schema_out) if schema_out.exists() else None
            df, schema = normalize_dataframe(
                df_raw, dataset_id, str(csv_path), existing_schema
            )
            df.write_parquet(parquet_out)
            write_schema(schema_out, schema)

            log.info(
                "[%s/%s] Normalised → %s (%d rows, %d cols)",
                control_id, dataset_id,
                parquet_out.name, len(df), len(df.columns),
            )

        schemas.append(schema)
        # Sample rows for the LLM prompt (convert to JSON-serialisable dicts)
        sample_rows[dataset_id] = [
            {k: (str(v) if v is not None else None) for k, v in row.items()}
            for row in df.head(10).to_dicts()
        ]

    return schemas, sample_rows


# ===========================================================================
# Phase 2 — Build (LLM decompose + compile)
# ===========================================================================


def build_control(
    control_id: str,
    instruction: str,
    schemas: list[DatasetSchema],
    sample_rows: dict[str, list[dict]],
    settings,
    llm_client: LLMClient,
    force: bool = False,
    skip_llm: bool = False,
) -> BuildManifest:
    """LLM-decompose control, validate DSL, compile SQL, write build manifest."""
    controls_dir = settings.controls_path
    ensure_dir(controls_dir / control_id)

    # --- Decompose (LLM or load existing) ---
    if skip_llm:
        decomp_path = controls_dir / control_id / "decomposition.yaml"
        if not decomp_path.exists():
            raise FileNotFoundError(
                f"--skip-llm set but no decomposition.yaml found: {decomp_path}"
            )
        log.info("[%s] --skip-llm: loading existing decomposition artifacts.", control_id)
        manifest = GroupManifest.model_validate(load_yaml(decomp_path))
        dsl_plans: dict[str, DSLPlan] = {}
        for g in manifest.groups:
            dsl_path = controls_dir / control_id / "groups" / g.id / "dsl.yaml"
            if dsl_path.exists():
                dsl_plans[g.id] = DSLPlan.model_validate(load_yaml(dsl_path))
            else:
                raise FileNotFoundError(f"Missing dsl.yaml: {dsl_path}")
    else:
        manifest, dsl_plans = decompose_control(
            control_id=control_id,
            instruction=instruction,
            schemas=schemas,
            sample_rows=sample_rows,
            controls_dir=controls_dir,
            llm_client=llm_client,
            force=force,
        )

    log.info(
        "[%s] Decomposition: %d groups — %s",
        control_id,
        len(manifest.groups),
        [g.id for g in manifest.groups],
    )

    # --- Schema map for compiler ---
    schema_map: dict[str, DatasetSchema] = {s.dataset_id: s for s in schemas}

    # --- Compile each group ---
    now = datetime.now(timezone.utc).isoformat()
    group_entries: list[GroupManifestEntry] = []

    for group in manifest.ordered_groups():
        dsl_plan = dsl_plans.get(group.id)
        if dsl_plan is None:
            log.warning("[%s/%s] No DSL plan — skipping compile.", control_id, group.id)
            continue

        # Validate
        allowed_ds = set(group.datasets)
        all_check_ids = {
            s.check_id
            for s in dsl_plan.steps
            if hasattr(s, "check_id") and s.check_id
        }
        errors = validate_dsl(dsl_plan, allowed_datasets=allowed_ds, allowed_check_ids=all_check_ids)
        if errors:
            log.warning(
                "[%s/%s] DSL validation warnings (%d):\n  %s",
                control_id, group.id, len(errors),
                "\n  ".join(str(e) for e in errors),
            )

        # Compile
        log.info("[%s/%s] Compiling SQL …", control_id, group.id)
        t0 = time.monotonic()
        sql = compile_group(dsl_plan, schema_map, controls_dir, force=force)
        elapsed = int((time.monotonic() - t0) * 1000)
        log.info("[%s/%s] SQL compiled in %dms.", control_id, group.id, elapsed)

        # Gather paths + checksums
        dsl_path = controls_dir / control_id / "groups" / group.id / "dsl.yaml"
        sql_path = controls_dir / control_id / "groups" / group.id / "compiled.sql"

        step_check_ids = [
            s.check_id
            for s in dsl_plan.steps
            if hasattr(s, "check_id") and s.check_id
        ]

        group_entries.append(
            GroupManifestEntry(
                group_id=group.id,
                dsl_file=str(dsl_path.relative_to(_ROOT)),
                dsl_sha256=sha256_file(dsl_path) if dsl_path.exists() else "",
                compiled_sql_file=str(sql_path.relative_to(_ROOT)),
                compiled_sql_sha256=sha256_file(sql_path) if sql_path.exists() else "",
                datasets_required=group.datasets,
                checks=step_check_ids,
            )
        )

    # Write build manifest
    decomp_path = controls_dir / control_id / "decomposition.yaml"
    build_manifest = BuildManifest(
        control_id=control_id,
        built_at=now,
        group_manifest_file=str(decomp_path.relative_to(_ROOT)),
        group_manifest_sha256=sha256_file(decomp_path) if decomp_path.exists() else "",
        groups=group_entries,
    )
    manifest_path = controls_dir / control_id / "build_manifest.json"
    write_json(manifest_path, build_manifest.model_dump())
    log.info("[%s] build_manifest.json written → %s", control_id, manifest_path)

    return build_manifest


# ===========================================================================
# Phase 3 — Execute
# ===========================================================================


def execute_control(
    control_id: str,
    build_manifest: BuildManifest,
    settings,
) -> dict[str, Any]:
    """Execute all groups and merge results. Returns summary dict."""
    controls_dir = settings.controls_path
    normalized_dir = settings.control_normalized_path(control_id)
    # executor + merger both expect the root results/ dir (they append /<control_id>/ internally)
    results_root = settings.results_path
    ensure_dir(results_root / control_id)

    # Load manifest + group manifest for execution order
    decomp_path = controls_dir / control_id / "decomposition.yaml"
    group_manifest = GroupManifest.model_validate(load_yaml(decomp_path))
    ordered_groups = group_manifest.ordered_groups()

    group_audit_entries = []
    errors = 0

    for group in ordered_groups:
        entry = build_manifest.get_group(group.id)
        if not entry:
            log.warning("[%s/%s] No build manifest entry — skipping.", control_id, group.id)
            continue

        log.info("[%s/%s] Executing compiled SQL …", control_id, group.id)
        t0 = time.monotonic()

        audit_entry = execute_group(
            group=group,
            manifest_entry=entry,
            control=_dummy_control(control_id),
            data_normalized_path=normalized_dir,
            controls_dir=controls_dir,
            results_dir=results_root,
            duckdb_threads=settings.execution.duckdb_threads,
            duckdb_memory_limit=settings.execution.duckdb_memory_limit,
            expected_sql_sha256=entry.compiled_sql_sha256,
        )
        group_audit_entries.append(audit_entry)

        elapsed = int((time.monotonic() - t0) * 1000)
        if audit_entry.status == "error":
            errors += 1
            log.error(
                "[%s/%s] Execution ERROR in %dms: %s",
                control_id, group.id, elapsed, audit_entry.error_message,
            )
        else:
            log.info(
                "[%s/%s] Executed in %dms — %d violations.",
                control_id, group.id, elapsed, audit_entry.violation_count,
            )

    audit = merge_results(control_id, group_audit_entries, results_root)

    return {
        "control_id": control_id,
        "status": "error" if errors == len(ordered_groups) else "ok",
        "total_violations": audit.total_violation_count,
        "group_errors": errors,
        "groups_run": len(ordered_groups),
    }


def _dummy_control(control_id: str):
    """Create a minimal control object for execute_group (severity lookup)."""
    from types import SimpleNamespace
    return SimpleNamespace(
        control=SimpleNamespace(id=control_id),
        checks=[],  # severity defaults to 'medium'
    )


# ===========================================================================
# Phase 4 — Validate + Report
# ===========================================================================


def validate_and_report(control_id: str, exec_summary: dict[str, Any], settings) -> dict:
    """Load results and print a structured validation report."""
    results_dir = settings.control_results_path(control_id)
    violations_path = results_dir / "violations.json"
    metrics_path = results_dir / "metrics.json"
    audit_path = results_dir / "audit.json"

    violations = load_json(violations_path) if violations_path.exists() else []
    metrics = load_json(metrics_path) if metrics_path.exists() else []

    # Severity breakdown
    severity_counts: dict[str, int] = {}
    for v in violations:
        sev = v.get("severity", "medium")
        severity_counts[sev] = severity_counts.get(sev, 0) + 1

    # Metric pass/fail
    metrics_passed = sum(1 for m in metrics if m.get("passed") is True)
    metrics_failed = sum(1 for m in metrics if m.get("passed") is False)

    # Overall status
    critical_count = severity_counts.get("critical", 0)
    high_count = severity_counts.get("high", 0)
    has_errors = exec_summary.get("group_errors", 0) > 0
    failed_metrics = metrics_failed > 0

    overall = "FAIL" if (critical_count > 0 or high_count > 0 or has_errors or failed_metrics) else "PASS"

    report = {
        "control_id": control_id,
        "overall": overall,
        "violations": {
            "total": len(violations),
            "by_severity": severity_counts,
        },
        "metrics": {
            "total": len(metrics),
            "passed": metrics_passed,
            "failed": metrics_failed,
        },
        "execution_errors": exec_summary.get("group_errors", 0),
    }

    # --- Pretty print ---
    sep = "─" * 60
    status_symbol = "✗ FAIL" if overall == "FAIL" else "✓ PASS"
    print(f"\n{sep}")
    print(f"  Control: {control_id}")
    print(f"  Status : {status_symbol}")
    print(sep)
    print(f"  Violations   : {len(violations)} total")
    for sev in ["critical", "high", "medium", "low"]:
        cnt = severity_counts.get(sev, 0)
        if cnt:
            marker = " ← " if sev in ("critical", "high") else "   "
            print(f"    {sev:10s}: {cnt}{marker}")
    print(f"  Metrics      : {metrics_passed} passed / {metrics_failed} failed")
    if has_errors:
        print(f"  Exec errors  : {exec_summary['group_errors']} group(s) failed")

    # Print top-5 violations for inspection
    if violations:
        print(f"\n  Sample violations (first 5):")
        for v in violations[:5]:
            cid = v.get("check_id", "?")
            sev = v.get("severity", "?")
            reason = v.get("reason", "")[:80]
            evidence_str = json.dumps(
                {k: val for k, val in (v.get("evidence") or {}).items()}, default=str
            )[:120]
            print(f"    [{sev:8s}] {cid}: {reason}")
            print(f"             evidence: {evidence_str}")

    if metrics:
        print(f"\n  Metrics:")
        for m in metrics:
            cid = m.get("check_id", "?")
            val = m.get("value")
            op = m.get("threshold_operator", "")
            thr = m.get("threshold_value")
            passed_str = "PASS" if m.get("passed") else "FAIL"
            print(f"    [{passed_str}] {cid}: value={val} {op} {thr}")

    print(sep)

    # Write report JSON
    report_path = settings.control_results_path(control_id) / "validation_report.json"
    write_json(report_path, report)
    log.info("[%s] Validation report → %s", control_id, report_path)

    return report


# ===========================================================================
# Main runner
# ===========================================================================


def run_control(
    control_id: str,
    settings,
    llm_client: LLMClient,
    force: bool,
    skip_llm: bool,
    dry_run: bool,
) -> dict[str, Any]:
    """Run the full pipeline for one control. Returns final report dict."""
    input_dir = settings.control_input_path(control_id)
    instruction_path = input_dir / "control-instruction.md"

    if not instruction_path.exists():
        raise FileNotFoundError(
            f"Missing control instruction: {instruction_path}"
        )

    instruction = instruction_path.read_text(encoding="utf-8")
    log.info("[%s] Instruction loaded (%d chars).", control_id, len(instruction))

    # ── Phase 1: Ingest ──────────────────────────────────────────────
    log.info("[%s] ── Phase 1: Ingest ──", control_id)
    schemas, sample_rows = ingest_control(control_id, settings, force=force)
    log.info("[%s] Ingested %d datasets.", control_id, len(schemas))

    if dry_run:
        log.info("[%s] --dry-run: stopping after ingestion.", control_id)
        print(f"\n[{control_id}] DRY-RUN — ingestion OK. Datasets:")
        for s in schemas:
            cols = ", ".join(c.normalized_name for c in s.columns)
            print(f"  {s.dataset_id}: {cols}")
        return {"control_id": control_id, "status": "dry_run"}

    # ── Phase 2: Build ───────────────────────────────────────────────
    log.info("[%s] ── Phase 2: Build ──", control_id)
    build_manifest = build_control(
        control_id=control_id,
        instruction=instruction,
        schemas=schemas,
        sample_rows=sample_rows,
        settings=settings,
        llm_client=llm_client,
        force=force,
        skip_llm=skip_llm,
    )
    log.info("[%s] Build complete: %d groups.", control_id, len(build_manifest.groups))

    # ── Phase 3: Execute ─────────────────────────────────────────────
    log.info("[%s] ── Phase 3: Execute ──", control_id)
    exec_summary = execute_control(control_id, build_manifest, settings)

    # ── Phase 4: Validate ────────────────────────────────────────────
    log.info("[%s] ── Phase 4: Validate ──", control_id)
    report = validate_and_report(control_id, exec_summary, settings)

    return report


def main() -> int:
    args = parse_args()
    settings = load_settings()

    # Invalidate cached settings so the new paths take effect
    import src.config as _cfg
    _cfg._cached_settings = None
    settings = load_settings()

    setup_logging(args.log_level, "text")
    log.info("=== Control Monitoring Engine ===")
    log.info("Project root: %s", settings.project_root)

    # Discover controls
    input_root = settings.input_path
    if not input_root.exists():
        log.error("Input directory not found: %s", input_root)
        return 1

    if args.control:
        control_ids = [args.control]
    else:
        control_ids = sorted(
            d.name for d in input_root.iterdir()
            if d.is_dir() and (d / "control-instruction.md").exists()
        )

    if not control_ids:
        log.warning("No controls found in %s", input_root)
        return 0

    log.info("Controls to run: %s", control_ids)

    # Build LLM client
    llm_client = LLMClient(
        provider="deepseek",
        model=settings.llm.model if settings.llm.provider == "deepseek" else "deepseek-chat",
    )

    # Run each control
    all_reports: list[dict] = []
    pipeline_errors = 0

    t_pipeline_start = time.monotonic()

    for control_id in control_ids:
        log.info("")
        log.info("═" * 60)
        log.info("  Control: %s", control_id)
        log.info("═" * 60)

        t0 = time.monotonic()
        try:
            report = run_control(
                control_id=control_id,
                settings=settings,
                llm_client=llm_client,
                force=args.force,
                skip_llm=args.skip_llm,
                dry_run=args.dry_run,
            )
            elapsed = int((time.monotonic() - t0) * 1000)
            report["elapsed_ms"] = elapsed
            all_reports.append(report)
            log.info("[%s] Pipeline finished in %dms.", control_id, elapsed)
        except LLMError as exc:
            pipeline_errors += 1
            log.error("[%s] LLM error: %s", control_id, exc)
            all_reports.append({"control_id": control_id, "status": "llm_error", "error": str(exc)})
        except Exception as exc:
            pipeline_errors += 1
            log.error("[%s] Pipeline error: %s\n%s", control_id, exc, traceback.format_exc())
            all_reports.append({"control_id": control_id, "status": "error", "error": str(exc)})

    # ── Final summary ────────────────────────────────────────────────
    total_elapsed = int((time.monotonic() - t_pipeline_start) * 1000)
    print(f"\n{'═' * 60}")
    print(f"  PIPELINE SUMMARY — {len(control_ids)} control(s) in {total_elapsed}ms")
    print(f"{'═' * 60}")
    for r in all_reports:
        cid = r.get("control_id", "?")
        overall = r.get("overall", r.get("status", "?"))
        viols = r.get("violations", {}).get("total", "N/A")
        elapsed = r.get("elapsed_ms", 0)
        print(f"  {cid:30s} {overall:8s}  violations={viols}  {elapsed}ms")
    print(f"{'═' * 60}")

    return 1 if pipeline_errors else 0


if __name__ == "__main__":
    sys.exit(main())
