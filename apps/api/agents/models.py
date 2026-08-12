"""Agents & configuration (DATA-MODEL §3).

Circular FKs (agents.system_prompt_id → prompt_versions, prompt_versions.agent_id →
agents) use use_alter so Alembic emits them as separate ALTERs after both tables exist.
"""

from datetime import datetime
from uuid import UUID

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
ENGINES = ("fake", "bolna")  # ThinnestAI retired by D-31 — do not re-add
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
