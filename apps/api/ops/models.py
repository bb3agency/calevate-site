"""Platform-scoped configuration tables (PLATFORM-CONFIG §5).

NEITHER TABLE IS TENANT-SCOPED and neither ever will be. They are PLATFORM state —
one engine selection, one calling window, one config version for every client at the
same instant — so they carry no `tenant_id`, they are reachable only from the admin
realm behind `platform:config`, and they are registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as the written reason. Per-tenant
credentials are a different table and a different problem (§11).

Giving them a fake `tenant_id` to satisfy the RLS checker was considered and rejected in
one line: a column nothing writes and nothing reads, whose only purpose is to make a
guardrail agree, is a lie the next reader inherits — and it would make the pair LOOK
tenant-scoped to every sweep that discovers tables by their columns.

Declared as ORM models rather than as raw DDL in the migration alone so that
`Base.metadata` knows about them: `check_rls_coverage` compares the live schema against
that metadata and reports "tables in DB not in model metadata", and alembic's
autogenerate is blind to anything it cannot see.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, ForeignKey, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base


class PlatformSetting(Base):
    """One core-config override. Plaintext, readable, revertible.

    NEVER a credential. `ops/config_service.py` refuses any key whose NAME matches the
    log-redaction patterns (`core/logging.REDACT_KEYS`) — one list deciding both "must
    never be logged" and "must never be stored here", rather than a second hand-kept
    list of secret-shaped names that would eventually disagree with the first.
    """

    __tablename__ = "platform_settings"

    #: The `Settings` field name, exactly. Not a display label and not an env var
    #: spelling: the resolution layer applies this dict straight onto the model, so a
    #: key that is not a field cannot be stored (`validate_key` refuses it at the
    #: boundary) and a field rename shows up as a stale row rather than a silent no-op.
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    #: The value in its JSON form — the same form `TypeAdapter.dump_python(mode="json")`
    #: produced when it was validated. `Decimal` therefore lands as a STRING, never a
    #: JSON float (hard rule 7): `88.50` as a double is not `88.50`.
    value: Mapped[Any] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=False
    )
    #: WHY, for the next reader. Required at the API boundary (the operator's stated
    #: reason, which also lands in `audit_log`); nullable here because a row written by
    #: a migration or a seed has no operator to state one.
    note: Mapped[str | None] = mapped_column(Text)


class PlatformConfigVersion(Base):
    """The sentinel every process polls. ONE row, ever.

    `id boolean PRIMARY KEY DEFAULT true CHECK (id)` is the standard singleton idiom:
    the only value the primary key admits is `true`, so a second row is a constraint
    violation rather than a race nobody notices. (`platform_state` uses an integer `id`
    with a CHECK for the same job; this shape is the tighter one and the spec names it.)

    THE MIGRATION GIVES `platform_settings` A TRIGGER THAT BUMPS THIS. That is the
    difference between a version that describes the data and a version somebody
    remembers to update: a value changed by the console, by a migration, or by an
    operator in psql at 3am all move the sentinel, so every process notices. See the
    migration for the argument.
    """

    __tablename__ = "platform_config_version"

    id: Mapped[bool] = mapped_column(Boolean, primary_key=True, server_default="true")
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="1")
    bumped_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


__all__ = ["PlatformConfigVersion", "PlatformSetting"]
