"""Compare SmartAPI daily closes with official NSE EOD bhavcopy closes.

Uses jugaad-data for one equity session (default 2026-11-04). A symbol whose
max absolute percent difference exceeds 0.5% is flagged.
"""
import io
import sys
from datetime import date
from pathlib import Path

import pandas as pd
from jugaad_data.nse import NSEArchives

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data.query import load

EQUITIES = ["RELIANCE-EQ", "HDFCBANK-EQ", "INFY-EQ", "TCS-EQ", "SBIN-EQ"]
THRESHOLD = 0.5
DEFAULT_DAY = date(2026, 11, 4)


def _bhavcopy_frame(day: date) -> pd.DataFrame:
    text = NSEArchives().bhavcopy_raw(day)
    df = pd.read_csv(io.StringIO(text))
    df.columns = [c.strip() for c in df.columns]
    return df


def _equity_closes(df: pd.DataFrame) -> dict[str, float]:
    symbol_col = "TckrSymb" if "TckrSymb" in df.columns else "SYMBOL"
    series_col = "SctySrs" if "SctySrs" in df.columns else "SERIES"
    close_col = "ClsPric" if "ClsPric" in df.columns else "CLOSE"
    eq = df[df[series_col].astype(str).str.strip().eq("EQ")]
    out = {}
    for _, row in eq.iterrows():
        out[str(row[symbol_col]).strip()] = float(row[close_col])
    return out


def compare(day: date = DEFAULT_DAY, symbols: list[str] | None = None) -> list[dict]:
    symbols = symbols or EQUITIES
    official = _equity_closes(_bhavcopy_frame(day))
    rows = []
    for symbol in symbols:
        name = symbol.split("-EQ")[0]
        candles = load(symbol, "NSE")
        ts = pd.to_datetime(candles["timestamp"])
        match = candles[ts.dt.date == day]
        if match.empty:
            raise RuntimeError(f"{symbol} has no SmartAPI bar on {day}")
        if name not in official:
            raise RuntimeError(f"{name} missing from bhavcopy on {day}")
        ours = float(match.iloc[-1]["close"])
        nse = official[name]
        pct = abs(ours - nse) / nse * 100 if nse else float("inf")
        rows.append({
            "symbol": symbol,
            "date": str(day),
            "smartapi_close": ours,
            "bhavcopy_close": nse,
            "abs_pct": pct,
            "flag": pct > THRESHOLD,
        })
    return rows


def report(rows: list[dict]) -> int:
    flagged = 0
    for row in rows:
        line = (
            f"{row['symbol']} {row['date']}: smartapi={row['smartapi_close']:.4f} "
            f"bhavcopy={row['bhavcopy_close']:.4f} abs_pct={row['abs_pct']:.4f}%"
        )
        if row["flag"]:
            flagged += 1
            print("!!! DATA QUALITY " + "!" * 40)
            print(f"!!! {line} EXCEEDS {THRESHOLD}%")
            print("!!! DATA QUALITY " + "!" * 40)
        else:
            print(line)
    print(f"max abs % = {max(r['abs_pct'] for r in rows):.4f}%  flagged={flagged}")
    return 1 if flagged else 0


if __name__ == "__main__":
    day = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DAY
    sys.exit(report(compare(day)))
