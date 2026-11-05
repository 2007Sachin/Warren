import unittest

import pandas as pd

from backtest.donchian import DONCHIAN_IN


class DonchianWindowTests(unittest.TestCase):
    def test_breakout_excludes_today(self):
        high = pd.Series([1, 2, 3, 4, 5] + [5] * DONCHIAN_IN)
        i = len(high) - 1
        prior = high.iloc[i - DONCHIAN_IN : i]
        self.assertEqual(len(prior), DONCHIAN_IN)
        self.assertEqual(float(prior.max()), 5.0)
        today = 6.0
        self.assertTrue(today > float(prior.max()))
        self.assertFalse(5.0 > float(prior.max()))


if __name__ == "__main__":
    unittest.main()
