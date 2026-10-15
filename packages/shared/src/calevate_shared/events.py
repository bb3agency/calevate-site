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
from decimal import Decimal
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


class EngineOptOut(BaseModel):
    """A caller asked the engine's own agent not to be called again, and it recorded them.

    `reason` is the caller's own words when the engine kept them. It is personal data: the
    receiver redacts it before it is stored and never logs it.
    """

    #: The number as the engine wrote it; None when the delivery named none.
    phone: str | None = None
    #: The call it was heard on, when the engine names one.
    engine_call_id: str | None = None
    reason: str | None = None
    engine: str


EngineProblemKind = Literal["no_answer_from_model", "own_key_failed", "slow_reply", "voice_failed"]
#: The problems a caller heard as silence, an apology or a cut-off, rather than a wait.
CALLER_HEARD_FAILURE: frozenset[EngineProblemKind] = frozenset(
    {"no_answer_from_model", "own_key_failed", "voice_failed"}
)


class EngineProblem(BaseModel):
    """Something the engine reports going wrong on a call while it is still live.

    Kind and time, and for `own_key_failed` alone the engine's sentence about the key (D-769),
    because which key failed and why is what an operator needs and the kind does not say it.
    Every other kind's sentence is not carried, so nothing a vendor writes reaches a screen
    through this model.
    """

    kind: EngineProblemKind
    #: The engine's id for the delivery, stable across its retries.
    problem_id: str
    engine_agent_ref: str | None = None
    engine_call_id: str
    occurred_at: datetime | None = None
    engine: str
    #: The engine's own sentence on an `own_key_failed`, shortened by the adapter with long
    #: digit runs masked, since it is vendor text we cannot vouch holds no caller detail. It
    #: reaches the operator alarm only (whose line `alert` logs), never a client surface.
    operator_detail: str | None = None


class CallQuality(BaseModel):
    """How a call went, in numbers the engine measured once it ended. Every figure may be
    None: the engine could not measure it on that call."""

    #: Caller turns the agent answered.
    turns: int | None = None
    #: Caller stops speaking -> the agent's first audio, milliseconds.
    reply_ms_median: int | None = None
    reply_ms_p90: int | None = None
    reply_ms_max: int | None = None
    #: The model's share of that wait: turn reaches the model -> its first word.
    first_token_ms_median: int | None = None
    first_token_ms_p90: int | None = None
    first_token_ms_max: int | None = None
    long_silences: int | None = None
    longest_silence_s: float | None = None
    interruptions: int | None = None
    #: Turns the agent apologised for because no model answered.
    model_errors: int | None = None
    #: Turns a backup model answered after the first choice failed.
    backup_answers: int | None = None


class CallLlmUsage(BaseModel):
    """The language-model tokens a call's replies used, as the engine counted them, our own
    model key's included. Each is None when the engine did not record it. The engine may
    estimate the input count from the prompt's length where the provider reports none, so it
    is a close guide rather than an invoice."""

    input_tokens: int | None = None
    output_tokens: int | None = None
    #: How many of `input_tokens` the provider served from its cache.
    cached_input_tokens: int | None = None
    #: True when part of `input_tokens` is the engine's estimate rather than the provider's
    #: count; False when every count came from the provider; None when unknown (no tokens,
    #: or a call from before the engine reported it).
    input_tokens_estimated: bool | None = None


#: Whose keys a call ran on, after any fallback when a key was gone at the start: `off` the
#: engine's own, `all` ours for speech, model and voice, `voice` our voice only, `llm` our
#: model only, `llm_voice` our model and voice. The same words an agent's `byok` setting uses.
CallKeys = Literal["off", "all", "voice", "llm", "llm_voice"]
#: The engine voice band a call was priced on. The same words as the rate keys of the
#: bands (`billing/engine_minutes.EngineRateKey`).
CallVoicePlan = Literal["standard", "premium", "studio"]


class CallBilling(BaseModel):
    """What the engine billed one call as. Evidence for reconciling our metered minute, never
    a price: our cost comes only from an operator-attested rate (hard rule 7)."""

    keys: CallKeys
    #: None for a flat own-key price, a free trial call, or a call from before the engine
    #: reported it.
    voice_plan: CallVoicePlan | None = None
    #: The per-minute rate the call was charged at, in rupees; None when the engine stated
    #: none (a free trial call) or stated it in another currency.
    rate_inr_per_min: Decimal | None = None
    currency: Literal["INR", "USD"] | None = None
    #: The seconds the charge was for, already rounded up to the engine's step. None until
    #: the call is settled.
    billed_seconds: int | None = None
    #: The call ended before the agent spoke: it is charged the phone carrier's fee only,
    #: and `billed_seconds` is rounded to the carrier's block rather than the engine's step,
    #: so neither the per-minute rate nor the step applies to it.
    carrier_only: bool = False


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
    #: `start_ms` is a rough position rather than a point in the audio. ThinnestAI's turn
    #: time is "when it was written down, not where it falls in the audio"
    #: (thinnest-findings get-call-transcript.md:7), so its turns carry True and every
    #: screen shows their times as approximate.
    start_approximate: bool = False


__all__ = [
    "CALLER_HEARD_FAILURE",
    "TERMINAL_STATUSES",
    "CallBilling",
    "CallDirection",
    "CallEvent",
    "CallKeys",
    "CallLlmUsage",
    "CallQuality",
    "CallStatus",
    "CallVoicePlan",
    "EngineNotice",
    "EngineNoticeKind",
    "EngineOptOut",
    "EngineProblem",
    "EngineProblemKind",
    "Speaker",
    "TranscriptTurn",
]
