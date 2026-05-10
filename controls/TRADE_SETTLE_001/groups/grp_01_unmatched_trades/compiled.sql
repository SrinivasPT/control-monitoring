-- Compiled by control-monitoring compiler
-- Control: TRADE_SETTLE_001
-- Group:   grp_01_unmatched_trades
-- Generated: 2026-05-10T18:19:38.154277+00:00
-- Source DSL: controls/TRADE_SETTLE_001/groups/grp_01_unmatched_trades/dsl.yaml
-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)


WITH

trades_01 AS (
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

settlements_01 AS (
    -- step_02: NORMALIZE settlements
    SELECT
        TRIM(settlement_id) AS settlement_id,
        TRIM(trade_id) AS trade_id,
        TRY_CAST(settlement_date AS DATE) AS settlement_date,
        TRY_CAST(amount_settled AS DOUBLE) AS amount_settled,
        TRIM(status) AS status
    FROM settlements
),

unmatched_trades AS (
    -- step_03: RECONCILIATION trades_01 vs settlements_01 on trade_id
    SELECT
        l.*,
        'CHK-TS-001' AS check_id,
        'Record present in trades_01 but absent from settlements_01' AS reason
    FROM trades_01 l
    LEFT JOIN settlements_01 r ON l.trade_id = r.trade_id
    WHERE r.trade_id IS NULL
)

SELECT 'reconciliation' AS result_type, * FROM unmatched_trades;