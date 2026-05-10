-- Compiled by control-monitoring compiler
-- Control: TRADE_SETTLE_001
-- Group:   grp_03_credit_limit_violations
-- Generated: 2026-05-10T18:19:38.161896+00:00
-- Source DSL: controls/TRADE_SETTLE_001/groups/grp_03_credit_limit_violations/dsl.yaml
-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)


WITH

trades_03 AS (
    -- step_01: NORMALIZE trades
    SELECT
        TRIM(trade_id) AS trade_id,
        TRIM(counterparty_id) AS counterparty_id,
        TRY_CAST(trade_date AS DATE) AS trade_date,
        TRY_CAST(settlement_due_date AS DATE) AS settlement_due_date,
        TRY_CAST(notional_amount AS DOUBLE) AS notional_amount,
        TRIM(currency) AS currency,
        TRIM(status) AS status
    FROM trades
),

counterparties_03 AS (
    -- step_02: NORMALIZE counterparties
    SELECT
        TRIM(counterparty_id) AS counterparty_id,
        TRIM(name) AS name,
        TRY_CAST(credit_limit AS DOUBLE) AS credit_limit,
        TRIM(risk_rating) AS risk_rating,
        TRIM(status) AS status
    FROM counterparties
),

trades_counterparties_joined AS (
    -- step_03: JOIN trades_03 INNER JOIN counterparties_03 ON counterparty_id = counterparty_id
    SELECT l.*, r.*
    FROM trades_03 l
    INNER JOIN counterparties_03 r ON l.counterparty_id = r.counterparty_id
),

credit_limit_violations AS (
    -- step_04: FILTER (check: CHK-TS-003)
    SELECT
        *,
        'CHK-TS-003' AS check_id,
        'Violation detected by CHK-TS-003' AS reason,
        'CHK-TS-003' AS _check_id
    FROM trades_counterparties_joined
    WHERE notional_amount > credit_limit
      AND status != 'FAILED'
)

SELECT 'row_level' AS result_type, * FROM credit_limit_violations;