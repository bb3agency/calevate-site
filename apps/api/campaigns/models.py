"""Campaign tables (DATA-MODEL §6).

Two state machines, both driven by CAS transitions (BACKEND-PATTERNS §5):

- `campaigns.status`: draft → scheduled → running ⇄ paused → completed | cancelled.
- `campaign_contacts.status`: pending → dialing → connected | pending (retry) | failed |
  dnc_blocked. `dnc_blocked` is TERMINAL — a number that opted out is not "retryable", it
  is done. `no_answer` and `completed` are admitted by the CHECK and written by nothing:
  whether an unconnected attempt was busy, unanswered or voicemail is a fact about its
  CALL (`last_call_id`), and `campaigns.results` reads it from there.

`dlt_templates` ships alongside because the launch gate reads it: an approved template
is one of the named blockers (SEC-COMP §3), and the 140/160 series-vs-classification
match is a CHECK at launch, not a convention.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

CAMPAIGN_CLASSIFICATIONS = ("promotional", "transactional", "service")
# Where a contact list's consent came from (SEC-COMP §3). An ENUM, not free text:
# the gate has to be able to CHECK the answer, and "consent obtained :)" typed into a
# text box checks as easily as it lies. Each member names a lawful basis a client can
# actually point at an artefact for.
#
# `purchased_list` is in the list ON PURPOSE. §3 refuses a purchased list "in writing,
# as policy" — a refusal that can only be written if the client can say the word. An
# enum containing only acceptable answers does not prevent purchased lists; it just
# moves them behind whichever member sounds closest, where nothing can see them.
CONSENT_SOURCES = (
    "existing_customer",  # prior transaction/relationship with the client
    "inbound_enquiry",  # they called, messaged or filled the client's enquiry form
    "web_form_optin",  # explicit tick-box on the client's own web form
    "offline_form_optin",  # paper form, event registration, in-store signup
    "purchased_list",  # bought or rented from a broker — refused at the gate
)
# Sources the launch gate refuses outright rather than merely recording.
REFUSED_CONSENT_SOURCES = ("purchased_list",)
CAMPAIGN_STATUSES = ("draft", "scheduled", "running", "paused", "completed", "cancelled")
CAMPAIGN_KINDS = ("standard", "pip")
#: The automatic pauses that carry no marker column of their own (D-773). Maintenance and
#: the healer are named by `paused_by_maintenance_id` / `paused_by_heal_id`.
AUTO_PAUSE_REASONS = ("complaint_spike", "out_of_credit", "spend_cap")
CONTACT_STATUSES = (
    "pending",
    "dialing",
    "connected",
    "no_answer",
    "failed",
    "dnc_blocked",
    "completed",
)
TEMPLATE_STATUSES = ("draft", "submitted", "approved", "rejected")


class Campaign(PKMixin, TimestampMixin, Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        CheckConstraint(
            f"classification IN {CAMPAIGN_CLASSIFICATIONS!r}", name="classification_enum"
        ),
        CheckConstraint(f"status IN {CAMPAIGN_STATUSES!r}", name="status_enum"),
        CheckConstraint(f"kind IN {CAMPAIGN_KINDS!r}", name="kind_enum"),
        # Per-campaign concurrency slider, bounded by the plan ceiling at launch time
        # (FLOWS §5 rule 4) and by the console's `campaign_max_concurrency` on every write;
        # the DB bound is the absolute sanity limit, the code ceiling
        # (`calevate_shared.config.CAMPAIGN_CONCURRENCY_CEILING`).
        CheckConstraint("concurrency BETWEEN 1 AND 20", name="concurrency_range"),
        # NULL is a legal value — it means "nobody has said yet", which is exactly what
        # every campaign that predates these columns can honestly claim. What is NOT
        # legal is a source outside the enum...
        CheckConstraint(
            f"consent_source IS NULL OR consent_source IN {CONSENT_SOURCES!r}",
            name="consent_source_enum",
        ),
        # ...or half an answer. A source with no date cannot be aged against a consent
        # that has since been withdrawn, and a date with no source names nothing.
        CheckConstraint(
            "(consent_source IS NULL) = (consent_collected_at IS NULL)",
            name="consent_provenance_complete",
        ),
        CheckConstraint(
            f"auto_pause_reason IS NULL OR auto_pause_reason IN {AUTO_PAUSE_REASONS!r}",
            name="auto_pause_reason_enum",
        ),
        # F-10: an archive says who did it, from which realm, and an operator says why.
        CheckConstraint(
            "(archived_at IS NULL AND archived_by_realm IS NULL AND archive_reason IS NULL) "
            "OR (archived_at IS NOT NULL AND archived_by_realm IN ('client', 'admin') "
            "AND (archived_by_realm = 'client' OR char_length(btrim(archive_reason)) >= 3))",
            name="archive_complete",
        ),
        # One trimmed line each, sized so the two fit one call variable (`campaigns/brief`).
        CheckConstraint(
            "purpose IS NULL OR (char_length(purpose) BETWEEN 3 AND 90 "
            "AND purpose = btrim(purpose) AND purpose !~ '[\\r\\n]')",
            name="purpose_line",
        ),
        CheckConstraint(
            "goal IS NULL OR (char_length(goal) BETWEEN 3 AND 50 "
            "AND goal = btrim(goal) AND goal !~ '[\\r\\n]')",
            name="goal_line",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    #: Why the campaign calls these people, and what a good call ends with, in the business's
    #: words (`campaigns/brief.py`). Both ride every dial as its reason; calls are judged
    #: against the goal (`calls.goal_reached`). NULL on a campaign made before they existed.
    purpose: Mapped[str | None] = mapped_column(Text)
    goal: Mapped[str | None] = mapped_column(Text)
    #: What the campaign should achieve, in the owner's words, many lines (D-992). Pip writes
    #: the campaign's script from it and the campaign's materials.
    main_task: Mapped[str | None] = mapped_column(Text)
    #: The campaign's own call script (a `CallScript` as JSON, D-992). The campaign owns what
    #: its calls say; Start puts it live on the campaign's agent, which is the voice.
    script: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    #: Pip's pending draft of that script (`campaigns/workspace.py`): id, status, the written
    #: script or the failure note. Replaced by the next request, cleared by Update or Discard.
    script_proposal: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    #: The agent's script version this campaign put live at its last Start.
    script_live_version: Mapped[int | None]
    #: The saved script as it was when Pip was last asked to write it, to switch back to.
    script_before_pip: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    script_before_pip_at: Mapped[datetime | None]
    #: A second opening line tested against the script's own, alternating per person (D-992).
    opening_b: Mapped[str | None] = mapped_column(Text)
    #: The agent settings this campaign sets for its own calls (D-994), each key present only
    #: when overridden (`campaigns/settings.py`). The agent holds the defaults.
    settings_overrides: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    #: RETIRED (D-1003): when this campaign last put its script on its agent, before each
    #: campaign had its own engine agent. Nothing writes it; the deploy sweep reads it once to
    #: give such an agent its own script back (`workers/campaign_engine_agents`). Kept until a
    #: later release drops it (hard rule 8).
    agent_held_at: Mapped[datetime | None]
    #: The campaign's own engine agent (D-1003): its script and settings in its agent's voice,
    #: published by Start and by its test call, retired when the campaign ends. It never
    #: answers a number; it calls out on one lent to it for each call.
    engine_agent_ref: Mapped[str | None] = mapped_column(Text)
    #: When that engine agent was last published; an unused test holder is retired after it.
    engine_agent_at: Mapped[datetime | None]
    #: What this campaign's calls note ("What it notes"), in the extraction-schema field
    #: shape; empty means the agent's own fields are noted.
    extraction_fields: Mapped[list[dict[str, object]]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    #: The calls its Test call placed, newest last (migration b3d8e1f6a2c9). Kept here rather
    #: than in `calls.campaign_id`, which would count them in the campaign's results.
    test_call_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(PG_UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )
    #: `pip` for a campaign a dialling plan made (D-893, migration f4b8d2a61c39), so its
    #: calls get a campaign's line limit, pacing, hours and retries; `standard` otherwise.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, server_default="standard")
    classification: Mapped[str] = mapped_column(String, nullable=False)
    number_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("phone_numbers.id", ondelete="SET NULL")
    )
    dlt_template_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("dlt_templates.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
    schedule: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    concurrency: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    # {max_attempts, backoff_minutes, windows} — FLOWS §5 per-contact retries.
    retry_policy: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    calling_hours: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    engine_campaign_ref: Mapped[str | None] = mapped_column(Text)
    launched_at: Mapped[datetime | None]
    #: WHICH MAINTENANCE WINDOW PAUSED THIS CAMPAIGN, if one did (D-544).
    #:
    #: The whole of "a campaign halted by maintenance must come back where it was". The
    #: pause itself is the ordinary `running -> paused` CAS every other pauser uses, so the
    #: campaign's contacts, attempt counts and retry ladder are untouched and a resume
    #: continues rather than restarting. What this column adds is the ONE thing the status
    #: alone cannot express: which paused campaigns are OURS to resume. Without it the
    #: window's end would either resume nothing (and silently kill every campaign it
    #: stopped) or resume everything paused (and restart the campaigns a client paused on
    #: purpose, or the ones `complaint_spike` stopped for a TCCCPR reason).
    #:
    #: NULLed in the same statement that resumes, so it is never a record of history — the
    #: history is `audit_log`. A FK with `ON DELETE SET NULL`: a deleted window must not
    #: strand a campaign, and a stranded NULL simply means nobody will auto-resume it.
    paused_by_maintenance_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("platform_maintenance_windows.id", ondelete="SET NULL")
    )
    #: Which healer incident paused this campaign, if one did (D-701). The same marker for
    #: the same reason as the maintenance one: the healer's restore resumes only its own
    #: pauses, and any person's pause or resume clears it (`set_campaign_status`).
    paused_by_heal_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("heal_incidents.id", ondelete="SET NULL")
    )
    #: Which automatic safety paused this campaign, when it was not maintenance or the
    #: healer (D-773). Written by the pausing CAS and cleared by any move a person makes,
    #: so it always describes the current pause and never a past one.
    auto_pause_reason: Mapped[str | None] = mapped_column(String)
    #: When the client confirmed they reviewed the opt-outs behind a complaint-spike pause.
    #: Resume is refused until it is set; the spike measurement restarts from it, so the
    #: opt-outs already reviewed do not pause the campaign a second time.
    complaint_reviewed_at: Mapped[datetime | None]
    #: Put away (F-10): hidden from the default list, never dialled, every call, lead and
    #: charge it made kept. NULL is "not archived". Restore clears all four.
    archived_at: Mapped[datetime | None]
    #: The user (client realm) or operator (admin realm) who archived it; no foreign key,
    #: because the two realms keep their people in different tables.
    archived_by: Mapped[UUID | None]
    archived_by_realm: Mapped[str | None] = mapped_column(String)
    #: Why, in an operator's words when Calevate archived it (required there); shown to the
    #: client in the notice.
    archive_reason: Mapped[str | None] = mapped_column(String)
    # Consent provenance for THIS campaign's contact list (SEC-COMP §3). It sits on the
    # campaign rather than in `consent_ledger` because the ledger answers a different
    # question at a different time: per phone, per call, AFTER the conversation. The
    # gate has to ask before the first ring, about the list as a whole.
    consent_source: Mapped[str | None] = mapped_column(String)
    consent_collected_at: Mapped[datetime | None]
    #: When OUR OWN tenant-list DNC scrub last ran for this campaign — half of
    #: SEC-COMP §3's DNC bullet, and compliance EVIDENCE rather than a cache: it is what
    #: a client's `/campaigns/{id}` shows beside the national-DND run, and the pair is
    #: the point (one is ours, one is an access provider's, and a single green tick
    #: could not say which).
    #:
    #: Declared here late (P4.3). It was created by `a1c8e40f27b9`, is written by
    #: `launch_campaign` and read by `campaign_progress`, and was absent from this model
    #: — so `alembic revision --autogenerate` compared a live column against metadata
    #: that did not mention it and would have proposed DROPPING it. CLAUDE.md's workflow
    #: is "autogenerate + hand-review diff", which makes an unreviewed accept a data-loss
    #: event on compliance evidence.
    dnc_scrubbed_at: Mapped[datetime | None]


MATERIAL_KINDS = ("file", "link", "note")
MATERIAL_SOURCES = ("owner", "call")


class CampaignMaterial(PKMixin, TimestampMixin, Base):
    """What the owner gives a campaign to work from (D-992): an uploaded document (held in the
    client's knowledge, `kb_upload_id`, so the agent can also look it up on a call), a link, or
    a note. `source = 'call'` is a note learned from the campaign's own calls: an answer the
    owner gave to a question the agent could not answer. Removed by archiving, never deleted.

    RETIRED: a campaign picks its sources from What your agents know (`CampaignSource`), and
    nothing reads or writes this table. Kept until a later release drops it (hard rule 8)."""

    __tablename__ = "campaign_materials"
    __table_args__ = (
        CheckConstraint(f"kind IN {MATERIAL_KINDS!r}", name="kind_enum"),
        CheckConstraint(f"source IN {MATERIAL_SOURCES!r}", name="source_enum"),
        Index("ix_campaign_materials_campaign", "campaign_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    source: Mapped[str] = mapped_column(String(8), nullable=False, server_default="owner")
    title: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    kb_upload_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("kb_uploads.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID | None]
    archived_at: Mapped[datetime | None]


class CampaignSource(PKMixin, TimestampMixin, Base):
    """A source from What your agents know that a campaign is written from (founder, 16 Nov
    2026: campaigns pick from what the agents know). Replaces `campaign_materials`, whose
    live rows migration e3c7a1d9b4f2 carried over and which nothing reads any more."""

    __tablename__ = "campaign_sources"
    __table_args__ = (UniqueConstraint("campaign_id", "kb_source_id", name="campaign_source"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False
    )
    kb_source_id: Mapped[UUID] = mapped_column(
        ForeignKey("kb_sources.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[UUID | None]


class CampaignContact(PKMixin, TimestampMixin, Base):
    __tablename__ = "campaign_contacts"
    __table_args__ = (
        UniqueConstraint("campaign_id", "phone_e164"),
        CheckConstraint(f"status IN {CONTACT_STATUSES!r}", name="status_enum"),
        CheckConstraint(
            "opening_variant IS NULL OR opening_variant IN ('a', 'b')",
            name="opening_variant_enum",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    campaign_id: Mapped[UUID] = mapped_column(
        ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True
    )
    phone_e164: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str | None] = mapped_column(Text)
    custom: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    last_attempt_at: Mapped[datetime | None]
    next_attempt_at: Mapped[datetime | None]
    last_call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    #: Which opening this person's calls used: `a` (the script's own) or `b` (D-992).
    opening_variant: Mapped[str | None] = mapped_column(String(1))
    #: Switched off, the person stays on the list and is never dialled (founder, 16 Nov 2026).
    included: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class DltTemplate(PKMixin, TimestampMixin, Base):
    """The DLT voice template a campaign speaks under. `dlt_ref` is the registrar's id;
    `approved` is what the launch gate requires (SEC-COMP §3)."""

    __tablename__ = "dlt_templates"
    __table_args__ = (
        CheckConstraint("kind = 'voice'", name="kind_enum"),
        CheckConstraint(
            f"classification IN {CAMPAIGN_CLASSIFICATIONS!r}", name="classification_enum"
        ),
        CheckConstraint(f"status IN {TEMPLATE_STATUSES!r}", name="status_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String, nullable=False, server_default="voice")
    classification: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    dlt_ref: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
