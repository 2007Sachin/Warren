import unittest
from datetime import date, time

from data.coverage import backtest_ok, expected_starts


class CoverageFlagTests(unittest.TestCase):
    def test_expected_session_starts(self):
        self.assertEqual(len(expected_starts("15m")), 25)
        self.assertEqual(expected_starts("15m")[0], time(9, 15))
        self.assertEqual(expected_starts("15m")[-1], time(15, 15))
        self.assertEqual(len(expected_starts("5m")), 75)
        self.assertEqual(expected_starts("5m")[-1], time(15, 25))

    def test_orb_and_muhurat_flags(self):
        day = date(2026, 11, 4)
        self.assertTrue(backtest_ok(day, []))
        self.assertTrue(backtest_ok(day, [time(15, 15), time(15, 20)]))
        self.assertFalse(backtest_ok(day, [time(9, 15)]))
        self.assertFalse(backtest_ok(day, [time(11, 0)]))
        self.assertTrue(backtest_ok(day, [time(11, 5), time(14, 0)]))
        self.assertFalse(backtest_ok(date(2025, 10, 21), []))


if __name__ == "__main__":
    unittest.main()
