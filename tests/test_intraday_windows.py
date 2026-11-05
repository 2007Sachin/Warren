import unittest
from datetime import datetime

from data.pipeline import iter_windows


class WindowTests(unittest.TestCase):
    def test_30_day_and_10_day_chunks_cover_the_range(self):
        start = datetime(2025, 8, 1, 9, 15)
        end = datetime(2025, 9, 15, 15, 30)
        thirty = list(iter_windows(start, end, 30))
        self.assertEqual(thirty[0][0], start)
        self.assertEqual(thirty[-1][1], end)
        self.assertEqual(thirty[1][0], thirty[0][1])
        self.assertLessEqual((thirty[0][1] - thirty[0][0]).days, 30)

        ten = list(iter_windows(start, end, 10))
        self.assertEqual(ten[0][0], start)
        self.assertEqual(ten[-1][1], end)
        self.assertTrue(all(b[0] == a[1] for a, b in zip(ten, ten[1:])))
        self.assertGreater(len(ten), len(thirty))

    def test_empty_when_already_current(self):
        now = datetime(2026, 11, 5, 15, 30)
        self.assertEqual(list(iter_windows(now, now, 10)), [])


if __name__ == "__main__":
    unittest.main()
