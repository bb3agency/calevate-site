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
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Identity,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin

#: A vendor LIST PRICE, in **USD per MILLION tokens** — the unit
#: `calevate_shared.engine.LlmPrice` publishes and `billing/rates.py` converts from. Six
#: decimals rather than `billing.models.MONEY`'s four: this is a per-MILLION-token dollar
#: figure ($0.15, $0.075, …), and the conversion to a NUMERIC(12,4) rupee `unit_cost_paid`
#: multiplies by the FX rate and divides by 1,000 downstream — so the precision that
#: matters is the vendor's published one, not the ledger column's. USD and not INR is
#: deliberate and matches the rate card's own doctrine (hard rule 7): the vendor publishes
#: dollars, the USD->INR rate MOVES (it is pulled every five minutes, D-475), and a
#: figure that has already
#: multiplied the two cannot be re-derived when either moves (the D-103/D-105 defect on the
#: money axis). NUMERIC, never a float.
USD_PER_MTOK = Numeric(12, 6)


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
    #: THE CONCURRENCY TOKEN. Drawn from a global sequence by the column default on
    #: INSERT and by a BEFORE UPDATE trigger on every update, so a value is never
    #: reissued — which is what makes an ETag read before a revert unable to match the
    #: row that replaces it. A conditional write (`If-Match`) compares against this and
    #: refuses rather than merges. See the migration for why not `xmin`, why not a
    #: per-row counter, and why not the fleet-wide sentinel.
    revision: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("nextval('platform_settings_revision_seq')")
    )


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


class PlatformSecret(Base):
    """One VERSION of one platform credential. Ciphertext only, INSERT-only (§5).

    Append-only for the reason the money ledgers are: "which key was live when this call
    was billed?" has to be answerable a year later, and an UPDATE would erase the
    evidence rather than record the change. A rotation is a NEW ROW; the old row is
    retired, never edited and never deleted. The immutability trigger ships in the same
    migration and `check_ledger_immutability` picks it up from `APPEND_ONLY_TABLES`.

    Column names are `core/envelope.Envelope`'s field names on purpose, so the INSERT is
    a transcription rather than a translation. `kek_version` holds `Envelope.kek_id` — a
    FINGERPRINT of the key rather than an operator-maintained counter (D-96;
    `core/envelope.Kek` carries the argument). It is a REPORTING field: nothing filters
    on it, and `secret_service.rewrap_all` says at length why it must never become a
    filter.
    """

    __tablename__ = "platform_secrets"

    key: Mapped[str] = mapped_column(Text, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_wrapped: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    dek_nonce: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    kek_version: Mapped[int] = mapped_column(Integer, nullable=False)
    #: The ONLY plaintext fragment that touches disk, and it exists so the console can
    #: show WHICH key is installed without being able to show the key
    #: (`core/envelope.last_four`, which masks anything too short to have four).
    last_four: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=False
    )
    #: Set when a newer version supersedes this one, and when a rewrap replaces its
    #: wrapping. NEVER deleted. These are the ONLY columns an UPDATE may touch, and the
    #: immutability trigger allows exactly that and nothing else — see the migration.
    retired_at: Mapped[datetime | None] = mapped_column()


class PlatformEngineHealth(Base):
    """One minute of one voice engine's server-side failures (OPERATIONS §4).

    THE STATE BEHIND `engine_error_spike`, and the reason it is a table rather than a
    counter in a process: "5xx spike" is a RATE, and the calls that produce it are spread
    over the api process pool and every ARQ worker. A module global would give each
    process its own private idea of how broken the vendor is, and the threshold would then
    mean N-times-more than it says — the identical defect D-160 fixed for the alert
    admission window.

    POSTGRES AND NOT REDIS, deliberately. Redis is already here and `core/alert_admission`
    already counts in it, so the boring choice was available; it is refused because that
    counter may only ever SUPPRESS an alert and this one CREATES one. A counter that can
    invent a page has to be as durable as the thing it reports on, and Redis in this
    deployment is an appendonly single container with no replica.

    ONE ROW PER (engine, minute), incremented — not one row per failure. A hard vendor
    outage retries thousands of times a minute; bounding the write to an upsert makes the
    table's growth a function of TIME (1,440 rows per engine per day, pruned to
    `RETENTION`) instead of a function of how bad the outage is.

    NOT tenant-scoped and never will be: the vendor is either answering or it is not, and
    that is one fact for the whole platform. Registered in
    `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as the written reason. Holds an
    engine name, a minute and two integers — no tenant, no call, no number.
    """

    __tablename__ = "platform_engine_health"

    #: Our engine name (`bolna`, `cartesia`, `fake`), never the vendor's.
    engine: Mapped[str] = mapped_column(Text, primary_key=True)
    #: The minute this row counts, truncated with `date_trunc('minute', now())`.
    bucket_start: Mapped[datetime] = mapped_column(primary_key=True)
    #: Requests that reached the vendor and came back 5xx.
    server_errors: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))
    #: Requests that never got an answer at all (DNS, TCP, TLS, read timeout). Counted
    #: SEPARATELY from `server_errors` because the two have different first moves for an
    #: operator — one is the vendor's application, the other is the path to it — and
    #: summed by the spike rule, because from a dial's point of view they are one outage.
    unreachable: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("0"))


