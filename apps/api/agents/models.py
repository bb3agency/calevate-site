"""Agents & configuration (DATA-MODEL §3).

Circular FKs (agents.system_prompt_id → prompt_versions, prompt_versions.agent_id →
agents) use use_alter so Alembic emits them as separate ALTERs after both tables exist.
"""

from datetime import datetime
from typing import Any, Literal, get_args
from uuid import UUID

from calevate_shared.config import SELECTABLE_ENGINES
from calevate_shared.engine import LLM_MODEL_NAMES
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: WHICH WAY AN AGENT'S CALLS GO, as a type rather than as three strings.
#:
#: This existed only as the tuple below, so every value read out of the `direction` column
#: was a `str` to the type checker while `AgentConfig.direction` is
#: `Literal["inbound", "outbound", "both"]` — and `agents/service.py::_to_config` passed
#: one straight into the other. Nothing checked it: not mypy (the value was `str`, and
#: until `[tool.pydantic-mypy] init_typed = true` the model's synthesised `__init__` took
#: `Any` anyway), not Pydantic on the way out. A `direction` this table's CHECK constraint
#: somehow let through would have reached the engine payload unexamined.
#:
#: Derived, never retyped (D-104), and in this direction rather than the other: the
#: LITERAL is the source and `get_args` renders the tuple, because a tuple cannot be
#: turned back into a type. `ck_agents_direction_enum` is rendered from the tuple, so the
#: constraint and the type cannot disagree — adding a fourth direction to the Literal
#: changes the CHECK in the same edit or it changes neither.
AgentDirection = Literal["inbound", "outbound", "both"]
AGENT_DIRECTIONS: tuple[AgentDirection, ...] = get_args(AgentDirection)

#: WHERE AN AGENT IS IN ITS LIFE, as a type, for the reason `AgentDirection` above is one:
#: this vocabulary is compared against, stored, filtered on and returned to a browser, and
#: it spent its whole life as a bare tuple of strings that nothing could check.
#:
#: THE FOUR WORDS, and why they are these words. `draft`/`live`/`paused` are what the
#: column has always held and what every gate in the tree already reads —
#: `compliance/service.check_dispatch` refuses `status <> 'live'` per contact,
#: `campaigns/service.launch_blockers` per launch, `agents/prompts.py` branches on it to
#: decide whether an edit needs an explicit apply. `archived` (migration e4b90d27c1f6) is
#: the fourth, and it is the one the product was missing: a way to take an agent off the
#: roster for good WITHOUT reaching for `deleted_at`, which means "this client's data was
#: erased" and takes the agent's own call history off every screen with it.
#:
#: THE PRODUCT SAYS "ACTIVE" AND "INACTIVE" AND THIS COLUMN DOES NOT, deliberately. Those
#: are labels on a screen — the same class of change as calling a voice agent an "agent" —
#: and renaming the stored values would rewrite a vocabulary that ten modules and thirty
#: test files compare against, to buy nothing a `<span>` cannot. `live` IS active and
#: `paused` IS inactive; the mapping lives in the API description and in the UI, and the
#: wire value stays the one the database holds so there is exactly one vocabulary.
AgentStatus = Literal["draft", "live", "paused", "archived"]
#: Derived from the Literal, never retyped (D-104): this tuple renders
#: `ck_agents_status_enum`, so a fifth status changes the CHECK in the same edit or it
#: changes neither.
AGENT_STATUSES: tuple[AgentStatus, ...] = get_args(AgentStatus)

#: Derived, never retyped (D-104). This WAS `("fake", "bolna")`, spelled here by hand, and
#: it is the copy that had teeth: it renders `ck_agents_engine_enum`, and
#: `agents/lifecycle.py::create_agent` writes `get_settings().engine` into that column
#: on every agent, the tenant's first included. So on a deployment running
#: `ENGINE=cartesia` — a value
#: `config.EngineName` accepts and the whole adapter exists for — the first thing a new
#: client does, exist, failed with an IntegrityError out of Postgres rather than with a
#: refusal anyone authored. `tests/engine_name_drift_test.py` fails on a fourth spelling.
#:
#: Sorted so the rendered CHECK is stable: an unordered frozenset would produce a
#: different constraint text per interpreter run, and `alembic revision --autogenerate`
#: would offer a spurious diff on every invocation.
#:
#: ThinnestAI is absent because D-31 retired it — do not re-add. It cannot come back by
#: accident now: it would have to be added to `EngineName`, where the decision is cited.
ENGINES = tuple(sorted(SELECTABLE_ENGINES))
NUMBER_SERIES = ("140", "160", "standard")
DLT_STATUSES = ("pending", "registered", "blocked")

