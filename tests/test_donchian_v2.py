import unittest

from backtest.donchian import SMA_DAYS
from backtest.donchian_v2 import simulate


class DonchianV2Tests(unittest.TestCase):
    def test_sma_window_unchanged(self):
        self.assertEqual(SMA_DAYS, 200)

    def test_simulate_exposes_occupancy_fields(self):
        from datetime import date
        # Empty window still returns occupancy keys.
        res = simulate(date(1990, 1, 1), date(1990, 1, 2))
        self.assertIn("occupancy", res)
        self.assertIn("regime_off_median", res)


if __name__ == "__main__":
    unittest.main()
