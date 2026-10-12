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

WHICH CALL. The platform names it twice, and neither is the model's: the `X-Call-Id` header
it sends with every action call, and the `{{call.id}}` placeholder our body template
carries as `call_id`. Dotted placeholders are filled by the platform "so a caller cannot
talk the agent into sending a different one" (snapshots/2026-10-08/pages/agent/
custom-api.md:84-119). So a call is identified when:

1. the per-agent secret proves the request comes from this vendor agent's action;
2. the header names a call, and the body's `call_id`, when filled, names the same one; and
3. `GET /calls/{id}` shows that call is on THIS vendor agent and still ringing or
   connected — so one agent's secret cannot act on another agent's call, and a replayed
   request cannot act on a call that has ended.

The number written to the DNC list or rung back is the VENDOR's record of who is on the
line (`phone` on the call), never anything the model or the caller said.

The call row: an outbound call is ours already (matched by `engine_call_id`, or by the
`reference` we sent, which is our `calls.id`); an inbound one has no row until its results
arrive, so a minimal `in_progress` row is inserted under the vendor's call id, which the
post-call upsert (`workers/pipeline._upsert_call_row`, `ON CONFLICT (engine_call_id)`)
then completes rather than duplicates.

A TEST CHAT writes nothing. Every action request from ThinnestAI's test chat carries
`X-Test-Chat: true` and no `X-Call-Id` (ThinnestAI email of 12 Oct 2026, VENDOR-STATED), so a
marked request is answered as the action succeeding, with a `*_in_test` status, and nothing
is written: no DNC entry, no call-back, no cancellation, no hand-over and no client action
(founder decision F6, 12 Oct 2026). The marker wins over a call id, because writing nothing is
the safe reading of a request that says it is a test. A request with neither the marker nor a
call keeps the older rule: an opt-out while the owner is testing the agent
(`agents/test_window`) answers as recorded and writes nothing, and anything else is answered
as not matched.

ONCE PER CALL. A turn the platform re-runs on its backup model can call the same tool again
(`reliability/in_call_once.py`), so each tool runs once per call and per
`MEANINGFUL_ARGUMENTS`; a repeat answers with the first answer.

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

from calevate_shared.engine_scope import scope_of
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

from apps.api.actions.execution import CallFacts
from apps.api.actions.in_call import run_in_call_action
from apps.api.agents.test_window import window_open
from apps.api.core.alerting import alert
from apps.api.core.auth import client_request_ip
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_actions import (
    CALL_ID_FIELD,
    CALL_ID_HEADER,
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
    CLIENT_LEAF,
    HANDOFF,
    OPT_OUT,
    envelope_of,
    open_action_secret,
)
from apps.api.reliability.in_call_once import once_per_call
from apps.api.worker.service import refuse_wrong_engine
from apps.api.worker.tools import (
    OPTOUT_DONE_SAY,
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
    "Nothing was done: this call could not be found. Do NOT tell the caller it is done. "
    "Apologise and tell them it could not be done on this call."
)
#: The opt-out's answer inside a test chat: nothing written, the agent told it was done.
TEST_CHAT_OPT_OUT_STATUS: Final = "recorded_in_test"

#: The header ThinnestAI adds to every action request made from a test chat (email of
#: 12 Oct 2026, VENDOR-STATED); its value is the string "true".
TEST_CHAT_HEADER: Final = "X-Test-Chat"

#: Per platform tool, the answer a test chat gets: what the tool's success tells the agent,
#: so the owner hears what a caller would, and a status that says nothing was written.
TEST_CHAT_ANSWERS: Final[dict[str, tuple[str, str]]] = {
    OPT_OUT: (TEST_CHAT_OPT_OUT_STATUS, OPTOUT_DONE_SAY),
    CALLBACK: ("booked_in_test", "Tell the caller that is booked for the time they agreed."),
    CALLBACK_CANCEL: ("cancelled_in_test", "Tell the caller we will not ring them back."),
    HANDOFF: (
        "handover_in_test",
        "This is a test, so nobody was contacted. Tell the person testing that on a real "
        "call this is where the caller would be passed to the team.",
    ),
}
#: A client's own action in a test chat (F6): it reaches none of the client's systems.
TEST_CHAT_CLIENT_STATUS: Final = "done_in_test"
TEST_CHAT_CLIENT_SAY: Final = "Done. Use the answer to reply to the caller."


