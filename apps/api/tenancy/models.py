"""Tenancy & identity (DATA-MODEL §2).

organizations is the tenant root: its RLS policy matches on `id`, every other
tenant table matches on `tenant_id`. Enums are TEXT + CHECK (mirroring the Pydantic
enums, DATA-MODEL §10) — cheaper to evolve than native PG enums.
"""

from datetime import datetime
from typing import Any
from uuid import UUID

from calevate_shared.engine import LLM_MODEL_NAMES
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    false,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.core.rbac import ADMIN_ROLES as RBAC_ADMIN_ROLES
from apps.api.db.base import Base, PKMixin, TimestampMixin

ORG_STATUSES = ("prospect", "onboarding", "active", "suspended", "churned")
# D-34 runs both motions on one product; D-39 puts the column in M1 because tenancy is
# not retrofittable. `self_serve` unlocks the M2 UI.
#
# ⚠ **D-521 ADDED `prepaid` AND MADE IT THE DEFAULT (`DEFAULT_PLAN_TIER` below), WHICH
# SUPERSEDES D-34 ON WHICH MOTION A NEW ACCOUNT IS BORN INTO.** The four names split on
# TWO different questions, and reading them as one ladder is the mistake this comment
# exists to stop:
#
#   * **does this account pay from a wallet?** — `billing/rates.PREPAID_TIERS`, which is
#     `prepaid`, `self_serve` and `trial`. `managed` is the ONLY invoiced tier and it is
#     now something an operator sets deliberately for a client genuinely billed on a
#     retainer (`POST /v1/admin/tenants/{id}/plan-tier`), not what a client gets by
#     default;
#   * **did a stranger sign this account up unattended?** — `compliance/service
#     .SELF_SERVE_TIERS`, which is `self_serve` and `trial` and does NOT include
#     `prepaid`. It gates subscriber KYC (D-47) and the first-campaign hold (D-51), both
#     of which exist because on that motion the applicant is a stranger. An operator who
#     creates a client has met them, so `prepaid` must not pick those gates up.
#
# The two questions had identical answers until D-521, which is why one constant used to
# serve both. `tests/plan_tier_split_test.py` pins the containment that survives it.
#
# D-707 (10 Oct 2026) puts every client on ONE pricing model, prepaid credits, so the
# invoiced `managed` motion is retired: migration `e5a1d706c3f2` moved every `managed`
# account to `prepaid` and nothing writes it any more. It stays in this tuple, and so in
# the CHECK, for ONE release (hard rule 8's two-step): a process not yet redeployed can
# still read it, and the next release narrows the CHECK and deletes the readers.
PLAN_TIERS = ("managed", "prepaid", "self_serve", "trial")

#: The tiers no writer may produce any more (D-707). `admin.service.create_organization`
#: refuses them and `tests/platform_fee_test.py` pins that nothing else writes one.
RETIRED_PLAN_TIERS = ("managed",)

