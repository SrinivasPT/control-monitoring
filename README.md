# Run
```bash
pip install -r requirements.txt
python scripts/generate_fixtures.py
python scripts/ingest.py --control HR_ACCESS_001
python scripts/build.py  --control HR_ACCESS_001 --skip-llm
python scripts/execute.py --control HR_ACCESS_001
```

# Control Monitoring Engine

A deterministic, structured-data compliance automation tool. Define controls in YAML, let an LLM decompose them into execution groups and primitive DSL steps, compile those steps to SQL, and run them against evidence files with DuckDB.

---

## Quick Start

### 1. Install

```bash
pip install -r requirements.txt
```

### 2. Generate example fixtures

```bash
python scripts/generate_fixtures.py
```

This creates `data/raw/iam_accounts.xlsx` and pre-written DSL files for `HR_ACCESS_001` (no LLM API key needed for the example).

### 3. Ingest evidence

```bash
python scripts/ingest.py --control HR_ACCESS_001
```

Normalises the raw CSV/Excel files into typed Parquet and writes column schemas to `data/schemas/`.

### 4. Build (compile SQL)

```bash
# With pre-written DSL (no LLM):
python scripts/build.py --control HR_ACCESS_001 --skip-llm

# With LLM decomposition (set OPENAI_API_KEY env var first):
python scripts/build.py --control HR_ACCESS_001
```

Produces `controls/HR_ACCESS_001/build_manifest.json` and one `compiled.sql` per execution group.

### 5. Execute

```bash
python scripts/execute.py --control HR_ACCESS_001
```

Runs every group's SQL in an isolated DuckDB `:memory:` session and writes results to `results/HR_ACCESS_001/`.

---

## Architecture

The engine has three fully independent phases:

```
Phase 1 — Ingestion
  scripts/ingest.py
    → reads CSV / Excel / Parquet evidence files
    → normalises column names and coerces types (Polars + openpyxl)
    → writes typed Parquet + schema YAML (idempotent)

Phase 2 — Build
  scripts/build.py
    → LLM decomposes control.yaml into groups  (group manifest)
    → LLM generates primitive DSL steps per group
    → validator rejects bad DSL before SQL is ever generated
    → compiler translates DSL → layered CTE SQL  (one file per group)
    → writes build_manifest.json

Phase 3 — Execute
  scripts/execute.py
    → loads build_manifest.json
    → runs each group's compiled.sql in isolated DuckDB connection
    → parses rows by result_type discriminator (row_level | aggregate | completeness | …)
    → merges into violations.json / metrics.json / audit.json
```

### Key design principles

| Principle | Detail |
|---|---|
| SQL is a compiled artifact | Never write SQL by hand; the compiler generates it from DSL |
| LLM constrained to decomposition only | LLMs produce YAML (groups, DSL), never SQL |
| Idempotent artifacts | Existing file = use as-is; `--force` to regenerate |
| Isolated execution | Each group gets its own DuckDB `:memory:` connection |
| Uniform output shape | Every terminal CTE emits a `result_type` discriminator column |

---

## Directory Layout

```
control-monitoring/
├── config/
│   └── settings.yaml          # Global settings (paths, LLM config, execution)
├── controls/
│   └── <CONTROL_ID>/
│       ├── control.yaml        # Control definition
│       ├── decomposition.yaml  # Group manifest (LLM-generated or hand-written)
│       ├── build_manifest.json # Build artefact index + checksums
│       └── groups/
│           └── <GROUP_ID>/
│               ├── dsl.yaml    # Primitive step plan (LLM-generated or hand-written)
│               └── compiled.sql
├── data/
│   ├── raw/                    # Source evidence files (CSV, Excel, Parquet)
│   ├── normalized/             # Typed Parquet output from ingestion
│   └── schemas/                # Per-dataset column schema YAML
├── results/
│   └── <CONTROL_ID>/
│       ├── violations.json     # All row-level violations (merged)
│       ├── metrics.json        # All aggregate metrics (merged)
│       ├── audit.json          # Execution audit trail
│       └── groups/
│           └── <GROUP_ID>/
│               └── results.json
├── scripts/
│   ├── ingest.py
│   ├── build.py
│   ├── execute.py
│   └── generate_fixtures.py   # Creates sample data and pre-written DSL
├── src/
│   ├── config.py
│   ├── ingestion/
│   ├── decomposer/
│   ├── compiler/
│   │   └── primitives/        # One module per DSL step type
│   ├── runtime/
│   ├── models/
│   └── utils/
└── tests/
    ├── ingestion/
    ├── compiler/
    ├── decomposer/
    └── runtime/
```

