"""Historical candle fetch via SmartAPI getCandleData.

NOTE: throttled to ~1 req/sec for candle APIs (limit is ~3/sec officially;
be conservative). Schedule bulk backfills off-market-hours.
"""
import os, time, logging
import pandas as pd
from execution.angel_auth import get_session

log = logging.getLogger("candles")

INTERVALS = {"1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE",
             "1h": "ONE_HOUR", "1d": "ONE_DAY"}


def fetch(symbol_token: str, exchange: str, interval: str, from_dt: str, to_dt: str,
          pause: float = 1.0) -> pd.DataFrame:
    obj = get_session()
    resp = obj.getCandleData({
        "exchange": exchange,
        "symboltoken": symbol_token,
        "interval": INTERVALS[interval],
        "fromdate": from_dt,   # "2026-10-01 09:15"
        "todate": to_dt,       # "2026-11-05 15:30"
    })
    if not resp.get("status"):
        raise RuntimeError(f"getCandleData failed: {resp}")
    cols = ["timestamp", "open", "high", "low", "close", "volume"]
    df = pd.DataFrame(resp["data"], columns=cols)
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    time.sleep(pause)
    return df


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    # Example: RELIANCE token 2885 on NSE (verify from instrument master)
    df = fetch("2885", "NSE", "1d", "2026-09-01 09:15", "2026-11-04 15:30")
    print(df.tail())
