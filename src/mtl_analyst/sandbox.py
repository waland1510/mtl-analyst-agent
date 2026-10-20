"""Every query the model writes runs through here. The boundary is the rewritten AST, not the prompt."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import duckdb
import sqlglot
from sqlglot import exp

from .catalog import TABLES
from .scope import Scope

_FORBIDDEN_FUNCTIONS = {
    "read_csv",
    "read_csv_auto",
    "read_parquet",
    "read_json",
    "read_json_auto",
    "getenv",
    "glob",
    "sniff_csv",
    "read_text",
    "read_blob",
}


class SandboxRejectedError(ValueError):
    pass


class QueryBudgetExceededError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class QueryBudget:
    max_rows: int = 500
    timeout_s: float = 10.0
    max_queries: int = 12


@dataclass(slots=True)
class QueryResult:
    sql_requested: str
    sql_executed: str
    columns: list[str]
    rows: list[tuple]
    truncated: bool
    elapsed_ms: float


@dataclass(slots=True)
class SqlSandbox:
    con: duckdb.DuckDBPyConnection
    scope: Scope
    budget: QueryBudget = field(default_factory=QueryBudget)
    executed: int = 0

    def rewrite(self, sql: str) -> str:
        try:
            statements = sqlglot.parse(sql, read="duckdb")
        except sqlglot.errors.ParseError as error:
            raise SandboxRejectedError(f"SQL does not parse: {error}") from error
        if len(statements) != 1 or statements[0] is None:
            raise SandboxRejectedError("Exactly one statement is allowed.")
        tree = statements[0]
        if not isinstance(tree, exp.Select | exp.Union):
            raise SandboxRejectedError(f"Only SELECT is allowed, not {type(tree).__name__}.")

        for node in tree.walk():
            if isinstance(node, exp.Anonymous | exp.Func) and node.name.lower() in _FORBIDDEN_FUNCTIONS:
                raise SandboxRejectedError(f"Function {node.name} is not allowed.")
            if isinstance(
                node, exp.Command | exp.Set | exp.Pragma | exp.Create | exp.Insert | exp.Update | exp.Delete | exp.Drop
            ):
                raise SandboxRejectedError(f"{type(node).__name__} is not allowed.")

        ctes = {cte.alias_or_name for cte in tree.find_all(exp.CTE)}

        def scope_table(node: exp.Expression) -> exp.Expression:
            if not isinstance(node, exp.Table):
                return node
            name = node.name
            if name in ctes:
                return node
            if node.db or node.catalog or name not in TABLES:
                raise SandboxRejectedError(f"Table {node.sql()} is not in the catalog.")
            column = TABLES[name].scope_column
            if self.scope.borough is None or column is None:
                return node
            inner = exp.select("*").from_(name).where(exp.column(column).eq(exp.Literal.string(self.scope.borough)))
            return exp.Subquery(this=inner, alias=exp.TableAlias(this=exp.to_identifier(node.alias or name)))

        tree = tree.transform(scope_table)

        if isinstance(tree, exp.Select) and tree.args.get("limit") is None:
            tree = tree.limit(self.budget.max_rows + 1)
        return tree.sql(dialect="duckdb")

    def run(self, sql: str) -> QueryResult:
        if self.executed >= self.budget.max_queries:
            raise QueryBudgetExceededError(f"Query budget exceeded: {self.budget.max_queries} queries per run.")
        executed_sql = self.rewrite(sql)
        self.executed += 1

        timer = threading.Timer(self.budget.timeout_s, self.con.interrupt)
        timer.start()
        import time

        started = time.perf_counter()
        try:
            cursor = self.con.execute(executed_sql)
            rows = cursor.fetchmany(self.budget.max_rows + 1)
            columns = [d[0] for d in cursor.description or []]
        except duckdb.InterruptException as error:
            raise QueryBudgetExceededError(f"Query exceeded {self.budget.timeout_s}s.") from error
        finally:
            timer.cancel()
        elapsed = (time.perf_counter() - started) * 1000
        truncated = len(rows) > self.budget.max_rows
        return QueryResult(sql, executed_sql, columns, rows[: self.budget.max_rows], truncated, elapsed)
