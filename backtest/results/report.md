# Phase 2 backtest comparison

Capital Rs 1,00,000. All figures after Angel One cash-market costs
(Rs 20 brokerage per order, STT, stamp, exchange, SEBI, GST, 0.05% slippage).
Only the TEST window decides. Parameters were not tuned after seeing TEST.

## Windows

- Momentum TRAIN 2024-01 → 2024-12, VALIDATE 2025-01 → 2025-06, TEST 2025-07 → 2026-11.
- ORB has no TRAIN (15m history starts 2025-08). VALIDATE 2025-08 → 2026-02, TEST 2026-03 → 2026-11.
- ORB skips `backtest_ok=false` days and hard-exits at the 15:00 15-minute bar close.

## Results

| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| momentum | TRAIN | 6.25% | 0.43 | -11.02% | 50.00% | 4.89 | 16 | 11.4% | 106146 |
| nifty | momentum-TRAIN | 9.11% | 0.69 | -10.95% | 100.00% | inf | 1 | 4.0% | 108769 |
| momentum | VALIDATE | 10.67% | 0.63 | -14.94% | 41.67% | 1.53 | 12 | 3.5% | 104862 |
| nifty | momentum-VALIDATE | 15.53% | 1.05 | -8.72% | 100.00% | inf | 1 | 4.9% | 107110 |
| momentum | TEST | -12.71% | -0.70 | -25.23% | 25.00% | 0.29 | 32 | 6.5% | 83296 |
| nifty | momentum-TEST | -3.11% | -0.18 | -15.59% | 0.00% | 0.00 | 1 | 8.8% | 95719 |
| orb | VALIDATE | -74.26% | -5.38 | -56.15% | 35.79% | 0.55 | 366 | 34.3% | 44723 |
| nifty | orb-VALIDATE | 4.10% | 0.46 | -5.72% | 100.00% | inf | 1 | 14.2% | 102142 |
| orb | TEST | -70.55% | -3.95 | -59.13% | 39.63% | 0.64 | 434 | 25.1% | 43222 |
| nifty | orb-TEST | -2.24% | -0.07 | -10.61% | 0.00% | 0.00 | 1 | 26.4% | 98327 |

## Verdict

Gate: TEST window only — beat Nifty CAGR after costs, Sharpe > 0.8, max DD < 20%.

Momentum TEST: FAIL. CAGR -12.71% vs Nifty -3.11% (does not beat); Sharpe -0.70 <= 0.8; max DD -25.23% >= 20%.
ORB TEST: FAIL. CAGR -70.55% vs Nifty -2.24% (does not beat); Sharpe -3.95 <= 0.8; max DD -59.13% >= 20%.

Verdict: neither strategy clears the TEST gate. A negative result is the result.

## Iteration 1 — Momentum v2

Universe: Nifty Next 50 plus the original 5 names (~55 CNC names). Rank 90-day return
minus last-5-day return. Hold top 5 equal weight, rebalance every 21 sessions,
drop names below rank 8. If Nifty 50 close is below its 200-day SMA on a rebalance day,
flatten to cash until it closes back at or above the SMA. Long-only, no leverage.
Same costs and TEST gate. Parameters were not tuned after seeing TEST.

| strategy | window | CAGR | Sharpe | max DD | win rate | profit factor | trades | cost % of gross | end equity |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| momentum_v2 | TRAIN | -9.45% | -0.32 | -21.96% | 40.00% | 0.56 | 40 | 7.2% | 90697 |
| nifty | momentum_v2-TRAIN | 9.11% | 0.69 | -10.95% | 100.00% | inf | 1 | 4.0% | 108769 |
| momentum_v2 | VALIDATE | -5.54% | -0.24 | -12.86% | 35.00% | 0.78 | 20 | 8.0% | 97258 |
| nifty | momentum_v2-VALIDATE | 15.53% | 1.05 | -8.72% | 100.00% | inf | 1 | 4.9% | 107110 |
| momentum_v2 | TEST | -4.50% | -0.24 | -11.68% | 33.33% | 0.71 | 45 | 8.5% | 93806 |
| nifty | momentum_v2-TEST | -3.11% | -0.18 | -15.59% | 0.00% | 0.00 | 1 | 8.8% | 95719 |

TEST days in cash (no holdings, including regime filter): 49.6% (166 / 335 sessions).

![Momentum v2 vs Nifty TEST](momentum_v2_test_vs_nifty.png)

Momentum v2 TEST: FAIL. CAGR -4.50% vs Nifty -3.11% (does not beat); Sharpe -0.24 <= 0.8; max DD -11.68% < 20%.

TEST days in cash (no holdings, including regime filter): 49.6% (166 / 335 sessions).

Verdict: Momentum v2 does not clear the TEST gate. Stop momentum here; do not tune parameters.

