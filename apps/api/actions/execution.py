"""Execute one in-call action — the single place bindings, credentials, SSRF vetting and
the external call meet.

Called synchronously from the voice-runtime tool endpoint (during a call) and from the
post-call worker (after-call triggers) and from the Test harness. Bolna blocks on the
response and feeds it back to the LLM, with the tool's `pre_call_message` masking the round
trip to the caller — so this returns the external system's answer, it does not defer it. The
one thing that IS deferred is the audit row: it goes to ARQ so this path writes no DB row of
its own, matching the opt-out tool's discipline (hard rule 3).

WHY A SYNCHRONOUS EXTERNAL CALL IS ALLOWED HERE. A data-returning in-call tool cannot defer
its result — the whole point is to hand the LLM the order status / the availability. CLAUDE.md
carves exactly this out ("except the in-call RAG tool endpoint which has a 100ms budget —
measure it"); an action's ceiling is Bolna's undocumented tool timeout (OPERATIONS §2 gate 8),
which `pre_call_message` is the vendor's own answer to. The call is bounded by `_TIMEOUT_S`
and vetted by the egress guard so a hostile config cannot turn it into an SSRF primitive.

HARD RULE 6. Nothing here logs a phone number, a message body or an external payload. The
audit summary carries ids, the kind/provider and the outcome — never a value.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import calendar as gcal
from apps.api.actions import whatsapp as wa
from apps.api.actions.credentials import resolve_secret
from apps.api.actions.schema import (
    CalendarConfig,
    CustomApiConfig,
    ParamSpec,
    PreparedRequest,
    WhatsAppConfig,
)
from apps.api.actions.service import LoadedTool
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue
from apps.api.integrations.egress_guard import EgressRefusedError, assert_public_http_url

log = get_logger(__name__)

# The ARQ job that appends the audit row. Spelled here (with the enqueuer) rather than
# imported from the worker, following `integrations.service.OUTBOUND_WEBHOOK_JOB`. Asserted
# equal to `apps.workers.action_audit.ACTION_AUDIT_JOB` by a test.
ACTION_AUDIT_JOB = "record_action_invocation"

# Bounded so a hung external endpoint cannot hold the caller's turn open forever. Generous
# because Bolna documents no tool timeout and the caller is hearing `pre_call_message`.
_TIMEOUT_S = 8.0

# The most external-response text handed back to the LLM. A phone-call reply is short; a
# multi-megabyte body would blow the prompt and the latency both.
_MAX_RESPONSE_CHARS = 4000


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """What the tool endpoint returns to Bolna (and the LLM). `ok` is for our own
    accounting; `payload` is the JSON the model reads."""

    ok: bool
    payload: dict[str, Any]
    #: Short outcome code for the audit row (`delivered`, `http_502`, `not_opted_in`, …).
    status: str


def resolve_values(params: list[dict[str, Any]], received: dict[str, Any]) -> dict[str, Any]:
    """The value of every binding by name: static from the spec, ai/lead_var from what
    Bolna sent us. A missing ai/lead_var value resolves to None and the field is dropped
    downstream rather than sent as the string "None"."""
    values: dict[str, Any] = {}
    for raw in params:
        spec = ParamSpec.model_validate(raw)
        if spec.source == "static":
            values[spec.name] = spec.value
        else:
            values[spec.name] = received.get(spec.name)
    return values


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


async def _send(request: PreparedRequest, *, client: httpx.AsyncClient) -> httpx.Response:
    """Put one `PreparedRequest` on the wire after vetting its host. The egress guard is
    the SSRF gate for a custom-API URL the tenant chose; for our fixed vendor hosts it is
    defence in depth (https + public + port), which they pass."""
    vetted = await assert_public_http_url(request.url, field="url")
    return await client.request(
        request.method,
        vetted.url,
        headers=request.headers or None,
        json=request.json_body,
        data=request.form_body,
        follow_redirects=False,
    )


def _clip(text: str) -> str:
    return text if len(text) <= _MAX_RESPONSE_CHARS else text[:_MAX_RESPONSE_CHARS]


def _response_payload(response: httpx.Response) -> dict[str, Any]:
    """The external answer, shaped for the LLM. JSON passes through; anything else is
    clipped text."""
    try:
        body = response.json()
    except ValueError:
        return {"status_code": response.status_code, "body": _clip(response.text)}
    return {"status_code": response.status_code, "data": body}


async def execute_action(
    session: AsyncSession,
    *,
    tool: LoadedTool,
    received: dict[str, Any],
    source: str,
    client: httpx.AsyncClient | None = None,
    audit: bool = True,
) -> ExecutionResult:
    """Run one action end to end and return the result for the LLM.

    `received` is what Bolna sent (AI-extracted args + substituted call variables), keyed
    by param name. `source` is `in_call` / `after_call` / `test` for the audit trail.
    Raises nothing for an ordinary failure — a refusal is an `ExecutionResult` the agent can
    relay ("I couldn't reach the system, I'll note it down") rather than an exception that
    would surface to the caller as dead air.
    """
    owns = client is None
    http = client or httpx.AsyncClient(timeout=_TIMEOUT_S, follow_redirects=False)
    try:
        result = await _dispatch(session, tool=tool, received=received, client=http)
    except EgressRefusedError as exc:
        result = ExecutionResult(ok=False, payload={"error": exc.code}, status=exc.code)
    except httpx.HTTPError as exc:
        # The error TYPE is safe to surface; the URL/body never are (hard rule 6).
        result = ExecutionResult(
            ok=False, payload={"error": "unreachable"}, status=type(exc).__name__
        )
    finally:
        if owns:
            await http.aclose()

    if audit:
        # DEFERRED so this path writes no DB row (hard rule 3). Ids and outcome only.
        await enqueue(
            ACTION_AUDIT_JOB,
            {
                "tenant_id": str(tool.tenant_id),
                "agent_id": str(tool.agent_id),
                "tool_id": str(tool.id),
                "kind": tool.kind,
                "provider": tool.provider or "",
                "status": result.status,
                "source": source,
            },
        )
    return result


async def _dispatch(
    session: AsyncSession, *, tool: LoadedTool, received: dict[str, Any], client: httpx.AsyncClient
) -> ExecutionResult:
    values = resolve_values(tool.params, received)
    if tool.kind == "custom_api":
        return await _run_custom_api(session, tool=tool, values=values, client=client)
    if tool.kind == "whatsapp":
        return await _run_whatsapp(session, tool=tool, values=values, client=client)
    return await _run_calendar(session, tool=tool, values=values, client=client)


async def _credential_secret(session: AsyncSession, tool: LoadedTool) -> str | None:
    if tool.credential_id is None:
        return None
    return await resolve_secret(session, tenant_id=tool.tenant_id, credential_id=tool.credential_id)


# --------------------------------------------------------------- custom API ----


async def _run_custom_api(
    session: AsyncSession, *, tool: LoadedTool, values: dict[str, Any], client: httpx.AsyncClient
) -> ExecutionResult:
    config = CustomApiConfig.model_validate(tool.config)
    headers = {
        f.key: _stringify(values.get(f.param))
        for f in config.headers
        if values.get(f.param) is not None
    }
    query = {
        f.key: _stringify(values.get(f.param))
        for f in config.query
        if values.get(f.param) is not None
    }
    # Auth from the saved credential — never a static param (see `CustomApiConfig`).
    secret = await _credential_secret(session, tool)
    if secret is not None:
        headers[config.auth_header] = f"{config.auth_scheme}{secret}"
    body: dict[str, Any] | None = None
    if config.method == "POST":
        body = {f.key: values.get(f.param) for f in config.body if values.get(f.param) is not None}
        headers.setdefault("Content-Type", "application/json")
    url = config.url + (("?" + _qs(query)) if query else "")
    request = PreparedRequest(method=config.method, url=url, headers=headers, json_body=body)
    response = await _send(request, client=client)
    ok = 200 <= response.status_code < 300
    return ExecutionResult(
        ok=ok, payload=_response_payload(response), status=f"http_{response.status_code}"
    )


def _qs(query: dict[str, str]) -> str:
    from urllib.parse import urlencode

    return urlencode(query)


# ----------------------------------------------------------------- whatsapp ----


async def _run_whatsapp(
    session: AsyncSession, *, tool: LoadedTool, values: dict[str, Any], client: httpx.AsyncClient
) -> ExecutionResult:
    config = WhatsAppConfig.model_validate(tool.config)
    recipient = values.get(config.recipient_param)
    if not recipient:
        return ExecutionResult(ok=False, payload={"error": "no_recipient"}, status="no_recipient")
    recipient = _stringify(recipient)
    # The dispatch gate AND the caller's messaging consent, in that order — the same two
    # questions `workers/whatsapp._send_escalation` asks, because one outbound channel
    # may not have two answers to "may we contact this person" (hard rule 5). This path
    # asked only the second until the audit found the split: a number on the tenant's DNC
    # list that had once granted messaging consent was refused by the campaign leg and
    # messaged by this one.
    try:
        await wa.assert_recipient_may_be_messaged(
            session,
            tenant_id=tool.tenant_id,
            agent_id=tool.agent_id,
            recipient_e164=recipient,
        )
    except wa.WhatsAppBlockedError as exc:
        return ExecutionResult(ok=False, payload={"error": exc.code}, status="blocked")
    except wa.WhatsAppNotOptedInError as exc:
        return ExecutionResult(ok=False, payload={"error": exc.code}, status="not_opted_in")

    secret = await _credential_secret(session, tool)
    if secret is None and tool.provider != "custom":
        return ExecutionResult(ok=False, payload={"error": "no_credential"}, status="no_credential")
    header_value = (
        _stringify(values[config.header_param])
        if config.header_param and values.get(config.header_param) is not None
        else None
    )
    body_values = [
        _stringify(values[name]) for name in config.body_params if values.get(name) is not None
    ]

    if tool.provider == "aisensy":
        request = wa.build_aisensy(
            config, api_key=secret or "", recipient_e164=recipient, body_values=body_values
        )
    elif tool.provider == "meta_cloud":
        request = wa.build_meta_cloud(
            config,
            access_token=secret or "",
            recipient_e164=recipient,
            header_value=header_value,
            body_values=body_values,
        )
    elif tool.provider == "interakt":
        request = wa.build_interakt(
            config,
            api_key=secret or "",
            recipient_e164=recipient,
            header_value=header_value,
            body_values=body_values,
        )
    else:  # custom — the "Other WhatsApp provider" fallback routes through Custom API
        return ExecutionResult(
            ok=False,
            payload={"error": "custom_whatsapp_uses_custom_api"},
            status="misconfigured",
        )

    response = await _send(request, client=client)
    ok = 200 <= response.status_code < 300
    return ExecutionResult(
        ok=ok,
        payload={"status": "sent"}
        if ok
        else {"error": "send_failed", "status_code": response.status_code},
        status="delivered" if ok else f"http_{response.status_code}",
    )


# ----------------------------------------------------------------- calendar ----


async def _run_calendar(
    session: AsyncSession, *, tool: LoadedTool, values: dict[str, Any], client: httpx.AsyncClient
) -> ExecutionResult:
    config = CalendarConfig.model_validate(tool.config)
    refresh_token = await _credential_secret(session, tool)
    if refresh_token is None:
        return ExecutionResult(ok=False, payload={"error": "no_credential"}, status="no_credential")
    # Mint an access token from the stored refresh token.
    token_resp = await _send(gcal.token_refresh_request(refresh_token=refresh_token), client=client)
    if token_resp.status_code != 200:
        return ExecutionResult(
            ok=False, payload={"error": "auth_failed"}, status=f"token_{token_resp.status_code}"
        )
    access_token = str(token_resp.json().get("access_token") or "")
    if not access_token:
        return ExecutionResult(ok=False, payload={"error": "auth_failed"}, status="token_empty")

    start = values.get(config.start_param) if config.start_param else None
    if not start:
        return ExecutionResult(ok=False, payload={"error": "no_start_time"}, status="no_start_time")
    start = _stringify(start)

    if config.operation == "check":
        end = (
            _stringify(values.get(config.end_param))
            if config.end_param and values.get(config.end_param)
            else start
        )
        request = gcal.build_freebusy(
            calendar_id=config.calendar_id, time_min=start, time_max=end, access_token=access_token
        )
        response = await _send(request, client=client)
        if response.status_code != 200:
            return ExecutionResult(
                ok=False, payload={"error": "calendar_error"}, status=f"http_{response.status_code}"
            )
        busy = response.json().get("calendars", {}).get(config.calendar_id, {}).get("busy", [])
        return ExecutionResult(
            ok=True, payload={"available": len(busy) == 0, "busy": busy}, status="checked"
        )

    # book
    end = (
        _stringify(values.get(config.end_param))
        if config.end_param and values.get(config.end_param)
        else _plus_minutes(start, config.duration_min or 30)
    )
    summary = (
        _stringify(values.get(config.summary_param))
        if config.summary_param and values.get(config.summary_param)
        else "Appointment"
    )
    request = gcal.build_book(
        calendar_id=config.calendar_id,
        start=start,
        end=end,
        summary=summary,
        access_token=access_token,
    )
    response = await _send(request, client=client)
    ok = 200 <= response.status_code < 300
    if not ok:
        return ExecutionResult(
            ok=False,
            payload={"error": "booking_failed", "status_code": response.status_code},
            status=f"http_{response.status_code}",
        )
    event_id = str(response.json().get("id") or "")
    return ExecutionResult(
        ok=True, payload={"status": "booked", "event_id": event_id}, status="booked"
    )


def _plus_minutes(start_iso: str, minutes: int) -> str:
    """`start` + duration as RFC 3339, when the client gave a duration rather than an end.
    Falls back to returning the start unchanged if it cannot be parsed — the API then
    refuses, which surfaces as a booking error the agent can relay, rather than a crash."""
    from datetime import datetime, timedelta

    try:
        dt = datetime.fromisoformat(start_iso)
    except ValueError:
        return start_iso
    return (dt + timedelta(minutes=minutes)).isoformat()


__all__ = [
    "ACTION_AUDIT_JOB",
    "ExecutionResult",
    "execute_action",
    "resolve_values",
]
