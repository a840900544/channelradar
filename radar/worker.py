"""Poll explicitly selected public channels and write results to the workbench."""

import argparse
import csv
import json
import sqlite3
import time
from contextlib import closing
from datetime import timedelta
from pathlib import Path

from sqlalchemy import create_engine, delete, event, select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from providers import ProviderError, TencentSkillProvider
from scan_latest import scan, triage
from .config import ROOT, Settings
from .importer import import_posts
from .models import Audit, Post, utcnow


def publish_posts(engine, provider, guild, info, schools, posts):
    candidates = [post for post, _, title, snippet in posts if triage(f"{title} {snippet}")]
    with Session(engine) as session:
        linked = set(session.scalars(select(Post.external_id).where(
            Post.provider == "tencent-skill", Post.guild_id == guild,
            Post.external_id.in_(candidates), Post.source_url.is_not(None),
        )))
    links = {}
    for post in [post for post in candidates if post not in linked][:3]:
        try:
            links[post] = provider.post_url(guild, post)
        except ProviderError:
            break
    rows = (
        dict(guild=guild, post=post, published=published, title=title, snippet=snippet,
             channel_name=info["name"], share_url=info["share_url"], source_url=links.get(post))
        for post, published, title, snippet in posts
    )
    with Session(engine) as session, session.begin():
        return import_posts(session, rows, {}, schools, cutoff=utcnow() - timedelta(days=30))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cli", type=Path, required=True)
    parser.add_argument("--guild", action="append", required=True)
    parser.add_argument("--interval", type=int, default=900)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.interval < 300:
        parser.error("扫描间隔至少 300 秒")
    settings = Settings()
    provider = TencentSkillProvider(args.cli, page_size=100)
    engine = create_engine(settings.database_url, pool_pre_ping=True)
    if engine.dialect.name == "sqlite":
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")
    with (ROOT / "universities.csv").open(encoding="utf-8", newline="") as source:
        schools = sorted((row["name"] for row in csv.DictReader(source)), key=len, reverse=True)
    try:
        with closing(sqlite3.connect(settings.source_db, timeout=30)) as checkpoint:
            while True:
                with Session(engine) as session, session.begin():
                    now = utcnow()
                    session.execute(delete(Post).where(Post.published_at < now - timedelta(days=90)))
                    session.execute(update(Post).where(Post.published_at < now - timedelta(days=30))
                                    .values(title="正文已过保留期", excerpt=""))
                    session.execute(delete(Audit).where(Audit.created_at < now - timedelta(days=180)))
                failed = False
                for guild in dict.fromkeys(args.guild):
                    try:
                        info = provider.channel_info(guild)
                        if info["guild_type"] != "公开腾讯频道":
                            raise ProviderError("频道未被官方标记为公开")
                        result = scan(
                            checkpoint, provider, guild, "", 6,
                            publish=lambda posts: publish_posts(engine, provider, guild, info, schools, posts),
                        )
                        result.pop("candidates")
                        print(json.dumps({"guild": guild, **result}, ensure_ascii=False), flush=True)
                    except (ProviderError, sqlite3.Error, SQLAlchemyError, ValueError) as exc:
                        failed = True
                        print(json.dumps({"guild": guild, "error": type(exc).__name__}), flush=True)
                if args.once:
                    return int(failed)
                time.sleep(args.interval)
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