def is_test_chat(header: str | None) -> bool:
    """Does this action request say it comes from a test chat? Only the value "true"."""
    return (header or "").strip().lower() == "true"


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


#: The header the platform adds to every action call naming the workspace it came from
#: (`thinnest-findings/mirror/snapshots/2026-10-08/pages/agent/custom-api.md:116-119`).
WORKSPACE_ID_HEADER: Final = "X-Workspace-Id"


def note_action_source(request: Request, route: ActionRoute) -> None:
    """A SOFT check of where an authenticated action came from (D-743). ThinnestAI says its
    action requests come from one fixed address (email of 11 Oct 2026, VENDOR-STATED; not
    in the docs, read 11 Oct 2026), held in `thinnest_action_source_ips`. The per-agent
    secret is the credential, so another address is served anyway and raises one alarm per
    episode: refusing it would let a vendor renumbering silently stop bookings. The address
    is the edge's (`client_request_ip`, never a raw X-Forwarded-For); when none is vouched
    for, nothing is compared."""
    allowed = {
        part.strip()
        for part in get_settings().thinnest_action_source_ips.split(",")
        if part.strip()
    }
    seen = client_request_ip(request)
    if not allowed or seen is None or seen in allowed:
        return
    alert(
        "ROUTE_HANDLER",
        "engine_action_source_unexpected",
        detail=(
            "an in-call action with a valid agent secret came from an address not on the "
            "ThinnestAI list (thinnest_action_source_ips). It was served. If ThinnestAI has "
            "moved, add the new address in the ops console; if not, rotate the agent's "
            "secret by republishing it."
        ),
        episode="thinnest_action_source",
        agent_id=str(route.agent_id),
    )


def workspace_matches(engine_agent_ref: str, header: str | None) -> bool:
    """False only when the agent lives in a client's own workspace (D-693) and the platform
    named a different one. The header is sent "when known", so its absence is not a
    mismatch; an agent in our developer workspace has no workspace id of ours to compare."""
    expected = scope_of(engine_agent_ref)
    claimed = (header or "").strip()
    return expected is None or not claimed or claimed == expected


def named_call_id(header: str | None, body_call_id: str | None) -> str | None:
    """The call the platform says this action came from, or None when it names none or
    names two. The header is sent with every action call; the body's `call_id` is our
    template's `{{call.id}}`, empty outside a call and absent from an older template."""
    header_id = (header or "").strip()[:_REF_MAX] or None
    body_id = (body_call_id or "").strip()[:_REF_MAX] or None
    if header_id is None:
        return None
    if body_id is not None and body_id != header_id:
        return None
    return header_id


async def resolve_live_call(
    client: ThinnestActions, engine_agent_ref: str, call_id: str | None
) -> LiveCall | None:
    """The call `call_id` names, when it is live on THIS vendor agent; else None."""
    if call_id is None:
        return None
    call = await client.call(engine_agent_ref, call_id)
    if call is None or call.agent_ref != engine_agent_ref or not call.live:
        return None
    return call


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


def _body(status: str, say: str, **extra: str | None) -> dict[str, Any]:
    return {"status": status, "say": say, **{k: v for k, v in extra.items() if v}}


def _answer(status: str, say: str, **extra: str | None) -> JSONResponse:
    return JSONResponse(_body(status, say, **extra))


