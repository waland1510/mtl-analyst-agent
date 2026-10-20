# Plan

A sibling to [condo-agents](https://github.com/waland1510/condo-agents), in
Python on the Microsoft Agent Framework, answering a different question:
when the model writes code (SQL) rather than prose, where does the
boundary go and how are its numbers checked?

| # | Step | Done when |
|---|---|---|
| 1 ✅ | Scaffold: scope, catalog over checked-in BIXI data, SQL sandbox with AST rewrite and budgets, CI | 25 tests green offline |
| 2 | Analyst agent: tools `run_sql`, `describe_tables`, scripted fake model; structured answer with the result table it narrates | Answers cite result rows, never free numbers |
| 3 | Critic in code: every number in the narrative must appear in a returned table; unsupported sentences dropped | Seeded wrong-number case fails closed |
| 4 | Charts from result tables (Vega-Lite spec validated by code, rendered in the page) | A chart never shows a number the table did not return |
| 5 | Human-in-the-loop: `export_csv` and `share` need approval; run persisted and resumable | Resume from a fresh process |
| 6 | Trajectory and numeric evals: golden SQL per question, scope cases, budget cases; committed results | Fake mode green in CI |
| 7 | Azure mode: Foundry `gpt-5-mini` through the Python Agent Framework, Entra only; committed `evals/results/azure-*.md` | Same cases, real numbers |
| 8 | Page served by the API: ask, watch SQL and rows, approve; README with diagram | Reader can follow in five minutes |
| 9 | Optional: LangGraph OSS adapter for the same graph, for comparison | Same evals pass on both |
