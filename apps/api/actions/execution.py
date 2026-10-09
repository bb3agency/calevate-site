"""Execute one action — the single place bindings, credentials, SSRF vetting and the
external call meet, for every engine and every trigger.

Callers: the in-call doors (`in_call.run_in_call_action`, reached by the ThinnestAI custom
action route and by the Pipecat worker's tool route), the background job that finishes a slow
in-call write (`workers/client_actions.py`), and the client's Test button. ONE executor, so an
action behaves the same however it was invoked (D-700).

THE BUDGET. A caller is waiting on an in-call action. ThinnestAI asks an action's endpoint to
"Answer within 10 seconds" (snapshots/2026-10-08/pages/mcp/own-database.md:48) and reads
about 4,000 characters of the answer (api-reference/actions/test-action.md, `result`). Each
external request here is bounded by `REQUEST_TIMEOUT_S` and the whole action by the caller's
`budget_s`; a write whose result the agent does not need to speak (a CRM push, a sheet row)
is acknowledged at once and finished in the background by the caller of this module.

WHAT THE MODEL SEES. Every answer handed back passes `for_model`: clipped to
`MAX_ANSWER_CHARS` and run through the platform's redaction pass, so a client API that
returns a card number, an email or another customer's phone never reaches a prompt (and so
never the caller's ear). A custom API's response body is read to at most
`MAX_RESPONSE_BYTES` before it is parsed, and redirects are never followed (a 3xx is
reported as that status), so a redirect cannot carry a request past the egress guard.

THE CALLER'S NUMBER is `CallFacts.caller_e164`, our record of who is on the line — the voice
platform's `phone` on the call, or the call row. A `lead_var` binding is filled from it and
NOTHING the engine or the model sent can override it.

HARD RULE 6. Nothing here logs a phone number, a message body or an external payload. The
audit summary carries ids, the kind/provider, the outcome and the duration — never a value.
"""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Final
from urllib.parse import urlencode
from uuid import UUID

import httpx
from calevate_shared.calling_window import IST
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions import calendar as gcal
from apps.api.actions import crm, oauth
from apps.api.actions import payment_links as rzp
from apps.api.actions import sheets as gsheets
from apps.api.actions import whatsapp as wa
from apps.api.actions.credentials import (
    CredentialUnusableError,
    ResolvedCredential,
    resolve_credential,
)
from apps.api.actions.schema import (
    CalendarConfig,
    CallerLookupConfig,
    CrmConfig,
    CustomApiConfig,
    ParamSpec,
    PaymentLinkConfig,
    PreparedRequest,
    SheetsConfig,
    WhatsAppConfig,
)
from apps.api.actions.service import LoadedTool
from apps.api.compliance.trial_access import restricting_trial
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue
from apps.api.integrations.egress_guard import (
    EgressRefusedError,
    assert_public_http_url,
    egress_client,
)
from apps.workers.redaction import redact

log = get_logger(__name__)

# The ARQ job that appends the audit row. Spelled here (with the enqueuer) rather than
# imported from the worker, following `integrations.service.OUTBOUND_WEBHOOK_JOB`. Asserted
# equal to `apps.workers.action_audit.ACTION_AUDIT_JOB` by a test.
ACTION_AUDIT_JOB = "record_action_invocation"

#: One external request. Two fit inside the in-call budget with room for a token refresh.
REQUEST_TIMEOUT_S: Final = 4.0
#: The most of an external response we read before parsing it.
MAX_RESPONSE_BYTES: Final = 64 * 1024
#: The most answer text handed to the model: what the voice platform reads (~4,000).
MAX_ANSWER_CHARS: Final = 4000
#: How many free slots a calendar check offers.
FREE_SLOTS_OFFERED: Final = 3

_IST = timezone(IST)


@dataclass(frozen=True, slots=True)
class CallFacts:
    """What we know about the call an action runs on, from OUR records — never the model."""

    #: The engine's call id (or our calls.id on a test). Ids only; safe to audit.
    call_ref: str | None
    #: The other party on the line, E.164.
    caller_e164: str | None
    direction: str | None = None


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """What an execution returns. `ok` is for our own accounting; `payload` is the JSON the
    model reads (already redacted and clipped); `status` is the outcome code the audit row
    and the spoken answer key on."""

    ok: bool
    payload: dict[str, Any]
    status: str


def _refused(status: str, **payload: Any) -> ExecutionResult:
    return ExecutionResult(ok=False, payload={"error": status, **payload}, status=status)


def resolve_values(params: list[dict[str, Any]], received: dict[str, Any]) -> dict[str, Any]:
    """The value of every binding by name: static from the spec, ai/lead_var from what was
    received. A missing value resolves to None and the field is dropped downstream rather
    than sent as the string "None"."""
    values: dict[str, Any] = {}
    for raw in params:
        spec = ParamSpec.model_validate(raw)
        if spec.source == "static":
            values[spec.name] = spec.value
        else:
            values[spec.name] = received.get(spec.name)
    return values


