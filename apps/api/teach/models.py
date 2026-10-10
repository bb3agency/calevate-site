"""Tables for teaching and the improvement loop. All tenant-scoped with FORCEd RLS (migration
`a8d3f6c1e924`, hard rule 1)."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: Where a fact came from. `quick_fact` is an agent's old script FAQ moved into knowledge
#: (founder decision 9); `call_gap` is an answer taught from a call where an agent struggled.
FACT_ORIGINS = ("taught", "quick_fact", "call_gap")
MAX_FACT_CHARS = 500
#: A pinned fact's answer may be as long as an old quick-fact answer (`FaqEntry.answer`),
#: so the move into knowledge loses nothing.
MAX_PINNED_ANSWER_CHARS = 2000
MAX_PINNED_QUESTION_CHARS = 500

TEACH_INPUT_KINDS = ("text", "photo", "file", "voice")
#: `heard` is a voice note transcribed and waiting for the owner to confirm the words.
TEACH_STATUSES = (
    "queued",
    "reading",
    "heard",
    "sorting",
    "ready",
    "saved",
    "discarded",
    "failed",
)
MAX_TEACH_WORDS = 8000

RULE_STATUSES = ("pending", "applied", "dismissed")
MAX_RULE_CHARS = 500

TEST_CASE_STATUSES = ("idle", "queued", "running")
MAX_CASE_LINES = 6
MAX_CASE_LINE_CHARS = 500
MAX_CASE_EXPECTED_CHARS = 600


class KbFact(PKMixin, TimestampMixin, Base):
    """One fact about the business, shared by every agent (D-689).

    An UNPINNED fact is compiled with the others into ONE knowledge source
    (`teach/facts.FACTS_SOURCE_NAME`), which the agents search. A PINNED fact is a quick fact
    (founder decision 9): it is spliced into every agent's instructions, so it always
    reaches the agent and wins over anything searched (`teach/pinned.py`). It may carry the
    caller's `question`; `position` orders the pinned list. `removed_at` keeps a removed
    fact's row so the audit trail can name what was taken out."""

    __tablename__ = "kb_facts"
    __table_args__ = (
        CheckConstraint(f"origin IN {FACT_ORIGINS!r}", name="origin_enum"),
        CheckConstraint(
            f"char_length(text) BETWEEN 1 AND {MAX_PINNED_ANSWER_CHARS}", name="text_length"
        ),
        CheckConstraint(
            f"question IS NULL OR char_length(question) <= {MAX_PINNED_QUESTION_CHARS}",
            name="question_length",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    question: Mapped[str | None] = mapped_column(Text)
    position: Mapped[int | None] = mapped_column(Integer)
    pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="taught")
    teaching_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("kb_teachings.id", ondelete="SET NULL")
    )
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    removed_at: Mapped[datetime | None]


class KbTeaching(PKMixin, TimestampMixin, Base):
    """One use of the teach box: what was given, and the facts and rules the AI proposed
    for the owner to review. Holds the owner's own words about their business, never a
    caller's."""

    __tablename__ = "kb_teachings"
    __table_args__ = (
        CheckConstraint(f"input_kind IN {TEACH_INPUT_KINDS!r}", name="input_kind_enum"),
        CheckConstraint(f"status IN {TEACH_STATUSES!r}", name="status_enum"),
        CheckConstraint("items IS NULL OR jsonb_typeof(items) = 'array'", name="items_is_array"),
        CheckConstraint(
            f"words IS NULL OR char_length(words) <= {MAX_TEACH_WORDS}", name="words_length"
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    #: The agent whose script receives the rules; chosen when the review is saved.
    agent_id: Mapped[UUID | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    #: The struggle this teaching answers, when it was opened from one.
    gap_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("knowledge_gaps.id", ondelete="SET NULL")
    )
    input_kind: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="queued")
    words: Mapped[str | None] = mapped_column(Text)
    object_key: Mapped[str | None] = mapped_column(Text)
    content_type: Mapped[str | None] = mapped_column(Text)
    filename: Mapped[str | None] = mapped_column(Text)
    items: Mapped[list[Any] | None] = mapped_column(JSONB)
    #: The fallback sentence the client must see when another model answered (D-127 G-6).
    disclosure: Mapped[str | None] = mapped_column(Text)
    #: A machine code when `failed`; never vendor text.
    error_code: Mapped[str | None] = mapped_column(Text)
    requested_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    completed_at: Mapped[datetime | None]


class AgentRuleProposal(PKMixin, TimestampMixin, Base):
    """A rule the owner taught for one agent, waiting to be written into its script as an
    'anytime' rule. The script builder lists the pending ones and marks each applied or
    dismissed."""

    __tablename__ = "agent_rule_proposals"
    __table_args__ = (
        CheckConstraint(f"status IN {RULE_STATUSES!r}", name="status_enum"),
        CheckConstraint(f"char_length(text) BETWEEN 1 AND {MAX_RULE_CHARS}", name="text_length"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    teaching_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("kb_teachings.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    resolved_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    resolved_at: Mapped[datetime | None]


class AgentTestCase(PKMixin, TimestampMixin, Base):
    """A saved test for one agent: caller lines (usually taken from a real call, redacted and
    edited by the owner) and the behaviour the owner expects. Re-run against the LIVE agent
    through the engine's test chat; the last answers are kept on the row."""

    __tablename__ = "agent_test_cases"
    __table_args__ = (
        CheckConstraint(f"status IN {TEST_CASE_STATUSES!r}", name="status_enum"),
        CheckConstraint(
            "jsonb_typeof(caller_lines) = 'array' "
            f"AND jsonb_array_length(caller_lines) BETWEEN 1 AND {MAX_CASE_LINES}",
            name="caller_lines_shape",
        ),
        CheckConstraint(
            "last_result IS NULL OR jsonb_typeof(last_result) = 'array'",
            name="last_result_is_array",
        ),
        CheckConstraint(
            f"char_length(expected) BETWEEN 1 AND {MAX_CASE_EXPECTED_CHARS}",
            name="expected_length",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agents.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_call_id: Mapped[UUID | None] = mapped_column(ForeignKey("calls.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    caller_lines: Mapped[list[Any]] = mapped_column(JSONB, nullable=False)
    expected: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="idle")
    last_result: Mapped[list[Any] | None] = mapped_column(JSONB)
    #: A machine code when the last run failed; never vendor text.
    last_error: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None]
    last_prompt_version: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))


__all__ = [
    "FACT_ORIGINS",
    "MAX_CASE_EXPECTED_CHARS",
    "MAX_CASE_LINES",
    "MAX_CASE_LINE_CHARS",
    "MAX_FACT_CHARS",
    "MAX_PINNED_ANSWER_CHARS",
    "MAX_PINNED_QUESTION_CHARS",
    "MAX_RULE_CHARS",
    "MAX_TEACH_WORDS",
    "RULE_STATUSES",
    "TEACH_INPUT_KINDS",
    "TEACH_STATUSES",
    "TEST_CASE_STATUSES",
    "AgentRuleProposal",
    "AgentTestCase",
    "KbFact",
    "KbTeaching",
]
