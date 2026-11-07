"""Static check: paper/ and agents/ never import live order placement."""
from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BANNED = (
    "SmartConnect",
    "placeOrder",
    "place_order",
    "modifyOrder",
    "cancelOrder",
    "smartapi.smartConnect",
    "SmartAPI",
)


class PaperIsolationTests(unittest.TestCase):
    def test_no_smartconnect_in_paper_or_agents(self):
        hits = []
        for folder in ("paper", "agents"):
            for path in (ROOT / folder).rglob("*.py"):
                text = path.read_text()
                for token in BANNED:
                    if token in text:
                        hits.append(f"{path.relative_to(ROOT)}:{token}")
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()