class PlatformModelPrice(Base):
    """One OPERATOR-ATTESTED vendor list price for one LLM model, effective-dated (§5).

    THE PRICE HARD RULE 7 HAS NO 'REPORTED' TIER FOR. `calevate_shared.engine.LlmModelSpec`
    refuses to make a model selectable on an unverified price, and every OpenAI/Google
    pricing page is egress-blocked from this deployment — so no price for those legs can be
    VERIFIED in the tree. The founder's own workflow supplies the missing evidence class:
    the AUTHORITATIVE billing price is a value the operator reads off THEIR OWN vendor
    console or invoice and types here. That is first-party evidence and the only figure true
    for THIS account, which a published list price never is (a Regional Standard deployment
    is reported to cost more than the Global Standard list `LlmModelSpec` carries).

    CONFIG, NOT A SECRET — so it is NOT in `platform_secrets` and NOT encrypted. A price has
    to be auditable and revertible (an operator has to see what it is set to and correct a
    wrong one), which is the opposite of a write-only credential. It carries no PII and no
    credential; the only sensitive thing about it is that it reaches `unit_cost_paid`, and
    that is served by making it visible and effective-dated rather than hidden.

    APPEND-ONLY AND EFFECTIVE-DATED, which are one property here. A correction is a NEW ROW
    with a later `effective_from`, never an edit — so `attested_model_prices(session, at=…)`
    can answer "what was the price live when THIS month's minutes ran" a year later, and a
    re-rendered invoice is re-derivable rather than re-priced by whatever an operator changed
    since. It joins the hard-rule-4 family: the immutability + truncate triggers ship in the
    migration and `check_ledger_immutability` picks the table up from
    `db/registry.APPEND_ONLY_TABLES`. There is no rewrap exception (unlike
    `platform_secrets`); the blanket `calevate_forbid_mutation` applies, so EVERY column is
    immutable once written.

    NOT tenant-scoped and never will be: one account, one Azure/OpenAI/Google subscription,
    one price per model at an instant — there is no tenant whose row this could be. It is
    `platform_*`-named for the family it belongs to, and registered in
    `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as the written reason (the RLS sweep's
    rule 7a REQUIRES a `platform_*` table to appear there).

    Declared as an ORM model, like its siblings above, so `Base.metadata` knows about it and
    `check_rls_coverage` can compare the live schema against it.
    """

    __tablename__ = "platform_model_prices"

    #: The model identifier in OUR vocabulary — a key of `calevate_shared.engine.LLM_MODELS`.
    #: A plain string and not a `Literal`, because a price read back for a historical invoice
    #: must resolve even for a model the allow-list no longer carries — the same reason
    #: `LLM_MODELS` itself is keyed by `str` (see its comment).
    model: Mapped[str] = mapped_column(Text, primary_key=True)
    #: The instant this price becomes authoritative. Part of the PK with `model`, so two
    #: attestations for one model at the same instant collide rather than silently both
    #: existing — a correction is a DISTINCT instant. Resolution at instant T is the row for
    #: this model with the greatest `effective_from <= T` (`ix_platform_model_prices_model`).
    effective_from: Mapped[datetime] = mapped_column(primary_key=True)
    #: USD per MILLION input tokens, exactly as the vendor publishes it. See `USD_PER_MTOK`.
    input_usd_per_mtok: Mapped[Decimal] = mapped_column(USD_PER_MTOK, nullable=False)
    #: USD per MILLION output tokens.
    output_usd_per_mtok: Mapped[Decimal] = mapped_column(USD_PER_MTOK, nullable=False)
    #: The operator who attested it — every price in this table was typed by a person, so
    #: NOT NULL, referencing `admin_users` exactly as `platform_settings.updated_by` does.
    attested_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=False
    )
    attested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    #: WHERE the figure came from, in the operator's words — "Azure invoice 2026-08, line 3",
    #: "openai.com/api/pricing 23 Aug 2026". Required at the boundary (it is the evidence that
    #: makes this an attestation rather than a guess) and NOT NULL here.
    source_note: Mapped[str] = mapped_column(Text, nullable=False)


