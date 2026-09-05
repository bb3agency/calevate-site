"""The ACTION framework: the tier is a property of the registry, and a Tier 1 action still
pays for everything except the click. D-500.

WHAT IS PROVED HERE, and the first two are the ones whose absence would be an incident
rather than a bug:

1. **THE TIER CANNOT BE OMITTED AND CANNOT BE INFERRED.** `ActionTool` refuses to construct
   without one, every registered action has one, and every action that runs WITHOUT a click
   is named in a reviewed list below — so a new action defaults to failing this file until
   somebody writes down why it is safe. The registry is ENUMERATED rather than retyped: the
   list here is the exception list, not a copy of the tools.
2. **THE TWO TIERS CANNOT LEAK INTO EACH OTHER.** `plan_write` will not mint a token for a
   Tier 1 tool, `run_immediate` will not run a Tier 2 one, and `confirm` refuses a token
   whose tool is no longer `confirm`. All three are code, and all three fail closed.
3. **A TIER 1 ACTION IS PERMISSION-CHECKED, TENANT-SCOPED, AUDITED AND IDEMPOTENT.** Staff
   are refused inside the tool; a neighbour's agent is a 404; the `audit_log` row is written
   in the same transaction as the change; and the same question asked twice creates one
   agent.
4. **THE COMPLIANCE GATE IS NOT BYPASSABLE BY THE ASSISTANT.** A campaign the launch gate
   refuses is refused here too, by name, before any card is drawn — and the sentence the
   model is handed says to relay it and not to try again.
5. **THE FOUNDER'S BUG IS FIXED AT THE ROOT.** A screen that declares no writable field
   cannot be filled: `validate_fill` refuses the whole call, which is the ONE mechanism for
   that (there is no second guard in the prompt or in the dock), and the model is told to
   reach for an action instead.

CONCURRENCY AND SHARED STATE: every test mints its own tenant. The one shared store an
action touches is `idempotency_records`, which is keyed on a per-tenant, per-user
`scope_key` and a conversation digest, so two runs cannot see each other's claims.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import prompt as prompt_module
from apps.api.copilot import service, write_tools
from apps.api.copilot.actions import ACTION_TIERS, ActionTool
from apps.api.copilot.schemas import CopilotAskIn
from apps.api.copilot.write_tools_test import (  # reuse, never re-implement
    _ask,
    _principal,
    _scripted,
    _turn,
    _user_of,
    azure_only,  # noqa: F401  (a fixture is used by name, not by reference)
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.workers import chat

#: THE REVIEWED EXCEPTION LIST, AND IT IS DELIBERATELY NOT A COPY OF THE REGISTRY.
#:
#: The registry is enumerated by the test below; this names the actions that are allowed to
#: run WITHOUT a person clicking, each with the reason. A new action is `confirm` as far as
#: this file is concerned unless somebody adds it here, so the failure mode of forgetting is
#: a red build rather than a campaign that dialled.
#:
#: The bar, from the founder's own instruction: reversible, reaches no caller, spends no
#: money. All three, not any of them.
_REVIEWED_IMMEDIATE: dict[str, str] = {
    "agent_create": (
        "a DRAFT agent answers nothing and calls nobody (`check_dispatch` refuses a "
        "non-live agent per contact and the engine holds nothing for it), costs nothing, "
        "and can be renamed or archived"
    ),
    "agent_rename": (
        "the name is internal — no caller ever hears it — and renaming it back restores "
        "the world exactly"
    ),
}


def test_every_registered_action_states_a_tier_and_only_reviewed_ones_skip_the_click() -> None:
    """THE TIER RULE, over the registry rather than over a list somebody typed.

    Two assertions and they close opposite gaps. The first is that a tier exists and is one
    of the two; the second is that the set of actions which run WITHOUT a click is exactly
    the set somebody reviewed — so adding `campaign_launch` with `tier="immediate"` fails
    here, and so does adding any new action that quietly picks the fast tier.
    """
    assert write_tools.WRITE_TOOLS, "the registry is empty, so this test proves nothing"
    for tool in write_tools.WRITE_TOOLS:
        assert tool.tier in ACTION_TIERS, tool.name
        assert tool.where, f"{tool.name} does not say where its result lives"
    immediate = {tool.name for tool in write_tools.WRITE_TOOLS if tool.tier == "immediate"}
    assert immediate == set(_REVIEWED_IMMEDIATE), (
        "an action runs without a person clicking and nobody wrote down why. Add it to "
        "`_REVIEWED_IMMEDIATE` with the reason, or give it `tier='confirm'`."
    )
    # And the derived half: `immediate_tool_names` is what the rest of the code reads, so it
    # must agree with the registry rather than being a second enumeration.
    assert write_tools.immediate_tool_names() == immediate


def test_the_two_caller_reaching_actions_are_behind_a_click() -> None:
    """The two the founder singled out, named explicitly.

    Redundant with the test above by construction — they are `confirm` because they are not
    in `_REVIEWED_IMMEDIATE` — and kept anyway, because a future edit that added them to
    that dict would satisfy the general rule and be exactly the incident. These two put an
    AI on a phone line and dial strangers; the assertion is worth stating twice.
    """
    assert write_tools.tier_of("agent_publish") == "confirm"
    assert write_tools.tier_of("campaign_launch") == "confirm"
    assert write_tools.tier_of("dnc_add") == "confirm"
    assert write_tools.tier_of("campaign_pause") == "confirm"


def test_an_action_tool_cannot_be_built_without_saying_which_tier_it_is_in() -> None:
    """The language refuses it, which is why `tier` has no default.

    A defaulted tier is how a Tier 2 action silently becomes Tier 1: the author writes the
    other seven fields, never thinks about the eighth, and the permissive value is inherited
    in silence. `dataclasses` makes the omission a `TypeError` at import, i.e. the build.
    """
    with pytest.raises(TypeError):
        ActionTool(  # type: ignore[call-arg]
            name="x",
            permission="org:manage",
            object_type="agent",
            audit_action="agent.created",
            where="nowhere",
            schema={},
            plan=None,  # type: ignore[arg-type]
            execute=None,  # type: ignore[arg-type]
        )


def test_tier_of_answers_none_for_a_name_that_is_not_an_action() -> None:
    """`service.py` splits the model's calls on this, so "not an action" has to be a real
    answer rather than a `KeyError` mid-stream."""
    assert write_tools.tier_of("set_fields") is None
    assert write_tools.tier_of("business_snapshot") is None


# --- the two tiers cannot leak into each other ------------------------------------------


async def test_plan_write_refuses_to_mint_a_token_for_a_tier_one_action() -> None:
    """Half one of the code-enforced separation, in the SAFE direction.

    `service.py` dispatches on the tier and can never route a Tier 1 tool here, which is
    exactly why the guard is asserted directly: it is the thing that stays true when the
    loop is rewritten. Nothing is minted and nothing is changed.
    """
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.plan_write(
            "agent_create",
            json.dumps({"name": "Reception", "direction": "inbound", "language_primary": "te-IN"}),
            actor=write_tools.actor_for(_principal(tenant_id, _user_of(token))),
        )
    assert "propose" in refused.value.reason
    assert await _agent_count(tenant_id, "Tier one probe") == 0


async def test_run_immediate_refuses_a_tier_two_action_so_nothing_dials_without_a_click() -> None:
    """Half two, and the direction where a mistake is an incident.

    A `confirm` action reaching `run_immediate` would be a campaign launched with nobody
    clicking. The refusal is in `run_immediate` itself rather than only in the loop, so it
    holds for any future caller.
    """
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _campaign_of(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.run_immediate(
            "campaign_launch",
            json.dumps({"campaign_id": str(campaign_id)}),
            principal=_principal(tenant_id, _user_of(token)),
            seed="s",
            ip=None,
        )
    assert "confirm" in refused.value.reason
    assert await _campaign_status(tenant_id, campaign_id) == "draft"


async def test_a_token_for_an_action_that_is_no_longer_tier_two_is_refused_at_confirm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tier is re-read from the registry at CONFIRM time, not carried in the token.

    A proposal minted while a tool needed a click must not still buy one after the tool has
    been re-tiered — this endpoint's whole job IS the click, so an action that no longer
    needs one has no business arriving through it. Re-tiering is simulated by replacing the
    registry entry, which is the only way this state can exist.
    """
    tenant_id, _slug, token = await _make_tenant()
    lead_id = await _lead_of(tenant_id)
    principal = _principal(tenant_id, _user_of(token))
    proposal = await write_tools.plan_write(
        "lead_set_status",
        json.dumps({"lead_id": str(lead_id), "status": "hot"}),
        actor=write_tools.actor_for(principal),
    )
    retiered = dataclasses.replace(write_tools.LEAD_SET_STATUS, tier="immediate")
    monkeypatch.setitem(write_tools._BY_NAME, "lead_set_status", retiered)

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await write_tools.confirm(session, proposal.token, principal=principal, ip=None)
    assert refused.value.code == "copilot_proposal_invalid"
    assert await _lead_status(tenant_id, lead_id) != "hot"


