import unittest

from backtest.harmonic import classify
from backtest.harmonic_daily import PRIMARY_ZZ, SENS_ZZ


class HarmonicDailyPortTests(unittest.TestCase):
    def test_ratios_unchanged(self):
        self.assertEqual(classify(0.618, 0.786, 0.5, 0.618), "Gartley")
        self.assertEqual(classify(0.5, 0.886, 0.4, 0.5), "Bat")

    def test_thresholds(self):
        self.assertEqual(PRIMARY_ZZ, 0.05)
        self.assertEqual(SENS_ZZ, 0.07)


if __name__ == "__main__":
    unittest.main()
