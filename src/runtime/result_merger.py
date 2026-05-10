"""Result merger — merges per-group results into control-level outputs."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.models.result import AuditRecord, GroupAuditEntry, Metric, Violation
from src.utils.filesystem import load_json, write_json
from src.utils.logging import get_logger

log = get_logger(__name__)


def merge_results(
    control_id: str,
    group_audit_entries: list[GroupAuditEntry],
    results_dir: Path,
) -> AuditRecord:
    """Merge per-group result files into control-level outputs.

    Writes:
    - results/<control_id>/violations.json
    - results/<control_id>/metrics.json
    - results/<control_id>/audit.json

    Args:
        control_id:          The control identifier.
        group_audit_entries: Audit entries from all group executions.
        results_dir:         Root results/ directory.

    Returns:
        The final AuditRecord.
    """
    control_results_dir = results_dir / control_id

    all_violations: list[dict[str, Any]] = []
    all_metrics: list[dict[str, Any]] = []

    for entry in group_audit_entries:
        if entry.status != "success":
            continue
        group_results_path = (
            control_results_dir / "groups" / entry.group_id / "results.json"
        )
        if not group_results_path.exists():
            log.warning(
                f"[{control_id}/{entry.group_id}] results.json not found — skipping merge."
            )
            continue

        data = load_json(group_results_path)
        all_violations.extend(data.get("violations", []))
        all_metrics.extend(data.get("metrics", []))

    total_violations = len(all_violations)

    write_json(control_results_dir / "violations.json", all_violations)
    write_json(control_results_dir / "metrics.json", all_metrics)

    audit = AuditRecord(
        control_id=control_id,
        executed_at=datetime.now(timezone.utc).isoformat(),
        total_violation_count=total_violations,
        total_groups=len(group_audit_entries),
        groups=group_audit_entries,
    )
    write_json(control_results_dir / "audit.json", audit.model_dump())

    log.info(
        f"[{control_id}] Results merged — "
        f"{total_violations} violations, {len(all_metrics)} metrics."
    )

    return audit
