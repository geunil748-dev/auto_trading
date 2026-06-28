# ChatGPT-Codex Slack Loop

## Purpose

The Slack loop turns Daily Ops and Source Triage messages into a safe manual handoff queue. In `SAFE_MANUAL_HANDOFF` mode, scheduled messages must not auto-trigger Codex. They may summarize findings and provide bounded LOW-risk prompts, but those prompts remain inert until a human reviews them and manually mentions Codex in the relevant Slack thread.

Codex is branch-and-PR-only. Humans remain responsible for deciding whether to start Codex, reviewing the draft PR, approving the work, merging, and any production rollout.

## Risk Classification

| Risk | Definition | SAFE_MANUAL_HANDOFF rule |
| --- | --- | --- |
| LOW | Documentation, formatting, report wording, read-only analysis notes, test naming, or other changes with no runtime behavior impact. | May be listed as a copy-paste handoff prompt. Codex starts only after a human manually mentions Codex in a thread and pastes the prompt. |
| MEDIUM | Bounded changes to tests, read-only reporting code, non-trading UI, logs, or developer tooling where production trading behavior is not changed. | May be listed for human review, but should not be converted into a Codex prompt unless a human explicitly approves the scope. |
| HIGH | Any change touching trading decisions, KIS API, order submission, scheduler timing, DB schema, credentials, account handling, live API calls, money movement, deployment, or merge/release actions. | Requires explicit human approval before implementation and must not be auto-executed. |

HIGH risk work may be discussed, but Slack automation must stop at a recommendation until a human explicitly approves the exact scope.

## Daily Ops / Source Triage Slack Format

Use this structure for scheduled Daily Ops or Source Triage messages. The message must be an execution record and review queue, not a direct Codex command.

````text
[Auto Trading Daily Ops] YYYY-MM-DD KST
Mode: SAFE_MANUAL_HANDOFF
Status: PASS | WARN | FAIL
Progress: NN.N% (delta: +N.N | -N.N | N/A)
Analysis period: YYYY-MM-DD to YYYY-MM-DD

Core result:
- Realized PnL: ...
- Candidate funnel: candidates -> selected -> buy_allowed -> order_submitted -> fills
- Main block reason: ...
- Data quality: ...

Runner / noisy universe:
- Runner finding: ...
- Noisy universe finding: ...

Risk queue:
1. LOW: ...
2. MEDIUM: ...
3. HIGH: ...

Selected LOW candidate:
- Selected: yes | no
- Title: ...
- Why selected: ...
- Expected PR type: draft PR
- Human action required: open this message thread, manually mention Codex, then paste the handoff prompt below.

Manual Codex handoff prompt:
Note: This prompt is not executed by the scheduled task. It starts only when a human manually mentions Codex in the Slack thread and pastes the prompt text.

```handoff-prompt
[MANUAL_CODEX_MENTION_PLACEHOLDER]
Use the Codex cloud environment named auto_trading.

Repository: geunil748-dev/auto_trading
Base branch: main

Selected candidate:
- Risk: LOW
- Title: ...

Task:
Create a new branch from main and implement only the selected LOW candidate.

Scope:
- Update only the named files.

Constraints:
- Do not modify trading logic, KIS API code, order code, scheduler timing, risk logic, DB schema, credentials, or reports/analysis outputs.
- Do not call KIS/order/Telegram/Slack/broker APIs.
- Open a draft PR only. Do not merge. Do not push directly to main.

Validation:
- Run git diff --check.
- No runtime tests are required for docs-only changes unless code is modified.

Summarize:
- changed files
- risk level
- checks run
- PR link
- follow-up tasks
```

Safety notes:
- DB/API/credential access: not performed by the scheduled task.
- Codex auto-execution: disabled.
- Source edits by ChatGPT: none.

Human approval needed:
- MEDIUM items require human review before execution.
- HIGH items require explicit human approval before implementation.
````

## Manual DRY_RUN Slack Review Checklist

When a Daily Ops message is posted in `placeholder-report dry-run`, `missing-report dry-run`, or any other DRY_RUN mode, the human operator should review the Slack record before starting any Codex work. Treat the message as an execution record and candidate queue, not as permission for real automation.

1. Verify headline safety fields.
   - Confirm `Status`, `Data quality`, and `Mode` are present.
   - If `Mode` contains DRY_RUN, placeholder, missing, stale, or mismatch wording, treat the report as non-operational evidence until a fresh package is uploaded.
   - Confirm any safety note says DB was not accessed, SQL was not executed, and no KIS/order/Telegram/Slack upload/broker APIs were called, except for the final manual Slack record if explicitly stated.
