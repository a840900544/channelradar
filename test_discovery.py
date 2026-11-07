import sqlite3
import unittest
from pathlib import Path
from unittest.mock import patch

from channelradar import CampusDiscovery, initialize
from providers import MockProvider, ProviderError, TencentSkillProvider, redact


class DiscoveryTests(unittest.TestCase):
    def setUp(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        initialize(db)
        self.service = CampusDiscovery(db, MockProvider())

    def test_seed_and_ambiguous_campus(self):
        self.assertEqual(len(self.service.universities()), 66)
        with self.assertRaisesRegex(ValueError, "歧义"):
            self.service.discover("五山校区")

    def test_discover_review_refresh_and_revoke(self):
        first, second = self.service.discover("粤海校区")
        self.assertGreater(first["confidence"], second["confidence"])
        self.assertEqual(first["access"], "unknown")
        self.assertEqual(len(first["evidence"]["queries"]), 3)
        with self.assertRaises(ValueError):
            self.service.refresh_sections(first["id"])
        with self.assertRaises(ValueError):
            self.service.review(first["id"], "approved", "unknown", "模拟")
        self.service.review(first["id"], "approved", "public", "模拟测试")
        rerun = self.service.discover("深大")
        self.assertEqual([row["id"] for row in rerun], [first["id"], second["id"]])
        self.assertEqual(rerun[0]["review"], "approved")
        self.assertEqual([row["relevant"] for row in self.service.refresh_sections(first["id"])], [1, 0])
        self.service.review(first["id"], "rejected", "unknown", "撤销")
        self.assertEqual(self.service.db.execute("SELECT count(*) FROM channel_sections").fetchone()[0], 0)
        with self.assertRaises(ValueError):
            self.service.refresh_sections(first["id"])

    def test_redaction(self):
        self.assertEqual(redact("QQ 12345678 或 test@example.invalid"), "QQ [已脱敏] 或 [已脱敏]")


class TencentProviderTests(unittest.TestCase):
    def setUp(self):
        self.provider = TencentSkillProvider(Path(__file__))

    def test_verified_large_home_page_keeps_section_default(self):
        provider = TencentSkillProvider(Path(__file__), page_size=100)
        with patch.object(provider, "_call", return_value={"feeds": [], "has_more": False}) as call:
            provider.latest_page("1", "", None)
            self.assertEqual(call.call_args.args[1]["count"], 100)
            self.assertEqual(call.call_args.args[1]["get_type"], 2)
            provider.latest_page("1", "2", None)
            self.assertEqual(call.call_args.args[1]["count"], 20)

    def test_synthetic_pagination_and_unsafe_link(self):
        item = {"guild_id": "1", "name": "模拟频道", "share_url": "javascript:alert(1)"}
        pages = [{"channels": [item], "next_page_token": "opaque"}, {"channels": [item]}]
        with patch.object(self.provider, "_call", side_effect=pages) as call:
            result = self.provider.search_channels("模拟")
        self.assertEqual(len(result), 1)
        self.assertIsNone(result[0].url)
        self.assertEqual(call.call_args.args[1]["next_page_token"], "opaque")

    def test_unknown_envelope_and_repeated_token_fail_closed(self):
        with patch.object(self.provider, "_call", return_value={}):
            with self.assertRaises(ProviderError):
                self.provider.search_channels("模拟")
        with patch.object(self.provider, "_call", return_value={"channels": [], "next_page_token": "same"}):
            with self.assertRaisesRegex(ProviderError, "重复"):
                self.provider.search_channels("模拟")

    def test_subprocess_uses_allowlist_and_stdin(self):
        with patch("providers.subprocess.run") as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b'{"success":true,"data":{"channels":[]}}'
            self.assertEqual(self.provider.search_channels("--unsafe"), [])
        self.assertEqual(run.call_args.args[0][1:], ["manage", "search-guild-content", "--json"])
        self.assertFalse(run.call_args.kwargs["shell"])
        self.assertIn(b"--unsafe", run.call_args.kwargs["input"])


if __name__ == "__main__":
    unittest.main()
