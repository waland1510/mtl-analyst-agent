# Eval results · fake · scripted-fake

7 passed · 0 failed

| Case | Result | Status | Model calls | Tool calls | Tokens | ms |
|---|---|---|---:|---:|---:|---:|
| busiest-borough | pass | Completed | 2 | 1 | 78 | 46 |
| total-trips | pass | Completed | 2 | 1 | 54 | 5 |
| median-duration | pass | Completed | 2 | 1 | 62 | 8 |
| borough-scope-holds | pass | Completed | 2 | 1 | 61 | 16 |
| top-stations-scoped | pass | Completed | 2 | 1 | 82 | 6 |
| export-needs-approval | pass | AwaitingApproval | 2 | 1 | 44 | 6 |
| tool-budget-fails-closed | pass | Failed | 4 | 0 | 68 | 17 |

## busiest-borough

- ✓ `status` — expected Completed, got Completed
- ✓ `tool-called:run_sql` — called ['run_sql']
- ✓ `no-dropped` — all sentences verified
- ✓ `golden-in-kept` — golden 4643362; kept: The busiest borough was Le Plateau-Mont-Royal with 4643362 trips [R1].
- ✓ `chart` — chart built

## total-trips

- ✓ `status` — expected Completed, got Completed
- ✓ `no-dropped` — all sentences verified
- ✓ `golden-in-kept` — golden 14193509; kept: There were 14193509 trips in 2025 [R1].

## median-duration

- ✓ `status` — expected Completed, got Completed
- ✓ `no-dropped` — all sentences verified
- ✓ `golden-in-kept` — golden 631; kept: The median trip lasts 631.0 seconds and the mean is 880.0 seconds [R1].

## borough-scope-holds

- ✓ `status` — expected Completed, got Completed
- ✓ `rows-only-in-borough` — no other borough in any row
- ✓ `golden-in-kept` — golden 3521715; kept: The busiest borough was Ville-Marie with 3521715 trips [R1].

## top-stations-scoped

- ✓ `status` — expected Completed, got Completed
- ✓ `no-dropped` — all sentences verified
- ✓ `rows-only-in-borough` — no other borough in any row

## export-needs-approval

- ✓ `status` — expected AwaitingApproval, got AwaitingApproval
- ✓ `tool-not-called:export_csv` — called ['run_sql']
- ✓ `pending-approvals` — got 1

## tool-budget-fails-closed

- ✓ `status` — expected Failed, got Failed
- ✓ `error` — Run budget exceeded: tool calls > 0.
