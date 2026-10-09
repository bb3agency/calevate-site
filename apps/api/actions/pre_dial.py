"""Know who we are calling BEFORE we dial (D-700, caller lookup on outbound calls).

On an outbound call the lookup costs the caller nothing if it runs before the dial: ThinnestAI
takes the lead's `name` (at most 120 characters) and up to 20 `variables` "the agent's
instructions use as `{{name}}`", values cut to 150 characters
(`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/calls/place-call.md:
895-899, :912-917`). So `agents.service.dispatch_call` — the platform's one outbound entry
point — asks the agent's live `caller_lookup` action here and passes what it found as the
call's name and `caller_name` / `caller_details` variables.

On an INBOUND call no pre-answer hook is documented (the webhook events are lead.captured,
conversation.escalated/resolved, call.completed, call.analysed and contact.opted_out,
`api-reference/webhooks.md:79-85`; nothing fires on ringing), so the lookup there is the
agent's first action, right after its opening line (`reliability/engine_actions`
`client_definitions`). Whether a ThinnestAI contact's name reaches an inbound agent is not
documented either (OPERATIONS gate A-11).

The lookup reads only the number being dialled, in the dialling tenant's session, through
the same executor as every action; what comes back was redacted by it (`for_model`). A
lookup that fails or runs long dials anyway, without the name: it is a courtesy, never a
gate. HARD RULE 6: nothing here logs the number or what was found.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.actions.execution import CallFacts, execute_action
from apps.api.actions.service import in_call_tools
from apps.api.core.logging import get_logger

log = get_logger(__name__)

#: How long a dial may wait for the lookup. It delays the ring, not a caller on the line.
PRE_DIAL_BUDGET_S: Final = 3.0
NAME_MAX: Final = 120
VARIABLE_MAX: Final = 150
#: The variables a client's script may use, filled only on a call a lookup found.
CALLER_NAME_VARIABLE: Final = "caller_name"
CALLER_DETAILS_VARIABLE: Final = "caller_details"

_NAME_KEYS: Final = ("Full_Name", "full_name", "name", "Name")


@dataclass(frozen=True, slots=True)
class CallerPrefill:
    name: str | None = None
    variables: dict[str, str] = field(default_factory=dict)


def _name_of(details: dict[str, Any]) -> str | None:
    for key in _NAME_KEYS:
        value = details.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:NAME_MAX]
    first = str(details.get("First_Name") or details.get("firstname") or "").strip()
    last = str(details.get("Last_Name") or details.get("lastname") or "").strip()
    joined = f"{first} {last}".strip()
    return joined[:NAME_MAX] or None


def prefill_from(payload: dict[str, Any]) -> CallerPrefill:
    """A lookup's answer as a call's name and variables, or nothing when not found."""
    details = payload.get("details") or payload.get("data")
    if payload.get("found") is not True or not isinstance(details, dict):
        return CallerPrefill()
    name = _name_of(details)
    summary = "; ".join(f"{k}: {v}" for k, v in details.items() if str(v).strip())
    variables: dict[str, str] = {}
    if name:
        variables[CALLER_NAME_VARIABLE] = name[:VARIABLE_MAX]
    if summary:
        variables[CALLER_DETAILS_VARIABLE] = summary[:VARIABLE_MAX]
    return CallerPrefill(name=name, variables=variables)


async def pre_dial_lookup(
    session: AsyncSession, *, tenant_id: UUID, agent_id: UUID, phone_e164: str
) -> CallerPrefill:
    """Run the agent's live caller lookup for the number about to be dialled."""
    tool = next(
        (t for t in await in_call_tools(session, agent_id=agent_id) if t.kind == "caller_lookup"),
        None,
    )
    if tool is None:
        return CallerPrefill()
    result = await execute_action(
        session,
        tool=tool,
        received={},
        source="in_call",
        call=CallFacts(call_ref=None, caller_e164=phone_e164, direction="outbound"),
        budget_s=PRE_DIAL_BUDGET_S,
    )
    log.info(
        "pre_dial_lookup",
        extra={"tenant_id": str(tenant_id), "agent_id": str(agent_id), "status": result.status},
    )
    return prefill_from(result.payload) if result.ok else CallerPrefill()


__all__ = [
    "CALLER_DETAILS_VARIABLE",
    "CALLER_NAME_VARIABLE",
    "PRE_DIAL_BUDGET_S",
    "CallerPrefill",
    "pre_dial_lookup",
    "prefill_from",
]
