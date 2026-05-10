-- Compiled by control-monitoring compiler
-- Control: TRADE_SETTLE_001
-- Group:   grp_04_failed_settlements
-- Generated: 2026-05-10T18:19:38.164152+00:00
-- Source DSL: controls/TRADE_SETTLE_001/groups/grp_04_failed_settlements/dsl.yaml
-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)


WITH

settlements_04 AS (
    -- step_01: NORMALIZE settlements
    SELECT
        TRIM(settlement_id) AS settlement_id,
        TRIM(trade_id) AS trade_id,
        TRY_CAST(settlement_date AS DATE) AS settlement_date,
        TRY_CAST(amount_settled AS DOUBLE) AS amount_settled,
        TRIM(status) AS status
    FROM settlements
),

failed_settlements AS (
    -- step_02: FILTER (check: CHK-TS-004)
    SELECT
        *,
        'CHK-TS-004' AS check_id,
        'Violation detected by CHK-TS-004' AS reason,
        'CHK-TS-004' AS _check_id
    FROM settlements_04
    WHERE status = 'FAILED'
)

SELECT 'row_level' AS result_type, * FROM failed_settlements;