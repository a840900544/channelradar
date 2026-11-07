from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow():
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("provider", "guild_id", "external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(40), default="tencent-skill")
    guild_id: Mapped[str] = mapped_column(String(80))
    external_id: Mapped[str] = mapped_column(String(160))
    university: Mapped[str] = mapped_column(String(150), index=True)
    channel: Mapped[str] = mapped_column(String(200))
    channel_url: Mapped[str | None] = mapped_column(String(500))
    source_url: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(500))
    excerpt: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    lead: Mapped["Lead"] = relationship(back_populates="post", uselist=False, cascade="all, delete-orphan")


class Lead(Base):
    __tablename__ = "leads"
    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), unique=True)
    is_candidate: Mapped[bool] = mapped_column(Boolean, index=True)
    rule_signal: Mapped[str | None] = mapped_column(String(50))
    rule_version: Mapped[str] = mapped_column(String(60))
    eligibility: Mapped[str] = mapped_column(String(20), default="pending")
    exclusion_reason: Mapped[str | None] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(20), default="new", index=True)
    category: Mapped[str] = mapped_column(String(40), default="unknown")
    note: Mapped[str] = mapped_column(Text, default="")
    amount_fen: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    post: Mapped[Post] = relationship(back_populates="lead")
    __mapper_args__ = {"version_id_col": version}


class Feedback(Base):
    __tablename__ = "lead_feedback"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("leads.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(100))
    label: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text)
    before_state: Mapped[str] = mapped_column(Text)
    after_state: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Audit(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(100))
    action: Mapped[str] = mapped_column(String(60))
    target: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class AdminSession(Base):
    __tablename__ = "admin_sessions"
    digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime, index=True)
