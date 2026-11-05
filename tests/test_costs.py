import unittest

from backtest.costs import order_cost, round_trip_cost


class CostTests(unittest.TestCase):
    def test_mis_buy_has_no_stt_and_has_stamp(self):
        c = order_cost("BUY", "MIS", 10, 1000)
        self.assertEqual(c["brokerage"], 20.0)
        self.assertEqual(c["stt"], 0.0)
        self.assertAlmostEqual(c["stamp"], 10000 * 0.00003)
        self.assertAlmostEqual(c["slippage"], 5.0)
        self.assertGreater(c["total"], 20.0)

    def test_mis_sell_has_stt(self):
        c = order_cost("SELL", "MIS", 10, 1000)
        self.assertAlmostEqual(c["stt"], 10000 * 0.00025)
        self.assertEqual(c["stamp"], 0.0)

    def test_cnc_both_sides_stt(self):
        rt = round_trip_cost("CNC", 10, 1000, 1100)
        self.assertAlmostEqual(rt["buy"]["stt"], 10000 * 0.001)
        self.assertAlmostEqual(rt["sell"]["stt"], 11000 * 0.001)
        self.assertEqual(rt["buy"]["brokerage"], 20.0)
        self.assertEqual(rt["sell"]["brokerage"], 20.0)

    def test_gst_on_brokerage_and_txn(self):
        c = order_cost("BUY", "CNC", 1, 100)
        expected_gst = 0.18 * (c["brokerage"] + c["exchange_txn"] + c["sebi"])
        self.assertAlmostEqual(c["gst"], expected_gst)

    def test_zero_qty(self):
        self.assertEqual(order_cost("BUY", "MIS", 0, 100)["total"], 0.0)


if __name__ == "__main__":
    unittest.main()
