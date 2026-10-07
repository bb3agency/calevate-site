"""`/v1/worker/engine-actions/{engine}/{tool}` — in-call tools reached as vendor actions.

On `ENGINE=thinnest` the agent calls our opt-out, call-back, call-back cancel and handoff
tools as ThinnestAI custom actions (`reliability/engine_actions.py` registers them). The
write each one makes is the Pipecat worker's, unchanged: every route below ends in a
`worker/tools.*_for` function, so there is still one implementation of "add this caller to
the DNC list" and one of "book this call-back".

AUTHENTICATION, before anything is parsed. The action carries `X-Agent-Secret`, a value we
minted per vendor agent and hold sealed on its `engine_agent_routes` row. The url names the
vendor agent (`?agent=`), which selects the secret; the header is compared in constant
time. Unknown agent, inactive route, no secret held and a wrong header all answer the same
401 (agent/custom-api.md:127-134).

WHICH CALL, AND WHY IT IS DONE THIS WAY (UNVERIFIED VENDOR BEHAVIOUR). No page of either
mirror documents a placeholder or header that tells an action which call or conversation
it came from: placeholders are parameters the MODEL fills (snapshots/2026-10-07/pages/
api-reference/actions/create-action.md:442; agent/custom-api.md:63-83). A model-filled call
id would be a value a caller can talk the model into, and the same agent also answers web
chat (`voice.surfaces`, agents.md:56), so "the agent's only live call" is not proof either.
So a call is identified only when BOTH hold:

1. the per-agent secret proves the request comes from this vendor agent's action; and
2. the number the caller gives (`caller_number`) equals, after normalisation, the customer
   number the vendor itself reports on exactly ONE of this agent's connected calls
   (`GET /calls?agent=&status=connected`, snapshots/…/calls/list-calls.md:262-277, :504).

The number written to the DNC list or rung back is therefore the VENDOR's record of who is
on the line, never the model's string; the model's string only selects among this agent's
live calls. What stays unproven: that a stranger holding a live caller's number cannot act
for them while they are on a call with the same agent (they would need the number and the
timing), and whether the vendor lists an inbound call as `connected` while it is in
progress — both are questions for ThinnestAI, listed in the phase-2 report.

The call row: an outbound call is ours already (matched by `engine_call_id`, or by the
`reference` we sent, which is our `calls.id`); an inbound one has no row until its results
arrive, so a minimal `in_progress` row is inserted under the vendor's call id, which the
post-call upsert (`workers/pipeline._upsert_call_row`, `ON CONFLICT (engine_call_id)`)
then completes rather than duplicates.

RESPONSES are the smallest object the agent can act on — `status`, `say`, and the booked
time on a call-back — because what an action returns may be read aloud (custom-api.md:151-
163). "No such call" and "number does not match" are one answer. HARD RULE 6: ids, states
and outcome words in logs; never the number, never the caller's words.
"""

from __future__ import annotations

import hmac
import json
import secrets
from dataclasses import dataclass
from typing import Annotated, Any, Final
from uuid import UUID

from calevate_shared.worker_api import (
    MAX_IDENTIFIER,
    MAX_TOOL_TEXT,
    CallbackBookIn,
    CallbackCancelIn,
    CallerIdentityIn,
    HandoffToolIn,
    OptOutToolIn,
)
from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.engine.thinnest_actions import (
    SECRET_HEADER,
    LiveCall,
    ThinnestActions,
    thinnest_actions,
)
from apps.api.ingest.service import normalize_phone
from apps.api.reliability.engine_actions import (
    ACTION_ENGINES,
    ACTIONS_PATH,
    CALLBACK,
    CALLBACK_CANCEL,
    CALLER_NUMBER,
    HANDOFF,
    OPT_OUT,
    envelope_of,
    open_action_secret,
)
from apps.api.worker.service import refuse_wrong_engine
from apps.api.worker.tools import (
    CallLocator,
    ToolCall,
    book_callback_for,
    cancel_callback_for,
    record_opt_out_for,
    request_handoff_unplaced,
)

log = get_logger(__name__)

router = APIRouter(prefix=ACTIONS_PATH, tags=["voice-worker"])

_REF_MAX: Final = 128
#: The largest body an action of ours can produce: six bounded strings in a JSON object.
_BODY_MAX: Final = 8 * 1024
_TOOLS: Final = frozenset({OPT_OUT, CALLBACK, CALLBACK_CANCEL, HANDOFF})
#: A secret no route holds, compared against when there is nothing to compare, so an
#: unknown agent costs the same comparison as a known one.
_DECOY: Final = secrets.token_urlsafe(32)

_UNAUTHORISED: Final = {"error": "unauthorised"}

NOT_MATCHED_SAY: Final = (
    "Nothing was done: the number given does not match this call. Do NOT tell the caller "
    "it is done. Ask them to say the phone number you are speaking to them on, then try "
    "once more. If it still does not match, apologise and tell them it could not be done "
    "on this call."
)
UNAVAILABLE_SAY: Final = (
    "Nothing was done: the system could not be reached just now. Do NOT tell the caller "
    "it is done. Apologise and tell them it could not be done on this call."
)


