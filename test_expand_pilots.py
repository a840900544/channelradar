import unittest
from datetime import datetime, timedelta
from unittest.mock import Mock

from expand_pilots import choose_channel
from providers import Channel, ProviderError
from scan_day import BEIJING


class PilotSelectionTests(unittest.TestCase):
    def test_selects_public_match_without_following_private_channel(self):
        provider = Mock()
        provider.search_channels.return_value = [
            Channel("1", "测试学校私密群", "", None),
            Channel("2", "测试学校校园圈", "", None),
            Channel("3", "其他学校频道", "", None),
        ]
        provider.channel_info.side_effect = [
            {"guild_type": "私密腾讯频道", "member_count": 10000},
            {"guild_type": "公开腾讯频道", "member_count": 2000},
        ]
        guild, _ = choose_channel(provider, "测试学校")
        self.assertEqual(guild, "2")
        self.assertEqual(provider.channel_info.call_count, 2)
        provider.search_channels.assert_called_once_with("测试学校", max_pages=1)

    def test_no_public_channel_remains_unverified(self):
        provider = Mock()
        provider.search_channels.return_value = []
        with self.assertRaises(ProviderError):
            choose_channel(provider, "测试学校")

    def test_activity_can_outweigh_member_count(self):
        provider = Mock()
        provider.search_channels.return_value = [
            Channel("1", "测试学校大群", "", None),
            Channel("2", "测试学校活跃群", "", None),
        ]
        provider.channel_info.side_effect = [
            {"guild_type": "公开腾讯频道", "member_count": 10000},
            {"guild_type": "公开腾讯频道", "member_count": 1000},
        ]
        now = datetime.now(BEIJING)
        old = (now - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S")
        recent = (now - timedelta(minutes=10)).strftime("%Y-%m-%d %H:%M:%S")
        provider.latest_page.side_effect = [
            ([("a", old, "", "")], None), ([("b", recent, "", "")], None),
        ]
        guild, info = choose_channel(provider, "测试学校", prefer_active=True)
        self.assertEqual(guild, "2")
        self.assertEqual(info["activity_screen"]["recent_24h"], 1)
