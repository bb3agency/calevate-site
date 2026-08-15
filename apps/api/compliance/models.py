"""Compliance & audit (DATA-MODEL §9). consent_ledger and audit_log are INSERT-only
(immutability triggers in the migration). audit_log additionally carries the tamper-
evident hash chain (BACKEND-PATTERNS §7): prev_hash/entry_hash filled by the writer
under a Redis lock; the chain head lives in Redis."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

CONSENT_PURPOSES = ("recording", "callback", "marketing", "messaging")
# The purpose that governs business-initiated MESSAGING (migration c2f7a91b4e63).
# Named once, here, because three layers switch on the same string — the CHECK
# constraint, `compliance/consent.py`'s reads and writes, and the WhatsApp campaign
# escalation in `workers/whatsapp.py`. It was previously a private constant in the
# worker; a literal that must match a database constraint belongs beside the column.
MESSAGING_PURPOSE = "messaging"
# HOW a consent statement was obtained. Never "assumed", never "implied", never
# inferred from a campaign list — see the migration docstring for what each member must
# be able to evidence. `staff_recorded_request` is CHECK-barred from `granted`: a client
# employee may record that somebody asked to stop, never that somebody agreed to start.
CONSENT_SOURCES = (
    "inbound_call_verbal",
    "web_form_optin",
    "offline_form_optin",
    "whatsapp_inbound_message",
    "staff_recorded_request",
)
WITHDRAWAL_ONLY_CONSENT_SOURCES = ("staff_recorded_request",)
# A one-member tuple's repr ends in a comma, which is a syntax error inside SQL's
# `IN (...)`. Rendered explicitly so the mirrored CHECK below stays valid SQL however
# many members this grows to.
_WITHDRAWAL_ONLY_SQL = ", ".join(repr(source) for source in WITHDRAWAL_ONLY_CONSENT_SOURCES)
# DLT Principal Entity registration, as the registrar's own lifecycle (SEC-COMP §1/§3).
# `not_started` exists so a row can say "we have not begun" without being absent —
# absence and "pending" are different facts to an operator chasing an onboarding step.
PE_REGISTRATION_STATUSES = ("not_started", "submitted", "active", "suspended", "rejected")
# The PE→TM authorisation: the client (PE) naming Calevate (TM) as permitted to place
# calls on their behalf. Separate from the PE's own status because it fails separately:
# a perfectly registered entity that never linked us is a different to-do item.
TM_LINK_STATUSES = ("not_linked", "pending", "active", "revoked")
# Subscriber KYC for a telecom connection (migration a3f6b1e02d95). The lifecycle of
# OUR verification, not a registrar's: `submitted` is the client having given us
# something, `in_review` an operator working it, `verified` the only state that opens
# number provisioning. `expired` exists because a verification goes stale — an entity
# is struck off, a GST registration is cancelled — and "was true in 2026" is not the
# question the gate asks.
KYC_STATUSES = ("not_started", "submitted", "in_review", "verified", "rejected", "expired")
# The one state that satisfies the gate. Named so the gate, the route and the CHECK
# cannot drift into three different spellings of the same idea.
KYC_VERIFIED = "verified"
# How the subscribing business is constituted. Drives WHICH document we should be
# looking at (a proprietorship has no CIN), and it is what the licensee's CAF asks.
KYC_ENTITY_TYPES = (
    "sole_proprietorship",
    "partnership",
    "llp",
    "private_limited",
    "public_limited",
    "trust_or_society",
    "huf",
)
# ENTITY registries only — see the migration. Every member identifies a BUSINESS in a
# public register; none identifies a natural person, which is what keeps `document_ref`
# out of DPDP scope and out of hard rule 6's reach. Aadhaar and personal PAN are absent
# on purpose and there is a CHECK constraint standing behind that absence.
KYC_DOCUMENT_KINDS = ("cin", "llpin", "gstin", "udyam", "shop_establishment", "trade_licence")
# The first-campaign review (R-11's last mitigation; migration c4d9e18a72b6). Exactly
# the two things a human can decide — "not reviewed yet" is the ABSENCE of a row, not a
# third status, because a stored `pending` could disagree with the absence and every
# gate would have to treat the two identically anyway.
FIRST_CAMPAIGN_REVIEW_STATUSES = ("approved", "rejected")
# The one status that releases an account. Named so the gate, the route and the CHECK
# cannot drift into three spellings of the same idea (`KYC_VERIFIED` does the same job).
FIRST_CAMPAIGN_REVIEW_APPROVED = "approved"
# WHO decided. `migration_backfill` exists so a row with no operator is self-describing
# rather than an anonymous release with the name left off — see the migration.
FIRST_CAMPAIGN_DECISION_SOURCES = ("operator", "migration_backfill")
CONSENT_STATUSES = ("granted", "declined", "withdrawn")
# The CLIENT-side WhatsApp opt-in (migration e6b2d94f31a7) — our own customer's owner
# agreeing to receive hot-lead alerts from the Calevate WABA. Deliberately a separate
# vocabulary from `CONSENT_STATUSES` above, which describes a CONSUMER's statement about
# a client's messages: there is no `declined` here because nobody asks a client on our
# behalf and records the no — an owner who has not opted in simply has no row, and
# absence is the default of the world.
ALERT_OPTIN_STATUSES = ("granted", "withdrawn")
# HOW the agreement was obtained. The asymmetry is argued in the migration: a self-serve
# row must have been recorded BY its own subject, an operator's row must name the
# operator and the document. Both are grant-capable; neither may be unevidenced.
ALERT_OPTIN_CHANNELS = ("self_serve_console", "operator_recorded")
# The one channel a client owner can reach themselves. Named so the route, the CHECK and
# the service cannot drift into three spellings of the same idea.
ALERT_OPTIN_SELF_SERVE = "self_serve_console"
ALERT_OPTIN_OPERATOR = "operator_recorded"
DATA_CATEGORIES = ("recording", "transcript", "lead", "consent_log")
RETENTION_ACTIONS = ("delete", "anonymize")
ACTOR_TYPES = ("admin", "user", "system")


class ConsentLedgerEntry(PKMixin, Base):
    """What a person agreed to, and how we know. INSERT-only (hard rule 4).

    A withdrawal is a NEW row with `status='withdrawn'`, never an UPDATE of the grant;
    the current state of a (tenant, phone, purpose) is the LATEST row for it. The
    `consent_ledger_append_only` trigger enforces that at the database, not here.

    The constraints below mirror migration `c2f7a91b4e63` — the CHECKs are the source of
    truth and this tuple must not drift from them (DATA-MODEL §10).
    """

    __tablename__ = "consent_ledger"
    __table_args__ = (
        CheckConstraint(f"purpose IN {CONSENT_PURPOSES!r}", name="purpose_enum"),
        CheckConstraint(f"status IN {CONSENT_STATUSES!r}", name="status_enum"),
        CheckConstraint(
            f"consent_source IS NULL OR consent_source IN {CONSENT_SOURCES!r}",
            name="source_enum",
        ),
        # "Consent is captured with a SOURCE, never assumed", as a constraint rather
        # than a convention: a messaging row that cannot say how it was obtained is not
        # written at all.
        CheckConstraint(
            f"purpose <> {MESSAGING_PURPOSE!r} OR consent_source IS NOT NULL",
            name="messaging_names_its_source",
        ),
        # A grant is evidenced, is never asserted by staff on the subject's behalf, and
        # if it was spoken it names the call it was spoken on. Withdrawals are exempt:
        # consent must be evidenced, a refusal must never be obstructed.
        CheckConstraint(
            "consent_source IS NULL OR status <> 'granted' OR ("
            "evidence IS NOT NULL "
            f"AND consent_source NOT IN ({_WITHDRAWAL_ONLY_SQL}) "
            "AND (consent_source <> 'inbound_call_verbal' OR call_id IS NOT NULL))",
            name="granted_consent_carries_evidence",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="RESTRICT"))
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    purpose: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    # Nullable because every row written before c2f7a91b4e63 has no answer, and
    # inventing one would be a fabricated compliance artefact. The CHECK above makes it
    # mandatory exactly where it is knowable: `purpose = 'messaging'`.
    consent_source: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)  # e.g. transcript span
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class WhatsAppAlertOptIn(PKMixin, Base):
    """A named person at a client agreed to receive WhatsApp alerts from OUR WABA.

    The client-side twin of `ConsentLedgerEntry`'s `messaging` purpose, and deliberately
    a different table: that ledger holds a CONSUMER's statement about being messaged by
    a client, keyed to the number a client's caller rang from. This holds our own
    contracting counterparty's statement about being messaged by US. Different party,
    different fiduciary, different regime — Meta's opt-in policy plus DPDP, with no
    TRAI/DLT leg at all, because a service notification to a paying customer about their
    own account is not commercial traffic to a subscriber.

    INSERT-only (hard rule 4). A withdrawal is a NEW row with `status='withdrawn'`; the
    current state of a (tenant, user, phone) is the LATEST row for it, and the
    `whatsapp_alert_optin_ledger_append_only` trigger enforces that at the database.
    The grant it supersedes survives, because "were we allowed to send that alert in
    March?" is a question asked in April.

    **There is no expiry column and that is a decision, not an omission** — the migration
    argues it. The consumer ledger's 365-day window stands in for a relationship we
    cannot observe; here the relationship is observable on every send, so the expiry is
    structural: the row names the `user_id` (so an owner handover does not inherit it)
    and the `phone_e164` it was given for (so a changed number fails closed), and
    `resolve_destination` already excludes deactivated users and non-owners. A clock
    would switch a client's hot-lead alerts off on a day nobody is watching, which is
    the failure the feature exists to prevent.

    The constraints below mirror migration `e6b2d94f31a7` — the CHECKs are the source of
    truth and this tuple must not drift from them (DATA-MODEL §10).
    """

    __tablename__ = "whatsapp_alert_optin_ledger"
    __table_args__ = (
        CheckConstraint(f"status IN {ALERT_OPTIN_STATUSES!r}", name="status_enum"),
        CheckConstraint(f"channel IN {ALERT_OPTIN_CHANNELS!r}", name="channel_enum"),
        # The three things Meta expects a business to produce when a number is
        # challenged, as a constraint rather than a convention: the wording the person
        # agreed to, and — per channel — who stands behind the record. A self-serve
        # grant nobody's own subject recorded, and an operator grant with no document,
        # are both unrepresentable. Withdrawals are exempt: consent must be evidenced, a
        # refusal must never be obstructed.
        CheckConstraint(
            "status <> 'granted' OR (notice_version IS NOT NULL AND ("
            f"(channel = {ALERT_OPTIN_SELF_SERVE!r} AND recorded_by_user_id = user_id) "
            f"OR (channel = {ALERT_OPTIN_OPERATOR!r} AND recorded_by_admin_id IS NOT NULL "
            "AND evidence IS NOT NULL)))",
            name="granted_optin_is_evidenced",
        ),
        # Exactly one accountable recorder. Neither is an anonymous consent record; both
        # is two parties for one act, which resolves to neither.
        CheckConstraint(
            "(recorded_by_user_id IS NULL) <> (recorded_by_admin_id IS NULL)",
            name="names_one_recorder",
        ),
        # The read: latest row for one (tenant, user, phone). Declared with a DESC
        # ordering and an INCLUDE, so autogenerate cannot faithfully diff it; the
        # migration is the source of truth for its existence.
        Index(
            "ix_whatsapp_alert_optin_current",
            "tenant_id",
            "user_id",
            "phone_e164",
            text("captured_at DESC"),
            text("created_at DESC"),
            postgresql_include=["status"],
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    # WHOSE agreement. An opt-in is obtained from the person who receives the messages,
    # so a handover of the owner role does not carry it.
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    # The number it was given FOR — the subject of the statement, not a second copy of
    # `users.phone`. Compared against the live number at send time.
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False)
    channel: Mapped[str] = mapped_column(String, nullable=False)
    # WHICH wording they agreed to (`whatsapp_optin.ALERT_NOTICE_VERSION`). Pinned by
    # version rather than copied, so the notice lives in one place and the row records
    # which one was shown.
    notice_version: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    recorded_by_user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT")
    )
    recorded_by_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    # A REFERENCE to what an operator's record rests on (onboarding pack, ticket id),
    # never the document itself.
    evidence: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class DncEntry(PKMixin, Base):
    """Do-not-call list (DATA-MODEL §9). `tenant_id IS NULL` = a GLOBAL entry.

    Two scopes in one table, as documented, with a deliberately asymmetric RLS policy
    (see the migration): a tenant can READ global entries — it must, or a nationally
    suppressed number would still be dialled — but can only WRITE its own. Creating a
    global entry is not a tenant-reachable operation at all.

    Additions must propagate BEFORE the next dispatch tick (hard rule 5), which is why
    the check reads this table live on every dispatch path rather than caching it.
    """

    __tablename__ = "dnc_list"
    __table_args__ = (
        CheckConstraint("scope IN ('global', 'tenant')", name="scope_enum"),
        CheckConstraint(
            "(scope = 'global' AND tenant_id IS NULL) "
            "OR (scope = 'tenant' AND tenant_id IS NOT NULL)",
            name="scope_matches_tenant",
        ),
        UniqueConstraint("tenant_id", "phone_e164"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String, nullable=False, server_default="tenant")
    source: Mapped[str | None] = mapped_column(Text)
    added_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class DltRegistration(PKMixin, TimestampMixin, Base):
    """Whether this client may lawfully have calls placed on their behalf (SEC-COMP §3).

    The DLT role model, per §3: the **client is the Principal Entity (PE)** and
    **Calevate is the registered Telemarketer (TM)** linked to them. Three registrations
    exist at the registrar and only two of them had a home in this schema —
    `phone_numbers.dlt_status` (the header) and `dlt_templates.status` (the voice
    template). This is the third and the widest: the ENTITY. A registered header on an
    unregistered entity is still unregistered traffic, dropped at the network as spam,
    with the complaints filed against the client.

    One row per tenant (UNIQUE on tenant_id): a business is one Principal Entity. The
    row is MUTABLE — a registration is suspended and restored over its life — so this
    is deliberately not an append-only ledger; `audit_log` carries who changed it.

    NOT modelled here: Calevate's OWN TM registration, which §3 also names. That is a
    company-level fact, true or false for every tenant at once, and it belongs with the
    other global switches in `platform_state` (DATA-MODEL §9a), not in a per-tenant
    table where it would be stored N times and disagree with itself.
    """

    __tablename__ = "dlt_registrations"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        CheckConstraint(f"status IN {PE_REGISTRATION_STATUSES!r}", name="status_enum"),
        CheckConstraint(f"tm_link_status IN {TM_LINK_STATUSES!r}", name="tm_link_status_enum"),
        # An `active` registration that cannot name its PE id is not a registration,
        # it is a claim. The id is what an operator checks against the registrar.
        CheckConstraint(
            "status <> 'active' OR (pe_id IS NOT NULL AND registered_at IS NOT NULL)",
            name="active_registration_names_its_pe",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    pe_id: Mapped[str | None] = mapped_column(Text)  # the registrar's Principal Entity id
    entity_name: Mapped[str | None] = mapped_column(Text)  # as registered, not as branded
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="not_started")
    tm_link_status: Mapped[str] = mapped_column(String, nullable=False, server_default="not_linked")
    registered_at: Mapped[datetime | None]
    verified_at: Mapped[datetime | None]  # when WE last checked it against the registrar


class KycRecord(PKMixin, TimestampMixin, Base):
    """Whether we know who this business is, to the standard a telecom connection needs.

    The last R-11 mitigation (BRD §245) and SURFACES §2b's last self-serve bullet:
    "Number purchase + KYC: gated; calling stays disabled until verification clears."

    **Not the same fact as `DltRegistration`, and deliberately not overlapping it.** PE
    registration proves the client may have commercial calls sent under their headers
    and templates, verified by an access provider on a DLT portal. This proves that a
    named person at Calevate checked this business's identity against a named document
    before a *connection* was provisioned for them — the DoT business-connection regime
    (CIN/licence + address + GST + end-user list), which attaches to the number, not to
    the message. The two ask for overlapping documents and are held by different
    parties for different purposes; neither satisfies the other. Sources are in
    `apps/api/compliance/kyc.py`.

    One row per tenant, MUTABLE, absent from `APPEND_ONLY_TABLES` — same reasoning as
    `DltRegistration`: a verification is cleared and later expires, the gate reads the
    current state on every provisioning attempt, and `audit_log` carries who changed it.

    **No identity document is stored here.** `document_ref` is a public business-registry
    identifier and `evidence_ref` is a reference to where the pack is filed. The CHECK
    constraints mirror migration a3f6b1e02d95 and the migration is the source of truth
    (DATA-MODEL §10).
    """

    __tablename__ = "kyc_records"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        CheckConstraint(f"status IN {KYC_STATUSES!r}", name="status_enum"),
        CheckConstraint(
            f"entity_type IS NULL OR entity_type IN {KYC_ENTITY_TYPES!r}", name="entity_type_enum"
        ),
        CheckConstraint(
            f"document_kind IS NULL OR document_kind IN {KYC_DOCUMENT_KINDS!r}",
            name="document_kind_enum",
        ),
        # The four questions an auditor asks — what, against what, by whom, when — as a
        # constraint rather than a convention. A `verified` row that cannot answer them
        # is a claim, not evidence.
        CheckConstraint(
            "status <> 'verified' OR (document_kind IS NOT NULL AND document_ref IS NOT NULL "
            "AND verified_by_admin_id IS NOT NULL AND verified_at IS NOT NULL)",
            name="verified_names_its_evidence",
        ),
        # The question a support person asks. "Rejected, no reason recorded" is the
        # ticket nobody can close.
        CheckConstraint(
            "status <> 'rejected' OR rejection_reason IS NOT NULL",
            name="rejected_names_its_reason",
        ),
        # Backstop, not the control: no permitted registry identifier is twelve bare
        # digits, so a value shaped like an Aadhaar is someone pasting personal data
        # into a business field, refused at the moment of the mistake.
        CheckConstraint(
            "document_ref IS NULL OR document_ref !~ '^[0-9]{12}$'",
            name="document_ref_is_not_an_aadhaar",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="not_started")
    entity_type: Mapped[str | None] = mapped_column(Text)
    document_kind: Mapped[str | None] = mapped_column(Text)
    # The public registry identifier — CIN/LLPIN/GSTIN/Udyam. Never a scan, never a
    # natural person's document number.
    document_ref: Mapped[str | None] = mapped_column(Text)
    # Who signed for the entity. A name, so support knows whom to call back; their
    # identity document stays with the licensee's CAF and never lands here.
    signatory_name: Mapped[str | None] = mapped_column(Text)
    # WHERE the verification pack is filed (ticket id / object key). A reference, on the
    # same principle as `outbound_webhooks.secret_ref`: the pointer travels, the
    # document does not.
    evidence_ref: Mapped[str | None] = mapped_column(Text)
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    # BY WHOM. An `admin_users.id`, not a free-text name: an auditor asks who, and a
    # string nobody can resolve to a person is not an answer.
    verified_by_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    submitted_at: Mapped[datetime | None]
    verified_at: Mapped[datetime | None]


class FirstCampaignReview(PKMixin, TimestampMixin, Base):
    """A human at Calevate cleared this account to run campaigns (R-11, D-34).

    The last of the six R-11 mitigations BRD §245 and FLOWS §2 require the self-serve
    motion to ship WITH: "manual review of the first campaign for any self-serve
    account". The argument for the shape — why "first" is a property of the ACCOUNT and
    not a flag on a campaign row, and why absence rather than a `pending` row means "not
    reviewed" — is in migration c4d9e18a72b6 and in
    `apps/api/compliance/first_campaign.py`.

    One row per tenant, MUTABLE, absent from `APPEND_ONLY_TABLES` — the same reasoning
    as `KycRecord` and `DltRegistration`: this is the account's CURRENT state, read by
    the launch gate and by every dispatch tick, and a release that is later withdrawn
    updates it. The immutable history is `audit_log`, where every decision writes a row
    (hard rule 4), so a reversal is a new entry rather than an edited one.

    The CHECK constraints mirror migration c4d9e18a72b6 and the migration is the source
    of truth (DATA-MODEL §10).
    """

    __tablename__ = "first_campaign_reviews"
    __table_args__ = (
        UniqueConstraint("tenant_id"),
        CheckConstraint(f"status IN {FIRST_CAMPAIGN_REVIEW_STATUSES!r}", name="status_enum"),
        CheckConstraint(
            f"decision_source IN {FIRST_CAMPAIGN_DECISION_SOURCES!r}",
            name="decision_source_enum",
        ),
        # WHO, as a constraint: an operator release that cannot name its operator is not
        # a review. The only exempt rows say in the same breath that no operator made
        # them (`migration_backfill`).
        CheckConstraint(
            "decision_source <> 'operator' OR decided_by_admin_id IS NOT NULL",
            name="operator_decision_names_its_operator",
        ),
        # WHAT was reviewed. A release nobody can account for later is the audit finding
        # this table exists to avoid.
        CheckConstraint(
            "length(btrim(decision_note)) >= 3", name="decision_says_what_was_reviewed"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String, nullable=False)
    # EVIDENCE, never the mechanism: which campaign the operator actually read. SET NULL
    # on delete, because losing the pointer must not change whether the account is
    # cleared — a hold that a DELETE could clear is not a hold.
    reviewed_campaign_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("campaigns.id", ondelete="SET NULL")
    )
    decision_note: Mapped[str] = mapped_column(Text, nullable=False)
    decision_source: Mapped[str] = mapped_column(String, nullable=False, server_default="operator")
    # An `admin_users.id`, not a typed name: an auditor asks who, and a string nobody can
    # resolve to a person is not an answer.
    decided_by_admin_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admin_users.id", ondelete="RESTRICT")
    )
    decided_at: Mapped[datetime] = mapped_column(nullable=False)


class RetentionPolicy(PKMixin, Base):
    __tablename__ = "retention_policies"
    __table_args__ = (
        CheckConstraint(f"data_category IN {DATA_CATEGORIES!r}", name="category_enum"),
        CheckConstraint(f"action IN {RETENTION_ACTIONS!r}", name="action_enum"),
        # TRAI 90-day floor for recordings (SEC-COMP §1)
        CheckConstraint(
            "data_category != 'recording' OR ttl_days >= 90", name="recording_ttl_floor"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    data_category: Mapped[str] = mapped_column(String, nullable=False)
    ttl_days: Mapped[int] = mapped_column(Integer, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False, server_default="delete")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class DeletionRequest(PKMixin, Base):
    """Deletion-with-proof (DPDP): proof JSON records what/where/when/hashes.

    The number lives exactly as long as the erasure takes. An OPEN request carries it
    because the worker's only handle on the subject is this row; a COMPLETED request has
    it cleared in the same UPDATE that stamps `proof`, because otherwise the record
    proving we erased someone is the last surviving copy of their number and no retention
    policy covers this table (migration f4a8e1c07b62). `subject_ref` — the same
    sha256(number)[:32] as the proof's `subject_hash` and the subject-access export — is
    what answers "have we already erased this person?" afterwards, and it answers it only
    to a reader who already holds the number.

    Two constraints keep those halves honest and are declared here to match the
    migration: an open request must name its subject, and every row must carry its
    reference. The first is also what keeps the partial unique index below total over the
    rows it covers — a NULL never conflicts in a unique index, so a request that could
    lose its number while still open would silently opt out of the one-open-request
    guarantee.

    `subject_ref` is NOT NULL and a BEFORE INSERT trigger derives it from the number when
    a writer does not supply one, so the hash cannot drift from the number and no INSERT
    written before the column existed becomes a failure. The application still writes it
    explicitly; the trigger fills, and never overwrites.
    """

    __tablename__ = "deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "completed_at IS NOT NULL OR phone_e164 IS NOT NULL",
            name="open_request_names_its_subject",
        ),
        CheckConstraint("subject_ref IS NOT NULL", name="subject_ref_not_null"),
        # At most ONE queued, unexecuted erasure per subject (migration e2c47b90d5a1).
        # Partial on purpose: erasure is not terminal for a phone number — the same
        # person can call the same client next month and exercise DPDP §12 again.
        # Declared with a predicate, so autogenerate cannot diff it; the migration is the
        # source of truth for its existence.
        Index(
            "uq_deletion_requests_open_subject",
            "tenant_id",
            "phone_e164",
            unique=True,
            postgresql_where=text("completed_at IS NULL"),
        ),
        Index("ix_deletion_requests_tenant_subject", "tenant_id", "subject_ref"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # Nullable ONLY after completion — see the CHECK above.
    phone_e164: Mapped[str | None] = mapped_column(Text)
    subject_ref: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str | None] = mapped_column(Text)
    requested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None]
    proof: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)


class AuditLogEntry(PKMixin, Base):
    """NOT tenant-RLS'd: admin-realm surface reads it cross-tenant, always audited
    itself. INSERT-only. Includes recording/raw-transcript reads (hard rule 5)."""

    __tablename__ = "audit_log"
    __table_args__ = (
        CheckConstraint(f"actor_type IN {ACTOR_TYPES!r}", name="actor_enum"),
        # The CHAIN ORDER, indexed. `(at, id)` is the total order every hash link is
        # computed in, so both chain operations are index-only walks over it: the head
        # read on the write path (`ORDER BY at DESC, id DESC LIMIT 1`, a backward
        # descent to the rightmost leaf) and `verify_chain`'s keyset pages
        # (`WHERE (at, id) > (...) ORDER BY at ASC, id ASC`, which needs the ASC
        # declaration for the row comparison to be an index qual rather than a filter).
        # Declared ASC for that reason; a LIMIT 1 costs the same in either direction.
        Index("ix_audit_log_chain", "at", "id"),
    )

    actor_type: Mapped[str] = mapped_column(String, nullable=False)
    actor_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    tenant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[str | None] = mapped_column(Text)
    object_id: Mapped[str | None] = mapped_column(Text)
    ip: Mapped[str | None] = mapped_column(Text)
    at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    # Tamper-evident chain (BACKEND-PATTERNS §7)
    prev_hash: Mapped[str | None] = mapped_column(Text)
    entry_hash: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
