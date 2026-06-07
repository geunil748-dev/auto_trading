# DB Preflight, Init, and Repair Boundaries

This project keeps database checks and database-changing commands separate.
Use this guide before running DB-related CLI commands on an operating server.

## Command Roles

| Command | Role | Writes DB schema? | Deletes data? |
| --- | --- | --- | --- |
| `python -m trading_bot preflight` | Read-only readiness check | No | No |
| `python -m trading_bot repair-db-schema` | Explicit idempotent schema repair | Yes | No |
| `python -m trading_bot init-db` | Initial DB/schema setup | Yes | No |
| `tools/preflight_check.py` | Read-only startup environment check | No | No |

## `preflight`

`preflight` is a read-only command. It checks whether MSSQL is reachable and
whether required tables and columns are present. It reports missing schema as
warnings and failed readiness fields.

It must not run:

- `CREATE TABLE`
- `ALTER TABLE`
- `ALTER COLUMN`
- `connection.commit()`
- order APIs
- KIS APIs

If `preflight` reports missing columns or tables, review the output and decide
whether an explicit repair or initial setup command is appropriate.

## `repair-db-schema`

`repair-db-schema` is the explicit repair command. It is the only supported CLI
path for applying the small idempotent repairs currently implemented in code.

Current repair scope:

- `repair_database_schema()` runs the daily target numeric-column repair only
  if `dbo.daily_target` exists.
- `mock_trading_readiness(..., repair_schema=True)` can add the known safe
  strategy metadata columns on `trade_history` and `fill_history` when those
  tables exist.

The command does not delete, truncate, or backfill data. It also does not run
the full initial schema setup.

## `init-db`

`init-db` is for first-time setup or deliberate schema initialization. It can
create the configured MSSQL database if it is missing and then runs
`db/schema.sql`.

Do not call `init-db` automatically from startup health checks, read-only
preflight, or pull-only deployment updates unless an operator explicitly plans
that initialization step.

## Operational Rule

Use this sequence on an existing operating server:

```powershell
python -m trading_bot preflight
```

If preflight reports missing schema and the release notes say the repair is
safe:

```powershell
python -m trading_bot repair-db-schema
python -m trading_bot preflight
```

Use `init-db` only for first-time setup or a deliberate schema initialization
procedure:

```powershell
python -m trading_bot init-db
```

## Future Migration Note

This repository does not yet use a versioned migration framework. If schema
changes continue to grow, add a migration table and ordered migration files
instead of expanding startup or preflight paths.
