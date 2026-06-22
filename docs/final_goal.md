# Final Goal: ChatGPT-Codex Daily Automation Foundation

## Final Project Goal

Build a daily, read-only operations loop where ChatGPT reviews the auto-trading system from operational data, calculates progress against an explicit 100-point checklist, reports the result in Slack, and proposes safe Codex follow-up work without directly changing production behavior.

The finished foundation should help the human operator answer three questions every day:

- Did the trading system behave safely and measurably better than yesterday?
- Which LOW or MEDIUM risk improvements can Codex prepare as pull requests?
- Which HIGH risk decisions require explicit human approval before any implementation work starts?

## Target Operating Model

1. A daily read-only DB report package is generated from existing operational tables.
2. The package contains an `.xlsx` workbook, a Markdown summary, and a JSON machine-readable summary.
3. ChatGPT calculates the daily progress percentage from `docs/progress_rules.md`.
4. ChatGPT posts or prepares a Slack-ready report using `docs/chatgpt_codex_slack_loop.md`.
5. LOW and MEDIUM risk tasks may be proposed automatically through Slack `@Codex`.
6. Codex creates a branch, commits scoped changes, pushes the branch, and opens a pull request only.
7. Humans review, approve, and merge pull requests.
8. HIGH risk tasks are held for human approval and must not be auto-executed.

## Non-Goals

This documentation foundation does not change trading behavior. It must not modify:

- Trading decision logic.
- KIS API integration code.
- Order submission, retry, cancellation, or fill handling code.
- Scheduler timing.
- DB schema or migrations.
- Runtime credentials, `.env`, app keys, tokens, account numbers, or secrets.

## Success Definition

The foundation is complete when the repository has:

- A documented final goal and operating model.
- A 100-point weighted progress checklist.
- A deterministic daily progress calculation rule.
- A read-only daily report package contract for `.xlsx`, `.md`, and `.json` outputs.
- A Slack report format with LOW / MEDIUM / HIGH risk handling.
- Repository-level Codex safety rules requiring branch-and-PR-only work.
