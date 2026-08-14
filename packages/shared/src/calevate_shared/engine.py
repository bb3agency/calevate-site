"""The VoiceEngine portability contract (TRD §5).

Nothing outside `engine/` may import a vendor SDK or see a vendor payload shape.
Both the `bolna` and `fake` adapters must satisfy this Protocol and pass the
conformance suite — the second adapter exists to keep the first one honest.
(ThinnestAI was retired by D-31 before any adapter was written.)

Everything an adapter ACCEPTS and everything it RETURNS is defined here, in our
vocabulary. That is the whole trick: a second engine changes one package, not the
codebase. Where a vendor has no equivalent of one of these fields, the adapter maps
or omits it — it never leaks its own shape upward.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from calevate_shared.events import CallDirection, CallEvent, CallStatus, TranscriptTurn

# Domain aliases.
E164 = str
EngineAgentRef = str
CallHandle = str
# The engine's own handle for ONE attached knowledge source — opaque to us, exactly
# like `EngineAgentRef`. It is the vendor's id (Bolna: `rag_id`), so only an adapter
# ever interprets it; everything above stores it and hands it back. Our `kb_sources.id`
# cannot serve here: the engine has never seen it, so it addresses nothing on their side.
EngineKBRef = str

NumberSeries = Literal["140", "160", "standard"]


class ModelConfig(BaseModel):
    """BYOK model selection — plain config strings (D-04/D-20/D-36), so changing a
    model is a config edit + regression run, never a code change."""

    stt_provider: str | None = None
    stt_model: str | None = None
    llm_model: str | None = None
    tts_provider: str | None = None
    tts_voice: str | None = None


class AgentConfig(BaseModel):
    """What an agent IS, in our terms. The adapter renders this into the vendor's
    agent object."""

    tenant_id: str
    agent_id: str
    name: str
    direction: Literal["inbound", "outbound", "both"]
    language_primary: str = "te-IN"
    languages_extra: list[str] = Field(default_factory=list)
    system_prompt: str
    # Compliance invariant (hard rule 5): never None, never empty. The adapter
    # prepends it to the greeting so it is spoken FIRST on every call.
    disclosure_line: str
    models: ModelConfig = Field(default_factory=ModelConfig)
    webhook_url: str | None = None
    knowledge_base_ref: str | None = None
    max_call_duration_s: int = 600


class CallContext(BaseModel):
    """Per-call variables rendered into the prompt (Bolna: `user_data`). This is OUR
    mechanism for lead callbacks and the D-21 "call this lead" note."""

    lead_id: str | None = None
    lead_name: str | None = None
    context_note: str | None = None
    prior_call_summary: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class NumberSpec(BaseModel):
    series: NumberSeries = "standard"
    provider: str | None = None
    region: str | None = None
    purpose: str | None = None


class ProvisionedNumber(BaseModel):
    e164: E164
    provider: str | None = None
    engine_number_ref: str | None = None
    series: NumberSeries = "standard"


class KBSourceRef(BaseModel):
    """A knowledge source we have already parsed, chunked and approved. Under BYOK the
    KB is NOT a model slot (D-33) — the engine's built-in KB serves in-call retrieval
    in v1, so this is a pointer plus the text, not an embedding."""

    kb_id: str
    title: str
    text: str
    language: str = "te-IN"


class CostBreakdown(BaseModel):
    """Money is NUMERIC INR, never floats (hard rule 7).

    Vendors quote in their own currency (Bolna: USD cents); the ADAPTER converts at
    capture and stamps the rate it used, so a ledger row can always be re-derived.

    `currency_stated` is what separates a fact from a house assumption, and it exists
    because the two were indistinguishable. `source_currency` was defaulted to `"USD"`
    and Bolna's adapter set the same literal, so a reader — including pilot gate 7,
    whose whole job is to check the currency — could only ever read our own guess back
    and agree with it (OPERATIONS §2). Now `source_currency` still says which currency
    the conversion ASSUMED, and `currency_stated` says whether the vendor said so:
    False means nobody has confirmed it, and if the guess is wrong every INR row is out
    by the exchange rate, in the direction that flatters our margin.
    """

    total_inr: Decimal
    platform_inr: Decimal | None = None
    network_inr: Decimal | None = None
    llm_inr: Decimal | None = None
    tts_inr: Decimal | None = None
    stt_inr: Decimal | None = None
    #: The currency the conversion treated the vendor's number as.
    source_currency: str = "USD"
    #: True only when the PAYLOAD named that currency. False = house assumption.
    currency_stated: bool = False
    source_amount: Decimal | None = None
    fx_rate: Decimal | None = None


class ExecutionSnapshot(BaseModel):
    """The authenticated fetch that is the TRUTH (D-31: webhooks are hints).

    Bolna populates cost/recording/extracted data only at `completed`, roughly 2-3
    min after disconnect — so `terminal` alone is not "ready", `billable_ready` is.
    """

    engine_call_id: str
    # Their agent id — the ONLY bridge to our tenant (agents.engine_agent_ref). The
    # reconciliation poller has no webhook payload to read it from, so the snapshot
    # must carry it or every repaired call is unmappable.
    engine_agent_ref: str | None = None
    direction: CallDirection = "inbound"
    status: CallStatus
    raw_status: str
    terminal: bool
    billable_ready: bool
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_s: int | None = None
    from_e164: str | None = None
    to_e164: str | None = None
    recording_url: str | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    #: Transcript lines the adapter could NOT turn into a turn. Zero is the normal
    #: answer and the only one that means anything: a parser that silently drops what it
    #: does not recognise reports an empty transcript and a healthy call identically, so
    #: gate 7 could only ever see a TOTAL parse failure. Counted rather than kept —
    #: transcript TEXT is hard rule 6, and a count is not text.
    transcript_lines_unparsed: int = 0
    cost: CostBreakdown | None = None
    #: When the engine says the execution reached its billable-ready state. Bolna
    #: populates cost, recording and extracted data only at `completed`, ~2-3 min after
    #: disconnect, and NOTHING recorded that instant — so gate 7's time-to-`completed`
    #: had no post-hoc route and the 2-minute lead SLO was un-auditable after the fact.
    #: `now - ended_at` is deliberately not a substitute: it grows with how long the
    #: operator took to look.
    billable_ready_at: datetime | None = None
    engine_extracted: dict[str, Any] = Field(default_factory=dict)
    engine: str = "fake"


class WebhookVerdict(BaseModel):
    """Per-engine authenticity result. Bolna signs nothing (D-31), so `method` is how
    we say what evidence we actually have — an unsigned event is accepted only as a
    HINT, and the poller remains the guarantee of record."""

    ok: bool
    method: Literal["hmac", "source_ip", "none"]
    reason: str | None = None


@runtime_checkable
class VoiceEngine(Protocol):
    name: str

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef: ...

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None: ...

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle: ...

    async def end_call(self, call_id: str) -> None: ...

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None: ...

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber: ...

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        """Push an approved source and return the engine's handle for it.

        Returning the handle is the whole reason a superseded version can ever be
        removed: the engine names its copy, we do not. An adapter that has nothing
        to return is an adapter whose KB can only ever grow.
        """
        ...

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        """Remove ONE attached source — the counterpart without which `attach_kb` is a
        one-way door.

        FLOWS §7 makes a knowledge version a governed object: a human approves it, and
        publishing v2 supersedes v1. Without this method "supersede" only ever happened
        in OUR tables, so the agent kept answering from v1 — the published KB diverging
        from the approved one, which is the single thing the approval gate exists to
        prevent. (After a rollback it was worse: every version was live at once.)

        It must be REAL. An adapter that accepts the call and does nothing turns the
        publish path into a silent lie, and nothing downstream can detect it — which is
        why the conformance suite observes the removal through `list_kb` rather than
        trusting the call to have happened.

        Detaching a handle the engine does not have must RAISE, not pass quietly: the
        publisher's next step is to attach the replacement, and it is entitled to know
        whether the old text is really gone before it does.
        """
        ...

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        """The handles currently attached to this agent.

        The engine — not our table — is what the caller actually hears, so "does the
        published KB match what was approved?" is only answerable by reading the engine
        back. It is also the only adapter-independent way to prove a `detach_kb` did
        anything at all.
        """
        ...

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        """The authenticated read. This — not the webhook — is what we persist."""
        ...

    async def list_executions(self, *, since: datetime) -> list[ExecutionSnapshot]:
        """Backs the reconciliation poller (D-31: guarantee of record, not a safety net)."""
        ...

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """HMAC where the engine signs; source-IP allowlist where it does not."""
        ...

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """Vendor payload → OUR normalized event. The isolation boundary."""
        ...


__all__ = [
    "E164",
    "AgentConfig",
    "CallContext",
    "CallHandle",
    "CostBreakdown",
    "EngineAgentRef",
    "EngineKBRef",
    "ExecutionSnapshot",
    "KBSourceRef",
    "ModelConfig",
    "NumberSeries",
    "NumberSpec",
    "ProvisionedNumber",
    "VoiceEngine",
    "WebhookVerdict",
]