#: What a NEW organisation is born on when no caller names a tier (D-521). Lives here,
#: beside the enum it must be a member of, rather than in `admin/service.py` where it
#: began: `billing.service.plan_tier_of` needs the same value for the row it cannot see,
#: and an admin module is not something the money layer may import. `admin.service`
#: re-exports it, so the name every caller already uses still resolves.
DEFAULT_PLAN_TIER = "prepaid"
#: How an account first paid (D-697): a gateway top-up, a bank transfer an operator credited
#: to the wallet, or "it existed before the rule" (the backfill). A goodwill grant is not one.
FIRST_PAID_VIA = ("wallet_topup", "manual_topup", "before_d697")
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
        # How an account first paid (D-697, migration a2f7c4e9d61b), and the two together.
        CheckConstraint(
            f"first_paid_via IS NULL OR first_paid_via IN {FIRST_PAID_VIA!r}",
            name="first_paid_via_enum",
        ),
        CheckConstraint(
            "(first_paid_at IS NULL) = (first_paid_via IS NULL)", name="first_paid_together"
        ),
        # A waiver is a decision with a reason (D-707): the instant and the reason are
        # set and cleared together, and the reason is never blank.
        CheckConstraint(
            "(platform_fee_waived_at IS NULL) = (platform_fee_waiver_reason IS NULL) "
            "AND (platform_fee_waiver_reason IS NULL "
            "OR length(btrim(platform_fee_waiver_reason)) > 0)",
            name="platform_fee_waiver_together",
        ),
        # The account's language-model choice, admitted only from the catalogue.
        # DERIVED from `LLM_MODEL_NAMES`, never retyped (D-104): the frozenset is the
        # source, `sorted` makes the rendered SQL byte-stable across interpreter runs, and
        # a model added to any of the three per-leg Literals therefore changes this
        # constraint in the same edit or it changes neither. NULL is admitted EXPLICITLY
        # because it is the "inherit the platform's model" sentinel, not by the accident
        # that a NULL-returning CHECK passes. Migrations b7d2f10c93ae, then d3a7c81f45be
        # which widened it from the Azure-only list to the whole catalogue — see that
        # revision for why the floor is the catalogue and the policy is in code.
        CheckConstraint(
            f"default_llm_model IS NULL OR default_llm_model IN {tuple(sorted(LLM_MODEL_NAMES))!r}",
            name="default_llm_model_allowed",
        ),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    # Immutability enforced by trigger in the migration (slug is in client URLs).
    slug: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="prospect")
    vertical_template: Mapped[str | None] = mapped_column(Text)
    #: WHEN THIS BUSINESS ATTESTED THAT ITS CALLS ARE SAFE TO REMEMBER, and who clicked
    #: (D-513). NULL means they have not, which is every tenant until they do, and
    #: `agents.publishing.set_caller_memory` refuses to switch cross-call memory on
    #: without it.
    #:
    #: ON `organizations` AND NOT ON `agents` because the attested fact is about the
    #: BUSINESS — "these calls do not take health, financial or other sensitive personal
    #: data, and our callers are told we keep notes" — not about one agent. A client with
    #: four agents answers once; four columns would ask four times and let three answers
    #: rot. It is the per-tenant instrument `compliance.caller_memory.
    #: SPDI_REFUSED_VERTICALS` describes itself as a weak proxy for; the proxy stays, as
    #: the belt, because an attestation is a claim and a vertical is a record.
    caller_memory_attested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    caller_memory_attested_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Which motion this org belongs to (D-34/D-39/D-521). NOT a feature flag: it decides
    # whether credits gate dispatch and whether the self-serve screens render. The
    # server default moved `managed` -> `prepaid` with D-521 (migration `a8d3f61c04e7`);
    # it is spelled from the constant so the column and the wizard cannot disagree.
    plan_tier: Mapped[str] = mapped_column(String, nullable=False, server_default=DEFAULT_PLAN_TIER)
    billing_email: Mapped[str | None] = mapped_column(Text)
    # The admin wizard's old intake answer sheet (migration c1f3a7d92b46). NOTHING WRITES
    # OR READS IT since D-695: migration f4c8b2e6a1d9 copied it into `business_profiles`,
    # which is the one home of the business's facts. Kept for one release (hard rule 8's
    # two-step) and as the downgrade's restore target. Staff names and escalation numbers:
    # never log it (hard rule 6).
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
    # MAY THIS ACCOUNT'S `staff` MEMBERS CURATE KNOWLEDGE — the owner-controlled half of
    # the founder's decision ("give the staff perms allowing option to owner"). FALSE for
    # every account until that account's own owner turns it on, which is why the migration
    # needs no backfill and changes nothing in any live account.
    #
    # IT GRANTS EXACTLY ONE CAPABILITY AND IS READ IN EXACTLY ONE PLACE:
    # `kb/curation.py::may_curate_knowledge`, behind `requires_kb_curation()`. It is NOT a
    # role, NOT a permission and NOT "staff are owners now" — `ROLE_PERMISSIONS["staff"]`
    # is untouched by it, so every other `requires(...)` in the tree answers for a staff
    # member exactly as it did before. Grepping that one dependency name shows the whole
    # reach of this column, which is the property a reader needs and a boolean on a role
    # table could not have given them.
    #
    # Written only by `PUT /v1/kb/staff-curation` (`org:manage`, so owner-only), audited
    # as `organization.staff_kb_curation_set`. Flipping a permission switch is itself a
    # mutation, so D-22 refuses an impersonating admin there like any other.
    staff_may_curate_knowledge: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    #: THE ACCOUNT'S OUTBOUND IS SERVICE/TRANSACTIONAL, AND THE GATE ENFORCES IT (D-624).
    #:
    #: ⚠ **THIS COLUMN EXISTS BECAUSE A BACKSTOP WAS REMOVED, AND IT IS THE ONLY THING THAT
    #: REPLACES IT.** `compliance/service.py`'s consent check is deliberately permissive —
    #: *"ABSENCE IS NOT A REFUSAL, and that asymmetry is the whole design"* — because most
    #: dialable leads legitimately have no `consent_ledger` row (a number typed in by staff,
    #: a CSV import, a caller who rang US), and refusing all of them would be met as an
    #: outage rather than a rule. That was the right default while a client's DLT PE/TM
    #: registration stood behind it: the registration, not the ledger, was what separated a
    #: relationship call from a cold list.
    #:
    #: An account whose outbound is sold and classified as SERVICE/TRANSACTIONAL has no such
    #: registration behind it. Its whole position is that it calls the client's own existing,
    #: consenting customers about those customers' own bookings and orders — a classification
    #: TRAI's promotional/transactional distinction turns on. Under the permissive default
    #: that position is an INTENTION: nothing stops a client with a quiet month uploading a
    #: prospect list, and the first anyone would know is a complaint, under a rule
    #: (TCCCPR Reg 25(6)) that disconnects "all telecom resources of the sender" and
    #: blacklists for up to two years.
    #:
    #: So on this account absence of an affirmative, unexpired `granted` consent row REFUSES
    #: the dial. It does not merely warn: a warning on a campaign nobody reads is the
    #: intention again with extra steps.
    #:
    #: **DEFAULT FALSE, AND THAT IS NOT TIMIDITY.** Flipping the global default would change
    #: the answer for every existing account at once — the exact "outage rather than a rule"
    #: the permissive comment warns about — and the accounts that need this are the ones
    #: SOLD on the service/transactional footing, which is a commercial fact about an
    #: account and not a property of the software. `docs/evidence/
    #: dlt-roles-and-operating-model-2026-09-18.md` addendum 2 carries the reasoning.
    outbound_requires_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=false()
    )
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    deleted_at: Mapped[datetime | None]
    #: THE GRACE WINDOW BETWEEN "CLOSED" AND "ERASED" (D-538, migration e6c1a49d2f70).
    #:
    #: The founder's delete button is *close now, erase after a grace period, undo during
    #: it*, so these four columns are the deadline that sits between `status = 'churned'`
    #: (the relationship ended, nothing is destroyed) and `deleted_at` (the tenant erasure
    #: ran and the caller data is gone). `tenancy/closure.py` is the only writer.
    #:
    #: The nesting is a database fact, not a convention: three CHECKs in that migration
    #: hold `deleted_at` => no `erase_after`, `erase_after` => `closed_at`, and
    #: `closed_at` => `churned`. Reading any one of the three columns therefore answers a
    #: strictly narrower question than the one before it.
    #:
    #: `erase_after` NULL on a closed account is a real and intended state — it is what an
    #: UNDO leaves behind, and it is also how an account closes with its records kept.
    closed_at: Mapped[datetime | None]
    erase_after: Mapped[datetime | None]
    closure_reason: Mapped[str | None] = mapped_column(Text)
    closed_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    #: WHEN THIS ACCOUNT FIRST PAID, and how (D-697, migration a2f7c4e9d61b). NULL until
    #: then. Written once, by `billing/first_payment.record_first_payment` only, in the
    #: transaction that credits the payment. It ends a free trial, unlocks KYC, numbers and
    #: live calling, and is what owes the account its own voice workspace
    #: (`first_payment.PAID_TENANT_SQL`). `before_d697` marks an account that existed
    #: before the rule and keeps what it had.
    first_paid_at: Mapped[datetime | None]
    first_paid_via: Mapped[str | None] = mapped_column(Text)
    #: THE MONTHLY PLATFORM FEE WAIVER (D-707, migration e5a1d706c3f2). An operator may
    #: excuse one client from the platform-wide fee, with a reason; the three columns are
    #: set and cleared together (a CHECK holds it) and every change writes an audit row
    #: (`billing/platform_fee.set_waiver`). NULL `platform_fee_waived_at` means the client
    #: pays the fee whenever the switch is on.
    platform_fee_waived_at: Mapped[datetime | None]
    platform_fee_waiver_reason: Mapped[str | None] = mapped_column(Text)
    platform_fee_waived_by: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    #: When D-707's migration moved this account off the invoiced (`managed`) motion onto
    #: prepaid credits. NULL for every account that was never invoiced. Invoices for the
    #: months before it are still rendered from the retainer terms in effect then; the
    #: migration's downgrade reads it to put exactly these accounts back.
    moved_to_credits_at: Mapped[datetime | None]


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
    #: WHEN THE LINK WAS LAST PUT IN SOMEBODY'S INBOX, and how many times (D-538).
    #:
    #: A resend ROTATES this row's token rather than minting a second invitation, so these
    #: two count sends of one key rather than keys. They are the rate limiter's clock and
    #: the console's "last sent 4 minutes ago, 3 times" line, and they are one fact on
    #: purpose: a screen reading a different value from the limiter tells an operator to
    #: wait when they need not, or worse, the reverse.
    last_sent_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    send_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))
    #: The invitee's name and mobile as the operator typed them on the new-client form
    #: (D-695). Used once, when the invitation is accepted, to fill the new `users` row;
    #: a name the invitee types at acceptance wins. PII: never logged (hard rule 6).
    invitee_name: Mapped[str | None] = mapped_column(Text)
    invitee_phone: Mapped[str | None] = mapped_column(Text)


