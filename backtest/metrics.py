"""Window metrics after costs. Equity is a daily (or session) mark-to-market series."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def max_drawdown(equity: pd.Series) -> float:
    peak = equity.cummax()
    dd = equity / peak - 1.0
    return float(dd.min()) if len(dd) else 0.0


def cagr(equity: pd.Series) -> float:
    if len(equity) < 2 or equity.iloc[0] <= 0:
        return 0.0
    years = len(equity) / TRADING_DAYS
    if years <= 0:
        return 0.0
    return float((equity.iloc[-1] / equity.iloc[0]) ** (1.0 / years) - 1.0)


def sharpe(equity: pd.Series) -> float:
    rets = equity.pct_change().dropna()
    if len(rets) < 2:
        return 0.0
    sigma = float(rets.std(ddof=1))
    if sigma == 0:
        return 0.0
    return float(rets.mean() / sigma * math.sqrt(TRADING_DAYS))


def summarize(equity: pd.Series, trades: pd.DataFrame) -> dict:
    n = int(len(trades))
    if n:
        net = trades["net_pnl"]
        gross = trades["gross_pnl"]
        costs = trades["cost"]
        wins = net[net > 0]
        losses = net[net < 0]
        win_rate = float(len(wins) / n)
        gross_win = float(wins.sum()) if len(wins) else 0.0
        gross_loss = float(losses.abs().sum()) if len(losses) else 0.0
        profit_factor = gross_win / gross_loss if gross_loss > 0 else (math.inf if gross_win > 0 else 0.0)
        cost_sum = float(costs.sum())
        gross_abs = float(gross.abs().sum())
        cost_pct_gross = 100.0 * cost_sum / gross_abs if gross_abs else 0.0
    else:
        win_rate = 0.0
        profit_factor = 0.0
        cost_pct_gross = 0.0
    return {
        "cagr": cagr(equity),
        "sharpe": sharpe(equity),
        "max_dd": max_drawdown(equity),
        "win_rate": win_rate,
        "profit_factor": profit_factor,
        "trades": n,
        "cost_pct_gross": cost_pct_gross,
        "start_equity": float(equity.iloc[0]) if len(equity) else 0.0,
        "end_equity": float(equity.iloc[-1]) if len(equity) else 0.0,
    }
