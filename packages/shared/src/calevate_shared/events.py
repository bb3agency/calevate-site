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

#: Why a call the engine held for later was never placed (D-842), in our words. The engine
#: states its reason as prose; the adapter maps the cases it knows to a code here and every
#: other reason to `unstated`, so no vendor sentence reaches storage or a client.
#: `from_number_withdrawn`: the number the call was to ring from was taken off the agent.
NotPlacedReason = Literal["from_number_withdrawn", "unstated"]
NOT_PLACED_REASONS: tuple[NotPlacedReason, ...] = ("from_number_withdrawn", "unstated")

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


class EngineContactErased(BaseModel):
    """The engine finished erasing one contact: the last of its recordings is gone.

    Ids and a time only; the engine sends no personal data with it.
    """

    #: The engine's id for the delivery, stable across its retries.
    event_id: str
    #: The engine's id for the erased contact.
    contact_id: str
    #: The customer workspace the delivery names, when it names one (a developer-wide
    #: endpoint); None when it came from an endpoint inside the workspace itself.
    workspace: str | None = None
    erased_at: datetime | None = None
    engine: str


EngineByokChange = Literal[
    "key_added",
    "key_replaced",
    "key_removed",
    "key_failed_verification",
    "byok_enabled",
    "byok_disabled",
    "scope_changed",
]


class EngineByokChanged(BaseModel):
    """The own-keys set-up of one engine workspace changed. Never carries key material."""

    event_id: str
    change: EngineByokChange
    #: Which key changed (`stt`, `llm`, `tts`) for the four key changes; None otherwise.
    kind: str | None = None
    provider: str | None = None
    #: Where the workspace stands AFTER the change.
    byok_enabled: bool | None = None
    scope: str | None = None
    #: As on `EngineContactErased`.
    workspace: str | None = None
    engine: str


class CallQuality(BaseModel):
    """How a call went, in numbers the engine measured once it ended. Every figure may be
    None: the engine could not measure it on that call."""

    #: Caller turns the agent answered.
    turns: int | None = None
    #: Caller stops speaking -> the first word of the ACTUAL answer heard, milliseconds: a
    #: filler line or an acknowledgement that plays first does not end it. The reply time
    #: targets are judged on. None on calls from before 27 Oct 2026 (VERIFIED-VENDOR-DOCS,
    #: `quality.answerMs`, https://app.thinnest.ai/openapi.json read 27 Oct 2026; D-902).
    answer_ms_median: int | None = None
    answer_ms_p90: int | None = None
    answer_ms_max: int | None = None
    #: Caller stops speaking -> the agent's first SOUND of any kind, a filler line included
    #: (`quality.responseMs`, same source). Kept beside the answer: the gap between the two
    #: is how long a filler held the line.
    reply_ms_median: int | None = None
    reply_ms_p90: int | None = None
    reply_ms_max: int | None = None
    #: Part of that wait: the turn reaching the voice platform -> the first speakable word,
    #: not counted from the caller's speech end (VENDOR-STATED, `docs/vendor/
    #: thinnest-replies-2026-10-12.md` §25.0).
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
    #: Turns on which the agent looked something up in its knowledge, by its own search or
    #: from passages handed to it up front (`quality.knowledgeTurns`, same source).
    knowledge_turns: int | None = None


#: What a turn's first sound was: the answer itself, a `filler` (a thinking line or an
#: acknowledgement before the answer), or `other` (the turn had no answer words of its own).
TurnFirstSound = Literal["answer", "filler", "other"]


class TurnTiming(BaseModel):
    """Where the time went in one turn, in milliseconds from the moment the caller stopped
    speaking. A step that did not happen is None, never zero. Times only, no words."""

    #: The turn's number, from 1.
    turn: int
    #: When the caller stopped speaking, from the start of the call.
    caller_stopped_at_ms: int | None = None
    #: The first sound of any kind (what `CallQuality.reply_ms_*` measures) and what it was.
    first_sound_ms: int | None = None
    first_sound_kind: TurnFirstSound | None = None
    #: The first word of the actual answer heard (what `CallQuality.answer_ms_*` measures).
    answer_ms: int | None = None
    #: True when a filler spoke first, so `answer_ms` was worked out from the audio queued
    #: behind it rather than heard directly.
    answer_estimated: bool = False
    #: Caller stopped -> the turn decided: the recogniser's wait, the final words and the
    #: end-of-turn check together.
    wait_before_decision_ms: int | None = None
    #: Caller stopped -> their final words arrived.
    recogniser_ms: int | None = None
    #: Final words -> the end-of-turn check's verdict. None when that check is not used.
    ear_check_ms: int | None = None
    #: The model asked -> the first words of the answer leaving it (a filler does not count).
    model_first_sentence_ms: int | None = None
    #: The answer's first words leaving the model -> heard: the voice starting, plus any wait
    #: behind a filler still speaking.
    voice_ms: int | None = None
    #: When the model was asked. Negative when it was asked before the turn was decided
    #: (early answers).
    model_asked_ms: int | None = None
    #: The moments the split is made from. Under the end-of-turn check only: the recogniser
    #: called the pause, the final words arrived, the check gave its verdict.
    pause_called_ms: int | None = None
    final_words_ms: int | None = None
    check_decided_ms: int | None = None
    #: The turn was decided and an answer wanted, on every turn mode.
    turn_decided_ms: int | None = None
    #: The first words of the answer left the model (a filler is not the answer).
    answer_text_ms: int | None = None


