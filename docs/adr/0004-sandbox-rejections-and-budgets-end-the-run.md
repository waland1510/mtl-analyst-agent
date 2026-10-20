# 4. A sandbox rejection or a budget violation ends the run; the model does not get a second try

Date: 2026-10-20 · Status: accepted

## Context

The Agent Framework's function loop catches a tool exception, reports it
to the model as the tool's result and continues, up to a consecutive-error
cap. For a transient error that is the right default. For a model that
wrote `DELETE FROM trips`, or that has already used its tool budget, it
means the model is invited to try again.

## Decision

`BudgetedTools` (function middleware) treats `SandboxRejectedError` and
`BudgetExceededError` alike: it parks the exception on the trace, sets
`context.terminate`, and re-raises. After the loop returns, the
orchestrator raises the parked exception and the run ends as `Failed`
with the reason. Model calls and tokens are counted in chat middleware
under the loop, so those ceilings hold however many turns the model asks
for.

## Consequences

A run that fails closed costs one model call. The eval
`tool-budget-fails-closed` and the orchestrator test for `delete from
trips` pin the behaviour. Charts and exports are built the same way:
`export_csv` is declared with `approval_mode="always_require"`, so the
loop returns an approval request instead of invoking it, the run pauses
with its session serialized, and a fresh process resumes it after the
decision (same shape as the sibling repository's ADR 7).