def lead_values(params: list[dict[str, Any]], call: CallFacts) -> dict[str, Any]:
    """`lead_var` bindings filled from our record of the call."""
    inbound = call.direction != "outbound"
    facts = {
        "caller_phone": call.caller_e164,
        "from_number": call.caller_e164 if inbound else None,
        "to_number": None if inbound else call.caller_e164,
        "call_sid": call.call_ref,
    }
    out: dict[str, Any] = {}
    for raw in params:
        spec = ParamSpec.model_validate(raw)
        if spec.source == "lead_var" and spec.lead_var is not None:
            out[spec.name] = facts.get(spec.lead_var)
    return out


def _stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def for_model(value: Any) -> Any:
    """Redact every string the model will read (phones, emails, cards, OTPs, …), recursively,
    then bound the whole answer. Names and ordinary words pass untouched."""
    if isinstance(value, str):
        return redact(value).text
    if isinstance(value, dict):
        return {str(k): for_model(v) for k, v in value.items()}
    if isinstance(value, list):
        return [for_model(v) for v in value]
    return value


def _bounded(payload: dict[str, Any]) -> dict[str, Any]:
    redacted = for_model(payload)
    encoded = json.dumps(redacted, ensure_ascii=False, default=str)
    if len(encoded) <= MAX_ANSWER_CHARS:
        return dict(redacted)
    return {"truncated": True, "text": encoded[:MAX_ANSWER_CHARS]}


async def _send(request: PreparedRequest, *, client: httpx.AsyncClient) -> httpx.Response:
    """Put one `PreparedRequest` on the wire after vetting its host, reading at most
    `MAX_RESPONSE_BYTES` of the answer. Never follows a redirect."""
    vetted = await assert_public_http_url(request.url, field="url")
    req = client.build_request(
        request.method,
        vetted.url,
        headers=request.headers or None,
        json=request.json_body,
        data=request.form_body,
        timeout=REQUEST_TIMEOUT_S,
    )
    response = await client.send(req, stream=True, follow_redirects=False)
    try:
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk[: MAX_RESPONSE_BYTES - len(body)])
            if len(body) >= MAX_RESPONSE_BYTES:
                break
    finally:
        await response.aclose()
    return httpx.Response(
        response.status_code, headers=response.headers, content=bytes(body), request=req
    )


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _ok(response: httpx.Response) -> bool:
    return 200 <= response.status_code < 300


async def execute_action(
    session: AsyncSession,
    *,
    tool: LoadedTool,
    received: dict[str, Any],
    source: str,
    client: httpx.AsyncClient | None = None,
    audit: bool = True,
    call: CallFacts | None = None,
    budget_s: float | None = None,
) -> ExecutionResult:
    """Run one action end to end and return the result for the model.

    `received` holds AI-extracted arguments keyed by param name; `call` is our record of the
    call (its `lead_var` values win over anything received). `source` is `in_call` /
    `background` / `after_call` / `test` for the audit trail. Raises nothing for an ordinary
    failure — a refusal is an `ExecutionResult` the agent can relay rather than an exception
    that would surface to the caller as dead air.
    """
    started = time.monotonic()
    facts = call or CallFacts(call_ref=None, caller_e164=None)
    # With a call in hand its values are the only ones a call variable may take; without
    # one (a caller that supplies its own, such as a unit of the executor) `received` is used.
    merged = {**received, **lead_values(tool.params, call)} if call is not None else received
    owns = client is None
    http = client or egress_client(timeout=REQUEST_TIMEOUT_S, follow_redirects=False)
    try:
        if budget_s is None:
            result = await _dispatch(session, tool=tool, received=merged, call=facts, client=http)
        else:
            async with asyncio.timeout(budget_s):
                result = await _dispatch(
                    session, tool=tool, received=merged, call=facts, client=http
                )
    except TimeoutError:
        result = _refused("timeout")
    except EgressRefusedError as exc:
        result = _refused(exc.code)
    except CredentialUnusableError:
        result = _refused("credential_unusable")
    except ProblemError as exc:
        # A refusal of ours mid-action (the platform's sign-in app was removed, a builder
        # refused a config): an answer the agent can say, never a 500 on a live call.
        result = _refused(exc.code)
    except httpx.HTTPError as exc:
        # The error TYPE is safe to surface; the URL/body never are (hard rule 6).
        result = ExecutionResult(
            ok=False, payload={"error": "unreachable"}, status=type(exc).__name__
        )
    finally:
        if owns:
            await http.aclose()
    result = ExecutionResult(ok=result.ok, payload=_bounded(result.payload), status=result.status)

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
                "call_ref": facts.call_ref or "",
                "duration_ms": int((time.monotonic() - started) * 1000),
            },
        )
    return result


