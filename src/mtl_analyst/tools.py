"""Tools constructed with the sandbox, and therefore the scope, already bound.

The model chooses SQL; it never sees the boundary.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Annotated, Any

from agent_framework import FunctionTool

from .catalog import schema_text
from .sandbox import SqlSandbox

PREVIEW_ROWS = 40


@dataclass(slots=True)
class StoredResult:
    id: str
    sql_requested: str
    sql_executed: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


def _plain(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    return value


class Exporter:
    """The one side effect: fake records, real writes a file. Always behind an approval."""

    def __init__(self) -> None:
        self.exported: list[tuple[str, str, int]] = []

    def export(self, result: StoredResult, filename: str) -> str:
        self.exported.append((result.id, filename, len(result.rows)))
        return f"export-{len(self.exported)}:{filename}"


@dataclass(slots=True)
class AnalystToolbox:
    sandbox: SqlSandbox
    exporter: Exporter
    results: list[StoredResult] = field(default_factory=list)

    def describe_tables(self) -> str:
        """Describe the tables and columns available to run_sql, with guidance on which table answers which question."""
        return schema_text()

    def run_sql(self, sql: Annotated[str, "A single DuckDB SELECT over the catalog tables."]) -> dict[str, Any]:
        """Run one SELECT and get back a result id with its columns and rows.

        Cite the result id when you state a number.
        """
        result = self.sandbox.run(sql)
        stored = StoredResult(
            id=f"R{len(self.results) + 1}",
            sql_requested=sql,
            sql_executed=result.sql_executed,
            columns=result.columns,
            rows=[[_plain(v) for v in row] for row in result.rows],
            truncated=result.truncated,
        )
        self.results.append(stored)
        return {
            "result_id": stored.id,
            "columns": stored.columns,
            "rows": stored.rows[:PREVIEW_ROWS],
            "row_count": len(stored.rows),
            "truncated": stored.truncated,
            "preview_only": len(stored.rows) > PREVIEW_ROWS,
        }

    def export_csv(
        self,
        result_id: Annotated[str, "The result id to export, for example R1."],
        filename: Annotated[str, "File name ending in .csv."],
    ) -> str:
        """Export a result as a CSV file. This leaves the system and needs a human's approval."""
        result = next((r for r in self.results if r.id == result_id), None)
        if result is None:
            raise ValueError(f"No result {result_id} in this run.")
        if not filename.endswith(".csv") or "/" in filename or ".." in filename:
            raise ValueError("filename must be a bare .csv name")
        return self.exporter.export(result, filename)

    def find(self, result_id: str) -> StoredResult | None:
        return next((r for r in self.results if r.id == result_id), None)

    def tools(self, *, allow_export: bool) -> list[Callable[..., Any] | FunctionTool]:
        base: list[Callable[..., Any] | FunctionTool] = [self.describe_tables, self.run_sql]
        if allow_export:
            base.append(
                FunctionTool(
                    name="export_csv",
                    description=self.export_csv.__doc__ or "",
                    func=self.export_csv,
                    approval_mode="always_require",
                )
            )
        return base