@dataclass(frozen=True, slots=True)
class ActionRoute:
    tenant_id: UUID
    agent_id: UUID


class _CallNotMatchedError(Exception):
    """The live call could not be tied to a row of ours; answered as `caller_not_matched`."""


async def _route_if_authentic(
    engine: str, engine_agent_ref: str, presented: str | None
) -> ActionRoute | None:
    """The route this request may act for, or None. Constant-time in every branch."""
    row = None
    if engine in ACTION_ENGINES:
        async with untenanted_session() as session:
            row = (
                await session.execute(
                    text(
                        "SELECT tenant_id, agent_id, action_secret_ciphertext, "
                        "action_secret_nonce, action_secret_dek_wrapped, "
                        "action_secret_dek_nonce, action_secret_kek_version "
                        "FROM engine_agent_routes "
                        "WHERE engine = :engine AND engine_agent_ref = :ref AND active"
                    ),
                    {"engine": engine, "ref": engine_agent_ref},
                )
            ).first()
    expected: str | None = None
    if row is not None:
        envelope = envelope_of(tuple(row[2:7]))
        if envelope is not None:
            expected = open_action_secret(
                envelope, engine=engine, engine_agent_ref=engine_agent_ref
            )
    matched = hmac.compare_digest(
        (presented or "").encode(), (expected if expected is not None else _DECOY).encode()
    )
    if not matched or expected is None or row is None:
        return None
    return ActionRoute(tenant_id=UUID(str(row[0])), agent_id=UUID(str(row[1])))


def _arguments(raw: bytes) -> dict[str, str] | None:
    """The filled body template as strings. A placeholder the vendor left unfilled, or an
    empty value, is absent — the substitution of an optional parameter the model did not
    fill is UNVERIFIED (no page says whether it is "" or the literal `{{name}}`)."""
    try:
        data = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    out: dict[str, str] = {}
    for key, value in data.items():
        if not isinstance(key, str) or not isinstance(value, str | int | float | bool):
            continue
        word = str(value).strip()
        if not word or (word.startswith("{{") and word.endswith("}}")):
            continue
        out[key] = word
    return out


def _clip(value: str | None, limit: int) -> str | None:
    return value[:limit] if value else None


def _yes(value: str | None) -> bool:
    """The narrow parse `voice_worker/call_tools` applies to `confirmed`: yes or true only."""
    return (value or "").strip().lower() in {"yes", "true"}


async def resolve_live_call(
    client: ThinnestActions, engine_agent_ref: str, caller_number: str | None
) -> LiveCall | None:
    """This agent's ONE connected call whose customer number is `caller_number`, or None."""
    wanted = normalize_phone(caller_number) if caller_number else None
    if wanted is None:
        return None
    matches = [
        call
        for call in await client.live_calls(engine_agent_ref)
        if call.phone is not None and normalize_phone(call.phone) == wanted
    ]
    return matches[0] if len(matches) == 1 else None


_CALL_COLUMNS: Final = "id, agent_id, direction, from_e164, to_e164"


def _tool_call(row: Any) -> ToolCall:
    return ToolCall(
        id=UUID(str(row[0])),
        agent_id=UUID(str(row[1])),
        direction=str(row[2]),
        from_e164=row[3],
        to_e164=row[4],
    )


def call_locator(route: ActionRoute, live: LiveCall, phone_e164: str) -> CallLocator:
    """The `worker/tools.CallLocator` for a live vendor call, run in the tool's own session."""

    async def locate(session: AsyncSession) -> ToolCall:
        row = (
            await session.execute(
                text(f"SELECT {_CALL_COLUMNS} FROM calls WHERE engine_call_id = :ecid"),
                {"ecid": live.engine_call_id},
            )
        ).first()
        if row is None and live.direction == "outbound" and live.reference:
            try:
                ours = UUID(live.reference)
            except ValueError:
                ours = None
            if ours is not None:
                row = (
                    await session.execute(
                        text(
                            f"SELECT {_CALL_COLUMNS} FROM calls "
                            "WHERE id = :id AND direction = 'outbound'"
                        ),
                        {"id": ours},
                    )
                ).first()
        if row is None and live.direction == "inbound":
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "from_e164, status, created_at, updated_at) VALUES (:id, :tid, :aid, "
                    ":ecid, 'inbound', :from_e, 'in_progress', now(), now()) "
                    "ON CONFLICT (engine_call_id) DO NOTHING"
                ),
                {
                    "id": uuid7(),
                    "tid": route.tenant_id,
                    "aid": route.agent_id,
                    "ecid": live.engine_call_id,
                    "from_e": phone_e164,
                },
            )
            row = (
                await session.execute(
                    text(f"SELECT {_CALL_COLUMNS} FROM calls WHERE engine_call_id = :ecid"),
                    {"ecid": live.engine_call_id},
                )
            ).first()
        # RLS already confines the read to the route's tenant; the agent must match too,
        # or one agent's secret could act on another agent's call in the same account.
        if row is None or UUID(str(row[1])) != route.agent_id:
            raise _CallNotMatchedError
        return _tool_call(row)

    return locate


