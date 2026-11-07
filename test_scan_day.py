import sqlite3
import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from providers import ProviderError
from scan_day import BEIJING, scan_day


class DayTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.day = datetime.now(BEIJING).date() - timedelta(days=1)
        self.provider = Mock()
        self.provider.channel_info.return_value = {
            "name": "测试频道", "guild_type": "公开腾讯频道", "share_url": None,
        }
        self.post = ("one", f"{self.day} 00:00:00", "表格对不上", "")
        self.old = ("old", f"{self.day - timedelta(days=1)} 23:59:59", "旧帖", "")

    def test_boundaries_duplicates_and_old_pin(self):
        today = ("today", f"{self.day + timedelta(days=1)} 00:00:00", "今天", "")
        self.provider.latest_page.side_effect = [
            ([today, self.old, self.post], "a"), ([self.post, self.old], "b"),
            ([self.old], "c"), ([self.old], "d"),
        ]
        result = scan_day(self.db, self.provider, "1", self.day)
        self.assertEqual((result["coverage"], result["posts"], result["pages"]),
                         ("boundary_reached", 1, 4))

    def test_budget_failure_and_resume(self):
        self.provider.latest_page.side_effect = [([self.post], "a")]
        result = scan_day(self.db, self.provider, "1", self.day, max_pages=1)
        self.assertEqual(result["coverage"], "budget_exhausted")
        self.provider.latest_page.side_effect = [ProviderError("network")]
        result = scan_day(self.db, self.provider, "1", self.day)
        self.assertEqual((result["coverage"], result["posts"]), ("error", 1))
        self.provider.latest_page.side_effect = [([self.post], None)]
        result = scan_day(self.db, self.provider, "1", self.day)
        self.assertEqual((result["coverage"], result["posts"]), ("api_end", 1))
        self.assertEqual(self.provider.latest_page.call_args.args[2], "a")

    def test_repeated_cursor_is_incomplete(self):
        self.provider.latest_page.side_effect = [([self.post], "a"), ([self.post], "a")]
        result = scan_day(self.db, self.provider, "1", self.day)
        self.assertEqual(result["coverage"], "error")
        self.assertEqual(result["pages"], 1)
