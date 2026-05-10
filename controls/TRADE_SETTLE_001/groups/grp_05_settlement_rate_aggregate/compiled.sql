-- Compiled by control-monitoring compiler
-- Control: TRADE_SETTLE_001
-- Group:   grp_05_settlement_rate_aggregate
-- Generated: 2026-05-10T18:19:38.170342+00:00
-- Source DSL: controls/TRADE_SETTLE_001/groups/grp_05_settlement_rate_aggregate/dsl.yaml
-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)


WITH

settlements_05 AS (
    -- step_01: NORMALIZE settlements
    SELECT
        TRIM(settlement_id) AS settlement_id,
        TRIM(trade_id) AS trade_id,
        TRY_CAST(settlement_date AS DATE) AS settlement_date,
        TRY_CAST(amount_settled AS DOUBLE) AS amount_settled,
        TRIM(status) AS status
    FROM settlements
),

settlement_rate_metrics AS (
    -- step_02: AGGREGATE
    SELECT
        'CHK-TS-005' AS check_id,
        COUNT(*) AS total_settlements,
        COUNT(*) FILTER (WHERE status = 'SETTLED') AS settled_count,
        COUNT(*) FILTER (WHERE status = 'FAILED') AS failed_count,
        COUNT(*) FILTER (WHERE status = 'PENDING') AS pending_count,
        ROUND(COUNT(*) FILTER (WHERE status = 'SETTLED')::DOUBLE / NULLIF(COUNT(*), 0), 4) AS settlement_rate
    FROM settlements_05
)

SELECT 'aggregate' AS result_type, * FROM settlement_rate_metrics;