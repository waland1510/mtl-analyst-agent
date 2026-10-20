"""One analyst agent per run.

The model writes SQL and prose; code runs the SQL, checks the numbers, builds the chart and stops for approval.
"""

from __future__ import annotations

import dataclasses
import json
import time
import uuid
from pathlib import Path
from typing import Any

from agent_framework import Agent, AgentSession, Content, Message
from pydantic import BaseModel, Field

from .answer import ANSWER_INSTRUCTIONS, Answer, verify
from .catalog import connect
from .charts import ChartRejectedError, build_vega_lite
from .runtime import BudgetedChat, BudgetedTools, BudgetExceededError, RunBudget, RunEvent, RunTrace
from .sandbox import QueryBudget, QueryBudgetExceededError, SandboxRejectedError, SqlSandbox
from .scope import Scope, ScopeError
from .tools import AnalystToolbox, Exporter, StoredResult


class PendingApproval(BaseModel):
    id: str
    tool: str
    arguments: dict[str, Any]
    function_call: dict[str, Any]
    approved: bool | None = None
    decided_by: str | None = None


class ResultRecord(BaseModel):
    id: str
    sql_requested: str
    sql_executed: str
    columns: list[str]
    rows: list[list[Any]]
    truncated: bool


class AnalystRun(BaseModel):
    id: str
    borough: str | None
    question: str
    allow_export: bool
    status: str = "Running"
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    events: list[RunEvent] = Field(default_factory=list)
    results: list[ResultRecord] = Field(default_factory=list)
    answer: Answer | None = None
    kept: list[str] = Field(default_factory=list)
    dropped: list[dict[str, str]] = Field(default_factory=list)
    chart: dict[str, Any] | None = None
    chart_error: str | None = None
    approvals: list[PendingApproval] = Field(default_factory=list)
    paused_session: dict[str, Any] | None = None
    error: str | None = None

    @staticmethod
    def new_id() -> str:
        return f"run-{time.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6]}"