#: RUPEES per ONE THOUSAND synthesised characters. NUMERIC(12,6), never a float (hard rule
#: 7). Six decimals because the figure is a DIVISION an operator does by hand — a monthly
#: plan's committed spend over the characters it buys (₹4,312 / 1.25M = ₹3.4496 per 1,000)
#: — and a plan an order of magnitude larger divides finer still.
INR_PER_KCHAR = Numeric(12, 6)


class PlatformTtsPrice(Base):
    """One OPERATOR-ATTESTED TTS price for one VOICE PROVIDER, effective-dated (D-547).

    `PlatformModelPrice`'s argument, one vendor further down the call, and it arrives for a
    sharper reason. A BYOK synthesizer leg costs **₹0 from the engine** — Bolna charges
    nothing for a component you bring your own key for — so `CostBreakdown.tts_inr`, the
    figure `workers/pipeline.py` meters the Sarvam leg from, has nothing to report for a
    Cartesia call. And what Cartesia bills is a MONTHLY PLAN with a character allotment,
    not a per-call charge, so no payload could report it either. The cost of a Cartesia
    character is therefore a figure only a human holding the invoice can state.

    RUPEES PER THOUSAND CHARACTERS, and NOT the USD its LLM sibling stores. That table
    holds dollars because the vendor publishes dollars and the USD→INR rate moves under it
    (D-475); this figure is already a division of a committed rupee spend by an allotment,
    and storing dollars would mean asking an operator to un-divide it. `source_note` is
    where the plan, its period and any fx used are recorded.

    ⚠ **IT PRICES A CHARACTER INSIDE THE ALLOTMENT.** The vendor's OVERAGE rate past it is
    **UNKNOWN** (plan ADDENDUM 1, unknown #3) — not published anywhere anyone here has
    read — so a deployment running past its plan is paying more per character than this
    table says. That is a vendor question, not a code one, and no number is invented for it.

    Append-only, effective-dated, platform-scoped and declared here as an ORM model for
    exactly the three reasons `PlatformModelPrice` above states at length: a correction is
    a NEW instant so a re-rendered month resolves the price its characters were metered at;
    there is one vendor account for the whole deployment so no `tenant_id` (registered in
    `db/registry.RLS_EXEMPT_TENANT_COLUMNS`); and `Base.metadata` has to know about it or
    `check_rls_coverage` has nothing to compare the live schema against.
    """

    __tablename__ = "platform_tts_prices"

    #: The voice provider in OUR vocabulary — `agents/voices.VoiceProvider`, the same
    #: Literal `billing/lots.VoiceTier` spells. Plain text and not an enum, for
    #: `PlatformModelPrice.model`'s reason: a price read back for a historical month must
    #: resolve even for a provider the catalogue no longer offers.
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    #: The instant this price becomes authoritative. Part of the PK, so a correction is a
    #: DISTINCT instant rather than a silent second row.
    effective_from: Mapped[datetime] = mapped_column(primary_key=True)
    #: ₹ per 1,000 characters. See `INR_PER_KCHAR` for why the unit is a thousand.
    inr_per_1k_chars: Mapped[Decimal] = mapped_column(INR_PER_KCHAR, nullable=False)
    #: The operator who attested it — every price here was typed by a person, so NOT NULL.
    attested_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=False
    )
    attested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    #: WHERE the figure came from, in the operator's words — "Cartesia Startup plan,
    #: invoice 2026-09, ₹4,312 / 1.25M characters". It is the evidence that makes this an
    #: attestation rather than a guess, so NOT NULL.
    source_note: Mapped[str] = mapped_column(Text, nullable=False)


#: RUPEES for ONE MONTH of a voice vendor's plan, as the invoice states it. NUMERIC(12,2)
#: and NOT `INR_PER_KCHAR`'s six decimals: this figure is not a division, it is the amount
#: on the bill, and an invoice is quoted to the paisa. Never a float (hard rule 7).
PLAN_FEE_INR = Numeric(12, 2)


