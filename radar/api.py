import hmac
import json
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager, closing
from datetime import timedelta
from threading import Lock
from typing import Literal

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Integer, create_engine, delete, event, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.exc import StaleDataError

from providers import redact
from .config import ROOT, Settings
from .importer import import_experiments
from .models import AdminSession, Audit, Feedback, Lead, Post, utcnow
from .security import csrf_token, token_digest, verify_password


Status = Literal["new", "qualified", "contacted", "won", "lost", "ignored"]
Eligibility = Literal["pending", "eligible", "excluded"]
Category = Literal["unknown", "ppt", "word", "excel", "coding", "engineering", "web", "computer", "other"]


class Login(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=100)
    password: str = Field(max_length=256)


class Review(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    status: Status
    eligibility: Eligibility
    category: Category = "unknown"
    note: str = Field(default="", max_length=1000)
    label: Literal["useful", "false_positive", "resolved", "ad", "assessment", "unknown"] = "unknown"
    amount_fen: int | None = Field(default=None, ge=0, le=100_000_000)


def lead_json(lead):
    post = lead.post
    return {
        "id": lead.id, "version": lead.version, "status": lead.status,
        "eligibility": lead.eligibility, "category": lead.category,
        "rule_signal": lead.rule_signal, "rule_version": lead.rule_version,
        "is_candidate": lead.is_candidate, "exclusion_reason": lead.exclusion_reason,
        "note": lead.note, "amount_fen": lead.amount_fen,
        "university": post.university, "channel": post.channel,
        "title": post.title, "excerpt": post.excerpt, "source_url": post.source_url,
        "channel_url": post.channel_url, "published_at": post.published_at.isoformat() + "Z",
        "updated_at": lead.updated_at.isoformat() + "Z",
    }


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    if settings.production and (
        not settings.cookie_secure
        or verify_password("666", settings.admin_password_hash.get_secret_value())
    ):
        raise RuntimeError("生产环境要求 Secure Cookie 与独立的强管理员密码")
    sqlite_args = {"check_same_thread": False, "timeout": 30} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=sqlite_args, pool_pre_ping=True)
    if settings.database_url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def sqlite_constraints(connection, record):
            cursor = connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="ChannelRadar", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.state.engine = engine
    failures = defaultdict(deque)
    login_lock = Lock()

    def database():
        with Session(engine, expire_on_commit=False) as session:
            yield session

    def admin(request: Request, db: Session = Depends(database)):
        raw = request.cookies.get("radar_session", "")
        stored = db.get(AdminSession, token_digest(raw)) if raw else None
        if stored is None or stored.expires_at <= utcnow():
            raise HTTPException(401, "请先登录")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            expected = csrf_token(settings.session_secret.get_secret_value(), raw)
            if not hmac.compare_digest(request.headers.get("X-CSRF-Token", ""), expected):
                raise HTTPException(403, "会话校验失败，请刷新页面")
        return settings.admin_username

    @app.middleware("http")
    async def headers(request, call_next):
        length = request.headers.get("content-length", "0")
        if not length.isdigit():
            return JSONResponse({"detail": "请求长度无效"}, status_code=400)
        if int(length) > 2_000_000:
            return JSONResponse({"detail": "请求过大"}, status_code=413)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(StaleDataError)
    async def conflict(request, exc):
        return JSONResponse({"detail": "记录已更新，请刷新后重新审核"}, status_code=409)

    @app.exception_handler(IntegrityError)
    async def duplicate(request, exc):
        return JSONResponse({"detail": "数据已由其他任务修改，请刷新后重试"}, status_code=409)

    @app.get("/healthz")
    def health():
        return {"status": "ok"}

    @app.get("/readyz")
    def ready(db: Session = Depends(database)):
        db.scalar(select(func.count()).select_from(AdminSession))
        return {"status": "ok"}

    @app.post("/api/v1/session")
    def login(payload: Login, request: Request, response: Response, db: Session = Depends(database)):
        address = request.client.host if request.client else "local"
        now = time.monotonic()
        with login_lock:
            queue = failures[address]
            while queue and queue[0] < now - 900:
                queue.popleft()
            if len(queue) >= 5:
                raise HTTPException(429, "登录尝试过多，请在 15 分钟后重试")
            valid_password = verify_password(payload.password, settings.admin_password_hash.get_secret_value())
            if not hmac.compare_digest(payload.username.encode(), settings.admin_username.encode()) or not valid_password:
                queue.append(now)
                raise HTTPException(401, "账号或密码错误")
            failures.pop(address, None)
        db.execute(delete(AdminSession).where(AdminSession.expires_at <= utcnow()))
        previous = request.cookies.get("radar_session")
        if previous:
            db.execute(delete(AdminSession).where(AdminSession.digest == token_digest(previous)))
        raw = secrets.token_urlsafe(32)
        db.add(AdminSession(digest=token_digest(raw), expires_at=utcnow() + timedelta(hours=settings.session_hours)))
        db.commit()
        response.set_cookie("radar_session", raw, httponly=True, secure=settings.cookie_secure,
                            samesite="strict", max_age=settings.session_hours * 3600)
        return {"username": settings.admin_username, "csrf_token": csrf_token(settings.session_secret.get_secret_value(), raw)}

    @app.get("/api/v1/session", dependencies=[Depends(admin)])
    def whoami(request: Request):
        return {"username": settings.admin_username, "csrf_token": csrf_token(
            settings.session_secret.get_secret_value(), request.cookies["radar_session"])}

    @app.delete("/api/v1/session", dependencies=[Depends(admin)])
    def logout(request: Request, response: Response, db: Session = Depends(database)):
        db.execute(delete(AdminSession).where(
            AdminSession.digest == token_digest(request.cookies["radar_session"])))
        db.commit()
        response.delete_cookie("radar_session", secure=settings.cookie_secure, httponly=True, samesite="strict")
        return {"ok": True}

    @app.get("/api/v1/dashboard", dependencies=[Depends(admin)])
    def dashboard(db: Session = Depends(database)):
        counts = dict(db.execute(select(Lead.status, func.count()).group_by(Lead.status)).all())
        distribution = db.execute(
            select(Post.university, func.count(Post.id), func.sum(Lead.is_candidate.cast(Integer)))
            .join(Lead).group_by(Post.university).order_by(func.count(Post.id).desc())
        ).all()
        return {
            "posts": db.scalar(select(func.count()).select_from(Post)),
            "candidates": db.scalar(select(func.count()).select_from(Lead).where(Lead.is_candidate.is_(True))),
            "qualified": db.scalar(select(func.count()).select_from(Lead).where(
                Lead.eligibility == "eligible", Lead.status.in_(["qualified", "contacted", "won"]))),
            "statuses": counts,
            "revenue_fen": db.scalar(select(func.coalesce(func.sum(Lead.amount_fen), 0)).where(Lead.status == "won")),
            "universities": [{"name": name, "posts": posts, "candidates": candidates or 0}
                             for name, posts, candidates in distribution],
        }

    @app.get("/api/v1/leads", dependencies=[Depends(admin)])
    def leads(candidate_only: bool = True, university: str = "", status: Status | None = None,
              q: str = Query(default="", max_length=100), page: int = Query(default=1, ge=1),
              page_size: int = Query(default=30, ge=1, le=100), db: Session = Depends(database)):
        query = select(Lead).join(Post)
        if candidate_only:
            query = query.where(or_(
                Lead.is_candidate.is_(True), Lead.eligibility == "eligible",
                Lead.status.in_(["qualified", "contacted", "won", "lost"]),
            ))
        if university:
            query = query.where(Post.university == university)
        if status:
            query = query.where(Lead.status == status)
        if q:
            query = query.where(Post.title.contains(q, autoescape=True) | Post.excerpt.contains(q, autoescape=True))
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        records = db.scalars(query.options(joinedload(Lead.post)).order_by(
            Post.published_at.desc(), Lead.id.desc()).offset((page - 1) * page_size).limit(page_size)).all()
        return {"total": total, "items": [lead_json(lead) for lead in records]}

    @app.get("/api/v1/leads/{lead_id}", dependencies=[Depends(admin)])
    def detail(lead_id: int, db: Session = Depends(database)):
        lead = db.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(404, "记录不存在")
        return lead_json(lead) | {"feedback": [
            {"label": item.label, "note": item.note, "actor": item.actor,
             "created_at": item.created_at.isoformat() + "Z"}
            for item in db.scalars(select(Feedback).where(Feedback.lead_id == lead_id)
                                   .order_by(Feedback.id.desc()).limit(50))
        ]}

    @app.post("/api/v1/leads/{lead_id}/feedback")
    def review(lead_id: int, payload: Review, actor=Depends(admin), db: Session = Depends(database)):
        lead = db.get(Lead, lead_id)
        if lead is None:
            raise HTTPException(404, "记录不存在")
        if lead.version != payload.version:
            raise HTTPException(409, "记录已更新，请刷新后重新审核")
        if payload.eligibility == "eligible" and lead.exclusion_reason:
            raise HTTPException(422, "当前内容有排除信号，请记录反馈并核实来源")
        if payload.label in {"false_positive", "resolved", "ad", "assessment"} and payload.eligibility != "excluded":
            raise HTTPException(422, "该反馈结论需要同时标记为已排除")
        if payload.status in {"qualified", "contacted", "won"} and payload.eligibility != "eligible":
            raise HTTPException(422, "确认可承接后才能进入有效商机或成交状态")
        if not payload.note.strip():
            raise HTTPException(422, "请填写判断依据或跟进记录")
        before = json.dumps({"status": lead.status, "eligibility": lead.eligibility,
                             "category": lead.category, "amount_fen": lead.amount_fen})
        lead.status, lead.eligibility, lead.category = payload.status, payload.eligibility, payload.category
        lead.note = redact(payload.note)
        lead.amount_fen = payload.amount_fen if payload.status == "won" else None
        # Force a version change even when an operator only adds feedback.
        lead.updated_at = utcnow()
        after = json.dumps({"status": lead.status, "eligibility": lead.eligibility,
                            "category": lead.category, "amount_fen": lead.amount_fen})
        db.add(Feedback(lead_id=lead.id, actor=actor, label=payload.label, note=lead.note,
                        before_state=before, after_state=after))
        db.add(Audit(actor=actor, action="review_lead", target=str(lead.id)))
        db.commit()
        return lead_json(lead)

    @app.post("/api/v1/imports/experiments")
    def import_data(actor=Depends(admin), db: Session = Depends(database)):
        try:
            result = import_experiments(db, settings.source_db, settings.evidence_dir, actor)
            db.commit()
            return result
        except (ValueError, sqlite3.Error):
            db.rollback()
            raise HTTPException(422, "实验数据无法导入，请检查服务器配置和采集结果")

    @app.get("/api/v1/scan-jobs", dependencies=[Depends(admin)])
    def jobs():
        if not settings.source_db.is_file():
            return {"items": []}
        with closing(sqlite3.connect(
            f"file:{settings.source_db.resolve().as_posix()}?mode=ro", uri=True
        )) as source:
            source.row_factory = sqlite3.Row
            rows = source.execute("""
                SELECT r.guild,r.day,r.channel_name,r.pages,r.coverage,r.updated_at,
                count(p.post) AS posts FROM day_runs r LEFT JOIN day_posts p
                ON p.guild=r.guild AND p.day=r.day
                GROUP BY r.guild,r.day ORDER BY r.updated_at DESC LIMIT 300
            """).fetchall()
        return {"items": [dict(row) for row in rows]}

    dist = ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app
