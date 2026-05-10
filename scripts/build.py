"""scripts/build.py — Build Phase runner.

Usage:
  python scripts/build.py --control HR_ACCESS_001
  python scripts/build.py --control HR_ACCESS_001 --force all
  python scripts/build.py --control HR_ACCESS_001 --group grp_03_sla_metrics --force dsl
  python scripts/build.py --control HR_ACCESS_001 --skip-llm
  python scripts/build.py --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

from src.compiler.compiler import compile_group
from src.config import load_settings
from src.decomposer.dsl_decomposer import decompose_dsl
from src.decomposer.group_decomposer import decompose_groups
from src.decomposer.llm_client import LLMClient
from src.decomposer.validator import validate_dsl
from src.ingestion.schema import read_schema
from src.models.control import ControlFile
from src.models.manifest import BuildManifest, GroupManifestEntry
from src.utils.filesystem import ensure_dir, file_exists, load_yaml, write_json
from src.utils.hashing import sha256_file
from src.utils.logging import get_logger, setup_logging


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run the Build Phase — decompose and compile control definitions."
    )
    p.add_argument(
        "--control", metavar="ID", help="Build a specific control (default: all)."
    )
    p.add_argument(
        "--group", metavar="ID", help="Scope to a specific group within the control."
    )
    p.add_argument(
        "--force",
        metavar="TARGET",
        choices=["groups", "dsl", "compile", "all"],
        help="Force regeneration: groups | dsl | compile | all.",
    )
    p.add_argument(
        "--skip-llm", action="store_true", help="Skip LLM calls; compile only."
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be built without writing.",
    )
    return p.parse_args()


def load_all_controls(settings, control_id: str | None) -> list[ControlFile]:
    controls_path = settings.controls_path
    if not controls_path.exists():
        return []
    if control_id:
        yaml_path = controls_path / control_id / "control.yaml"
        if not yaml_path.exists():
            raise FileNotFoundError(f"Control definition not found: {yaml_path}")
        return [ControlFile.model_validate(load_yaml(yaml_path))]
    result = []
    for d in sorted(controls_path.iterdir()):
        p = d / "control.yaml"
        if p.exists():
            result.append(ControlFile.model_validate(load_yaml(p)))
    return result


def load_schemas(control: ControlFile, settings) -> dict:
    """Load all schemas for datasets declared in a control."""
    schemas = {}
    for ds in control.datasets:
        schema_path = settings.data_schemas_path / f"{ds.id}.schema.yaml"
        if schema_path.exists():
            schemas[ds.id] = read_schema(schema_path)
    return schemas


def build_control(
    control: ControlFile,
    settings,
    llm_client: LLMClient,
    force_groups: bool,
    force_dsl: bool,
    force_compile: bool,
    skip_llm: bool,
    target_group: str | None,
    dry_run: bool,
    log,
) -> dict:
    """Run the full build pipeline for one control."""
    cid = control.control.id
    controls_dir = settings.controls_path

    if dry_run:
        log.info(f"[{cid}] DRY-RUN: would build control.")
        return {"control_id": cid, "status": "dry_run"}

    t0 = time.monotonic()

    # Step 1: Group decomposition
    if skip_llm:
        manifest_path = controls_dir / cid / "decomposition.yaml"
        if not manifest_path.exists():
            log.error(f"[{cid}] --skip-llm requires decomposition.yaml to exist.")
            return {
                "control_id": cid,
                "status": "error",
                "reason": "missing_decomposition",
            }
        from src.models.decomposition import GroupManifest

        manifest = GroupManifest.model_validate(load_yaml(manifest_path))
        log.info(f"[{cid}] --skip-llm: loaded existing decomposition.yaml.")
    else:
        manifest = decompose_groups(
            control, controls_dir, llm_client, force=force_groups
        )

    groups = manifest.ordered_groups()
    if target_group:
        groups = [g for g in groups if g.id == target_group]
        if not groups:
            log.error(
                f"[{cid}] Group '{target_group}' not found in decomposition.yaml."
            )
            return {
                "control_id": cid,
                "status": "error",
                "reason": f"unknown_group:{target_group}",
            }

    # Load schemas
    schemas = load_schemas(control, settings)

    # Step 2 & 3: Per-group DSL + compile
    group_entries: list[GroupManifestEntry] = []
    errors = 0

    for group in groups:
        gid = group.id
        try:
            # DSL generation
            if skip_llm:
                dsl_path = controls_dir / cid / "groups" / gid / "dsl.yaml"
                if not dsl_path.exists():
                    log.error(f"[{cid}/{gid}] --skip-llm: dsl.yaml not found.")
                    errors += 1
                    continue
                from src.models.dsl import DSLPlan

                dsl_plan = DSLPlan.model_validate(load_yaml(dsl_path))
            else:
                dsl_plan = decompose_dsl(
                    control, group, controls_dir, llm_client, force=force_dsl
                )

            # Validate DSL
            validation_errors = validate_dsl(
                dsl_plan,
                allowed_datasets=group.datasets,
                allowed_check_ids=group.checks if group.checks else None,
            )
            if validation_errors:
                for err in validation_errors:
                    log.warning(f"[{cid}/{gid}] DSL validation: {err}")

            # SQL compilation
            compiled_sql = compile_group(
                dsl_plan, schemas, controls_dir, force=force_compile
            )

            # Checksums
            dsl_path = controls_dir / cid / "groups" / gid / "dsl.yaml"
            sql_path = controls_dir / cid / "groups" / gid / "compiled.sql"

            entry = GroupManifestEntry(
                group_id=gid,
                dsl_file=str(dsl_path.relative_to(settings.project_root)),
                dsl_sha256=sha256_file(dsl_path) if dsl_path.exists() else "",
                compiled_sql_file=str(sql_path.relative_to(settings.project_root)),
                compiled_sql_sha256=sha256_file(sql_path) if sql_path.exists() else "",
                datasets_required=group.datasets,
                checks=group.checks,
            )
            group_entries.append(entry)
            log.info(f"[{cid}/{gid}] Build complete.")

        except Exception as exc:
            log.error(f"[{cid}/{gid}] Build failed: {exc}")
            errors += 1

    # Write build manifest
    decomp_path = controls_dir / cid / "decomposition.yaml"
    manifest_file = BuildManifest(
        control_id=cid,
        built_at=datetime.now(timezone.utc).isoformat(),
        group_manifest_file=str(decomp_path.relative_to(settings.project_root)),
        group_manifest_sha256=sha256_file(decomp_path) if decomp_path.exists() else "",
        groups=group_entries,
    )
    manifest_json_path = controls_dir / cid / "build_manifest.json"
    write_json(manifest_json_path, manifest_file.model_dump())

    elapsed = int((time.monotonic() - t0) * 1000)
    log.info(
        f"[{cid}] Build done in {elapsed}ms — {len(group_entries)} groups, {errors} errors."
    )
    return {
        "control_id": cid,
        "status": "error" if errors else "ok",
        "groups": len(group_entries),
        "errors": errors,
        "elapsed_ms": elapsed,
    }


def main() -> int:
    args = parse_args()
    settings = load_settings()
    setup_logging(settings.logging.level, settings.logging.format)
    log = get_logger("build")

    log.info("=== Build Phase starting ===")

    try:
        controls = load_all_controls(settings, args.control)
    except FileNotFoundError as exc:
        log.error(str(exc))
        return 1

    if not controls:
        log.warning("No control definitions found — nothing to do.")
        return 0

    force = args.force or ""
    force_groups = force in ("groups", "all")
    force_dsl = force in ("dsl", "all")
    force_compile = force in ("compile", "all")

    llm_client = LLMClient(
        provider=settings.llm.provider,
        model=settings.llm.model,
        max_retries=settings.llm.max_retries,
        timeout_seconds=settings.llm.timeout_seconds,
    )

    results = []
    errors = 0

    for ctrl in controls:
        r = build_control(
            ctrl,
            settings,
            llm_client,
            force_groups=force_groups,
            force_dsl=force_dsl,
            force_compile=force_compile,
            skip_llm=args.skip_llm,
            target_group=args.group,
            dry_run=args.dry_run,
            log=log,
        )
        results.append(r)
        if r.get("status") == "error":
            errors += 1

    ok = sum(1 for r in results if r.get("status") == "ok")
    skipped = sum(1 for r in results if r.get("status") == "dry_run")
    log.info(f"=== Build complete: {ok} built, {skipped} dry-run, {errors} errors ===")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
