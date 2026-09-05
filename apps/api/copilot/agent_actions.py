"""The actions that BUILD and the actions that GO LIVE — one of the first tier, three of
the second.

D-500. The four tools that shipped first (`write_tools.py`) all act on a row a person is
already looking at: a lead's status, a number's suppression, a running campaign, a knowledge
entry. Nothing in the assistant could bring an object into existence, and the founder's own
transcript is what that cost: asked to "create a new agent for handling outbound campaigns",
the model had no tool for it, was told by the prompt to be proactive and not hand the
question back, and filled the twenty-one extraction-schema variables that happened to be
writable on the screen in front of it. The root fix is not a prompt sentence. It is that
this file exists.

═══ WHY THESE FOUR, AND WHY THEY SIT IN THESE TIERS ═══

`agent_create` is `immediate` because a draft is the safest object this product has: it
takes no calls and places none (`check_dispatch` refuses `status <> 'live'` per contact, and
the engine holds nothing for it at all), it is renameable and archivable, and creating one
spends nothing. `agent_rename` is `immediate` for the neighbouring reason — the name is ours,
not the caller's; nobody on a phone ever hears it, and renaming it back restores the world.

`agent_publish` and `campaign_launch` are `confirm`, and they are the two this platform's
hard rule 5 is written about. One puts an AI on a real phone line; the other starts dialling
strangers. Neither is undoable in the only direction that matters — a call already answered
or already placed is not recallable — so neither may happen without a person clicking.

═══ WHY NEITHER OF THOSE TWO IS A NEW GATE ═══

**Both executors call the SAME function the button calls, and that is the whole compliance
argument.** `lifecycle.activate_agent` is what `POST /v1/agents/{id}/activate` calls, and it
publishes rather than writing a column — so D-64's read-back, the truthful-answer directive,
the account-open check, `agent_has_no_script` and the engine capability check all run here
because they run THERE. `campaigns_service.launch_campaign` is what
`POST /v1/campaigns/{id}/launch` calls, and SEC-COMP §3's gate (`launch_blockers`), the
agent-row lock, the DNC scrub and the CAS to `running` are inside it. There is no second
implementation to keep in step, no flag, and no "fast path": hard rule 5's "never add a
bypass" is satisfied structurally rather than by review.

The planners ALSO ask the gate, read-only, and that is not a duplicate enforcement — it is
so the card a person approves states the truth and so a blocked launch is explained BEFORE
anybody clicks. `_plan_campaign_launch` refuses with the blocker names when the gate would
refuse, which reaches the model as a `WriteRefusedError` and comes out as "you cannot launch
this yet because ..." instead of a 422 after a click. The gate that ENFORCES is still the one
inside `launch_campaign`, and it runs again with the row locked.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Final
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import lifecycle
from apps.api.agents.models import AGENT_DIRECTIONS, AgentDirection
from apps.api.agents.voices import Language
from apps.api.campaigns import service as campaigns_service
from apps.api.copilot.actions import (
    DOES_IT,
    PROPOSES_ONLY,
    ActionTool,
    Executed,
    Plan,
    ToolActor,
    WriteRefusedError,
    action_schema,
    parse_args,
)
from apps.api.copilot.sanitize import strip_invisible
from apps.api.core.errors import ProblemError
from apps.api.db.ownership import assert_visible

#: The three languages an agent can be born speaking (`agents/voices.Language`), read off
#: that Literal rather than retyped so a fourth language reaches the model's enum the day it
#: reaches the column's.
_LANGUAGES: Final[tuple[str, ...]] = ("te-IN", "hi-IN", "en-IN")

#: The longest an agent's name may be — `AgentCreateIn.name`'s own ceiling, which the
#: column and the create form already agree on. Stated as a constant so the refusal the
#: model reads and the constraint the database holds are the same number.
_MAX_AGENT_NAME: Final = 120


#: How a language reads in a sentence a person approves. Machine tags are what the column
#: holds; "Telugu" is what somebody checking a card needs to see.
_LANGUAGE_LABELS: Final[dict[str, str]] = {
    "te-IN": "Telugu",
    "hi-IN": "Hindi",
    "en-IN": "Indian English",
}

#: And the same for the calling direction, which is the field the founder's own request
#: turned on ("should handle outbound calling").
_DIRECTION_LABELS: Final[dict[str, str]] = {
    "inbound": "answers incoming calls",
    "outbound": "makes outgoing calls",
    "both": "answers incoming calls and makes outgoing calls",
}

#: What every voice minute costs, said the same way on both `confirm` cards. Deliberately
#: NOT a number: hard rule 7 keeps rupees in NUMERIC columns, the per-minute rate is a
#: property of the account's plan and its model choice, and a figure invented in a prompt
#: module would be the exact defect hard rule 11 exists for. The card says WHAT is billed
#: and sends the person to the screen that holds the amount.
_BILLED_PER_MINUTE: Final = (
    "Calls are billed per minute at your plan's rate — see Billing for the amount."
)


# --- tool 5: agent_create ---------------------------------------------------------------


class _AgentCreateArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    direction: AgentDirection
    language_primary: Language


async def _plan_agent_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY, and the read is a DUPLICATE CHECK rather than an authorization one.

    Nothing has to be resolved to create an agent — which is exactly why this planner has a
    job to do at all. The failure mode of a create action is not a 404, it is a SECOND
    "Reception" sitting under the first because the person asked twice and the first answer
    scrolled away. `run_immediate`'s idempotency record closes the mechanical half of that
    (the same request, retried); this closes the human half, by telling the model the name is
    taken so it can ask rather than duplicate.

    A refusal and not a silent rename: picking `Reception 2` on somebody's behalf is the
    class of helpfulness that produced the twenty-one filled variables.
    """
    del actor
    parsed = parse_args(_AgentCreateArgs, args)
    name = strip_invisible(parsed.name.strip())
    if not name:
        raise WriteRefusedError("the agent's `name` was blank, so ask the person what to call it")
    if len(name) > _MAX_AGENT_NAME:
        raise WriteRefusedError(
            f"the agent's `name` is longer than {_MAX_AGENT_NAME} characters, so shorten it"
        )
    taken = (
        await session.execute(
            # RLS scopes this to the caller's own account, so a neighbour's agent of the
            # same name is invisible here exactly as it is everywhere else.
            text(
                "SELECT count(*) FROM agents WHERE lower(name) = lower(:name) "
                "AND deleted_at IS NULL"
            ),
            {"name": name},
        )
    ).scalar()
    if taken:
        raise WriteRefusedError(
            "this account already has an agent with that name, so ask the person for a "
            "different one rather than making a second"
        )
    return Plan(
        # NO OBJECT YET, and `""` is the honest spelling of that. The id the create produces
        # rides back on `Executed.object_id`, which is what the audit row and the person's
        # "where is it" both need.
        object_id="",
        title="Create a draft agent",
        summary=(
            f"Create a draft voice agent called “{name}” that "
            f"{_DIRECTION_LABELS[parsed.direction]}, speaking "
            f"{_LANGUAGE_LABELS[parsed.language_primary]}. It starts as a DRAFT: it answers "
            "nothing and calls nobody until it has a script and somebody publishes it."
        ),
        current=None,
        proposed=f"{name} — draft, {_LANGUAGE_LABELS[parsed.language_primary]}",
        cost=None,
        reversal=(
            "A draft reaches no caller. You can rename it, or archive it, from the Agents screen."
        ),
        args={
            "name": name,
            "direction": parsed.direction,
            "language_primary": parsed.language_primary,
        },
    )


