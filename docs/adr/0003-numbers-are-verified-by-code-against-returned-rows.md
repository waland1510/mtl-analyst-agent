# 3. Every number in an answer is verified by code against the rows that came back

Date: 2026-10-20 · Status: accepted

## Context

A model narrating a result table will round, add, convert to percentages,
or quietly remember a figure from training. In an analyst, a wrong number
is the whole failure.

## Decision

The answer contract (`Answer`) is text plus the result ids it relies on.
`verify` splits the text into sentences, extracts every number, and keeps
a sentence only when every number in it appears in a result it cites, in
any common formatting (thousands separators, rounding to two decimals, a
fraction shown as a percentage). Sentences that state numbers without a
citation, or cite a result that does not contain the number, are dropped
and listed with the reason. The data year and numbers from the question
are the only free numbers.

The instructions tell the model to compute totals, shares and percentages
in SQL, never in prose, because the critic will not accept arithmetic it
cannot see.

## Rejected

- **A model critic.** The sibling repository uses one for prose claims
  over documents, where there is no ground truth to compare against. Here
  there is: the rows. Code is exact, free and deterministic.
- **Trusting the model's own citations.** A citation is a pointer; the
  check is whether the pointed-to rows contain the number.

## Consequences

Wrong numbers never reach the page; they appear in the "dropped" list with
the reason, which is also what the evals grade. The chart follows the same
rule: it is built by code from a cited result, and a request naming a
column that is not in the result is rejected (ADR 4).
