"""Budgets and the trace, enforced in middleware under and around the model loop, never in the prompt."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from agent_framework import ChatContext, ChatMiddleware, FunctionInvocationContext, FunctionMiddleware
from pydantic import BaseModel

from .sandbox import SandboxRejectedError


class BudgetExceededError(RuntimeError):
    def __init__(self, what: str, limit: int) -> None:
        super().__init__(f"Run budget exceeded: {what} > {limit}.")
        self.what = what
        self.limit = limit


@dataclass(frozen=True, slots=True)
class RunBudget:
    max_model_calls: int = 10
    max_tool_calls: int = 12
    max_total_tokens: int = 60_000
    max_seconds: float = 120.0


class RunEvent(BaseModel):
    sequence: int
    kind: str
    name: str
    at: float
    duration_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    detail: str | None = None


@dataclass(slots=True)
class RunTrace:
    observer: Callable[[RunEvent], None] | None = None
    events: list[RunEvent] = field(default_factory=list)
    violation: Exception | None = None

    def record(
        self,
        kind: str,
        name: str,
        duration_ms: float = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        detail: str | None = None,
    ) -> None:
        event = RunEvent(
            sequence=len(self.events) + 1,
            kind=kind,
            name=name,
            at=time.time(),
            duration_ms=duration_ms,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            detail=detail,
        )
        self.events.append(event)
        if self.observer:
            self.observer(event)

    @property
    def model_calls(self) -> int:
        return sum(1 for e in self.events if e.kind == "model")

    @property
    def tool_calls(self) -> int:
        return sum(1 for e in self.events if e.kind == "tool")

    @property
    def total_tokens(self) -> int:
        return sum(e.input_tokens + e.output_tokens for e in self.events)


class BudgetedChat(ChatMiddleware):
    """Sits under the function loop, so the ceiling holds however many turns the model asks for."""

    def __init__(self, budget: RunBudget, trace: RunTrace, agent_name: str) -> None:
        self.budget = budget
        self.trace = trace
        self.agent_name = agent_name

    async def process(self, context: ChatContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if self.trace.model_calls >= self.budget.max_model_calls:
            raise BudgetExceededError("model calls", self.budget.max_model_calls)
        started = time.perf_counter()
        await call_next()
        usage = getattr(context.result, "usage_details", None) or {}
        inp = int(usage.get("input_token_count") or 0)
        out = int(usage.get("output_token_count") or 0)
        finish = getattr(context.result, "finish_reason", None)
        self.trace.record(
            "model", self.agent_name, (time.perf_counter() - started) * 1000, inp, out, str(finish) if finish else None
        )
        if self.trace.total_tokens > self.budget.max_total_tokens:
            raise BudgetExceededError("total tokens", self.budget.max_total_tokens)


class BudgetedTools(FunctionMiddleware):
    """The loop reports a tool exception to the model and continues, so a violation is parked on the trace.

    The orchestrator raises it after the loop returns. A sandbox rejection is treated the same way:
    a model that writes a DELETE does not get a second try.
    """

    def __init__(self, budget: RunBudget, trace: RunTrace) -> None:
        self.budget = budget
        self.trace = trace

    async def process(self, context: FunctionInvocationContext, call_next: Callable[[], Awaitable[None]]) -> None:
        if self.trace.tool_calls >= self.budget.max_tool_calls:
            violation = BudgetExceededError("tool calls", self.budget.max_tool_calls)
            self.trace.violation = self.trace.violation or violation
            context.terminate = True
            raise violation
        started = time.perf_counter()
        try:
            await call_next()
        except SandboxRejectedError as error:
            self.trace.violation = self.trace.violation or error
            context.terminate = True
            raise
        args = context.arguments
        detail = ", ".join(
            f"{k}={str(v)[:120]}" for k, v in (args.model_dump() if hasattr(args, "model_dump") else dict(args)).items()
        )
        self.trace.record("tool", context.function.name, (time.perf_counter() - started) * 1000, detail=detail)
