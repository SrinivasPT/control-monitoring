-- Compiled by control-monitoring compiler
-- Control: HR_ACCESS_001
-- Group:   grp_01_terminated_employee_access
-- Generated: 2026-05-10T18:19:20.002416+00:00
-- Source DSL: controls/HR_ACCESS_001/groups/grp_01_terminated_employee_access/dsl.yaml
-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)


WITH

hr_roster_01 AS (
    -- step_01: NORMALIZE hr_roster
    SELECT
        TRIM(employee_id) AS employee_id,
        TRIM(full_name) AS full_name,
        TRIM(department) AS department,
        TRIM(status) AS status,
        TRY_CAST(hire_date AS DATE) AS hire_date,
        TRY_CAST(termination_date AS DATE) AS termination_date
    FROM hr_roster
),

iam_accounts_01 AS (
    -- step_02: NORMALIZE iam_accounts
    SELECT
        TRIM(account_id) AS account_id,
        TRIM(employee_id) AS employee_id,
        TRIM(username) AS username,
        TRIM(account_status) AS account_status,
        TRY_CAST(last_access_date AS DATE) AS last_access_date,
        TRY_CAST(disabled_date AS DATE) AS disabled_date
    FROM iam_accounts
),

hr_iam_joined AS (
    -- step_03: JOIN hr_roster_01 INNER JOIN iam_accounts_01 ON employee_id = employee_id
    SELECT l.*, r.*
    FROM hr_roster_01 l
    INNER JOIN iam_accounts_01 r ON l.employee_id = r.employee_id
),

active_access_terminated AS (
    -- step_04: FILTER (check: CHK-HR-001)
    SELECT
        *,
        'CHK-HR-001' AS check_id,
        'Violation detected by CHK-HR-001' AS reason,
        'CHK-HR-001' AS _check_id
    FROM hr_iam_joined
    WHERE status = 'TERMINATED'
      AND account_status = 'ACTIVE'
),

with_revocation_days AS (
    -- step_05: DATE_DIFF termination_date → disabled_date (days)
    SELECT
        *,
        DATE_DIFF('day', termination_date, disabled_date) AS termination_date_to_disabled_date_days
    FROM hr_iam_joined
),

with_sla_flag AS (
    -- step_06: THRESHOLD — termination_date_to_disabled_date_days <= 1
    SELECT
        *,
        (termination_date_to_disabled_date_days <= 1) AS within_sla
    FROM with_revocation_days
),

sla_compliance AS (
    -- step_07: AGGREGATE
    SELECT
        'CHK-HR-002' AS check_id,
        COUNT(*) FILTER (WHERE within_sla) AS accounts_disabled_within_sla,
        COUNT(*) AS total_disabled_accounts,
        ROUND(COUNT(*) FILTER (WHERE within_sla)::DOUBLE / NULLIF(COUNT(*), 0), 4) AS sla_compliance_rate
    FROM with_sla_flag
),

missing_termination_date AS (
    -- step_08: COMPLETENESS check on termination_date
    SELECT
        *,
        'CHK-HR-003' AS check_id,
        'Required field termination_date is NULL or missing' AS reason
    FROM hr_roster_01
    WHERE status = 'TERMINATED'
    AND termination_date IS NULL
)

SELECT 'row_level' AS result_type, * FROM active_access_terminated;

-- @@TERMINAL_SEP@@


WITH

hr_roster_01 AS (
    -- step_01: NORMALIZE hr_roster
    SELECT
        TRIM(employee_id) AS employee_id,
        TRIM(full_name) AS full_name,
        TRIM(department) AS department,
        TRIM(status) AS status,
        TRY_CAST(hire_date AS DATE) AS hire_date,
        TRY_CAST(termination_date AS DATE) AS termination_date
    FROM hr_roster
),

iam_accounts_01 AS (
    -- step_02: NORMALIZE iam_accounts
    SELECT
        TRIM(account_id) AS account_id,
        TRIM(employee_id) AS employee_id,
        TRIM(username) AS username,
        TRIM(account_status) AS account_status,
        TRY_CAST(last_access_date AS DATE) AS last_access_date,
        TRY_CAST(disabled_date AS DATE) AS disabled_date
    FROM iam_accounts
),

hr_iam_joined AS (
    -- step_03: JOIN hr_roster_01 INNER JOIN iam_accounts_01 ON employee_id = employee_id
    SELECT l.*, r.*
    FROM hr_roster_01 l
    INNER JOIN iam_accounts_01 r ON l.employee_id = r.employee_id
),

