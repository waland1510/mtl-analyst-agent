"""HTTP surface: start a run in the background, poll it, decide an approval.

The borough in the route is the resolved scope.
"""

from __future__ import annotations

import asyncio
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .catalog import boroughs, connect, find_data_root
from .orchestrator import Orchestrator, RunStore
from .scope import Scope, ScopeError

log = logging.getLogger(__name__)


class StartRequest(BaseModel):
    question: str
    allow_export: bool = False


class Decision(BaseModel):
    approved: bool
    decided_by: str = "browser"


def _build() -> tuple[Orchestrator, str]:
    from .__main__ import budget_for, build_client, mode_from_env

    mode = mode_from_env()
    store = RunStore(Path(os.environ.get("MTL_RUNS_DIR", find_data_root().parent / "runs")))
    return Orchestrator(build_client(mode), store, budget=budget_for(mode)), mode


app = FastAPI(title="mtl-analyst-agent")
_orchestrator, _mode = _build()
_in_flight: dict[str, asyncio.Task[Any]] = {}


def _track(run_id: str, coro: Any) -> None:
    async def guarded() -> None:
        try:
            await coro
        except Exception as error:
            log.exception("run %s crashed", run_id)
            run = _orchestrator.store.load(run_id)
            if run:
                run.status = "Failed"
                run.error = str(error)
                _orchestrator.store.save(run)
        finally:
            _in_flight.pop(run_id, None)

    _in_flight[run_id] = asyncio.create_task(guarded())


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.get("/health/ready")
def ready() -> dict[str, str]:
    return {"status": "ready", "mode": _mode}


@app.get("/boroughs")
def list_boroughs() -> list[str]:
    return boroughs(connect())


@app.post("/scopes/{scope}/runs", status_code=202)
async def start(scope: str, body: StartRequest) -> dict[str, Any]:
    try:
        resolved = Scope(None if scope == "city" else scope)
    except ScopeError as error:
        raise HTTPException(400, str(error)) from error
    if not body.question.strip():
        raise HTTPException(400, "question is required")
    from .orchestrator import AnalystRun

    run = AnalystRun(
        id=AnalystRun.new_id(), borough=resolved.borough, question=body.question, allow_export=body.allow_export
    )
    _orchestrator.store.save(run)
    _track(run.id, _orchestrator.continue_run(run))
    return {"id": run.id, "status": run.status}


@app.get("/runs")
def list_runs() -> list[dict[str, Any]]:
    return [
        {"id": r.id, "status": r.status, "question": r.question, "borough": r.borough, "created_at": r.created_at}
        for r in _orchestrator.store.list()[:20]
    ]


@app.get("/runs/{run_id}")
def get_run(run_id: str) -> dict[str, Any]:
    run = _orchestrator.store.load(run_id)
    if run is None:
        raise HTTPException(404)
    payload = run.model_dump()
    payload.pop("paused_session", None)
    return {"run": payload, "in_flight": run_id in _in_flight}


@app.post("/runs/{run_id}/approvals/{approval_id}", status_code=202)
async def decide(run_id: str, approval_id: str, body: Decision) -> dict[str, Any]:
    run = _orchestrator.store.load(run_id)
    if run is None:
        raise HTTPException(404)
    if not any(a.id == approval_id and a.approved is None for a in run.approvals):
        raise HTTPException(409, f"no pending approval {approval_id}")
    _track(run_id, _orchestrator.decide(run_id, approval_id, body.approved, body.decided_by))
    return {"id": run_id, "status": "Running"}
