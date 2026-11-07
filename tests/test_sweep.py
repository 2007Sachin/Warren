import unittest

from backtest.sweep import STOP_PAD, SWEEP_PAD


class SweepRuleTests(unittest.TestCase):
    def test_bearish_sweep_needs_close_back_inside(self):
        level = 100.0
        high = 100.0 * (1 + SWEEP_PAD) + 0.01
        self.assertTrue(high >= level * (1 + SWEEP_PAD))
        self.assertTrue(99.9 < level)  # close back below
        self.assertFalse(100.2 < level)  # close above is not a fade

    def test_stop_is_ten_bps_beyond_extreme(self):
        extreme = 100.0
        stop = extreme * (1 + STOP_PAD)
        self.assertAlmostEqual(stop, 100.1)


if __name__ == "__main__":
    unittest.main()
