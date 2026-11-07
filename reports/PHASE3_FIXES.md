# Phase 3 review fixes

Paper only. Frozen files (`execution/`, `data/fetch_candles.py`, `risk/kill_switch.py`) untouched.

## What changed

1. **Expired orders are visible.** `runtime/report.py` adds an Expired orders section: week and cumulative count/rate (expired / total BUY entries), a table of every expired row (`symbol`, `signal_date`, `limit_price`, next-day open, gap %), and a WARNING if cumulative expired rate > 10%. `PaperBroker` stores `session_open` and `{expired_open, gap_pct}` on EXPIRE.

2. **UNFILLED-SIGNAL vs DEFECT.** A backtest signal with a paper EXPIRED entry is UNFILLED-SIGNAL (counted, not a hard defect). A paper entry whose `(symbol, signal_date)` is not in the backtest signal set is still a DEFECT.

3. **Drift is per-trade return, not equity.** For each backtest TEST-window round trip, paper is matched on `(symbol, signal_date)` (fallback fill_date). Table: `symbol`, `entry_date`, `backtest_return_pct`, `paper_return_pct`, `delta`, `status` in `{MATCH within 0.5pp, UNFILLED-SIGNAL, MISSING, DEFECT}`. Open paper fills with no exit yet stay MATCH with a blank paper return. Portfolio equity and daily P&L are not compared.

4. **Laya.** README documents CPU torch before `pip install laya`. `requirements.txt` pins `laya==0.4.27`. `agents/fit_laya.py` and `laya_advisor.py` use `laya.Agent.predict` on CPU (the library has no `laya.choice`).

Tests: `tests/test_expired_reporting.py`, `tests/test_signal_drift.py`, `tests/test_report_no_equity.py`. `python -m pytest -q` → 32 passed.

## Laya gate (real model)

```
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install laya
```

Install succeeded: `torch 2.15.0+cpu` (`cuda` False), `laya 0.4.27`. `python -m agents.fit_laya`:

```
wrote 24 rows -> data/store/paper/laya_labels.csv
VALIDATE regime majority=volatile majority_acc=0.533
TRAIN  regime model_acc=0.333 ECE=0.090 (real laya Agent)
VALIDATE regime model_acc=0.400 ECE=0.063 (real laya Agent)
advisor mode=log-only (VALIDATE regime head did not beat majority by 5 points)
```

Checkpoint warning (library): invalid temperatures outside [0.5, 5]; confidence treated as uncalibrated. Gate stays **log-only**. `LAYA_MOCK` abstain path remains for environments without the wheel.

## Replay `2025-07-01:2025-10-31`

Kill switch was reset for the first pass. `LAYA_MOCK=1` so the daily loop does not reload Agent on every signal.

First run: `JOB {'new_orders': 6, 'new_pnl_rows': 85, 'days': 85}`

Second run: `JOB {'new_orders': 0, 'new_pnl_rows': 0, 'days': 85}` (zero new rows).

Paper halt tripped on **2025-07-21** (`Daily loss limit breached: -1853.89 <= -1749.34`). After that, new entries stop; four positions stay open (one RELIANCE SELL filled 2025-07-22). That is the 2% daily paper-loss switch using mark-to-market vs prior equity, not a Donchian defect.

### Entry / fill / expire

| | count |
|---|---|
| Total entry (BUY) orders | 5 |
| FILLED entries | 5 (POLYCAB, RELIANCE, ZYDUSLIFE, PNB, AMBUJACEM) |
| EXPIRED entries | 0 |
| Expired rate | 0 / 5 = **0.0%** (no WARNING) |
| SELL fills | 1 (RELIANCE) |

The 1% LIMIT pad did not expire any of the five entries that were placed before the halt. Later TEST signals have no paper order because the kill switch blocked placement — those are **MISSING**, not EXPIRED.

### DEFECTS

_None._

### UNFILLED-SIGNAL

_None._ (no EXPIRED paper entries)

### Signal-level drift (TEST 2025-07-01–2025-10-31)

| symbol | entry_date | signal_date | backtest_return_pct | paper_return_pct | delta | status |
|---|---|---|---|---|---|---|
| RELIANCE-EQ | 2025-07-02 | 2025-07-01 | -7.29% | -7.12% | 0.001654 | MATCH |
| PNB-EQ | 2025-07-02 | 2025-07-01 | -7.57% |  |  | MATCH |
| BPCL-EQ | 2025-07-07 | 2025-07-04 | -5.55% |  |  | MISSING |
| IOC-EQ | 2025-07-07 | 2025-07-04 | -5.08% |  |  | MISSING |
| ZYDUSLIFE-EQ | 2025-07-02 | 2025-07-01 | -6.23% |  |  | MATCH |
| AMBUJACEM-EQ | 2025-07-03 | 2025-07-02 | -3.43% |  |  | MATCH |
| TORNTPHARM-EQ | 2025-07-24 | 2025-07-23 | -1.54% |  |  | MISSING |
| DMART-EQ | 2025-08-19 | 2025-08-18 | -2.67% |  |  | MISSING |
| HYUNDAI-EQ | 2025-08-19 | 2025-08-18 | 0.61% |  |  | MISSING |
| CGPOWER-EQ | 2025-09-16 | 2025-09-15 | -9.20% |  |  | MISSING |
| HDFCAMC-EQ | 2025-08-22 | 2025-08-21 | -7.69% |  |  | MISSING |
| POLYCAB-EQ | 2025-07-02 | 2025-07-01 | 14.30% |  |  | MATCH |
| CUMMINSIND-EQ | 2025-07-09 | 2025-07-08 | 23.50% |  |  | MISSING |
| TVSMOTOR-EQ | 2025-08-06 | 2025-08-05 | 17.01% |  |  | MISSING |
| MUTHOOTFIN-EQ | 2025-08-18 | 2025-08-14 | 12.78% |  |  | MISSING |
| HINDZINC-EQ | 2025-10-01 | 2025-09-30 | -2.46% |  |  | MISSING |
| IDEA-EQ | 2025-10-08 | 2025-10-07 | -6.29% |  |  | MISSING |
| CHOLAFIN-EQ | 2025-10-27 | 2025-10-24 | -3.57% |  |  | MISSING |
| ADANIENSOL-EQ | 2025-10-30 | 2025-10-29 | 0.76% |  |  | MISSING |

Status counts: **MATCH=5**, **MISSING=14**, UNFILLED-SIGNAL=0, DEFECT=0.

RELIANCE is the only closed paper round-trip (`|delta| = 0.17pp` within 0.5pp). The other four MATCH rows are still open, so paper return is blank by design.

MISSING after 2025-07-21 is the kill-switch halt, not a signal-set mismatch.