class PlatformTtsPlanFee(Base):
    """What a voice vendor BILLED US for one IST month, attested by an operator (D-547).

    `PlatformTtsPrice` next door answers "what does one CHARACTER cost" — the figure a
    usage row multiplies. It cannot answer this one, and the gap between them is the point
    of the table. A Cartesia plan is a COMMITTED monthly spend for a character allotment:
    the fee is paid whether or not the allotment is spoken, so the plan spend and the sum
    our own meter attributed to calls are two different numbers, and their difference is
    the unused allotment. That difference is the only figure that says whether the plan is
    the right size, and until this table existed nothing in this tree recorded the half of
    it that comes from the invoice.

    ⚠ **IT IS NOT AN INPUT TO `unit_cost_paid` AND MUST NEVER BECOME ONE.** A call's cost
    is the attested PER-CHARACTER rate times the characters it spoke (`PlatformTtsPrice`);
    dividing this fee by a month's characters after the fact would re-price a month whose
    rows are already written, on an append-only ledger. It is published beside the metered
    total, never folded into it.

    ⚠ **UNKNOWN: whether the vendor's own character count agrees with ours**
    (OPERATIONS §2 gate 51). `usage_events.qty` on a `tts_kchars` row comes from OUR
    transcript and from nothing the vendor says. This row is the vendor's side of the
    story and the meter is ours; the spend board publishes both and reconciles neither.

    Append-only, effective-dated per MONTH, platform-scoped — `PlatformTtsPrice`'s three
    properties for its three reasons, with `effective_from` beside `month` in the key so a
    CORRECTION is a later attestation for the same month rather than an edit.
    """

    __tablename__ = "platform_tts_plan_fees"

    #: The voice provider in OUR vocabulary — text, not an enum, for
    #: `PlatformTtsPrice.provider`'s reason.
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    #: The IST billing month the invoice covers, `YYYY-MM` — the same string
    #: `billing/plans.ist_billing_month` produces and every billing surface names. A CHECK
    #: pins the shape, because a row spelled `2026-9` would never match and would read as
    #: "nobody attested September".
    month: Mapped[str] = mapped_column(Text, primary_key=True)
    #: The instant this attestation becomes authoritative for that month.
    effective_from: Mapped[datetime] = mapped_column(primary_key=True)
    #: The whole month's fee in rupees. See `PLAN_FEE_INR`.
    plan_inr: Mapped[Decimal] = mapped_column(PLAN_FEE_INR, nullable=False)
    #: The operator who attested it — every figure here was typed by a person, so NOT NULL.
    attested_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=False
    )
    attested_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    #: WHERE the figure came from — "Cartesia Startup plan, invoice INV-2026-09-014". It is
    #: the evidence that makes this an attestation rather than a guess, so NOT NULL.
    source_note: Mapped[str] = mapped_column(Text, nullable=False)


#: INR per ONE US dollar, as the source publishes it. NUMERIC(12,6), never a float
#: (hard rule 7). Six decimals because a reference rate is quoted to four (`88.4275`) and
#: two spare digits cost nothing, while a `float` would make the stored number differ from
#: the vendor's published one in the digits an auditor compares.
FX_RATE = Numeric(12, 6)


class FxRateObservation(Base):
    """One USD→INR rate we pulled, with the provenance to explain a bill months later.

    PLATFORM-SCOPED AND APPEND-ONLY. There is one exchange rate for the whole deployment
    at an instant — no tenant whose row this could be — so it carries no `tenant_id` and
    is registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as the written
    reason. It is in `APPEND_ONLY_TABLES` (hard rule 4) for the reason
    `platform_model_prices` is: `usage_events.meta.fx_rate` records the rate a call was
    costed at, and a rate history somebody can edit after the bill was computed from it is
    not evidence of anything.

    NOT A `Settings` FIELD, deliberately. A row here is written by a machine every five
    minutes; `platform_settings` rows are written by an operator, carry a per-key revision
    for optimistic concurrency and land an `audit_log` entry each time. Routing a robot's
    288 daily writes through that store would put every operator's console edit into a
    false conflict with a poller and fill a hash-chained human-accountability ledger with
    machine noise. The two stores stay separate and `Settings.usd_inr_rate` keeps its own
    job: the FALLBACK money converts at when this table has nothing fresh.
    """

    __tablename__ = "fx_rate_observations"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)
    #: THE ORDER WE LEARNED THINGS. Not `observed_at`: `now()` is TRANSACTION start time in
    #: Postgres, so two rows written in one transaction share it and a tie between a rate
    #: and its own correction would be broken at random. Monotonic by construction.
    seq: Mapped[int] = mapped_column(BigInteger, Identity(always=True), nullable=False)
    #: `USD`/`INR` today, and columns rather than an assumption because a pair is exactly
    #: the fact `engine/bolna.py::_cost` got burned assuming (`currency_stated`): a rate
    #: whose direction is implied by the module it lives in cannot be checked by a reader.
    base_currency: Mapped[str] = mapped_column(Text, nullable=False)
    quote_currency: Mapped[str] = mapped_column(Text, nullable=False)
    #: Units of `quote_currency` per ONE unit of `base_currency`.
    rate: Mapped[Decimal] = mapped_column(FX_RATE, nullable=False)
    #: The date the SOURCE stamped on this rate. Part of the natural key below, because it
    #: is what makes a five-minute poll of a once-a-day publication idempotent.
    as_of: Mapped[date] = mapped_column(Date, nullable=False)
    #: `"<api>:<provider>"` — `frankfurter:FBIL`. Stamped onto every usage row this rate
    #: converts, so "which rate" and "whose rate" are both answerable later.
    source: Mapped[str] = mapped_column(Text, nullable=False)
    #: The exact URL that produced it, so a disputed figure can be re-requested rather than
    #: re-argued.
    source_url: Mapped[str] = mapped_column(Text, nullable=False)
    #: When THIS deployment fetched it. Distinct from `as_of` on purpose: the age of the
    #: DATA and the age of the PULL are different failures with different remedies
    #: (`core/fx.MAX_QUOTE_AGE` bounds the first, `workers/fx_pull.MAX_PULL_SILENCE` the
    #: second).
    observed_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    #: THE IDEMPOTENCY KEY, and the reason two workers cannot both write one instant:
    #: `source|base|quote|as_of|rate`. UNIQUE, so the second writer's INSERT is a no-op
    #: rather than a duplicate row — see the migration for why the RATE is in the key.
    observation_key: Mapped[str] = mapped_column(Text, nullable=False, unique=True)


