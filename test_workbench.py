import json
import secrets
import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from radar.api import create_app
from radar.config import Settings
from radar.models import Base, Feedback, Lead
from radar.security import hash_password


class WorkbenchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.password = secrets.token_urlsafe(24)
        cls.password_hash = hash_password(cls.password)

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        source = root / "source.sqlite3"
        with closing(sqlite3.connect(source)) as db:
            db.executescript("""
                CREATE TABLE day_runs(guild,day,channel_name,share_url,coverage,pages,updated_at);
                CREATE TABLE day_posts(guild,day,post,published,title,snippet);
                INSERT INTO day_runs VALUES ('1','2026-11-06','深圳大学模拟频道',NULL,'boundary_reached',3,'2026-11-07');
                INSERT INTO day_posts VALUES ('1','2026-11-06','one','2026-11-06 09:00:00','表格排序后姓名对不上','求帮忙');
                INSERT INTO day_posts VALUES ('1','2026-11-06','two','2026-11-06 09:01:00','求代写 Python 作业','有偿');
                INSERT INTO day_posts VALUES ('1','2026-11-06','three','2026-11-06 09:02:00','普通闲聊','');
            """)
        (root / "review.json").write_text(json.dumps({"reviews": [
            {"post": "one", "source": "https://pd.qq.com/s/test"},
            {"post": "three", "source": "javascript:alert(1)"},
        ]}), encoding="utf-8")
        settings = Settings(
            _env_file=None, database_url=f"sqlite:///{root / 'web.sqlite3'}",
            source_db=source, evidence_dir=root, admin_password_hash=self.password_hash,
            session_secret=secrets.token_urlsafe(40), cookie_secure=False,
        )
        self.app = create_app(settings)
        Base.metadata.create_all(self.app.state.engine)
        self.client = self.enterContext(TestClient(self.app))
        self.source = source

    def login(self):
        result = self.client.post("/api/v1/session", json={"username": "admin", "password": self.password})
        self.assertEqual(result.status_code, 200)
        self.csrf = {"X-CSRF-Token": result.json()["csrf_token"]}
        return result

    def import_data(self):
        result = self.client.post("/api/v1/imports/experiments", headers=self.csrf)
        self.assertEqual(result.status_code, 200)
        return result.json()

    def test_session_csrf_and_logout_revocation(self):
        self.assertEqual(self.client.get("/api/v1/leads").status_code, 401)
        result = self.login()
        self.assertIn("HttpOnly", result.headers["set-cookie"])
        self.assertEqual(self.client.post("/api/v1/imports/experiments").status_code, 403)
        token = self.client.cookies.get("radar_session")
        self.assertEqual(self.client.delete("/api/v1/session", headers=self.csrf).status_code, 200)
        self.client.cookies.set("radar_session", token)
        self.assertEqual(self.client.get("/api/v1/session").status_code, 401)

    def test_import_review_feedback_and_idempotence(self):
        self.login()
        self.assertEqual(self.import_data()["imported"], 3)
        lead = self.client.get("/api/v1/leads").json()["items"][0]
        self.assertEqual(lead["source_url"], "https://pd.qq.com/s/test")
        payload = {"version": lead["version"], "status": "won", "eligibility": "eligible",
                   "category": "excel", "note": "确认属于合法表格处理，已人工完成", "label": "useful", "amount_fen": 12345}
        result = self.client.post(f"/api/v1/leads/{lead['id']}/feedback", json=payload, headers=self.csrf)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(self.client.post(
            f"/api/v1/leads/{lead['id']}/feedback", json=payload, headers=self.csrf
        ).status_code, 409)
        self.assertEqual(self.import_data()["imported"], 0)
        detail = self.client.get(f"/api/v1/leads/{lead['id']}").json()
        self.assertEqual(detail["status"], "won")
        self.assertEqual(len(detail["feedback"]), 1)
        self.assertEqual(self.client.get("/api/v1/dashboard").json()["revenue_fen"], 12345)
        all_posts = self.client.get("/api/v1/leads?candidate_only=false").json()
        self.assertEqual(all_posts["total"], 3)
        self.assertIsNone(next(row for row in all_posts["items"] if row["title"] == "普通闲聊")["source_url"])
        missed = next(row for row in all_posts["items"] if row["title"] == "普通闲聊")
        recovered = self.client.post(f"/api/v1/leads/{missed['id']}/feedback", headers=self.csrf, json={
            "version": missed["version"], "status": "qualified", "eligibility": "eligible", "note": "原帖详情中核实到真实需求",
        })
        self.assertEqual(recovered.status_code, 200)
        self.assertIn(missed["id"], [row["id"] for row in self.client.get("/api/v1/leads").json()["items"]])

    def test_exclusions_and_failed_import_are_atomic(self):
        self.login()
        self.import_data()
        records = self.client.get("/api/v1/leads?candidate_only=false").json()["items"]
        excluded = next(row for row in records if row["eligibility"] == "excluded")
        result = self.client.post(f"/api/v1/leads/{excluded['id']}/feedback", headers=self.csrf, json={
            "version": excluded["version"], "status": "qualified", "eligibility": "eligible", "note": "想承接",
        })
        self.assertEqual(result.status_code, 422)
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("INSERT INTO day_posts VALUES ('1','2026-11-06','new','2026-11-06 09:03:00','新记录','')")
            db.execute("INSERT INTO day_posts VALUES ('1','2026-11-06','bad','invalid','坏日期','')")
            db.commit()
        self.assertEqual(self.client.post("/api/v1/imports/experiments", headers=self.csrf).status_code, 422)
        self.assertEqual(self.client.get("/api/v1/dashboard").json()["posts"], 3)
        with Session(self.app.state.engine) as db:
            self.assertEqual(db.query(Feedback).count(), 0)

    def test_source_update_requires_revalidation(self):
        self.login()
        self.import_data()
        lead = self.client.get("/api/v1/leads").json()["items"][0]
        result = self.client.post(f"/api/v1/leads/{lead['id']}/feedback", headers=self.csrf, json={
            "version": lead["version"], "status": "qualified", "eligibility": "eligible", "note": "已核实任务用途",
        })
        self.assertEqual(result.status_code, 200)
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("UPDATE day_posts SET snippet='任务内容已经变更' WHERE post='one'")
            db.commit()
        self.assertEqual(self.import_data()["updated"], 1)
        detail = self.client.get(f"/api/v1/leads/{lead['id']}").json()
        self.assertEqual(detail["eligibility"], "pending")
        self.assertGreater(detail["version"], result.json()["version"])
        self.assertEqual(detail["note"], "已核实任务用途")

    def test_login_rate_limit(self):
        for _ in range(5):
            self.assertEqual(self.client.post("/api/v1/session", json={
                "username": "admin", "password": "incorrect",
            }).status_code, 401)
        self.assertEqual(self.client.post("/api/v1/session", json={
            "username": "admin", "password": self.password,
        }).status_code, 429)
