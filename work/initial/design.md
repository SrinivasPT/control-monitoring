# Enterprise Control Monitoring Engine — Detailed Design

**Version:** 1.0  
**Date:** 2026-05-10  
**Status:** Living Document  

---

## Table of Contents

1. [Purpose and Scope](#1-purpose-and-scope)
2. [Core Design Principles](#2-core-design-principles)
3. [Phase Architecture](#3-phase-architecture)
4. [Idempotent Artifact Strategy](#4-idempotent-artifact-strategy)
5. [Directory Layout](#5-directory-layout)
6. [Control Definition Model](#6-control-definition-model)
7. [Evidence Normalization (Ingestion Phase)](#7-evidence-normalization-ingestion-phase)
8. [Decomposer (Build Phase)](#8-decomposer-build-phase)
9. [SQL Compiler (Build Phase)](#9-sql-compiler-build-phase)
10. [Runtime / Execution Phase](#10-runtime--execution-phase)
11. [Primitive Operation Library](#11-primitive-operation-library)
12. [Results and Explainability Model](#12-results-and-explainability-model)
13. [Run Scripts](#13-run-scripts)
14. [Configuration Schema Reference](#14-configuration-schema-reference)
15. [Technology Stack](#15-technology-stack)
16. [Testing Strategy](#16-testing-strategy)
17. [MVP Scope and Iteration Plan](#17-mvp-scope-and-iteration-plan)
18. [What This System Is Not](#18-what-this-system-is-not)

---

## 1. Purpose and Scope

### What This System Does

The Enterprise Control Monitoring Engine is a **deterministic, structured-data compliance automation tool**. It ingests enterprise evidence files (HR rosters, IAM exports, invoice ledgers, etc.), executes auditor-defined controls against that evidence, and produces explainable pass/fail results with full audit trails.

### What It Must Support

- Multiple controls, each independently defined
- Multiple evidence files per control (CSV, Excel, Parquet)
- Multiple check types per control:
  - Row-level checks (individual record violations)
  - Aggregate checks (metric thresholds)
  - Cross-file reconciliation (join-based)
  - Temporal/SLA checks (date arithmetic)
- Manual correction of any intermediate artifact without losing work
- Independent execution of each pipeline phase
- Fully explainable, auditable outputs

### What It Explicitly Does Not Do

See [Section 18](#18-what-this-system-is-not) for the full exclusion list. In summary: no AI agents, no semantic reasoning, no probabilistic logic, no autonomous SQL generation.

---

## 2. Core Design Principles

These principles drive every design decision. Each is stated with its rationale.

---

### 2.1 SQL Is a Compiled Artifact, Not the Source of Truth

**Decision:** SQL is generated deterministically from a structured logical plan. It is never hand-authored as the primary control definition.

**Rationale:** Hand-written SQL is opaque to non-engineers, fragile to schema changes, and untestable at the control-logic level. By keeping the source of truth in declarative YAML (control definition + decomposition plan), the SQL becomes a reproducible output — like bytecode from source. This also enables regenerating SQL from updated plans without losing the original intent.

---

### 2.2 LLM Role Is Strictly Constrained to Decomposition Only

**Decision:** LLMs only assist with two tightly scoped translation steps: (1) grouping a control's checks into logical execution groups, and (2) translating each group's intent into a structured primitive step plan (DSL). They never generate SQL, never make runtime decisions, and never run queries.

**Rationale:** LLMs produce non-deterministic output. Their value in this system is as a one-time translator from human language to a validated, human-readable structure. After those two translation steps, every downstream action is deterministic and auditable. Constraining LLMs strictly to these decomposition steps means the system is safe to audit: every execution can be traced back to a deterministic plan, not a probabilistic model output.

---

### 2.3 Phases Are Independent and Explicitly Separated

**Decision:** Ingestion, Build, and Execution are fully independent phases. Each can be run alone. No phase calls another phase internally.

**Rationale:** Independence gives operators control. Ingestion can be re-run to pick up new evidence without rebuilding SQL. Build can be re-run to re-decompose or recompile without touching normalized data. Execution can be re-run on demand against already-built artifacts. This separation also enables debugging a single phase without side effects on others.

---

### 2.4 Idempotent Artifact Generation

**Decision:** Every generated file (normalized Parquet, schema files, decomposition.yaml, per-group DSL files, per-group compiled SQL) is written only if it does not already exist. Existing files are used as-is, even if the source inputs changed.

**Rationale:** This is the key enabler for **manual correction**. An operator can adjust a generated group DSL (e.g., to fix a primitive the LLM got wrong), fix a compiled SQL for one group, or correct a schema — and re-run the subsequent phases without losing that correction. It also protects against accidental regeneration overwriting days of manual tuning. When a regeneration is genuinely needed, files must be explicitly deleted or a `--force` flag passed to the phase script.

---

### 2.5 Modularity: Each Configuration File Is Self-Contained and Correctable

**Decision:** All configuration artifacts (control definitions, schema files, decomposition plans, compiled SQL) are standalone files that can be opened, edited, and committed to version control independently.

**Rationale:** Enterprise compliance teams include non-engineers (auditors, risk analysts) who need to review and approve what the system does. Self-contained, human-readable YAML/SQL artifacts enable that review. If any artifact is wrong, it can be corrected in place without modifying source code.

---

### 2.6 All Execution Is Local and DuckDB-Based

**Decision:** DuckDB is the single execution engine. All SQL runs in-process. No external database required.

**Rationale:** DuckDB is embeddable, fast for analytical queries over Parquet/CSV, requires no infrastructure, and produces consistent results. Local-first execution removes network dependencies, simplifies debugging, and makes the system portable. This is the right choice for an MVP that needs to be provably correct before adding scale.

---

### 2.7 Simplicity Over Abstraction

**Decision:** Avoid frameworks, orchestrators, agents, and premature abstractions. Use plain Python functions, Pydantic models, and YAML files.

**Rationale:** Unnecessary abstraction is the primary cause of debugging difficulty in data systems. A flat, readable codebase that a new engineer can trace end-to-end in one sitting is more valuable than a clever framework. Abstractions should only be introduced when a concrete need has been demonstrated twice.

---

## 3. Phase Architecture

The system has three phases. They are executed in order but are independently invokable.

```
┌──────────────────────────────────────────────────────────────────────┐
│                         INGESTION PHASE                              │
│                                                                      │
│  Raw Evidence Files (CSV / Excel / Parquet)                          │
│         ↓                                                            │
│  Column Sanitization → Type Inference → Date Standardization         │
│         ↓                                                            │
│  Normalized Parquet (one file per dataset)                           │
│  Schema YAML (per dataset, manually correctable)                     │
└──────────────────────────────────────────────────────────────────────┘
                              ↓ (artifacts written to disk)
┌──────────────────────────────────────────────────────────────────────┐
│                           BUILD PHASE                                │
│                                                                      │
│  control.yaml                                                        │
│         ↓                                                            │
│  ┌─── Step 1: Group Decomposition (LLM) ───────────────────────────┐ │
│  │  Partitions all checks into named logical groups               │ │
│  │  decomposition.yaml  (group manifest, idempotent)              │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│         ↓  (for each group)                                          │
│  ┌─── Step 2: DSL Generation (LLM, per group) ────────────────────┐ │
│  │  Translates group intent → ordered primitive steps             │ │
│  │  groups/<group_id>/dsl.yaml  (idempotent per group)            │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│         ↓  (for each group)                                          │
│  ┌─── Step 3: SQL Compilation (deterministic, per group) ─────────┐ │
│  │  Compiles DSL → layered CTE SQL                                │ │
│  │  groups/<group_id>/compiled.sql  (idempotent per group)        │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│         ↓                                                            │
│  build_manifest.json  (covers all groups, checksums)                 │
└──────────────────────────────────────────────────────────────────────┘
                              ↓ (artifacts written to disk)
┌──────────────────────────────────────────────────────────────────────┐
│                        EXECUTION PHASE                               │
│                                                                      │
│  For each group (in order declared in decomposition.yaml):           │
│    groups/<group_id>/compiled.sql + Normalized Parquet               │
│         ↓                                                            │
│    DuckDB: Register datasets → Execute group SQL                     │
│         ↓                                                            │
│    groups/<group_id>/results.json  (group-level raw output)          │
│                                                                      │
│  Merge all group results →                                           │
│    violations.json   metrics.json   audit.json                       │
└──────────────────────────────────────────────────────────────────────┘
```

### Phase Inputs and Outputs Summary

| Phase     | Inputs                                              | Outputs                                                                    |
|-----------|-----------------------------------------------------|----------------------------------------------------------------------------|
| Ingestion | Raw evidence files, normalization config             | Normalized Parquet, schema YAMLs                                           |
| Build     | control.yaml                                        | decomposition.yaml, groups/*/dsl.yaml, groups/*/compiled.sql, build_manifest.json |
| Execution | groups/*/compiled.sql, normalized Parquet           | groups/*/results.json, violations.json, metrics.json, audit.json           |

### Why Two Levels of Decomposition?

A non-trivial control (e.g., a SOX access review with row-level violations, SLA metrics, data completeness checks, and cross-file reconciliation) involves fundamentally different kinds of logic. Squashing all of that into one flat list of primitives compiling to one SQL statement creates:

- SQL that is hundreds of lines long and hard to reason about
- A single point of failure: any error aborts all checks
- Manual correction in one part risks breaking another unrelated check
- No way to independently test or re-run a subset of the logic

The two-level approach solves this:

1. **Group decomposition** (what groups exist) separates concerns at the logical level — data preparation, row-level checks, aggregate checks, and reconciliation are naturally distinct
2. **DSL** (how each group executes) keeps each group's SQL small, focused, and independently correctable

Groups execute sequentially by default. Their only shared state is the normalized Parquet files — there is no inter-group in-memory coupling.

---

## 4. Idempotent Artifact Strategy

Every artifact produced by the system follows this rule:

> **If the file exists at the expected path, use it. Do not overwrite it. Do not regenerate it.**

This applies to:

| Artifact | Phase | Path |
|---|---|---|
| Normalized Parquet | Ingestion | `data/normalized/<dataset>.parquet` |
| Schema YAML | Ingestion | `data/schemas/<dataset>.schema.yaml` |
| Group Manifest | Build | `controls/<control_id>/decomposition.yaml` |
| Group DSL | Build | `controls/<control_id>/groups/<group_id>/dsl.yaml` |
| Group Compiled SQL | Build | `controls/<control_id>/groups/<group_id>/compiled.sql` |
| Build Manifest | Build | `controls/<control_id>/build_manifest.json` |
| Group Results | Execution | `results/<control_id>/groups/<group_id>/results.json` |

The granularity of idempotency is intentional. A group's DSL can be corrected without affecting any other group's DSL or SQL. A group's SQL can be hand-edited without triggering recompilation of any other group.

### How Forced Regeneration Works

Each phase script accepts a `--force` flag with scoped targets:

```bash
# Force regeneration of the group manifest only (re-runs group-level LLM call)
python scripts/build.py --control HR_ACCESS_001 --force groups

# Force regeneration of one group's DSL (re-runs DSL-level LLM call for that group)
python scripts/build.py --control HR_ACCESS_001 --group grp_sla_checks --force dsl

# Force recompile SQL for one group (no LLM call — purely deterministic)
python scripts/build.py --control HR_ACCESS_001 --group grp_sla_checks --force compile

# Force everything for one control
python scripts/build.py --control HR_ACCESS_001 --force all

# Force re-normalize one dataset
python scripts/ingest.py --dataset hr_roster --force
```

### Rationale for This Pattern

Without idempotency, running any phase would silently discard operator corrections. With idempotency, every correction is durable. The `--force` flag makes intentional regeneration explicit and deliberate.

---

## 5. Directory Layout

```
control-monitoring/
│
├── controls/                          # One subdirectory per control
│   └── HR_ACCESS_001/
│       ├── control.yaml               # Control definition (source of truth, hand-authored)
│       ├── decomposition.yaml         # Group manifest: LLM-generated, manually correctable, idempotent
│       ├── build_manifest.json        # Build metadata + checksums for all groups
│       └── groups/                    # One subdirectory per execution group
│           ├── grp_01_data_prep/
│           │   ├── dsl.yaml           # Primitive step plan: LLM-generated, manually correctable
│           │   └── compiled.sql       # Compiled CTE SQL: deterministic, manually correctable
│           ├── grp_02_access_violations/
│           │   ├── dsl.yaml
│           │   └── compiled.sql
│           ├── grp_03_sla_metrics/
│           │   ├── dsl.yaml
│           │   └── compiled.sql
│           └── grp_04_completeness/
│               ├── dsl.yaml
│               └── compiled.sql
│
├── data/
│   ├── raw/                           # Raw evidence files dropped here
│   │   ├── hr_roster.csv
│   │   └── iam_accounts.xlsx
│   ├── normalized/                    # Normalized Parquet (idempotent)
│   │   ├── hr_roster.parquet
│   │   └── iam_accounts.parquet
│   └── schemas/                       # Per-dataset normalization schema (idempotent)
│       ├── hr_roster.schema.yaml
│       └── iam_accounts.schema.yaml
│
├── results/                           # Execution outputs
│   └── HR_ACCESS_001/
│       ├── groups/                    # Per-group raw results
│       │   ├── grp_01_data_prep/
│       │   │   └── results.json
│       │   ├── grp_02_access_violations/
│       │   │   └── results.json
│       │   ├── grp_03_sla_metrics/
│       │   │   └── results.json
│       │   └── grp_04_completeness/
│       │       └── results.json
│       ├── violations.json            # Merged across all groups
│       ├── metrics.json               # Merged across all groups
│       └── audit.json                 # Execution audit (covers all groups)
│
├── scripts/                           # Phase runner scripts
│   ├── ingest.py                      # Run ingestion phase
│   ├── build.py                       # Run build phase
│   └── execute.py                     # Run execution phase
│
├── src/                               # Core library modules
│   ├── ingestion/
│   │   ├── __init__.py
│   │   ├── reader.py                  # Read CSV / Excel / Parquet
│   │   ├── normalizer.py              # Column sanitization, type coercion
│   │   ├── schema.py                  # Schema YAML read/write
│   │   └── registry.py               # Dataset → file path registry
│   │
│   ├── decomposer/
│   │   ├── __init__.py
│   │   ├── group_decomposer.py        # LLM call: control → group manifest
│   │   ├── dsl_decomposer.py          # LLM call: group definition → DSL steps
│   │   ├── validator.py               # Validate DSL steps against allowed primitives
│   │   └── prompts/
│   │       ├── decompose_groups.txt   # Prompt: partition checks into groups
│   │       └── decompose_dsl.txt      # Prompt: translate group → primitive steps
│   │
│   ├── compiler/
│   │   ├── __init__.py
│   │   ├── compiler.py                # Compile one group's dsl.yaml → compiled.sql
│   │   ├── cte_builder.py             # Builds named CTE blocks
│   │   └── primitives/                # One module per primitive
│   │       ├── normalize.py
│   │       ├── join.py
│   │       ├── filter.py
│   │       ├── aggregate.py
│   │       ├── date_diff.py
│   │       ├── threshold.py
│   │       ├── completeness.py
│   │       ├── uniqueness.py
│   │       └── reconciliation.py
│   │
│   ├── runtime/
│   │   ├── __init__.py
│   │   ├── executor.py                # DuckDB session + dataset registration (per group)
│   │   ├── result_merger.py           # Merge group results into control-level outputs
│   │   └── result_parser.py           # Parse raw DuckDB output → result models
│   │
│   ├── models/
│   │   ├── __init__.py
│   │   ├── control.py                 # Pydantic: ControlDefinition
│   │   ├── decomposition.py           # Pydantic: GroupManifest, GroupDefinition
│   │   ├── dsl.py                     # Pydantic: DSLPlan, PrimitiveStep (per group)
│   │   ├── schema.py                  # Pydantic: DatasetSchema
│   │   ├── result.py                  # Pydantic: Violation, Metric, AuditRecord
│   │   └── manifest.py                # Pydantic: BuildManifest
│   │
│   └── utils/
│       ├── __init__.py
│       ├── filesystem.py              # Idempotent write helpers
│       ├── hashing.py                 # SHA-256 checksums for artifact tracking
│       └── logging.py                 # Structured logging setup
│
├── tests/
│   ├── ingestion/
│   ├── decomposer/
│   ├── compiler/
│   ├── runtime/
│   └── fixtures/                      # Sample evidence files, control YAMLs
│
├── examples/
│   ├── HR_ACCESS_001/                 # Worked example: terminated employee access
│   ├── INV_DUP_002/                   # Worked example: duplicate invoice
│   └── HR_IAM_RECON_003/             # Worked example: HR-to-IAM reconciliation
│
├── config/
│   └── settings.yaml                  # Global settings (paths, LLM config, logging)
│
└── README.md
```

### Rationale for Structure

- `controls/` is the center of gravity. Each control is a self-contained directory. An auditor can hand a reviewer just `controls/HR_ACCESS_001/` and they have everything — the definition, the group plan, each group's primitive logic, and each group's SQL — without touching source code.
- The `groups/` subdirectory makes the decomposition granularity explicit on disk. Each group directory is a standalone unit of work.
- `data/` separates raw inputs from processed outputs, preventing accidental mutation of evidence.
- `results/groups/` mirrors the `controls/groups/` structure, making it easy to trace any result back to the exact group and SQL that produced it.
- `scripts/` are the only entry points. There are no hidden entry points in `src/`.
- `src/` is a library, never executed directly. This makes it fully testable.

---

## 6. Control Definition Model

Controls are defined in YAML. The control definition is the **only** file that humans write from scratch. Everything else is generated from it (or manually corrected from a generated base).

### Schema

```yaml
# controls/HR_ACCESS_001/control.yaml

control:
  id: HR_ACCESS_001
  name: "Terminated Employee Active Access Review"
  description: >
    Verify that all terminated employees have had their access revoked
    within the required SLA window. Flag any active accounts belonging
    to terminated employees.
  version: "1.0"
  owner: "IAM Risk Team"
  tags: [access-management, hr, iam, sla]

datasets:
  - id: hr_roster
    description: "Monthly HR employee status export"
    file: "hr_roster.csv"                      # relative to data/raw/
    required_columns:
      - employee_id
      - status
      - termination_date

  - id: iam_accounts
    description: "IAM system account status snapshot"
    file: "iam_accounts.xlsx"
    sheet: "Accounts"                           # for Excel files
    required_columns:
      - employee_id
      - account_status
      - last_modified

checks:
  - id: terminated_active_access
    type: row_level
    description: "Flag terminated employees with active IAM accounts"
    conditions:
      - field: hr_roster.status
        op: eq
        value: "TERMINATED"
      - field: iam_accounts.account_status
        op: eq
        value: "ACTIVE"
    join:
      left: hr_roster.employee_id
      right: iam_accounts.employee_id
      type: inner
    severity: critical

  - id: access_revocation_sla
    type: aggregate
    description: ">=95% of terminated employees must have access revoked within 7 days"
    metric:
      numerator: "count(terminated_revoked_within_sla)"
      denominator: "count(total_terminated)"
    threshold:
      operator: ">="
      value: 0.95
    sla_days: 7
    severity: high

  - id: missing_termination_date
    type: completeness
    description: "Terminated employees must have a termination_date populated"
    dataset: hr_roster
    filter:
      field: status
      op: eq
      value: "TERMINATED"
    check_field: termination_date
    severity: medium
```

### Design Notes

- `checks` replaces the old `rules` key to be more descriptive of intent.
- Each check has a `type` that maps directly to a supported primitive category.
- `severity` is stored but does not affect execution logic — it informs result prioritization only.
- `required_columns` in dataset declarations enable early validation before any SQL runs.
- `sheet` is an Excel-specific optional field handled at the reader level.

---

## 7. Evidence Normalization (Ingestion Phase)

### Responsibilities

1. Read raw evidence files (CSV, Excel, Parquet)
2. Sanitize column names (lowercase, underscores, strip special characters)
3. Infer and coerce data types (especially dates)
4. Validate required columns are present
5. Write normalized Parquet to `data/normalized/`
6. Write schema YAML to `data/schemas/` (idempotent)

### Normalization Rules

| Rule | Example Input | Example Output |
|---|---|---|
| Lowercase all headers | `Employee ID` | `employee_id` |
| Replace spaces/hyphens with underscores | `EMP-STATUS` | `emp_status` |
| Strip non-alphanumeric characters | `Hire Date (UTC)` | `hire_date_utc` |
| Deduplicate headers | `name, name` | `name, name_1` |
| Trim whitespace from string values | `" ACTIVE "` | `"ACTIVE"` |
| Infer date columns | `"2024-01-15"`, `"01/15/2024"` | stored as DATE type |
| Coerce numeric strings | `"42"` in numeric context | `42` |

### Schema YAML (Manually Correctable)

When a dataset is first normalized, a schema file is written. If it already exists, it is used as-is, allowing manual override:

```yaml
# data/schemas/hr_roster.schema.yaml

dataset_id: hr_roster
source_file: hr_roster.csv
generated_at: "2026-05-10T08:00:00Z"

columns:
  - source_name: "Employee ID"
    normalized_name: employee_id
    type: string
    nullable: false

  - source_name: "Status"
    normalized_name: status
    type: string
    nullable: false

  - source_name: "Termination Date"
    normalized_name: termination_date
    type: date
    nullable: true
    date_formats_tried: ["%Y-%m-%d", "%m/%d/%Y"]
```

**Rationale:** By externalizing the schema into a correctable file, operators can fix type inference errors (e.g., a column that looks numeric but should be a string ID) without touching any Python code. The schema file is also the normalization contract — execution will validate that normalized Parquet matches the schema before running queries.

### Idempotency Behavior

| Condition | Action |
|---|---|
| `data/normalized/<dataset>.parquet` does not exist | Run normalization, write Parquet, write schema |
| `data/normalized/<dataset>.parquet` already exists | Skip normalization entirely |
| `data/schemas/<dataset>.schema.yaml` does not exist | Write schema from inference |
| `data/schemas/<dataset>.schema.yaml` already exists | Use existing schema (do not overwrite) |

### Excel Multi-Sheet Handling

When a control definition specifies `sheet:`, that sheet is extracted. If no sheet is specified and the workbook has multiple sheets, ingestion fails fast with a descriptive error listing the available sheet names. This prevents silent wrong-sheet reads.

---

## 8. Decomposer (Build Phase)

The Build phase runs two LLM-assisted steps sequentially, then a deterministic compilation step. All three produce independently correctable artifacts.

### Step 1 — Group Decomposition: Control → Group Manifest

The **group decomposer** reads `control.yaml` and partitions the control's checks into named logical groups. Each group represents a coherent, independently executable unit of work.

**What makes a good group?**

- Checks that share the same join and dataset scope belong in the same group
- Checks with fundamentally different computation types (row-level vs. aggregate vs. completeness) are separated into different groups
- Data preparation (normalization, joins) goes into a dedicated preparation group that other groups implicitly depend on via shared Parquet inputs

**Group Manifest: `controls/HR_ACCESS_001/decomposition.yaml`**

```yaml
# controls/HR_ACCESS_001/decomposition.yaml
# Generated by group_decomposer on 2026-05-10T09:00:00Z
# MANUALLY CORRECTABLE — will not be overwritten if this file exists

control_id: HR_ACCESS_001
generated_at: "2026-05-10T09:00:00Z"
generator: llm                   # or: manual

groups:
  - id: grp_01_data_prep
    name: "Data Preparation"
    description: >-
      Normalize HR and IAM datasets and produce the canonical joined
      view of terminated employees and their IAM account status.
    datasets: [hr_roster, iam_accounts]
    checks: []                   # No check_ids — pure data preparation
    execution_order: 1

  - id: grp_02_access_violations
    name: "Row-Level Access Violations"
    description: >-
      Identify individual terminated employees with active IAM accounts.
    datasets: [hr_roster, iam_accounts]
    checks: [terminated_active_access]
    execution_order: 2

  - id: grp_03_sla_metrics
    name: "SLA Compliance Metrics"
    description: >-
      Compute the proportion of terminated employees whose access
      was revoked within the 7-day SLA window.
    datasets: [hr_roster, iam_accounts]
    checks: [access_revocation_sla]
    execution_order: 3

  - id: grp_04_completeness
    name: "Data Completeness Checks"
    description: >-
      Flag terminated employees missing a termination_date.
    datasets: [hr_roster]
    checks: [missing_termination_date]
    execution_order: 4
```

**LLM prompt inputs for group decomposition:**

1. The full `control.yaml`
2. A list of supported group classification heuristics (row-level, aggregate, completeness, reconciliation, preparation)
3. Instruction: *"Partition the checks into named groups. Each group must have a single logical purpose. Do not infer checks not declared in the control. Emit only the group names, descriptions, datasets, and check_id assignments."*
4. A JSON schema for the group manifest (enforced via structured output)

**Idempotency:**

| Condition | Action |
|---|---|
| `decomposition.yaml` does not exist | Call LLM, validate, write file |
| `decomposition.yaml` exists | Load and use existing file, skip LLM call |
| `--force groups` passed | Delete and regenerate |

---

### Step 2 — DSL Generation: Group → Primitive Steps

For each group defined in the manifest, the **DSL decomposer** generates a `dsl.yaml` containing an ordered list of primitive operation steps. This is where the actual logic is spelled out.

The DSL decomposer runs independently per group. A group whose `dsl.yaml` already exists is skipped.

**Group DSL: `controls/HR_ACCESS_001/groups/grp_02_access_violations/dsl.yaml`**

```yaml
# controls/HR_ACCESS_001/groups/grp_02_access_violations/dsl.yaml
# Generated by dsl_decomposer on 2026-05-10T09:00:30Z
# MANUALLY CORRECTABLE — will not be overwritten if this file exists

control_id: HR_ACCESS_001
group_id: grp_02_access_violations
generated_at: "2026-05-10T09:00:30Z"
generator: llm

steps:
  - id: step_01
    type: NORMALIZE
    dataset: hr_roster
    output_alias: norm_hr

  - id: step_02
    type: NORMALIZE
    dataset: iam_accounts
    output_alias: norm_iam

  - id: step_03
    type: JOIN
    left: norm_hr
    right: norm_iam
    on:
      left_key: employee_id
      right_key: employee_id
    join_type: inner
    output_alias: joined_accounts

  - id: step_04
    type: FILTER
    input: joined_accounts
    conditions:
      - "hr_status = 'TERMINATED'"
      - "account_status = 'ACTIVE'"
    output_alias: terminated_active
    check_id: terminated_active_access
```

**Group DSL: `controls/HR_ACCESS_001/groups/grp_03_sla_metrics/dsl.yaml`**

```yaml
control_id: HR_ACCESS_001
group_id: grp_03_sla_metrics
generated_at: "2026-05-10T09:00:45Z"
generator: llm

steps:
  - id: step_01
    type: NORMALIZE
    dataset: hr_roster
    output_alias: norm_hr

  - id: step_02
    type: NORMALIZE
    dataset: iam_accounts
    output_alias: norm_iam

  - id: step_03
    type: JOIN
    left: norm_hr
    right: norm_iam
    on:
      left_key: employee_id
      right_key: employee_id
    join_type: inner
    output_alias: joined_accounts

  - id: step_04
    type: DATE_DIFF
    input: joined_accounts
    from_field: termination_date
    to_field: last_modified
    unit: days
    output_alias: days_to_revoke
    filter:
      field: hr_status
      op: eq
      value: TERMINATED

  - id: step_05
    type: THRESHOLD
    input: days_to_revoke
    condition: "days_to_revoke <= 7"
    flag_field: revoked_within_sla
    output_alias: sla_evaluated

  - id: step_06
    type: AGGREGATE
    input: sla_evaluated
    metrics:
      - name: total_terminated
        formula: "COUNT(*)"
        filter: "hr_status = 'TERMINATED'"
      - name: revoked_within_sla_count
        formula: "COUNT(*) FILTER (WHERE revoked_within_sla = true)"
      - name: sla_rate
        formula: "revoked_within_sla_count::DOUBLE / NULLIF(total_terminated, 0)"
    check_id: access_revocation_sla
```

**LLM prompt inputs for DSL generation:**

1. The control's `control.yaml` (full context)
2. The specific group definition (id, description, datasets, checks) from the group manifest
3. The full list of supported primitive types with their parameter schemas
4. Instruction: *"Emit only the primitive steps needed for this group's checks. Do not generate SQL. Do not reference datasets or checks not declared for this group. All `output_alias` values must be valid SQL identifiers."*
5. A JSON schema for the DSL output (enforced via structured output)

**DSL Validation (per group):**

- Every `type` is in the allowed primitive list
- Every `input` reference points to a previously defined `output_alias` within this group's steps
- Every `dataset` reference exists in this group's declared datasets
- Every `check_id` reference matches a check declared for this group
- No SQL strings are present anywhere in the step definitions

Validation failures produce a structured error report per group. Each group validates independently — a failing group does not block other groups.

**Idempotency:**

| Condition | Action |
|---|---|
| `groups/<group_id>/dsl.yaml` does not exist | Call LLM, validate, write file |
| `groups/<group_id>/dsl.yaml` exists | Load and validate existing file, skip LLM call |
| `--group <id> --force dsl` passed | Delete that group's DSL and regenerate |

---

## 9. SQL Compiler (Build Phase)

### What the Compiler Produces

The compiler reads a single group's `dsl.yaml` and produces a `compiled.sql` for that group. This is a **deterministic, purely functional** transformation: same DSL always produces the same SQL. The compiler runs once per group, independently.

A control with four groups produces four SQL files. Each SQL file is scoped to its group's checks, uses only its group's datasets, and produces a result set with a uniform shape (see Section 12).

### CTE Structure

Each primitive step maps to one named CTE. The final SELECT retrieves the group's results in a uniform shape.

```sql
-- controls/HR_ACCESS_001/groups/grp_02_access_violations/compiled.sql
-- Generated by compiler v1.0 on 2026-05-10T09:01:00Z
-- Group: grp_02_access_violations — Row-Level Access Violations
-- Source: controls/HR_ACCESS_001/groups/grp_02_access_violations/dsl.yaml
-- DO NOT EDIT unless you intend to prevent recompilation (idempotent)

WITH

norm_hr AS (
    -- step_01: NORMALIZE hr_roster
    SELECT
        CAST(employee_id AS VARCHAR)              AS employee_id,
        TRIM(UPPER(status))                       AS hr_status,
        TRY_CAST(termination_date AS DATE)        AS termination_date
    FROM hr_roster
),

norm_iam AS (
    -- step_02: NORMALIZE iam_accounts
    SELECT
        CAST(employee_id AS VARCHAR)              AS employee_id,
        TRIM(UPPER(account_status))               AS account_status,
        TRY_CAST(last_modified AS DATE)           AS last_modified
    FROM iam_accounts
),

joined_accounts AS (
    -- step_03: JOIN norm_hr INNER JOIN norm_iam ON employee_id
    SELECT
        h.employee_id,
        h.hr_status,
        h.termination_date,
        i.account_status,
        i.last_modified
    FROM norm_hr h
    INNER JOIN norm_iam i ON h.employee_id = i.employee_id
),

terminated_active AS (
    -- step_04: FILTER — terminated employees with active IAM accounts (check: terminated_active_access)
    SELECT
        employee_id,
        hr_status,
        account_status,
        termination_date,
        'terminated_active_access'                AS check_id,
        'Terminated employee has active IAM account' AS reason
    FROM joined_accounts
    WHERE hr_status = 'TERMINATED'
      AND account_status = 'ACTIVE'
)

SELECT 'row_level' AS result_type, * FROM terminated_active;
```

The SLA metrics group produces a separate, focused SQL file:

```sql
-- controls/HR_ACCESS_001/groups/grp_03_sla_metrics/compiled.sql
-- Group: grp_03_sla_metrics — SLA Compliance Metrics

WITH

norm_hr AS (
    -- step_01: NORMALIZE hr_roster
    SELECT
        CAST(employee_id AS VARCHAR)              AS employee_id,
        TRIM(UPPER(status))                       AS hr_status,
        TRY_CAST(termination_date AS DATE)        AS termination_date
    FROM hr_roster
),

norm_iam AS (
    -- step_02: NORMALIZE iam_accounts
    SELECT
        CAST(employee_id AS VARCHAR)              AS employee_id,
        TRIM(UPPER(account_status))               AS account_status,
        TRY_CAST(last_modified AS DATE)           AS last_modified
    FROM iam_accounts
),

joined_accounts AS (
    -- step_03: JOIN
    SELECT h.employee_id, h.hr_status, h.termination_date,
           i.account_status, i.last_modified
    FROM norm_hr h
    INNER JOIN norm_iam i ON h.employee_id = i.employee_id
),

days_to_revoke AS (
    -- step_04: DATE_DIFF
    SELECT *, DATE_DIFF('day', termination_date, last_modified) AS days_to_revoke
    FROM joined_accounts
    WHERE hr_status = 'TERMINATED'
),

sla_evaluated AS (
    -- step_05: THRESHOLD
    SELECT *, (days_to_revoke <= 7) AS revoked_within_sla
    FROM days_to_revoke
),

agg_metrics AS (
    -- step_06: AGGREGATE
    SELECT
        'access_revocation_sla'                                          AS check_id,
        COUNT(*)                                                         AS total_terminated,
        COUNT(*) FILTER (WHERE revoked_within_sla = true)                AS revoked_within_sla_count,
        ROUND(
            COUNT(*) FILTER (WHERE revoked_within_sla = true)::DOUBLE
            / NULLIF(COUNT(*), 0), 4
        )                                                                AS sla_rate,
        (ROUND(
            COUNT(*) FILTER (WHERE revoked_within_sla = true)::DOUBLE
            / NULLIF(COUNT(*), 0), 4
        ) >= 0.95)                                                       AS passed
    FROM sla_evaluated
)

SELECT 'aggregate' AS result_type, * FROM agg_metrics;
```

### Compiler Design Rules

1. **One CTE per primitive step** — no collapsing steps, even if it would be slightly more efficient. Readability and debuggability take precedence.
2. **One SQL file per group** — the compiler never merges groups into a combined SQL file. Each group's SQL is independently readable and executable.
3. **Comments in every CTE** — each CTE begins with a comment identifying the step ID, type, and purpose.
4. **No dynamic SQL** — the compiler uses string templating (not `eval`), driven by the primitive modules in `src/compiler/primitives/`.
5. **Stable naming** — CTE names come from `output_alias` in the DSL, which must be valid SQL identifiers (validated on DSL parse).
6. **Uniform output shape** — each group's final SELECT always includes a `result_type` discriminator column (`'row_level'`, `'aggregate'`, `'completeness'`, etc.) so the result merger can process all group outputs consistently.

### Compiler Idempotency (Per Group)

| Condition | Action |
|---|---|
| `groups/<group_id>/compiled.sql` does not exist | Compile from that group's dsl.yaml, write file |
| `groups/<group_id>/compiled.sql` already exists | Use existing file, skip compilation |
| `--group <id> --force compile` passed | Recompile that group's SQL only |

### Build Manifest

After a successful build, a manifest is written that covers all groups:

```json
{
  "control_id": "HR_ACCESS_001",
  "built_at": "2026-05-10T09:01:00Z",
  "group_manifest_file": "controls/HR_ACCESS_001/decomposition.yaml",
  "group_manifest_sha256": "a3f1...",
  "groups": [
    {
      "group_id": "grp_02_access_violations",
      "dsl_file": "controls/HR_ACCESS_001/groups/grp_02_access_violations/dsl.yaml",
      "dsl_sha256": "b7d2...",
      "compiled_sql_file": "controls/HR_ACCESS_001/groups/grp_02_access_violations/compiled.sql",
      "compiled_sql_sha256": "9b2c...",
      "datasets_required": ["hr_roster", "iam_accounts"],
      "checks": ["terminated_active_access"]
    },
    {
      "group_id": "grp_03_sla_metrics",
      "dsl_file": "controls/HR_ACCESS_001/groups/grp_03_sla_metrics/dsl.yaml",
      "dsl_sha256": "c4f9...",
      "compiled_sql_file": "controls/HR_ACCESS_001/groups/grp_03_sla_metrics/compiled.sql",
      "compiled_sql_sha256": "7e1a...",
      "datasets_required": ["hr_roster", "iam_accounts"],
      "checks": ["access_revocation_sla"]
    },
    {
      "group_id": "grp_04_completeness",
      "dsl_file": "controls/HR_ACCESS_001/groups/grp_04_completeness/dsl.yaml",
      "dsl_sha256": "d2b8...",
      "compiled_sql_file": "controls/HR_ACCESS_001/groups/grp_04_completeness/compiled.sql",
      "compiled_sql_sha256": "4c3f...",
      "datasets_required": ["hr_roster"],
      "checks": ["missing_termination_date"]
    }
  ],
  "generator_version": "1.0"
}
```

The manifest enables the execution phase to verify checksums per group and detect which groups have been manually edited since the last build.

---

## 10. Runtime / Execution Phase

### Execution Flow

```
1. Load build_manifest.json
2. For each group (in execution_order from decomposition.yaml):
   a. Verify group's compiled.sql checksum (warn on mismatch — manual edit detected)
   b. Verify all required normalized Parquet files exist
   c. Open a new DuckDB in-memory session (isolated per group)
   d. Register each dataset as a view: CREATE VIEW <dataset> AS SELECT * FROM '...parquet'
   e. Execute the group's compiled.sql
   f. Parse raw results using result_type discriminator column
   g. Write results/<control_id>/groups/<group_id>/results.json
3. Merge all group results:
   - Collect all row_level / completeness / reconciliation results → violations.json
   - Collect all aggregate results → metrics.json
4. Write audit.json covering all groups
```

### Dataset Registration

Datasets are registered as DuckDB views pointing to Parquet files, not loaded into memory. This keeps memory usage proportional to query footprint, not total dataset size.

```python
conn.execute(f"CREATE VIEW hr_roster AS SELECT * FROM '{parquet_path}'")
```

**Rationale:** Views are lazy. DuckDB will only scan the columns the query needs. For large evidence files this is significantly more efficient than full Parquet loads.

### Checksum Warning Behavior

If a group's `compiled.sql` has been manually edited and its checksum no longer matches the manifest, the executor logs a structured warning per group:

```
WARN: [grp_03_sla_metrics] compiled.sql checksum mismatch.
      Expected: 7e1a...  Actual: 4d9b...
      This file has been manually edited since last build.
      Proceeding with execution using the current file.
```

Execution still proceeds. The warning is recorded per group in `audit.json`. This is intentional: manual SQL edits are a supported correction workflow, and blocking execution would break the correction-then-execute cycle.

### Execution Isolation

Each **group** runs in its own DuckDB connection. Connections are never shared between groups or between controls. This means:

- A SQL error in one group does not abort other groups
- Dataset view names cannot collide between groups
- Failed groups produce an error entry in `audit.json` but do not block the remaining groups from running

### Result Parsing and Merging

Each group's executor reads its result set and dispatches rows by the `result_type` discriminator column:

- `'row_level'` / `'completeness'` / `'reconciliation'` → parsed into `Violation` objects, written to `groups/<id>/results.json`
- `'aggregate'` → parsed into `Metric` objects, written to `groups/<id>/results.json`

After all groups finish, `result_merger.py` reads all group `results.json` files and:

1. Unions all violations into `violations.json` (with `group_id` added to each record)
2. Unions all metrics into `metrics.json` (with `group_id` added to each record)
3. Produces `audit.json` with per-group execution entries

---

## 11. Primitive Operation Library

Each primitive maps to a compiler module in `src/compiler/primitives/`. Each module implements a `build_cte(step: PrimitiveStep) -> str` function that returns a SQL CTE block.

| Primitive | Description | Compiler Module |
|---|---|---|
| `NORMALIZE` | Sanitize column names, cast types, trim strings | `normalize.py` |
| `JOIN` | INNER / LEFT / FULL join on declared keys | `join.py` |
| `FILTER` | WHERE clause from declared conditions | `filter.py` |
| `AGGREGATE` | GROUP BY or whole-table metrics | `aggregate.py` |
| `DATE_DIFF` | Compute day/hour/month difference between date columns | `date_diff.py` |
| `THRESHOLD` | Apply a numeric comparison, emit boolean flag | `threshold.py` |
| `COMPLETENESS` | Count and flag NULL values in required fields | `completeness.py` |
| `UNIQUENESS` | Detect duplicates on declared key columns | `uniqueness.py` |
| `RECONCILIATION` | Identify records present in one dataset but missing in another | `reconciliation.py` |

### Adding a New Primitive

1. Add a new entry to the `PrimitiveType` enum in `src/models/decomposition.py`
2. Create `src/compiler/primitives/<new_primitive>.py` with a `build_cte()` function
3. Register the module in `src/compiler/compiler.py`'s dispatch table
4. Add the primitive to the decomposition prompt template

No other changes required. This is the extension point.

### Primitive Parameter Schemas (Pydantic)

Each primitive step is a Pydantic model with strict field validation. Models live in `src/models/dsl.py`. Example:

```python
class JoinStep(PrimitiveStep):
    type: Literal["JOIN"]
    left: str                      # output_alias of left input CTE (within this group)
    right: str                     # output_alias of right input CTE (within this group)
    on: JoinKey
    join_type: Literal["inner", "left", "full"] = "inner"
    output_alias: str

class JoinKey(BaseModel):
    left_key: str
    right_key: str
```

**Rationale:** Strict Pydantic models mean that a malformed `dsl.yaml` fails immediately at load time with a clear field-level error, not silently at SQL generation or execution time. Because each group's DSL is validated independently, a broken DSL in one group does not prevent other groups from building successfully.

---

## 12. Results and Explainability Model

### Violation Record (with Group Context)

Violation records include a `group_id` field so any violation can be traced back to the exact group and SQL that produced it:

```json
{
  "control_id": "HR_ACCESS_001",
  "group_id": "grp_02_access_violations",
  "check_id": "terminated_active_access",
  "severity": "critical",
  "reason": "Terminated employee has active IAM account",
  "evidence": {
    "employee_id": "EMP-4421",
    "hr_status": "TERMINATED",
    "termination_date": "2026-03-01",
    "account_status": "ACTIVE"
  },
  "detected_at": "2026-05-10T10:00:00Z"
}
```

### Metric Record (with Group Context)

Aggregate check results include `group_id` for the same traceability reason:

```json
{
  "control_id": "HR_ACCESS_001",
  "group_id": "grp_03_sla_metrics",
  "check_id": "access_revocation_sla",
  "severity": "high",
  "metric_name": "sla_rate",
  "value": 0.8714,
  "threshold_operator": ">=",
  "threshold_value": 0.95,
  "passed": false,
  "supporting_counts": {
    "total_terminated": 70,
    "revoked_within_sla_count": 61
  },
  "evaluated_at": "2026-05-10T10:00:00Z"
}
```

### Audit Record

The audit file covers all groups. Each group has its own entry with its own datasets, SQL path, checksum, and execution result:

```json
{
  "control_id": "HR_ACCESS_001",
  "executed_at": "2026-05-10T10:00:00Z",
  "executor_version": "1.0",
  "total_violation_count": 9,
  "total_groups": 3,
  "groups": [
    {
      "group_id": "grp_02_access_violations",
      "execution_order": 2,
      "compiled_sql_path": "controls/HR_ACCESS_001/groups/grp_02_access_violations/compiled.sql",
      "compiled_sql_sha256": "9b2c...",
      "manual_edit_warning": false,
      "datasets_used": [
        {"id": "hr_roster",    "sha256": "c7a2...", "row_count": 312},
        {"id": "iam_accounts", "sha256": "bb91...", "row_count": 287}
      ],
      "execution_duration_ms": 58,
      "status": "success",
      "violation_count": 9,
      "checks_evaluated": [
        {"check_id": "terminated_active_access", "type": "row_level", "violation_count": 9}
      ]
    },
    {
      "group_id": "grp_03_sla_metrics",
      "execution_order": 3,
      "compiled_sql_path": "controls/HR_ACCESS_001/groups/grp_03_sla_metrics/compiled.sql",
      "compiled_sql_sha256": "4d9b...",
      "manual_edit_warning": true,
      "datasets_used": [
        {"id": "hr_roster",    "sha256": "c7a2...", "row_count": 312},
        {"id": "iam_accounts", "sha256": "bb91...", "row_count": 287}
      ],
      "execution_duration_ms": 71,
      "status": "success",
      "violation_count": 0,
      "checks_evaluated": [
        {"check_id": "access_revocation_sla", "type": "aggregate", "passed": false, "sla_rate": 0.8714}
      ]
    },
    {
      "group_id": "grp_04_completeness",
      "execution_order": 4,
      "compiled_sql_path": "controls/HR_ACCESS_001/groups/grp_04_completeness/compiled.sql",
      "compiled_sql_sha256": "4c3f...",
      "manual_edit_warning": false,
      "datasets_used": [
        {"id": "hr_roster", "sha256": "c7a2...", "row_count": 312}
      ],
      "execution_duration_ms": 14,
      "status": "success",
      "violation_count": 2,
      "checks_evaluated": [
        {"check_id": "missing_termination_date", "type": "completeness", "violation_count": 2}
      ]
    }
  ]
}
```

### Why Full Explainability Matters

Compliance outputs will be reviewed by auditors who need to know exactly what data was used, what logic was applied, and what the system concluded. The combination of `violations.json + metrics.json + audit.json` provides a self-contained, version-controllable evidence package. The `audit.json` can be attached to a GRC ticket directly.

---

## 13. Run Scripts

Three scripts are the only entry points for operators. All scripts are in `scripts/`. They accept consistent CLI arguments.

### `scripts/ingest.py`

```
Runs the Ingestion Phase.

Arguments:
  --control <id>          Process only datasets declared in this control (default: all)
  --dataset <name>        Process a specific dataset by name
  --force                 Re-normalize even if Parquet already exists
  --dry-run               Show what would be normalized without writing files

Examples:
  python scripts/ingest.py
  python scripts/ingest.py --control HR_ACCESS_001
  python scripts/ingest.py --dataset hr_roster --force
  python scripts/ingest.py --dry-run
```

### `scripts/build.py`

```
Runs the Build Phase (group decomposition + DSL generation + SQL compilation).

Arguments:
  --control <id>          Build a specific control (default: all)
  --group <id>            Scope to a specific group within the control
  --force groups          Regenerate the group manifest (decomposition.yaml)
  --force dsl             Regenerate DSL for all groups (or --group scoped)
  --force compile         Recompile SQL for all groups (or --group scoped)
  --force all             Delete and regenerate all build artifacts
  --skip-llm              Skip LLM calls; use existing group manifest and DSLs, only recompile SQL
  --dry-run               Show what would be built without writing files

Examples:
  python scripts/build.py --control HR_ACCESS_001
  python scripts/build.py --control HR_ACCESS_001 --force all
  python scripts/build.py --control HR_ACCESS_001 --group grp_03_sla_metrics --force dsl
  python scripts/build.py --control HR_ACCESS_001 --group grp_03_sla_metrics --force compile
  python scripts/build.py --control HR_ACCESS_001 --skip-llm
  python scripts/build.py
```

### `scripts/execute.py`

```
Runs the Execution Phase.

Arguments:
  --control <id>          Execute a specific control (default: all)
  --group <id>            Execute only a specific group within the control
  --output-dir <path>     Override default results/ directory
  --dry-run               Validate artifacts and datasets without executing

Examples:
  python scripts/execute.py --control HR_ACCESS_001
  python scripts/execute.py --control HR_ACCESS_001 --group grp_03_sla_metrics
  python scripts/execute.py
  python scripts/execute.py --dry-run
```

`--group` is particularly useful during development or manual SQL correction: an operator can edit one group's SQL, run only that group, inspect its `results.json`, and iterate — without re-executing all other groups.

### Common Behavior Across All Scripts

- Structured JSON log output (machine-parseable)
- Human-readable console summary on completion
- Non-zero exit code on any failure (CI-compatible)
- `--dry-run` always safe — never writes files, never calls LLM, never executes SQL
- Independent: none of the scripts import from each other

### Shell Wrappers (Optional Convenience)

```bash
# scripts/ingest.sh
#!/bin/bash
set -e
python scripts/ingest.py "$@"

# scripts/build.sh
#!/bin/bash
set -e
python scripts/build.py "$@"

# scripts/execute.sh
#!/bin/bash
set -e
python scripts/execute.py "$@"
```

**Rationale for Independent Scripts:** A team may run ingestion nightly via cron, trigger builds when control definitions change (CI), and execute controls on demand or on a schedule. These are naturally different workflows with different triggers and owners. Bundling them into a single monolithic runner would remove that operational flexibility.

---

## 14. Configuration Schema Reference

### `config/settings.yaml`

```yaml
paths:
  controls_dir: controls/
  data_raw_dir: data/raw/
  data_normalized_dir: data/normalized/
  data_schemas_dir: data/schemas/
  results_dir: results/

llm:
  provider: openai                      # openai | azure_openai | anthropic
  model: gpt-4o
  temperature: 0                        # Always 0 — deterministic output required
  max_retries: 3
  timeout_seconds: 60

normalization:
  default_string_encoding: utf-8
  date_formats:
    - "%Y-%m-%d"
    - "%m/%d/%Y"
    - "%d-%m-%Y"
    - "%Y%m%d"
  null_strings: ["", "N/A", "NULL", "null", "None", "NONE", "-"]

execution:
  duckdb_threads: 4
  duckdb_memory_limit: "2GB"

logging:
  level: INFO                           # DEBUG | INFO | WARN | ERROR
  format: json                          # json | text
```

**Rationale for `temperature: 0`:** LLM temperature must be 0 for all decomposition calls. Any non-zero temperature introduces randomness into the decomposition plan, which would mean two builds of the same control could produce different SQL. This is unacceptable in a compliance context.

---

## 15. Technology Stack

| Component | Technology | Rationale |
|---|---|---|
| Language | Python 3.11+ | Ecosystem fit, readability, rich data tooling |
| Execution Engine | DuckDB | Embeddable, fast analytical SQL, excellent Parquet support, no infrastructure |
| Data Models | Pydantic v2 | Strict validation, clear error messages, JSON schema generation |
| Data Processing | Polars | Fast columnar processing for normalization; more predictable than Pandas for type handling |
| Excel Reading | openpyxl | Standard, stable, well-maintained |
| Configuration | PyYAML + Pydantic | Human-readable YAML, machine-validated models |
| LLM Client | openai / anthropic SDK | Whichever matches deployment; both wrapped behind an interface |
| Hashing | hashlib (stdlib) | SHA-256 for artifact checksums, no dependencies |
| Testing | pytest | Standard, widely understood |
| CLI | argparse (stdlib) | No extra dependencies; scripts are simple enough not to need Click |

**Deliberate Exclusions:**
- No Airflow / Prefect / Dagster — phases are independent scripts, not DAG nodes
- No FastAPI — no HTTP interface in MVP; this is a local CLI tool
- No SQLAlchemy — DuckDB's Python API is direct and sufficient
- No LangChain — adds abstraction with no benefit for a single constrained LLM call

---

## 16. Testing Strategy

### Test Categories

| Category | Location | Purpose |
|---|---|---|
| Unit tests | `tests/ingestion/`, `tests/compiler/`, etc. | Test each module in isolation |
| Integration tests | `tests/integration/` | Test full phase execution end-to-end |
| Fixture-based tests | `tests/fixtures/` | Reusable sample evidence and control definitions |

### Key Test Cases (Priority Order)

1. **Normalizer:** Column name sanitization, date inference, null string handling, duplicate header deduplication
2. **Schema idempotency:** Running ingestion twice produces identical Parquet
3. **Decomposer validator:** Rejects unknown primitives, rejects SQL in conditions, rejects undefined aliases
4. **Compiler:** Each primitive produces correct CTE SQL (tested individually)
5. **Compiler idempotency:** Running build twice does not change compiled.sql
6. **Executor:** Full HR_ACCESS_001 end-to-end with fixture data
7. **Result parser:** Violations and metrics parsed correctly
8. **Edge cases:** Empty datasets, all-null columns, zero denominators in aggregate checks

### Test Data Strategy

Fixture evidence files live in `tests/fixtures/evidence/`. They are small (20–50 rows), deterministic, and cover known violation scenarios. Every test that executes SQL uses these fixtures — never live enterprise data.

---

## 17. MVP Scope and Iteration Plan

### Phase 0 — Foundation (Week 1)

- [ ] Project structure and directory layout
- [ ] Pydantic models for all artifacts
- [ ] `config/settings.yaml` loading
- [ ] `src/utils/filesystem.py` — idempotent write helpers
- [ ] Basic logging setup

### Phase 1 — Ingestion (Week 2)

- [ ] CSV and Excel reader
- [ ] Column normalizer
- [ ] Schema YAML writer
- [ ] Parquet writer
- [ ] `scripts/ingest.py`
- [ ] Tests: normalizer, schema idempotency

### Phase 2 — Build (Week 3)

- [ ] Group decomposer (LLM call → group manifest)
- [ ] DSL decomposer (LLM call → per-group DSL)
- [ ] DSL validator (per group, independent)
- [ ] Primitive modules: NORMALIZE, JOIN, FILTER, AGGREGATE, DATE_DIFF, THRESHOLD
- [ ] CTE compiler (per group → compiled.sql)
- [ ] Build manifest writer (covers all groups)
- [ ] `scripts/build.py` with `--group` scoping
- [ ] Tests: compiler primitives, per-group idempotency, validator rejection cases

### Phase 3 — Execution (Week 4)

- [ ] DuckDB executor (per group, isolated connections)
- [ ] Dataset registration (views per group session)
- [ ] Result parser with `result_type` discriminator
- [ ] Result merger (`result_merger.py`)
- [ ] Output writers (per-group results.json + merged violations.json, metrics.json, audit.json)
- [ ] `scripts/execute.py` with `--group` scoping
- [ ] Tests: end-to-end with HR_ACCESS_001 fixture (all groups), single-group execution, group failure isolation

### Phase 4 — Remaining Primitives + Examples (Week 5)

- [ ] COMPLETENESS, UNIQUENESS, RECONCILIATION primitives
- [ ] `examples/HR_ACCESS_001/`, `examples/INV_DUP_002/`, `examples/HR_IAM_RECON_003/`
- [ ] End-to-end test for each example

### Post-MVP Candidates (Out of Scope Now)

- Web UI for result visualization
- Parallel multi-control execution
- Control versioning and historical result comparison
- Push results to GRC / ticketing systems
- Schedule-based execution
- Multiple LLM provider support (currently single provider)

---

## 18. What This System Is Not

This is a **deterministic control compiler and execution engine**. It is not:

| What it is not | Why excluded |
|---|---|
| An AI agent platform | Agents make autonomous runtime decisions; this system does not |
| A semantic reasoning engine | No NLP, no embeddings, no fuzzy matching |
| A workflow orchestrator | Phases are scripts; scheduling is the operator's responsibility |
| A self-healing system | Errors are reported, not automatically resolved |
| A graph database | All relationships are explicit SQL joins, not graph traversals |
| A probabilistic system | Every result is deterministic and reproducible |
| A microservices platform | Single-machine, single-process execution |

Controls that require any of the above capabilities are **explicitly rejected** at decomposition time. The decomposer validator will classify them as unsupported and return a structured rejection message rather than attempting to approximate unsupported behavior.

---

*End of Design Document*