class PlatformDashboardDataUse(Base):
    """WHAT AN OPERATOR ATTESTED ABOUT ONE LLM PROVIDER'S DATA-USE TERMS FOR THE DASHBOARD
    ASSIST LEG — and about the vendor account those terms are a property of.

    PLATFORM-SCOPED AND APPEND-ONLY, for `PlatformModelPrice`'s reasons exactly: there is one
    vendor account per provider for the whole deployment, so there is no tenant whose row this
    could be (`db/registry.RLS_EXEMPT_TENANT_COLUMNS`), and a correction is a NEW dated row so
    that "what did we believe, and on whose word, when we let a client's screen content reach
    this vendor" stays answerable after the fact. That question is the entire point of the
    table; a row somebody could edit afterwards would answer it with today's belief.

    ═══ WHY IT IS THREE FACTS AND NOT ONE SIGNATURE ═══

    A single "yes, the terms are fine" boolean is unfalsifiable and un-recheckable. The tier
    that decides the terms is a property of the vendor's PROJECT, not of the API key, and the
    binding between the two is the one joint nothing in this tree can verify — which is
    exactly the shape of the Azure region attestation (OPERATIONS §2 gate 20), where the
    portal is the only instrument. So the row captures the project by id, and the two
    independent settings that can each defeat the paid tier, separately:

    * `vendor_account_ref` — the vendor project/account the credential belongs to. FIRST
      CLASS and required, because without it nobody can ever re-check the claim: Google's
      Cloud Billing API answers `billingEnabled` for a PROJECT ID
      (`cloudbilling.googleapis.com/$discovery/rest?version=v1`, revision `20260821`, read
      27 Aug 2026 — VENDOR-PUBLISHED), and a boolean with no project id attached is a claim
      that can only ever be re-attested, never verified.
    * `paid_tier_confirmed` — the project is linked to an OPEN billing account. On Google
      this is the AI Studio Projects page's "Billing Tier" column. SECONDARY evidence (every
      Google-owned host is egress-blocked from this environment, re-measured 27 Aug 2026)
      says the unpaid tier's terms have Google use submitted content to improve its products
      with human reviewers able to read it, and instruct developers in as many words not to
      submit personal information to it.
    * `no_training_opt_in_confirmed` — no setting on that project puts submitted content back
      under the unpaid terms. On Google this is Gemini API Logs/Datasets sharing, which is off
      by default and, when on, SECONDARY evidence says returns a billing-enabled project's
      logs to the unpaid terms including model training. **An attestation that asked only the
      billing question would give a false negative on exactly this path**, which is why it is
      a second column rather than a sentence in `source_note`.

    ⚠ **`paid_tier_confirmed` DOES NOT MEAN "NOT LOGGED", "NEVER HUMAN-READ" OR "STORED IN
    INDIA", AND NOTHING HERE MAY BE READ AS SAYING SO.** On the same SECONDARY evidence the
    paid terms log prompts and responses for a limited period for abuse detection, permit
    authorised employees to read flagged content, and state the data "may be stored
    transiently or cached in any country". This table records that the vendor does not TRAIN
    on the content. That is one property, and it is the one the dashboard-eligibility gate
    turns on.

    ⚠ **THE SAME QUESTION GOVERNS THE IN-CALL LEG, WHICH IS LIVE TODAY**, and this table does
    NOT gate it: in-call sends raw caller speech to whatever provider a client's chosen model
    sits on. OPERATIONS §2 gate 41 is where that is owned, and it is a founder's decision, not
    a column.
    """

    __tablename__ = "platform_dashboard_data_use"

    #: `calevate_shared.engine.LlmProvider`, as text. A plain string and not an enum for
    #: `PlatformModelPrice.model`'s reason: an attestation read back to explain a decision
    #: must still resolve for a leg the product no longer declares.
    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    #: When the operator attested it. Part of the PK, so a re-attestation is a new row and two
    #: writers at one instant collide rather than silently both existing. The LATEST row per
    #: provider is what the eligibility gate reads.
    attested_at: Mapped[datetime] = mapped_column(primary_key=True)
    #: The operator who attested it — every row here was typed by a person, so NOT NULL,
    #: referencing `admin_users` exactly as `platform_model_prices.attested_by` does.
    attested_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admin_users.id"), nullable=False
    )
    #: The vendor project/account id the platform's credential for this provider belongs to.
    #: See the class docstring: without it the claim can never be re-checked, only re-made.
    vendor_account_ref: Mapped[str] = mapped_column(Text, nullable=False)
    #: Is that account on the vendor's PAID tier — the tier whose terms exclude training on
    #: submitted content?
    paid_tier_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: Is it free of any opt-in that puts submitted content back under the unpaid terms?
    no_training_opt_in_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    #: WHERE the operator looked, in their own words — "AI Studio Projects page, Billing Tier
    #: = Paid, project calevate-prod, 27 Aug 2026". The evidence that makes this an
    #: attestation rather than a guess, and the reason recorded in `audit_log`. NOT NULL.
    source_note: Mapped[str] = mapped_column(Text, nullable=False)


