"""The ONE in-call door to a client's action, for every engine (D-700).

ThinnestAI reaches it through its custom actions (`worker/engine_actions.client_action`).
The route authenticates its caller, establishes WHICH call this is from its own records, and
hands
over a `CallFacts` — then everything after that is here: which action, whether it may run,
whether it runs now or in the background, and the sentence the agent says about it.

WHAT THE AGENT IS TOLD. The answer is `{status, say, …}`, the shape our own in-call tools
already use (`worker/engine_actions.py`): `say` is platform text telling the model what
happened and what it must NOT claim, because what an action returns may be read aloud
(agent/custom-api.md:187-199) and a model left to interpret `{"error": "no_credential"}`
will improvise. Client-facing words name no provider.

FAST AND SLOW. A write whose result the caller does not need to hear — a CRM record, a
sheet row — is acknowledged at once and finished by `workers/client_actions.py`; everything
else runs inside `IN_CALL_BUDGET_S`, below ThinnestAI's "Answer within 10 seconds"
(snapshots/2026-10-08/pages/mcp/own-database.md:48).

ONCE PER CALL. A turn the platform re-runs on its backup model can call an action again, so
an action runs once per call and arguments and a repeat answers with the first answer
(`reliability/in_call_once.py`). That is a separate guard from the caps below: a repeat is
answered without counting against them.

LIMITS PER CALL. ThinnestAI caps custom actions at thirty calls per conversation per hour
(agent/custom-api.md:147-155). Ours are tighter where an action reaches the caller or moves
money: two WhatsApp messages and two payment links per action per call, counted in Redis. A
counter we cannot read refuses those two (a message or a payment link sent twice is not
undone) and admits the rest.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

from calevate_shared.calling_window import today_in_india

from apps.api.actions.execution import CallFacts, ExecutionResult, execute_action
from apps.api.actions.schema import SheetsConfig
from apps.api.actions.service import LoadedTool, in_call_tool
from apps.api.actions.whatsapp import SPOKEN_CONSENT_ARGS, spoken_consent_from_args
from apps.api.core.logging import get_logger
from apps.api.core.queue import enqueue
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session
from apps.api.reliability.in_call_once import once_per_call
from apps.api.team_alerts import service as team_alerts

log = get_logger(__name__)

#: The whole in-call action. With the 2 s live-call read before it
#: (`worker/engine_actions.LIVE_CALL_BUDGET_S`) that is 8 s of the voice platform's ten, leaving
#: room for our own authentication and the vendor's round trip to us.
IN_CALL_BUDGET_S: Final = 6.0
#: A caller lookup runs under the agent's opening line; past this the agent carries on
#: without a name rather than leave the caller waiting after the greeting.
LOOKUP_BUDGET_S: Final = 4.0

#: The ARQ job that finishes a slow write (`apps.workers.client_actions`).
CLIENT_ACTION_JOB: Final = "run_client_action"

#: Per action, per call. Absent means unlimited by us (the vendor's thirty still applies).
PER_CALL_LIMITS: Final[dict[str, int]] = {"whatsapp": 2, "payment_link": 2}
#: The kinds that send the caller a WhatsApp, and so carry the caller's spoken answer.
MESSAGING_KINDS: Final = frozenset({"whatsapp", "payment_link"})
_LIMIT_TTL_S: Final = 3 * 3600

#: Outcomes that mean the client's connection is gone or broken: the agent says it cannot do
#: it right now, and the client's Needs-attention queue shows it (`crm/attention.py`).
CONNECTION_BROKEN: Final = frozenset({"no_credential", "credential_unusable", "auth_failed"})

NOT_AVAILABLE_SAY: Final = (
    "Nothing was done: this cannot be done right now. Do NOT tell the caller it is done. "
    "Apologise, say you cannot do that right now, and offer to note it for the team."
)
LIMIT_SAY: Final = (
    "Nothing was done: this has already been done as many times as allowed on this call. "
    "Do NOT do it again. Tell the caller it has already been sent."
)


@dataclass(frozen=True, slots=True)
class InCallAnswer:
    status: str
    say: str
    data: dict[str, Any] = field(default_factory=dict)

    def body(self) -> dict[str, Any]:
        return {"status": self.status, "say": self.say, **self.data}


def runs_in_background(tool: LoadedTool) -> bool:
    """A write the caller does not need to hear the result of."""
    if tool.kind == "crm":
        return True
    if tool.kind == "sheets":
        return SheetsConfig.model_validate(tool.config).operation == "record"
    return False


_ACCEPTED_SAY: Final = (
    "It is being saved now. You may tell the caller it has been noted. Do not read any "
    "details back as confirmed by the system."
)

_OK_SAY: Final[dict[str, str]] = {
    "delivered": (
        "The WhatsApp message was sent to the caller's number. Tell them it is on its way."
    ),
    "link_sent": (
        "The payment link was sent to the caller on WhatsApp. Tell them to open it there; "
        "say the amount in 'amount_inr' in rupees. Never read the link aloud."
    ),
    "booked": (
        "The booking is made. Read the time in 'say' back to the caller exactly as "
        "written, and confirm it."
    ),
    "checked": (
        "Offer the caller the times in 'free_slots', reading each 'say' exactly as written. "
        "If the list is empty, nothing is free in that window: ask for another day or time."
    ),
    "found": (
        "The caller's details are in 'details' (or 'data'). Greet them by name if one is "
        "there, and use what is there; never read out anything they did not ask about."
    ),
    "not_found": (
        "This caller is not in the records. Carry on normally; do not mention looking them up."
    ),
    "row_added": "Saved.",
    "row_updated": "Saved.",
    "crm_saved": "Saved.",
}

_REFUSAL_SAY: Final[dict[str, str]] = {
    "not_opted_in": (
        "Nothing was sent: this caller has not agreed to receive WhatsApp messages from this "
        "business. Do NOT say it was sent. Offer to give the details aloud instead."
    ),
    "blocked": (
        "Nothing was sent: this number may not be contacted. Do NOT say it was sent. Give the "
        "details aloud if they want them."
    ),
    "slot_taken": (
        "That time is no longer free. Do NOT say it is booked. Apologise and offer to check "
        "other times."
    ),
    "time_in_past": "That time has already passed. Ask the caller for a time in the future.",
    "outside_hours": (
        "Nothing was booked: the business does not take bookings at that time. Do NOT say "
        "it is booked. Offer a time inside its booking hours."
    ),
    "unreadable_time": (
        "Nothing was booked: the time could not be read. Ask the caller for the day and time "
        "again, then call this with the date and time in YYYY-MM-DDTHH:MM form, Indian time."
    ),
    "no_start_time": "Ask the caller which day and time they want, then call this again.",
    "no_end_time": "Ask the caller which day and time they want, then call this again.",
    "no_amount": "Ask the caller how much the payment is for, then call this again.",
    "amount_outside_rules": (
        "Nothing was sent: that amount cannot be taken by link on this call. Do NOT say a link "
        "was sent. Tell the caller the team will be in touch about the payment."
    ),
    "trial_payment_links": (
        "Nothing was sent: payment links do not work on a test call. Do NOT say a link was "
        "sent. Say a link would be sent here on a real call."
    ),
    "missing_template_value": (
        "Nothing was sent: some details are missing. Ask the caller for what 'missing' "
        "names, then call this again."
    ),
    "consent_not_asked": (
        "Nothing was sent: you did not ask first. Ask the caller, in their language, "
        "'Shall I send this on WhatsApp to this number?' and call this again with "
        "caller_agreed set to their answer and caller_words set to the words they said."
    ),
    "caller_declined": (
        "Nothing was sent: the caller does not want it on WhatsApp. Do NOT send it. Offer to "
        "give the details aloud instead."
    ),
    # D-943: the caller said no to messages inside the last 90 days, so asking is barred.
    "reask_locked": (
        "Nothing was sent. Do NOT ask the caller about WhatsApp on this call. Give the "
        "details aloud instead."
    ),
    "link_not_sent": (
        "Nothing reached the caller: the payment link could not be sent. Do NOT say it was "
        "sent. Apologise and say the team will send it."
    ),
}


#: Refusals that ask the agent to work out a day: they carry today's date, which the voice
#: platform does not otherwise give the model.
TIME_REFUSALS: Final = frozenset(
    {"unreadable_time", "time_in_past", "no_start_time", "no_end_time", "outside_hours"}
)


def say_for(result: ExecutionResult, *, now: datetime | None = None) -> str:
    """The platform sentence for one outcome. An unlisted failure is the honest default."""
    if result.ok:
        return _OK_SAY.get(result.status, "Done. Use the answer to reply to the caller.")
    said = _REFUSAL_SAY.get(result.status, NOT_AVAILABLE_SAY)
    hours = result.payload.get("hours")
    if result.status == "outside_hours" and isinstance(hours, str):
        said = f"{said} It takes bookings {hours}."
    if result.status in TIME_REFUSALS:
        said = f"{said} {today_in_india(now or datetime.now(UTC))}"
    return said


async def _within_limit(tool: LoadedTool, call: CallFacts) -> bool:
    limit = PER_CALL_LIMITS.get(tool.kind)
    if limit is None or not call.call_ref:
        return True
    key = f"actions:per-call:{tool.id}:{call.call_ref}"
    try:
        # INCR and EXPIRE NX in one round trip, `core/ratelimit.check`'s shape: as two
        # requests a failure between them left a counter with no expiry.
        pipe = get_redis().pipeline()
        pipe.incr(key)
        pipe.expire(key, _LIMIT_TTL_S, nx=True)
        count = int((await pipe.execute())[0])
    except Exception as exc:
        log.warning(
            "client_action_limit_unreadable",
            extra={"tool_id": str(tool.id), "error": type(exc).__name__},
        )
        return False
    return count <= limit


async def run_in_call_action(
    *, tenant_id: UUID, agent_id: UUID, name: str, args: dict[str, Any], call: CallFacts
) -> InCallAnswer:
    """Run (or accept) the client action `name` on this agent's call, once per call and
    arguments: a repeat answers with the first answer (`reliability/in_call_once.py`)."""
    if not call.call_ref:
        return await _run_in_call_action(
            tenant_id=tenant_id, agent_id=agent_id, name=name, args=args, call=call
        )

    async def _run() -> dict[str, Any]:
        answer = await _run_in_call_action(
            tenant_id=tenant_id, agent_id=agent_id, name=name, args=args, call=call
        )
        return answer.body()

    body = await once_per_call(
        call_ref=call.call_ref, action=f"client:{agent_id}:{name}", args=args, run=_run
    )
    status, say = str(body.get("status", "")), str(body.get("say", ""))
    return InCallAnswer(status, say, {k: v for k, v in body.items() if k not in ("status", "say")})


#: What the agent is told after `tell_the_team` (D-904).
TEAM_SAY: Final[dict[str, str]] = {
    "queued": (
        "The team has been told, with the caller's name and number and the problem you "
        "described. Tell the caller someone from the team will contact them. Do not promise "
        "a time."
    ),
    "already_told": (
        "The team was already told about this call. Tell the caller someone from the team "
        "will contact them. Do not promise a time."
    ),
    "unavailable": (
        "Nothing was sent: the team cannot be told from this call. Do NOT say the team was "
        "told or will call. Apologise and say you cannot pass this on right now."
    ),
}


async def _tell_the_team(
    *, tenant_id: UUID, agent_id: UUID, args: dict[str, Any], call: CallFacts
) -> InCallAnswer:
    outcome = await team_alerts.queue_in_call(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call.call_id,
        problem=args.get(team_alerts.TEAM_PROBLEM_PARAM),
    )
    return InCallAnswer(outcome, TEAM_SAY[outcome])


async def _run_in_call_action(
    *, tenant_id: UUID, agent_id: UUID, name: str, args: dict[str, Any], call: CallFacts
) -> InCallAnswer:
    if name == team_alerts.TEAM_ACTION_NAME:
        return await _tell_the_team(tenant_id=tenant_id, agent_id=agent_id, args=args, call=call)
    ids = {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    async with tenant_session(tenant_id) as session:
        tool = await in_call_tool(session, agent_id=agent_id, name=name)
        if tool is None:
            log.info("client_action_not_live", extra=ids)
            return InCallAnswer("unavailable", NOT_AVAILABLE_SAY)
        if not await _within_limit(tool, call):
            log.info("client_action_limit_reached", extra={**ids, "tool_id": str(tool.id)})
            return InCallAnswer("limit_reached", LIMIT_SAY)
        if runs_in_background(tool):
            if not call.call_ref:
                return InCallAnswer("unavailable", NOT_AVAILABLE_SAY)
            await enqueue(
                CLIENT_ACTION_JOB,
                {
                    "tenant_id": str(tenant_id),
                    "tool_id": str(tool.id),
                    "call_ref": call.call_ref,
                    "args": {k: str(v)[:1000] for k, v in args.items()},
                },
            )
            return InCallAnswer("accepted", _ACCEPTED_SAY)
        spoken = None
        if tool.kind in MESSAGING_KINDS and call.direction != "test":
            # The caller's answer to the agent's question travels apart from the template
            # values, so it can never fill a blank in the message.
            spoken = spoken_consent_from_args(
                args, call_id=call.call_id, call_ref=call.call_ref, action_id=tool.id
            )
        result = await execute_action(
            session,
            tool=tool,
            received={k: v for k, v in args.items() if k not in SPOKEN_CONSENT_ARGS},
            spoken=spoken,
            source="in_call",
            call=call,
            budget_s=LOOKUP_BUDGET_S if tool.kind == "caller_lookup" else IN_CALL_BUDGET_S,
        )
    if result.status in CONNECTION_BROKEN:
        log.warning(
            "client_action_connection_broken",
            extra={**ids, "tool_id": str(tool.id), "status": result.status},
        )
    log.info(
        "client_action_answered",
        extra={**ids, "tool_id": str(tool.id), "kind": tool.kind, "status": result.status},
    )
    data = {k: v for k, v in result.payload.items() if k != "error"}
    return InCallAnswer(result.status, say_for(result), data)


__all__ = [
    "CLIENT_ACTION_JOB",
    "CONNECTION_BROKEN",
    "IN_CALL_BUDGET_S",
    "MESSAGING_KINDS",
    "NOT_AVAILABLE_SAY",
    "PER_CALL_LIMITS",
    "InCallAnswer",
    "run_in_call_action",
    "runs_in_background",
    "say_for",
]
