-- Compiled by control-monitoring compiler
-- Control: TRADE_SETTLE_001
-- Group:   grp_02_settlement_sla_breach
-- Generated: 2026-05-10T18:19:38.157352+00:00
-- Source DSL: controls/TRADE_SETTLE_001/groups/grp_02_settlement_sla_breach/dsl.yaml
-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)


WITH

trades_02 AS (
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

settlements_02 AS (
    -- step_02: NORMALIZE settlements
    SELECT
        TRIM(settlement_id) AS settlement_id,
        TRIM(trade_id) AS trade_id,
        TRY_CAST(settlement_date AS DATE) AS settlement_date,
        TRY_CAST(amount_settled AS DOUBLE) AS amount_settled,
        TRIM(status) AS status
    FROM settlements
),

trades_settlements_joined AS (
    -- step_03: JOIN trades_02 INNER JOIN settlements_02 ON trade_id = trade_id
    SELECT l.*, r.*
    FROM trades_02 l
    INNER JOIN settlements_02 r ON l.trade_id = r.trade_id
),

sla_breaches AS (
    -- step_04: FILTER (check: CHK-TS-002)
    SELECT
        *,
        'CHK-TS-002' AS check_id,
        'Violation detected by CHK-TS-002' AS reason,
        'CHK-TS-002' AS _check_id
    FROM trades_settlements_joined
    WHERE status = 'SETTLED'
      AND CAST(settlement_date AS DATE) > CAST(settlement_due_date AS DATE)
)

SELECT 'row_level' AS result_type, * FROM sla_breaches;