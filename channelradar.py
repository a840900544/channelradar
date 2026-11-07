"""Local campus discovery and review."""

import argparse
import csv
import json
import sqlite3
import sys
import unicodedata
from contextlib import closing
from pathlib import Path

from providers import CollectorProvider, MockProvider, ProviderError, TencentSkillProvider, redact


SCHEMA = """
CREATE TABLE IF NOT EXISTS universities (
    name TEXT PRIMARY KEY, region TEXT NOT NULL, aliases TEXT NOT NULL,
    campuses TEXT NOT NULL, community TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS campus_channels (
    id INTEGER PRIMARY KEY, university TEXT NOT NULL REFERENCES universities(name),
    provider TEXT NOT NULL, external_id TEXT NOT NULL, name TEXT NOT NULL,
    description TEXT NOT NULL, url TEXT, confidence INTEGER NOT NULL,
    evidence TEXT NOT NULL, review TEXT NOT NULL DEFAULT 'pending',
    access TEXT NOT NULL DEFAULT 'unknown', review_note TEXT,
    UNIQUE (university, provider, external_id)
);
CREATE TABLE IF NOT EXISTS channel_sections (
    candidate_id INTEGER NOT NULL REFERENCES campus_channels(id) ON DELETE CASCADE,
    external_id TEXT NOT NULL, name TEXT NOT NULL, relevant INTEGER NOT NULL,
    PRIMARY KEY (candidate_id, external_id)
);
"""


def normalize(value: str) -> str:
    return "".join(unicodedata.normalize("NFKC", value).casefold().split())


def terms(value: str) -> list[str]:
    return [item for item in value.split("|") if item]


def initialize(db: sqlite3.Connection) -> None:
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    with Path(__file__).with_name("universities.csv").open(encoding="utf-8", newline="") as file:
        with db:
            db.executemany(
                "INSERT OR IGNORE INTO universities VALUES (:name,:region,:aliases,:campuses,:community)",
                csv.DictReader(file),
            )