# --- the draft-create action, end to end -------------------------------------------------


async def _agent_count(tenant_id: UUID, name: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM agents WHERE name = :n"), {"n": name}
                )
            ).scalar()
            or 0
        )


async def _agent_row(tenant_id: UUID, name: str) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT id, status, direction, language_primary, ai_disclosure_line, "
                    "recording_notice_line FROM agents WHERE name = :n"
                ),
                {"n": name},
            )
        ).first()
    assert row is not None, f"no agent called {name}"
    return {
        "id": UUID(str(row[0])),
        "status": str(row[1]),
        "direction": str(row[2]),
        "language": str(row[3]),
        "ai_disclosure_line": str(row[4]),
        "recording_notice_line": str(row[5]),
    }


async def _lead_of(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).first()
    assert row is not None
    return UUID(str(row[0]))


async def _lead_status(tenant_id: UUID, lead_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(text("SELECT status FROM leads WHERE id = :i"), {"i": lead_id})
        ).first()
    assert row is not None
    return str(row[0])


async def _campaign_of(tenant_id: UUID) -> UUID:
    """A DRAFT campaign with no template, no number and no consent provenance — i.e. one the
    launch gate has plenty to refuse."""
    from apps.api.db.base import uuid7

    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        agent = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).first()
        assert agent is not None
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, "
                "classification, created_at, updated_at) VALUES (:id, :tid, :aid, "
                "'Winter checkup', 'draft', 'service', now(), now())"
            ),
            {"id": campaign_id, "tid": tenant_id, "aid": agent[0]},
        )
    return campaign_id


