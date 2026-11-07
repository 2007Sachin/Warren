# Phase 3 — paper-trading runtime

Branch: `cursor/phase3-paper-runtime-f952` (platform branch template; requested name was `phase3-paper-runtime`).

## What was built

- `paper/broker.py` — LIMIT-only PaperBroker. Fill at next session open if buy `open<=limit` / sell `open>=limit`, else EXPIRED. Costs from `backtest/costs.py`.
- `paper/ledger.py` — parquet mirror (`PAPER_STORE`) plus optional Supabase upsert. `client_tag` / `date` unique → restart-safe.
- `supabase/migrations/0002_paper.sql` — `paper_orders`, `paper_positions`, `paper_daily_pnl`, append-only `advisor_votes`.
- `runtime/daily_job.py` — `--replay START:END` walks Donchian-v2 signals (factored helpers in `backtest/donchian_v2.py`), sizes at 0.75% equity / 2×ATR(14), max 6 names, 4% heat, 2% daily paper-loss kill switch, Telegram dry-run to stdout.
- `runtime/telegram_bot.py` — `STOP` trips `risk.kill_switch.trip`; `STATUS`; dry-run never sends.
- `agents/laya_advisor.py` — regime + triage; abstain if laya missing; size multiplier never > 1.
- `agents/fit_laya.py` — TRAIN/VALIDATE labels from Donchian-v2 trades; coded 5-point majority gate.
- `runtime/report.py` — weekly markdown; live signals missing from the backtest set are listed as DEFECTS. Nifty from `^NSEI` with parquet fallback.
- Frozen files were not edited: `execution/angel_auth.py`, `execution/instruments.py`, `data/fetch_candles.py`, `risk/kill_switch.py`.

## Tests (`python -m pytest -q`)

```
.............................                                            [100%]
29 passed in 2.33s
```

`tests/test_paper_no_broker.py` greps `paper/` and `agents/` for live-gateway tokens (`SmartConnect`, `placeOrder`, …) — empty.

`tests/parity_donchian.py` reproduces published v2 TRAIN/VALIDATE: 9 trades / equity 94939 and 15 trades / equity 109101, plus CSV golden of 48 order rows.

`tests/test_kill_paper.py`: daily loss > limit trips halt; `reset(False)` raises; human `reset(True)` required.

## Replay `runtime/daily_job.py --replay 2025-10-01:2025-10-15`

First run (stdout dry-run excerpt):

```
Warren paper 2025-10-01  equity=100000  signals=1 fills=0
Warren paper 2025-10-03  FILL BUY MUTHOOTFIN-EQ 5@3150.00
Warren paper 2025-10-06  FILL BUY JINDALSTEL-EQ 15@1077.00 / CANBK-EQ 122@126.00  (2 expired)
Warren paper 2025-10-07  FILL BUY BANKBARODA-EQ / IOC-EQ
JOB {'new_orders': 9, 'new_pnl_rows': 10, 'days': 10}
```

Second run, same range: `JOB {'new_orders': 0, 'new_pnl_rows': 0, 'days': 10}`.

Ledger: 9 `paper_orders` (unique `client_tag`), 10 `paper_daily_pnl` dates, 5 open positions.

## Laya gate

```
wrote 24 rows -> data/store/paper/laya_labels.csv
VALIDATE regime majority=volatile majority_acc=0.533
VALIDATE regime model_acc=0.533 ECE=0.000
advisor mode=log-only (laya not installed; mock)
```

`laya` is not installed in this environment (`LAYA_MOCK` / import failure). Votes are recorded as `"no opinion"` and never change size. Pipeline runs identically.

## Known limitations

- Paper LIMIT pad is 1% around the signal close so next-open fills can miss on larger gaps (EXPIRED). Backtest v2 entered at next open unconditionally — a documented fill-model difference, not a Donchian rule change.
- Paper sizing (0.75% / ATR / max 6 / heat 4%) is the Phase 3 overlay; backtest v2 remains 12.5% × 8.
- Daily candle refresh in non-replay mode calls `data.pipeline.run` (data path only). Paper modules do not import the order gateway.
- Supabase is optional; this VM had no `SUPABASE_URL`. Parquet is the source of truth for tests.
- Weekly report yfinance `^NSEI` may fail offline; falls back to stored Nifty 50.
- Train-time 252-day / 200-day lookbacks still apply: early 2024 has few Donchian-v2 signals.

## Frozen-file proof

`git diff --stat` does not include `execution/angel_auth.py`, `execution/instruments.py`, `data/fetch_candles.py`, or `risk/kill_switch.py`.
