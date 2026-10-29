"""The table behind Pip's notes (migration `e5b9d3f7a248`, D-936), declared for `Base.metadata`.

The migration is the schema of record; this file exists for `routine_models.py`'s reason:
`alembic/env.py` autogenerates against `Base.metadata`, and a column the model does not
declare is one the next `--autogenerate` proposes to drop.
"""

from __future__ import annotations

from datetime import datetime
from typing import Final
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: Every kind a detector writes (`copilot/notes.py::NoteKind`). Repeated by the CHECK.
NOTE_KINDS: Final = ("hot_lead_waiting", "balance_runway", "knowledge_gap_repeat", "good_week")
MAX_SUBJECT: Final = 64
MAX_EPISODE_KEY: Final = 96


class CopilotNote(PKMixin, TimestampMixin, Base):
    """One thing Pip noticed in an account, for one episode of it.

    `subject` names what the note is about inside its kind (`account`, a gap id, an ISO
    week). While a note is unresolved no second note of that kind and subject can open,
    which is what makes a condition that lasts three days one note and not seventy-two.
    `episode_key` (subject plus the IST day it opened) is unique for ever, so a condition
    that clears and returns on the same day is not noted twice that day.

    `payload` holds ids and counts only, never a name, number or caller's words: the line
    is composed when it is read, from the rows the ids point at.
    """

    __tablename__ = "copilot_notes"
    __table_args__ = (
        CheckConstraint(f"kind IN {NOTE_KINDS!r}", name="kind_enum"),
        CheckConstraint(f"length(subject) BETWEEN 1 AND {MAX_SUBJECT}", name="subject_length"),
        CheckConstraint(
            f"length(episode_key) BETWEEN 1 AND {MAX_EPISODE_KEY}", name="episode_key_length"
        ),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_is_object"),
        UniqueConstraint("tenant_id", "kind", "episode_key"),
        Index(
            "uq_copilot_notes_open_subject",
            "tenant_id",
            "kind",
            "subject",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
        ),
        Index("ix_copilot_notes_tenant_recent", "tenant_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    subject: Mapped[str] = mapped_column(String(MAX_SUBJECT), nullable=False)
    episode_key: Mapped[str] = mapped_column(String(MAX_EPISODE_KEY), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    seen_at: Mapped[datetime | None]
    dismissed_at: Mapped[datetime | None]
    dismissed_by: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    acted_at: Mapped[datetime | None]
    resolved_at: Mapped[datetime | None]


__all__ = ["MAX_EPISODE_KEY", "MAX_SUBJECT", "NOTE_KINDS", "CopilotNote"]