active_access_terminated AS (
    -- step_04: FILTER (check: CHK-HR-001)
    SELECT
        *,
        'CHK-HR-001' AS check_id,
        'Violation detected by CHK-HR-001' AS reason,
        'CHK-HR-001' AS _check_id
    FROM hr_iam_joined
    WHERE status = 'TERMINATED'
      AND account_status = 'ACTIVE'
),

with_revocation_days AS (
    -- step_05: DATE_DIFF termination_date → disabled_date (days)
    SELECT
        *,
        DATE_DIFF('day', termination_date, disabled_date) AS termination_date_to_disabled_date_days
    FROM hr_iam_joined
),

with_sla_flag AS (
    -- step_06: THRESHOLD — termination_date_to_disabled_date_days <= 1
    SELECT
        *,
        (termination_date_to_disabled_date_days <= 1) AS within_sla
    FROM with_revocation_days
),

sla_compliance AS (
    -- step_07: AGGREGATE
    SELECT
        'CHK-HR-002' AS check_id,
        COUNT(*) FILTER (WHERE within_sla) AS accounts_disabled_within_sla,
        COUNT(*) AS total_disabled_accounts,
        ROUND(COUNT(*) FILTER (WHERE within_sla)::DOUBLE / NULLIF(COUNT(*), 0), 4) AS sla_compliance_rate
    FROM with_sla_flag
),

missing_termination_date AS (
    -- step_08: COMPLETENESS check on termination_date
    SELECT
        *,
        'CHK-HR-003' AS check_id,
        'Required field termination_date is NULL or missing' AS reason
    FROM hr_roster_01
    WHERE status = 'TERMINATED'
    AND termination_date IS NULL
)

SELECT 'aggregate' AS result_type, * FROM sla_compliance;

-- @@TERMINAL_SEP@@


WITH

hr_roster_01 AS (
    -- step_01: NORMALIZE hr_roster
    SELECT
        TRIM(employee_id) AS employee_id,
        TRIM(full_name) AS full_name,
        TRIM(department) AS department,
        TRIM(status) AS status,
        TRY_CAST(hire_date AS DATE) AS hire_date,
        TRY_CAST(termination_date AS DATE) AS termination_date
    FROM hr_roster
),

iam_accounts_01 AS (
    -- step_02: NORMALIZE iam_accounts
    SELECT
        TRIM(account_id) AS account_id,
        TRIM(employee_id) AS employee_id,
        TRIM(username) AS username,
        TRIM(account_status) AS account_status,
        TRY_CAST(last_access_date AS DATE) AS last_access_date,
        TRY_CAST(disabled_date AS DATE) AS disabled_date
    FROM iam_accounts
),

hr_iam_joined AS (
    -- step_03: JOIN hr_roster_01 INNER JOIN iam_accounts_01 ON employee_id = employee_id
    SELECT l.*, r.*
    FROM hr_roster_01 l
    INNER JOIN iam_accounts_01 r ON l.employee_id = r.employee_id
),

active_access_terminated AS (
    -- step_04: FILTER (check: CHK-HR-001)
    SELECT
        *,
        'CHK-HR-001' AS check_id,
        'Violation detected by CHK-HR-001' AS reason,
        'CHK-HR-001' AS _check_id
    FROM hr_iam_joined
    WHERE status = 'TERMINATED'
      AND account_status = 'ACTIVE'
),

with_revocation_days AS (
    -- step_05: DATE_DIFF termination_date → disabled_date (days)
    SELECT
        *,
        DATE_DIFF('day', termination_date, disabled_date) AS termination_date_to_disabled_date_days
    FROM hr_iam_joined
),

with_sla_flag AS (
    -- step_06: THRESHOLD — termination_date_to_disabled_date_days <= 1
    SELECT
        *,
        (termination_date_to_disabled_date_days <= 1) AS within_sla
    FROM with_revocation_days
),

sla_compliance AS (
    -- step_07: AGGREGATE
    SELECT
        'CHK-HR-002' AS check_id,
        COUNT(*) FILTER (WHERE within_sla) AS accounts_disabled_within_sla,
        COUNT(*) AS total_disabled_accounts,
        ROUND(COUNT(*) FILTER (WHERE within_sla)::DOUBLE / NULLIF(COUNT(*), 0), 4) AS sla_compliance_rate
    FROM with_sla_flag
),

missing_termination_date AS (
    -- step_08: COMPLETENESS check on termination_date
    SELECT
        *,
        'CHK-HR-003' AS check_id,
        'Required field termination_date is NULL or missing' AS reason
    FROM hr_roster_01
    WHERE status = 'TERMINATED'
    AND termination_date IS NULL
)

SELECT 'completeness' AS result_type, * FROM missing_termination_date;