#: The India country code, and the two regulated national prefixes the series names.
#:
#: VERIFIED THIS SESSION against the Department of Telecommunications' own press release
#: (PIB PRID 2022249, "DoT allots separate numbering series exclusively for service and
#: transactional voice calls", read 27 Aug 2026): service/transactional calls originate
#: from **160xxxxxxx**, and "calls from telemarketers for transactional or promotional
#: calls would start from 140xxxxxxx". A "series" in Indian numbering IS the leading
#: digits of the ten-digit national number, which is what makes the check below possible
#: at all. Corroborated by `docs/legal/phone-number-research.md:23`, which quotes DoT's
#: May-2024 release to the same effect and records the penalty ladder (₹2/₹5/₹10 lakh
#: under the 2025 TCCCPR amendments) that makes misclassification expensive.
_INDIA_CC = "+91"
_REGULATED_PREFIXES: dict[str, str] = {"140": "140", "160": "160"}


def series_for_e164(e164: str) -> str | None:
    """Which `NUMBER_SERIES` this number's own prefix declares — or None if it says.

    Returns None ONLY for a number outside the Indian country code, where the 140/160
    series do not exist as a concept and no Indian prefix rule can classify the number.
    Every `+91` number gets an answer: `140`, `160`, or `standard` (i.e. "an ordinary
    number, not a regulated series").

    WHY THIS IS A FACT AND NOT A PREFERENCE. `phone_numbers.series` is what the campaign
    launch gate matches against the campaign's classification
    (`campaigns.service.SERIES_FOR_CLASSIFICATION`: 140 dials promotions, 160/standard
    dials service and transactional), so it decides whether a promotional campaign may
    run — and it was an operator's typed word, never checked against the number sitting
    in the same INSERT. A `+91 98…` mobile typed `"140"` opened promotional dialling from
    a number that is not a telemarketing header, and a real 140 number typed
    `"standard"` opened service/transactional dialling from one that is. The prefix was
    in the row the whole time.
    """
    if not e164.startswith(_INDIA_CC):
        return None
    national = e164[len(_INDIA_CC) :]
    return _REGULATED_PREFIXES.get(national[:3], "standard")


# The cost-runaway guard (SURFACES §2b:107). NULL on the column means "the platform
# default", never "unlimited" — `agents/service.py::effective_call_cap` resolves it.
CALL_CAP_DEFAULT_S = 600
# 60s floor: a cap a real conversation cannot satisfy is not thrift, it is an agent
# that hangs up on everyone while still billing the connected minute. 3600s ceiling:
# past an hour the guard has stopped guarding. Mirrored by `ck_agents_max_call_
# duration_range` in migration a4e7b2c95d18 (DATA-MODEL §10).
CALL_CAP_MIN_S = 60
CALL_CAP_MAX_S = 3600