#: How long a DRAIN may run before the window activates anyway (D-544).
#:
#: Fifteen minutes, and every part of that number is a measurement in this repo rather
#: than a round figure. What draining waits for is (a) live calls and (b) durable queued
#: work. A call is bounded by `agents.call_cap_seconds` — the fleet ceiling is 15 minutes
#: (`agents/publishing.CallCapResult`), so one full-length call started one second before
#: the window opened is the worst honest case. Queued work is bounded by the outbox
#: dispatcher's 10-second tick times its 5-attempt ladder, which is far shorter. So the
#: bound is "the longest call we allow, and not a minute of round-number padding on top";
#: anything still running past it is not draining, it is wedged, and the answer to wedged
#: is an operator reading the straggler list rather than a longer wait.
#:
#: It is a per-window COLUMN with this as its default rather than a constant the code
#: reads, because the operator scheduling the window is the one who knows whether tonight
#: is a schema migration (wait) or a config push (do not).
DEFAULT_MAX_DRAIN_MINUTES = 15

#: The lifecycle of one window. Read `ops/maintenance.py` for the transitions; this tuple
#: is the DATABASE's copy of the same vocabulary and is interpolated into the CHECK below.
#:
#: THE TWO STATES THAT MATTER ARE `draining` AND `active`, and the whole feature is the
#: distinction between them. `draining` = we have stopped ACCEPTING work; in-flight work
#: is still running and is not killed. `active` = in-flight work reached zero (or the
#: drain deadline passed) and the platform is now shut to clients.
MAINTENANCE_STATES: tuple[str, ...] = (
    "scheduled",
    "draining",
    "active",
    "completed",
    "cancelled",
)

#: The states a window is still LIVE in — the ones at most one window may be in at a time
#: (`ux_platform_maintenance_windows_open` enforces it), and the ones the tick advances.
MAINTENANCE_OPEN_STATES: tuple[str, ...] = ("scheduled", "draining", "active")


