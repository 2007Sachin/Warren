# Neon ops-DB migration

Paper only. Frozen files untouched. Secrets (`NEON_API_KEY`, `DATABASE_URL`, `DATABASE_URL_UNPOOLED`) are never printed; presence is boolean-only.

## What changed

- Removed `supabase-py`. Paper ledger mirrors to Neon via `psycopg[binary]==3.2.10` in `db/` using pooled `DATABASE_URL`.
- Migrations live in `db/migrations/0001_init.sql` and `0002_paper.sql` (moved from `supabase/migrations/`). Apply with `python -m db.migrate` on `DATABASE_URL_UNPOOLED`.
- Env: `SUPABASE_URL` / `SUPABASE_KEY` replaced by `DATABASE_URL` / `DATABASE_URL_UNPOOLED`. Repo grep has no `SUPABASE` / `supabase` matches.
- If `DATABASE_URL` is unset or the connect (5s timeout) fails, the ledger stays Parquet-only and the trading loop does not raise.

## STEP 1 — CLI auth (this VM)

| check | result |
| --- | --- |
| `NEON_API_KEY` set | **no** |
| `DATABASE_URL` set | **no** |
| `DATABASE_URL_UNPOOLED` set | **no** |
| `npx neon@latest me --api-key "$NEON_API_KEY"` | skipped (key unset) |
| `neon deploy` | **not run** (project already provisioned; no key anyway) |

Headless auth could not run here. Add `NEON_API_KEY` to the Cloud Agent environment and re-run `npx neon@latest me --api-key "$NEON_API_KEY"` then `npx neon@latest env pull --api-key "$NEON_API_KEY" --file .env.local` (gitignored). Do not paste the key into chat.

## STEP 3 — Schema (blocked on direct URL)

Expected 10 tables (9 named in the brief plus `schema_migrations`):

| table | expected |
| --- | --- |
| orders_intent | yes |
| orders | yes |
| positions | yes |
| daily_pnl | yes |
| kill_switch_state | yes |
| audit_log | yes |
| paper_orders | yes |
| paper_positions | yes |
| paper_daily_pnl | yes |
| advisor_votes | yes |

**Not applied on Neon in this VM** — `DATABASE_URL_UNPOOLED` was not set, so `python -m db.migrate` was not executed against production.

Append-only: `0002_paper.sql` revokes `UPDATE`/`DELETE` on `advisor_votes` from `PUBLIC` (and from `authenticated`/`anon` if those roles exist) and adds a BEFORE UPDATE/DELETE trigger that raises `42501`. Live proof of that trigger is in `tests/test_neon_roundtrip.py` and was **skipped**.

## STEP 4 — Round-trip

```
python -m pytest -q tests/test_neon_roundtrip.py
SKIPPED (DATABASE_URL unset)
```

## STEP 5 — Regression

```
python -m pytest -q
33 passed, 1 skipped in 2.51s
```

Skipped test: `test_neon_roundtrip.py` (no `DATABASE_URL`).

Replay `runtime/daily_job.py --replay 2025-10-01:2025-10-15` with `LAYA_MOCK=1` and an isolated `PAPER_STORE` (no `DATABASE_URL`):

| | first run | second run |
| --- | --- | --- |
| JOB new_orders | 9 | 0 |
| JOB new_pnl_rows | 10 | 0 |
| Parquet paper_orders | 9 | 9 |
| Parquet paper_daily_pnl | 10 | 10 |
| Parquet paper_positions | 5 | 5 |
| Neon paper_orders | n/a (URL unset) | n/a |

Second run added **zero** Parquet rows. Neon counts could not be queried.

## Free-tier limits

None hit: no compute or storage API calls were made without credentials.

## How to finish live wiring (after the key is in the environment)

```
npx neon@latest me --api-key "$NEON_API_KEY"
npx neon@latest env pull --api-key "$NEON_API_KEY" --file .env.local
set -a && . ./.env.local && set +a
python -m db.migrate
python -m pytest -q
```

Never `echo` or `cat` `.env.local`.
