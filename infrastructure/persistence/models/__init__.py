"""ORM-модели PostgreSQL (зеркало file-store manifest)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import JSON

from core.database import Base

JsonType = JSON().with_variant(JSONB, "postgresql")


class UserRecord(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    username: Mapped[str] = mapped_column(String(255))
    hashed_password: Mapped[str] = mapped_column(Text)
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    role: Mapped[str] = mapped_column(String(32), default="viewer")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class DatasetRecord(Base):
    __tablename__ = "datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(512))
    filename: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    stored_as: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    content_hash: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    row_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extra: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType, nullable=True)


class ReportRecord(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    dataset_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    report_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payload_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class ScheduledJobRecord(Base):
    __tablename__ = "scheduled_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    job_type: Mapped[str] = mapped_column(String(64))
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType, nullable=True)
    cron: Mapped[str] = mapped_column(String(128))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    webhook_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    last_run_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class JobRunRecord(Base):
    __tablename__ = "job_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scheduled_job_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    payload: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType, nullable=True)
    result: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class SavedViewRecord(Base):
    __tablename__ = "saved_views"
    __table_args__ = (UniqueConstraint("dataset_id", "view_id", name="uq_saved_view_dataset"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(Integer, index=True)
    view_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(255))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    mode: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    config: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_at: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class NLQueryRecord(Base):
    __tablename__ = "nl_queries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[int] = mapped_column(Integer, index=True)
    user_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    question: Mapped[str] = mapped_column(Text)
    plan: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType, nullable=True)
    result_preview: Mapped[Optional[dict[str, Any]]] = mapped_column(JsonType, nullable=True)
    created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