async def _dispatch(
    session: AsyncSession,
    *,
    tool: LoadedTool,
    received: dict[str, Any],
    call: CallFacts,
    client: httpx.AsyncClient,
) -> ExecutionResult:
    values = resolve_values(tool.params, received)
    if tool.kind == "custom_api":
        return await _run_custom_api(session, tool=tool, values=values, client=client)
    if tool.kind == "whatsapp":
        return await _run_whatsapp(session, tool=tool, values=values, client=client, call=call)
    if tool.kind == "calendar":
        return await _run_calendar(session, tool=tool, values=values, client=client, call=call)
    if tool.kind == "sheets":
        return await _run_sheets(tool=tool, values=values, client=client, call=call)
    if tool.kind == "payment_link":
        return await _run_payment_link(session, tool=tool, values=values, client=client, call=call)
    if tool.kind == "crm":
        return await _run_crm(session, tool=tool, values=values, client=client, call=call)
    if tool.kind == "caller_lookup":
        return await _run_caller_lookup(session, tool=tool, client=client, call=call)
    return _refused("misconfigured")


async def _credential(
    session: AsyncSession, tool: LoadedTool, credential_id: UUID | None = None
) -> ResolvedCredential | None:
    cid = credential_id or tool.credential_id
    if cid is None:
        return None
    return await resolve_credential(session, tenant_id=tool.tenant_id, credential_id=cid)


# --- OAuth access tokens ---------------------------------------------------------------

#: Access tokens minted from a stored refresh token, keyed by (credential id, version): a
#: rotation bumps the version and so never reuses a token from the old grant. Process-local
#: and short-lived; the refresh token stays the only durable credential.
_ACCESS: dict[tuple[str, int], tuple[str, float, dict[str, Any]]] = {}
_ACCESS_SKEW_S: Final = 60.0


def reset_access_cache() -> None:
    _ACCESS.clear()


async def _access_token(
    cred: ResolvedCredential, *, credential_id: UUID, client: httpx.AsyncClient
) -> tuple[str, dict[str, Any]] | None:
    """(access token, token response extras such as Zoho's `api_domain`), or None."""
    key = (str(credential_id), cred.version)
    now = time.monotonic()
    cached = _ACCESS.get(key)
    if cached is not None and cached[1] > now:
        return cached[0], cached[2]
    if cred.kind not in oauth.OAUTH_KINDS:
        return None
    kind: oauth.OAuthKind = cred.kind
    accounts = cred.non_secret.get("accounts_server")
    request = oauth.refresh_request(
        kind,
        refresh_token=cred.secret,
        accounts_server=accounts if isinstance(accounts, str) else None,
    )
    response = await _send(request, client=client)
    body = _json(response)
    if response.status_code != 200 or not isinstance(body, dict):
        log.info(
            "action_token_refresh_refused", extra={"kind": kind, "status": response.status_code}
        )
        return None
    token = str(body.get("access_token") or "")
    if not token:
        return None
    try:
        ttl = float(body.get("expires_in") or 1800)
    except (TypeError, ValueError):
        ttl = 1800.0
    extras = {"api_domain": body.get("api_domain") or cred.non_secret.get("api_domain")}
    _ACCESS[key] = (token, now + max(ttl - _ACCESS_SKEW_S, 0.0), extras)
    return token, extras


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
    if tool.credential_id is not None:
        cred = await _credential(session, tool)
        if cred is None:
            return _refused("no_credential")
        headers[config.auth_header] = f"{config.auth_scheme}{cred.secret}"
    body: dict[str, Any] | None = None
    if config.method == "POST":
        body = {f.key: values.get(f.param) for f in config.body if values.get(f.param) is not None}
        headers.setdefault("Content-Type", "application/json")
    url = config.url + (("?" + urlencode(query)) if query else "")
    response = await _send(
        PreparedRequest(method=config.method, url=url, headers=headers, json_body=body),
        client=client,
    )
    data = _json(response)
    payload: dict[str, Any] = (
        {"status_code": response.status_code, "data": data}
        if data is not None
        else {"status_code": response.status_code, "body": response.text[:MAX_ANSWER_CHARS]}
    )
    return ExecutionResult(ok=_ok(response), payload=payload, status=f"http_{response.status_code}")


# ----------------------------------------------------------------- whatsapp ----


