import csv
import hashlib
import json
import re
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from providers import redact
from scan_latest import EXCLUDED, TRIAGE_VERSION, triage
from .config import ROOT
from .models import Audit, Lead, Post, utcnow


def safe_source_url(value):
    return value if isinstance(value, str) and re.fullmatch(r"https://pd\.qq\.com/s/[A-Za-z0-9_-]+", value) else None


def source_links(evidence_dir: Path) -> dict:
    links = {}
    for path in evidence_dir.glob("*review*.json"):
        report = json.loads(path.read_text(encoding="utf-8-sig"))
        for row in report.get("reviews", []):
            url = safe_source_url(row.get("source"))
            if url and isinstance(row.get("post"), str):
                links[row["post"]] = url
    return links


def import_experiments(session, source_db: Path, evidence_dir: Path, actor: str):
    if not source_db.is_file():
        raise ValueError("实验数据库不存在，请先完成采集")
    with (ROOT / "universities.csv").open(encoding="utf-8", newline="") as file:
        schools = sorted((row["name"] for row in csv.DictReader(file)), key=len, reverse=True)
    links = source_links(evidence_dir)
    with closing(sqlite3.connect(f"file:{source_db.resolve().as_posix()}?mode=ro", uri=True)) as source:
        source.row_factory = sqlite3.Row
        rows = source.execute("""
            SELECT p.*,r.channel_name,r.share_url FROM day_posts p
            JOIN day_runs r ON r.guild=p.guild AND r.day=p.day
            WHERE r.coverage IN ('boundary_reached','api_end')
        """).fetchall()
    result = import_posts(session, (dict(row) for row in rows), links, schools,
                          cutoff=utcnow() - timedelta(days=30))
    session.add(Audit(actor=actor, action="import_experiments", target=f"new={result['imported']},updated={result['updated']}"))
    return result


def import_posts(session, rows, links, schools, *, cutoff):
    scanned = 0
    new = changed = 0
    for row in rows:
        scanned += 1
        title, excerpt = redact(row["title"])[:500], redact(row["snippet"])[:1000]
        digest = hashlib.sha256(json.dumps([title, excerpt], ensure_ascii=False).encode()).hexdigest()
        published = datetime.fromisoformat(row["published"]).replace(
            tzinfo=timezone(timedelta(hours=8))
        ).astimezone(UTC).replace(tzinfo=None)
        if published < cutoff:
            continue
        post = session.scalar(select(Post).where(
            Post.provider == "tencent-skill", Post.guild_id == row["guild"], Post.external_id == row["post"]
        ))
        if post is None:
            school = next((name for name in schools if name in row["channel_name"]), row["channel_name"])
            post = Post(guild_id=row["guild"], external_id=row["post"], university=school,
                        channel=row["channel_name"], channel_url=safe_source_url(row["share_url"]),
                        title=title, excerpt=excerpt, published_at=published, content_hash=digest)
            session.add(post)
            post.lead = Lead(is_candidate=False, rule_version=TRIAGE_VERSION)
            new += 1
        elif post.content_hash != digest:
            post.title, post.excerpt, post.content_hash = title, excerpt, digest
            post.lead.eligibility = "pending"
            changed += 1
        post.source_url = safe_source_url(row.get("source_url")) or links.get(row["post"], post.source_url)
        lead = post.lead
        text = f"{title} {excerpt}"
        lead.rule_signal, lead.rule_version = triage(text), TRIAGE_VERSION
        lead.is_candidate = lead.rule_signal is not None
        lead.exclusion_reason = "规则发现已解决、广告、汇总或考核代做信号" if EXCLUDED.search(text) else None
        if lead.exclusion_reason:
            lead.eligibility = "excluded"
    return {"imported": new, "updated": changed, "scanned": scanned}