#: The arguments that make two calls of one platform tool on one call different requests.
#: The wording of a reason or a note is not one of them: a backup model re-running the turn
#: writes it again in its own words. A call-back for another time is another request.
MEANINGFUL_ARGUMENTS: Final[dict[str, tuple[str, ...]]] = {
    OPT_OUT: (),
    CALLBACK: ("callback_date", "callback_time", "confirmed"),
    CALLBACK_CANCEL: (),
    HANDOFF: (),
}


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
    if not workspace_matches(agent, request.headers.get(WORKSPACE_ID_HEADER)):
        # The secret is this agent's, yet the platform says the call came from another
        # workspace: a misregistered or replayed action. Refused, and an operator told.
        alert(
            "ROUTE_HANDLER",
            "engine_action_workspace_mismatch",
            detail=(
                "an in-call action arrived with this agent's secret but from a different voice "
                "platform workspace than the agent lives in, and was refused. Republish the "
                "agent to re-register its actions; if it recurs, rotate by republishing and "
                "check the platform's console for a copied action."
            ),
            agent_id=str(route.agent_id),
        )
        return JSONResponse(_UNAUTHORISED, status_code=401)
    note_action_source(request, route)
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
    if is_test_chat(request.headers.get(TEST_CHAT_HEADER)):
        # Before the call is resolved and before `once_per_call`: a test chat names no call,
        # so there is nothing to key the once-per-call guard on and nothing to write.
        log.info("engine_action_test_chat", extra=ids)
        status, say = TEST_CHAT_ANSWERS[tool]
        return _answer(status, say)

    call_id = named_call_id(request.headers.get(CALL_ID_HEADER), args.get(CALL_ID_FIELD))
    if tool == HANDOFF:

        async def _handoff() -> dict[str, Any]:
            out = await request_handoff_unplaced(
                route.tenant_id,
                route.agent_id,
                HandoffToolIn(
                    reason=_clip(args.get("reason"), MAX_TOOL_TEXT),
                    summary=_clip(args.get("summary"), MAX_TOOL_TEXT),
                ),
            )
            return {"status": out.status, "say": out.say}

        # One hand-over request per call, whatever words a re-run turn gives its reason.
        handed = (
            await once_per_call(call_ref=call_id, action=tool, args={}, run=_handoff)
            if call_id is not None
            else await _handoff()
        )
        return JSONResponse(handed)

    if tool == OPT_OUT and call_id is None and await window_open(route.agent_id):
        # A test chat (`agents/test_window`): no call, so no number and nothing to write.
        # The agent is told what a recorded opt-out tells it, so the test shows what a
        # caller on a real call hears; the status says it was a test.
        log.info("engine_action_test_chat", extra=ids)
        return _answer(TEST_CHAT_OPT_OUT_STATUS, OPTOUT_DONE_SAY)
    client = thinnest_actions()
    try:
        live = await resolve_live_call(client, agent, call_id)
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

    async def _run() -> dict[str, Any]:
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
                return _body(opted.status, opted.say)
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
                return _body(booked.status, booked.say, booked_for=booked.booked_for)
            cancelled = await cancel_callback_for(
                route.tenant_id, CallbackCancelIn(caller=caller), locate=locate
            )
            return _body(cancelled.status, cancelled.say)
        except _CallNotMatchedError:
            log.info("engine_action_call_row_not_matched", extra=ids)
            return _body("caller_not_matched", NOT_MATCHED_SAY)

    answer = await once_per_call(
        call_ref=live.engine_call_id,
        action=tool,
        args={key: args.get(key) or "" for key in MEANINGFUL_ARGUMENTS[tool]},
        run=_run,
    )
    return JSONResponse(answer)


#: A client action's body: up to 20 agent-filled values (create-action.md
#: `parameters.maxItems`), each bounded by the in-call door.
_CLIENT_BODY_MAX: Final = 32 * 1024
_CLIENT_NAME: Final = r"^[a-z][a-z0-9_]{2,39}$"

NO_CALL_SAY: Final = (
    "Nothing was done: this only works during a call. Do NOT tell the caller it is done."
)