async def _campaign_status(tenant_id: UUID, campaign_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :i"), {"i": campaign_id}
            )
        ).first()
    assert row is not None
    return str(row[0])


async def _audit_actions(tenant_id: UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE tenant_id = :t ORDER BY at"),
                {"t": tenant_id},
            )
        ).all()
    return [str(row[0]) for row in rows]


def _create_args(name: str = "Raghava outbound") -> str:
    return json.dumps({"name": name, "direction": "outbound", "language_primary": "te-IN"})


async def test_creating_a_draft_agent_runs_at_once_and_the_agent_meets_the_compliance_floor(
    azure_only: None,  # noqa: F811  (the imported fixture, requested by name)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE FOUNDER'S OWN REQUEST, end to end through the loop.

    "create a new agent for handling outbound campaigns" now reaches a tool. The assertions
    that matter are not that a row exists — they are hard rule 5's: the agent is a DRAFT (it
    reaches no caller), and it has BOTH opening sentences on file and non-blank, because
    `lifecycle.create_agent` is the one function that writes them and the executor calls it
    rather than a copy of it. There is no argument to this tool that could produce an agent
    without an AI disclosure.
    """
    tenant_id, _slug, token = await _make_tenant()
    _scripted(
        monkeypatch,
        [
            _turn(
                content="Making that now.",
                calls=(chat.ToolCall(id="c1", name="agent_create", arguments=_create_args()),),
            ),
            _turn(content="Done — it's a draft under Agents."),
        ],
    )

    events = [
        event
        async for event in service.run_copilot(
            _ask(), principal=_principal(tenant_id, _user_of(token)), seed="conv-1"
        )
    ]

    actions = [event.action for event in events if event.action is not None]
    assert len(actions) == 1
    action = actions[0]
    assert action is not None
    assert action.tool == "agent_create"
    assert action.applied is True
    assert action.where == "under Agents in your dashboard"
    # THE RECEIPT SAYS WHETHER IT CAN BE TAKEN BACK, and for a draft the honest answer is
    # yes-and-here-is-how. The panel offers an Undo for a field fill and not for this, so
    # the sentence is the only thing telling somebody what they can do next.
    assert "draft reaches no caller" in action.reversal

    agent = await _agent_row(tenant_id, "Raghava outbound")
    assert agent["status"] == "draft"
    assert agent["direction"] == "outbound"
    assert agent["language"] == "te-IN"
    assert agent["ai_disclosure_line"].strip()
    assert agent["recording_notice_line"].strip()
    assert str(agent["id"]) == action.object_id
    # NO CLICK DOES NOT MEAN NO RECORD.
    assert "agent.created" in await _audit_actions(tenant_id)


async def test_the_loop_keeps_going_after_an_immediate_action_so_the_person_is_told(
    azure_only: None,  # noqa: F811  (the imported fixture, requested by name)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A Tier 1 action does NOT end the run, and the model is handed the server's own
    sentence plus where the result lives.

    This is the asymmetry the tier buys: a proposal ends the turn because there is something
    to decide, and an action does not because there is something to explain. A run that
    stopped at the write would leave a person with a receipt and no sentence.
    """
    tenant_id, _slug, token = await _make_tenant()
    sent = _scripted(
        monkeypatch,
        [
            _turn(
                calls=(
                    chat.ToolCall(
                        id="c1", name="agent_create", arguments=_create_args("Nightline")
                    ),
                ),
            ),
            _turn(content="Created Nightline as a draft — you'll find it under Agents."),
        ],
    )

    events = [
        event
        async for event in service.run_copilot(
            _ask(), principal=_principal(tenant_id, _user_of(token)), seed="conv-2"
        )
    ]

    assert "".join(event.text or "" for event in events).startswith("Created Nightline")
    # The SECOND turn was sent the outcome as a tool result, including the place.
    followup = sent[1]
    tool_messages = [m for m in followup if m.get("role") == "tool"]
    assert len(tool_messages) == 1
    content = str(tool_messages[0]["content"])
    assert content.startswith("DONE.")
    assert "under Agents in your dashboard" in content
    assert "Do not call this tool again" in content


