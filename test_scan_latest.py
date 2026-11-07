import sqlite3
import unittest
from unittest.mock import Mock

from providers import ProviderError
from scan_latest import scan, triage


class ScanTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.provider = Mock()
        self.post = ("sample", "2026-11-07 10:00:00", "表格排序后姓名和成绩对不上", "")

    def test_overlap_updates_and_preserves_first_seen(self):
        self.provider.latest_page.side_effect = [
            ([self.post], "cursor"), ([self.post], None),
        ]
        first = scan(self.db, self.provider, "1", "", 3)
        self.assertEqual((first["raw_posts"], first["new"]), (2, 1))
        self.assertEqual(first["candidates"][0]["triage"], "skill_review")
        observed = self.db.execute("SELECT first_seen FROM feed_observations").fetchone()
        changed = (*self.post[:3], "已经解决")
        self.provider.latest_page.side_effect = [([changed], "next"), ([self.post], "more")]
        second = scan(self.db, self.provider, "1", "", 3)
        self.assertEqual((second["new"], second["updated"], second["coverage"]), (0, 1, "overlap"))
        self.assertEqual(second["candidates"], [])
        self.assertEqual(self.db.execute("SELECT first_seen FROM feed_observations").fetchone(), observed)

    def test_partial_failure_keeps_state(self):
        self.provider.latest_page.side_effect = [([self.post], "next"), ProviderError("failed")]
        with self.assertRaises(ProviderError):
            scan(self.db, self.provider, "1", "", 3)
        self.assertEqual(self.db.execute("SELECT count(*) FROM feed_observations").fetchone()[0], 0)

    def test_publish_failure_does_not_advance_checkpoint(self):
        self.provider.latest_page.return_value = ([self.post], None)
        publish = Mock(side_effect=ValueError("destination unavailable"))
        with self.assertRaises(ValueError):
            scan(self.db, self.provider, "1", "", 2, publish=publish)
        self.assertEqual(self.db.execute("SELECT count(*) FROM feed_observations").fetchone()[0], 0)
        self.assertEqual(scan(self.db, self.provider, "1", "", 2)["new"], 1)

    def test_unclear_paid_and_excluded_request(self):
        self.assertEqual(triage("有偿帮忙"), "paid_unclear")
        self.assertIsNone(triage("求代做 Python 作业 有偿"))
        self.assertIsNone(triage("我接单，Word 不会排版的欢迎找我"))
        self.assertIsNone(triage("谁会 cadet 这个游戏"))
        self.assertEqual(triage("文档页码一改就不对齐"), "skill_review")
        self.assertEqual(triage("这怎么弄 [附图待审]"), "image_review")
        self.assertIsNone(triage("有没有人一起 [附图待审]"))
        self.assertIsNone(triage("捡到联系我，有偿帮忙"))
        self.assertEqual(triage("谁会做人工智能通识的作业（有偿）"), "assessment_review")
        self.assertEqual(triage("PLC 梯形图运行就报错，怎么调"), "skill_review")
        self.assertEqual(triage("有没有懂为啥电脑右侧声音沉闷有电流滋滋声"), "skill_review")
        self.assertIsNone(triage("11月5日频道「测试」发生了什么？有人求助有偿帮忙"))
        self.assertEqual(triage("有电脑能连校园网的代做吗一个表格"), "skill_review")
        self.assertEqual(triage("求帮写Wps操作系统"), "skill_review")
        self.assertEqual(triage("找一个会画画的朋友有偿"), "paid_unclear")

    def test_one_old_post_does_not_stop_scan(self):
        self.provider.latest_page.side_effect = [([self.post], None)]
        scan(self.db, self.provider, "1", "", 3)
        new_post = ("new", *self.post[1:])
        self.provider.latest_page.side_effect = [
            ([self.post], "one"), ([self.post, new_post], "two"), ([self.post], "three"),
        ]
        result = scan(self.db, self.provider, "1", "", 3)
        self.assertEqual((result["pages"], result["new"], result["coverage"]), (3, 1, "overlap"))