class CallTimeline(BaseModel):
    """A call's per-turn timings, in turn order."""

    turns: list[TurnTiming] = Field(default_factory=list)


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
    #: reported it. On a `carrier_only` call, the plan the call was set up on, not the one
    #: it was charged at.
    voice_plan: CallVoicePlan | None = None
    #: The per-minute rate the call was charged at, in rupees; None when the engine stated
    #: none (a free trial call) or stated it in another currency. On a `carrier_only` call,
    #: the rate the call was set up on, not the one it was charged at.
    rate_inr_per_min: Decimal | None = None
    currency: Literal["INR", "USD"] | None = None
    #: The seconds the charge was for, already rounded up to the engine's step (the
    #: carrier's block on a `carrier_only` call). None until a charge was taken, and on a
    #: free trial call. A free trial call is ONLY one paid from a free-plan workspace's trial
    #: minutes: a workspace on a paid plan, a developer workspace's own test calls included,
    #: is charged from its balance and reports plan, rate and seconds.
    billed_seconds: int | None = None
    #: The call ended before the agent spoke, so no agent ran on it (a forwarded call is not
    #: this, D-835): it is charged the phone carrier's fee only, by the carrier's block, so
    #: neither `voice_plan` nor `rate_inr_per_min` is what was charged and the call is
    #: reconciled by its total.
    carrier_only: bool = False


#: How a call ended, as the engine's call insights read it (D-940). `converted`: the customer
#: agreed to what the call was for.
InsightOutcome = Literal[
    "converted",
    "interested",
    "callback",
    "promise_to_pay",
    "not_interested",
    "no_decision",
    "wrong_person",
    "do_not_call",
]
#: Why a `not_interested` was a no.
InsightNoReason = Literal["price", "timing", "trust", "fit", "already_has", "other"]
ObjectionKind = Literal[
    "price", "timing", "trust", "fit", "need", "authority", "competitor", "other"
]
#: A problem the customer has with the business's own service.
IssueKind = Literal["payment", "billing", "login", "delivery", "product", "other"]
NextStepKind = Literal["callback", "promise_to_pay", "send_info", "visit", "hand_to_sales"]
#: `open` while on the follow-up list, `done` once marked done, `replaced` when a later call
#: with the same contact settled a newer step.
NextStepStatus = Literal["open", "done", "replaced"]


class CallObjection(BaseModel):
    #: In the customer's own words: personal data, redacted before it is stored and never
    #: logged (hard rule 6).
    text: str
    kind: ObjectionKind


class CallIssue(BaseModel):
    #: In the customer's own words, handled like `CallObjection.text`.
    text: str
    kind: IssueKind


class CallNextStep(BaseModel):
    kind: NextStepKind
    #: The day (and time) agreed; None when the call settled no date.
    at: datetime | None = None
    #: One short line, possibly empty; handled like `CallObjection.text`.
    note: str = ""
    status: NextStepStatus = "open"
    #: When it was marked done or replaced; None while open.
    followed_up_at: datetime | None = None


class CallInsights(BaseModel):
    """What a call came to, as the engine read it once after the call: how it ended, the
    customer's objections, why a no was a no, problems on the customer's side, and the next
    step agreed. Only what the customer said is noted; nothing is inferred. Absent (None on
    the snapshot) when the engine did not read the call."""

    outcome: InsightOutcome
    no_reason: InsightNoReason | None = None
    objections: list[CallObjection] = Field(default_factory=list)
    issues: list[CallIssue] = Field(default_factory=list)
    next_step: CallNextStep | None = None


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
    "CallInsights",
    "CallIssue",
    "CallKeys",
    "CallLlmUsage",
    "CallNextStep",
    "CallObjection",
    "CallQuality",
    "CallStatus",
    "CallTimeline",
    "CallVoicePlan",
    "EngineByokChange",
    "EngineByokChanged",
    "EngineContactErased",
    "EngineNotice",
    "EngineNoticeKind",
    "EngineOptOut",
    "EngineProblem",
    "EngineProblemKind",
    "InsightNoReason",
    "InsightOutcome",
    "IssueKind",
    "NextStepKind",
    "NextStepStatus",
    "ObjectionKind",
    "Speaker",
    "TranscriptTurn",
    "TurnFirstSound",
    "TurnTiming",
]
