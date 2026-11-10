"""Modelo de dados do projeto (equivalente ao arquivo de projeto do Burp).

Tudo o que o usuário e o agente fazem fica registrado aqui. A conversa e o
estado do agente ficam nos checkpoints do LangGraph.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id() -> str:
    return uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    scope: Mapped[dict[str, Any]] = mapped_column(JSON)
    # {tool: {"enabled": bool, "manual": "ask" | "act"}}
    tool_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    llm_data_policy: Mapped[str] = mapped_column(String(20), default="any")
    llm_provider: Mapped[str | None] = mapped_column(String(40))
    llm_base_url: Mapped[str | None] = mapped_column(String(500))
    llm_model: Mapped[str | None] = mapped_column(String(200))
    llm_api_key_enc: Mapped[str | None] = mapped_column(Text)
    killed_reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(20), default="smart")
    # idle | running | waiting_approval | done | stopped | failed
    status: Mapped[str] = mapped_column(String(30), default="idle")
    steps_used: Mapped[int] = mapped_column(Integer, default=0)
    requests_used: Mapped[int] = mapped_column(Integer, default=0)
    tokens_used: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (UniqueConstraint("task_id", "tool_call_id"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(100))
    tool: Mapped[str] = mapped_column(String(100))
    args: Mapped[dict[str, Any]] = mapped_column(JSON)
    impact: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(Text)
    # pending | approved | rejected
    status: Mapped[str] = mapped_column(String(20), default="pending")
    # once | session | always | reject | redirect
    response: Mapped[str | None] = mapped_column(String(20))
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), index=True)
    tool_call_id: Mapped[str] = mapped_column(String(100))
    tool: Mapped[str] = mapped_column(String(100))
    args: Mapped[dict[str, Any]] = mapped_column(JSON)
    # executed | rejected | denied | blocked | error
    outcome: Mapped[str] = mapped_column(String(20))
    result: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Lead(Base):
    __tablename__ = "leads"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"))
    title: Mapped[str] = mapped_column(String(300))
    severity: Mapped[str] = mapped_column(String(10))
    url: Mapped[str] = mapped_column(Text)
    evidence: Mapped[str] = mapped_column(Text)
    # lead | confirmed | dismissed
    status: Mapped[str] = mapped_column(String(20), default="lead")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(20))  # agent | user | system
    kind: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str] = mapped_column(Text, default="")
    method: Mapped[str | None] = mapped_column(String(10))
    url: Mapped[str | None] = mapped_column(Text)
    resolved_ip: Mapped[str | None] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Exchange(Base):
    """Uma requisição e sua resposta (equivalente ao proxy history do Burp)."""

    __tablename__ = "exchanges"
    __table_args__ = (Index("ix_exchanges_project_host", "project_id", "host"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), index=True)
    task_id: Mapped[str | None] = mapped_column(String(32))
    # proxy | har | burp | agent | api
    source: Mapped[str] = mapped_column(String(20))
    method: Mapped[str] = mapped_column(String(10))
    url: Mapped[str] = mapped_column(Text)
    scheme: Mapped[str] = mapped_column(String(10))
    host: Mapped[str] = mapped_column(String(255))
    port: Mapped[int] = mapped_column(Integer)
    path: Mapped[str] = mapped_column(Text)
    query: Mapped[str] = mapped_column(Text, default="")
    request_headers: Mapped[list[Any]] = mapped_column(JSON, default=list)
    request_body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[int | None] = mapped_column(Integer)
    response_headers: Mapped[list[Any]] = mapped_column(JSON, default=list)
    response_body: Mapped[str] = mapped_column(Text, default="")
    response_size: Mapped[int] = mapped_column(Integer, default=0)
    mime: Mapped[str] = mapped_column(String(200), default="")
    elapsed_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
