"""Who holds the calling setups in a client's own workspace, and the refusal that names them.

A calling setup is one engine agent object in the client's ThinnestAI customer workspace,
whether or not it is on a call. The platform caps how many may EXIST per workspace (2 on
pay-as-you-go, raised per workspace on request, VENDOR-STATED 23 Oct 2026,
`docs/vendor/thinnest-relationship-2026-10-23.md:136-142`); that is not the account's call
concurrency, which is a separate account-wide limit. The cap is
`workspace_agent_allowance`: the one the vendor raised for this client's workspace when an
operator recorded it, else the console's `thinnest_agents_per_workspace`. Raising the console
value instead would let every client past the vendor's cap. `agents/service._allowance_full`
decides when it is reached.

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
from apps.api.core.settings import get_settings

#: The refusal's problem code and launch-gate rule.
ENGINE_AGENT_ALLOWANCE_FULL_RULE: Final = "engine_agent_allowance_full"
#: The platform's own refusal of a new agent in a full workspace (`engine/thinnest.
#: AGENT_ALLOWANCE_USED`), named here because only the engine package may import the adapter.
ENGINE_AGENT_ALLOWANCE_USED_CODE: Final = "engine_agent_allowance_used"
#: Either refusal: our count said the workspace is full, or the platform did.
SLOTS_FULL_CODES: Final = frozenset(
    {ENGINE_AGENT_ALLOWANCE_FULL_RULE, ENGINE_AGENT_ALLOWANCE_USED_CODE}
)

#: The campaign statuses whose engine agent is kept: it is dialling, or paused so Resume
#: dials at once; every other state retires it. A scheduled campaign holds none (D-1010):
#: the engine agent takes one of the workspace's few slots, so it is made when the start
#: fires, not when it is set, and a repeat gives it back between runs.
CAMPAIGN_HOLDING_STATUSES: Final = ("running", "paused")

#: `test_call`: an agent's test copy made in the workspace for a test call from the client's
#: own number (D-1020), given back an hour after its last use.
SlotHolderKind = Literal["agent", "inbound_line", "campaign", "script_trial", "test_call"]

#: What was being attempted when there was no free setup, so the sentence fits the button
#: the owner pressed: a test call, Start (or a scheduled start), or putting a line live.
AllowanceContext = Literal["test_call", "start", "line_live"]


class SlotHolder(BaseModel):
    """One calling setup in the workspace. `id` is the agent's for an agent or a script
    trial of it, the line's for a line, the campaign's for a campaign. `removing`: its
    holder has let go of it and the deletion has not run yet; nothing to do but wait.
    `test_only`: a draft line's or a not-started campaign's, held only for its test calls;
    a Start or a line put live takes its place once no test call is on it, so archiving the
    line or stopping the campaign is not what frees it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: SlotHolderKind
    id: UUID
    name: str
    removing: bool
    test_only: bool = False


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


async def workspace_agent_override(session: AsyncSession, tenant_id: UUID) -> int | None:
    """The cap an operator recorded for this client's workspace, None when it has none (or no
    workspace row yet). Read in the caller's tenant session, under RLS."""
    value = (
        await session.execute(
            text("SELECT agent_allowance FROM tenant_engine_workspaces WHERE tenant_id = :tid"),
            {"tid": tenant_id},
        )
    ).scalar_one_or_none()
    return int(value) if value is not None else None


async def workspace_agent_allowance(session: AsyncSession, tenant_id: UUID) -> int:
    """How many engine agents this client's own workspace may hold: its recorded override,
    else the console's `thinnest_agents_per_workspace`. The ONE reader of the limit."""
    override = await workspace_agent_override(session, tenant_id)
    return override if override is not None else get_settings().thinnest_agents_per_workspace


#: Every active route of this tenant on this engine; the workspace is matched on the ref's
#: scope in Python, as the count does. `engine_agent_routes` carries `tenant_id` without an
#: RLS policy on it (`db/registry`), so the tenant filter here is what keeps another
#: account's setups out; the joined tables are RLS-scoped as well.
_HOLDERS_SQL: Final = (
    "SELECT r.engine_agent_ref, r.agent_id, r.inbound_line_id, r.campaign_id, "
    "c.name, c.engine_agent_ref IS NOT DISTINCT FROM r.engine_agent_ref, "
    "c.status = ANY(:holding) AND c.archived_at IS NULL, "
    "l.name, l.engine_agent_ref IS NOT DISTINCT FROM r.engine_agent_ref, "
    "l.published_at IS NOT NULL, "
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
    rows = (
        await session.execute(
            text(_HOLDERS_SQL),
            {"tid": tenant_id, "engine": engine, "holding": list(CAMPAIGN_HOLDING_STATUSES)},
        )
    ).all()
    holders: list[SlotHolder] = []
    for (
        ref,
        agent_id,
        line_id,
        campaign_id,
        c_name,
        c_holds,
        c_going,
        l_name,
        l_holds,
        l_live,
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
                kind="campaign",
                id=campaign_id,
                name=str(c_name or ""),
                removing=not c_holds,
                test_only=bool(c_holds) and not c_going,
            )
        elif line_id is not None:
            holder = SlotHolder(
                kind="inbound_line",
                id=line_id,
                name=str(l_name or ""),
                removing=not l_holds,
                test_only=bool(l_holds) and not l_live,
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
    workspace full of those is ours to clear.

    A setup held only for test calls (an agent's test copy, a draft line's or a not-started
    campaign's) is not offered as a line to archive or a campaign to stop: Start and putting
    a line live take its place themselves once no test call is on it
    (`service.give_back_idle_test_holders`), and the hourly sweep otherwise."""
    live = [h for h in holders if not h.removing]
    kinds = {h.kind for h in live if not h.test_only}
    steps = [
        step
        for kind, step in (
            ("inbound_line", "archive an inbound line you no longer use"),
            ("campaign", "stop a campaign"),
        )
        if kind in kinds
    ]
    testing = any(h.test_only or h.kind == "test_call" for h in live)
    said: list[str] = []
    if steps:
        first = " or ".join(steps)
        said.append(f"{first[0].upper()}{first[1:]} to free one.")
    if testing:
        said.append(
            "A setup held for test calls is freed an hour after the last one, or when you "
            "start a campaign or put a line live with no test call on it."
        )
    if not said:
        return "Ask us to free one or to raise your limit."
    return " ".join([*said, "To have more, ask us to raise your limit."])


__all__ = [
    "CAMPAIGN_HOLDING_STATUSES",
    "ENGINE_AGENT_ALLOWANCE_FULL_RULE",
    "ENGINE_AGENT_ALLOWANCE_USED_CODE",
    "SLOTS_FULL_CODES",
    "SLOTS_FULL_RESPONSES",
    "AllowanceContext",
    "EngineAgentAllowanceFull",
    "SlotHolder",
    "SlotHolderKind",
    "allowance_reason",
    "allowance_remediation",
    "slot_holders",
    "workspace_agent_allowance",
    "workspace_agent_override",
]