@router.post(f"/{{engine}}/{CLIENT_LEAF}/{{name}}", include_in_schema=False)
async def client_action(
    request: Request,
    engine: Annotated[str, Path(max_length=32)],
    name: Annotated[str, Path(pattern=_CLIENT_NAME)],
    agent: Annotated[str, Query(max_length=_REF_MAX)] = "",
) -> JSONResponse:
    """A client's own action (D-700), called by the voice platform on its agent's behalf.

    The same gates as the platform's four tools, in the same order: the agent's secret, the
    workspace, the engine, then the live call. What runs is decided by
    `actions/in_call.run_in_call_action`, the door the Pipecat worker uses too.
    """
    route = await verify_agent_secret(engine, agent, request.headers.get(SECRET_HEADER))
    if route is None:
        log.warning("engine_action_unauthorised", extra={"engine": engine[:32]})
        return JSONResponse(_UNAUTHORISED, status_code=401)
    if not workspace_matches(agent, request.headers.get(WORKSPACE_ID_HEADER)):
        alert(
            "ROUTE_HANDLER",
            "engine_action_workspace_mismatch",
            detail=(
                "a client's in-call action arrived with this agent's secret but from a "
                "different voice platform workspace than the agent lives in, and was refused. "
                "Republish the agent to re-register its actions."
            ),
            agent_id=str(route.agent_id),
        )
        return JSONResponse(_UNAUTHORISED, status_code=401)
    note_action_source(request, route)
    if get_settings().engine != engine:
        raise refuse_wrong_engine()
    raw = await request.body()
    args = _arguments(raw) if len(raw) <= _CLIENT_BODY_MAX else None
    if args is None:
        raise ProblemError(
            kind="validation",
            code="engine_action_body_unreadable",
            title="The action's body could not be read",
            detail="The action body must be a JSON object of short text values.",
        )
    ids = {"tenant_id": str(route.tenant_id), "agent_id": str(route.agent_id), "tool": "client"}
    if is_test_chat(request.headers.get(TEST_CHAT_HEADER)):
        # A test chat (F6): the client's systems are not reached and nothing is queued.
        log.info("engine_action_test_chat", extra=ids)
        return _answer(TEST_CHAT_CLIENT_STATUS, TEST_CHAT_CLIENT_SAY)
    call_id = named_call_id(request.headers.get(CALL_ID_HEADER), args.pop(CALL_ID_FIELD, None))
    if call_id is None:
        # The vendor's own test (`POST …/actions/{id}/test`) has no conversation and so no
        # call id: answered without running anything, because a client action writes to
        # the client's systems and a test from the vendor console is not their instruction.
        return _answer("no_call", NO_CALL_SAY)
    client = thinnest_actions()
    try:
        live = await resolve_live_call(client, agent, call_id)
    except ProblemError as exc:
        log.warning("engine_action_live_calls_unreadable", extra={**ids, "reason": exc.code})
        return _answer("unavailable", UNAVAILABLE_SAY)
    phone = normalize_phone(live.phone) if live is not None and live.phone else None
    if live is None or phone is None:
        log.info("engine_action_caller_not_matched", extra=ids)
        return _answer("caller_not_matched", NOT_MATCHED_SAY)
    try:
        # The call row a background write reads the caller back from (an inbound call has
        # none until its results arrive), and the proof the call is this agent's.
        async with tenant_session(route.tenant_id) as session:
            await call_locator(route, live, phone)(session)
    except _CallNotMatchedError:
        log.info("engine_action_call_row_not_matched", extra=ids)
        return _answer("caller_not_matched", NOT_MATCHED_SAY)
    answer = await run_in_call_action(
        tenant_id=route.tenant_id,
        agent_id=route.agent_id,
        name=name,
        args=args,
        call=CallFacts(call_ref=live.engine_call_id, caller_e164=phone, direction=live.direction),
    )
    return JSONResponse(answer.body())


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
    "NO_CALL_SAY",
    "TEST_CHAT_ANSWERS",
    "TEST_CHAT_CLIENT_SAY",
    "TEST_CHAT_CLIENT_STATUS",
    "TEST_CHAT_HEADER",
    "TEST_CHAT_OPT_OUT_STATUS",
    "UNAVAILABLE_SAY",
    "ActionRoute",
    "call_locator",
    "client_action",
    "is_test_chat",
    "named_call_id",
    "resolve_live_call",
    "router",
    "verify_agent_secret",
]