async def _execute_agent_create(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`lifecycle.create_agent` — the function `POST /v1/agents` calls, unchanged.

    Which is the point. That function is the ONE insert into `agents` on any path a client
    reaches (`scripts/check_compliance_invariants.AGENT_STATE_WRITERS` registers its writers
    and fails the build on a third), and it is where hard rule 5's floor is written: both
    `ai_disclosure_line` and `recording_notice_line` composed from the language templates,
    both toggles TRUE, neither takeable from a caller. So an agent the assistant created has
    an AI disclosure on file for the same reason one a person created does — there is no
    argument to this call that could produce one without.
    """
    parsed = parse_args(_AgentCreateArgs, args)
    agent_id = await lifecycle.create_agent(
        session,
        tenant_id=actor.tenant_id,
        name=parsed.name,
        direction=parsed.direction,
        language_primary=parsed.language_primary,
    )
    return Executed(
        applied=True,
        detail=(
            f"“{parsed.name}” exists as a draft. It has an AI disclosure and a recording "
            "notice already written for it. Give it a script, then publish it when you are "
            "ready — it takes no calls until then."
        ),
        # Ids and closed-set strings (hard rules 4 and 6). The NAME is a client's own
        # business copy and `audit_log` is append-only, so text written into it is text a
        # DPDP erasure cannot reach; the `agents` row is where the name lives and where
        # deletion already gets to it.
        audit_summary={
            "agent_id": str(agent_id),
            "direction": parsed.direction,
            "language_primary": parsed.language_primary,
            "status": "draft",
        },
        object_id=str(agent_id),
    )


AGENT_CREATE: Final = ActionTool(
    name="agent_create",
    # TIER 1. A draft answers nothing, calls nobody and costs nothing; see the module
    # docstring. Every other property of a Tier 2 action still holds — the permission is
    # checked, the audit row is written, the idempotency record is claimed.
    tier="immediate",
    # `POST /v1/agents`'s own permission. Staff do not hold it and are refused inside the
    # tool, which is where `run_read_tool` puts the same check.
    permission="org:manage",
    object_type="agent",
    audit_action="agent.created",
    where="under Agents in your dashboard",
    schema=action_schema(
        "agent_create",
        "Create a new voice agent for this business, as a DRAFT. Use this whenever the "
        "person asks you to make, add, set up or create an agent — it works from any "
        "screen, so do NOT ask them to go to the Agents page first, and do NOT try to do "
        "it by filling in form fields. A draft answers no calls and places none until it "
        "has a script and somebody publishes it. If you do not know what to call it, what "
        "direction it should have, or which language it should speak, ASK for the missing "
        "ones in one short question before calling this." + DOES_IT,
        {
            "name": {
                "type": "string",
                "description": (
                    "What the business wants to call this agent, in their own words, e.g. "
                    "'Reception' or 'Outbound sales'. Never invented — ask if they have not "
                    "said."
                ),
            },
            "direction": {
                "type": "string",
                "enum": list(AGENT_DIRECTIONS),
                "description": (
                    "`inbound` if it answers the business's phone, `outbound` if it makes "
                    "calls for campaigns, `both` if it does both."
                ),
            },
            "language_primary": {
                "type": "string",
                "enum": list(_LANGUAGES),
                "description": (
                    "The language it mainly speaks to callers in: te-IN Telugu, hi-IN "
                    "Hindi, en-IN Indian English."
                ),
            },
        },
    ),
    plan=_plan_agent_create,
    execute=_execute_agent_create,
)


# --- tool 6: agent_rename ---------------------------------------------------------------


class _AgentRenameArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID
    name: str


async def _agent_name_and_status(session: AsyncSession, agent_id: UUID) -> tuple[str, str]:
    """One agent's name and status, or a 404 — which under RLS is also a neighbour's answer.

    `assert_visible` is asked FIRST rather than inferring visibility from an empty row,
    because it is the tenancy question and this repo answers it in one place
    (`db/ownership.py`). The SELECT that follows is then a fact-read, not a permission check.
    """
    await assert_visible(session, "agent", agent_id)
    row = (
        await session.execute(
            text("SELECT name, status FROM agents WHERE id = :aid AND deleted_at IS NULL"),
            {"aid": agent_id},
        )
    ).first()
    if row is None:  # pragma: no cover - `assert_visible` has already 404'd an absent row
        raise ProblemError.not_found("Agent")
    return strip_invisible(str(row[0])), str(row[1])


async def _plan_agent_rename(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY. The OLD name is quoted back, because "rename it" with only the new name in
    front of you is a sentence a person cannot check."""
    del actor
    parsed = parse_args(_AgentRenameArgs, args)
    name = strip_invisible(parsed.name.strip())
    if not name:
        raise WriteRefusedError("the new `name` was blank, so ask the person what to call it")
    if len(name) > _MAX_AGENT_NAME:
        raise WriteRefusedError(
            f"the new `name` is longer than {_MAX_AGENT_NAME} characters, so shorten it"
        )
    current, _status = await _agent_name_and_status(session, parsed.agent_id)
    return Plan(
        object_id=str(parsed.agent_id),
        title="Rename this agent",
        summary=(
            f"Rename “{current}” to “{name}”. This is the name you see in your own "
            "dashboard; it changes nothing a caller hears."
        ),
        current=current,
        proposed=name,
        cost=None,
        reversal="Rename it back at any time from the Agents screen.",
        args={"agent_id": str(parsed.agent_id), "name": name},
    )


async def _execute_agent_rename(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`lifecycle.update_agent` — the function `PATCH /v1/agents/{id}` calls, unchanged.

    Which carries one behaviour worth naming here rather than discovering: a LIVE agent is
    re-published to the voice platform in the same transaction, and if that push fails
    nothing is saved. That is why the rename of a live agent can raise, and why a failure
    reaches the person as the publish's own refusal rather than as a half-applied name.
    """
    parsed = parse_args(_AgentRenameArgs, args)
    before, _status = await _agent_name_and_status(session, parsed.agent_id)
    await lifecycle.update_agent(
        session,
        tenant_id=actor.tenant_id,
        agent_id=parsed.agent_id,
        name=parsed.name,
    )
    applied = before != parsed.name
    return Executed(
        applied=applied,
        detail=(
            f"That agent is now called “{parsed.name}”."
            if applied
            else f"That agent was already called “{parsed.name}”, so nothing changed."
        ),
        audit_summary={"agent_id": str(parsed.agent_id), "renamed": applied},
    )


AGENT_RENAME: Final = ActionTool(
    name="agent_rename",
    # TIER 1. The name is ours, not the caller's — nobody on a phone hears it — and renaming
    # it back restores the world exactly.
    tier="immediate",
    permission="org:manage",
    object_type="agent",
    audit_action="agent.updated",
    where="under Agents in your dashboard",
    schema=action_schema(
        "agent_rename",
        "Change what one of this business's voice agents is called in their dashboard. "
        "Works from any screen. This is the internal name only — it changes nothing a "
        "caller hears, and it does not change what the agent says or does." + DOES_IT,
        {
            "agent_id": {
                "type": "string",
                "description": (
                    "The agent's id, from the SCREEN STATE or from an `agents_list` lookup. "
                    "Never invented — look it up if you do not have it."
                ),
            },
            "name": {"type": "string", "description": "The new name, in the person's words."},
        },
    ),
    plan=_plan_agent_rename,
    execute=_execute_agent_rename,
)


# --- tool 7: agent_publish (TIER 2) -----------------------------------------------------


class _AgentPublishArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: UUID


async def _plan_agent_publish(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY, and the status read is what makes the card honest rather than a label.

    An ARCHIVED agent is refused here rather than at execute, because `activate_agent`'s
    refusal for it is correct but arrives after somebody has clicked Confirm on a card that
    implied it would work. Everything else — no script, a closed account, an engine that
    cannot host agents, a read-back that proves the engine did not take the change — is left
    to `publish_agent`, deliberately: those are conditions that can change between the card
    being drawn and the button being pressed, and the gate that decides them must be the one
    holding the row.
    """
    del actor
    parsed = parse_args(_AgentPublishArgs, args)
    name, status = await _agent_name_and_status(session, parsed.agent_id)
    if status == "archived":
        raise WriteRefusedError(
            "that agent is archived, so it cannot be published — tell the person to restore "
            "it first from the Agents screen"
        )
    return Plan(
        object_id=str(parsed.agent_id),
        title="Put this agent on the phone",
        summary=(
            f"Publish “{name}” to the voice platform so it answers and places real calls. "
            f"It is {status} right now. Calevate checks that the platform is really holding "
            "this agent's script, its voice and its AI-disclosure line before anything goes "
            "live; if that check fails, nothing changes."
        ),
        current=status,
        proposed="live",
        cost=_BILLED_PER_MINUTE,
        reversal=(
            "You can switch it off again from the Agents screen, which also stops its "
            "numbers answering. Calls it has already taken cannot be undone."
        ),
        args={"agent_id": str(parsed.agent_id)},
    )


async def _execute_agent_publish(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`lifecycle.activate_agent` — the function `POST /v1/agents/{id}/activate` calls.

    NOT a column write, and that is the whole compliance property: `activate_agent` publishes
    (D-64), so the engine is created-or-updated and then READ BACK, and no column says `live`
    until the platform has been observed holding the script, the opening line and the
    truthful-answer directive. An agent with no script is refused by name
    (`agent_has_no_script`); a closed account is refused before the vendor is touched. This
    module adds nothing to that and takes nothing away.
    """
    parsed = parse_args(_AgentPublishArgs, args)
    result = await lifecycle.activate_agent(
        session, tenant_id=actor.tenant_id, agent_id=parsed.agent_id
    )
    return Executed(
        applied=result.changed,
        detail=(
            "That agent is live. It is now answering the numbers bound to it and can be "
            "used by a campaign."
            if result.changed
            else "That agent was already live, so nothing changed."
        ),
        audit_summary={
            "agent_id": str(parsed.agent_id),
            "status": result.status,
            "moved": result.changed,
        },
    )


AGENT_PUBLISH: Final = ActionTool(
    name="agent_publish",
    # TIER 2 — IT PUTS AN AI ON A REAL PHONE LINE. A call already answered is not recallable,
    # so this may never happen without a person clicking.
    tier="confirm",
    permission="org:manage",
    object_type="agent",
    audit_action="agent.activated",
    where="under Agents in your dashboard",
    schema=action_schema(
        "agent_publish",
        "Propose putting one of this business's voice agents LIVE on the phone system, so "
        "it starts answering and placing real calls. Works from any screen. The agent must "
        "already have a script; if it does not, the platform refuses and tells you so — "
        "relay that refusal, do not try again." + PROPOSES_ONLY,
        {
            "agent_id": {
                "type": "string",
                "description": (
                    "The agent's id, from the SCREEN STATE or from an `agents_list` lookup. "
                    "Never invented."
                ),
            }
        },
    ),
    plan=_plan_agent_publish,
    execute=_execute_agent_publish,
)


# --- tool 8: campaign_launch (TIER 2) ---------------------------------------------------


class _CampaignLaunchArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    campaign_id: UUID


async def _plan_campaign_launch(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Plan:
    """READ ONLY — and it asks SEC-COMP §3's gate, by calling the gate.

    `launch_blockers` is the same function `GET /{id}/launch-check` calls to render the
    launch button disabled with reasons, and `launch_campaign` calls it again with the
    agent row locked. Asking it here does not move the enforcement point one inch; what it
    buys is that a person is never shown a Confirm button for a launch the platform is
    going to refuse, and that the model is handed the blocker NAMES so it can say "your DLT
    registration is not active yet" instead of "something went wrong".

    THE BLOCKERS ARE A REFUSAL AND NOT A WARNING ON THE CARD. A card that listed the reasons
    beside a live Confirm button would be an invitation to click through a compliance gate,
    which is the shape hard rule 5 exists to forbid even where the gate underneath would
    hold.
    """
    parsed = parse_args(_CampaignLaunchArgs, args)
    row = (
        await session.execute(
            text("SELECT name, status FROM campaigns WHERE id = :cid"),
            {"cid": parsed.campaign_id},
        )
    ).first()
    if row is None:
        # RLS makes this the same answer for a neighbour's campaign, deliberately.
        raise ProblemError.not_found("Campaign")
    name, status = strip_invisible(str(row[0])), str(row[1])
    blockers = await campaigns_service.launch_blockers(
        session, tenant_id=actor.tenant_id, campaign_id=parsed.campaign_id
    )
    if blockers:
        # The RULE NAMES and the platform's own reasons, both of which this repo authors —
        # never a value from the campaign. They become a tool result and then the model's
        # sentence to the person.
        listed = "; ".join(f"{blocker.rule}: {blocker.reason}" for blocker in blockers)
        raise WriteRefusedError(
            f"this campaign cannot launch yet and nothing was proposed — {listed}. Tell the "
            "person exactly this, and do not try to launch it again"
        )
    dialable = (
        await session.execute(
            text(
                "SELECT count(*) FROM campaign_contacts WHERE campaign_id = :cid "
                "AND status = 'pending'"
            ),
            {"cid": parsed.campaign_id},
        )
    ).scalar()
    return Plan(
        object_id=str(parsed.campaign_id),
        title="Start calling on this campaign",
        summary=(
            f"Launch “{name}” and start dialling. It is {status} right now, and "
            f"{int(dialable or 0)} contacts are waiting to be called. Numbers on your "
            "do-not-call list are removed before the first dial, and calls only go out "
            "inside the campaign's calling hours."
        ),
        current=status,
        proposed="running",
        cost=_BILLED_PER_MINUTE,
        reversal=(
            "You can pause it from the campaign screen, which stops the remaining dials. "
            "Calls that have already been placed cannot be recalled."
        ),
        args={"campaign_id": str(parsed.campaign_id)},
    )


async def _execute_campaign_launch(
    session: AsyncSession, actor: ToolActor, args: Mapping[str, Any]
) -> Executed:
    """`campaigns_service.launch_campaign` — the function `POST /{id}/launch` calls.

    HARD RULE 5, STRUCTURALLY. The compliance gate is INSIDE that function, after it takes
    the agent-row lock and before the CAS to `running`, and it re-runs from scratch: the
    verdict this module read while drawing the card is not carried forward, passed in, or
    trusted. A campaign whose DLT template was withdrawn, whose agent was archived, or whose
    consent provenance was cleared between the card and the click is refused at the click,
    with the blockers named, exactly as it would be for the button.
    """
    parsed = parse_args(_CampaignLaunchArgs, args)
    result = await campaigns_service.launch_campaign(
        session, tenant_id=actor.tenant_id, campaign_id=parsed.campaign_id
    )
    return Executed(
        applied=True,
        detail=(
            f"That campaign is running. {result['dialable']} contacts are queued to be "
            f"called, and {result['dnc_scrubbed']} were removed because they are on your "
            "do-not-call list."
        ),
        audit_summary={
            "dialable": result["dialable"],
            "dnc_scrubbed": result["dnc_scrubbed"],
        },
    )


CAMPAIGN_LAUNCH: Final = ActionTool(
    name="campaign_launch",
    # TIER 2 — IT DIALS REAL PHONE NUMBERS. The highest blast radius in this product.
    tier="confirm",
    # `POST /{campaign_id}/launch`'s own permission, which staff do not hold.
    permission="leads:dispatch",
    object_type="campaign",
    audit_action="campaign.launched",
    where="on the campaign's own screen",
    schema=action_schema(
        "campaign_launch",
        "Propose launching an outbound campaign, so the platform starts calling the "
        "contacts on it. Works from any screen. Calevate checks every compliance "
        "requirement first — the client's DLT registration, an approved template, consent "
        "provenance for the list, a live agent — and refuses with the reasons if any is "
        "missing. If it refuses, tell the person the reasons and do NOT call this again."
        + PROPOSES_ONLY,
        {
            "campaign_id": {
                "type": "string",
                "description": (
                    "The campaign's id, from the SCREEN STATE or from a `campaigns_list` "
                    "lookup. Never invented."
                ),
            }
        },
    ),
    plan=_plan_campaign_launch,
    execute=_execute_campaign_launch,
)


#: Registration order is wire order and is therefore part of the cacheable prompt prefix.
#: New actions APPEND; they never insert.
AGENT_ACTIONS: Final[tuple[ActionTool, ...]] = (
    AGENT_CREATE,
    AGENT_RENAME,
    AGENT_PUBLISH,
    CAMPAIGN_LAUNCH,
)

__all__ = [
    "AGENT_ACTIONS",
    "AGENT_CREATE",
    "AGENT_PUBLISH",
    "AGENT_RENAME",
    "CAMPAIGN_LAUNCH",
]
