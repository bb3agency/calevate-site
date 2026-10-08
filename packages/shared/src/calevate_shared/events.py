"""OUR normalized call models (TRD §5).

Everything outside `engine/` consumes these, never a vendor payload shape. Raw
vendor payloads are archived to object storage and referenced by
`engine_payload_ref` — they are never read by app code. Never read is not the same
as never personal: the archived document carries the caller's number and the
transcript, so its key names the tenant and the call and a DPDP erasure deletes it
(D-126, `apps/workers/storage.payload_key`).
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


EngineNoticeKind = Literal["lead_captured", "conversation_escalated"]


class EngineNotice(BaseModel):
    """Something the ENGINE's own agent did during a conversation that is not a call
    lifecycle step: it took down a lead, or it handed the conversation to a person.

    Ids only. The vendor's description of the lead (a name, a number) is never carried:
    our own extraction pass over the transcript is the record of what was said, and this
    notice only tells the receiver that the engine acted, so it can be routed and counted.
    `tenant_id`/`agent_id` are resolved from `engine_agent_ref` by the receiver, as on
    `CallEvent`.
    """

    kind: EngineNoticeKind
    #: The engine's id for the delivery, stable across its retries; the inbox dedupe key.
    notice_id: str
    engine_agent_ref: str | None = None
    #: The call it happened on, when the engine names one (a chat has none).
    engine_call_id: str | None = None
    occurred_at: datetime | None = None
    tenant_id: UUID | None = None
    agent_id: UUID | None = None
    engine: str


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
    "EngineNotice",
    "EngineNoticeKind",
    "Speaker",
    "TranscriptTurn",
]
