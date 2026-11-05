"""Historical candle fetch via SmartAPI getCandleData.

NOTE: default pause is 2.5s (official candle limit is ~3/sec; stay slower).
Schedule bulk backfills off-market-hours.
"""
import os, time, logging
import pandas as pd
from execution.angel_auth import get_session

log = logging.getLogger("candles")
IST = "Asia/Kolkata"
SESSION_OPEN = pd.Timestamp("09:15").time()
SESSION_CLOSE = pd.Timestamp("15:30").time()

INTERVALS = {"1m": "ONE_MINUTE", "5m": "FIVE_MINUTE", "15m": "FIFTEEN_MINUTE",
             "1h": "ONE_HOUR", "1d": "ONE_DAY"}


def _session():
    """Cached sessions store jwtToken already prefixed with 'Bearer '.

    SmartConnect._request adds that prefix again, which the historical API
    rejects as AG8001. Strip a single prefix here; do not change auth.
    """
    obj = get_session()
    token = getattr(obj, "access_token", None)
    if isinstance(token, str) and token.lower().startswith("bearer "):
        obj.setAccessToken(token.split(" ", 1)[1].strip())
    return obj


def normalize_timestamps(ts: pd.Series) -> pd.Series:
    """Convert candle times to tz-naive Asia/Kolkata wall-clock."""
    parsed = pd.to_datetime(ts)
    tz = getattr(parsed.dt, "tz", None)
    if tz is None:
        parsed = parsed.dt.tz_localize(IST)
    else:
        parsed = parsed.dt.tz_convert(IST)
    return parsed.dt.tz_localize(None)


def assert_session_timestamps(ts: pd.Series, *, intraday: bool) -> None:
    """Floored date is the trading day. Intraday bars sit inside 09:15–15:30."""
    parsed = pd.to_datetime(ts)
    if getattr(parsed.dt, "tz", None) is not None:
        raise AssertionError("timestamps must be tz-naive IST wall-clock")
    floored = parsed.dt.floor("D")
    trading_day = parsed.dt.normalize()
    if not floored.equals(trading_day):
        raise AssertionError("floored timestamp date is not the trading day")
    if intraday:
        clock = parsed.dt.time
        outside = [t for t in clock if t < SESSION_OPEN or t > SESSION_CLOSE]
        if outside:
            raise AssertionError(f"intraday timestamps outside 09:15-15:30: {outside[:5]}")


def fetch(symbol_token: str, exchange: str, interval: str, from_dt: str, to_dt: str,
          pause: float = 2.5) -> pd.DataFrame:
    obj = _session()
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
    df["timestamp"] = normalize_timestamps(df["timestamp"])
    time.sleep(pause)
    return df


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    # Example: RELIANCE token 2885 on NSE (verify from instrument master)
    df = fetch("2885", "NSE", "1d", "2026-09-01 09:15", "2026-11-04 15:30")
    print(df.tail())
