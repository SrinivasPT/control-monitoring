# Control Instruction: Terminated Employee Access Revocation Control
# Control ID: HR_ACCESS_001

## Purpose

This control ensures that when an employee is terminated, their system access (IAM accounts)
are promptly disabled. Retaining active system access for terminated employees violates the
principle of least privilege and creates significant security risk.

## Evidence Datasets

### Dataset 1: `hr_roster`

Contains the HR record for every employee. Key columns:

- `employee_id` – Unique identifier (e.g., `EMP-001`)
- `full_name` – Employee full name
- `department` – Department code (HR, FINANCE, IT, SALES, OPS)
- `status` – Employment status: `ACTIVE` or `TERMINATED`
- `hire_date` – Date employee was hired (`YYYY-MM-DD`)
- `termination_date` – Date of termination (`YYYY-MM-DD`). NULL if still active.

### Dataset 2: `iam_accounts`

Contains all IAM (Identity and Access Management) accounts. Key columns:

- `account_id` – Unique account ID (e.g., `IAM-001`)
- `employee_id` – References `hr_roster.employee_id`
- `username` – Login username
- `account_status` – `ACTIVE` or `DISABLED`
- `last_access_date` – Last login date (`YYYY-MM-DD`)
- `disabled_date` – Date the account was disabled. NULL if still active.

## Checks

### CHK-HR-001: Active Access for Terminated Employees (Row-Level)
Join `hr_roster` to `iam_accounts` on `employee_id`. Identify all rows where:
- `hr_roster.status = 'TERMINATED'`
- `iam_accounts.account_status = 'ACTIVE'`

Each matching row is a **critical** violation.

### CHK-HR-002: Access Revocation SLA (Aggregate)
For terminated employees with `iam_accounts.disabled_date` populated, compute the
number of days between `hr_roster.termination_date` and `iam_accounts.disabled_date`.
Report the percentage of accounts disabled within 1 day (i.e., revocation_days <= 1).

This is an **aggregate** check:
- `accounts_disabled_within_sla` = COUNT of accounts where revocation days ≤ 1
- `total_disabled_accounts` = COUNT of all disabled accounts (with a disabled_date)
- `sla_compliance_rate` = accounts_disabled_within_sla / total_disabled_accounts

### CHK-HR-003: Missing Termination Date for Terminated Employees (Completeness)
Identify terminated employees (`status = 'TERMINATED'`) where `termination_date` is NULL.
This is a data quality violation that also prevents SLA calculation.
