"""Generate sample evidence fixture files and pre-built control artifacts.

Run once after cloning:
  python scripts/generate_fixtures.py

This creates:
  - data/raw/iam_accounts.xlsx
  - controls/HR_ACCESS_001/decomposition.yaml   (pre-written, no LLM needed)
  - controls/HR_ACCESS_001/groups/*/dsl.yaml     (pre-written, no LLM needed)
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

# --- IAM accounts Excel ---


def create_iam_xlsx():
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = "Accounts"

    headers = [
        "employee_id",
        "account_status",
        "last_modified",
        "account_type",
        "system",
    ]
    ws.append(headers)

    rows = [
        # Active employees — accounts stay active (OK)
        ("EMP-0001", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        ("EMP-0002", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        ("EMP-0005", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        ("EMP-0008", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        ("EMP-0011", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        ("EMP-0015", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        ("EMP-0018", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        ("EMP-0021", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        ("EMP-0024", "ACTIVE", "2026-04-01", "standard", "Azure AD"),
        # Terminated employees — accounts correctly revoked (compliant)
        (
            "EMP-0006",
            "DISABLED",
            "2026-02-16",
            "standard",
            "Azure AD",
        ),  # 1 day — within SLA
        (
            "EMP-0009",
            "DISABLED",
            "2026-01-22",
            "standard",
            "Azure AD",
        ),  # 2 days — within SLA
        (
            "EMP-0019",
            "DISABLED",
            "2026-01-13",
            "standard",
            "Azure AD",
        ),  # 3 days — within SLA
        (
            "EMP-0022",
            "DISABLED",
            "2026-02-05",
            "standard",
            "Azure AD",
        ),  # 4 days — within SLA
        (
            "EMP-0023",
            "DISABLED",
            "2026-03-30",
            "standard",
            "Azure AD",
        ),  # 5 days — within SLA
        (
            "EMP-0014",
            "DISABLED",
            "2026-03-06",
            "standard",
            "Azure AD",
        ),  # 6 days — within SLA
        (
            "EMP-0017",
            "DISABLED",
            "2026-03-27",
            "standard",
            "Azure AD",
        ),  # 7 days — within SLA
        (
            "EMP-0010",
            "DISABLED",
            "2026-03-18",
            "standard",
            "Azure AD",
        ),  # 8 days — outside SLA
        (
            "EMP-0012",
            "DISABLED",
            "2026-04-05",
            "standard",
            "Azure AD",
        ),  # 21 days — outside SLA
        (
            "EMP-0025",
            "DISABLED",
            "2026-04-28",
            "standard",
            "Azure AD",
        ),  # 18 days — outside SLA
        # VIOLATIONS: terminated employees with accounts still ACTIVE
        ("EMP-0003", "ACTIVE", "2026-03-01", "standard", "Azure AD"),  # violation
        ("EMP-0004", "ACTIVE", "2026-03-05", "standard", "Azure AD"),  # violation
        ("EMP-0007", "ACTIVE", "2026-04-01", "standard", "Azure AD"),  # violation
        ("EMP-0016", "ACTIVE", "2026-04-05", "standard", "Azure AD"),  # violation
    ]

    for row in rows:
        ws.append(row)

    out = _ROOT / "data" / "raw" / "iam_accounts.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    print(f"Created: {out}")


# --- Pre-written decomposition.yaml ---

DECOMPOSITION_YAML = """\
# controls/HR_ACCESS_001/decomposition.yaml
# Pre-written for use without an LLM API key.
# MANUALLY CORRECTABLE — will not be overwritten if this file exists.

control_id: HR_ACCESS_001
generated_at: '2026-05-10T09:00:00+00:00'
generator: manual

groups:
  - id: grp_01_data_prep
    name: Data Preparation
    description: >-
      Normalize HR and IAM datasets ready for downstream checks.
    datasets: [hr_roster, iam_accounts]
    checks: []
    execution_order: 1

  - id: grp_02_access_violations
    name: Row-Level Access Violations
    description: >-
      Identify individual terminated employees who still have ACTIVE IAM accounts.
    datasets: [hr_roster, iam_accounts]
    checks: [terminated_active_access]
    execution_order: 2

  - id: grp_03_sla_metrics
    name: SLA Compliance Metrics
    description: >-
      Compute the proportion of terminated employees whose access was revoked
      within the 7-day SLA window.
    datasets: [hr_roster, iam_accounts]
    checks: [access_revocation_sla]
    execution_order: 3

  - id: grp_04_completeness
    name: Data Completeness Checks
    description: >-
      Flag terminated employees missing a termination_date.
    datasets: [hr_roster]
    checks: [missing_termination_date]
    execution_order: 4
"""

# --- Pre-written DSL files ---

DSL_GRP_01 = """\
# Pre-written DSL for grp_01_data_prep
# MANUALLY CORRECTABLE — will not be overwritten if this file exists.

control_id: HR_ACCESS_001
group_id: grp_01_data_prep
generated_at: '2026-05-10T09:00:00+00:00'
generator: manual

