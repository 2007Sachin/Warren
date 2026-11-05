import unittest

import pandas as pd

from backtest.meanrevert import wilder_rsi


class WilderRsiTests(unittest.TestCase):
    def test_period_two_known_path(self):
        # Closes: 100, 102, 101, 99
        # changes: +2, -1, -2
        # seed at i=2: avg_gain=1, avg_loss=0.5 -> RSI = 100-100/(1+2)=66.666...
        close = pd.Series([100.0, 102.0, 101.0, 99.0])
        rsi = wilder_rsi(close, 2)
        self.assertTrue(pd.isna(rsi.iloc[0]))
        self.assertTrue(pd.isna(rsi.iloc[1]))
        self.assertAlmostEqual(float(rsi.iloc[2]), 100.0 - 100.0 / (1.0 + 2.0), places=6)
        # i=3: ag=(1*1+0)/2=0.5, al=(0.5*1+2)/2=1.25, rs=0.4, rsi=28.571...
        self.assertAlmostEqual(float(rsi.iloc[3]), 100.0 - 100.0 / (1.0 + 0.4), places=6)

    def test_all_up_is_100(self):
        close = pd.Series([1.0, 2.0, 3.0, 4.0])
        rsi = wilder_rsi(close, 2)
        self.assertEqual(float(rsi.iloc[-1]), 100.0)


if __name__ == "__main__":
    unittest.main()
