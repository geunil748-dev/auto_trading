# ChatGPT-Codex Slack Loop

## Purpose

The Slack loop turns the daily operations report into a safe action queue. ChatGPT may propose LOW and MEDIUM risk work through Slack `@Codex`, but Codex must only create a branch and pull request. Humans remain responsible for approval, merge, and production rollout.

Note: Slack mention ID `&lt;@U0BC29CQUBD&gt;` read-only integration was verified before enabling automated task prompts.

## Risk Classification

| Risk | Definition | Automation Rule |
| --- | --- | --- |
| LOW | Documentation, formatting, report wording, read-only analysis notes, test naming, or other changes with no runtime behavior impact. | May be proposed automatically through Slack `@Codex`. Codex may prepare a branch and PR only. |
| MEDIUM | Bounded changes to tests, read-only reporting code, non-trading UI, logs, or developer tooling where production trading behavior is not changed. | May be proposed automatically through Slack `@Codex`. Codex may prepare a branch and PR only with validation. |
| HIGH | Any change touching trading decisions, KIS API, order submission, scheduler timing, DB schema, credentials, account handling, live API calls, money movement, deployment, or merge/release actions. | Requires explicit human approval before implementation and must not be auto-executed. |

HIGH risk work may be discussed, but Slack automation must stop at a recommendation until a human explicitly approves the exact scope.

## Daily Slack Report Format

Use this format for the daily report:

```text
[Auto Trading Daily Ops] YYYY-MM-DD KST
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
- LOW: ...
- MEDIUM: ...
- HIGH: ...

Recommended @Codex proposals:
- LOW: @Codex create a branch and PR for ...
- MEDIUM: @Codex create a branch and PR for ...

Human approval needed:
- HIGH: ...

Follow-ups:
- ...
```

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
   - LOW/MEDIUM items labeled `[Codex 실행 후보]` are review candidates only. They may be turned into a Codex request only after a human manually mentions Codex in a Slack thread with the exact bounded scope.
   - HIGH items labeled `[승인 필요]` require explicit human approval before implementation and must not be converted into an automated Codex request by the Scheduled Task.
   - The Scheduled Task must not include a real `<@U0BC29CQUBD>` mention or direct `@Codex` execution phrase in DRY_RUN candidate text.
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

A safe human follow-up for a LOW docs candidate should look like: "Codex, create a branch from `main`, update only the named docs, do not touch trading/runtime code, run `git diff --check`, commit the docs-only change, and open a draft PR."

## `@Codex` Proposal Rules

LOW and MEDIUM tasks may be proposed automatically through Slack `@Codex` when the proposed scope is specific and bounded.

Each proposal must state:

- Risk level.
- Files or areas expected to change.
- Explicit non-goals.
- Validation expected.
- PR summary requirements.

Example:

```text
@Codex Risk: LOW. Create a branch and PR that updates docs/progress_rules.md to clarify progress delta handling. Do not modify trading logic, KIS code, order code, scheduler timing, DB schema, credentials, or generated reports. Run docs-only validation and summarize changed files, risk, tests, and follow-ups.
```

## Codex Execution Boundaries

Codex must:

- Create or use a feature branch.
- Prefer `codex/<short-description>` branch names for new automation branches.
- Keep changes scoped to the approved LOW or MEDIUM task.
- Commit only intended files.
- Push the feature branch.
- Open a pull request.
- Include changed files, risk level, tests run, and follow-up tasks in the PR summary.

Codex must not:

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