#: The setup wizard's steps, in the order the wizard asks them (D-695). One topic each.
PROFILE_STEPS = (
    "hours",
    "branches",
    "services",
    "faqs",
    "staff",
    "booking",
    "contacts",
    "languages",
)


class BusinessProfile(PKMixin, TimestampMixin, Base):
    """THE business's own facts, one row per client (D-695, migration f4c8b2e6a1d9).

    The single source of what every agent of this client says about the business: the
    [T0 FACTS] block of every agent is compiled from it (`agents/t0.py`), the after-hours
    flag and the handover rota are judged against its hours, and each agent's extra
    languages are its languages. The client fills it in a skippable setup wizard and edits
    it later under Settings; an operator edits it through view-as.

    `hours` maps a weekday to `{"opens", "closes"}` or to null. Null is CLOSED; an absent
    day is NOT ANSWERED YET. The agent says different things about the two.

    Escalation contacts are not here: they are `business_contacts`, rows an agent's
    handover list points at. Phone numbers never enter the prompt.
    """

    __tablename__ = "business_profiles"
    __table_args__ = (
        UniqueConstraint("tenant_id", name="uq_business_profiles_tenant"),
        CheckConstraint("jsonb_typeof(hours) = 'object'", name="ck_business_profiles_hours"),
        CheckConstraint(
            "jsonb_typeof(branches) = 'array' AND jsonb_typeof(services) = 'array' "
            "AND jsonb_typeof(faqs) = 'array' AND jsonb_typeof(staff) = 'array'",
            name="ck_business_profiles_lists",
        ),
        CheckConstraint(
            "jsonb_typeof(setup_steps) = 'object'", name="ck_business_profiles_setup_steps"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    hours: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    branches: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    #: Prices are digit STRINGS inside each item (hard rule 7): what the agent reads out is
    #: exactly what the client typed.
    services: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    faqs: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    staff: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    booking_rules: Mapped[str | None] = mapped_column(Text)
    #: Every language the business serves, primaries included. An agent speaks these
    #: besides its own primary language.
    languages: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, server_default=text("'{}'::text[]")
    )
    #: Setup wizard progress: `{step: "done" | "skipped"}`. A step that is absent has not
    #: been reached. Server-side so it follows the client across devices.
    setup_steps: Mapped[dict[str, str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    setup_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    setup_dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    #: What the D-695 data migration could not merge when a client's agents disagreed —
    #: the value kept and the values set aside, per field. Written by that migration only,
    #: shown to operators, never to the client.
    merge_notes: Mapped[list[Any] | None] = mapped_column(JSONB)
    updated_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


class BusinessContact(PKMixin, TimestampMixin, Base):
    """One person who can take a call the agents hand over (D-695).

    The client's roster, kept once for the whole business. Each agent's handover list
    (`agent_handoff_members`) is an ordered SELECTION from these rows, so an agent can put
    callers through to a subset. Deleting a contact removes it from every agent's list.
    """

    __tablename__ = "business_contacts"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_business_contacts_position"),
        CheckConstraint("length(btrim(label)) > 0", name="ck_business_contacts_label_nonempty"),
        # Doubled with the Pydantic pattern because this number is dialled.
        CheckConstraint(
            r"phone_e164 ~ '^\+[1-9][0-9]{7,18}$'", name="ck_business_contacts_phone_e164"
        ),
        # DEFERRED so one save can swap two contacts' numbers.
        UniqueConstraint(
            "tenant_id",
            "phone_e164",
            name="uq_business_contacts_phone",
            deferrable=True,
            initially="DEFERRED",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    #: PII (hard rule 6): a member of the client's staff, often on a personal mobile.
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    #: When they can be reached, in the client's words. Never parsed into a schedule.
    note: Mapped[str | None] = mapped_column(Text)


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


class TenantEngineWorkspace(PKMixin, TimestampMixin, Base):
    """The tenant's own ThinnestAI customer workspace (D-693; migration d93b6f2a4c18).

    ONE ROW PER TENANT. `external_ref` is OUR reference, sent as the customer's `externalId`,
    so provisioning finds a workspace it already made before creating one
    (`api-reference/customers/list-customers.md:20-30`). `workspace_id` is the vendor's `org_`
    id once it exists; `tenancy/engine_workspace.workspace_for_tenant` answers it only while
    `status = 'active'`, and nothing ever falls back to our developer workspace for a client
    resource. The `business_*` columns are the workspace's business-details application as
    last read (`phone-numbers/get-business-details.md:412-470`); the vendor is the truth.
    """

    __tablename__ = "tenant_engine_workspaces"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'active', 'plan_limit', 'failed', 'offboarding', 'deleted')",
            name="status_enum",
        ),
        CheckConstraint(
            "business_status IS NULL OR business_status IN ('none', 'draft', 'submitted', "
            "'accepted', 'rejected', 'suspended', 'expired', 'unknown')",
            name="business_status_enum",
        ),
        CheckConstraint(
            "workspace_id IS NULL OR workspace_id ~ '^org_[^@[:space:]]{1,120}$'",
            name="workspace_id_shape",
        ),
        CheckConstraint(
            "status <> 'active' OR workspace_id IS NOT NULL", name="active_has_workspace"
        ),
        CheckConstraint("external_ref ~ '^[A-Za-z0-9._:-]{1,128}$'", name="external_ref_shape"),
        CheckConstraint(
            "last_error_code IS NULL OR char_length(last_error_code) <= 64",
            name="error_code_bounded",
        ),
        CheckConstraint(
            "business_review_note IS NULL OR char_length(business_review_note) <= 2000",
            name="review_note_bounded",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, unique=True
    )
    engine: Mapped[str] = mapped_column(Text, nullable=False)
    external_ref: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    workspace_id: Mapped[str | None] = mapped_column(Text, nullable=True, unique=True)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'pending'"))
    last_error_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    provisioned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    business_status: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_can_rent: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=false())
    business_review_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    business_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    business_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    business_document_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