class CampusDiscovery:
    def __init__(self, db: sqlite3.Connection, provider: CollectorProvider):
        self.db = db
        self.provider = provider

    def universities(self, query: str = "", *, exact: bool = False) -> list[dict]:
        key = normalize(query)
        matches = []
        for row in self.db.execute("SELECT * FROM universities ORDER BY name"):
            groups = [row["name"], *terms(row["aliases"]), *terms(row["campuses"]), *terms(row["community"])]
            normalized = [normalize(value) for value in groups]
            if (key in normalized if exact else any(key in value for value in normalized)):
                matches.append(dict(row))
        return matches

    def discover(self, query: str) -> list[dict]:
        schools = self.universities(query, exact=True)
        if len(schools) != 1:
            raise ValueError("高校不存在或名称有歧义，请使用高校全名")
        school = schools[0]
        formal = school["name"]
        aliases = terms(school["aliases"])
        campuses = terms(school["campuses"])
        community = terms(school["community"])
        found = {}
        for keyword in dict.fromkeys([formal, *aliases, *campuses, *community]):
            for channel in self.provider.search_channels(keyword):
                found.setdefault(channel.id, (channel, []))[1].append(keyword)

        with self.db:
            for channel, queries in found.values():
                name, description = redact(channel.name)[:120], redact(channel.description)[:400]
                title, body = normalize(name), normalize(description)
                signals = []
                for values, score, location in [
                    ([formal], 95, title), ([formal], 80, body),
                    (aliases + community, 70, title), (aliases + community, 50, body),
                    (campuses, 35, title), (campuses, 25, body),
                ]:
                    signals.extend((score, value) for value in values if normalize(value) in location)
                if not signals:
                    continue
                evidence = {"queries": queries, "matched": sorted({value for _, value in signals})}
                self.db.execute(
                    """INSERT INTO campus_channels
                    (university,provider,external_id,name,description,url,confidence,evidence)
                    VALUES (?,?,?,?,?,?,?,?)
                    ON CONFLICT(university,provider,external_id) DO UPDATE SET
                    name=excluded.name,description=excluded.description,
                    url=COALESCE(excluded.url,campus_channels.url),
                    confidence=excluded.confidence,evidence=excluded.evidence""",
                    (formal, self.provider.name, channel.id, name, description, channel.url,
                     max(score for score, _ in signals), json.dumps(evidence, ensure_ascii=False)),
                )
        return self.channels(formal)

    def channels(self, university: str | None = None) -> list[dict]:
        rows = self.db.execute(
            """SELECT * FROM campus_channels WHERE (? IS NULL OR university=?)
            ORDER BY confidence DESC, id""", (university, university)
        )
        return [dict(row) | {"evidence": json.loads(row["evidence"])} for row in rows]

    def review(self, candidate_id: int, review: str, access: str, note: str) -> dict:
        if review not in {"approved", "rejected"}:
            raise ValueError("无效的审核结论")
        if review == "approved" and access not in {"public", "authorized"}:
            raise ValueError("批准前须确认公开或授权访问")
        if not note.strip():
            raise ValueError("请填写访问范围或拒绝原因")
        with self.db:
            row = self.db.execute(
                """UPDATE campus_channels SET review=?,access=?,review_note=?
                WHERE id=? RETURNING *""",
                (review, access if review == "approved" else "unknown", redact(note)[:500], candidate_id),
            ).fetchone()
            if row is None:
                raise ValueError("候选频道不存在")
            if review == "rejected":
                self.db.execute("DELETE FROM channel_sections WHERE candidate_id=?", (candidate_id,))
        return dict(row) | {"evidence": json.loads(row["evidence"])}

    def refresh_sections(self, candidate_id: int) -> list[dict]:
        row = self.db.execute("SELECT * FROM campus_channels WHERE id=?", (candidate_id,)).fetchone()
        if row is None or row["review"] != "approved" or row["access"] not in {"public", "authorized"}:
            raise ValueError("须先审核频道并确认访问范围")
        if row["provider"] != self.provider.name:
            raise ValueError("频道来源与当前 Provider 不一致")
        sections = self.provider.list_sections(row["external_id"])
        with self.db:
            # Serialize the permission recheck and snapshot write against review updates.
            self.db.execute("BEGIN IMMEDIATE")
            current = self.db.execute(
                "SELECT review,access,review_note FROM campus_channels WHERE id=?", (candidate_id,)
            ).fetchone()
            if current is None or tuple(current) != (row["review"], row["access"], row["review_note"]):
                raise ValueError("审核状态已变更，请重新发起查询")
            self.db.execute("DELETE FROM channel_sections WHERE candidate_id=?", (candidate_id,))
            for section in {section.id: section for section in sections}.values():
                name = redact(section.name)[:120]
                relevant = any(term in name for term in ("学习", "求助", "提问", "技术", "软件", "互助", "互帮互助", "校园服务"))
                self.db.execute("INSERT INTO channel_sections VALUES (?,?,?,?)",
                                (candidate_id, section.id, name, relevant))
        return [dict(item) for item in self.db.execute(
            "SELECT * FROM channel_sections WHERE candidate_id=? ORDER BY relevant DESC, external_id",
            (candidate_id,),
        )]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default="channelradar.sqlite3")
    parser.add_argument("--tencent-cli", type=Path, help="仅在已确认授权和访问范围时使用")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("universities").add_argument("query", nargs="?", default="")
    actions.add_parser("discover").add_argument("school")
    actions.add_parser("channels")
    review = actions.add_parser("review")
    review.add_argument("id", type=int)
    review.add_argument("decision", choices=["approved", "rejected"])
    review.add_argument("--access", choices=["public", "authorized", "unknown"], default="unknown")
    review.add_argument("--note", required=True)
    actions.add_parser("sections").add_argument("id", type=int)
    args = parser.parse_args()
    try:
        with closing(sqlite3.connect(args.db)) as db:
            initialize(db)
            provider = TencentSkillProvider(args.tencent_cli) if args.tencent_cli else MockProvider()
            service = CampusDiscovery(db, provider)
            match args.action:
                case "universities":
                    result = service.universities(args.query)
                case "discover":
                    result = service.discover(args.school)
                case "channels":
                    result = service.channels()
                case "review":
                    result = service.review(args.id, args.decision, args.access, args.note)
                case "sections":
                    result = service.refresh_sections(args.id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, ProviderError, sqlite3.Error) as exc:
        print(f"操作失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