async def _send_template(
    session: AsyncSession,
    *,
    tool: LoadedTool,
    provider: str | None,
    credential_id: UUID | None,
    config: WhatsAppConfig,
    recipient: str,
    header_value: str | None,
    body_values: list[str],
    client: httpx.AsyncClient,
    test_recipient: bool = False,
) -> ExecutionResult:
    """The one WhatsApp send: the dispatch gate and the caller's messaging consent, then the
    provider's template request. Used by WhatsApp actions and by payment links."""
    try:
        if test_recipient:
            normalized = await wa.assert_business_contact_may_be_messaged(
                session, tenant_id=tool.tenant_id, agent_id=tool.agent_id, recipient_e164=recipient
            )
        else:
            normalized = await wa.assert_recipient_may_be_messaged(
                session, tenant_id=tool.tenant_id, agent_id=tool.agent_id, recipient_e164=recipient
            )
    except wa.WhatsAppBlockedError as exc:
        return ExecutionResult(ok=False, payload={"error": exc.code}, status="blocked")
    except wa.WhatsAppNotOptedInError as exc:
        return ExecutionResult(ok=False, payload={"error": exc.code}, status="not_opted_in")
    if provider == "custom":
        return _refused("misconfigured")
    cred = await _credential(session, tool, credential_id)
    if cred is None:
        return _refused("no_credential")
    if provider == "aisensy":
        request = wa.build_aisensy(
            config, api_key=cred.secret, recipient_e164=normalized, body_values=body_values
        )
    elif provider == "meta_cloud":
        request = wa.build_meta_cloud(
            config,
            access_token=cred.secret,
            recipient_e164=normalized,
            header_value=header_value,
            body_values=body_values,
        )
    elif provider == "interakt":
        request = wa.build_interakt(
            config,
            api_key=cred.secret,
            recipient_e164=normalized,
            header_value=header_value,
            body_values=body_values,
        )
    else:
        return _refused("misconfigured")
    response = await _send(request, client=client)
    if _ok(response):
        return ExecutionResult(ok=True, payload={"status": "sent"}, status="delivered")
    return ExecutionResult(
        ok=False,
        payload={"error": "send_failed", "status_code": response.status_code},
        status=f"http_{response.status_code}",
    )


async def _run_whatsapp(
    session: AsyncSession,
    *,
    tool: LoadedTool,
    values: dict[str, Any],
    client: httpx.AsyncClient,
    call: CallFacts,
) -> ExecutionResult:
    config = WhatsAppConfig.model_validate(tool.config)
    recipient = values.get(config.recipient_param)
    if not recipient:
        return _refused("no_recipient")
    # Template variables are positional ({{1}}, {{2}}...): sending without one would move
    # every later value into its slot. Refused with the names, so the model can ask for them.
    template_bindings = ([config.header_param] if config.header_param else []) + list(
        config.body_params
    )
    missing = [name for name in template_bindings if values.get(name) is None]
    if missing:
        return _refused("missing_template_value", missing=missing)
    return await _send_template(
        session,
        tool=tool,
        provider=tool.provider,
        credential_id=tool.credential_id,
        config=config,
        recipient=_stringify(recipient),
        header_value=_stringify(values[config.header_param]) if config.header_param else None,
        body_values=[_stringify(values[name]) for name in config.body_params],
        client=client,
        test_recipient=call.direction == "test",
    )


# ----------------------------------------------------------------- calendar ----


def _rfc3339(value: Any) -> datetime | None:
    """A model-supplied time as an aware instant, or None when it is not an ISO 8601 time.

    RFC 3339 §5.6 requires an offset and a model often omits it. A time with none is read
    as IST — the caller's own clock in this India-only product — rather than sent bare for
    Google to guess at or refuse.
    """
    try:
        parsed = datetime.fromisoformat(_stringify(value).strip())
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=_IST)


def _busy(body: Any, calendar_id: str) -> list[tuple[datetime, datetime]] | None:
    """The busy intervals freeBusy answered, or None when it answered an error for the
    calendar (a calendar we cannot read is not a free one)."""
    entry = body.get("calendars", {}).get(calendar_id, {}) if isinstance(body, dict) else {}
    if not isinstance(entry, dict) or entry.get("errors"):
        return None
    out: list[tuple[datetime, datetime]] = []
    for row in entry.get("busy") or []:
        start, end = _rfc3339(row.get("start")), _rfc3339(row.get("end"))
        if start is not None and end is not None:
            out.append((start, end))
    return out


def free_slots(
    *,
    window_start: datetime,
    window_end: datetime,
    minutes: int,
    busy: list[tuple[datetime, datetime]],
) -> list[datetime]:
    """Slot starts of `minutes` inside the window that overlap no busy interval (busy end is
    exclusive, as freeBusy says), stepping by the slot length."""
    step = timedelta(minutes=minutes)
    slots: list[datetime] = []
    at = window_start
    while at + step <= window_end and len(slots) < FREE_SLOTS_OFFERED:
        if all(not (at < end and at + step > start) for start, end in busy):
            slots.append(at)
        at += step
    return slots


