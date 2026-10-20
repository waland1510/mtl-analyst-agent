"""CLI.

`python -m mtl_analyst ask [--borough X] "question"`, `python -m mtl_analyst evals`, `python -m mtl_analyst serve`.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from .catalog import find_data_root
from .fakes import ScriptedChatClient
from .orchestrator import Orchestrator, RunStore
from .runtime import RunBudget
from .scope import Scope


def build_client(mode: str):
    if mode == "azure":
        from .azure import AzureSettings, chat_client

        return chat_client(AzureSettings.from_env())
    return ScriptedChatClient()


def mode_from_env() -> str:
    return "azure" if os.environ.get("MTL_MODE") == "azure" else "fake"


def budget_for(mode: str) -> RunBudget:
    return (
        RunBudget(max_model_calls=24, max_tool_calls=16, max_total_tokens=300_000, max_seconds=600)
        if mode == "azure"
        else RunBudget()
    )


async def ask(args: argparse.Namespace) -> int:
    mode = mode_from_env()
    repo = find_data_root().parent
    started = asyncio.get_event_loop().time()

    def show(e):
        print(
            f"  {(asyncio.get_event_loop().time() - started) * 1000:7.0f} ms  {e.kind:<6} {e.name:<14} {e.input_tokens + e.output_tokens or '':>6}  {e.detail or ''}"
        )

    orchestrator = Orchestrator(build_client(mode), RunStore(repo / "runs"), budget=budget_for(mode), observer=show)
    if args.approve or args.reject:
        run_id, approval_id = (args.approve or args.reject).split("/")
        run = await orchestrator.decide(run_id, approval_id, bool(args.approve), os.environ.get("USER", "cli"))
    else:
        print(f"[{mode}] {args.borough or 'city'} · {args.question}")
        run = await orchestrator.start(Scope(args.borough), args.question, allow_export=args.allow_export)
    print(f"\n{run.id} · {run.status}")
    for r in run.results:
        print(f"  {r.id}: {r.sql_requested}  → {len(r.rows)} rows")
    for a in run.approvals:
        if a.approved is None:
            print(
                f"  awaiting approval {a.id}: {a.tool} {a.arguments}\n  → python -m mtl_analyst ask --approve {run.id}/{a.id}"
            )
    for s in run.kept:
        print(f"  {s}")
    for d in run.dropped:
        print(f"  dropped: {d['sentence']} ({d['reason']})")
    if run.chart:
        print(f"  chart: {run.chart['description']}")
    if run.error:
        print(f"  error: {run.error}")
    return 1 if run.status == "Failed" else 0


async def evals(args: argparse.Namespace) -> int:
    from .evals import find_evals_root, load_cases, run_suite, to_json, to_markdown

    mode = mode_from_env()
    root = find_evals_root()
    cases = load_cases(root / "cases.json")
    if args.case:
        cases = [c for c in cases if c["id"] == args.case]
    client = build_client(mode)
    model = os.environ.get("MTL_CHAT_DEPLOYMENT", "gpt-5-mini") if mode == "azure" else "scripted-fake"

    def make(store, budget):
        return Orchestrator(
            client,
            store,
            budget=budget,
            observer=lambda e: print(f"  {e.kind:<6} {e.name:<14} {e.detail or ''}", file=sys.stderr),
        )

    report = await run_suite(cases, make, mode, model, Path(root.parent / "runs" / "evals"), budget_for(mode))
    stem = "latest" if mode == "fake" else f"azure-{__import__('time').strftime('%Y%m%d')}"
    (root / "results").mkdir(exist_ok=True)
    (root / "results" / f"{stem}.md").write_text(to_markdown(report))
    (root / "results" / f"{stem}.json").write_text(to_json(report))
    print(to_markdown(report))
    return 0 if report.failed == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mtl_analyst")
    sub = parser.add_subparsers(dest="command", required=True)
    p_ask = sub.add_parser("ask")
    p_ask.add_argument("question", nargs="?", default="")
    p_ask.add_argument("--borough")
    p_ask.add_argument("--allow-export", action="store_true")
    p_ask.add_argument("--approve", metavar="RUN/APPROVAL")
    p_ask.add_argument("--reject", metavar="RUN/APPROVAL")
    p_evals = sub.add_parser("evals")
    p_evals.add_argument("--case")
    p_serve = sub.add_parser("serve")
    p_serve.add_argument("--port", type=int, default=8000)
    args = parser.parse_args(argv)
    if args.command == "serve":
        import uvicorn

        uvicorn.run("mtl_analyst.api:app", host="127.0.0.1", port=args.port)
        return 0
    return asyncio.run(ask(args) if args.command == "ask" else evals(args))


if __name__ == "__main__":
    sys.exit(main())
