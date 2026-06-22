# Progress Rules

## 100-Point Weighted Checklist

ChatGPT calculates project progress from this checklist. The maximum score is 100 points.

| Area | Item | Points |
| --- | --- | ---: |
| Governance and safety | Final goal is documented and current | 3 |
| Governance and safety | `AGENTS.md` includes Codex automation safety rules | 4 |
| Governance and safety | LOW / MEDIUM / HIGH risk classes are defined | 4 |
| Governance and safety | Secret, credential, live API, main-push, and merge prohibitions are documented | 4 |
| Daily report package | Read-only DB report scope is documented | 4 |
| Daily report package | Required `.xlsx` workbook output is documented | 4 |
| Daily report package | Required Markdown summary output is documented | 3 |
| Daily report package | Required JSON summary output is documented | 3 |
| Daily report package | Sensitive values are masked or omitted | 2 |
| Daily report package | Analysis date window and generated timestamp rules are documented | 2 |
| Daily report package | Data quality warnings are documented | 2 |
| Progress calculation | Status credit rules are documented | 4 |
| Progress calculation | Daily progress percentage formula is documented | 4 |
| Progress calculation | Evidence rules distinguish merged, open PR, blocked, and proposed work | 4 |
| Progress calculation | Daily delta from previous report is documented | 3 |
| Slack reporting | Slack summary format is documented | 4 |
| Slack reporting | PASS / WARN / FAIL status rules are documented | 3 |
| Slack reporting | Risk queue format is documented | 3 |
| Slack reporting | `@Codex` proposal format is documented | 3 |
| Slack reporting | HIGH risk approval language is documented | 2 |
| Codex PR workflow | Codex branch naming and scoped commits are documented | 3 |
| Codex PR workflow | Codex opens pull requests only | 4 |
| Codex PR workflow | Direct pushes to `main` are prohibited | 3 |
| Codex PR workflow | Codex PR merges are prohibited | 3 |
| Codex PR workflow | PR summaries include changed files, risk, tests, and follow-ups | 2 |
| Validation | Docs-only validation path is documented | 3 |
| Validation | Code/test validation expectations for non-docs work are documented | 3 |
| Validation | Report output files are excluded from commits | 2 |
| Validation | External API calls are prohibited for report generation | 2 |
| Operational feedback | Daily recommendation ranking is documented | 3 |
| Operational feedback | Blocker and human approval tracking are documented | 3 |
| Operational feedback | Follow-up tasks are mapped back to checklist areas | 2 |
| Operational feedback | The next-day report carries forward unresolved items | 2 |

## Status Credit Rules

Each checklist item receives one status credit:

| Status | Credit | Meaning |
| --- | ---: | --- |
| `done` | 1.0 | Implemented, documented, and available on the base branch or explicitly accepted by the human operator. |
| `partial` | 0.5 | Work exists in an open PR, draft, or documented proposal, but is not fully accepted yet. |
| `blocked` | 0.0 | Work cannot proceed without human approval, missing data, or another external dependency. |
| `not_started` | 0.0 | No usable artifact or proposal exists. |

Open pull requests normally count as `partial`. Merged pull requests or already-existing accepted repository artifacts count as `done`.

## Daily Progress Formula

ChatGPT must calculate the daily percentage as:

```text
daily_progress_percent = round(sum(item_points * status_credit), 1)
```

Because the checklist totals 100 points, the weighted sum is already a percentage.

ChatGPT must also calculate the daily delta when a previous JSON report is available:

```text
daily_progress_delta = today.daily_progress_percent - previous.daily_progress_percent
```

If no previous JSON report exists, the delta is reported as `N/A`.

## Evidence Rules

ChatGPT should base scoring on repository documentation, accepted PRs, the daily JSON package, and explicit human approvals. It must not infer `done` from an unreviewed Slack idea alone.

For each changed score, the Markdown report should include:

- Checklist item.
- Previous status.
- Current status.
- Point impact.
- Evidence path, PR link, or approval reference.