def spoken_time(at: datetime) -> str:
    """`Tuesday 14 October, 4:00 PM` in India time — read aloud exactly as written."""
    local = at.astimezone(_IST)
    hour = local.strftime("%I").lstrip("0") or "12"
    day = f"{local.strftime('%A')} {local.day} {local.strftime('%B')}"
    return f"{day}, {hour}:{local.strftime('%M %p')}"


async def _run_calendar(
    session: AsyncSession,
    *,
    tool: LoadedTool,
    values: dict[str, Any],
    client: httpx.AsyncClient,
    call: CallFacts,
) -> ExecutionResult:
    config = CalendarConfig.model_validate(tool.config)
    raw_start = values.get(config.start_param) if config.start_param else None
    if not raw_start:
        return _refused("no_start_time")
    raw_end = values.get(config.end_param) if config.end_param else None
    if config.operation == "check" and not raw_end:
        # Not defaulted to the start: a window from a time to itself contains nothing, so
        # no calendar is busy in it and the answer would be "available" for a taken slot.
        return _refused("no_end_time")
    minutes = config.duration_min or 30
    start_at = _rfc3339(raw_start)
    end_at = (
        _rfc3339(raw_end)
        if raw_end
        else (start_at + timedelta(minutes=minutes) if start_at else None)
    )
    if start_at is None or end_at is None or end_at <= start_at:
        return _refused("unreadable_time")
    if start_at < datetime.now(UTC) - timedelta(minutes=5):
        return _refused("time_in_past")

    cred = await _credential(session, tool)
    if cred is None:
        return _refused("no_credential")
    access = await _access_token(cred, credential_id=tool.credential_id, client=client)  # type: ignore[arg-type]
    if access is None:
        return _refused("auth_failed")
    token = access[0]

    response = await _send(
        gcal.build_freebusy(
            calendar_id=config.calendar_id,
            time_min=start_at.isoformat(),
            time_max=end_at.isoformat(),
            access_token=token,
        ),
        client=client,
    )
    busy = _busy(_json(response), config.calendar_id) if response.status_code == 200 else None
    if busy is None:
        return _refused("calendar_error", status_code=response.status_code)

    if config.operation == "check":
        slots = free_slots(window_start=start_at, window_end=end_at, minutes=minutes, busy=busy)
        return ExecutionResult(
            ok=True,
            payload={
                "available": bool(slots) and slots[0] == start_at,
                "free_slots": [
                    {"start": s.astimezone(_IST).isoformat(), "say": spoken_time(s)} for s in slots
                ],
            },
            status="checked",
        )

    # book: the slot must be free in the diary at this moment, not when the caller asked.
    if any(start_at < end and end_at > start for start, end in busy):
        return ExecutionResult(
            ok=False, payload={"error": "slot_taken", "available": False}, status="slot_taken"
        )
    summary = (
        _stringify(values.get(config.summary_param))
        if config.summary_param and values.get(config.summary_param)
        else "Appointment"
    )
    description = "Booked on a phone call by your Calevate agent."
    if call.caller_e164:
        description += f" Caller: {call.caller_e164}"
    response = await _send(
        gcal.build_book(
            calendar_id=config.calendar_id,
            start=start_at.isoformat(),
            end=end_at.isoformat(),
            summary=summary[:200],
            description=description,
            access_token=token,
        ),
        client=client,
    )
    if not _ok(response):
        return _refused("booking_failed", status_code=response.status_code)
    body = _json(response)
    return ExecutionResult(
        ok=True,
        payload={
            "status": "booked",
            "event_id": str(body.get("id") or "") if isinstance(body, dict) else "",
            "say": spoken_time(start_at),
        },
        status="booked",
    )


# ------------------------------------------------------------------- sheets ----


def _header_index(headers: list[str], name: str) -> int | None:
    wanted = name.strip().casefold()
    for index, header in enumerate(headers):
        if header.strip().casefold() == wanted:
            return index
    return None


async def _run_sheets(
    *, tool: LoadedTool, values: dict[str, Any], client: httpx.AsyncClient, call: CallFacts
) -> ExecutionResult:
    config = SheetsConfig.model_validate(tool.config)
    token = await gsheets.bearer(client)
    if token is None:
        return _refused("sheets_not_configured")
    if config.operation == "lookup":
        return await _sheet_lookup(
            spreadsheet_id=config.spreadsheet_id,
            worksheet=config.worksheet,
            match_header=config.match_header or "",
            return_headers=config.return_headers,
            token=token,
            client=client,
            call=call,
        )
    if not call.call_ref:
        return _refused("no_call")
    return await _sheet_record(config, values=values, token=token, client=client, call=call)