---

## Control Definition Format

```yaml
control:
  id: HR_ACCESS_001
  name: "Terminated Employee Active Access Review"
  version: "1.0"
  owner: "IAM Risk Team"

datasets:
  - id: hr_roster
    file: "hr_roster.csv"          # relative to data/raw/
    required_columns: [employee_id, status, termination_date]

  - id: iam_accounts
    file: "iam_accounts.xlsx"
    sheet: "Accounts"
    required_columns: [employee_id, account_status, last_modified]

checks:
  - id: terminated_active_access
    type: row_level
    description: "Flag terminated employees with active IAM accounts"
    severity: critical

  - id: access_revocation_sla
    type: aggregate
    description: ">=95% of terminated employees must have access revoked within 7 days"
    threshold:
      operator: ">="
      value: 0.95
    severity: high

  - id: missing_termination_date
    type: completeness
    check_field: termination_date
    dataset: hr_roster
    severity: medium
```

### Supported check types

| Type | Description |
|---|---|
| `row_level` | Each failing row becomes a `Violation` |
| `aggregate` | Computes a metric and compares against a threshold |
| `completeness` | Flags rows with a required field null/empty |
| `reconciliation` | Left-joins two datasets and flags unmatched records |
| `temporal` | Computes date differences and applies SLA thresholds |

---

## Supported DSL Primitives

| Primitive | Purpose |
|---|---|
| `NORMALIZE` | Select + type-cast from a dataset using its schema |
| `JOIN` | INNER / LEFT / FULL JOIN two aliases on declared keys |
| `FILTER` | SELECT with WHERE clause; outputs violations |
| `AGGREGATE` | GROUP BY + metric expressions; outputs pass/fail metrics |
| `DATE_DIFF` | Add a computed date-difference column |
| `THRESHOLD` | Add a boolean flag column from a condition |
| `COMPLETENESS` | Select rows where a required field is NULL |
| `UNIQUENESS` | Use window COUNT to detect duplicate records |
| `RECONCILIATION` | LEFT JOIN + IS NULL to find unmatched records |

---

## Configuration

`config/settings.yaml` controls all key behaviours:

```yaml
paths:
  controls: controls/
  data_raw: data/raw/
  data_normalized: data/normalized/
  data_schemas: data/schemas/
  results: results/

llm:
  provider: openai          # openai | anthropic
  model: gpt-4o
  max_retries: 3
  timeout_seconds: 60

execution:
  duckdb_threads: 4
  duckdb_memory_limit: "2GB"

logging:
  level: INFO
  format: json              # json | text
```

LLM credentials are read from environment variables:

```bash
export OPENAI_API_KEY=sk-...
export ANTHROPIC_API_KEY=sk-ant-...
```

---

## Running Tests

```bash
pytest tests/ -v
```

---

## Skipping LLM

Use `--skip-llm` with `build.py` to rely on pre-written `decomposition.yaml` and `dsl.yaml` files. The example `HR_ACCESS_001` control ships with these files so it works out of the box.

```bash
python scripts/build.py --control HR_ACCESS_001 --skip-llm
```

---

## Output Files

### `violations.json`

```json
[
  {
    "control_id": "HR_ACCESS_001",
    "group_id": "grp_02_access_violations",
    "check_id": "terminated_active_access",
    "severity": "critical",
    "reason": "Violation detected",
    "evidence": {"employee_id": "EMP-0003", "status": "TERMINATED", "account_status": "ACTIVE"},
    "detected_at": "2026-05-10T12:00:00+00:00"
  }
]
```

### `metrics.json`

```json
[
  {
    "control_id": "HR_ACCESS_001",
    "group_id": "grp_03_sla_metrics",
    "check_id": "access_revocation_sla",
    "severity": "high",
    "metric_name": "sla_rate",
    "value": 0.88,
    "threshold_operator": ">=",
    "threshold_value": 0.95,
    "passed": false,
    "evaluated_at": "2026-05-10T12:00:00+00:00"
  }
]
```
