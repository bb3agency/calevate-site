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

Per-turn timings are NOT mapped here, and there is no call-latency column to map them
into any more (migration f1a7c39d5be2 dropped it). Their docs now describe a
`latency_data` object on Get Execution — per-component `transcriber`/`llm`/`synthesizer`
timings plus a first-audio number — but it is an unverified claim with no captured
payload, it is not the voice-to-voice measurement the budget is written in, and its
transcriber entries carry recognised TEXT (hard rules 5/6). So it stays a PILOT GATE:
capture it at OPERATIONS §2 gate 4 beside the stopwatch that can falsify it, then decide
what to store. Until then latency measurement is the stopwatch, not a field.

Resilience shipped here: a request timeout and jittered backoff on 429 (SURFACES §3.3).
The circuit breaker that section also describes is deliberately NOT built — see the
throttle block below for what is and is not retried, and why.
"""

from __future__ import annotations

import asyncio
import random
import re
from collections.abc import Callable
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
    EngineKBRef,
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

# --- Throttle handling (SURFACES §3.3) ---------------------------------------
# Bolna's rate limits are unpublished (pilot item), so 429 is a response we will meet
# without warning. Three deliberate limits on what we do about it:
#
# 1. **429 ONLY.** A 429 means the request was refused, not performed — the one status
#    where retrying `POST /call` cannot dial a person twice. A 502/503/504 on the same
#    endpoint is ambiguous, so those are reported, never repeated. Retrying a
#    non-idempotent create because it "felt transient" is how a lead gets two calls.
# 2. **Jitter, always.** Our workers are throttled in the same second and would
#    otherwise retry in the same second; a synchronized herd is how a rate limit
#    becomes an outage. Full jitter, and a `Retry-After` is a floor we never undercut.
# 3. **A short ceiling.** Adapter calls happen inside request handlers as well as
#    workers, so the adapter may stall a request by a second or two — not by two
#    minutes. A `Retry-After` longer than the ceiling is not slept through: it is
#    reported as `transient`, which is the caller's cue to reschedule the work.
THROTTLE_STATUS = 429
THROTTLE_MAX_ATTEMPTS = 3
THROTTLE_BASE_S = 0.5
THROTTLE_MAX_SLEEP_S = 8.0


def _retry_after_seconds(response: httpx.Response) -> float | None:
    """`Retry-After` in delay-seconds form. The HTTP-date form is not parsed on
    purpose: a clock-skewed date is worse than no hint, and the fallback is a sane
    backoff either way."""
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        seconds = float(raw.strip())
    except ValueError:
        return None
    return seconds if seconds >= 0 else None


def throttle_delay_s(
    attempt: int,
    retry_after: float | None,
    *,
    rand: Callable[[], float] = random.random,
) -> float:
    """How long to wait before retry `attempt` (0-based). Never zero-variance.

    `rand` is injected so the jitter is assertable in a test — an un-jittered backoff
    passes every "does it retry" test ever written and still takes the platform down.
    """
    if retry_after is not None:
        # Their number is a FLOOR. Jitter goes on top so we do not all wake together
        # at exactly the moment they told everyone to wake.
        return retry_after + THROTTLE_BASE_S * rand()
    # Full jitter over an exponentially growing ceiling: the delay is uniform in
    # [0, capped], so two workers throttled in the same second do not wake in the same
    # second. A fixed backoff would just move the herd, not disperse it.
    capped = min(THROTTLE_BASE_S * (2.0**attempt), THROTTLE_MAX_SLEEP_S)
    return capped * rand()


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

# What the adapter treats a cost as when the payload does not say. Read off docs.bolna.ai
# and NOT confirmed against a live account — pilot gate 7 (OPERATIONS §2) is where it
# stops being an assumption. `CostBreakdown.currency_stated` carries the difference into
# every row, so a wrong guess is discoverable rather than baked in.
_ASSUMED_CURRENCY = "USD"
# Currencies this adapter can turn into INR. Anything else is refused rather than
# converted at the wrong rate — see `_cost`.
_CONVERTIBLE_CURRENCIES = frozenset({"USD", "INR"})


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


def parse_transcript(raw: str | None, call_id: str) -> tuple[list[TranscriptTurn], int]:
    """Prefix-tagged text -> typed turns, AND how many lines were lost. `(turns, lost)`.

    A continuation line with no prefix is appended to the previous turn rather than
    dropped — long agent answers wrap. Two lines genuinely cannot be placed, and both
    used to vanish without trace:

    * an unprefixed line arriving BEFORE any turn exists — there is no previous turn to
      append it to, and inventing a speaker for it would put words in someone's mouth;
    * a recognised prefix with an empty body.

    THE COUNT IS THE POINT. This returned a bare list, so a shape it does not recognise
    at all came back as `[]` — identical to a call where nobody spoke. Pilot gate 7's
    transcript criterion could therefore only ever detect a TOTAL parse failure, and a
    prefix-format change that cost us a third of every transcript would have looked like
    quiet callers (OPERATIONS §2). The count travels to `ExecutionSnapshot
    .transcript_lines_unparsed` and the gate scores it.

    A COUNT, not the lines. Hard rule 6: transcript text never leaves the engine
    boundary except as a `TranscriptTurn`, so what could not become one is measured and
    discarded rather than logged for later inspection.
    """
    if not raw:
        return [], 0
    turns: list[TranscriptTurn] = []
    lost = 0
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
            else:
                lost += 1
            continue
        speaker = _SPEAKER_MAP.get(match.group(1).lower(), "caller")
        text_value = match.group(2).strip()
        if not text_value:
            lost += 1
            continue
        turns.append(
            TranscriptTurn(
                call_id=call_id,
                idx=len(turns),
                speaker=speaker,
                text=text_value,
            )
        )
    return turns, lost


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
        for attempt in range(THROTTLE_MAX_ATTEMPTS):
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
            if response.status_code != THROTTLE_STATUS:
                break
            retry_after = _retry_after_seconds(response)
            last_attempt = attempt == THROTTLE_MAX_ATTEMPTS - 1
            if last_attempt or (retry_after is not None and retry_after > THROTTLE_MAX_SLEEP_S):
                break
            log.warning("engine_throttled", extra={"route": path, "attempt": attempt + 1})
            await asyncio.sleep(throttle_delay_s(attempt, retry_after))

        if response.status_code == THROTTLE_STATUS:
            # Distinct from `engine_rejected` on purpose. A throttle says nothing about
            # the request — so on the campaign path it must not burn a contact's retry
            # budget for a reason that has nothing to do with the contact. `transient`
            # is the ladder rung that means "identical retry can work" (503, retryable).
            log.warning("engine_throttle_exhausted", extra={"route": path})
            raise ProblemError(
                kind="transient",
                code="engine_rate_limited",
                title="Voice engine is rate limiting us",
                detail="The voice platform is temporarily refusing new requests.",
                remediation="This will be retried automatically.",
                failure_stage="CORE_LOGIC",
            )
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
        if not response.content:
            # A successful DELETE may answer 204/empty. `response.json()` raises on an
            # empty body, and a delete that "failed" only because the vendor said
            # nothing is the worst possible lie on this particular path.
            return {}
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

    # --- knowledge base ------------------------------------------------------
    #
    # Their surface, and how far each part of it is actually verified (TRD §5 records
    # it as "rag_id CRUD API (POST/GET/DELETE /knowledgebase)", and their published API
    # reference indexes POST /knowledgebase, GET /knowledgebase/all,
    # GET /knowledgebase/{rag_id}, DELETE /knowledgebase/{rag_id}):
    #
    # * VERIFIED from published docs — the ROUTES and the fact that a knowledge base is
    #   addressed by the vendor's own `rag_id`. Note what that rules out: our
    #   `kb_sources.id` is not a key on their side, so `DELETE /knowledgebase/<our uuid>`
    #   would 404 forever while looking like a working detach. The id we delete by must
    #   be the one POST handed back, which is why `attach_kb` now returns it.
    # * UNVERIFIED until the pilot — every BODY on this path. Bolna publishes no OpenAPI
    #   spec, so the create payload here, the `rag_id` field name in its response, and
    #   the row shape of the list are hand-maintained claims (the module docstring's
    #   standing warning). Two specifically to settle at gate 8:
    #     (a) does the list response carry the agent linkage this filters on? Our account
    #         holds every tenant's agents, so `list_kb` filters STRICTLY — a row that
    #         does not name this agent is not attributed to it.
    #     (b) does deleting the knowledge base also drop the agent's reference to it, or
    #         does the agent config keep a dangling `rag_id`? If the latter, detach grows
    #         a second call (an agent update) — it does NOT become optional.

    async def attach_kb(self, ref: EngineAgentRef, source: KBSourceRef) -> EngineKBRef:
        """Built-in KB (`rag_id`). Under BYOK the KB is NOT a model slot (D-33): this
        is a document push, and multilingual mode is IMMUTABLE at KB creation — Telugu
        retrieval quality is pilot gate 8.

        The returned handle is the ONLY way this document can ever be removed again, so
        a response we cannot read a handle out of is a failure, not a success: treating
        it as one would attach text nobody can retract.
        """
        data = await self._request(
            "POST",
            "/knowledgebase",
            json={"agent_id": ref, "name": source.title, "text": source.text},
        )
        rag_id = data.get("rag_id") or data.get("id")
        if not isinstance(rag_id, str) or not rag_id:
            raise ProblemError(
                kind="dependency",
                code="engine_bad_response",
                title="Voice engine returned an unusable response",
                detail="The voice platform did not return a knowledge base id.",
            )
        return rag_id

    async def detach_kb(self, ref: EngineAgentRef, kb: EngineKBRef) -> None:
        """`DELETE /knowledgebase/{rag_id}`.

        No swallowing of the vendor's 404: an id we cannot delete is an id we cannot
        prove is gone, and the caller's next act is to publish a replacement.
        """
        await self._request("DELETE", f"/knowledgebase/{kb}")

    async def list_kb(self, ref: EngineAgentRef) -> list[EngineKBRef]:
        data = await self._request("GET", "/knowledgebase/all")
        rows = data.get("data")
        if not isinstance(rows, list):
            rows = data.get("knowledgebases")
        if not isinstance(rows, list):
            return []
        handles: list[EngineKBRef] = []
        for row in rows:
            if not isinstance(row, dict) or str(row.get("agent_id") or "") != ref:
                continue
            rag_id = row.get("rag_id") or row.get("id")
            if isinstance(rag_id, str) and rag_id:
                handles.append(rag_id)
        return handles

    # --- reading the truth ---------------------------------------------------

    def _snapshot(self, payload: dict[str, Any]) -> ExecutionSnapshot:
        raw_status = str(payload.get("status") or "").lower()
        status = _STATUS_MAP.get(raw_status, "failed")
        call_id = str(payload.get("id") or payload.get("execution_id") or "")
        cost = self._cost(payload)
        turns, unparsed = parse_transcript(payload.get("transcript"), call_id)
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
            transcript=turns,
            transcript_lines_unparsed=unparsed,
            cost=cost,
            # Their `completed` timestamp where they give one, else the instant we
            # OBSERVED it — which is what the poller's tick resolution actually buys and
            # is honest about being a ceiling. Absent until the execution is billable,
            # so it never reads as "ready at" for a call that is not.
            billable_ready_at=(
                _parse_dt(payload.get("completed_at")) or datetime.now(UTC)
                if raw_status == "completed"
                else None
            ),
            engine_extracted=payload.get("extracted_data") or {},
            engine="bolna",
        )

    def _cost(self, payload: dict[str, Any]) -> CostBreakdown | None:
        """USD cents -> INR, and an honest account of whether "USD cents" is a FACT.

        Bolna publishes no OpenAPI spec, so "costs arrive in USD cents" is a claim read
        off their docs, not a guarantee — and it is worth 83x. This used to write
        `source_currency="USD"` as a literal, which made the assumption unfalsifiable
        from inside: pilot gate 7's currency criterion read our own guess back and
        agreed with it (OPERATIONS §2). Three behaviours now, in order:

        * the payload NAMES a currency we can convert -> use it, `currency_stated=True`,
          and the gate has a fact to score;
        * the payload names a currency we have no rate for -> refuse. Returning a number
          converted at the USD rate would be a fabricated cost basis flowing into the
          margin panel and every invoice. An absent cost is a visible gap; a wrong one
          is not;
        * the payload names nothing -> convert on the house assumption, exactly as
          before, but stamp `currency_stated=False` so the row says which it is.

        The refusal logs at WARNING with the currency and the execution id — ids only,
        never the payload (hard rule 6).
        """
        total = payload.get("total_cost")
        if total is None:
            return None

        stated = payload.get("currency") or payload.get("cost_currency")
        currency = str(stated).strip().upper() if stated else _ASSUMED_CURRENCY
        if currency not in _CONVERTIBLE_CURRENCIES:
            log.warning(
                "engine_cost_currency_unsupported",
                extra={
                    "engine": "bolna",
                    "currency": currency,
                    "engine_call_id": str(payload.get("id") or payload.get("execution_id") or ""),
                },
            )
            return None

        # INR needs no conversion, and multiplying it by the USD rate is precisely the
        # 83x error this branch exists to prevent.
        rate = Decimal(1) if currency == "INR" else self._fx_rate
        breakdown = payload.get("cost_breakdown") or {}
        total_inr = _to_inr(total, rate)
        if total_inr is None:
            return None
        return CostBreakdown(
            total_inr=total_inr,
            platform_inr=_to_inr(breakdown.get("platform"), rate),
            network_inr=_to_inr(breakdown.get("network"), rate),
            llm_inr=_to_inr(breakdown.get("llm"), rate),
            tts_inr=_to_inr(breakdown.get("synthesizer"), rate),
            stt_inr=_to_inr(breakdown.get("transcriber"), rate),
            source_currency=currency,
            currency_stated=stated is not None,
            source_amount=Decimal(str(total)) / Decimal(100),
            fx_rate=rate,
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


__all__ = [
    "ALLOWED_SOURCE_IPS",
    "BASE_URL",
    "THROTTLE_MAX_ATTEMPTS",
    "THROTTLE_MAX_SLEEP_S",
    "THROTTLE_STATUS",
    "BolnaEngine",
    "parse_transcript",
    "throttle_delay_s",
]
