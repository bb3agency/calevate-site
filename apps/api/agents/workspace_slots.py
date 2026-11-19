"""Who holds the calling setups in a client's own workspace, and the refusal that names them.

A calling setup is one engine agent object in the client's ThinnestAI customer workspace,
whether or not it is on a call. The platform caps how many may EXIST per workspace (2 on
pay-as-you-go, raised per workspace on request, VENDOR-STATED 23 Oct 2026,
`docs/vendor/thinnest-relationship-2026-10-23.md:136-142`); that is not the account's call
concurrency, which is a separate account-wide limit. The cap is the console's
`thinnest_agents_per_workspace`; `agents/service._allowance_full` decides when it is reached.

What this module adds is WHO holds them, so the refusal can say what to free instead of a
bare count: each agent, inbound line, campaign, script trial or test call holding one, and
any whose deletion is owed and has not run yet (the platform still counts those). The list is
read from the same rows, with the same filter, as `service.engine_agents_in_workspace` counts.

The screen gets the holders as typed problem+json extension members (RFC 9457 §3.2,
`EngineAgentAllowanceFull`) and the launch checklist as `BlockerOut.holders`. The sentence
(`allowance_reason`) names kinds and counts, never a name: it also reaches Pip as a tool
result, and a client-authored name there is text the model would read as instructions.
"""

from __future__ import annotations

from collections import Counter
from typing import ClassVar, Final, Literal
from uuid import UUID

from calevate_shared.engine_scope import scope_of
from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemExtension, problem_responses

#: The refusal's problem code and launch-gate rule.
ENGINE_AGENT_ALLOWANCE_FULL_RULE: Final = "engine_agent_allowance_full"

#: `test_call`: an agent's test copy made in the workspace for a test call from the client's
#: own number (D-1020), given back an hour after its last use.
SlotHolderKind = Literal["agent", "inbound_line", "campaign", "script_trial", "test_call"]

#: What was being attempted when there was no free setup, so the sentence fits the button
#: the owner pressed: a test call, Start (or a scheduled start), or putting a line live.
AllowanceContext = Literal["test_call", "start", "line_live"]


