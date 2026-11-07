"""Collect a completed Beijing calendar day from an approved public channel."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from providers import ProviderError, TencentSkillProvider
from scan_latest import TRIAGE_VERSION, triage


BEIJING = timezone(timedelta(hours=8))
SCHEMA = """
CREATE TABLE IF NOT EXISTS day_runs (
    guild TEXT, day TEXT, channel_name TEXT, share_url TEXT, cursor TEXT,
    pages INTEGER NOT NULL DEFAULT 0, raw_count INTEGER NOT NULL DEFAULT 0,
    old_pages INTEGER NOT NULL DEFAULT 0, coverage TEXT NOT NULL DEFAULT 'running',
    error TEXT, updated_at TEXT NOT NULL, PRIMARY KEY(guild, day)
);
CREATE TABLE IF NOT EXISTS day_posts (
    guild TEXT, day TEXT, post TEXT, published TEXT, title TEXT, snippet TEXT,
    triage TEXT, rule_version TEXT, PRIMARY KEY(guild, day, post),
    FOREIGN KEY(guild, day) REFERENCES day_runs(guild, day) ON DELETE CASCADE
);
"""


def reclassify_day(db, guild: str, day: str) -> int:
    """Recheck stored summaries after a rule update without another API scan."""
    rows = db.execute(
        """SELECT post,title,snippet FROM day_posts
        WHERE guild=? AND day=? AND rule_version<>?""", (guild, day, TRIAGE_VERSION),
    ).fetchall()
    with db:
        for row in rows:
            db.execute(
                "UPDATE day_posts SET triage=?,rule_version=? WHERE guild=? AND day=? AND post=?",
                (triage(f"{row[1]} {row[2]}"), TRIAGE_VERSION, guild, day, row[0]),
            )
    return len(rows)


def summarize(db, guild: str, day: str) -> dict:
    db.row_factory = sqlite3.Row
    run = dict(db.execute(
        "SELECT * FROM day_runs WHERE guild=? AND day=?", (guild, day)
    ).fetchone())
    run.pop("cursor")  # Opaque pagination state is kept local.
    counts = db.execute(
        """SELECT COALESCE(triage,'no_rule_match') AS status, count(*) AS count
        FROM day_posts WHERE guild=? AND day=? GROUP BY triage""", (guild, day),
    ).fetchall()
    run["posts"] = sum(row["count"] for row in counts)
    run["triage_counts"] = {row["status"]: row["count"] for row in counts}
    run["candidates"] = [dict(row) for row in db.execute(
        """SELECT post,published,title,triage FROM day_posts
        WHERE guild=? AND day=? AND triage IS NOT NULL ORDER BY published DESC""", (guild, day),
    )]
    return run


def scan_day(db, provider, guild: str, day: date, max_pages: int = 300) -> dict:
    """Checkpoint each page. Stop only at API end or two entirely older pages."""
    if day >= datetime.now(BEIJING).date():
        raise ValueError("请选已经结束的北京时间自然日")
    if max_pages < 1:
        raise ValueError("页数预算必须大于零")
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    # Minimized text is retained for at most 30 calendar days for human review.
    cutoff = (datetime.now(BEIJING).date() - timedelta(days=30)).isoformat()
    with db:
        db.execute("DELETE FROM day_runs WHERE day < ?", (cutoff,))
    if day.isoformat() < cutoff:
        raise ValueError("日期超出 30 天实验数据保留窗口")
    info = provider.channel_info(guild)
    if info["guild_type"] != "公开腾讯频道":
        raise ProviderError("本实验仅扫描官方标记为公开的频道")
    stamp = datetime.now(BEIJING).isoformat()
    with db:
        db.execute(
            """INSERT OR IGNORE INTO day_runs
            (guild,day,channel_name,share_url,updated_at) VALUES (?,?,?,?,?)""",
            (guild, day.isoformat(), info["name"], info["share_url"], stamp),
        )
    state = db.execute(
        "SELECT * FROM day_runs WHERE guild=? AND day=?", (guild, day.isoformat())
    ).fetchone()
    reclassify_day(db, guild, day.isoformat())
    if state["coverage"] in {"boundary_reached", "api_end"}:
        return summarize(db, guild, day.isoformat())
    cursor, old_pages = state["cursor"], state["old_pages"]
    start = datetime.combine(day, datetime.min.time())
    end = start + timedelta(days=1)
    try:
        seen_cursors = {cursor} if cursor else set()
        for _ in range(max_pages):
            rows, next_cursor = provider.latest_page(guild, "", cursor)
            if not rows and next_cursor:
                raise ProviderError("Feed 返回空页但仍有分页令牌")
            parsed = [(row, datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S")) for row in rows]
            # Do not stop at one old item, which may be pinned or out of order.
            old_pages = old_pages + 1 if parsed and all(ts < start for _, ts in parsed) else 0
            coverage = "running"
            if next_cursor is None:
                coverage = "api_end"
            elif old_pages >= 2:
                coverage = "boundary_reached"
            elif next_cursor in seen_cursors:
                raise ProviderError("Feed 分页令牌重复，覆盖未完成")
            now = datetime.now(BEIJING).isoformat()
            with db:
                for row, published in parsed:
                    if start <= published < end:
                        post, timestamp, title, snippet = row
                        db.execute(
                            """INSERT INTO day_posts VALUES (?,?,?,?,?,?,?,?)
                            ON CONFLICT(guild,day,post) DO UPDATE SET
                            title=excluded.title,snippet=excluded.snippet,
                            triage=excluded.triage,rule_version=excluded.rule_version""",
                            (guild, day.isoformat(), post, timestamp, title, snippet,
                             triage(f"{title} {snippet}"), TRIAGE_VERSION),
                        )
                db.execute(
                    """UPDATE day_runs SET cursor=?,pages=pages+1,raw_count=raw_count+?,
                    old_pages=?,coverage=?,error=NULL,updated_at=? WHERE guild=? AND day=?""",
                    (next_cursor, len(rows), old_pages, coverage, now, guild, day.isoformat()),
                )
            if coverage != "running":
                return summarize(db, guild, day.isoformat())
            seen_cursors.add(next_cursor)
            cursor = next_cursor
        with db:
            db.execute(
                "UPDATE day_runs SET coverage='budget_exhausted' WHERE guild=? AND day=?",
                (guild, day.isoformat()),
            )
    except (ProviderError, ValueError) as exc:
        with db:
            db.execute(
                "UPDATE day_runs SET coverage='error',error=? WHERE guild=? AND day=?",
                (str(exc), guild, day.isoformat()),
            )
    return summarize(db, guild, day.isoformat())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--guild", action="append", required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--db", default="channelradar.sqlite3")
    parser.add_argument("--max-pages", type=int, default=300, help="每频道本次预算，耗尽后可续跑")
    parser.add_argument("--page-size", type=int, choices=range(1, 101), default=100)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    provider = TencentSkillProvider(args.cli, page_size=args.page_size)
    reports = []
    with closing(sqlite3.connect(args.db)) as db:
        for guild in dict.fromkeys(args.guild):
            try:
                result = scan_day(db, provider, guild, args.date, args.max_pages)
            except (ProviderError, ValueError, sqlite3.Error) as exc:
                result = {"guild": guild, "coverage": "error", "error": str(exc)}
            reports.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            args.out.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    if any(report.get("coverage") not in {"boundary_reached", "api_end"} for report in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
