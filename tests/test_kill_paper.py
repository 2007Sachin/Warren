from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from risk.kill_switch import can_trade, check_daily_loss, reset, trip


class KillPaperTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        os.environ["KILL_SWITCH_FILE"] = str(Path(tmp) / "kill.json")
        # reload module paths
        import importlib
        import risk.kill_switch as ks
        ks.STATE_FILE = os.environ["KILL_SWITCH_FILE"]
        reset(True)

    def test_daily_loss_trips_and_blocks(self):
        check_daily_loss(-2500, 2000)
        self.assertFalse(can_trade())
        with self.assertRaises(PermissionError):
            reset(False)
        self.assertFalse(can_trade())
        reset(True)
        self.assertTrue(can_trade())

    def test_trip_reason(self):
        trip("drill")
        self.assertFalse(can_trade())


if __name__ == "__main__":
    unittest.main()
