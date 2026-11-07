"""Bounded activity and demand probe for manually selected public channels."""

import argparse
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from providers import ProviderError, TencentSkillProvider
from scan_latest import SKILL, triage


def probe(provider, guild: str) -> dict:
    info = provider.channel_info(guild)
    if info["guild_type"] != "公开腾讯频道":
        raise ProviderError("本实验仅测试官方标记为公开的频道")
    posts, cursor = provider.latest_page(guild, "", None)
    now = datetime.now(timezone(timedelta(hours=8)))
    recent = [
        post for post in posts
        if 0 <= (now - datetime.strptime(post[1], "%Y-%m-%d %H:%M:%S").replace(tzinfo=now.tzinfo)).total_seconds() <= 86400
    ]
    reviews = []
    skill_mentions = 0
    for post_id, published, title, snippet in posts:
        text = f"{title} {snippet}"
        skill_mentions += bool(SKILL.search(text))
        status = triage(text)
        if status:
            reviews.append({"post_id": post_id, "published": published, "title": title, "status": status})
    sections = provider.list_sections(guild)
    relevant = [section for section in sections if any(
        word in section.name for word in ("学习", "技术", "提问", "求助", "互帮", "软件", "编程")
    )]
    return {
        "channel": info, "observed_at": now.isoformat(), "sample_size": len(posts),
        "recent_24h_sample": len(recent), "oldest_sample": min((post[1] for post in posts), default=None),
        "skill_mentions": skill_mentions, "reviews": reviews,
        "sections": [{"id": section.id, "name": section.name} for section in relevant],
        "coverage": "first_page_only" if cursor else "end",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--guild", action="append", required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if len(args.guild) > 8:
        parser.error("单轮最多测试 8 个频道")
    provider = TencentSkillProvider(args.cli)
    results = []
    for guild in dict.fromkeys(args.guild):
        try:
            results.append(probe(provider, guild))
        except (ProviderError, ValueError) as exc:
            results.append({"guild": guild, "error": str(exc)})
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
