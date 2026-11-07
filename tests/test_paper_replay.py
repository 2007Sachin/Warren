"""Replay 10 sessions: produces ledger rows and is idempotent."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ReplayTests(unittest.TestCase):
    def test_replay_idempotent(self):
        tmp = tempfile.mkdtemp(prefix="paper-")
        os.environ["PAPER_STORE"] = tmp
        os.environ["KILL_SWITCH_FILE"] = str(Path(tmp) / "kill.json")
        os.environ["LAYA_MOCK"] = "1"
        os.environ["LAYA_MODE_FILE"] = str(Path(tmp) / "laya_mode.json")
        from paper import ledger
        ledger.STORE = Path(tmp)
        from runtime.daily_job import run_range
        from datetime import date
        first = run_range(date(2025, 10, 1), date(2025, 10, 15), replay=True, dry_run=True)
        from paper.ledger import daily_pnl, orders
        n1 = 0 if orders().empty else len(orders())
        p1 = 0 if daily_pnl().empty else len(daily_pnl())
        self.assertGreaterEqual(p1, 1)
        second = run_range(date(2025, 10, 1), date(2025, 10, 15), replay=True, dry_run=True)
        n2 = 0 if orders().empty else len(orders())
        p2 = 0 if daily_pnl().empty else len(daily_pnl())
        self.assertEqual(n1, n2)
        self.assertEqual(p1, p2)
        self.assertEqual(second["new_orders"], 0)
        self.assertEqual(second["new_pnl_rows"], 0)
        self.assertGreaterEqual(first["days"], 8)


if __name__ == "__main__":
    unittest.main()
