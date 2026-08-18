"""Tenancy & identity (DATA-MODEL §2).

organizations is the tenant root: its RLS policy matches on `id`, every other
tenant table matches on `tenant_id`. Enums are TEXT + CHECK (mirroring the Pydantic
enums, DATA-MODEL §10) — cheaper to evolve than native PG enums.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

ORG_STATUSES = ("prospect", "onboarding", "active", "suspended", "churned")
# D-34 runs both motions on one product; D-39 puts the column in M1 because tenancy is
# not retrofittable. `managed` is the client-#1 path; `self_serve` unlocks the M2 UI.
PLAN_TIERS = ("managed", "self_serve", "trial")
MEMBER_ROLES = ("owner", "staff")
ADMIN_ROLES = ("superadmin", "operator")


class Organization(PKMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9-]{3,40}$'", name="slug_shape"),
        CheckConstraint(f"status IN {ORG_STATUSES!r}".replace("(", "(", 1), name="status_enum"),
        CheckConstraint(f"plan_tier IN {PLAN_TIERS!r}", name="plan_tier_enum"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Immutability enforced by trigger in the migration (slug is in client URLs).
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="prospect")
    vertical_template: Mapped[str | None] = mapped_column(Text)
    # Which motion this org belongs to (D-34/D-39). NOT a feature flag: it decides
    # whether credits gate dispatch and whether the self-serve screens render.
    plan_tier: Mapped[str] = mapped_column(String, nullable=False, server_default="managed")
    billing_email: Mapped[str | None] = mapped_column(Text)
    # The wizard's intake answer sheet (FLOWS §1 step 3), raw and resumable: the fields
    # an operator typed, not the [T0 FACTS] block compiled out of them. Lives here
    # because these are the BUSINESS's own facts — hours, branches, prices, staff — and
    # `organizations` is the row that is the business (DATA-MODEL §2); the per-agent
    # halves stay on `agents` (§3). Envelope shape and the reasons for the column rather
    # than a `client_intake` table: migration c1f3a7d92b46. Validated at the API
    # boundary by `admin.intake.IntakeFacts` (§10), envelope pinned by a CHECK.
    # Contains staff names and escalation numbers: never log it (hard rule 6).
    intake: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    deleted_at: Mapped[datetime | None]


class ReservedSlug(Base):
    __tablename__ = "reserved_slugs"

    slug: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class User(PKMixin, TimestampMixin, Base):
    """Global identity (crosses tenants via memberships) — NOT tenant-scoped."""

    __tablename__ = "users"

    # NOTHING WRITES THIS ANY MORE (D-177), and nothing reads it. Step 1 of hard rule 8's
    # two-step deprecation: the writers went with Clerk, the column stays one more release
    # so the rows Clerk created are still identifiable if a question about them arrives.
    # Recorded in `scripts/check_wiring.UNWIRED_BASELINE`, which is where this repo tracks
    # a column with no toucher and what closes it — step 2 is the DROP migration.
    clerk_user_id: Mapped[str | None] = mapped_column(Text, unique=True)
    email: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    phone: Mapped[str | None] = mapped_column(Text)  # E.164
    # Re-checked by the auth guard on EVERY request (BACKEND-PATTERNS §7): a cached
    # session must not outlive a deactivation. It is also the client realm's whole
    # liveness rule for `authn/subjects.py`, so signing in and staying signed in agree
    # about what "active" means.
    deactivated_at: Mapped[datetime | None]
    # When this mailbox was proved (D-170). Set by the `email_verify` OTP round trip, or
    # directly on invitation redemption — possession of a token emailed to the address IS
    # the proof, which is why redemption needs no address comparison at all.
    email_verified_at: Mapped[datetime | None]


class Membership(PKMixin, TimestampMixin, Base):
    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id"),
        CheckConstraint(f"role IN {MEMBER_ROLES!r}", name="role_enum"),
    )

    # No `index=True` on `tenant_id`: UNIQUE(tenant_id, user_id) leads with it. This
    # table's RLS policy is the asymmetric `tenant_id = ... OR user_id = ...`, so both
    # arms of the BitmapOr still need an index and both still have one — the tenant arm
    # from the unique constraint, the user arm from `ix_memberships_user_id` below,
    # which is NOT redundant and must stay (b9e5d2c74a18).
    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
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
    """The operator allowlist. Separate realm, separate session — NOT tenant-scoped."""

    __tablename__ = "admin_users"
    __table_args__ = (CheckConstraint(f"role IN {ADMIN_ROLES!r}", name="role_enum"),)

    # Unwritten and unread since D-177, exactly as `User.clerk_user_id` — same two-step,
    # same baseline entry, same DROP migration closes both.
    clerk_user_id: Mapped[str | None] = mapped_column(Text, unique=True)
    # The address an operator signs in with, and the address the bootstrap link is mailed
    # to (D-171). Nullable because Clerk-era rows have none. UNIQUE on
    # `lower(email)` via an expression index in the migration — SQLAlchemy cannot express
    # that as a column constraint, which is why it is `op.execute`'d there rather than
    # declared here; `check_metadata_columns` compares COLUMNS, and the index is asserted
    # by `tests/authn_bootstrap_test.py` reaching it through `resolve_by_email`.
    email: Mapped[str | None] = mapped_column(Text)
    name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(String, nullable=False, server_default="operator")
