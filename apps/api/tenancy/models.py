"""Tenancy & identity (DATA-MODEL §2).

organizations is the tenant root: its RLS policy matches on `id`, every other
tenant table matches on `tenant_id`. Enums are TEXT + CHECK (mirroring the Pydantic
enums, DATA-MODEL §10) — cheaper to evolve than native PG enums.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

ORG_STATUSES = ("prospect", "onboarding", "active", "suspended", "churned")
MEMBER_ROLES = ("owner", "staff")
ADMIN_ROLES = ("superadmin", "operator")


class Organization(PKMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9-]{3,40}$'", name="slug_shape"),
        CheckConstraint(f"status IN {ORG_STATUSES!r}".replace("(", "(", 1), name="status_enum"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Immutability enforced by trigger in the migration (slug is in client URLs).
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="prospect")
    vertical_template: Mapped[str | None] = mapped_column(Text)
    billing_email: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    deleted_at: Mapped[datetime | None]


class ReservedSlug(Base):
    __tablename__ = "reserved_slugs"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class User(PKMixin, TimestampMixin, Base):
    """Global identity (crosses tenants via memberships) — NOT tenant-scoped."""

    __tablename__ = "users"

    clerk_user_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)  # E.164


class Membership(PKMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint(f"role IN {MEMBER_ROLES!r}", name="role_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # staff: no billing.*, no org settings, no raw (unredacted) transcripts
    role: Mapped[str] = mapped_column(String, nullable=False)


class Invitation(PKMixin, TimestampMixin, Base):
    """Single-use, 72h, hash-at-rest; burned on accept (CAS on used_at IS NULL)."""

    __tablename__ = "invitations"
    __table_args__ = (CheckConstraint(f"role IN {MEMBER_ROLES!r}", name="role_enum"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    email: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        server_default=func.now() + func.make_interval(0, 0, 0, 0, 72), nullable=False
    )
    used_at: Mapped[datetime | None]
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class AdminUser(PKMixin, TimestampMixin, Base):
    """Separate realm (admin Clerk app) — NOT tenant-scoped."""

    __tablename__ = "admin_users"
    __table_args__ = (CheckConstraint(f"role IN {ADMIN_ROLES!r}", name="role_enum"),)

    clerk_user_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String, nullable=False, server_default="operator")
