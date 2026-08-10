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


class Agent(PKMixin, TimestampMixin, Base):
    __tablename__ = "agents"
    __table_args__ = (
        CheckConstraint(f"direction IN {AGENT_DIRECTIONS!r}", name="direction_enum"),
        CheckConstraint(f"status IN {AGENT_STATUSES!r}", name="status_enum"),
        CheckConstraint(f"engine IN {ENGINES!r}", name="engine_enum"),
        # Compliance invariant (hard rule 5): agents ALWAYS have a disclosure line.
        CheckConstraint("length(disclosure_line) > 0", name="disclosure_nonempty"),
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
    system_prompt_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("prompt_versions.id", use_alter=True, ondelete="SET NULL")
    )
    extraction_schema_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("extraction_schemas.id", use_alter=True, ondelete="SET NULL")
    )
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
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    compiled_t0_context: Mapped[str | None] = mapped_column(Text)
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
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="RESTRICT"), nullable=False, index=True
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
