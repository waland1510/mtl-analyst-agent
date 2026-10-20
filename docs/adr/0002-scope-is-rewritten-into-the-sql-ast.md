# 2. The scope is rewritten into the SQL AST, not appended to the query

Date: 2026-10-20 · Status: accepted

## Context

The model writes SQL. Whatever it writes must only ever see the rows the
caller is entitled to: a borough analyst sees trips that start in their
borough, the city analyst sees everything. Telling the model to add a
`WHERE` clause is advice. Appending `AND start_borough = …` to the outer
query is wrong as soon as the query joins, aggregates or uses a CTE.

## Decision

`SqlSandbox.rewrite` parses the statement with sqlglot and replaces every
reference to a catalog table with a subquery that carries the scope
predicate: `trips` becomes `(SELECT * FROM trips WHERE start_borough = 'X')
AS trips`. The rewrite walks the whole tree, so joins, CTEs and subqueries
all get it. Tests: `tests/test_sandbox.py`, including a query that asks for
other boroughs by name and gets no rows.

The same pass is the allowlist: one statement, `SELECT` only, catalog
tables only (no `information_schema`, no qualified names), no file-reading
or environment functions, and a row limit added when the query has none.
DuckDB runs with external access disabled so a function the allowlist
missed still cannot touch the disk.

Budgets are enforced outside the model: a query count per run and a
wall-clock timeout per query through DuckDB's interrupt.

## Rejected

- **Row-level security in a database the model connects to.** DuckDB has
  none, and it would move the boundary into configuration the repository
  cannot test.
- **A view per scope.** Views are fixed; scopes are values at run time.
- **Validating the model's `WHERE` clause.** Checking that the model
  included the right predicate is harder than putting it there.

## Consequences

The agent can be handed any SQL the model produces. Scope mistakes are
impossible by construction; what remains to verify is whether the numbers
the model narrates match the rows that came back, which is the critic's job.
