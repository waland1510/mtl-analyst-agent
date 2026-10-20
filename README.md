# mtl-analyst-agent

[![ci](https://github.com/waland1510/mtl-analyst-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/waland1510/mtl-analyst-agent/actions/workflows/ci.yml)

An analyst agent over Montréal open data (BIXI bike-share trips, 2025),
in Python on the Microsoft Agent Framework. The model writes SQL; it never
runs it. Every query goes through a sandbox that rewrites the AST to
inject the caller's row-level scope, allows only catalog reads, and
enforces a query count and a timeout. The numbers in an answer are checked
by code against the rows that actually came back.

Sibling of [condo-agents](https://github.com/waland1510/condo-agents)
(.NET, retrieval over documents). Same posture, different question: there
the model drives control flow; here it writes code.

Status: step 1 of the [plan](docs/plan.md). Scope, catalog and sandbox are
in place and tested; the agent comes next.

## Run

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q            # no network: the data is checked in
```

## Reading guide

1. [ADR 2](docs/adr/0002-scope-is-rewritten-into-the-sql-ast.md) and
   [sandbox.py](src/mtl_analyst/sandbox.py): the boundary is the rewritten
   AST. [test_sandbox.py](tests/test_sandbox.py) asks for other boroughs by
   name and gets nothing.
2. [catalog.py](src/mtl_analyst/catalog.py): the only three tables the model
   can name, and the text it is told about them.
3. [data/README.md](data/README.md): where the data comes from and how the
   three small files were derived from the 2.8 GB export.
