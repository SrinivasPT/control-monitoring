# Control Instruction: General Ledger Period Balance Control
# Control ID: GL_BALANCE_001

## Purpose

This control ensures the integrity of General Ledger (GL) entries by checking:

1. **Period Balance** – For every accounting period, the sum of all debit amounts must equal
   the sum of all credit amounts. Any period where debits ≠ credits indicates an unbalanced
   journal entry that requires investigation.

2. **Completeness of Account Code** – Every GL entry must have a non-null, non-empty
   `account_code`. Missing account codes prevent proper classification and reporting.

3. **Future-Dated Entries** – No GL entry should have an `entry_date` in the future
   (i.e., later than today). Future-dated entries indicate potential data quality issues
   or unauthorised pre-dated postings.

## Evidence Dataset: `gl_entries`

- Columns: `entry_id`, `account_code`, `account_name`, `debit_amount`, `credit_amount`,
  `entry_date`, `period`, `created_by`
- `period` format: `YYYY-MM` (e.g., `2026-03`)
- `entry_date` format: `YYYY-MM-DD`
- `debit_amount` and `credit_amount` are decimal numbers.

## Checks

### CHK-GL-001: Period Balance (Aggregate)
For each distinct `period`, compute:
- `total_debits` = SUM of `debit_amount`
- `total_credits` = SUM of `credit_amount`
- Flag any period where `total_debits` ≠ `total_credits`.
- This is an **aggregate** check (one row per period).

### CHK-GL-002: Missing Account Code (Completeness)
Identify all GL entries where `account_code` is NULL or empty.
This is a **completeness** check.

### CHK-GL-003: Future-Dated Entries (Row-Level)
Identify all rows where `entry_date > CURRENT_DATE`.
This is a **row-level** filter check.
