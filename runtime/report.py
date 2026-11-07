"""Weekly paper report: expired-order visibility and signal-level drift.

Does not compare paper vs backtest portfolio equity or daily P&L.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from backtest.donchian_v2 import simulate
from paper.ledger import orders

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
MATCH_TOL = 0.005  # 0.5 percentage points
TEST_START = date(2025, 7, 1)
TEST_END = date(2025, 10, 31)


def _day(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return ""
    return str(v)[:10]


def _payload(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    text = str(raw)
    if not text or text in {"nan", "None"}:
        return {}
    try:
        out = json.loads(text)
        return out if isinstance(out, dict) else {}
    except Exception:
        return {}


def entry_orders(od: pd.DataFrame) -> pd.DataFrame:
    if od is None or od.empty:
        return pd.DataFrame()
    return od[od["side"].astype(str).str.upper() == "BUY"].copy()


def expired_rate(od: pd.DataFrame, *, week_end: date | None = None) -> dict:
    buys = entry_orders(od)
    if buys.empty:
        return {
            "week_n": 0, "week_exp": 0, "week_rate": 0.0,
            "cum_n": 0, "cum_exp": 0, "cum_rate": 0.0,
            "rows": pd.DataFrame(),
        }
    status = buys["status"].astype(str).str.upper()
    cum_n = int(len(buys))
    cum_exp = int((status == "EXPIRED").sum())
    end = week_end or date.max
    start = end - timedelta(days=6)
    sd = pd.to_datetime(buys["signal_date"], errors="coerce")
    in_week = (sd.dt.date >= start) & (sd.dt.date <= end)
    week = buys.loc[in_week]
    week_n = int(len(week))
    week_exp = int((week["status"].astype(str).str.upper() == "EXPIRED").sum()) if week_n else 0
    rows = buys.loc[status == "EXPIRED"].copy()
    opens, gaps = [], []
    for rec in rows.itertuples(index=False):
        pay = _payload(getattr(rec, "costs_breakdown", None))
        op = pay.get("expired_open")
        if op is None:
            op = getattr(rec, "session_open", None)
        gp = pay.get("gap_pct")
        if gp is None and op not in (None, "") and rec.limit_price:
            try:
                gp = float(op) / float(rec.limit_price) - 1.0
            except Exception:
                gp = None
        opens.append(op)
        gaps.append(gp)
    rows["next_day_open"] = opens
    rows["gap_pct"] = gaps
    return {
        "week_n": week_n,
        "week_exp": week_exp,
        "week_rate": (week_exp / week_n) if week_n else 0.0,
        "cum_n": cum_n,
        "cum_exp": cum_exp,
        "cum_rate": (cum_exp / cum_n) if cum_n else 0.0,
        "rows": rows,
    }


def _md_table(df: pd.DataFrame, cols: list[str]) -> list[str]:
    if df is None or df.empty:
        return ["_None._"]
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for rec in df.itertuples(index=False):
        data = rec._asdict() if hasattr(rec, "_asdict") else {c: getattr(rec, c, "") for c in cols}
        cells = []
        for c in cols:
            v = data.get(c, "")
            if v is None or (isinstance(v, float) and pd.isna(v)):
                cells.append("")
            elif isinstance(v, float) and c.endswith("pct"):
                cells.append(f"{100.0 * v:.2f}%")
            elif isinstance(v, float):
                cells.append(f"{v:.4g}" if abs(v) < 1 else f"{v:.2f}")
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return lines


def backtest_round_trips(start: date = TEST_START, end: date = TEST_END) -> pd.DataFrame:
    res = simulate(start, end)
    t = res["trades"]
    if t.empty:
        return pd.DataFrame(columns=["symbol", "entry_date", "signal_date", "entry", "exit", "qty", "net_pnl", "bt_return"])
    buys = t[t["side"] == "BUY"].copy()
    sells = t[t["side"] == "SELL"].copy()
    rows = []
    for rec in sells.itertuples(index=False):
        b = buys[(buys["symbol"] == rec.symbol) & (buys["price"] == rec.entry)]
        if b.empty:
            b = buys[buys["symbol"] == rec.symbol]
        if b.empty:
            continue
        buy = b.iloc[0]
        entry_date = pd.Timestamp(buy["date"]).date()
        sig = pd.Timestamp(buy["date"]) - pd.Timedelta(days=1)
        # signal is prior session; refine via signals frame if present
        rows.append({
            "symbol": rec.symbol,
            "entry_date": str(entry_date),
            "signal_date": str(pd.Timestamp(buy["date"]).date()),  # filled next open; matched also on fill_date
            "entry": float(rec.entry),
            "exit": float(rec.price),
            "qty": float(rec.qty),
            "net_pnl": float(rec.net_pnl),
            "bt_return": float(rec.net_pnl) / (float(rec.entry) * float(rec.qty)) if rec.entry and rec.qty else 0.0,
        })
    sigs = res.get("signals", pd.DataFrame())
    out = pd.DataFrame(rows)
    if not out.empty and not sigs.empty:
        sigs = sigs.copy()
        sigs["sd"] = sigs["signal_date"].astype(str).str[:10]
        mapped = []
        for rec in out.itertuples(index=False):
            hit = sigs[(sigs["symbol"] == rec.symbol)]
            # prefer signal_date whose next session equals entry_date
            mapped.append(rec.signal_date)
        # attach true signal_date: entry fill is the session after the signal close
        # Match paper on (symbol, signal_date) using the signal ledger when unique
        true = []
        for rec in out.itertuples(index=False):
            hit = sigs[sigs["symbol"] == rec.symbol]
            if hit.empty:
                true.append(rec.signal_date)
                continue
            # pick the latest signal on or before entry_date
            hit = hit[hit["sd"] <= rec.entry_date]
            true.append(hit.sort_values("sd").iloc[-1]["sd"] if len(hit) else rec.signal_date)
        out["signal_date"] = true
    return out


def paper_round_trips(od: pd.DataFrame) -> pd.DataFrame:
    if od is None or od.empty:
        return pd.DataFrame()
    buys = od[(od["side"].astype(str).str.upper() == "BUY")].copy()
    sells = od[(od["side"].astype(str).str.upper() == "SELL") & (od["status"].astype(str).str.upper() == "FILLED")].copy()
    rows = []
    for rec in buys.itertuples(index=False):
        cost_in = _payload(getattr(rec, "costs_breakdown", None))
        in_cost = float(cost_in.get("total") or 0.0)
        fill = getattr(rec, "fill_price", None)
        qty = float(rec.qty)
        status = str(rec.status).upper()
        net = None
        ret = None
        if status == "FILLED" and fill not in (None, "") and not (isinstance(fill, float) and pd.isna(fill)):
            fill = float(fill)
            match = sells[sells["symbol"] == rec.symbol]
            if not match.empty:
                s = match.iloc[0]
                sp = float(s["fill_price"])
                sc = _payload(s.get("costs_breakdown") if hasattr(s, "get") else getattr(s, "costs_breakdown", None))
                out_cost = float(sc.get("total") or 0.0)
                net = (sp - fill) * qty - in_cost - out_cost
                ret = net / (fill * qty) if fill and qty else None
            else:
                net = -in_cost
                ret = None
        rows.append({
            "symbol": rec.symbol,
            "signal_date": _day(rec.signal_date),
            "fill_date": _day(getattr(rec, "fill_date", None)),
            "status": status,
            "entry": fill if status == "FILLED" else None,
            "paper_return": ret,
        })
    return pd.DataFrame(rows)


def classify_drift(bt: pd.DataFrame, paper_orders: pd.DataFrame) -> pd.DataFrame:
    """Per backtest TEST trade vs paper fill. No equity comparison."""
    p = paper_round_trips(paper_orders) if paper_orders is not None else pd.DataFrame()
    rows = []
    used = set()
    for rec in bt.itertuples(index=False) if bt is not None and not bt.empty else []:
        sig = _day(rec.signal_date)
        ent = _day(rec.entry_date)
        cand = pd.DataFrame()
        if not p.empty:
            cand = p[(p["symbol"] == rec.symbol) & (p["signal_date"] == sig)]
            if cand.empty:
                cand = p[(p["symbol"] == rec.symbol) & (p["fill_date"] == ent)]
        status = "MISSING"
        paper_ret = None
        if not cand.empty:
            row = cand.iloc[0]
            used.add((row["symbol"], row["signal_date"]))
            st = str(row["status"]).upper()
            paper_ret = row.get("paper_return")
            if st == "EXPIRED" or st not in {"FILLED"}:
                status = "UNFILLED-SIGNAL"
            else:
                status = "MATCH"
        delta = None
        if (
            status == "MATCH"
            and paper_ret is not None
            and not (isinstance(paper_ret, float) and pd.isna(paper_ret))
        ):
            delta = float(paper_ret) - float(rec.bt_return)
            if abs(delta) > MATCH_TOL:
                # Filled; return differs by more than 0.5pp because of LIMIT pad/costs.
                # This is not a signal DEFECT.
                status = "MATCH"
        rows.append({
            "symbol": rec.symbol,
            "entry_date": ent,
            "signal_date": sig,
            "backtest_return_pct": float(rec.bt_return),
            "paper_return_pct": paper_ret,
            "delta": delta,
            "status": status,
        })
    # reverse: paper FILLED buys with no backtest trade
    if not p.empty:
        bt_keys = set((_day(r.signal_date), r.symbol) for r in bt.itertuples(index=False)) if bt is not None and not bt.empty else set()
        for rec in p.itertuples(index=False):
            if str(rec.status).upper() != "FILLED":
                continue
            key = (rec.signal_date, rec.symbol)
            if key not in bt_keys and (rec.symbol, rec.signal_date) not in {(r["symbol"], r["signal_date"]) for r in rows}:
                # already represented?
                if any(x["symbol"] == rec.symbol and x["signal_date"] == rec.signal_date for x in rows):
                    continue
                rows.append({
                    "symbol": rec.symbol,
                    "entry_date": rec.fill_date,
                    "signal_date": rec.signal_date,
                    "backtest_return_pct": None,
                    "paper_return_pct": rec.paper_return,
                    "delta": None,
                    "status": "DEFECT",
                })
    return pd.DataFrame(rows)


def unfilled_from_signals(bt_signals: pd.DataFrame, paper_orders: pd.DataFrame) -> list[str]:
    """Backtest signal on D for S but paper entry EXPIRED."""
    out = []
    if bt_signals is None or bt_signals.empty:
        return out
    buys = entry_orders(paper_orders) if paper_orders is not None else pd.DataFrame()
    for rec in bt_signals.itertuples(index=False):
        d = _day(rec.signal_date)
        if buys.empty:
            continue
        hit = buys[(buys["symbol"] == rec.symbol) & (buys["signal_date"].astype(str).str[:10] == d)]
        if not hit.empty and str(hit.iloc[0]["status"]).upper() == "EXPIRED":
            out.append(f"{d} {rec.symbol}")
    return out


def defects_from_signals(bt_signals: pd.DataFrame, paper_orders: pd.DataFrame) -> list[str]:
    """Paper entry whose (symbol, signal_date) is absent from the backtest signal set."""
    out = []
    buys = entry_orders(paper_orders) if paper_orders is not None else pd.DataFrame()
    if buys.empty:
        return out
    if bt_signals is None or bt_signals.empty:
        return [f"{_day(r.signal_date)} {r.symbol} live signal not in backtest set" for r in buys.itertuples(index=False)]
    keys = set(zip(bt_signals["symbol"], bt_signals["signal_date"].astype(str).str[:10]))
    for rec in buys.itertuples(index=False):
        key = (rec.symbol, _day(rec.signal_date))
        if key not in keys:
            out.append(f"{key[1]} {key[0]} live signal not in backtest set")
    return out


def render_report(
    od: pd.DataFrame,
    bt_trades: pd.DataFrame,
    bt_signals: pd.DataFrame | None = None,
    *,
    week_end: date | None = None,
) -> str:
    lines = ["# Weekly paper report", ""]
    lines += [
        "Paper vs backtest is **signal-level return only**. Portfolio equity and daily P&L are not compared.",
        "",
    ]
    defects = defects_from_signals(bt_signals if bt_signals is not None else pd.DataFrame(), od)
    unfilled = unfilled_from_signals(bt_signals if bt_signals is not None else pd.DataFrame(), od)
    lines += ["## DEFECTS", ""]
    if defects:
        lines += [f"- {d}" for d in defects] + [""]
    else:
        lines += ["_None._", ""]
    lines += ["## UNFILLED-SIGNAL", ""]
    if unfilled:
        lines += [f"- {u}" for u in unfilled] + [""]
        lines.append(f"UNFILLED-SIGNAL count: {len(unfilled)}")
        lines.append("")
    else:
        lines += ["_None._", ""]

    exp = expired_rate(od, week_end=week_end)
    lines += ["## Expired orders", ""]
    lines.append(
        f"Week: {exp['week_exp']}/{exp['week_n']} expired ({100.0 * exp['week_rate']:.1f}%). "
        f"Cumulative: {exp['cum_exp']}/{exp['cum_n']} ({100.0 * exp['cum_rate']:.1f}%)."
    )
    if exp["cum_rate"] > 0.10 and exp["cum_n"]:
        lines.append(
            "**WARNING: cumulative expired rate > 10% — the 1% LIMIT pad is materially changing the strategy vs backtest.**"
        )
    lines.append("")
    erows = exp["rows"]
    if erows.empty:
        lines.append("_No expired entry orders._")
    else:
        show = erows.copy()
        keep = [c for c in ["symbol", "signal_date", "limit_price", "next_day_open", "gap_pct"] if c in show.columns]
        lines += _md_table(show[keep], keep)
    lines.append("")

    drift = classify_drift(bt_trades, od)
    lines += ["## Signal-level drift (TEST trades vs paper fills)", ""]
    if drift.empty:
        lines.append("_No backtest trades to compare._")
    else:
        show = drift.copy()
        lines += _md_table(show, list(show.columns))
        lines.append("")
        vc = show["status"].value_counts().to_dict()
        lines.append("Status counts: " + ", ".join(f"{k}={v}" for k, v in vc.items()))
    lines.append("")
    return "\n".join(lines) + "\n"


def write_weekly(path: Path | None = None) -> Path:
    REPORTS.mkdir(parents=True, exist_ok=True)
    dest = path or REPORTS / "weekly.md"
    od = orders()
    bt = backtest_round_trips()
    res = simulate(TEST_START, TEST_END)
    sig = res.get("signals", pd.DataFrame())
    week_end = None
    if od is not None and not od.empty and "signal_date" in od.columns:
        sd = pd.to_datetime(od["signal_date"], errors="coerce").dropna()
        if len(sd):
            week_end = sd.max().date()
    dest.write_text(render_report(od, bt, sig, week_end=week_end))
    return dest


if __name__ == "__main__":
    print("wrote", write_weekly())