class Agent(PKMixin, TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(f"direction IN {AGENT_DIRECTIONS!r}", name="direction_enum"),
        CheckConstraint(f"status IN {AGENT_STATUSES!r}", name="status_enum"),
        # `archived` and `archived_at` are two spellings of one fact (migration
        # e4b90d27c1f6), so the constraint is an EQUIVALENCE rather than an implication:
        # neither an archived agent with no timestamp nor a live one carrying a stale
        # archival date is representable, and the restore path clears the column in the
        # same statement that moves the status.
        CheckConstraint(
            "(status = 'archived') = (archived_at IS NOT NULL)",
            name="ck_agents_archived_at_matches_status",
        ),
        CheckConstraint(f"engine IN {ENGINES!r}", name="engine_enum"),
        # THIS AGENT'S OWN language-model choice — the top rung of
        # `agent -> organization -> platform` (`agents/llm_models.py`, migrations
        # b7d2f10c93ae then d3a7c81f45be). DERIVED from `LLM_MODEL_NAMES`, never retyped
        # (D-104), and sorted so the rendered SQL is byte-stable.
        #
        # **THE WHOLE CATALOGUE, NOT THE SELECTABLE SET**, and d3a7c81f45be's docstring
        # argues it in full: a CHECK is a FLOOR against values no writer should ever produce
        # — a restore that lands without constraints, a hand-run UPDATE during an incident —
        # and it is not the product's policy surface. Which models may actually be CHOSEN
        # depends on a live credential and a live price attestation, facts a CHECK cannot
        # see; `agents/llm_models.offerable_models()` is where that is decided, and
        # `validate_llm_model` and `in_call_llm` each refuse again.
        #
        # THE COLUMN HAD A READER AND NO CONSTRAINT FOR ITS WHOLE LIFE, which is what this
        # closes: `agents/service.py::in_call_llm` reads it, and on a leg that is not
        # Azure it goes to the engine verbatim — so a value outside the allow-list is a
        # 404 from a third party mid-sentence on a client's live phone call, the failure
        # class `SARVAM_RETIRED_LLMS` already exists for. NULL is admitted explicitly: it
        # is the "inherit the account default" sentinel.
        CheckConstraint(
            f"llm_model IS NULL OR llm_model IN {tuple(sorted(LLM_MODEL_NAMES))!r}",
            name="llm_model_allowed",
        ),
        # LEGACY, and kept deliberately: the bundled line, step 1 of a two-step
        # deprecation (hard rule 8, D-163). Still written by every writer of the four
        # columns below (`compliance/disclosure.bundled_disclosure_line`), so the
        # constraint still holds and no reader that has not migrated sees a NULL.
        CheckConstraint("length(disclosure_line) > 0", name="disclosure_nonempty"),
        # Hard rule 5 AFTER D-163: the AI sentence must EXIST on every agent — the
        # compliance gate reads it, and the honest answer to "are you an AI?" is
        # meaningless without one. Whether it is VOLUNTEERED is
        # `ai_disclosure_enabled`, which is a tenant's choice and not a constraint.
        CheckConstraint(
            "length(btrim(ai_disclosure_line)) > 0", name="ck_agents_ai_disclosure_nonempty"
        ),
        CheckConstraint(
            "length(btrim(recording_notice_line)) > 0",
            name="ck_agents_recording_notice_nonempty",
        ),
        # The cost-runaway guard's range. NULL is admitted EXPLICITLY (it is the "use
        # the platform default" sentinel), not by the accident that a NULL-returning
        # CHECK passes. Migration a4e7b2c95d18.
        CheckConstraint(
            f"max_call_duration_s IS NULL OR (max_call_duration_s >= {CALL_CAP_MIN_S} "
            f"AND max_call_duration_s <= {CALL_CAP_MAX_S})",
            name="ck_agents_max_call_duration_range",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    direction: Mapped[str] = mapped_column(String, nullable=False)
    language_primary: Mapped[str] = mapped_column(Text, nullable=False, server_default="te-IN")
    languages_extra: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    # Model choices are plain config strings (D-04/D-20): changing one is a config
    # edit + regression run, never a code change.
    stt_provider: Mapped[str | None] = mapped_column(Text)
    stt_model: Mapped[str | None] = mapped_column(Text)
    tts_provider: Mapped[str | None] = mapped_column(Text)
    tts_voice: Mapped[str | None] = mapped_column(Text)
    # THIS AGENT'S language-model choice, or NULL to inherit
    # `organizations.default_llm_model` and then the platform's
    # (`agents/llm_models.resolve_llm_model`). Bounded by
    # `ck_agents_llm_model_allowed` above.
    llm_model: Mapped[str | None] = mapped_column(Text)
    # THE SENT VOICE: what `publish_agent` last handed the engine, as opposed to
    # `tts_voice`, which is what an operator CONFIGURED (migration c8b3f14e7a29). The
    # two are allowed to differ — `voice_routes.set_agent_voice` writes the row and
    # deliberately does not touch the engine — so one column could not hold both
    # answers, exactly as `system_prompt_id`/`live_prompt_id` above. The divergence IS
    # `live_tts_voice IS DISTINCT FROM tts_voice`: derived, so it cannot drift the way
    # a `voice_dirty` flag would. NULL = nothing recorded as sent (never published, or
    # published before this column existed); `published` disambiguates the two, and
    # both read as "we cannot prove the engine holds the configured voice".
    #
    # The provider is mirrored alongside because the pair is only meaningful together:
    # the adapter sends `synthesizer.provider` and `synthesizer.provider_config.voice`
    # as one object (engine/bolna.py), and a mirror of half of it can lie about the
    # other half.
    live_tts_voice: Mapped[str | None] = mapped_column(Text)
    live_tts_provider: Mapped[str | None] = mapped_column(Text)
    # WHAT A READ-BACK CONFIRMED, as opposed to what we sent (migration c1f6a94d2b07).
    # `live_prompt_id` and `live_tts_voice` above record the config `publish_agent`
    # HANDED the engine on the strength of a 2xx; these two record what
    # `VoiceEngine.get_agent` was afterwards observed to be holding. One of the four
    # values in `agents/verification.py::StoredVerifyState`, guarded by a CHECK.
    # `not_applied` is not among them on purpose: a proven mismatch is a refusal, so no
    # row ever commits it.
    live_verify_state: Mapped[str] = mapped_column(
        Text, nullable=False, server_default="unverified"
    )
    # Set only under `applied`. A timestamp of EVIDENCE — stamping one for a verdict that
    # proved nothing would let a screen render "confirmed" over an unread answer.
    live_verified_at: Mapped[datetime | None]
    # THE DRAFT POINTER: the script the client is editing.
    system_prompt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", use_alter=True, ondelete="SET NULL")
    )
    # THE APPLIED POINTER: the script the engine is actually running (SURFACES §2b's
    # two-speed publishing, migration a4e7b2c95d18). One column could not hold both
    # answers once they are allowed to differ, which is why "Apply to live calls" had
    # nowhere to live. `system_prompt_id IS DISTINCT FROM live_prompt_id` IS the
    # pending state — derived, so it cannot drift the way a boolean flag would.
    live_prompt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", use_alter=True, ondelete="SET NULL")
    )
    extraction_schema_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extraction_schemas.id", use_alter=True, ondelete="SET NULL")
    )
    # NULL = the platform default (CALL_CAP_DEFAULT_S), NEVER unlimited. There is no
    # value of this column, and no absence of one, that publishes an uncapped agent.
    max_call_duration_s: Mapped[int | None] = mapped_column(Integer)
    business_hours: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    escalation_config: Mapped[dict[str, object] | None] = mapped_column(JSONB)
    # THE PER-AGENT MASTER SWITCH for in-call Actions/tools (migration
    # e1f7a3c920b4). Default FALSE: an agent nobody configured actions for makes no
    # mid-call external calls. Read by `actions/service.actions_enabled` and written
    # by the Actions tab's master-switch route; the adapter only ships `api_tools`
    # when this is on. Server-default keeps a row created outside this path safe.
    api_actions_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    # THE LEGACY BUNDLE (migration f4a1d0b6e29c, D-163). Both notices joined, whatever
    # the toggles say — see `compliance/disclosure.bundled_disclosure_line` for why it
    # deliberately does NOT track what is spoken. Written, no longer read by the publish
    # path. Step 2 of the two-step is a `drop` in a later release (hard rule 8).
    disclosure_line: Mapped[str] = mapped_column(Text, nullable=False)
    # THE SPLIT (D-163). SEC-COMP §2 has always stated two invariants — "the caller is
    # told this is an AI" (TRAI/UCC) and "the caller is told the call is recorded" (DPDP
    # notice-and-consent) — and they shared the one column above, so a client could only
    # ever have both or neither. Two regimes, two obligations, two columns, two toggles.
    #
    # THE TEXT IS MANDATORY AND THE TOGGLE IS NOT, and the asymmetry is the design. The
    # sentence must exist because `compliance/service.check_dispatch` refuses an agent
    # with no AI disclosure ON FILE and because the truthful answer needs something to
    # say; whether it is VOLUNTEERED unprompted is the tenant's call to make, and theirs
    # to answer for as the Principal Entity.
    ai_disclosure_line: Mapped[str] = mapped_column(Text, nullable=False)
    recording_notice_line: Mapped[str] = mapped_column(Text, nullable=False)
    # Default TRUE on both: an agent nobody has decided about discloses. A default of
    # false would make an omission — a forgotten column in an INSERT, a row created by a
    # future importer — silently produce the posture with the legal exposure.
    ai_disclosure_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    recording_notice_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
    engine: Mapped[str] = mapped_column(String, nullable=False, server_default="fake")
    engine_agent_ref: Mapped[str | None] = mapped_column(Text)
    engine_staging_ref: Mapped[str | None] = mapped_column(Text)
    # WHEN THE CLIENT RETIRED THIS AGENT (migration e4b90d27c1f6). NOT `deleted_at`, which
    # is the erasure column the DPDP deletion path writes: archiving keeps every row and
    # every screen, it only takes the agent off the working roster. `updated_at` could not
    # order the history list — a republish, a voice change or a disclosure toggle moves it.
    archived_at: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]