class RunStore:
    """One JSON file per run, written atomically; enough to resume after a restart."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def save(self, run: AnalystRun) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        run.updated_at = time.time()
        target = self.directory / f"{run.id}.json"
        tmp = target.with_suffix(".tmp")
        tmp.write_text(run.model_dump_json(indent=2))
        tmp.replace(target)

    def load(self, run_id: str) -> AnalystRun | None:
        if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789-" for c in run_id):
            return None
        path = self.directory / f"{run_id}.json"
        return AnalystRun.model_validate_json(path.read_text()) if path.exists() else None

    def list(self) -> list[AnalystRun]:
        if not self.directory.exists():
            return []
        runs = [AnalystRun.model_validate_json(p.read_text()) for p in self.directory.glob("run-*.json")]
        return sorted(runs, key=lambda r: r.created_at, reverse=True)


class Orchestrator:
    def __init__(
        self,
        chat_client: Any,
        store: RunStore,
        exporter: Exporter | None = None,
        budget: RunBudget | None = None,
        observer=None,
    ) -> None:
        self.chat_client = chat_client
        self.store = store
        self.exporter = exporter or Exporter()
        self.budget = budget or RunBudget()
        self.observer = observer
        self.con = connect()

    async def start(self, scope: Scope, question: str, *, allow_export: bool = False) -> AnalystRun:
        run = AnalystRun(id=AnalystRun.new_id(), borough=scope.borough, question=question, allow_export=allow_export)
        self.store.save(run)
        return await self.continue_run(run)

    async def decide(self, run_id: str, approval_id: str, approved: bool, decided_by: str) -> AnalystRun:
        run = self.store.load(run_id)
        if run is None:
            raise KeyError(run_id)
        pending = next((a for a in run.approvals if a.id == approval_id and a.approved is None), None)
        if pending is None:
            raise ValueError(f"Run {run_id} has no pending approval {approval_id}.")
        pending.approved = approved
        pending.decided_by = decided_by
        run.status = "Running"
        self.store.save(run)
        return await self.continue_run(run)

    async def continue_run(self, run: AnalystRun) -> AnalystRun:
        trace = RunTrace(observer=self.observer)
        baseline = len(run.events)
        toolbox = AnalystToolbox(
            SqlSandbox(self.con.cursor(), Scope(run.borough), QueryBudget(max_queries=self.budget.max_tool_calls)),
            self.exporter,
        )
        for record in run.results:
            toolbox.results.append(StoredResult(**record.model_dump()))

        agent = Agent(
            self.chat_client,
            ANSWER_INSTRUCTIONS,
            name="analyst",
            tools=toolbox.tools(allow_export=run.allow_export),
            middleware=[BudgetedChat(self.budget, trace, "analyst"), BudgetedTools(self.budget, trace)],
        )
        try:
            decided = [a for a in run.approvals if a.approved is not None and not a.function_call.get("consumed")]
            if run.paused_session and decided:
                session = AgentSession.from_dict(run.paused_session)
                contents = [
                    Content.from_function_approval_response(bool(a.approved), a.id, Content.from_dict(a.function_call))
                    for a in decided
                ]
                for a in decided:
                    a.function_call["consumed"] = True
                run.paused_session = None
                messages: Any = [Message("user", contents)]
            else:
                session = agent.create_session()
                messages = run.question

            deadline = time.monotonic() + self.budget.max_seconds
            response = await agent.run(messages, session=session, options={"response_format": Answer})
            if trace.violation:
                raise trace.violation
            if time.monotonic() > deadline:
                raise BudgetExceededError("seconds", int(self.budget.max_seconds))

            self._store_results(run, toolbox)
            requests = response.user_input_requests
            if requests:
                for request in requests:
                    call = request.function_call
                    run.approvals.append(
                        PendingApproval(
                            id=request.id,
                            tool=call.name,
                            arguments=dict(call.parse_arguments() or {}),
                            function_call=call.to_dict(),
                        )
                    )
                    trace.record("gate", "approval", detail=f"{call.name} awaiting approval")
                run.paused_session = session.to_dict()
                run.status = "AwaitingApproval"
                return self._persist(run, trace, baseline)

            answer = self._parse_answer(response)
            run.answer = answer
            verdict = verify(answer, toolbox.results, allowed_free_numbers=_numbers_in(run.question))
            run.kept = [s.text for s in verdict.kept]
            run.dropped = [{"sentence": s.text, "reason": why} for s, why in verdict.dropped]
            trace.record("critic", "numbers", detail=f"{len(verdict.kept)} kept, {len(verdict.dropped)} dropped")
            if answer.chart:
                result = toolbox.find(answer.chart.result_id)
                try:
                    if result is None:
                        raise ChartRejectedError(f"{answer.chart.result_id} is not a result of this run.")
                    run.chart = build_vega_lite(answer.chart, result)
                except ChartRejectedError as error:
                    run.chart_error = str(error)
            run.status = "Rejected" if any(a.approved is False for a in run.approvals) else "Completed"
            return self._persist(run, trace, baseline)
        except (BudgetExceededError, SandboxRejectedError, QueryBudgetExceededError, ScopeError) as error:
            run.status = "Failed"
            run.error = str(error)
            return self._persist(run, trace, baseline)

    @staticmethod
    def _store_results(run: AnalystRun, toolbox: AnalystToolbox) -> None:
        run.results = [ResultRecord(**dataclasses.asdict(r)) for r in toolbox.results]

    @staticmethod
    def _parse_answer(response: Any) -> Answer:
        if response.value is not None:
            return response.value
        text = response.text or ""
        start, end = text.find("{"), text.rfind("}")
        try:
            return Answer.model_validate_json(text[start : end + 1] if start >= 0 < end else text)
        except ValueError:
            return Answer(text=text, result_ids=[])

    def _persist(self, run: AnalystRun, trace: RunTrace, baseline: int) -> AnalystRun:
        del run.events[baseline:]
        run.events.extend(e.model_copy(update={"sequence": baseline + e.sequence}) for e in trace.events)
        self.store.save(run)
        return run


def _numbers_in(text: str) -> set[str]:
    import re

    return set(re.findall(r"\d+", text))


def run_to_json(run: AnalystRun) -> str:
    return json.dumps(run.model_dump(), indent=2, default=str)
