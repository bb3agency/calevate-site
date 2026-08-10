"""`fake` adapter — the second implementation that keeps the first one honest.

Two jobs, both real:

1. **Local development runs offline and deterministic** (DEV-SETUP §3): `ENGINE=fake`
   means the whole pipeline — dispatch, webhook, post-call, lead — works with no
   vendor account, no network and no spend.
2. **It is the conformance control.** A behaviour that only the Bolna adapter has is
   either mapped into the contract or is not allowed to leak upward; running the same
   suite against both is how that stays true (TRD §5).

It is deliberately NOT a mock: calls have a lifecycle, transcripts are Telugu-first
code-mixed samples of the shape Saaras actually returns, and costs come out of the
verified rate card (TRD §10) so metering code meets realistic numbers.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from calevate_shared.engine import (
    E164,
    AgentConfig,
    CallContext,
    CallHandle,
    CostBreakdown,
    EngineAgentRef,
    ExecutionSnapshot,
    KBSourceRef,
    NumberSpec,
    ProvisionedNumber,
    WebhookVerdict,
)
from calevate_shared.events import CallEvent, CallStatus, TranscriptTurn

# A short code-mixed exchange: Telugu with English clinical terms, which is what
# real calls sound like and what the extraction fixtures must cope with.
SAMPLE_TURNS: tuple[tuple[str, str], ...] = (
    ("agent", "Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi."),
    ("caller", "Namaskaram, naaku appointment kavali."),
    ("agent", "Tappakunda. Ee roju evening 6 gantalaku doctor available unnaru."),
    ("caller", "Sare, naa peru Ravi, number 9876543210."),
    ("agent", "Thank you Ravi garu, mee appointment 6 PM ki book chesanu."),
)

# Per-minute INR from the verified rate card (TRD §10.1, D-35/D-36): all-Sarvam BYOK.
_COST_PER_MIN = {
    "platform": Decimal("1.7500"),
    "network": Decimal("0.6000"),
    "stt": Decimal("0.5000"),
    "llm": Decimal("0.0000"),  # Sarvam 105B is free per token (D-35)
    "tts": Decimal("1.2000"),
}


class FakeEngine:
    """Implements `VoiceEngine` entirely in memory."""

    name = "fake"

    def __init__(self) -> None:
        self._agents: dict[str, AgentConfig] = {}
        self._calls: dict[str, dict[str, Any]] = {}
        self._kb: dict[str, list[KBSourceRef]] = {}

    # --- deterministic ids ---------------------------------------------------

    @staticmethod
    def _stable_id(prefix: str, *parts: str) -> str:
        digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:24]
        return f"{prefix}_{digest}"

    # --- agent lifecycle -----------------------------------------------------

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        ref = self._stable_id("fakeagent", cfg.tenant_id, cfg.agent_id)
        self._agents[ref] = cfg
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        self._agents[ref] = cfg

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        handle = self._stable_id("fakecall", ref, to, ctx.lead_id or "", str(len(self._calls)))
        now = datetime.now(UTC)
        self._calls[handle] = {
            "agent_ref": ref,
            "direction": "outbound",
            "status": "completed",
            "started_at": now,
            "ended_at": now + timedelta(seconds=95),
            "duration_s": 95,
            "from_e164": "+911140000000",
            "to_e164": to,
            "context": ctx.model_dump(),
        }
        return handle

    async def end_call(self, call_id: str) -> None:
        call = self._calls.get(call_id)
        if call is not None:
            call["status"] = "completed"
            call["ended_at"] = datetime.now(UTC)

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        call = self._calls.get(call_id)
        if call is not None:
            call["transferred_to"] = to
            call["transfer_warm"] = warm

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        e164 = "+9111" + self._stable_id("n", spec.series, spec.purpose or "")[-8:].replace(
            "abcdef", "123456"
        )
        digits = "".join(c for c in e164 if c.isdigit())[:12].ljust(12, "0")
        return ProvisionedNumber(
            e164=f"+{digits}",
            provider=spec.provider or "fake-telco",
            engine_number_ref=self._stable_id("fakenum", digits),
            series=spec.series,
        )

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> None:
        self._kb.setdefault(ref, []).append(source)

    # --- reading the truth ---------------------------------------------------

    def _cost_for(self, duration_s: int) -> CostBreakdown:
        minutes = Decimal(duration_s) / Decimal(60)
        legs = {k: (v * minutes).quantize(Decimal("0.0001")) for k, v in _COST_PER_MIN.items()}
        total = sum(legs.values(), Decimal("0"))
        return CostBreakdown(
            total_inr=total.quantize(Decimal("0.0001")),
            platform_inr=legs["platform"],
            network_inr=legs["network"],
            llm_inr=legs["llm"],
            tts_inr=legs["tts"],
            stt_inr=legs["stt"],
            source_currency="INR",
            source_amount=total,
            fx_rate=Decimal("1"),
        )

    def _snapshot_from(self, call_id: str, call: dict[str, Any]) -> ExecutionSnapshot:
        raw_status = str(call["status"])
        duration = int(call.get("duration_s") or 0)
        return ExecutionSnapshot(
            engine_call_id=call_id,
            status=raw_status,  # type: ignore[arg-type]  # fake only stores our enum
            raw_status=raw_status,
            terminal=raw_status in ("completed", "failed", "no_answer", "busy", "voicemail"),
            billable_ready=raw_status == "completed",
            started_at=call.get("started_at"),
            ended_at=call.get("ended_at"),
            duration_s=duration,
            from_e164=call.get("from_e164"),
            to_e164=call.get("to_e164"),
            recording_url=f"https://fake-engine.local/recordings/{call_id}.wav",
            transcript=[
                TranscriptTurn(call_id=call_id, idx=i, speaker=speaker, text=text)  # type: ignore[arg-type]
                for i, (speaker, text) in enumerate(SAMPLE_TURNS)
            ],
            cost=self._cost_for(duration) if raw_status == "completed" else None,
            engine_extracted={},
            engine="fake",
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        call = self._calls.get(call_id)
        if call is None:
            # Match the real thing: an unknown execution id is an engine-side 404, and
            # the caller must handle it rather than get a synthesized success.
            call = {
                "agent_ref": "unknown",
                "direction": "inbound",
                "status": "failed",
                "duration_s": 0,
            }
        return self._snapshot_from(call_id, call)

    async def list_executions(self, *, since: datetime) -> list[ExecutionSnapshot]:
        return [
            self._snapshot_from(cid, call)
            for cid, call in self._calls.items()
            if (call.get("started_at") or datetime.now(UTC)) >= since
        ]

    # --- webhooks ------------------------------------------------------------

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """Accepts everything on purpose: the fake engine exists to exercise the code
        AFTER verification. The `method="none"` label is what stops a caller mistaking
        this for evidence."""
        return WebhookVerdict(ok=True, method="none", reason="fake engine")

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        status = str(payload.get("status") or "completed")
        known: set[str] = {
            "queued",
            "ringing",
            "in_progress",
            "completed",
            "failed",
            "no_answer",
            "busy",
            "voicemail",
        }
        normalized: CallStatus = status if status in known else "failed"  # type: ignore[assignment]
        return CallEvent(
            call_id=str(payload.get("id") or payload.get("execution_id") or ""),
            engine_agent_ref=str(payload["agent_id"]) if payload.get("agent_id") else None,
            direction="inbound" if payload.get("direction") == "inbound" else "outbound",
            status=normalized,
            raw_status=status,
            from_e164=payload.get("from_number"),
            to_e164=payload.get("to_number"),
            recording_url=payload.get("recording_url"),
            engine="fake",
        )

    # --- test affordances ----------------------------------------------------

    def seed_inbound_call(
        self,
        *,
        call_id: str,
        agent_ref: str,
        from_e164: str,
        to_e164: str,
        duration_s: int = 95,
    ) -> None:
        """Used by the smoke test and the regression harness to stage a call that the
        webhook receiver will then 'discover'."""
        now = datetime.now(UTC)
        self._calls[call_id] = {
            "agent_ref": agent_ref,
            "direction": "inbound",
            "status": "completed",
            "started_at": now - timedelta(seconds=duration_s),
            "ended_at": now,
            "duration_s": duration_s,
            "from_e164": from_e164,
            "to_e164": to_e164,
        }


__all__ = ["SAMPLE_TURNS", "FakeEngine"]
