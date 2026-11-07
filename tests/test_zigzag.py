import unittest

import pandas as pd

from backtest.harmonic import classify, confirmed_zigzag


class ZigZagTests(unittest.TestCase):
    def test_pivot_confirms_only_after_full_threshold(self):
        # Peak at bar 2 (high 100), 2% drop completes at bar 4 (low 97.9).
        rows = [
            (98.0, 97.0, 97.5),
            (99.0, 97.5, 98.5),
            (100.0, 99.0, 99.5),  # candidate high
            (99.8, 98.5, 98.6),   # 1.5% off high — not enough
            (99.0, 97.9, 98.0),   # 2.1% off high — confirm
        ]
        df = pd.DataFrame(rows, columns=["high", "low", "close"])
        pivots = confirmed_zigzag(df, 0.02)
        highs = [p for p in pivots if p["kind"] == "H"]
        self.assertEqual(len(highs), 1)
        self.assertEqual(highs[0]["index"], 2)
        self.assertEqual(highs[0]["confirmed_index"], 4)
        self.assertGreater(highs[0]["confirmed_index"], highs[0]["index"])
        # 1.5% off the high at bar 3 is not enough to confirm.
        self.assertGreater(highs[0]["confirmed_index"], 3)

    def test_gartley_group1_xb_618(self):
        name = classify(xb=0.62, xd=0.79, ac=0.5, xa_retr=0.5)
        self.assertEqual(name, "Gartley")


if __name__ == "__main__":
    unittest.main()
