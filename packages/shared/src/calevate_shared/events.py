"""OUR normalized call models (TRD §5).

Everything outside `engine/` consumes these, never a vendor payload shape. Raw
vendor payloads are archived to object storage and referenced by
`engine_payload_ref` — they are never read by app code.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

CallDirection = Literal["inbound", "outbound"]
CallStatus = Literal[
    "queued",
    "ringing",
    "in_progress",
    "completed",
    "failed",
    "no_answer",
    "busy",
    "voicemail",
]
Speaker = Literal["agent", "caller"]

# Statuses after which no further audio is expected. `completed` is the only one that
# also implies cost/recording/transcript are populated (Bolna fills them ~2-3 min after
# disconnect — TRD §5), which is why the pipeline triggers on it and not on a
# disconnect event.
TERMINAL_STATUSES: frozenset[CallStatus] = frozenset(
    {"completed", "failed", "no_answer", "busy", "voicemail"}
)


class CallEvent(BaseModel):
    """A normalized call lifecycle event, parsed from any engine's webhook.

    `tenant_id`/`agent_id` are OURS and are resolved by looking `engine_agent_ref` up
    in the agents table — a vendor payload cannot know them, and an adapter must never
    invent them. They stay None until that lookup happens.
    """

    call_id: str
    engine_agent_ref: str | None = None
    tenant_id: UUID | None = None
    agent_id: UUID | None = None
    direction: CallDirection
    status: CallStatus
    raw_status: str | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    from_e164: str | None = None
    to_e164: str | None = None
    recording_url: str | None = None
    cost_raw: str | None = None
    engine: str
    engine_payload_ref: str | None = None

    @property
    def is_terminal(self) -> bool:
        return self.status in TERMINAL_STATUSES


class TranscriptTurn(BaseModel):
    """One turn of a conversation.

    `text` is raw; `text_redacted` is what every API response returns by default
    (root CLAUDE.md hard rule 5).
    """

    call_id: str
    idx: int = Field(ge=0)
    speaker: Speaker
    text: str
    text_redacted: str | None = None
    lang: str | None = None
    start_ms: int | None = None
    end_ms: int | None = None


__all__ = [
    "TERMINAL_STATUSES",
    "CallDirection",
    "CallEvent",
    "CallStatus",
    "Speaker",
    "TranscriptTurn",
]