steps:
  - id: step_01
    type: NORMALIZE
    dataset: hr_roster
    output_alias: norm_hr

  - id: step_02
    type: NORMALIZE
    dataset: iam_accounts
    output_alias: norm_iam
"""

DSL_GRP_02 = """\
# Pre-written DSL for grp_02_access_violations
# MANUALLY CORRECTABLE — will not be overwritten if this file exists.

control_id: HR_ACCESS_001
group_id: grp_02_access_violations
generated_at: '2026-05-10T09:00:00+00:00'
generator: manual

steps:
  - id: step_01
    type: NORMALIZE
    dataset: hr_roster
    output_alias: norm_hr

  - id: step_02
    type: NORMALIZE
    dataset: iam_accounts
    output_alias: norm_iam

  - id: step_03
    type: JOIN
    left: norm_hr
    right: norm_iam
    on:
      left_key: employee_id
      right_key: employee_id
    join_type: inner
    output_alias: joined_accounts

  - id: step_04
    type: FILTER
    input: joined_accounts
    conditions:
      - "status = 'TERMINATED'"
      - "account_status = 'ACTIVE'"
    output_alias: terminated_active
    check_id: terminated_active_access
"""

DSL_GRP_03 = """\
# Pre-written DSL for grp_03_sla_metrics
# MANUALLY CORRECTABLE — will not be overwritten if this file exists.

control_id: HR_ACCESS_001
group_id: grp_03_sla_metrics
generated_at: '2026-05-10T09:00:00+00:00'
generator: manual

steps:
  - id: step_01
    type: NORMALIZE
    dataset: hr_roster
    output_alias: norm_hr

  - id: step_02
    type: NORMALIZE
    dataset: iam_accounts
    output_alias: norm_iam

  - id: step_03
    type: JOIN
    left: norm_hr
    right: norm_iam
    on:
      left_key: employee_id
      right_key: employee_id
    join_type: inner
    output_alias: joined_accounts

  - id: step_04
    type: DATE_DIFF
    input: joined_accounts
    from_field: termination_date
    to_field: last_modified
    unit: days
    output_alias: days_to_revoke
    filter:
      field: status
      op: eq
      value: TERMINATED

  - id: step_05
    type: THRESHOLD
    input: days_to_revoke
    condition: termination_date_to_last_modified_days <= 7
    flag_field: revoked_within_sla
    output_alias: sla_evaluated

  - id: step_06
    type: AGGREGATE
    input: sla_evaluated
    output_alias: agg_metrics
    check_id: access_revocation_sla
    metrics:
      - name: total_terminated
        formula: "COUNT(*)"
      - name: revoked_within_sla_count
        formula: "COUNT(*)"
        filter: "revoked_within_sla = true"
      - name: sla_rate
        formula: "ROUND(COUNT(*) FILTER (WHERE revoked_within_sla = true)::DOUBLE / NULLIF(COUNT(*), 0), 4)"
      - name: passed
        formula: "ROUND(COUNT(*) FILTER (WHERE revoked_within_sla = true)::DOUBLE / NULLIF(COUNT(*), 0), 4) >= 0.95"
"""

DSL_GRP_04 = """\
# Pre-written DSL for grp_04_completeness
# MANUALLY CORRECTABLE — will not be overwritten if this file exists.

control_id: HR_ACCESS_001
group_id: grp_04_completeness
generated_at: '2026-05-10T09:00:00+00:00'
generator: manual

steps:
  - id: step_01
    type: NORMALIZE
    dataset: hr_roster
    output_alias: norm_hr

  - id: step_02
    type: COMPLETENESS
    input: norm_hr
    check_field: termination_date
    filter:
      field: status
      op: eq
      value: TERMINATED
    output_alias: missing_termination_dates
    check_id: missing_termination_date
"""


def write_if_missing(path: Path, content: str):
    if path.exists():
        print(f"Exists (skipping): {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"Created: {path}")


def main():
    create_iam_xlsx()

    ctrl_dir = _ROOT / "controls" / "HR_ACCESS_001"

    write_if_missing(ctrl_dir / "decomposition.yaml", DECOMPOSITION_YAML)
    write_if_missing(ctrl_dir / "groups" / "grp_01_data_prep" / "dsl.yaml", DSL_GRP_01)
    write_if_missing(
        ctrl_dir / "groups" / "grp_02_access_violations" / "dsl.yaml", DSL_GRP_02
    )
    write_if_missing(
        ctrl_dir / "groups" / "grp_03_sla_metrics" / "dsl.yaml", DSL_GRP_03
    )
    write_if_missing(
        ctrl_dir / "groups" / "grp_04_completeness" / "dsl.yaml", DSL_GRP_04
    )

    print("\nFixture generation complete.")
    print("Next steps:")
    print("  python scripts/ingest.py --control HR_ACCESS_001")
    print("  python scripts/build.py  --control HR_ACCESS_001 --skip-llm")
    print("  python scripts/execute.py --control HR_ACCESS_001")


if __name__ == "__main__":
    main()