def _sheet_failure(response: httpx.Response) -> ExecutionResult:
    if response.status_code in (403, 404):
        return _refused("sheet_not_shared", status_code=response.status_code)
    return _refused("sheet_error", status_code=response.status_code)


async def _sheet_record(
    config: SheetsConfig,
    *,
    values: dict[str, Any],
    token: str,
    client: httpx.AsyncClient,
    call: CallFacts,
) -> ExecutionResult:
    """One row per call: the headers we need are added to row 1 if missing, the call's row
    is found by our call column, and only our cells are written."""
    sheet_id, ws = config.spreadsheet_id, config.worksheet
    response = await _send(
        gsheets.read_range(spreadsheet_id=sheet_id, a1=f"{gsheets.a1_sheet(ws)}!1:1", token=token),
        client=client,
    )
    if response.status_code != 200:
        return _sheet_failure(response)
    rows = gsheets.rows_of(_json(response))
    headers = rows[0] if rows else []
    wanted = [gsheets.CALL_COLUMN_HEADER, *(c.header for c in config.columns)]
    added = [h for h in wanted if _header_index(headers, h) is None]
    if added:
        start = len(headers)
        response = await _send(
            gsheets.write_cells(
                spreadsheet_id=sheet_id,
                cells=[(gsheets.cell(ws, start + i, 1), h) for i, h in enumerate(added)],
                token=token,
            ),
            client=client,
        )
        if not _ok(response):
            return _sheet_failure(response)
        headers = [*headers, *added]
    key_col = _header_index(headers, gsheets.CALL_COLUMN_HEADER)
    assert key_col is not None
    letter = gsheets.column_letter(key_col)
    response = await _send(
        gsheets.read_range(
            spreadsheet_id=sheet_id, a1=f"{gsheets.a1_sheet(ws)}!{letter}:{letter}", token=token
        ),
        client=client,
    )
    if response.status_code != 200:
        return _sheet_failure(response)
    keys = [row[0] if row else "" for row in gsheets.rows_of(_json(response))]
    cells: dict[int, str] = {key_col: call.call_ref or ""}
    for column in config.columns:
        value = values.get(column.param)
        index = _header_index(headers, column.header)
        if value is not None and index is not None:
            cells[index] = _stringify(value)[:1000]
    if (call.call_ref or "") in keys:
        row_number = keys.index(call.call_ref or "") + 1
        response = await _send(
            gsheets.write_cells(
                spreadsheet_id=sheet_id,
                cells=[(gsheets.cell(ws, col, row_number), v) for col, v in cells.items()],
                token=token,
            ),
            client=client,
        )
        status = "row_updated"
    else:
        row = [""] * len(headers)
        for col, v in cells.items():
            row[col] = v
        response = await _send(
            gsheets.append_row(spreadsheet_id=sheet_id, worksheet=ws, row=row, token=token),
            client=client,
        )
        status = "row_added"
    if not _ok(response):
        return _sheet_failure(response)
    return ExecutionResult(ok=True, payload={"status": "saved"}, status=status)


async def _sheet_lookup(
    *,
    spreadsheet_id: str,
    worksheet: str,
    match_header: str,
    return_headers: list[str],
    token: str,
    client: httpx.AsyncClient,
    call: CallFacts,
) -> ExecutionResult:
    if not call.caller_e164:
        return _refused("no_caller_number")
    response = await _send(
        gsheets.read_range(
            spreadsheet_id=spreadsheet_id,
            a1=f"{gsheets.a1_sheet(worksheet)}!A1:ZZ{gsheets.LOOKUP_MAX_ROWS}",
            token=token,
        ),
        client=client,
    )
    if response.status_code != 200:
        return _sheet_failure(response)
    rows = gsheets.rows_of(_json(response))
    headers = rows[0] if rows else []
    column = _header_index(headers, match_header)
    if column is None:
        return _refused("sheet_column_missing")
    index = gsheets.find_row(rows, column=column, phone_e164=call.caller_e164)
    if index is None:
        return ExecutionResult(ok=True, payload={"found": False}, status="not_found")
    row = rows[index]
    details: dict[str, str] = {}
    for header in return_headers:
        at = _header_index(headers, header)
        if at is not None and at < len(row) and row[at].strip():
            details[header] = row[at][:500]
    return ExecutionResult(ok=True, payload={"found": True, "details": details}, status="found")


# ------------------------------------------------------------- payment link ----


def _amount(raw: Any) -> Decimal | None:
    if raw is None:
        return None
    cleaned = _stringify(raw).replace(",", "").replace("₹", "").replace("Rs.", "").replace("Rs", "")
    try:
        amount = Decimal(cleaned.strip())
    except InvalidOperation:
        return None
    return amount.quantize(Decimal("0.01")) if amount.is_finite() else None


