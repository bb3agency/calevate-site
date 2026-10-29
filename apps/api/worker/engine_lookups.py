"""`/v1/worker/engine-lookups/{engine}` — who is calling, asked before the agent answers (D-716).

ThinnestAI POSTs `{event: "call.started", callId, surface, agentId, from, to, direction:
"inbound", contact, sentAt}` to an agent's `voice.callStartUrl` when an inbound phone or
WhatsApp call is about to be answered, and waits up to two seconds for
`{"variables": {...}}` (docs.thinnest.ai channels/voice "Who-is-calling lookup" and
api-reference/agents/update-agent `callStartUrl`, read 10 Oct 2026). No answer, an error or
anything else and the call goes ahead without them; it is never retried, but a phone provider
that repeats its own request makes ThinnestAI ask again with the same `callId` (live docs,
"Who-is-calling lookup", read 11 Oct 2026). So the first request for a call answers it and a
repeat gets the same variables back with no second lookup (`repeat_key`). Two seconds is
the vendor's limit; we keep our own 0.8.

AUTHENTICATION, before the body is parsed: `x-thinnest-signature-v2` is `sha256=` + hex
HMAC-SHA256 of `<x-thinnest-delivered-at>.<raw body>` under the secret the vendor minted for
this agent (`reliability/engine_lookups.py` holds it sealed), compared in constant time, and
the delivery time must be within five minutes of our clock — the webhook rule the vendor
documents and `calevate_shared.webhook_signature` already implements. The body's `agentId`
must be the agent the url names. Every failure is one 401.

THE ANSWER is built from our CRM for the route's tenant only (`crm/caller_lookup.py`) under
`ANSWER_BUDGET_S`; any miss, error or overrun answers no caller values with 200 so the call
goes ahead at once. A secret read that overruns `SECRET_BUDGET_S` answers 503, which the
vendor treats the same way. Every answer, those included, carries today's IST date
(`calevate_shared.engine.TODAY_VARIABLE`, D-888): the lookup is the one way an inbound
call's instructions get a value from us. HARD RULE 6: logs carry ids and an outcome word,
never the number.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from calevate_shared.engine import (
    CALLER_HIDDEN_VARIABLE,
    TODAY_VARIABLE,
    neutralise_markers,
    today_value,
)
from calevate_shared.engine_scope import raw_of
from calevate_shared.webhook_signature import (
    signed_time_is_fresh,
    timestamped_sha256_signature,
    timestamped_sha256_signature_matches,
)
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.crm.caller_lookup import caller_variables
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_actions import DELIVERED_AT_HEADER, SIGNATURE_HEADER, parse_call_start
from apps.api.forwarding.testing import queue_early_hang_up, record_lookup_arrival
from apps.api.ingest.service import normalize_phone
from apps.api.reliability.engine_lookups import (
    LOOKUP_ENGINES,
    LOOKUPS_PATH,
    read_call_start_secret,
)

log = get_logger(__name__)

router = APIRouter(prefix=LOOKUPS_PATH, tags=["engine-actions"])

_REF_MAX: Final = 128
#: The lookup body is one small JSON object; anything larger is not one.
_BODY_MAX: Final = 16 * 1024
#: The vendor waits two seconds; we answer well inside it so a slow read never makes the
#: caller hear extra ringing for nothing.
ANSWER_BUDGET_S: Final = 0.8
#: The route's other awaits, each bounded so the whole request stays inside the vendor's
#: two seconds: the secret read (`SECRET_BUDGET_S`) and up to two Redis round trips
#: (`REDIS_BUDGET_S` each) around the answer, 0.4 + 0.2 + 0.8 + 0.2 = 1.6 s at worst.
#: Without them the only bounds are the pool's 5 s checkout and redis-py's 2 s socket
#: timeout, so one slow store makes the caller ring for the vendor's full wait.
SECRET_BUDGET_S: Final = 0.4
REDIS_BUDGET_S: Final = 0.2
FRESHNESS: Final = timedelta(minutes=5)
#: Signed against when no route or secret exists, so an unknown agent costs the same.
_DECOY: Final = secrets.token_urlsafe(32)
_UNAUTHORISED: Final = {"error": "unauthorised"}
_UNAVAILABLE: Final = {"error": "unavailable"}


def _answer_with(variables: dict[str, str]) -> JSONResponse:
    """The lookup's answer: `variables` plus today's date, which no caller record decides.

    The engine fills these into the instructions, so each value passes the prompt's one
    marker gate (`neutralise_markers`): a lead name or a captured detail cannot write a
    platform section."""
    safe = {key: neutralise_markers(value) for key, value in variables.items()}
    return JSONResponse({"variables": {**safe, TODAY_VARIABLE: today_value(datetime.now(UTC))}})


def _empty() -> JSONResponse:
    return _answer_with({})


def verify_lookup_signature(
    body: bytes, *, header: str | None, delivered_at: str | None, secret: str | None
) -> bool:
    """THE credential of this surface (`scripts/check_public_routes`): the v2 signature
    over `<delivered-at>.<body>` and a fresh delivery time. Constant-time either way."""
    if secret is None:
        # Still one HMAC and one comparison, so "no such agent" is not faster.
        expected = timestamped_sha256_signature(body, _DECOY, signed_at=delivered_at or "")
        hmac.compare_digest(expected.encode(), (header or "").encode())
        return False
    matched = timestamped_sha256_signature_matches(body, header, secret, signed_at=delivered_at)
    fresh = signed_time_is_fresh(delivered_at, now=datetime.now(UTC), tolerance=FRESHNESS)
    return matched and fresh


@router.post("/{engine}", include_in_schema=False)
async def caller_lookup(
    request: Request,
    engine: Annotated[str, Path(max_length=32)],
    agent: Annotated[str, Query(max_length=_REF_MAX)] = "",
) -> JSONResponse:
    """Who is calling, for the voice platform, before its agent answers."""
    raw = await request.body()
    secret = None
    tenant_id = agent_id = None
    if engine in LOOKUP_ENGINES and agent and len(raw) <= _BODY_MAX:
        try:
            async with asyncio.timeout(SECRET_BUDGET_S), untenanted_session() as session:
                exists, secret, tenant_id, agent_id = await read_call_start_secret(
                    session, engine=engine, engine_agent_ref=agent
                )
        except TimeoutError:
            # Not a forgery and not an answer: the platform goes ahead without variables on
            # any non-200, which is all a late answer would have got.
            log.warning("engine_lookup_not_answered", extra={"outcome": "secret_slow"})
            return JSONResponse(_UNAVAILABLE, status_code=503)
        if not exists:
            secret = None
    authentic = verify_lookup_signature(
        raw,
        header=request.headers.get(SIGNATURE_HEADER),
        delivered_at=request.headers.get(DELIVERED_AT_HEADER),
        secret=secret,
    )
    lookup = parse_call_start(raw) if authentic else None
    if lookup is None or tenant_id is None or agent_id is None or lookup.agent_id != raw_of(agent):
        log.warning("engine_lookup_unauthorised", extra={"engine": engine[:32]})
        return JSONResponse(_UNAUTHORISED, status_code=401)
    ids = {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    if get_settings().engine != engine or not lookup.answerable:
        log.info("engine_lookup_not_answered", extra={**ids, "outcome": "not_inbound"})
        return _empty()
    phone = normalize_phone(lookup.caller) if lookup.caller else None
    if phone is None:
        log.info("engine_lookup_not_answered", extra={**ids, "outcome": "no_number"})
        return _empty()

    tid, aid, number = tenant_id, agent_id, phone

    async def _answer() -> dict[str, str]:
        async with tenant_session(tid) as session:
            # A forwarded number (D-746): our own test arriving is recorded and gets no
            # variables; a call that shows the client's own published number instead of the
            # caller's tells the agent to ask for a call-back number, and is never looked up
            # as a caller (it would find the business's own records).
            verdict = await record_lookup_arrival(
                session, tenant_id=tid, caller_e164=number, engine_call_id=lookup.call_id
            )
            if verdict.test_id is None and not verdict.caller_hidden:
                return await caller_variables(
                    session, tenant_id=tid, agent_id=aid, phone_e164=number
                )
        if verdict.test_id is not None:
            await queue_early_hang_up(tid, verdict.test_id)
            return {}
        return {CALLER_HIDDEN_VARIABLE: "yes"}

    key = repeat_key(engine, agent, lookup.call_id) if lookup.call_id else None
    claimed = await _claim(key)
    if claimed is False:
        repeated = await _first_answer(key)
        log.info(
            "engine_lookup_answered",
            extra={**ids, "outcome": "repeat", "count": len(repeated or {})},
        )
        return _answer_with(repeated or {})
    try:
        variables = await asyncio.wait_for(_answer(), timeout=ANSWER_BUDGET_S)
    except TimeoutError:
        log.warning("engine_lookup_not_answered", extra={**ids, "outcome": "timeout"})
        await _keep(key, {})
        return _empty()
    except Exception as exc:  # the call must go ahead whatever happened here
        log.warning(
            "engine_lookup_not_answered",
            extra={**ids, "outcome": "error", "error": type(exc).__name__},
        )
        await _keep(key, {})
        return _empty()
    await _keep(key, variables)
    log.info(
        "engine_lookup_answered",
        extra={**ids, "outcome": "known" if variables else "unknown", "count": len(variables)},
    )
    return _answer_with(variables)


# --- one answer per call ---------------------------------------------------------------

#: A repeat is the phone provider asking again when our first answer was late, seconds
#: later. The kept answer holds a caller's name, so it lives only that long.
REPEAT_TTL_S: Final = 120
_PENDING: Final = "pending"
_POLL_S: Final = 0.05


def repeat_key(engine: str, agent: str, call_id: str) -> str:
    """Hashed, so neither the agent nor the call id is a Redis key name."""
    digest = hashlib.sha256(f"{engine}\x00{agent}\x00{call_id}".encode()).hexdigest()
    return f"lookup:once:{digest}"


async def _claim(key: str | None) -> bool | None:
    """True when this request answers the call, False when an earlier one does, None when
    there is nothing to dedupe on or Redis cannot say (then this one answers)."""
    if key is None:
        return None
    try:
        async with asyncio.timeout(REDIS_BUDGET_S):
            return bool(await get_redis().set(key, _PENDING, nx=True, ex=REPEAT_TTL_S))
    except Exception as exc:
        log.warning("engine_lookup_repeat_unreadable", extra={"error": type(exc).__name__})
        return None


async def _first_answer(key: str | None) -> dict[str, str] | None:
    """The variables the first request answered with, waited for inside the budget. None
    when it has not answered in time: the repeat then sends none rather than a second
    lookup, and the call goes ahead as it would on a late answer."""
    if key is None:
        return None
    loop = asyncio.get_running_loop()
    deadline = loop.time() + ANSWER_BUDGET_S
    while True:
        try:
            async with asyncio.timeout(REDIS_BUDGET_S):
                held = await get_redis().get(key)
        except Exception as exc:
            log.warning("engine_lookup_repeat_unreadable", extra={"error": type(exc).__name__})
            return None
        if held is not None and held != _PENDING:
            try:
                kept = json.loads(held)
            except ValueError:
                return None
            return {str(k): str(v) for k, v in kept.items()} if isinstance(kept, dict) else None
        if held is None or loop.time() >= deadline:
            return None
        await asyncio.sleep(_POLL_S)


async def _keep(key: str | None, variables: dict[str, str]) -> None:
    if key is None:
        return
    try:
        async with asyncio.timeout(REDIS_BUDGET_S):
            await get_redis().set(key, json.dumps(variables), ex=REPEAT_TTL_S)
    except Exception as exc:
        log.warning("engine_lookup_repeat_unsaved", extra={"error": type(exc).__name__})


__all__ = [
    "ANSWER_BUDGET_S",
    "REDIS_BUDGET_S",
    "REPEAT_TTL_S",
    "SECRET_BUDGET_S",
    "caller_lookup",
    "repeat_key",
    "router",
    "verify_lookup_signature",
]
