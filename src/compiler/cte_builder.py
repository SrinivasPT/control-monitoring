"""CTE builder — assembles named CTE blocks into a full SQL query."""

from __future__ import annotations

from src.models.dsl import (
    AggregateStep,
    CompletenessStep,
    DSLPlan,
    DateDiffStep,
    FilterStep,
    JoinStep,
    NormalizeStep,
    ReconciliationStep,
    ThresholdStep,
    UniquenessStep,
)

# Result-type discriminator values for each step type
_RESULT_TYPE_MAP = {
    "FILTER": "row_level",
    "COMPLETENESS": "completeness",
    "UNIQUENESS": "uniqueness",
    "RECONCILIATION": "reconciliation",
    "AGGREGATE": "aggregate",
}

# Steps that produce the final result rows (need a SELECT … from them)
_TERMINAL_TYPES = frozenset(_RESULT_TYPE_MAP.keys())


# Sentinel used to split multi-terminal SQL into separate queries.
# The executor splits on this marker and runs each sub-query independently
# to avoid UNION ALL column-count mismatches between different result schemas.
TERMINAL_SEPARATOR = "-- @@TERMINAL_SEP@@"


class CTEBuilder:
    """Builds a layered CTE SQL statement from a list of CTE blocks."""

    def __init__(self) -> None:
        self._ctes: list[tuple[str, str]] = []  # (alias, full_cte_block)
        self._terminal_aliases: list[tuple[str, str]] = []  # (alias, result_type)

    def add_cte(self, alias: str, block: str) -> None:
        """Add a named CTE block.  *block* should NOT include the trailing comma."""
        self._ctes.append((alias, block))

    def mark_terminal(self, alias: str, result_type: str) -> None:
        """Mark a CTE as a terminal (result-producing) step."""
        self._terminal_aliases.append((alias, result_type))

    def _cte_header(self) -> str:
        """Build the WITH ... CTE header (all CTEs, no final SELECT)."""
        cte_parts = []
        for i, (alias, block) in enumerate(self._ctes):
            is_last = i == len(self._ctes) - 1
            cte_parts.append(block + ("" if is_last else ","))
        return "\nWITH\n\n" + "\n\n".join(cte_parts)

    def build(self) -> str:
        """Return the complete SQL string.

        When there are multiple terminal CTEs with potentially different schemas,
        separate queries are emitted joined by TERMINAL_SEPARATOR so the executor
        can run them independently and combine results in Python.
        """
        if not self._ctes:
            return "-- (empty DSL plan)\nSELECT NULL WHERE FALSE;"

        cte_header = self._cte_header()

        if not self._terminal_aliases:
            # No terminal steps (e.g. NORMALIZE-only data-prep group).
            # Return zero rows so no false violations are emitted.
            return cte_header + "\n\nSELECT NULL::VARCHAR AS result_type WHERE FALSE;"

        if len(self._terminal_aliases) == 1:
            alias, result_type = self._terminal_aliases[0]
            return (
                cte_header
                + f"\n\nSELECT '{result_type}' AS result_type, * FROM {alias};"
            )

        # Multiple terminals — emit one full query per terminal to avoid
        # UNION ALL column-count mismatch between different result schemas.
        queries: list[str] = []
        for alias, result_type in self._terminal_aliases:
            queries.append(
                cte_header
                + f"\n\nSELECT '{result_type}' AS result_type, * FROM {alias};"
            )
        return f"\n\n{TERMINAL_SEPARATOR}\n\n".join(queries)