def _answer(status: str, say: str, **extra: str) -> JSONResponse:
    return JSONResponse({"status": status, "say": say, **{k: v for k, v in extra.items() if v}})


@router.post("/{engine}/{tool}", include_in_schema=False)
async def engine_action(
    request: Request,
    engine: Annotated[str, Path(max_length=32)],
    tool: Annotated[str, Path(max_length=32)],
    agent: Annotated[str, Query(max_length=_REF_MAX)] = "",
) -> JSONResponse:
    """One in-call tool, called by the voice platform on behalf of its agent."""
    route = await verify_agent_secret(engine, agent, request.headers.get(SECRET_HEADER))
    if route is None:
        log.warning("engine_action_unauthorised", extra={"engine": engine[:32]})
        return JSONResponse(_UNAUTHORISED, status_code=401)
    if get_settings().engine != engine:
        raise refuse_wrong_engine()
    if tool not in _TOOLS:
        raise ProblemError(
            kind="not_found",
            code="engine_action_unknown",
            title="No such action",
            detail="This action is not one of ours.",
        )
    raw = await request.body()
    args = _arguments(raw) if len(raw) <= _BODY_MAX else None
    if args is None:
        raise ProblemError(
            kind="validation",
            code="engine_action_body_unreadable",
            title="The action's body could not be read",
            detail="The action body must be a JSON object of short text values.",
        )
    ids = {"tenant_id": str(route.tenant_id), "agent_id": str(route.agent_id), "tool": tool}

    if tool == HANDOFF:
        out = await request_handoff_unplaced(
            route.tenant_id,
            route.agent_id,
            HandoffToolIn(
                reason=_clip(args.get("reason"), MAX_TOOL_TEXT),
                summary=_clip(args.get("summary"), MAX_TOOL_TEXT),
            ),
        )
        return _answer(out.status, out.say)

    client = thinnest_actions()
    try:
        live = await resolve_live_call(client, agent, args.get(CALLER_NUMBER))
    except ProblemError as exc:
        log.warning("engine_action_live_calls_unreadable", extra={**ids, "reason": exc.code})
        return _answer("unavailable", UNAVAILABLE_SAY)
    phone = normalize_phone(live.phone) if live is not None and live.phone else None
    if live is None or phone is None:
        log.info("engine_action_caller_not_matched", extra=ids)
        return _answer("caller_not_matched", NOT_MATCHED_SAY)
    locate = call_locator(route, live, phone)
    caller = CallerIdentityIn(state="known", e164=phone)
    language = _clip(args.get("language"), 8)
    try:
        if tool == OPT_OUT:
            opted = await record_opt_out_for(
                route.tenant_id,
                OptOutToolIn(
                    reason=_clip(args.get("reason"), MAX_TOOL_TEXT),
                    language=language,
                    caller=caller,
                ),
                locate=locate,
            )
            return _answer(opted.status, opted.say)
        if tool == CALLBACK:
            booked = await book_callback_for(
                route.tenant_id,
                live.engine_call_id,
                CallbackBookIn(
                    callback_date=_clip(args.get("callback_date"), MAX_IDENTIFIER),
                    callback_time=_clip(args.get("callback_time"), MAX_IDENTIFIER),
                    confirmed=_yes(args.get("confirmed")),
                    note=_clip(args.get("note"), MAX_TOOL_TEXT),
                    language=language,
                    caller=caller,
                ),
                locate=locate,
            )
            return _answer(booked.status, booked.say, booked_for=booked.booked_for)
        cancelled = await cancel_callback_for(
            route.tenant_id, CallbackCancelIn(caller=caller), locate=locate
        )
        return _answer(cancelled.status, cancelled.say)
    except _CallNotMatchedError:
        log.info("engine_action_call_row_not_matched", extra=ids)
        return _answer("caller_not_matched", NOT_MATCHED_SAY)


async def verify_agent_secret(
    engine: str, engine_agent_ref: str, presented: str | None
) -> ActionRoute | None:
    """THE credential of this surface (`scripts/check_public_routes`)."""
    if not engine_agent_ref or not presented:
        # Still one comparison, so absence is not faster than a wrong value.
        hmac.compare_digest(b"", _DECOY.encode())
        return None
    return await _route_if_authentic(engine, engine_agent_ref, presented)


__all__ = [
    "NOT_MATCHED_SAY",
    "UNAVAILABLE_SAY",
    "ActionRoute",
    "call_locator",
    "resolve_live_call",
    "router",
    "verify_agent_secret",
]
