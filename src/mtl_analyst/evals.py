"""Cases graded on the run record and on numbers: the golden SQL's value must appear in a kept sentence."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .answer import _cell_forms, _normalize
from .catalog import connect
from .orchestrator import AnalystRun, Orchestrator, RunStore
from .runtime import RunBudget
from .scope import Scope


@dataclass(slots=True)
class Check:
    name: str
    passed: bool
    detail: str


@dataclass(slots=True)
class CaseResult:
    id: str
    passed: bool
    status: str
    checks: list[Check]
    model_calls: int
    tool_calls: int
    tokens: int
    ms: float


@dataclass(slots=True)
class Report:
    mode: str
    model: str
    cases: list[CaseResult] = field(default_factory=list)

    @property
    def passed(self) -> int:
        return sum(1 for c in self.cases if c.passed)

    @property
    def failed(self) -> int:
        return sum(1 for c in self.cases if not c.passed)


def find_evals_root(start: Path | None = None) -> Path:
    here = (start or Path(__file__)).resolve()
    for parent in [here, *here.parents]:
        if (parent / "evals" / "cases.json").exists():
            return parent / "evals"
    raise FileNotFoundError("evals/cases.json not found")


def load_cases(path: Path) -> list[dict[str, Any]]:
    return json.loads(path.read_text())


def grade(expect: dict[str, Any], run: AnalystRun, golden_value: str | None) -> list[Check]:
    checks: list[Check] = []
    tools = [e.name for e in run.events if e.kind == "tool"]
    if "status" in expect:
        checks.append(Check("status", run.status == expect["status"], f"expected {expect['status']}, got {run.status}"))
    for tool in expect.get("tools_called", []):
        checks.append(Check(f"tool-called:{tool}", tool in tools, f"called {tools}"))
    for tool in expect.get("tools_not_called", []):
        checks.append(Check(f"tool-not-called:{tool}", tool not in tools, f"called {tools}"))
    if expect.get("no_dropped"):
        checks.append(
            Check(
                "no-dropped", not run.dropped, "; ".join(d["reason"] for d in run.dropped) or "all sentences verified"
            )
        )
    if expect.get("rows_only_in_borough"):
        leaked = [
            row
            for r in run.results
            for row in r.rows
            for cell in row
            if isinstance(cell, str) and _is_other_borough(cell, run.borough)
        ]
        checks.append(
            Check(
                "rows-only-in-borough",
                not leaked,
                f"{len(leaked)} leaked rows" if leaked else "no other borough in any row",
            )
        )
    if expect.get("golden_in_kept"):
        kept = " ".join(run.kept)
        found = golden_value is not None and any(f in _numbers(kept) for f in {golden_value})
        checks.append(Check("golden-in-kept", found, f"golden {golden_value}; kept: {kept[:160]}"))
    if expect.get("chart"):
        checks.append(Check("chart", run.chart is not None, run.chart_error or "chart built"))
    if "pending_approvals" in expect:
        pending = sum(1 for a in run.approvals if a.approved is None)
        checks.append(Check("pending-approvals", pending == expect["pending_approvals"], f"got {pending}"))
    if "error_includes" in expect:
        checks.append(Check("error", expect["error_includes"] in (run.error or ""), run.error or "(no error)"))
    return checks


def _numbers(text: str) -> set[str]:
    from .answer import _NUMBER

    return {_normalize(m.group(0)) for m in _NUMBER.finditer(text)}


_BOROUGHS: list[str] | None = None


def _is_other_borough(cell: str, borough: str | None) -> bool:
    global _BOROUGHS
    if borough is None:
        return False
    if _BOROUGHS is None:
        from .catalog import boroughs

        _BOROUGHS = boroughs(connect())
    return cell in _BOROUGHS and cell != borough


async def run_suite(
    cases: list[dict[str, Any]], make: Any, mode: str, model: str, runs_dir: Path, budget: RunBudget
) -> Report:
    report = Report(mode, model)
    con = connect()
    for case in cases:
        case_budget = budget
        if "max_tool_calls" in case:
            case_budget = RunBudget(
                budget.max_model_calls, case["max_tool_calls"], budget.max_total_tokens, budget.max_seconds
            )
        orchestrator: Orchestrator = make(RunStore(runs_dir), case_budget)
        started = time.perf_counter()
        run = await orchestrator.start(
            Scope(case["borough"]), case["question"], allow_export=case.get("allow_export", False)
        )
        ms = (time.perf_counter() - started) * 1000
        golden = None
        if sql := case["expect"].get("golden_sql"):
            value = con.execute(sql).fetchone()[0]
            golden = next(iter(_cell_forms(value) & {_normalize(str(value))}), _normalize(str(value)))
        checks = grade(case["expect"], run, golden)
        report.cases.append(
            CaseResult(
                case["id"],
                all(c.passed for c in checks),
                run.status,
                checks,
                sum(1 for e in run.events if e.kind == "model"),
                sum(1 for e in run.events if e.kind == "tool"),
                sum(e.input_tokens + e.output_tokens for e in run.events),
                ms,
            )
        )
    return report


def to_markdown(report: Report) -> str:
    lines = [
        f"# Eval results · {report.mode} · {report.model}",
        "",
        f"{report.passed} passed · {report.failed} failed",
        "",
    ]
    lines += [
        "| Case | Result | Status | Model calls | Tool calls | Tokens | ms |",
        "|---|---|---|---:|---:|---:|---:|",
    ]
    for c in report.cases:
        outcome = "pass" if c.passed else "FAIL"
        lines.append(
            f"| {c.id} | {outcome} | {c.status} | {c.model_calls} | {c.tool_calls} | {c.tokens} | {c.ms:.0f} |"
        )
    for c in report.cases:
        lines += ["", f"## {c.id}", ""]
        lines += [f"- {'✓' if ch.passed else '✗'} `{ch.name}` — {ch.detail}" for ch in c.checks]
    return "\n".join(lines) + "\n"


def to_json(report: Report) -> str:
    return json.dumps(
        {
            "mode": report.mode,
            "model": report.model,
            "passed": report.passed,
            "failed": report.failed,
            "cases": [_case_dict(c) for c in report.cases],
        },
        indent=2,
    )


def _case_dict(c: CaseResult) -> dict[str, Any]:
    return {
        "id": c.id,
        "passed": c.passed,
        "status": c.status,
        "model_calls": c.model_calls,
        "tool_calls": c.tool_calls,
        "tokens": c.tokens,
        "ms": round(c.ms),
        "checks": [{"name": ch.name, "passed": ch.passed, "detail": ch.detail} for ch in c.checks],
    }
