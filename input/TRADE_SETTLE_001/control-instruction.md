# Control Instruction: Trade Settlement Monitoring Control
# Control ID: TRADE_SETTLE_001

## Purpose

This control monitors the settlement of financial trades to detect:
- Unmatched (unreconciled) trades
- Settlement SLA breaches (settlement not completed within T+2 business days)
- Credit limit violations (trade notional exceeds counterparty credit limit)
- Failed settlements
- Low settlement rates by counterparty

## Evidence Datasets

### Dataset 1: `trades`

All trades booked in the trading system. Key columns:

- `trade_id` – Unique trade identifier (e.g., `TRD-001`)
- `counterparty_id` – References `counterparties.counterparty_id`
- `trade_date` – Date trade was executed (`YYYY-MM-DD`)
- `settlement_due_date` – Contractual settlement date (`YYYY-MM-DD`); typically T+2
- `notional_amount` – Trade notional value in base currency (decimal)
- `currency` – Currency code (e.g., `USD`, `EUR`)
- `status` – `OPEN`, `SETTLED`, `FAILED`, `PENDING`

### Dataset 2: `settlements`

Records of actual settlements. Key columns:

- `settlement_id` – Unique settlement identifier
- `trade_id` – References `trades.trade_id`
- `settlement_date` – Actual settlement date (`YYYY-MM-DD`)
- `amount_settled` – Amount actually settled (decimal)
- `status` – `SETTLED`, `FAILED`, `PENDING`

### Dataset 3: `counterparties`

Counterparty reference data. Key columns:

- `counterparty_id` – Unique counterparty ID (e.g., `CP-001`)
- `name` – Counterparty name
- `credit_limit` – Maximum allowable exposure in base currency (decimal)
- `risk_rating` – `LOW`, `MEDIUM`, `HIGH`, `CRITICAL`
- `status` – `ACTIVE`, `SUSPENDED`, `INACTIVE`

## Checks

### CHK-TS-001: Unmatched Trades (Reconciliation)
Find all trades in `trades` that have no corresponding record in `settlements`
(using `trade_id` as the key). These are unmatched/unreconciled trades.

### CHK-TS-002: Settlement SLA Breach (Row-Level)
Join `trades` to `settlements` on `trade_id`. Find trades where:
- `settlements.status = 'SETTLED'`
- `CAST(settlements.settlement_date AS DATE) > CAST(trades.settlement_due_date AS DATE)`

These represent settlements that occurred after the contractual deadline.

### CHK-TS-003: Credit Limit Exceeded (Row-Level)
Join `trades` to `counterparties` on `counterparty_id`. Find rows where:
- `trades.notional_amount > counterparties.credit_limit`
- `trades.status` is not `FAILED` (exclude already-failed trades)

### CHK-TS-004: Failed Settlements (Row-Level)
Identify all rows in `settlements` where `status = 'FAILED'`.

### CHK-TS-005: Settlement Rate by Status (Aggregate)
On the `settlements` dataset, compute:
- `total_settlements` = COUNT(*)
- `settled_count` = COUNT(*) where status = 'SETTLED'
- `failed_count` = COUNT(*) where status = 'FAILED'
- `pending_count` = COUNT(*) where status = 'PENDING'
- `settlement_rate` = settled_count / total_settlements (as a decimal ratio)
