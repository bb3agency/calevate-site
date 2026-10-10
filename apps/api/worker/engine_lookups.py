"""`/v1/worker/engine-lookups/{engine}` — who is calling, asked before the agent answers (D-716).

ThinnestAI POSTs `{event: "call.started", callId, surface, agentId, from, to, direction:
"inbound", contact, sentAt}` to an agent's `voice.callStartUrl` when an inbound phone or
WhatsApp call is about to be answered, and waits up to two seconds for
`{"variables": {...}}` (docs.thinnest.ai channels/voice "Who-is-calling lookup" and
api-reference/agents/update-agent `callStartUrl`, read 10 Oct 2026). No answer, an error or
anything else and the call goes ahead without them; it is never retried, and a repeat with
the same `callId` is the phone provider asking again. Answering is read-only here, so a
repeat is answered again rather than deduplicated.

AUTHENTICATION, before the body is parsed: `x-thinnest-signature-v2` is `sha256=` + hex
HMAC-SHA256 of `<x-thinnest-delivered-at>.<raw body>` under the secret the vendor minted for
this agent (`reliability/engine_lookups.py` holds it sealed), compared in constant time, and
the delivery time must be within five minutes of our clock — the webhook rule the vendor
documents and `calevate_shared.webhook_signature` already implements. The body's `agentId`
must be the agent the url names. Every failure is one 401.

THE ANSWER is built from our CRM for the route's tenant only (`crm/caller_lookup.py`) under
`ANSWER_BUDGET_S`; any miss, error or overrun is `{"variables": {}}` with 200 so the call
goes ahead at once. HARD RULE 6: logs carry ids and an outcome word, never the number.
"""

from __future__ import annotations

import asyncio
import hmac
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Final

from calevate_shared.engine_scope import raw_of
from calevate_shared.webhook_signature import (
    signed_time_is_fresh,
    timestamped_sha256_signature,
    timestamped_sha256_signature_matches,
)
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse

from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.crm.caller_lookup import caller_variables
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_actions import DELIVERED_AT_HEADER, SIGNATURE_HEADER, parse_call_start
from apps.api.ingest.service import normalize_phone
from apps.api.reliability.engine_lookups import (
    LOOKUP_ENGINES,
    LOOKUPS_PATH,
    read_call_start_secret,
)

log = get_logger(__name__)

router = APIRouter(prefix=LOOKUPS_PATH, tags=["voice-worker"])

_REF_MAX: Final = 128
#: The lookup body is one small JSON object; anything larger is not one.
_BODY_MAX: Final = 16 * 1024
#: The vendor waits two seconds; we answer well inside it so a slow read never makes the
#: caller hear extra ringing for nothing.
ANSWER_BUDGET_S: Final = 0.8
FRESHNESS: Final = timedelta(minutes=5)
#: Signed against when no route or secret exists, so an unknown agent costs the same.
_DECOY: Final = secrets.token_urlsafe(32)
_UNAUTHORISED: Final = {"error": "unauthorised"}


def _empty() -> JSONResponse:
    return JSONResponse({"variables": {}})


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
        async with untenanted_session() as session:
            exists, secret, tenant_id, agent_id = await read_call_start_secret(
                session, engine=engine, engine_agent_ref=agent
            )
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
            return await caller_variables(session, tenant_id=tid, agent_id=aid, phone_e164=number)

    try:
        variables = await asyncio.wait_for(_answer(), timeout=ANSWER_BUDGET_S)
    except TimeoutError:
        log.warning("engine_lookup_not_answered", extra={**ids, "outcome": "timeout"})
        return _empty()
    except Exception as exc:  # the call must go ahead whatever happened here
        log.warning(
            "engine_lookup_not_answered",
            extra={**ids, "outcome": "error", "error": type(exc).__name__},
        )
        return _empty()
    log.info(
        "engine_lookup_answered",
        extra={**ids, "outcome": "known" if variables else "unknown", "count": len(variables)},
    )
    return JSONResponse({"variables": variables})


__all__ = ["ANSWER_BUDGET_S", "caller_lookup", "router", "verify_lookup_signature"]
