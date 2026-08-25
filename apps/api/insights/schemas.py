"""Wire shapes for the Knowledge Gaps surface (client realm).

Every quote field carries REDACTED text — the columns behind them only ever hold redacted
text (hard rule 6) — so there is no raw-transcript concern on this surface at all: unlike
`/v1/calls/{id}`, nothing here is gated on `calls:read_raw` because nothing here can return
raw PII.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

GapStatus = Literal["open", "taught", "dismissed"]
GapSignal = Literal["dont_know", "deferred_channel", "unanswered_question"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class KnowledgeGapOut(Strict):
    """One rolled-up gap for the card. `occurrence_count`/`call_count` are the "Nx on M
    calls"; `signal` drives the "DIDN'T KNOW THIS"-style badge wording."""

    id: UUID
    agent_id: UUID
    #: The agent's display name, joined in for the dashboard-home card where gaps from
    #: several agents sit together. Absent when the agent row is gone.
    agent_name: str | None = None
    topic_key: str
    topic_label: str
    status: GapStatus
    signal: GapSignal
    occurrence_count: int
    call_count: int
    example_question: str
    example_answer: str
    first_seen_at: datetime
    last_seen_at: datetime
    resolution: str | None = None
    #: Who acted on the gap and when, and the KB draft a "teach" seeded (if any) so the
    #: screen can link to it. Ids only (hard rule 6); all null while the gap is open.
    resolved_by: UUID | None = None
    resolved_at: datetime | None = None
    kb_source_id: UUID | None = None


class KnowledgeGapListOut(Strict):
    """The urgent surface. `open_count` is what the nav badge and "N things need
    attention" sentence read; `items` is the page, open gaps first (see
    `service.list_gaps` for the ordering)."""

    items: list[KnowledgeGapOut]
    #: How many OPEN gaps exist for this scope, cap or no cap — the urgent number.
    open_count: int
    #: Every gap the scope matches, whatever its status. `total >= len(items)` on a busy
    #: account, the same honesty `AttentionOut` keeps between its count and its page.
    total: int


class GapDismissIn(Strict):
    """Dismiss a gap. An optional note the client leaves for their own audit trail."""

    reason: str | None = Field(default=None, max_length=2000)


class GapTeachIn(Strict):
    """Teach the answer to a gap. `answer` is the fact the agent was missing; when
    `create_kb_draft` is set the service seeds a KB draft from it (see `service.teach_gap`)."""

    answer: str = Field(min_length=1, max_length=8000)
    create_kb_draft: bool = True


__all__ = [
    "GapDismissIn",
    "GapSignal",
    "GapStatus",
    "GapTeachIn",
    "KnowledgeGapListOut",
    "KnowledgeGapOut",
]