class PromptVersion(PKMixin, TimestampMixin, Base):
    """Full history + rollback; published versions mirrored to git by CI (PROMPT-GUIDE §6)."""

    __tablename__ = "prompt_versions"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # No `index=True`: UNIQUE(agent_id, version) leads with `agent_id`, and at the
    # version counts this table reaches no query in the repo named the single-column
    # index even before it was dropped (b9e5d2c74a18).
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # The authored STRUCTURED form (`calevate_shared.call_script.CallScript`) this version's
    # `body` was compiled from — opening line, ordered steps, FAQ, end-call rules, merge
    # variables. NULL means the version was authored as freeform text (everything written
    # before the structured builder existed); the builder represents that losslessly with
    # `CallScript.from_freeform(body)`. Stamped at INSERT beside `body`, never updated
    # (append-only). Migration c7e2b4f019ad.
    structured_script: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    compiled_t0_context: Mapped[str | None] = mapped_column(Text)
    # Operator-facing: why this version exists ("rollback to v3", "new pricing").
    # NOT compiled_t0_context — that is a build artifact OF the version, reserved by
    # D-39 for the T0 compiler (migration 2faa301dc488 split them).
    notes: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    published_at: Mapped[datetime | None]


EXPERIMENT_STATUSES = ("running", "concluded")

