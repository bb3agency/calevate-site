"""OUR normalized call models (TRD §5).

Everything outside `engine/` consumes these, never a vendor payload shape. Raw
vendor payloads are archived to object storage and referenced by
`engine_payload_ref` — they are never read by app code.
"""

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


class CallEvent(BaseModel):
    """A normalized call lifecycle event, parsed from any engine's webhook."""

    call_id: str
    tenant_id: UUID
    agent_id: UUID
    direction: CallDirection
    status: CallStatus
    started_at: datetime | None = None
    ended_at: datetime | None = None
    from_e164: str
    to_e164: str
    recording_url: str | None = None
    cost_raw: str | None = None
    engine: str
    engine_payload_ref: str | None = None


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
    "CallDirection",
    "CallEvent",
    "CallStatus",
    "Speaker",
    "TranscriptTurn",
]
