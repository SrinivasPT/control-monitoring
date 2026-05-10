"""DuckDB group executor — runs one group's compiled SQL in an isolated session."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import duckdb

from src.models.control import ControlFile
from src.models.decomposition import GroupDefinition
from src.models.manifest import BuildManifest
from src.models.result import (
    AuditRecord,
    CheckEvaluated,
    DatasetUsed,
    GroupAuditEntry,
    Metric,
    Violation,
)
from src.runtime.result_parser import parse_aggregate, parse_row_level
from src.compiler.cte_builder import TERMINAL_SEPARATOR
from src.utils.filesystem import ensure_dir, write_json
from src.utils.hashing import sha256_file
from src.utils.logging import get_logger

log = get_logger(__name__)


def _row_count(parquet_path: Path) -> int:
    """Fast row count via DuckDB scan."""
    conn = duckdb.connect(":memory:")
    try:
        result = conn.execute(f"SELECT COUNT(*) FROM '{parquet_path}'").fetchone()
        return result[0] if result else 0
    finally:
        conn.close()


def execute_group(
    group: GroupDefinition,
    manifest_entry,
    control: ControlFile,
    data_normalized_path: Path,
    controls_dir: Path,
    results_dir: Path,
    duckdb_threads: int = 4,
    duckdb_memory_limit: str = "2GB",
    expected_sql_sha256: Optional[str] = None,
) -> GroupAuditEntry:
    """Execute one group's compiled SQL against DuckDB.

    Args:
        group:                  GroupDefinition from the manifest.
        manifest_entry:         The group's BuildManifestEntry (for paths/checksums).
        control:                Parsed ControlFile (for severity lookups).
        data_normalized_path:   Directory containing normalized Parquet files.
        controls_dir:           Root controls/ directory.
        results_dir:            Root results/ directory.
        duckdb_threads:         DuckDB thread count.
        duckdb_memory_limit:    DuckDB memory limit string.
        expected_sql_sha256:    SHA-256 of compiled.sql at build time (from manifest).

    Returns:
        A GroupAuditEntry describing the execution result.
    """
    cid = control.control.id
    gid = group.id
    sql_path = Path(manifest_entry.compiled_sql_file)
    if not sql_path.is_absolute():
        sql_path = controls_dir.parent / sql_path

    t0 = time.monotonic()

    # --- Checksum check ---
    actual_sha = sha256_file(sql_path) if sql_path.exists() else ""
    manual_edit_warning = (
        expected_sql_sha256 is not None and actual_sha != expected_sql_sha256
    )
    if manual_edit_warning:
        log.warning(
            f"[{cid}/{gid}] compiled.sql checksum mismatch. "
            f"Expected: {expected_sql_sha256[:8]}...  Actual: {actual_sha[:8]}... "
            "File has been manually edited since last build. Proceeding."
        )

    # --- Verify Parquet files exist ---
    datasets_used: list[DatasetUsed] = []
    for ds_id in group.datasets:
        pq_path = data_normalized_path / f"{ds_id}.parquet"
        if not pq_path.exists():
            elapsed = int((time.monotonic() - t0) * 1000)
            return GroupAuditEntry(
                group_id=gid,
                execution_order=group.execution_order,
                compiled_sql_path=str(sql_path),
                compiled_sql_sha256=actual_sha,
                manual_edit_warning=manual_edit_warning,
                datasets_used=[],
                execution_duration_ms=elapsed,
                status="error",
                error_message=f"Normalized Parquet not found: {pq_path}",
            )
        datasets_used.append(
            DatasetUsed(
                id=ds_id,
                sha256=sha256_file(pq_path),
                row_count=_row_count(pq_path),
            )
        )

    # --- Execute ---
    sql = sql_path.read_text(encoding="utf-8")
    severity_map = {chk.id: chk.severity for chk in control.checks}

    violations: list[Violation] = []
    metrics: list[Metric] = []

    try:
        conn = duckdb.connect(":memory:")
        conn.execute(f"PRAGMA threads={duckdb_threads}")
        conn.execute(f"PRAGMA memory_limit='{duckdb_memory_limit}'")

        # Register dataset views
        for ds_id in group.datasets:
            pq_path = data_normalized_path / f"{ds_id}.parquet"
            conn.execute(f"CREATE VIEW {ds_id} AS SELECT * FROM '{pq_path}'")

        # Execute compiled SQL — may contain multiple sub-queries separated by
        # TERMINAL_SEPARATOR when the group has terminals with different schemas.
        sql_parts = [s.strip() for s in sql.split(TERMINAL_SEPARATOR) if s.strip()]

        for sql_part in sql_parts:
            result = conn.execute(sql_part)
            rows = result.fetchall()
            columns = [desc[0] for desc in result.description]

            for row in rows:
                row_dict: dict[str, Any] = dict(zip(columns, row))
                rt = str(row_dict.get("result_type", "row_level"))

                if rt == "aggregate":
                    metric = parse_aggregate(
                        row_dict, cid, gid, severity_map, control.checks
                    )
                    metrics.append(metric)
                else:
                    violation = parse_row_level(row_dict, cid, gid, severity_map)
                    violations.append(violation)

        conn.close()

    except Exception as exc:
        elapsed = int((time.monotonic() - t0) * 1000)
        log.error(f"[{cid}/{gid}] Execution error: {exc}")
        return GroupAuditEntry(
            group_id=gid,
            execution_order=group.execution_order,
            compiled_sql_path=str(sql_path),
            compiled_sql_sha256=actual_sha,
            manual_edit_warning=manual_edit_warning,
            datasets_used=datasets_used,
            execution_duration_ms=elapsed,
            status="error",
            error_message=str(exc),
        )

    elapsed = int((time.monotonic() - t0) * 1000)

    # --- Write per-group results ---
    group_results_dir = results_dir / cid / "groups" / gid
    ensure_dir(group_results_dir)

    group_result_data = {
        "violations": [v.model_dump() for v in violations],
        "metrics": [m.model_dump() for m in metrics],
    }
    write_json(group_results_dir / "results.json", group_result_data)

    # Build checks_evaluated summary
    checks_evaluated: list[CheckEvaluated] = []
    viol_by_check: dict[str, int] = {}
    for v in violations:
        viol_by_check[v.check_id] = viol_by_check.get(v.check_id, 0) + 1
    for check_id, count in viol_by_check.items():
        checks_evaluated.append(
            CheckEvaluated(check_id=check_id, type="row_level", violation_count=count)
        )
    for m in metrics:
        extra = {}
        if m.metric_name:
            extra[m.metric_name] = m.value
        checks_evaluated.append(
            CheckEvaluated(
                check_id=m.check_id, type="aggregate", passed=m.passed, extra=extra
            )
        )

    log.info(
        f"[{cid}/{gid}] Executed in {elapsed}ms — "
        f"{len(violations)} violations, {len(metrics)} metrics."
    )

    return GroupAuditEntry(
        group_id=gid,
        execution_order=group.execution_order,
        compiled_sql_path=str(sql_path),
        compiled_sql_sha256=actual_sha,
        manual_edit_warning=manual_edit_warning,
        datasets_used=datasets_used,
        execution_duration_ms=elapsed,
        status="success",
        violation_count=len(violations),
        checks_evaluated=checks_evaluated,
    )
