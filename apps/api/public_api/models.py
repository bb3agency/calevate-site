"""`api_requests`: the API activity log, one row per public-surface request (W2.8, D-1047).

What a request WAS, never what it carried: the route TEMPLATE (`/api/v1/dnc/{entry_id}`,
never the resolved path), no query string, no body, no header but the version. That is
what lets the dashboard show every request to the people who manage keys without the log
becoming a second copy of the numbers and transcripts it touched (hard rule 6).

Written by the `api_requests` worker from a Redis stream, never on the request's own
transaction (`public_api/activity.py`). `stream_id` is the stream entry's id and is unique,
so a flush that is retried after a crash inserts nothing twice. Kept 30 days.

A plain table rather than a partitioned one: dropping a day's partition is DDL the app role
cannot run, and at this volume a batched DELETE by `created_at` does the same job.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin

RETENTION_DAYS: Final = 30
METHODS: Final = ("GET", "POST", "PUT", "PATCH", "DELETE")
API_REQUEST_CHECKS: Final = (
    f"method IN {METHODS!r}",
    "status BETWEEN 100 AND 599",
    "latency_ms >= 0",
)


class ApiRequest(PKMixin, Base):
    __tablename__ = "api_requests"
    __table_args__ = (
        CheckConstraint(API_REQUEST_CHECKS[0], name="method_enum"),
        CheckConstraint(API_REQUEST_CHECKS[1], name="status_bounds"),
        CheckConstraint(API_REQUEST_CHECKS[2], name="latency_bounds"),
        Index("ix_api_requests_tenant_created", "tenant_id", "created_at"),
        Index("ix_api_requests_key_created", "api_key_id", "created_at"),
        Index("uq_api_requests_stream_id", "stream_id", unique=True),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    api_key_id: Mapped[UUID] = mapped_column(
        ForeignKey("api_keys.id", ondelete="CASCADE"), nullable=False
    )
    stream_id: Mapped[str] = mapped_column(String(40), nullable=False)
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    route: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The problem `code` of a refusal (`core/errors.ProblemError.code`), else NULL.
    problem_code: Mapped[str | None] = mapped_column(String(80))
    #: Our own next-step sentence for that refusal, shown as "what to do".
    remediation: Mapped[str | None] = mapped_column(String(300))
    trace_id: Mapped[str | None] = mapped_column(String(64))
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    replayed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    api_version: Mapped[str] = mapped_column(String(10), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False)


__all__ = ["API_REQUEST_CHECKS", "METHODS", "RETENTION_DAYS", "ApiRequest"]
