"""`api_keys`: one row per tenant API key (D-1047, migration b1e7c4a9d2f3).

The secret is never stored; `secret_sha256` is its digest (`tokens.digest`). The row is
FORCE-RLS'd on the tenant; the one widening is a READ of the single row whose digest the
session names (`db/session.api_key_session`), which is how a bearer key finds its tenant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, CIDR
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

NAME_MAX: Final = 80
#: The per-key ceiling a person may set, per minute; NULL means the surface's own.
RATE_MIN: Final = 1
RATE_MAX: Final = 600
#: The most agents and address ranges one key may be bound to.
MAX_AGENTS: Final = 50
MAX_CIDRS: Final = 20

API_KEY_CHECKS: Final = (
    f"length(btrim(name)) BETWEEN 1 AND {NAME_MAX}",
    "cardinality(scopes) >= 1",
    f"rate_per_minute IS NULL OR rate_per_minute BETWEEN {RATE_MIN} AND {RATE_MAX}",
    f"agent_ids IS NULL OR cardinality(agent_ids) BETWEEN 1 AND {MAX_AGENTS}",
    f"ip_cidrs IS NULL OR cardinality(ip_cidrs) BETWEEN 1 AND {MAX_CIDRS}",
    "length(secret_sha256) = 64",
    "expires_at > created_at",
)


class ApiKey(PKMixin, TimestampMixin, Base):
    __tablename__ = "api_keys"
    __table_args__ = (
        CheckConstraint(API_KEY_CHECKS[0], name="name_bounds"),
        CheckConstraint(API_KEY_CHECKS[1], name="has_scope"),
        CheckConstraint(API_KEY_CHECKS[2], name="rate_bounds"),
        CheckConstraint(API_KEY_CHECKS[3], name="agent_bounds"),
        CheckConstraint(API_KEY_CHECKS[4], name="cidr_bounds"),
        CheckConstraint(API_KEY_CHECKS[5], name="digest_shape"),
        CheckConstraint(API_KEY_CHECKS[6], name="expires_after_created"),
        Index("ix_api_keys_tenant_created", "tenant_id", "created_at"),
        Index("uq_api_keys_secret_sha256", "secret_sha256", unique=True),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    #: The person who made it. A key never holds more than this person's role does, read
    #: again on every request, so a removed or demoted creator takes the key down with them.
    created_by: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(NAME_MAX), nullable=False)
    #: The first characters of the key, so the console can tell keys apart.
    display_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    secret_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False)
    agent_ids: Mapped[list[UUID] | None] = mapped_column(ARRAY(PgUUID(as_uuid=True)))
    ip_cidrs: Mapped[list[str] | None] = mapped_column(ARRAY(CIDR))
    rate_per_minute: Mapped[int | None] = mapped_column(Integer)
    #: The `Calevate-Version` this key answers in when a request names none (W2.13).
    api_version: Mapped[str] = mapped_column(String(10), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    last_used_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


__all__ = [
    "API_KEY_CHECKS",
    "MAX_AGENTS",
    "MAX_CIDRS",
    "NAME_MAX",
    "RATE_MAX",
    "RATE_MIN",
    "ApiKey",
]
