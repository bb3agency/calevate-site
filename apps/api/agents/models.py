"""Agents & configuration (DATA-MODEL §3).

Circular FKs (agents.system_prompt_id → prompt_versions, prompt_versions.agent_id →
agents) use use_alter so Alembic emits them as separate ALTERs after both tables exist.
"""

from datetime import datetime
from uuid import UUID

from calevate_shared.config import SELECTABLE_ENGINES
from sqlalchemy import (
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

AGENT_DIRECTIONS = ("inbound", "outbound", "both")
AGENT_STATUSES = ("draft", "live", "paused")

#: Derived, never retyped (D-104). This WAS `("fake", "bolna")`, spelled here by hand, and
#: it is the copy that had teeth: it renders `ck_agents_engine_enum`, and
#: `admin/service.py::_default_engine` writes `get_settings().engine` into that column
#: when a tenant is born. So on a deployment running `ENGINE=cartesia` — a value
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
        CheckConstraint(f"engine IN {ENGINES!r}", name="engine_enum"),
        # Compliance invariant (hard rule 5): agents ALWAYS have a disclosure line.
        CheckConstraint("length(disclosure_line) > 0", name="disclosure_nonempty"),
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
    disclosure_line: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="draft")
    engine: Mapped[str] = mapped_column(String, nullable=False, server_default="fake")
    engine_agent_ref: Mapped[str | None] = mapped_column(Text)
    engine_staging_ref: Mapped[str | None] = mapped_column(Text)
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