2. Verify the progress cap.
   - Confirm `Progress` includes the cap reason, such as `70% missing metrics` or `75% placeholder metrics`, whenever summary/metrics are missing, placeholder-only, stale, or mismatched.
   - Do not interpret capped progress as proof that the underlying operational data is fresh.
3. Verify report freshness.
   - Compare `Expected completed trade_date`, `Latest report date found`, `Freshness status`, and the analysis period.
   - If freshness is `placeholder`, `unknown`, `stale`, or date-mismatched, require a newly generated `daily_ops_summary_YYYY-MM-DD.md` and `daily_ops_metrics_YYYY-MM-DD.json` before making trading conclusions.
4. Separate Codex candidates from approval-required work.
   - LOW items labeled as Codex candidates are review candidates only. They may be converted into copy-paste handoff prompts, but they must not execute until a human manually mentions Codex in a Slack thread with the exact bounded scope.
   - MEDIUM items require human review before execution and should not be included as ready-to-run prompts by default.
   - HIGH items labeled `[승인 필요]` require explicit human approval before implementation and must not be converted into an automated Codex request by the scheduled task.
   - The scheduled task must not include a real Slack app mention, raw mention ID, or direct execution phrase in candidate text.
5. Confirm execution boundaries before mentioning Codex.
   - No real Codex execution happens unless the human operator manually mentions Codex in a thread.
   - The manual Codex request must restate the allowed scope, non-goals, validation, and PR summary requirements.
   - For docs-only LOW work, require branch-and-PR-only changes and `git diff --check`; no runtime tests are required unless code changes are introduced.
6. Confirm prohibited operations stayed prohibited.
   - Do not allow DB access, SQL execution, KIS API calls, order API calls, Telegram API calls, Slack API calls, broker API calls, credential reads, or credential printing as part of DRY_RUN review.
   - Do not allow trading logic, KIS code, order submission, scheduler timing, risk logic, DB schema, deployment, merge, or release changes unless separately approved under the HIGH-risk process.
7. Confirm generated report outputs are not committed.
   - `reports/analysis/` may contain generated summaries, metrics, Excel files, runner profiles, or CSVs, but those files must not be included in a Codex commit or PR.
   - If the follow-up is to generate or upload reports, keep that as a human/local reporting step rather than a repository change.

A safe human follow-up for a LOW docs candidate should ask Codex to create a branch from `main`, update only the named docs, avoid trading/runtime code, run `git diff --check`, commit the docs-only change, and open a draft PR.

## Manual Codex Handoff Rules

Daily Ops and Source Triage messages must not contain real Slack mention IDs or direct Codex execution examples. Use a neutral placeholder in prompt blocks and make the required human action explicit.

Each handoff prompt must state:

- Risk level.
- Files or areas expected to change.
- Explicit non-goals.
- Validation expected.
- Draft PR requirement.
- PR summary requirements.

Recommended placeholder pattern:

```text
[MANUAL_CODEX_MENTION_PLACEHOLDER]
Use the Codex cloud environment named auto_trading.

Selected candidate:
- Risk: LOW
- Title: <bounded docs-only task>

Task:
Create a new branch from main and implement only this selected LOW candidate.

Scope:
- Update only <specific file or files>.

Constraints:
- Do not modify trading logic, KIS API code, order code, scheduler timing, risk logic, DB schema, credentials, or reports/analysis outputs.
- Do not call KIS/order/Telegram/Slack/broker APIs.
- Open a draft PR only. Do not merge. Do not push directly to main.

Validation:
- Run git diff --check.
```

## Codex Execution Boundaries

Codex must:

- Create or use a feature branch.
- Prefer `codex/<short-description>` or `docs/<short-description>` branch names for new automation branches.
- Keep changes scoped to the human-approved LOW or MEDIUM task.
- Commit only intended files.
- Push the feature branch when a remote is available.
- Open a draft pull request.
- Include changed files, risk level, tests run, and follow-up tasks in the PR summary.

Codex must not:

- Start from a scheduled Daily Ops or Source Triage message alone.
- Push directly to `main`.
- Merge pull requests.
- Auto-execute HIGH risk tasks.
- Access or print `.env`, tokens, app keys, account numbers, or credentials.
- Call KIS, Telegram, Slack, order, broker, or other external APIs unless a human explicitly approved that exact HIGH risk operation.
- Commit `reports/analysis/` output files.

## Validation Rules

For docs-only LOW risk work, Codex should run formatting or documentation checks when available. If no dedicated documentation checker exists, `git diff --check` is sufficient and code tests are not required.

For MEDIUM risk work, Codex should run the narrowest relevant automated tests or explain why they are not available.

For HIGH risk work, validation must be defined in the human approval before implementation begins.