async def test_asking_the_same_thing_twice_in_one_conversation_creates_one_agent(
    azure_only: None,  # noqa: F811  (the imported fixture, requested by name)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE IDEMPOTENCY GUARD, driven the way it actually fires: the same conversation, the
    same tool, the same canonical arguments.

    A dropped stream that the person re-asks is the case this exists for — "request
    succeeded, response lost" is the failure that turns a retry into a duplicate. The key is
    derived from content that does not change on retry (`conversation_seed`), so the second
    run finds the claim, returns the FIRST run's own sentence, and writes nothing.

    `applied is False` on the replay is the honest answer: this call changed nothing.
    """
    tenant_id, _slug, token = await _make_tenant()
    principal = _principal(tenant_id, _user_of(token))
    for _attempt in range(2):
        _scripted(
            monkeypatch,
            [
                _turn(
                    calls=(chat.ToolCall(id="c1", name="agent_create", arguments=_create_args()),)
                ),
                _turn(content="Done."),
            ],
        )
        events = [
            event
            async for event in service.run_copilot(_ask(), principal=principal, seed="same-conv")
        ]
        actions = [event.action for event in events if event.action is not None]
        assert len(actions) == 1

    assert await _agent_count(tenant_id, "Raghava outbound") == 1
    assert actions[0] is not None
    assert actions[0].applied is False


async def test_a_second_agent_of_the_same_name_is_refused_back_to_the_model(
    azure_only: None,  # noqa: F811  (the imported fixture, requested by name)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HUMAN duplicate, which is a different failure from the mechanical one and has a
    different fix.

    A person who asks twice an hour apart is making two decisions and the idempotency key
    correctly lets both through. What stops a second "Reception" is the planner's own read,
    and the refusal goes to the MODEL so it can ask for another name rather than to the
    person as a dead end — and rather than the tool picking "Reception 2" on their behalf,
    which is the class of helpfulness that produced the founder's twenty-one filled fields.
    """
    tenant_id, _slug, token = await _make_tenant()
    principal = _principal(tenant_id, _user_of(token))
    _scripted(
        monkeypatch,
        [
            _turn(calls=(chat.ToolCall(id="c1", name="agent_create", arguments=_create_args()),)),
            _turn(content="Done."),
        ],
    )
    async for _event in service.run_copilot(_ask(), principal=principal, seed="first"):
        pass

    sent = _scripted(
        monkeypatch,
        [
            _turn(calls=(chat.ToolCall(id="c2", name="agent_create", arguments=_create_args()),)),
            _turn(content="What should I call this one?"),
        ],
    )
    events = [
        event async for event in service.run_copilot(_ask(), principal=principal, seed="second")
    ]

    assert [event.action for event in events if event.action is not None] == []
    assert await _agent_count(tenant_id, "Raghava outbound") == 1
    refusal = str(next(m for m in sent[1] if m.get("role") == "tool")["content"])
    assert "already has an agent with that name" in refusal
    assert refusal.startswith("NOTHING was changed.")


async def test_staff_cannot_create_an_agent_and_are_refused_inside_the_tool() -> None:
    """The permission is the one `POST /v1/agents` declares (`org:manage`), checked where
    `run_read_tool` checks its own — INSIDE the tool, not by dropping it from the schema.

    The tool array must stay byte-identical per realm for the prompt cache, so gating by
    varying the list is the one implementation that is not available. A staff member sees
    the tool, calls it, and is told no.
    """
    tenant_id, _slug, token = await _make_tenant(role="staff")
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await write_tools.run_immediate(
            "agent_create",
            _create_args(),
            principal=_principal(tenant_id, _user_of(token), role="staff"),
            seed="s",
            ip=None,
        )
    assert "role may not" in refused.value.reason
    assert await _agent_count(tenant_id, "Raghava outbound") == 0


async def test_an_action_with_no_signed_in_account_changes_nothing() -> None:
    """`run_copilot` is reachable from callers holding no principal, and the tools refuse
    rather than the loop branching on it — the same shape `plan_write` already had, so the
    tool array cannot become a function of who is asking."""
    with pytest.raises(write_tools.WriteRefusedError):
        await write_tools.run_immediate(
            "agent_create", _create_args(), principal=None, seed="s", ip=None
        )


async def test_renaming_a_neighbours_agent_is_a_404_and_touches_nothing() -> None:
    """Hard rule 1. `assert_visible` answers for a row this tenant cannot see exactly as it
    answers for one that does not exist, and RLS is still behind it."""
    tenant_a, _slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    async with tenant_session(tenant_b) as session:
        row = (await session.execute(text("SELECT id, name FROM agents LIMIT 1"))).first()
    assert row is not None
    stranger_id, stranger_name = UUID(str(row[0])), str(row[1])

    with pytest.raises(ProblemError) as refused:
        await write_tools.run_immediate(
            "agent_rename",
            json.dumps({"agent_id": str(stranger_id), "name": "Taken over"}),
            principal=_principal(tenant_a, _user_of(token_a)),
            seed="s",
            ip=None,
        )
    assert refused.value.kind == "not_found"
    async with tenant_session(tenant_b) as session:
        after = (
            await session.execute(text("SELECT name FROM agents WHERE id = :i"), {"i": stranger_id})
        ).scalar()
    assert str(after) == stranger_name


# --- the compliance gate ------------------------------------------------------------------


async def test_a_campaign_the_gate_refuses_is_never_offered_and_the_reasons_go_to_the_model(
    azure_only: None,  # noqa: F811  (the imported fixture, requested by name)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HARD RULE 5, on the path the assistant takes.

    `_plan_campaign_launch` asks `launch_blockers` — the SAME function `GET /launch-check`
    calls and the same one `launch_campaign` runs again with the row locked — and refuses
    with the rule names when it has anything to say. So no Confirm button is ever drawn for
    a launch the platform would refuse, which matters because a card listing the reasons
    beside a live button is an invitation to click through a compliance gate.

    The refusal reaches the MODEL, with instructions to relay it and not to try again. That
    is the founder's rule, and this is where it is enforced.
    """
    tenant_id, _slug, token = await _make_tenant()
    campaign_id = await _campaign_of(tenant_id)
    sent = _scripted(
        monkeypatch,
        [
            _turn(
                calls=(
                    chat.ToolCall(
                        id="c1",
                        name="campaign_launch",
                        arguments=json.dumps({"campaign_id": str(campaign_id)}),
                    ),
                )
            ),
            _turn(content="It can't go out yet — here's what is missing."),
        ],
    )

    events = [
        event
        async for event in service.run_copilot(
            _ask(), principal=_principal(tenant_id, _user_of(token)), seed="c"
        )
    ]

    assert [event.proposal for event in events if event.proposal is not None] == []
    assert await _campaign_status(tenant_id, campaign_id) == "draft"
    refusal = str(next(m for m in sent[1] if m.get("role") == "tool")["content"])
    assert "cannot launch yet" in refusal
    assert "do not try to launch it again" in refusal
    # The step frame carries the same refusal, so a person watching sees it too.
    steps = [event.step for event in events if event.step is not None]
    assert [step.status for step in steps if step is not None] == ["running", "refused"]


async def test_publishing_an_agent_is_proposed_and_the_card_states_cost_and_reversal(
    azure_only: None,  # noqa: F811  (the imported fixture, requested by name)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tier 2, and the card is the point.

    An "Approve / Deny" button with a verb on it gets a worse decision than one stating what
    changes, what it costs and whether it can be taken back. `cost` is a sentence rather
    than a rupee figure on purpose (hard rule 7 keeps money in NUMERIC columns and the rate
    is a property of the plan), and `reversal` is honest in the negative direction: calls
    already taken cannot be undone.

    NOTHING IS PUBLISHED. The agent is still a draft afterwards, which is the property that
    makes a proposal a proposal.
    """
    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id, status FROM agents LIMIT 1"))).first()
    assert row is not None
    agent_id, before = UUID(str(row[0])), str(row[1])

    _scripted(
        monkeypatch,
        [
            _turn(
                calls=(
                    chat.ToolCall(
                        id="c1",
                        name="agent_publish",
                        arguments=json.dumps({"agent_id": str(agent_id)}),
                    ),
                )
            )
        ],
    )
    events = [
        event
        async for event in service.run_copilot(
            _ask(), principal=_principal(tenant_id, _user_of(token)), seed="p"
        )
    ]

    proposals = [event.proposal for event in events if event.proposal is not None]
    assert len(proposals) == 1
    proposal = proposals[0]
    assert proposal is not None
    assert proposal.cost is not None and "billed per minute" in proposal.cost
    assert "cannot be undone" in proposal.reversal
    assert proposal.proposed == "live"
    async with tenant_session(tenant_id) as session:
        after = (
            await session.execute(text("SELECT status FROM agents WHERE id = :i"), {"i": agent_id})
        ).scalar()
    assert str(after) == before


# --- live tool-execution visibility --------------------------------------------------------


async def test_every_tool_call_emits_a_running_frame_and_a_terminal_one_with_its_own_timing(
    azure_only: None,  # noqa: F811  (the imported fixture, requested by name)
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The step contract: two frames per call, sharing an id, the second carrying
    `elapsed_ms`.

    The elapsed time is PER CALL and not per batch, which is the whole reason
    `_run_read_tools` times inside the `gather` rather than around it: these run
    concurrently, and a batch boundary would report every call as taking as long as the
    slowest — precisely the number somebody watching is trying to find out.
    """
    tenant_id, _slug, token = await _make_tenant()
    _scripted(
        monkeypatch,
        [
            _turn(
                calls=(
                    chat.ToolCall(id="r1", name="agents_list", arguments="{}"),
                    chat.ToolCall(id="r2", name="leads_search", arguments="{}"),
                )
            ),
            _turn(content="Here's what I found."),
        ],
    )

    events = [
        event
        async for event in service.run_copilot(
            _ask(),
            principal=_principal(tenant_id, _user_of(token)),
            tool_context=service.ToolContext(tenant_id=tenant_id, role="owner"),
            seed="s",
        )
    ]
    steps = [event.step for event in events if event.step is not None]
    assert [step.id for step in steps] == ["r1", "r2", "r1", "r2"]
    assert [step.status for step in steps] == ["running", "running", "done", "done"]
    assert all(step.elapsed_ms is None for step in steps[:2])
    assert all(isinstance(step.elapsed_ms, int) for step in steps[2:])
    assert all(step.detail for step in steps[2:])


def test_a_step_preview_is_bounded_and_carries_no_invisible_characters() -> None:
    """A step frame reaches the DOM, so it goes through the same egress strip every other
    text on this channel does — and it is truncated, because a tool result is prose written
    for a model and can run to thousands of characters."""
    long = "x" * (service.MAX_STEP_CHARS * 3)
    assert len(service._preview(long)) == service.MAX_STEP_CHARS
    assert service._preview("a\u200bb") == "ab"
    assert service._preview("a\n  b") == "a b"


# --- the founder's bug: a fill that was never asked for --------------------------------------


def test_a_screen_with_no_writable_fields_cannot_be_filled_at_all() -> None:
    """THE ROOT-CAUSE PROPERTY, and it is ONE mechanism rather than two.

    A screen that declares nothing — the fallback surface a page with no declaration gets —
    is the sharpest version of the founder's bug: any fill there is guaranteed to be wrong.
    Nothing new guards it, and nothing should: `validate_fill` already refuses an item whose
    `field_id` is not on THIS request, and the fill is all-or-nothing, so a screen with no
    fields refuses every fill by construction. A second guard in the prompt or in the dock
    would be a second answer to one question.

    What changed at D-500 is where the model goes instead — the prompt now tells it to reach
    for an action tool or to say it cannot do that here (see the test below).
    """
    payload = CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/x/somewhere", "title": "A screen", "realm": "client"},
            "question": "create an outbound agent",
            "fields": [],
        }
    )
    with pytest.raises(service.FillRefusedError) as refused:
        service.validate_fill(
            payload, json.dumps({"items": [{"field_id": "variable_1_name", "value": "x"}]})
        )
    assert refused.value.reasons == ("`variable_1_name` is not a field on this screen",)


def test_a_fill_is_all_or_nothing_so_one_unasked_field_discards_the_whole_batch() -> None:
    """The founder's screenshot in one assertion: twenty-one items, one of them not on the
    screen, and NOTHING is written.

    All-or-nothing was already the rule and is what makes the failure recoverable — the
    person gets a form in the state they left it, and the model gets a sentence naming the
    field it invented.
    """
    payload = CopilotAskIn.model_validate(
        {
            "screen": {"route": "/c/x/agents", "title": "Agents", "realm": "client"},
            "question": "create a new agent for handling outbound campaigns",
            "fields": [{"id": "note", "label": "Note", "type": "text", "writable": True}],
        }
    )
    items = [{"field_id": "note", "value": "ok"}, {"field_id": "agent_name", "value": "Raghava"}]
    with pytest.raises(service.FillRefusedError) as refused:
        service.validate_fill(payload, json.dumps({"items": items}))
    assert refused.value.reasons == ("`agent_name` is not a field on this screen",)


def test_the_prompt_separates_filling_this_form_from_doing_something() -> None:
    """The other half of the root-cause fix, and the half a test can only assert as text.

    The model filled twenty-one extraction variables because it had no tool for what it was
    asked and was told to be proactive and never hand the question back. Both halves are now
    scoped: `set_fields` is described as the form in front of the person, actions are
    described as how you DO things and as working from any screen, and "say you cannot do
    that here" is an explicit exit that did not exist.
    """
    system = prompt_module.SYSTEM_PROMPT
    assert "NEVER FILL A FIELD THE PERSON DID NOT ASK ABOUT" in system
    assert "Actions work from\nANY screen." in system or "Actions work from " in system
    assert "If this screen has no fields at all, then there is nothing to fill" in system
    tool = prompt_module.set_fields_tool()
    description = tool["function"]["description"]
    assert "NOT how you create, rename, publish" in description
    assert "say you cannot do that here" in description
