"""Run one bounded, read-only scan of an explicitly approved QQ channel."""

import argparse
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from providers import ProviderError, TencentSkillProvider


SKILL = re.compile(
    r"\b(?:ppt|word|excel|python|cad|matlab|spss|wps|vba|sql|bim|plc|"
    r"solidworks|ansys|simulink|keil|proteus|multisim|verilog|stm32)\b|"
    r"幻灯片|表格|单元格|数据透视|文档|页码|目录格式|排版|代码|程序|"
    r"调试|编程|建模|画图纸|网站|网页|小程序|数据分析|公式|参考文献格式|"
    r"单片机|仿真|梯形图|数控|电路图|三维制图|装配图|机械制图|电脑|声卡|驱动程序",
    re.I | re.ASCII,
)
DEMAND = re.compile(
    r"求助|求教|帮忙|谁会|有人会|有没有人|有没有懂|有人懂|怎么|如何|为啥|不会|报错|打不开|装不上|"
    r"对不上|不对齐|跑不起来|闪退|乱码|没反应|求帮|"
    r"求.{0,4}(做|写|改)|代做吗|找.{0,12}(老师|辅导|指导|帮|人做|会|能)"
)
EXCLUDED = re.compile(
    r"已解决|已经解决|已找到|已搞定|不用了|代考|代测|"
    r"代(?:写|做|交).{0,12}(作业|论文|考试|课设|毕设)|"
    r"(作业|论文|考试|课设|毕设).{0,12}找人代(?:写|做|交)|"
    r"接单|长期接|承接.{0,12}(排版|制作|开发)|欢迎下单|教程分享|经验分享|"
    r"\d{1,2}月\d{1,2}日频道「[^」]+」发生了什么"
)
TRIAGE_VERSION = "2026-11-07.8"


def triage(text: str) -> str | None:
    """Queue possible demand for human review using transparent heuristics."""
    if EXCLUDED.search(text):
        return None
    if "有偿" in text and re.search(r"作业|结课|实训|考核|毕设|论文", text):
        return "assessment_review"
    skill = SKILL.search(text)
    demand = DEMAND.search(text)
    if skill and demand:
        return "skill_review"
    if re.search(r"失物|丢了|捡到|代拿|代取|跑腿|搬东西|收养|疫苗|拼车|找搭子", text):
        return None
    if "有偿" in text and demand:
        return "paid_unclear"
    if "[附图待审]" in text and re.search(r"怎么弄|怎么做|谁会|有人会|有没有人会|帮.{0,6}(做|弄|看)", text):
        return "image_review"
    return None


def scan(db, provider, guild: str, section: str, max_pages: int, *, publish=None) -> dict:
    db.executescript("""
        CREATE TABLE IF NOT EXISTS feed_observations (
            guild TEXT, post TEXT, digest TEXT, published TEXT, first_seen TEXT,
            changed_at TEXT, triage TEXT, PRIMARY KEY (guild, post)
        );
        CREATE TABLE IF NOT EXISTS feed_source_posts (
            guild TEXT, section TEXT, post TEXT, PRIMARY KEY (guild, section, post)
        );
        CREATE TABLE IF NOT EXISTS feed_scans (
            id INTEGER PRIMARY KEY, guild TEXT, section TEXT, completed TEXT,
            pages INTEGER, coverage TEXT, new_posts INTEGER, updated_posts INTEGER
        );
    """)
    posts = {}
    cursor = None
    cursors = set()
    coverage = "page_cap"
    raw = 0
    for page in range(1, max_pages + 1):
        rows, cursor = provider.latest_page(guild, section, cursor)
        raw += len(rows)
        for post in rows:
            posts.setdefault(post[0], post)
        if cursor is None:
            coverage = "end"
            break
        if cursor in cursors:
            raise ProviderError("Feed 分页令牌重复")
        cursors.add(cursor)
        # A single repeated or pinned item does not establish continuity.
        if page >= 2 and rows:
            page_ids = {post[0] for post in rows}
            placeholders = ",".join("?" for _ in page_ids)
            known_count = db.execute(
                f"SELECT count(*) FROM feed_source_posts WHERE guild=? AND section=? "
                f"AND post IN ({placeholders})", (guild, section, *page_ids),
            ).fetchone()[0]
            if known_count == len(page_ids):
                coverage = "overlap"
                break

    now = datetime.now(UTC).isoformat()
    new = updated = 0
    candidates = []
    with db:
        db.execute("BEGIN IMMEDIATE")
        if publish is not None:
            # Commit the destination first. A checkpoint failure can safely replay the batch.
            publish(list(posts.values()))
        for post, published, title, snippet in posts.values():
            digest = hashlib.sha256(json.dumps([TRIAGE_VERSION, title, snippet]).encode()).hexdigest()
            previous = db.execute(
                "SELECT digest FROM feed_observations WHERE guild=? AND post=?", (guild, post)
            ).fetchone()
            db.execute("INSERT OR IGNORE INTO feed_source_posts VALUES (?,?,?)", (guild, section, post))
            if previous and previous[0] == digest:
                continue
            new += previous is None
            updated += previous is not None
            category = triage(f"{title} {snippet}")
            db.execute("""
                INSERT INTO feed_observations VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(guild,post) DO UPDATE SET
                    digest=excluded.digest, changed_at=excluded.changed_at, triage=excluded.triage
            """, (guild, post, digest, published, now, now, category))
            if category:
                candidates.append({"post_id": post, "published": published, "triage": category, "title": title})
        db.execute("INSERT INTO feed_scans VALUES (NULL,?,?,?,?,?,?,?)",
                   (guild, section, now, page, coverage, new, updated))
    return {"pages": page, "raw_posts": raw, "unique_posts": len(posts), "coverage": coverage,
            "new": new, "updated": updated, "candidates": candidates}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--guild", required=True)
    parser.add_argument("--section", default="")
    parser.add_argument("--db", default="channelradar.sqlite3")
    parser.add_argument("--max-pages", type=int, choices=range(2, 7), default=3)
    parser.add_argument("--authorized", action="store_true", help="确认本次频道或版块访问已获准")
    args = parser.parse_args()
    if not args.authorized:
        parser.error("须确认本次访问范围已获授权")
    try:
        with closing(sqlite3.connect(args.db)) as db:
            result = scan(db, TencentSkillProvider(args.cli), args.guild, args.section, args.max_pages)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ProviderError, sqlite3.Error) as exc:
        parser.exit(1, f"扫描失败：{exc}\n")


if __name__ == "__main__":
    main()
