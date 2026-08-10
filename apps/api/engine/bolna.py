"""Bolna adapter — the ONLY place in the codebase that knows Bolna's payload shapes.

Adopted by D-31 (supersedes D-02's ThinnestAI pick), gated on the pilot scorecard.
Everything here is hand-maintained from docs.bolna.ai + payloads captured during the
pilot, because **Bolna publishes no OpenAPI spec** (TRD §5). Treat every field name as
a claim that needs re-checking against a captured payload, not as a guarantee.

Three properties of this vendor shape the whole design and are load-bearing:

1. **Webhooks are unsigned and at-most-once** (verified in their docs AND their OSS
   delivery code: a single aiohttp POST, no retry, no timeout, errors swallowed). So
   authenticity = source-IP allowlist + execution-id dedupe, webhook payloads are
   HINTS, and the List-Executions poller is the guarantee of record.
2. **cost / recording_url / extracted_data populate only at `completed`**, roughly
   2-3 min after disconnect. The post-call pipeline therefore triggers on `completed`,
   never on a disconnect event — `billable_ready` encodes exactly that.
3. **Costs arrive in USD cents** with a per-leg breakdown. The adapter converts to INR
   at capture and stamps the fx rate, so a ledger row can always be re-derived
   (hard rule 7).

Per-turn timings are not exposed, so `calls.latency` stays null for Bolna calls —
latency measurement is the pilot stopwatch method (OPERATIONS §2 gate 4), not a field.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx
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

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

BASE_URL = "https://api.bolna.ai"
# Their ONLY control for webhook authenticity: a static egress IP (D-31). Enforced at
# nginx AND here — belt and braces, because nginx config drifts and this does not.
ALLOWED_SOURCE_IPS: frozenset[str] = frozenset({"13.203.39.153"})
REQUEST_TIMEOUT_S = 10.0

# Their 15-value status enum → our 8. Anything unmapped becomes `failed`, which is the
# safe direction: a call we cannot classify must not look successful.
_STATUS_MAP: dict[str, CallStatus] = {
    "scheduled": "queued",
    "queued": "queued",
    "initiated": "ringing",
    "ringing": "ringing",
    "in-progress": "in_progress",
    "call-connected": "in_progress",
    "call-disconnected": "completed",
    "completed": "completed",
    "no-answer": "no_answer",
    "busy": "busy",
    "voicemail": "voicemail",
    "failed": "failed",
    "canceled": "failed",
    "cancelled": "failed",
    "stopped": "failed",
    "error": "failed",
    "balance-low": "failed",
}

_TERMINAL_RAW = frozenset(
    {
        "completed",
        "no-answer",
        "busy",
        "failed",
        "canceled",
        "cancelled",
        "stopped",
        "error",
        "balance-low",
        "voicemail",
    }
)

# Transcript arrives as prefix-tagged plain text, e.g.
#   "assistant: namaskaram\nuser: appointment kavali"
_TURN_RE = re.compile(r"^\s*(assistant|agent|user|human|bot)\s*:\s*(.*)$", re.IGNORECASE)
_SPEAKER_MAP = {
    "assistant": "agent",
    "agent": "agent",
    "bot": "agent",
    "user": "caller",
    "human": "caller",
}

_PAISE = Decimal("0.0001")


def _to_inr(usd_cents: Any, fx_rate: Decimal) -> Decimal | None:
    """USD cents → INR, quantized to the ledger's NUMERIC(12,4). Floats never touch
    money: the vendor value is stringified before it becomes a Decimal."""
    if usd_cents is None:
        return None
    try:
        cents = Decimal(str(usd_cents))
    except (ArithmeticError, ValueError):
        return None
    return (cents / Decimal(100) * fx_rate).quantize(_PAISE, rounding=ROUND_HALF_UP)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, int | float):
        return datetime.fromtimestamp(float(value), tz=UTC)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def parse_transcript(raw: str | None, call_id: str) -> list[TranscriptTurn]:
    """Prefix-tagged text → typed turns. A continuation line with no prefix is
    appended to the previous turn rather than dropped — long agent answers wrap."""
    if not raw:
        return []
    turns: list[TranscriptTurn] = []
    for line in raw.splitlines():
        if not line.strip():
            continue
        match = _TURN_RE.match(line)
        if match is None:
            if turns:
                previous = turns[-1]
                turns[-1] = previous.model_copy(
                    update={"text": f"{previous.text} {line.strip()}".strip()}
                )
            continue
        speaker = _SPEAKER_MAP.get(match.group(1).lower(), "caller")
        text_value = match.group(2).strip()
        if not text_value:
            continue
        turns.append(
            TranscriptTurn(
                call_id=call_id,
                idx=len(turns),
                speaker=speaker,
                text=text_value,
            )
        )
    return turns


class BolnaEngine:
    """Implements `VoiceEngine`. Constructed per process; the httpx client is reused."""

    name = "bolna"

    def __init__(
        self,
        *,
        api_key: str | None,
        fx_rate: Decimal,
        client: httpx.AsyncClient | None = None,
        base_url: str = BASE_URL,
    ) -> None:
        self._api_key = api_key
        self._fx_rate = fx_rate
        self._base_url = base_url
        self._client = client

    # --- plumbing ------------------------------------------------------------

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            if not self._api_key:
                raise ProblemError(
                    kind="dependency",
                    code="engine_not_configured",
                    title="Voice engine is not configured",
                    detail="No Bolna API key is available in this environment.",
                )
            self._client = httpx.AsyncClient(
                base_url=self._base_url,
                timeout=REQUEST_TIMEOUT_S,
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
        return self._client

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = await self._http().request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise ProblemError(
                kind="dependency",
                code="engine_unreachable",
                title="Voice engine unreachable",
                detail="The voice platform did not respond.",
                failure_stage="CORE_LOGIC",
            ) from exc
        if response.status_code >= 400:
            # Never echo a vendor error body to a client — it is not user-safe and it
            # is not our vocabulary.
            log.warning("engine_error", extra={"status": response.status_code, "route": path})
            raise ProblemError(
                kind="dependency",
                code="engine_rejected",
                title="Voice engine rejected the request",
                detail="The voice platform could not complete this operation.",
                failure_stage="CORE_LOGIC",
            )
        payload = response.json()
        return payload if isinstance(payload, dict) else {"data": payload}

    # --- agent lifecycle -----------------------------------------------------

    def _agent_body(self, cfg: AgentConfig) -> dict[str, Any]:
        """Our AgentConfig → their agent object. The disclosure line is PREPENDED to
        the prompt, not appended: hard rule 5 wants it spoken first, always."""
        prompt = f"{cfg.disclosure_line}\n\n{cfg.system_prompt}"
        return {
            "agent_config": {
                "agent_name": cfg.name,
                "agent_type": "other",
                "agent_welcome_message": cfg.disclosure_line,
                "webhook_url": cfg.webhook_url,
                "tasks": [
                    {
                        "task_type": "conversation",
                        "tools_config": {
                            "llm_agent": {
                                "agent_flow_type": "streaming",
                                "family": "openai",
                                "model": cfg.models.llm_model,
                            },
                            "synthesizer": {
                                "provider": cfg.models.tts_provider,
                                "provider_config": {"voice": cfg.models.tts_voice},
                                "stream": True,
                            },
                            "transcriber": {
                                "provider": cfg.models.stt_provider,
                                "model": cfg.models.stt_model,
                                "language": cfg.language_primary,
                                "stream": True,
                            },
                        },
                        "task_config": {
                            "hangup_after_silence": 10,
                            "call_terminate": cfg.max_call_duration_s,
                        },
                    }
                ],
            },
            "agent_prompts": {"task_1": {"system_prompt": prompt}},
        }

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        # /v2/agent — legacy unversioned agent paths are deprecated, never call them.
        data = await self._request("POST", "/v2/agent", json=self._agent_body(cfg))
        ref = data.get("agent_id") or data.get("id")
        if not isinstance(ref, str):
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return an agent id.",
            )
        return ref

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        await self._request("PUT", f"/v2/agent/{ref}", json=self._agent_body(cfg))

    async def start_outbound_call(
        self, ref: EngineAgentRef, to: E164, ctx: CallContext
    ) -> CallHandle:
        # `user_data` dynamic variables are rendered into the prompt — our CallContext
        # mechanism for lead callbacks (D-21).
        user_data = {k: v for k, v in ctx.fields.items() if v}
        if ctx.lead_name:
            user_data["lead_name"] = ctx.lead_name
        if ctx.context_note:
            user_data["context_note"] = ctx.context_note
        if ctx.prior_call_summary:
            user_data["prior_call_summary"] = ctx.prior_call_summary
        data = await self._request(
            "POST",
            "/call",
            json={"agent_id": ref, "recipient_phone_number": to, "user_data": user_data},
        )
        handle = data.get("execution_id") or data.get("id")
        if not isinstance(handle, str):
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a call id.",
            )
        return handle

    async def end_call(self, call_id: str) -> None:
        await self._request("POST", f"/executions/{call_id}/stop")

    async def transfer(self, call_id: str, to: E164, warm: bool) -> None:
        # UNVERIFIED on Bolna (pilot item). Until the pilot confirms the mechanics,
        # failing loudly beats pretending a transfer happened.
        raise ProblemError(
            kind="dependency",
            code="engine_capability_unverified",
            title="Transfer is not available yet",
            detail="Call transfer has not been verified on the current voice platform.",
            remediation="Use the escalation phone number configured on the agent.",
        )

    async def provision_number(self, spec: NumberSpec) -> ProvisionedNumber:
        raise ProblemError(
            kind="dependency",
            code="engine_capability_unverified",
            title="Number provisioning is not automated yet",
            detail="Numbers are provisioned with the telephony provider directly (M1).",
        )

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> None:
        """Built-in KB (`rag_id`). Under BYOK the KB is NOT a model slot (D-33): this
        is a document push, and multilingual mode is IMMUTABLE at KB creation — Telugu
        retrieval quality is pilot gate 8."""
        await self._request(
            "POST",
            "/knowledgebase",
            json={"agent_id": ref, "name": source.title, "text": source.text},
        )

    # --- reading the truth ---------------------------------------------------

    def _snapshot(self, payload: dict[str, Any]) -> ExecutionSnapshot:
        raw_status = str(payload.get("status") or "").lower()
        status = _STATUS_MAP.get(raw_status, "failed")
        call_id = str(payload.get("id") or payload.get("execution_id") or "")
        cost = self._cost(payload)
        started = _parse_dt(payload.get("created_at") or payload.get("started_at"))
        ended = _parse_dt(payload.get("ended_at") or payload.get("updated_at"))
        duration = payload.get("conversation_duration") or payload.get("duration")
        telephony = payload.get("telephony_data") or {}
        agent_ref = payload.get("agent_id")
        return ExecutionSnapshot(
            engine_call_id=call_id,
            engine_agent_ref=str(agent_ref) if agent_ref else None,
            direction="inbound" if payload.get("direction") == "inbound" else "outbound",
            status=status,
            raw_status=raw_status,
            terminal=raw_status in _TERMINAL_RAW,
            # The distinction that matters: terminal means "no more audio";
            # billable_ready means "cost, recording and transcript are populated".
            billable_ready=raw_status == "completed",
            started_at=started,
            ended_at=ended,
            duration_s=int(duration) if isinstance(duration, int | float) else None,
            from_e164=telephony.get("from_number") or payload.get("from_number"),
            to_e164=telephony.get("to_number") or payload.get("to_number"),
            recording_url=telephony.get("recording_url") or payload.get("recording_url"),
            transcript=parse_transcript(payload.get("transcript"), call_id),
            cost=cost,
            engine_extracted=payload.get("extracted_data") or {},
            engine="bolna",
        )

    def _cost(self, payload: dict[str, Any]) -> CostBreakdown | None:
        total = payload.get("total_cost")
        if total is None:
            return None
        breakdown = payload.get("cost_breakdown") or {}
        total_inr = _to_inr(total, self._fx_rate)
        if total_inr is None:
            return None
        return CostBreakdown(
            total_inr=total_inr,
            platform_inr=_to_inr(breakdown.get("platform"), self._fx_rate),
            network_inr=_to_inr(breakdown.get("network"), self._fx_rate),
            llm_inr=_to_inr(breakdown.get("llm"), self._fx_rate),
            tts_inr=_to_inr(breakdown.get("synthesizer"), self._fx_rate),
            stt_inr=_to_inr(breakdown.get("transcriber"), self._fx_rate),
            source_currency="USD",
            source_amount=Decimal(str(total)) / Decimal(100),
            fx_rate=self._fx_rate,
        )

    async def get_execution(self, call_id: str) -> ExecutionSnapshot:
        return self._snapshot(await self._request("GET", f"/executions/{call_id}"))

    async def list_executions(self, *, since: datetime) -> list[ExecutionSnapshot]:
        data = await self._request(
            "GET", "/executions", params={"created_after": since.isoformat()}
        )
        rows = data.get("data") if isinstance(data.get("data"), list) else data.get("executions")
        if not isinstance(rows, list):
            return []
        return [self._snapshot(row) for row in rows if isinstance(row, dict)]

    # --- webhooks ------------------------------------------------------------

    def verify_webhook(
        self, headers: dict[str, str], body: bytes, source_ip: str
    ) -> WebhookVerdict:
        """No signature exists to check (D-31). The source IP is the only control, and
        it is deliberately reported as `source_ip` rather than dressed up as proof —
        the caller must keep treating the payload as a hint."""
        if source_ip in ALLOWED_SOURCE_IPS:
            return WebhookVerdict(ok=True, method="source_ip")
        return WebhookVerdict(
            ok=False, method="source_ip", reason="source ip not in the engine allowlist"
        )

    def parse_webhook(self, payload: dict[str, Any]) -> CallEvent:
        """Webhooks and Get Execution share one shape, so this reuses the snapshot
        parser and drops to the event fields."""
        snapshot = self._snapshot(payload)
        agent_ref = payload.get("agent_id")
        # Their payload marks inbound explicitly; everything else on this platform is a
        # call WE placed. Defaulting to outbound is the compliance-safe direction —
        # outbound is the side that carries DNC/calling-hours obligations, so a
        # misclassified call is over-regulated rather than under-regulated.
        direction = "inbound" if payload.get("direction") == "inbound" else "outbound"
        return CallEvent(
            call_id=snapshot.engine_call_id,
            engine_agent_ref=str(agent_ref) if agent_ref else None,
            direction=direction,
            status=snapshot.status,
            raw_status=snapshot.raw_status,
            started_at=snapshot.started_at,
            ended_at=snapshot.ended_at,
            from_e164=snapshot.from_e164,
            to_e164=snapshot.to_e164,
            recording_url=snapshot.recording_url,
            cost_raw=str(payload.get("total_cost")) if payload.get("total_cost") else None,
            engine="bolna",
        )


__all__ = ["ALLOWED_SOURCE_IPS", "BASE_URL", "BolnaEngine", "parse_transcript"]
