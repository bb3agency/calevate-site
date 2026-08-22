"""Tenancy & identity (DATA-MODEL §2).

organizations is the tenant root: its RLS policy matches on `id`, every other
tenant table matches on `tenant_id`. Enums are TEXT + CHECK (mirroring the Pydantic
enums, DATA-MODEL §10) — cheaper to evolve than native PG enums.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from calevate_shared.engine import AZURE_OPENAI_MODELS
from sqlalchemy import CheckConstraint, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.rbac import ADMIN_ROLES as RBAC_ADMIN_ROLES
from apps.api.db.base import Base, PKMixin, TimestampMixin

ORG_STATUSES = ("prospect", "onboarding", "active", "suspended", "churned")
# D-34 runs both motions on one product; D-39 puts the column in M1 because tenancy is
# not retrofittable. `managed` is the client-#1 path; `self_serve` unlocks the M2 UI.
PLAN_TIERS = ("managed", "self_serve", "trial")
MEMBER_ROLES = ("owner", "staff")
#: RE-EXPORTED, NOT RESTATED. `core/rbac.ROLE_PERMISSIONS` is keyed by these two names and
#: `authn/bootstrap` validates against them; a second literal here is how a role table and
#: the CHECK constraint built from it come to disagree about what a role is called.
ADMIN_ROLES = RBAC_ADMIN_ROLES


class Organization(PKMixin, TimestampMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (
        CheckConstraint("slug ~ '^[a-z0-9-]{3,40}$'", name="slug_shape"),
        CheckConstraint(f"status IN {ORG_STATUSES!r}".replace("(", "(", 1), name="status_enum"),
        CheckConstraint(f"plan_tier IN {PLAN_TIERS!r}", name="plan_tier_enum"),
        # The account's language-model choice, admitted only from the allow-list.
        # DERIVED from `AZURE_OPENAI_MODELS`, never retyped (D-104): the frozenset is the
        # source, `sorted` makes the rendered SQL byte-stable across interpreter runs, and
        # a model added to the Literal therefore changes this constraint in the same edit
        # or it changes neither. NULL is admitted EXPLICITLY because it is the "inherit
        # the platform's model" sentinel, not by the accident that a NULL-returning CHECK
        # passes. Migration b7d2f10c93ae.
        CheckConstraint(
            "default_llm_model IS NULL OR default_llm_model IN "
            f"{tuple(sorted(AZURE_OPENAI_MODELS))!r}",
            name="default_llm_model_allowed",
        ),
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
    # WHICH LANGUAGE MODEL THIS ACCOUNT'S AGENTS RUN when the agent itself names none —
    # the middle rung of `agent -> organization -> platform`
    # (`agents/llm_models.resolve_llm_model`, migration b7d2f10c93ae).
    #
    # NULL IS THE ANSWER "INHERIT", never "no model": an account that has never chosen
    # runs `Settings.azure_openai_model`, and clearing this column is how a client goes
    # back to it. A `server_default` naming a model would have made every existing account
    # claim a choice nobody made, and would then have to be kept in step with a live
    # console switch — the D-105 defect with a clock attached.
    default_llm_model: Mapped[str | None] = mapped_column(Text)
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
    #: WHEN THIS OPERATOR ACCOUNT STOPPED BEING ONE. NULL = live; set = revoked, and every
    #: identity read in the admin realm carries `AND deactivated_at IS NULL`
    #: (`authn/subjects._ADMIN_SELECT`, `core/auth._load_admin_principal`).
    #:
    #: THIS COLUMN REVERSES A STATED POSITION AND THE REVERSAL IS THE POINT.
    #: `authn/subjects.py` argued that the admin realm's liveness rule is ROW PRESENCE and
    #: that adding a `deactivated_at` would be "a second way to express the same fact".
    #: That argument rested on a premise the schema does not support: EIGHT tables
    #: reference `admin_users` with `ON DELETE RESTRICT` — `first_campaign_reviews`,
    #: `kyc_records`, `platform_secrets`, `platform_settings`, `preference_scrub_runs`,
    #: `qa_call_samples`, `tenant_feature_flags`, `whatsapp_alert_optin_ledger` — so the
    #: DELETE that was supposed to be the removal mechanism raises a foreign-key violation
    #: for any operator who has ever approved a campaign, verified a KYC record, installed
    #: a credential or reviewed a call. In other words it worked only for operators nobody
    #: needed to remove. Those references are evidence about who decided what, and they
    #: are the reason the row must survive its account.
    #:
    #: So there is still ONE way to say "this person may not sign in", and this is it; the
    #: uniformity `subjects.py` cares about is preserved where it was actually promised —
    #: in the RETURN TYPE, where `load_subject` answers `None` for absent, deleted and
    #: deactivated alike and no caller can tell which. It is the same shape `users` has
    #: carried since 769a9152cb06, which is what makes the two realms readable side by side.
    deactivated_at: Mapped[datetime | None]