async def _run_payment_link(
    session: AsyncSession,
    *,
    tool: LoadedTool,
    values: dict[str, Any],
    client: httpx.AsyncClient,
    call: CallFacts,
) -> ExecutionResult:
    """Create the link on the client's Razorpay and send it to the caller on WhatsApp."""
    if await restricting_trial(session, tenant_id=tool.tenant_id) is not None:
        # D-700 with D-697: no money moves on a trial test call, not even a client's.
        return _refused("trial_payment_links")
    config = PaymentLinkConfig.model_validate(tool.config)
    if not call.caller_e164:
        return _refused("no_caller_number")
    amount = config.fixed_amount_inr or _amount(values.get(config.amount_param or ""))
    if amount is None:
        return _refused("no_amount")
    if (
        not (config.min_amount_inr <= amount <= config.max_amount_inr)
        or rzp.paise(amount) < rzp.MIN_AMOUNT_PAISE
    ):
        return _refused(
            "amount_outside_rules",
            min_inr=str(config.min_amount_inr),
            max_inr=str(config.max_amount_inr),
        )
    cred = await _credential(session, tool)
    if cred is None:
        return _refused("no_credential")
    key_id = cred.non_secret.get("key_id")
    if not isinstance(key_id, str) or not key_id:
        return _refused("credential_unusable")
    reference = f"cv-{tool.id.hex[:12]}-{int(time.time())}"
    response = await _send(
        rzp.create_link(
            key_id=key_id,
            key_secret=cred.secret,
            amount_inr=amount,
            description=config.description,
            reference_id=reference,
            contact_e164=call.caller_e164,
            expire_minutes=config.expire_minutes,
        ),
        client=client,
    )
    body = _json(response)
    link = body.get("short_url") if isinstance(body, dict) else None
    if not _ok(response) or not isinstance(link, str) or not link.startswith("https://"):
        return _refused("link_not_created", status_code=response.status_code)
    message = config.message
    fills = {"link": link, "amount": f"{amount:.2f}", "description": config.description}
    sent = await _send_template(
        session,
        tool=tool,
        provider=message.provider,
        credential_id=message.credential_id,
        config=WhatsAppConfig(
            recipient_param="caller",
            template=message.template,
            language=message.language,
            phone_number_id=message.phone_number_id,
            country_code=message.country_code,
        ),
        recipient=call.caller_e164,
        header_value=None,
        body_values=[fills[name] for name in message.body_values],
        client=client,
        test_recipient=call.direction == "test",
    )
    if not sent.ok:
        # The link exists on the client's Razorpay and expires on its own; the caller was
        # not sent it, and the agent must not say they were.
        return ExecutionResult(
            ok=False,
            payload={"error": "link_not_sent", "reason": sent.status},
            status="link_not_sent",
        )
    return ExecutionResult(
        ok=True, payload={"status": "sent", "amount_inr": f"{amount:.2f}"}, status="link_sent"
    )


# ---------------------------------------------------------------------- crm ----


async def _crm_access(
    session: AsyncSession, tool: LoadedTool, client: httpx.AsyncClient
) -> tuple[str, dict[str, Any]] | ExecutionResult:
    cred = await _credential(session, tool)
    if cred is None:
        return _refused("no_credential")
    access = await _access_token(cred, credential_id=tool.credential_id, client=client)  # type: ignore[arg-type]
    if access is None:
        return _refused("auth_failed")
    return access


async def _run_crm(
    session: AsyncSession,
    *,
    tool: LoadedTool,
    values: dict[str, Any],
    client: httpx.AsyncClient,
    call: CallFacts,
) -> ExecutionResult:
    config = CrmConfig.model_validate(tool.config)
    if not call.caller_e164:
        return _refused("no_caller_number")
    access = await _crm_access(session, tool, client)
    if isinstance(access, ExecutionResult):
        return access
    token, extras = access
    fields = {
        f.crm_field: _stringify(values[f.param])[:500]
        for f in config.fields
        if values.get(f.param) is not None
    }
    if tool.provider == "zoho":
        domain = crm.zoho_api_domain(extras.get("api_domain"))
        if domain is None:
            return _refused("credential_unusable")
        record = {"Last_Name": crm.UNNAMED_CALLER, **fields, "Phone": call.caller_e164}
        response = await _send(
            crm.zoho_upsert(api_domain=domain, token=token, module=config.module, record=record),
            client=client,
        )
        if _ok(response) and crm.zoho_upsert_ok(_json(response)):
            return ExecutionResult(ok=True, payload={"status": "saved"}, status="crm_saved")
        return _refused("crm_error", status_code=response.status_code)
    # hubspot
    response = await _send(
        crm.hubspot_search(token=token, phone_e164=call.caller_e164), client=client
    )
    if response.status_code != 200:
        return _refused("crm_error", status_code=response.status_code)
    found = crm.hubspot_first_result(_json(response))
    properties = {**fields, "phone": call.caller_e164}
    if found is not None and found.get("id"):
        response = await _send(
            crm.hubspot_update(token=token, record_id=str(found["id"]), properties=properties),
            client=client,
        )
    else:
        response = await _send(
            crm.hubspot_create(token=token, properties=properties), client=client
        )
    if _ok(response):
        return ExecutionResult(ok=True, payload={"status": "saved"}, status="crm_saved")
    return _refused("crm_error", status_code=response.status_code)


