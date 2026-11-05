"""Candle timestamps are tz-naive IST, and intraday bars sit in the session."""
import unittest
from pathlib import Path

import pandas as pd

from data.fetch_candles import assert_session_timestamps, normalize_timestamps

ROOT = Path(__file__).resolve().parents[1]
STORE = ROOT / "data" / "store" / "candles"


class CandleTimestampTests(unittest.TestCase):
    def test_utc_instants_become_ist_trading_days(self):
        raw = pd.Series([
            "2026-11-03T18:30:00+00:00",  # daily stamp -> 2026-11-04 00:00 IST
            "2026-11-04T03:45:00+00:00",  # 09:15 IST
            "2026-11-04T10:00:00+00:00",  # 15:30 IST
        ])
        out = normalize_timestamps(raw)
        self.assertIsNone(out.dt.tz)
        self.assertEqual(str(out.iloc[0]), "2026-11-04 00:00:00")
        self.assertEqual(str(out.iloc[1]), "2026-11-04 09:15:00")
        self.assertEqual(str(out.iloc[2]), "2026-11-04 15:30:00")

        daily = out.iloc[:1]
        assert_session_timestamps(daily, intraday=False)
        self.assertEqual(daily.dt.floor("D").iloc[0], pd.Timestamp("2026-11-04"))

        intraday = out.iloc[1:]
        assert_session_timestamps(intraday, intraday=True)
        self.assertTrue((intraday.dt.floor("D") == pd.Timestamp("2026-11-04")).all())

    def test_intraday_outside_session_fails(self):
        late = pd.Series([pd.Timestamp("2026-11-04 15:31:00")])
        with self.assertRaises(AssertionError):
            assert_session_timestamps(late, intraday=True)

    def test_stored_daily_files(self):
        paths = sorted(STORE.glob("*/*.parquet"))
        self.assertTrue(paths, "expected migrated candle files")
        for path in paths:
            df = pd.read_parquet(path)
            assert_session_timestamps(df["timestamp"], intraday=False)
            self.assertTrue((df["timestamp"].dt.floor("D") == df["timestamp"].dt.normalize()).all())


if __name__ == "__main__":
    unittest.main()
