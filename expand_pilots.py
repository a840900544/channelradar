"""Discover public pilot channels and collect a completed day per school."""

import argparse
import json
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from providers import ProviderError, TencentSkillProvider
from scan_day import BEIJING, scan_day


def choose_channel(provider, school: str, *, prefer_active: bool = False):
    # The pilot selects among the first three matches, so later search pages add no value.
    matches = [channel for channel in provider.search_channels(school, max_pages=1) if school in channel.name]
    public = []
    for channel in matches[:3]:
        info = provider.channel_info(channel.id)
        if info["guild_type"] == "公开腾讯频道":
            members = int(info.get("member_count") or 0)
            score = (members,)
            if prefer_active:
                rows, _ = provider.latest_page(channel.id, "", None)
                now = datetime.now(BEIJING).replace(tzinfo=None)
                times = [datetime.strptime(row[1], "%Y-%m-%d %H:%M:%S") for row in rows]
                recent = [timestamp for timestamp in times if now - timedelta(days=1) <= timestamp <= now]
                span = (max(recent) - min(recent)).total_seconds() if recent else 0
                score = (len(recent), 1 / max(span, 1), members)
                info["activity_screen"] = {
                    "sample_size": len(rows), "recent_24h": len(recent),
                    "recent_span_seconds": span,
                }
            public.append((channel.id, info, score))
    if not public:
        raise ProviderError("本轮搜索未定位到同名且确认公开的频道")
    guild, info, _ = max(public, key=lambda row: row[2])
    return guild, info


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--school", action="append", required=True)
    parser.add_argument("--date", type=date.fromisoformat, required=True)
    parser.add_argument("--db", default="channelradar.sqlite3")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=300)
    parser.add_argument("--prefer-active", action="store_true", help="比较候选频道发帖速度后选择入口")
    parser.add_argument("--min-daily-posts", type=int, default=50, help="高活跃实验筛选线，按完整日计数")
    parser.add_argument("--page-size", type=int, choices=range(1, 101), default=100)
    args = parser.parse_args()
    if args.min_daily_posts < 1:
        parser.error("活跃筛选线必须至少为每天 1 条")
    selection_mode = "activity" if args.prefer_active else "members"
    provider = TencentSkillProvider(args.cli, page_size=args.page_size)
    previous = {}
    if args.out.exists():
        previous = {item["school"]: item for item in json.loads(args.out.read_text(encoding="utf-8"))
                    if item.get("date") == args.date.isoformat()}
    reports = []
    with closing(sqlite3.connect(args.db)) as db:
        for school in dict.fromkeys(args.school):
            old = previous.get(school)
            if (old and old.get("scan", {}).get("coverage") in {"boundary_reached", "api_end"}
                    and old.get("selection_mode", "members") == selection_mode):
                result = old
            else:
                result = {"school": school, "date": args.date.isoformat(), "selection_mode": selection_mode}
                try:
                    guild, info = choose_channel(provider, school, prefer_active=args.prefer_active)
                    result.update({"guild": guild, "channel": info})
                    print(json.dumps({"school": school, "stage": "scan", "channel": info["name"]},
                                     ensure_ascii=False), flush=True)
                    result["scan"] = scan_day(db, provider, guild, args.date, args.max_pages)
                except (ProviderError, ValueError, sqlite3.Error) as exc:
                    result["error"] = str(exc)
            reports.append(result)
            completed = result.get("scan", {}).get("coverage") in {"boundary_reached", "api_end"}
            result["active_threshold"] = args.min_daily_posts
            result["active_qualified"] = completed and result["scan"]["posts"] >= args.min_daily_posts
            # Keep already finished schools if the process is interrupted.
            persisted = previous | {item["school"]: item for item in reports}
            temporary = args.out.with_suffix(args.out.suffix + ".tmp")
            temporary.write_text(json.dumps(list(persisted.values()), ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            temporary.replace(args.out)
            print(json.dumps(result, ensure_ascii=False), flush=True)
    if any(item.get("scan", {}).get("coverage") not in {"boundary_reached", "api_end"} for item in reports):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
