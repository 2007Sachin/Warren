import unittest

import pandas as pd

from backtest.tsmom import CAP_W, inverse_vol_weights


class InvVolTests(unittest.TestCase):
    def test_cap_and_cash_remainder(self):
        w = inverse_vol_weights(pd.Series({"a": 0.01, "b": 0.20}))
        self.assertLessEqual(float(w.max()), CAP_W + 1e-12)
        self.assertLessEqual(float(w.sum()), 1.0 + 1e-12)
        # Dominant low-vol name is capped; leftover is cash, not dumped into b.
        self.assertAlmostEqual(float(w["a"]), CAP_W)
        self.assertLess(float(w["b"]), 1.0 - CAP_W + 1e-9)

    def test_many_names_sum_to_one_if_uncapped(self):
        vols = pd.Series({f"s{i}": 0.02 for i in range(20)})
        w = inverse_vol_weights(vols)
        self.assertAlmostEqual(float(w.sum()), 1.0, places=6)
        self.assertTrue((w <= CAP_W + 1e-12).all())


if __name__ == "__main__":
    unittest.main()