class PlatformMaintenanceWindow(PKMixin, Base):
    """ONE planned outage: when it starts, when it ends, why, and where it has got to.

    PLATFORM-SCOPED AND DELIBERATELY SO. A maintenance window is one fact for the whole
    deployment at one instant, exactly like the big red switch and the load-shed mode it
    drives, so it carries no `tenant_id`, it is reachable only from the admin realm behind
    `ops:manage`, and it is registered in `db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that
    as the written reason (rule 7(a) of `check_rls_coverage` fires on the `platform_`
    prefix, which is how this table is made impossible to forget).

    NOT APPEND-ONLY, and the reasoning is `tenant_trials`': the row IS a state machine and
    an append-only version would need a second table to answer the one question it exists
    to answer ("what is happening right now"). The immutable history of who scheduled,
    amended, cancelled or forced it is `audit_log`, written in the same transaction as
    every transition.

    THE FOUR NOTICE STAMPS ARE THE DEDUPE, and they are columns rather than a second table
    for one reason: the fan-out must happen EXACTLY once per window per kind across an
    arbitrary number of worker processes, and a `UPDATE ... SET advance_notice_at = now()
    WHERE id = :id AND advance_notice_at IS NULL` returning rowcount 1 is that guarantee in
    one statement (BACKEND-PATTERNS §5's CAS doctrine). A worker that loses the race sends
    nothing and moves on.
    """

    __tablename__ = "platform_maintenance_windows"
    __table_args__ = (
        CheckConstraint(f"state IN {MAINTENANCE_STATES!r}", name="state_enum"),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        CheckConstraint("max_drain_minutes BETWEEN 1 AND 240", name="max_drain_minutes_range"),
        # A forced activation is a fact about an activation, so it cannot be recorded on a
        # window that never activated. Without this a cancelled window could carry
        # `forced = true` and the ops screen would report a drain that never ran.
        CheckConstraint("NOT forced OR activated_at IS NOT NULL", name="forced_implies_activated"),
    )

    #: What clients are shown, in the operator's own words. NOT NULL and non-blank at the
    #: boundary: a lockout page reading "maintenance" and nothing else is the generic error
    #: this whole feature exists to replace.
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(nullable=False)
    ends_at: Mapped[datetime] = mapped_column(nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False, server_default="scheduled")
    #: This window's drain bound, defaulted from `DEFAULT_MAX_DRAIN_MINUTES`.
    max_drain_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=str(DEFAULT_MAX_DRAIN_MINUTES)
    )
    #: Stamped when the window enters `draining`; `drain_deadline_at` is derived from it and
    #: stored rather than recomputed so the console and the tick read one instant.
    draining_since: Mapped[datetime | None] = mapped_column()
    drain_deadline_at: Mapped[datetime | None] = mapped_column()
    activated_at: Mapped[datetime | None] = mapped_column()
    #: True when the drain deadline expired with work still in flight. The window is ACTIVE
    #: either way; this is what tells the operator which kind of ACTIVE they are looking at.
    forced: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    #: What was still running at the moment of a FORCED activation — `{"calls": n,
    #: "jobs": n, "tenants": [...]}`. JSONB and not columns because it is a report an
    #: operator reads once, and NULL on a clean activation is the honest value.
    stragglers: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    #: THE LAST DRAIN PROBE, and the instant it was taken — `{"calls": n, "jobs": n,
    #: "tenants_unreached": n, "complete": bool}`.
    #:
    #: Written by the worker tick, read by the ops console. The console does NOT run the
    #: probe itself, and that is the decision rather than a shortcut: the probe is a
    #: fleet-wide walk (`calls` is FORCE-RLS'd, so it is one tenant session at a time —
    #: `workers/fleet_walk.py` exists because these walks outgrow a job timeout, never
    #: mind a request), and running it per page load would put an O(tenants) walk on an
    #: HTTP path. Storing it also makes the screen and the state machine provably agree:
    #: the operator sees the numbers the activation decision was actually taken on, with
    #: `probed_at` saying how old they are, instead of a second measurement that can
    #: disagree with the first.
    in_flight: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    probed_at: Mapped[datetime | None] = mapped_column()
    ended_at: Mapped[datetime | None] = mapped_column()
    cancelled_at: Mapped[datetime | None] = mapped_column()
    #: The mode `platform_state.load_shed_mode` held when this window activated, so
    #: completion RESTORES rather than assuming `normal`. A window that opened during a
    #: `reduced` shed must not silently end the shed as well as itself.
    restore_load_shed_mode: Mapped[str | None] = mapped_column(Text)
    #: The three client notices and the amendment, each stamped once by a CAS.
    advance_notice_at: Mapped[datetime | None] = mapped_column()
    amended_notice_at: Mapped[datetime | None] = mapped_column()
    active_notice_at: Mapped[datetime | None] = mapped_column()
    ended_notice_at: Mapped[datetime | None] = mapped_column()
    #: The operator who scheduled it. `ondelete` DECLARED, and matching the migration
    #: exactly: alembic compares a foreign key's options as well as its columns, so a model
    #: that omits it makes `--autogenerate` propose dropping and re-adding the constraint on
    #: every future revision — the drift `orm_schema_fidelity_test` exists to catch.
    #: SET NULL rather than RESTRICT because an operator leaving must not pin the history of
    #: every window they ever scheduled; the permanent record of who did what is `audit_log`.
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PlatformAlert(PKMixin, Base):
    """One EPISODE of one alarm — the console half of `core/alerting.py` (D-591).

    **A ROW IS AN EPISODE, NOT AN OCCURRENCE.** `fx_rate_stale` fires on every cost
    conversion while a vendor feed is down; twenty-six of them are one condition, and the
    thing an operator needs to read is "this started at 19:04, it is still going, it has
    happened 2,140 times". So the natural key is the alert FINGERPRINT (`stage:code`, the
    same string the delivery path deduplicates on) scoped to the episode that is still
    OPEN: `uq_platform_alerts_open_fingerprint` is a partial unique index on
    `fingerprint WHERE cleared_at IS NULL`, which is both the upsert target and the reason
    at most one episode of a code can be open at a time.

    That partial index is also what makes the EMAIL decision a transition rather than a
    poll: `INSERT ... ON CONFLICT ... RETURNING (xmax = 0)` says whether this occurrence
    OPENED the episode, and only an opening one is allowed to mail (`alert_records.py`).

    **NOT tenant-scoped, and registered as such.** An alarm is about this platform's own
    machinery — a backup chain, an outbox, a vendor feed — and a great many of them fire
    with no tenant in scope at all (the SIGTERM handler, the unauthenticated webhook edge,
    the host backup relay). See `db/registry.RLS_EXEMPT_TENANT_COLUMNS` for the written
    reason. A `tenant_id` here would be decorative on most rows and wrong on the rest.

    **NOT append-only**, deliberately: `occurrences`, `last_seen_at` and `cleared_at` are
    the whole point, and a ledger of 2,140 identical rows is the inbox this table exists
    to replace. Every figure in it is re-derivable from the ERROR log lines `alert()`
    writes first and unconditionally, which is the property `APPEND_ONLY_TABLES` protects
    elsewhere and the reason this table does not need to be in it.

    **HARD RULE 6, BY CONSTRUCTION.** `detail` and `ids` are written through
    `core/logging.redact_mapping` — the SAME function the alert email body uses — before
    they reach this table, so a phone number in a call site's kwarg is masked in the row
    as well as in the mail. `detail` is additionally capped. The column comments say so in
    the migration, and `tests/alert_severity_test.py` pins it.
    """

    __tablename__ = "platform_alerts"
    __table_args__ = (
        CheckConstraint(
            "severity IN ('page', 'attention', 'record')",
            name="severity",
        ),
        CheckConstraint("occurrences >= 1", name="occurrences_positive"),
        Index(
            "uq_platform_alerts_open_fingerprint",
            "fingerprint",
            unique=True,
            postgresql_where=text("cleared_at IS NULL"),
        ),
        Index(
            "ix_platform_alerts_last_seen",
            text("last_seen_at DESC"),
        ),
    )

    #: `stage:code` — the alert fingerprint, and the deduplication key `core/alerting.py`
    #: already keys its repeat window on. Stored rather than derived so the unique index
    #: has one column to sit on.
    fingerprint: Mapped[str] = mapped_column(Text, nullable=False)
    code: Mapped[str] = mapped_column(Text, nullable=False)
    stage: Mapped[str] = mapped_column(Text, nullable=False)
    #: `page` / `attention` / `record`, as `core/alarm_severity.py` had it AT THE TIME.
    #: Recorded on the row and not looked up on read, so a re-classification does not
    #: rewrite the history of what was actually mailed.
    severity: Mapped[str] = mapped_column(Text, nullable=False)
    #: `api`, `voice-runtime` or `workers` — the first question an operator asks.
    service: Mapped[str] = mapped_column(Text, nullable=False)
    #: REDACTED, and capped. See the class docstring.
    detail: Mapped[str | None] = mapped_column(Text)
    #: The `**ids` the call site passed, REDACTED by the same function. Ids only.
    ids: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    first_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    #: Every occurrence in this episode, including the ones the repeat window withheld
    #: from delivery — which is why the count can run far ahead of the emails.
    occurrences: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default=text("1"))
    #: Did this episode leave the building. False on every `attention` and `record` row by
    #: construction, and on a `page` row whose transport failed.
    emailed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    emailed_at: Mapped[datetime | None] = mapped_column()
    #: When the condition went quiet for `ALERT_CLEAR_AFTER_S` and `sweep_alert_clears`
    #: closed the episode. NULL means "still happening", which is what the console's
    #: "Open" filter reads and what the partial unique index above keys on.
    cleared_at: Mapped[datetime | None] = mapped_column()


__all__ = [
    "DEFAULT_MAX_DRAIN_MINUTES",
    "FX_RATE",
    "MAINTENANCE_OPEN_STATES",
    "MAINTENANCE_STATES",
    "USD_PER_MTOK",
    "FxRateObservation",
    "PlatformAlert",
    "PlatformConfigVersion",
    "PlatformDashboardDataUse",
    "PlatformEngineHealth",
    "PlatformMaintenanceWindow",
    "PlatformModelPrice",
    "PlatformSecret",
    "PlatformSetting",
]
