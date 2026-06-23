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