class SlotHolder(BaseModel):
    """One calling setup in the workspace. `id` is the agent's for an agent or a script
    trial of it, the line's for a line, the campaign's for a campaign. `removing`: its
    holder has let go of it and the deletion has not run yet; nothing to do but wait."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SlotHolderKind
    id: UUID
    name: str
    removing: bool


class EngineAgentAllowanceFull(ProblemExtension):
    """No free calling setup: the cap, what was attempted and every setup held."""

    code: ClassVar[str] = ENGINE_AGENT_ALLOWANCE_FULL_RULE
    status: ClassVar[int] = 422

    context: AllowanceContext
    limit: int
    holders: list[SlotHolder]


#: `responses=` for every route that can make a new engine agent: a test call, Start, putting
#: a line live.
SLOTS_FULL_RESPONSES: Final = problem_responses(EngineAgentAllowanceFull)


#: Every active route of this tenant on this engine; the workspace is matched on the ref's
#: scope in Python, as the count does. `engine_agent_routes` carries `tenant_id` without an
#: RLS policy on it (`db/registry`), so the tenant filter here is what keeps another
#: account's setups out; the joined tables are RLS-scoped as well.
_HOLDERS_SQL: Final = (
    "SELECT r.engine_agent_ref, r.agent_id, r.inbound_line_id, r.campaign_id, "
    "c.name, c.engine_agent_ref IS NOT DISTINCT FROM r.engine_agent_ref, "
    "l.name, l.engine_agent_ref IS NOT DISTINCT FROM r.engine_agent_ref, "
    "a.name, a.engine_agent_ref IS NOT DISTINCT FROM r.engine_agent_ref, "
    "EXISTS (SELECT 1 FROM prompt_experiment_variants v "
    "        WHERE v.engine_agent_ref = r.engine_agent_ref), "
    "EXISTS (SELECT 1 FROM agent_test_copies t "
    "        WHERE t.agent_id = r.agent_id AND t.engine_agent_ref = r.engine_agent_ref) "
    "FROM engine_agent_routes r "
    "LEFT JOIN campaigns c ON c.id = r.campaign_id "
    "LEFT JOIN inbound_lines l ON l.id = r.inbound_line_id "
    "LEFT JOIN agents a ON a.id = r.agent_id "
    "WHERE r.tenant_id = :tid AND r.engine = :engine AND r.active "
    "ORDER BY r.created_at, r.engine_agent_ref"
)


async def slot_holders(
    session: AsyncSession, *, tenant_id: UUID, engine: str, workspace: str
) -> list[SlotHolder]:
    """The calling setups this client holds in `workspace`, oldest first."""
    rows = (await session.execute(text(_HOLDERS_SQL), {"tid": tenant_id, "engine": engine})).all()
    holders: list[SlotHolder] = []
    for (
        ref,
        agent_id,
        line_id,
        campaign_id,
        c_name,
        c_holds,
        l_name,
        l_holds,
        a_name,
        a_holds,
        arm,
        test_copy,
    ) in rows:
        if scope_of(str(ref)) != workspace:
            continue
        if test_copy:
            holder = SlotHolder(
                kind="test_call", id=agent_id, name=str(a_name or ""), removing=False
            )
        elif campaign_id is not None:
            holder = SlotHolder(
                kind="campaign", id=campaign_id, name=str(c_name or ""), removing=not c_holds
            )
        elif line_id is not None:
            holder = SlotHolder(
                kind="inbound_line", id=line_id, name=str(l_name or ""), removing=not l_holds
            )
        elif arm:
            holder = SlotHolder(
                kind="script_trial", id=agent_id, name=str(a_name or ""), removing=False
            )
        else:
            holder = SlotHolder(
                kind="agent", id=agent_id, name=str(a_name or ""), removing=not a_holds
            )
        holders.append(holder)
    return holders


_LEADS: Final[dict[AllowanceContext, str]] = {
    "test_call": "Test calls need a free calling setup.",
    "start": "Starting needs a free calling setup.",
    "line_live": "Putting a line live needs a free calling setup.",
}

_KIND_WORDS: Final[dict[SlotHolderKind, tuple[str, str]]] = {
    "agent": ("agent", "agents"),
    "inbound_line": ("inbound line", "inbound lines"),
    "campaign": ("campaign", "campaigns"),
    "script_trial": ("script trial", "script trials"),
    "test_call": ("test call", "test calls"),
}


def _held_by(holders: list[SlotHolder]) -> str:
    kinds = Counter(h.kind for h in holders if not h.removing)
    parts = [
        f"{count} {_KIND_WORDS[kind][0 if count == 1 else 1]}"
        for kind, count in sorted(kinds.items(), key=lambda item: list(_KIND_WORDS).index(item[0]))
    ]
    removing = sum(1 for h in holders if h.removing)
    if removing:
        parts.append(f"{removing} being removed")
    return ", ".join(parts)


def allowance_reason(limit: int, holders: list[SlotHolder], context: AllowanceContext) -> str:
    """The refusal's sentence: what was attempted, the cap, and what holds the setups by kind."""
    in_use = "it is" if limit == 1 else "both are" if limit == 2 else "all are"
    held = _held_by(holders)
    return f"{_LEADS[context]} Your account can have {limit}, and {in_use} in use" + (
        f": {held}." if held else "."
    )


def allowance_remediation(holders: list[SlotHolder]) -> str:
    """What the owner can do about it, said with every form of the refusal. Only the steps
    that would free one of THESE setups: an agent's own setup, a script trial's and a test
    call's are not the owner's to free (archiving an agent keeps its engine agent), so a
    workspace full of those is ours to clear."""
    kinds = {h.kind for h in holders if not h.removing}
    steps = [
        step
        for kind, step in (
            ("inbound_line", "archive an inbound line you no longer use"),
            ("campaign", "stop a campaign"),
        )
        if kind in kinds
    ]
    if not steps:
        return "Ask us to free one or to raise your limit."
    first = " or ".join(steps)
    return f"{first[0].upper()}{first[1:]} to free one. To have more, ask us to raise your limit."


__all__ = [
    "ENGINE_AGENT_ALLOWANCE_FULL_RULE",
    "SLOTS_FULL_RESPONSES",
    "AllowanceContext",
    "EngineAgentAllowanceFull",
    "SlotHolder",
    "SlotHolderKind",
    "allowance_reason",
    "allowance_remediation",
    "slot_holders",
]
