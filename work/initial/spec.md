# Enterprise Control Monitoring Engine (MVP)

## Objective

Build an MVP for an enterprise control monitoring engine that can:

- ingest structured evidence files
- normalize evidence
- decompose controls into deterministic execution steps
- compile controls into DuckDB SQL
- execute controls
- produce explainable violations and aggregate metrics

This system is intentionally scoped to deterministic structured-data controls only.

The architecture should prioritize:
- simplicity
- explainability
- debuggability
- deterministic execution
- maintainability

Avoid over-engineering and avoid autonomous AI behavior.

---

# NON-GOALS

The following are OUT OF SCOPE for MVP:

- unstructured document interpretation
- OCR
- semantic reasoning
- fuzzy matching
- embeddings
- graph databases
- autonomous agents
- workflow orchestration engines
- probabilistic reasoning
- dynamic runtime planning
- AI-generated joins
- self-healing mappings
- LLM-generated executable SQL

LLMs should ONLY assist with decomposition into supported primitives.

All execution must remain deterministic.

---

# High-Level Architecture

```text
Control Definition
        ↓
LLM Decomposer
        ↓
Logical Primitive Plan
        ↓
Deterministic SQL Compiler
        ↓
DuckDB Execution
        ↓
Explainable Results

Core Principles
1. SQL Is a Compiled Artifact

SQL must NOT be the source of truth.

Source of truth is:

control definition
decomposition plan
execution metadata

SQL is generated deterministically.

2. LLM Usage Must Be Constrained

LLM responsibilities:

decomposition
identifying supported primitives
structuring logical plans

LLM must NEVER:

execute controls
generate final SQL
infer joins automatically
make runtime decisions
3. Controls Must Be Decomposed

A control should decompose into smaller deterministic execution steps.

Example:

sub_controls:
  - normalize_hr
  - normalize_iam
  - join_accounts
  - identify_terminated_users
  - compute_sla
  - aggregate_compliance
4. Use Layered CTE SQL

Generated SQL should use layered CTEs.

Example:

WITH

normalized_hr AS (...),

normalized_iam AS (...),

joined_accounts AS (...),

violations AS (...),

metrics AS (...)

SELECT ...

Avoid gigantic monolithic SQL.

Supported Evidence Types

MVP supports:

CSV
Excel (.xlsx)
Parquet

Evidence files should be normalized internally into Parquet.

Supported Control Types
Row-Level Checks

Examples:

terminated employee has active access
duplicate invoice
missing approval
Aggregate Checks

Examples:

SLA compliance > 95%
exception rate < threshold
Cross-File Reconciliation

Examples:

employee exists in both HR and IAM
transaction totals reconcile
Temporal Checks

Examples:

disable within 7 days
approval completed before payment
Unsupported Control Types

Reject controls requiring:

semantic interpretation
subjective reasoning
NLP understanding
workflow traversal
graph traversal
fuzzy identity resolution

The system should explicitly classify unsupported controls.

Primitive Operation Library

The platform should support a deterministic primitive library.

Initial primitives:

JOIN
FILTER
THRESHOLD
AGGREGATE
DATE_DIFF
COMPLETENESS
UNIQUENESS
RECONCILIATION

The decomposer must only emit supported primitives.

Evidence Normalization Layer

Build a robust normalization layer.

Responsibilities:

sanitize column names
standardize datatypes
infer dates
trim whitespace
handle duplicate headers
select worksheets
normalize headers

Examples:

Employee ID → employee_id
EMP_ID → employee_id

Normalization should happen before control execution.

Suggested Project Structure
src/

  control_definition/
  decomposer/
  compiler/
  runtime/
  normalization/
  primitives/
  execution/
  results/
  storage/

tests/

examples/

generated/
Control Definition Model

Use YAML or JSON.

Example:

control:
  id: HR_ACCESS_001
  name: Terminated Employee Access Review

datasets:
  - hr_roster
  - iam_accounts

joins:
  - left: hr_roster.employee_id
    right: iam_accounts.employee_id

rules:
  - id: terminated_active_access
    type: row_level

    conditions:
      - hr_roster.status = 'TERMINATED'
      - iam_accounts.status = 'ACTIVE'

  - id: sla_compliance
    type: aggregate

    metric:
      formula: compliant_users / total_terminated

    threshold:
      operator: '>='
      value: 0.95
Decomposer Requirements

The decomposer should:

INPUT:

control definition
instructions
metadata

OUTPUT:

logical execution plan
ordered primitive operations

Example:

{
  "steps": [
    {
      "type": "NORMALIZE",
      "dataset": "hr_roster"
    },
    {
      "type": "JOIN",
      "left": "hr_roster",
      "right": "iam_accounts"
    },
    {
      "type": "FILTER",
      "condition": "terminated_active_accounts"
    },
    {
      "type": "AGGREGATE",
      "metric": "sla_compliance"
    }
  ]
}

The decomposer should NOT generate SQL.

Compiler Requirements

Compiler responsibilities:

convert primitives into layered CTE SQL
generate deterministic SQL
generate readable SQL
support explainability metadata

Compiler output:

{
  "sql": "...",
  "stages": [
    {
      "cte": "normalized_hr",
      "purpose": "normalize HR dataset"
    }
  ]
}
Runtime Requirements

Use DuckDB.

Runtime responsibilities:

register normalized datasets
execute generated SQL
capture execution metrics
return structured outputs
Result Model

Every violation should include:

{
  "control_id": "HR_ACCESS_001",
  "rule_id": "terminated_active_access",
  "reason": "terminated employee has active account",
  "source_rows": {
    "hr_row": 15,
    "iam_row": 42
  }
}

Aggregate outputs should include:

metrics
thresholds
pass/fail
Explainability Requirements

Persist:

original control definition
decomposition output
generated SQL
execution metadata
violations
aggregate metrics

This is mandatory for debugging and auditability.

SQL Generation Requirements

Generated SQL must:

be readable
use layered CTEs
avoid deeply nested subqueries
use stable naming conventions
be deterministic
MVP Success Criteria

The MVP is successful if it can reliably execute controls involving:

multiple evidence files
row-level checks
aggregate checks
reconciliation logic
temporal SLA checks

using:

deterministic SQL
DuckDB
explainable outputs

without requiring manual SQL writing.

Suggested Initial Use Cases

Implement these first:

Terminated employee active access check
Duplicate invoice detection
Missing approval validation
HR-to-IAM reconciliation
SLA compliance calculation

Avoid complicated controls initially.

Engineering Expectations

Code should prioritize:

clarity
modularity
deterministic behavior
testability

Avoid:

premature abstractions
distributed systems complexity
microservices
agent frameworks

Keep the MVP simple and local-first.

Technology Recommendations

Preferred stack:

Python
DuckDB
Pydantic
Pandas/Polars
PyYAML

Testing:

pytest
Important Design Philosophy

This system is NOT:

an AI agent platform
a semantic reasoning engine
a workflow orchestrator

It is:

A deterministic control compiler and execution engine
for structured enterprise evidence.