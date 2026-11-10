import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from history import PageHistory, build_stats

TZ = timezone(timedelta(hours=1))


def at(year, month, day, hour=0, minute=0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


class BuildStatsTests(unittest.TestCase):
    def test_splits_pages_across_midnight_and_builds_series(self):
        now = at(2026, 11, 10, 10)
        points = [
            (at(2026, 11, 9, 22), 1000),
            (at(2026, 11, 10, 4), 1100),
            (now, 1160),
        ]
        stats = build_stats(points, now)
        self.assertEqual(stats["today"], 127)
        self.assertIsNone(stats["last_week"])
        self.assertIsNone(stats["last_month"])
        self.assertEqual(len(stats["series"]["week"]), 7)
        self.assertEqual(len(stats["series"]["month"]), 30)
        self.assertEqual(len(stats["series"]["year"]), 12)
        self.assertEqual(stats["series"]["week"][-1]["label"], "Tue")
        self.assertEqual(stats["series"]["week"][-1]["pages"], 127)
        self.assertEqual(stats["series"]["week"][-2]["pages"], 33)
        self.assertIsNone(stats["series"]["week"][-3]["pages"])
        self.assertEqual(stats["series"]["year"][-1]["label"], "Nov")
        self.assertIsNone(stats["series"]["year"][0]["pages"])
        self.assertTrue(stats["series"]["week"][-1]["current"])

    def test_counter_reset_does_not_subtract_pages(self):
        now = at(2026, 11, 10, 12)
        points = [
            (at(2026, 11, 10, 8), 500),
            (at(2026, 11, 10, 9), 10),
            (now, 40),
        ]
        stats = build_stats(points, now)
        self.assertEqual(stats["today"], 30)
        self.assertEqual(stats["average_day"], round(30 / (4 / 24), 1))

    def test_quiet_history_stays_outside_recent_windows(self):
        now = at(2026, 11, 10, 12)
        points = [
            (at(2026, 10, 1, 12), 0),
            (at(2026, 10, 11, 12), 1000),
            (now, 1000),
        ]
        stats = build_stats(points, now)
        self.assertEqual(stats["today"], 0)
        self.assertEqual(stats["last_week"], 0)
        self.assertEqual(stats["last_month"], 0)
        self.assertEqual(stats["average_day"], 25.0)
        self.assertAlmostEqual(stats["average_year"], 25 * 365.25, places=1)

    def test_single_reading_has_no_measured_pages(self):
        now = at(2026, 11, 10, 12)
        stats = build_stats([(now, 100)], now)
        self.assertIsNone(stats["today"])
        self.assertIsNone(stats["average_day"])
        self.assertIsNone(stats["series"]["week"][-1]["pages"])


class PageHistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.history = PageHistory(Path(self.tmp.name) / "pages.sqlite")

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_immediately_then_every_six_hours(self):
        start = datetime(2026, 11, 10, 8, tzinfo=timezone.utc)
        self.assertEqual(self.history.record_due([("office", 1000), ("office", None)], now=start), 1)
        self.assertEqual(self.history.record_due([("office", 1100)], now=start + timedelta(hours=5, minutes=59)), 0)
        self.assertEqual(self.history.record_due([("office", 1200)], now=start + timedelta(hours=6)), 1)
        later = start + timedelta(hours=6, minutes=30)
        stats = self.history.stats("office", 1300, now=later)
        self.assertEqual(stats["sample_count"], 2)
        self.assertEqual(stats["today"], 300)

    def test_restart_keeps_the_six_hour_gap(self):
        start = datetime(2026, 11, 10, 8, tzinfo=timezone.utc)
        self.history.record_due([("office", 1000)], now=start)
        reopened = PageHistory(self.history.path)
        self.assertEqual(reopened.record_due([("office", 1005)], now=start + timedelta(hours=1)), 0)


if __name__ == "__main__":
    unittest.main()
