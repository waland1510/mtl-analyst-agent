# 5. Azure mode through the Python Agent Framework, Entra only, same cases

Date: 2026-10-20 · Status: accepted

## Context

Everything up to here runs on a scripted fake that picks a golden query by
keywords. The claim that the sandbox and the critic mean the same thing
against a real model is only a claim until the same eval cases run
against one.

## Decision

`MTL_MODE=azure` swaps the chat client for the Agent Framework's
`OpenAIChatCompletionClient` pointed at the Foundry endpoint with the
`gpt-5-mini` deployment. Credentials are Entra only: locally the Azure CLI
identity pinned to one subscription (which implies the tenant that owns
the resources), `DefaultAzureCredential` anywhere else. No keys, no other
Azure resource: this app needs a model and nothing more, since the data is
local DuckDB.

The eval runner is unchanged; it writes `evals/results/azure-<date>.md`
next to the fake-mode `latest.md`, and both are committed.

## What the first real run found

- On the first full run six of seven cases passed. The failure was the
  critic's, not the model's: the model wrote "the top 10 stations", and 10
  was its own `LIMIT`, not a value in the rows. Numbers the model wrote
  into a cited query are now free, because a LIMIT or a filter is a
  choice, not a claim about the data. The unit test pins it.
- The model once answered "I will export the result as requested" and
  stopped, and once simply ignored the export the user asked for. Neither
  is a prompt problem to solve with more prompt: the orchestrator now
  sends the agent back once, on the same session, when the question or
  the answer mentions an export and no `export_csv` call happened. A
  scripted fake reproduces the promise-without-action case in the tests.
- The real model calls `describe_tables` first every time, writes correct
  aggregate SQL against `daily_borough` for exact questions and against
  the sample for the median, and respects the borough scope without being
  told about it (it cannot see it).
- A whole case costs 2 to 4 model calls and 2 to 5 thousand tokens, which
  is a tenth of what the sibling repository's document agents spend on a
  comparable question. Code the model can run is cheaper to verify than
  prose the model can only cite.

## Rejected

- **The Responses-API client.** The Foundry endpoint serves chat
  completions for this deployment; the Responses client is the framework's
  default and was not needed.
- **An Azure-hosted agent (Foundry Agent Service).** It would own the tool
  loop and the session; the point of the repository is that the loop,
  the budgets and the approvals are in code the reader can see.

## Consequences

Same cases, two committed result files, one line of configuration between
them. The LangGraph adapter in the plan would be judged the same way.
