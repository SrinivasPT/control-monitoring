-- Compiled by control-monitoring compiler
-- Control: GL_BALANCE_001
-- Group:   grp_01_gl_balance_checks
-- Generated: 2026-05-10T18:19:09.365855+00:00
-- Source DSL: controls/GL_BALANCE_001/groups/grp_01_gl_balance_checks/dsl.yaml
-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)


WITH

gl_entries_norm AS (
    -- step_01: NORMALIZE gl_entries
    SELECT
        TRIM(entry_id) AS entry_id,
        TRY_CAST(account_code AS BIGINT) AS account_code,
        TRIM(account_name) AS account_name,
        TRY_CAST(debit_amount AS DOUBLE) AS debit_amount,
        TRY_CAST(credit_amount AS DOUBLE) AS credit_amount,
        TRY_CAST(entry_date AS DATE) AS entry_date,
        TRIM(period) AS period,
        TRIM(created_by) AS created_by
    FROM gl_entries
),

period_balance_violations AS (
    -- step_02: AGGREGATE
    SELECT
        'CHK-GL-001' AS check_id,
        SUM(debit_amount) AS total_debits,
        SUM(credit_amount) AS total_credits,
        ROUND(SUM(debit_amount) - SUM(credit_amount), 2) AS imbalance
    FROM gl_entries_norm
),

missing_account_code AS (
    -- step_03: COMPLETENESS check on account_code
    SELECT
        *,
        'CHK-GL-002' AS check_id,
        'Required field account_code is NULL or missing' AS reason
    FROM gl_entries_norm
    WHERE account_code IS NULL
),

future_dated_entries AS (
    -- step_04: FILTER (check: CHK-GL-003)
    SELECT
        *,
        'CHK-GL-003' AS check_id,
        'Violation detected by CHK-GL-003' AS reason,
        'CHK-GL-003' AS _check_id
    FROM gl_entries_norm
    WHERE CAST(entry_date AS DATE) > CURRENT_DATE
)

SELECT 'aggregate' AS result_type, * FROM period_balance_violations;

-- @@TERMINAL_SEP@@


WITH

gl_entries_norm AS (
    -- step_01: NORMALIZE gl_entries
    SELECT
        TRIM(entry_id) AS entry_id,
        TRY_CAST(account_code AS BIGINT) AS account_code,
        TRIM(account_name) AS account_name,
        TRY_CAST(debit_amount AS DOUBLE) AS debit_amount,
        TRY_CAST(credit_amount AS DOUBLE) AS credit_amount,
        TRY_CAST(entry_date AS DATE) AS entry_date,
        TRIM(period) AS period,
        TRIM(created_by) AS created_by
    FROM gl_entries
),

period_balance_violations AS (
    -- step_02: AGGREGATE
    SELECT
        'CHK-GL-001' AS check_id,
        SUM(debit_amount) AS total_debits,
        SUM(credit_amount) AS total_credits,
        ROUND(SUM(debit_amount) - SUM(credit_amount), 2) AS imbalance
    FROM gl_entries_norm
),

missing_account_code AS (
    -- step_03: COMPLETENESS check on account_code
    SELECT
        *,
        'CHK-GL-002' AS check_id,
        'Required field account_code is NULL or missing' AS reason
    FROM gl_entries_norm
    WHERE account_code IS NULL
),

future_dated_entries AS (
    -- step_04: FILTER (check: CHK-GL-003)
    SELECT
        *,
        'CHK-GL-003' AS check_id,
        'Violation detected by CHK-GL-003' AS reason,
        'CHK-GL-003' AS _check_id
    FROM gl_entries_norm
    WHERE CAST(entry_date AS DATE) > CURRENT_DATE
)

SELECT 'completeness' AS result_type, * FROM missing_account_code;

-- @@TERMINAL_SEP@@


WITH

gl_entries_norm AS (
    -- step_01: NORMALIZE gl_entries
    SELECT
        TRIM(entry_id) AS entry_id,
        TRY_CAST(account_code AS BIGINT) AS account_code,
        TRIM(account_name) AS account_name,
        TRY_CAST(debit_amount AS DOUBLE) AS debit_amount,
        TRY_CAST(credit_amount AS DOUBLE) AS credit_amount,
        TRY_CAST(entry_date AS DATE) AS entry_date,
        TRIM(period) AS period,
        TRIM(created_by) AS created_by
    FROM gl_entries
),

period_balance_violations AS (
    -- step_02: AGGREGATE
    SELECT
        'CHK-GL-001' AS check_id,
        SUM(debit_amount) AS total_debits,
        SUM(credit_amount) AS total_credits,
        ROUND(SUM(debit_amount) - SUM(credit_amount), 2) AS imbalance
    FROM gl_entries_norm
),

missing_account_code AS (
    -- step_03: COMPLETENESS check on account_code
    SELECT
        *,
        'CHK-GL-002' AS check_id,
        'Required field account_code is NULL or missing' AS reason
    FROM gl_entries_norm
    WHERE account_code IS NULL
),

future_dated_entries AS (
    -- step_04: FILTER (check: CHK-GL-003)
    SELECT
        *,
        'CHK-GL-003' AS check_id,
        'Violation detected by CHK-GL-003' AS reason,
        'CHK-GL-003' AS _check_id
    FROM gl_entries_norm
    WHERE CAST(entry_date AS DATE) > CURRENT_DATE
)

SELECT 'row_level' AS result_type, * FROM future_dated_entries;