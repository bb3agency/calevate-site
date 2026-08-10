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
    """

    total_inr: Decimal
    platform_inr: Decimal | None = None
    network_inr: Decimal | None = None
    llm_inr: Decimal | None = None
    tts_inr: Decimal | None = None
    stt_inr: Decimal | None = None
    source_currency: str = "USD"
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
    cost: CostBreakdown | None = None
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

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> None: ...

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
    "ExecutionSnapshot",
    "KBSourceRef",
    "ModelConfig",
    "NumberSeries",
    "NumberSpec",
    "ProvisionedNumber",
    "VoiceEngine",
    "WebhookVerdict",
]