# Exactly two arms. Not a limitation we ran out of time for — a third arm needs a
# multiplicity correction (the family-wise error rate of three pairwise 95% intervals is
# not 5%), and `agents/proportions.py` implements none. Two labels, fixed, so the shape
# of the comparison is a property of the schema rather than of the reader's memory.
VARIANT_LABELS = ("A", "B")

# Traffic split in basis points, so a 50/50 is 5000/5000 and an INTEGER column can hold
# a 2.5% ramp. The two variants of an experiment must sum to 10000 — enforced by
# `agents/experiments.py` on the only path that writes them, because a CHECK cannot see
# its sibling row.
SPLIT_TOTAL_BP = 10_000
# A ramp below 5% cannot reach `MIN_CALLS_PER_VARIANT` in any campaign this platform
# dials, so an experiment configured that way is one that can only ever report "not
# enough data" — a control that looks like it is running and can never conclude.
SPLIT_MIN_BP = 500

# What "converted" means, as SQL over the assigned call. Two definitions because the
# verticals genuinely measure different things — a receptionist resolves a call, a sales
# agent produces a lead somebody eventually wins — and hardcoding one would be wrong for
# half the clients. Two is the whole list: this mapping IS the enum, so a metric with no
# predicate cannot be stored, and the CHECK constraint in migration b3c8f27d41ae repeats
# the same two names against the database.
CONVERSION_METRICS: dict[str, str] = {
    # The post-call pipeline's own verdict on the conversation (workers/extraction.py
    # writes `calls.outcome_tag`).
    "call_outcome_resolved": "c.outcome_tag = 'resolved'",
    # The commercial outcome: the lead this call belongs to was eventually won. Lags the
    # call by however long the client's sales cycle takes, which is why it is not the
    # default — an experiment read too early on this metric shows two zeroes.
    "lead_won": "EXISTS (SELECT 1 FROM leads l WHERE l.id = c.lead_id AND l.status = 'won')",
}
DEFAULT_CONVERSION_METRIC = "call_outcome_resolved"