# ------------------------------------------------------------ caller lookup ----


async def _run_caller_lookup(
    session: AsyncSession, *, tool: LoadedTool, client: httpx.AsyncClient, call: CallFacts
) -> ExecutionResult:
    config = CallerLookupConfig.model_validate(tool.config)
    if not call.caller_e164:
        return _refused("no_caller_number")
    if tool.provider == "sheet":
        token = await gsheets.bearer(client)
        if token is None:
            return _refused("sheets_not_configured")
        return await _sheet_lookup(
            spreadsheet_id=config.spreadsheet_id or "",
            worksheet=config.worksheet or "",
            match_header=config.match_header or "",
            return_headers=config.return_headers,
            token=token,
            client=client,
            call=call,
        )
    if tool.provider == "api":
        headers: dict[str, str] = {}
        if tool.credential_id is not None:
            cred = await _credential(session, tool)
            if cred is None:
                return _refused("no_credential")
            headers[config.auth_header] = f"{config.auth_scheme}{cred.secret}"
        url = f"{config.url}?{urlencode({config.phone_query_key: call.caller_e164})}"
        response = await _send(
            PreparedRequest(method="GET", url=url, headers=headers), client=client
        )
        if not _ok(response):
            return _refused("lookup_failed", status_code=response.status_code)
        return ExecutionResult(
            ok=True, payload={"found": True, "data": _json(response)}, status="found"
        )
    access = await _crm_access(session, tool, client)
    if isinstance(access, ExecutionResult):
        return access
    token, extras = access
    if tool.provider == "zoho":
        domain = crm.zoho_api_domain(extras.get("api_domain"))
        if domain is None:
            return _refused("credential_unusable")
        response = await _send(
            crm.zoho_search(
                api_domain=domain, token=token, module=config.module, phone_e164=call.caller_e164
            ),
            client=client,
        )
        if response.status_code == 204:
            return ExecutionResult(ok=True, payload={"found": False}, status="not_found")
        record = crm.zoho_first_record(_json(response)) if response.status_code == 200 else None
        if record is None:
            return _refused("lookup_failed", status_code=response.status_code)
        details = {k: str(record[k]) for k in crm.ZOHO_LOOKUP_FIELDS if record.get(k)}
        return ExecutionResult(ok=True, payload={"found": True, "details": details}, status="found")
    response = await _send(
        crm.hubspot_search(token=token, phone_e164=call.caller_e164), client=client
    )
    if response.status_code != 200:
        return _refused("lookup_failed", status_code=response.status_code)
    found = crm.hubspot_first_result(_json(response))
    if found is None:
        return ExecutionResult(ok=True, payload={"found": False}, status="not_found")
    raw_props = found.get("properties")
    props: dict[str, Any] = raw_props if isinstance(raw_props, dict) else {}
    details = {k: str(props[k]) for k in crm.HUBSPOT_SEARCH_PROPERTIES if props.get(k)}
    return ExecutionResult(ok=True, payload={"found": True, "details": details}, status="found")


async def caller_of_call(session: AsyncSession, *, engine_call_id: str) -> CallFacts | None:
    """Our record of a call by the engine's id: the background job's way back to the caller's
    number, so the number never travels in a queue payload."""
    row = (
        await session.execute(
            text("SELECT direction, from_e164, to_e164 FROM calls WHERE engine_call_id = :ecid"),
            {"ecid": engine_call_id},
        )
    ).first()
    if row is None:
        return None
    caller = row[2] if row[0] == "outbound" else row[1]
    return CallFacts(call_ref=engine_call_id, caller_e164=caller, direction=str(row[0]))


__all__ = [
    "ACTION_AUDIT_JOB",
    "MAX_ANSWER_CHARS",
    "MAX_RESPONSE_BYTES",
    "REQUEST_TIMEOUT_S",
    "CallFacts",
    "ExecutionResult",
    "caller_of_call",
    "execute_action",
    "for_model",
    "free_slots",
    "lead_values",
    "reset_access_cache",
    "resolve_values",
    "spoken_time",
]
