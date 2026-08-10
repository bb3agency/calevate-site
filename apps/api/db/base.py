"""Declarative base, naming conventions and shared mixins (DATA-MODEL conventions).

- ids are UUIDv7 generated app-side (uuid-utils; PG16 has no native uuidv7()).
  Time-ordered ids keep b-tree inserts sequential.
- every table: created_at/updated_at timestamptz, server-side defaults.
- every tenant-scoped table: tenant_id + FORCEd RLS (policy lives in the migration,
  hard rule 1). TenantMixin carries the column; the RLS coverage guardrail asserts
  the policy exists for every table that has it.
"""

import uuid
from datetime import datetime

import uuid_utils
from sqlalchemy import DateTime, MetaData, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def uuid7() -> uuid.UUID:
    """App-side UUIDv7 as a stdlib UUID (SQLAlchemy needs uuid.UUID, not uuid_utils.UUID)."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    # Every datetime column is timestamptz (UTC in DB, IST at the edge — conventions).
    type_annotation_map = {datetime: DateTime(timezone=True)}  # noqa: RUF012


class PKMixin:
    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True, default=uuid7)


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class TenantMixin:
    """tenant_id on every tenant-scoped row. RLS policy ships in the same migration."""

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            PgUUID(as_uuid=True),
            nullable=False,
            index=True,
            # FK by name (not Column object) so mixin works across modules.
            # ondelete RESTRICT: offboarding is an explicit workflow (FLOWS §9),
            # never a cascade.
            server_default=None,
        )


# The RLS policy expression every tenant table gets (DATA-MODEL §1). Referenced by
# migrations and by the coverage guardrail — single source of truth. NULLIF: a
# pooled connection that once had the GUC returns '' (not NULL) when unset —
# ''::uuid would ERROR instead of failing closed to zero rows.
RLS_POLICY_SQL = text("tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid")