class PromptExperiment(PKMixin, TimestampMixin, Base):
    """One A/B script test on one agent (ROADMAP M3).

    At most ONE may be running per agent at a time — a partial unique index in the
    migration, not a code check, because two overlapping experiments would each attribute
    the same calls and neither result would mean anything.
    """

    __tablename__ = "prompt_experiments"
    __table_args__ = (
        CheckConstraint(f"status IN {EXPERIMENT_STATUSES!r}", name="ck_prompt_experiments_status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="running")
    conversion_metric: Mapped[str] = mapped_column(String, nullable=False)
    started_at: Mapped[datetime] = mapped_column(nullable=False)
    concluded_at: Mapped[datetime | None]
    # Which arm the operator promoted, or NULL for an experiment that was stopped
    # without promoting either. NULL is a real answer here — "we learned nothing and
    # kept the control" is the commonest honest ending of an A/B test.
    promoted_variant_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_experiment_variants.id", use_alter=True, ondelete="SET NULL")
    )


class PromptExperimentVariant(PKMixin, TimestampMixin, Base):
    """One arm: an EXISTING immutable prompt version, its disclosure line, its share of
    traffic, and the engine agent that actually speaks it.

    The body is not copied here. A variant names a `prompt_versions` row, so the script
    an experiment ran stays readable in the same history a rollback reads, and there is
    exactly one place a prompt body lives (`agents/prompts.py`'s immutability promise).

    `disclosure_line` IS copied, and is NOT NULL with a non-empty CHECK, because hard
    rule 5 says an agent always has one and a variant is what the caller actually hears.
    A variant whose disclosure could be absent would be a way to publish an undisclosed
    agent through a feature flag.
    """

    __tablename__ = "prompt_experiment_variants"
    __table_args__ = (
        UniqueConstraint("experiment_id", "label", name="uq_prompt_experiment_variants_label"),
        CheckConstraint(f"label IN {VARIANT_LABELS!r}", name="ck_prompt_experiment_variants_label"),
        CheckConstraint(
            f"weight_bp BETWEEN {SPLIT_MIN_BP} AND {SPLIT_TOTAL_BP - SPLIT_MIN_BP}",
            name="ck_prompt_experiment_variants_weight_range",
        ),
        # Hard rule 5, at the schema, in the same shape `agents.disclosure_nonempty` has.
        CheckConstraint(
            "length(btrim(disclosure_line)) > 0",
            name="ck_prompt_experiment_variants_disclosure_nonempty",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    experiment_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_experiments.id", ondelete="CASCADE"), nullable=False
    )
    label: Mapped[str] = mapped_column(String, nullable=False)
    prompt_version_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_versions.id", ondelete="RESTRICT"), nullable=False
    )
    disclosure_line: Mapped[str] = mapped_column(Text, nullable=False)
    weight_bp: Mapped[int] = mapped_column(Integer, nullable=False)
    # The engine's own agent for this arm. Two arms means two engine agents, because the
    # vendor contract carries the script ON the agent (`AgentConfig.system_prompt`) and
    # `start_outbound_call` takes only a ref — there is no per-call prompt override to
    # reach for. NULL until the arm is published.
    engine_agent_ref: Mapped[str | None] = mapped_column(Text)


class CallVariantAssignment(PKMixin, TimestampMixin, Base):
    """WHICH ARM THIS CALL GOT. The fact, recorded once, at the moment the call is made.

    This row is the entire reason the attribution can be trusted. The alternative —
    recomputing the bucket at read time from the call's phone number and the experiment's
    split — gives a DIFFERENT answer the moment anybody ramps the split, silently
    reassigning calls that already happened to the arm they never ran. Assignment is
    deterministic so it can be reproduced; it is stored because a reproduction is not
    evidence.

    UNIQUE on `call_id`: one call, one arm, forever. No UPDATE path exists in this
    codebase and none should be added — a correction is a data question for an operator,
    not a code path.
    """

    __tablename__ = "call_variant_assignments"
    __table_args__ = (UniqueConstraint("call_id", name="uq_call_variant_assignments_call_id"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    call_id: Mapped[UUID] = mapped_column(
        ForeignKey("calls.id", ondelete="CASCADE"), nullable=False
    )
    experiment_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_experiments.id", ondelete="RESTRICT"), nullable=False
    )
    variant_id: Mapped[UUID] = mapped_column(
        ForeignKey("prompt_experiment_variants.id", ondelete="RESTRICT"), nullable=False
    )


class ExtractionSchema(PKMixin, TimestampMixin, Base):
    """fields JSONB validated by Pydantic on write (DATA-MODEL §3 shape).
    Changing a schema creates a NEW version; leads render by the version active at
    extraction time (no data loss)."""

    __tablename__ = "extraction_schemas"
    __table_args__ = (UniqueConstraint("agent_id", "version"),)

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    # No `index=True`: UNIQUE(agent_id, version) leads with `agent_id` (b9e5d2c74a18).
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    fields: Mapped[list[object]] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime | None]


class PhoneNumber(PKMixin, TimestampMixin, Base):
    __tablename__ = "phone_numbers"
    __table_args__ = (
        CheckConstraint(f"series IN {NUMBER_SERIES!r}", name="series_enum"),
        CheckConstraint(f"dlt_status IN {DLT_STATUSES!r}", name="dlt_status_enum"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    e164: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    series: Mapped[str] = mapped_column(String, nullable=False, server_default="standard")
    provider: Mapped[str | None] = mapped_column(Text)
    engine_number_ref: Mapped[str | None] = mapped_column(Text)
    dlt_status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    purpose: Mapped[str | None] = mapped_column(Text)
