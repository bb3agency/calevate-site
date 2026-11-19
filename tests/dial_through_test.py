"""Direct calls ring through an assignment (D-1019): the resolver, the dial and the gate.

1. `dial_through` picks, in order, the producing campaign's engine agent, the origin call's
   live line, a live line in the agent's voice, the agent's own engine agent, and refuses
   `no_assignment_to_call_through` when there is none.
2. A dial through a line rings the line's engine agent, stamps `calls.inbound_line_id`, rings
   from a number the line answers unlent, and lends any other number to the line's holder.
3. The gate asks the dialled holder: a line's truthful-answer verdict is its own, an agent
   that only answers may call back through its line, and no holder is refused.
4. Another account's line is never resolved.
5. D2: a line's engine agent is composed to place calls; the agent's own prompt is not.

SHARED DATABASE DISCIPLINE: every organisation is minted here; the engine is the fake.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents.dial_through import dial_through, resolve_dial_holder
from apps.api.agents.reconciliation import TRUTHFUL_ANSWER_MISSING
from apps.api.agents.service import CampaignDial, LineDial
from apps.api.campaigns import engine_agent, engine_numbers
from apps.api.compliance.service import (
    NO_ASSIGNMENT_RULE,
    TRUTHFUL_ANSWER_DRIFT_RULE,
    check_dispatch,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.inbound.publish import put_line_live
from calevate_shared.engine import (
    PHONE_LINE,
    PLACED_CALL_PERMISSION_RULE,
    compose_engine_prompt,
)
from sqlalchemy import text
from tests.agent_lifecycle_test import _fresh_engine, _number
from tests.campaign_engine_agents_test import _campaign, _live_agent
from tests.inbound_lines_test import _attach, _line

pytestmark = pytest.mark.rls


def _phone() -> str:
    return f"+9198765{uuid.uuid4().int % 10**5:05d}"


async def _live_line(tenant_id: UUID, agent_id: UUID) -> tuple[UUID, str]:
    line_id = await _line(tenant_id, agent_id)
    return line_id, await put_line_live(tenant_id=tenant_id, line_id=line_id)


async def _forget_own_ref(tenant_id: UUID, agent_id: UUID) -> None:
    """The agent as D-1019 leaves it: an employee holding no engine agent of its own."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    campaign_id: UUID | None = None,
    line_id: UUID | None = None,
) -> UUID:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "campaign_id, inbound_line_id, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'inbound', 'completed', :c, :l, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"origin-{call_id}",
                "c": campaign_id,
                "l": line_id,
            },
        )
    return call_id


async def _through(tenant_id: UUID, agent_id: UUID, **kwargs: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return await dial_through(session, agent_id=agent_id, **kwargs)


# --- 1. the resolver ---------------------------------------------------------------------


async def test_a_campaign_that_produced_the_call_is_rung_first() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _live_line(tenant_id, agent_id)
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    ref = await engine_agent.put_campaign_live(tenant_id=tenant_id, campaign_id=campaign_id)
    origin = await _call(tenant_id, agent_id, campaign_id=campaign_id)

    found = await _through(tenant_id, agent_id, origin_call_id=origin)

    assert found.holder == CampaignDial(ref=str(ref), campaign_id=campaign_id)
    assert found.campaign_id == campaign_id and found.line is None


async def test_a_call_through_a_campaign_carries_the_number_the_campaign_calls_from() -> None:
    """A call-back or a person's call through a campaign presents the campaign's caller id."""
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    number_id = await _number(tenant_id, agent_id, ref=f"num_{uuid.uuid4().hex[:10]}")
    campaign_id = await _campaign(tenant_id, agent_id, status="running")
    await engine_agent.put_campaign_live(tenant_id=tenant_id, campaign_id=campaign_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET number_id = :n WHERE id = :c"),
            {"n": number_id, "c": campaign_id},
        )

    found = await _through(tenant_id, agent_id, campaign_id=campaign_id)

    assert found.campaign is not None and found.campaign.number_id == number_id
    assert found.number_id == number_id


async def test_a_campaign_that_holds_no_engine_agent_is_passed_over() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    campaign_id = await _campaign(tenant_id, agent_id, status="completed")

    found = await _through(tenant_id, agent_id, campaign_id=campaign_id)

    assert found.holder is None and found.own, "a finished campaign was dialled through"


async def test_the_line_the_call_came_in_on_beats_another_live_line() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _live_line(tenant_id, agent_id)
    second, second_ref = await _live_line(tenant_id, agent_id)
    origin = await _call(tenant_id, agent_id, line_id=second)

    found = await _through(tenant_id, agent_id, origin_call_id=origin)

    assert isinstance(found.holder, LineDial)
    assert (found.holder.line_id, found.holder.ref) == (second, second_ref)


async def test_a_lead_follows_its_latest_line_call() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _live_line(tenant_id, agent_id)
    second, _ref = await _live_line(tenant_id, agent_id)
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, "
                "created_at, updated_at) VALUES (:id, :t, :a, :p, 'manual', 'new', now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id, "p": _phone()},
        )
    origin = await _call(tenant_id, agent_id, line_id=second)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET lead_id = :l WHERE id = :c"), {"l": lead_id, "c": origin}
        )

    found = await _through(tenant_id, agent_id, lead_id=lead_id)

    assert found.line is not None and found.line.line_id == second


async def test_with_no_origin_a_live_line_in_the_agents_voice_is_rung() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id, line_ref = await _live_line(tenant_id, agent_id)
    draft = await _line(tenant_id, agent_id)
    await _forget_own_ref(tenant_id, agent_id)

    found = await _through(tenant_id, agent_id)

    assert found.line is not None
    assert (found.line.line_id, found.line.ref) == (line_id, line_ref)
    assert found.line.line_id != draft


async def test_with_no_holder_the_agents_own_engine_agent_is_rung() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()

    found = await _through(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        held = await resolve_dial_holder(session, agent_id=agent_id)

    assert found.own and found.holder is None and not found.unassigned
    assert held is None


async def test_with_nothing_to_ring_through_the_call_is_refused_naming_the_fix() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _line(tenant_id, agent_id)  # a draft line holds nothing to ring through
    await _forget_own_ref(tenant_id, agent_id)

    found = await _through(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await resolve_dial_holder(session, agent_id=agent_id)

    assert found.unassigned
    assert refused.value.code == NO_ASSIGNMENT_RULE
    assert "campaign" in (refused.value.remediation or "")
    assert "inbound line live" in (refused.value.remediation or "")


# --- 2. the dial -------------------------------------------------------------------------


async def test_a_dial_through_a_line_rings_its_engine_agent_and_carries_the_line() -> None:
    engine = _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    line_id, line_ref = await _live_line(tenant_id, agent_id)
    await _forget_own_ref(tenant_id, agent_id)
    through = await _through(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        handle = await agents_service.dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164=_phone(),
            line=through.line,
        )
        row = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref, inbound_line_id FROM calls WHERE engine_call_id = :h"
                ),
                {"h": handle},
            )
        ).one()

    assert engine._calls[handle]["agent_ref"] == line_ref
    assert (row.engine_agent_ref, row.inbound_line_id) == (line_ref, line_id)


async def test_a_line_dial_takes_part_in_no_agent_experiment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _live_line(tenant_id, agent_id)
    through = await _through(tenant_id, agent_id)

    async def _assign(*_a: Any, **_k: Any) -> Any:
        raise AssertionError("a call through a line was assigned an agent experiment arm")

    monkeypatch.setattr(agents_service.assignment, "assign", _assign)
    async with tenant_session(tenant_id) as session:
        assert await agents_service.dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164=_phone(),
            line=through.line,
        )


async def _on_carrier(tenant_id: UUID, number_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE phone_numbers SET provider = 'thinnest', direction = 'both' WHERE id = :n"
            ),
            {"n": number_id},
        )


@pytest.mark.parametrize("on_the_line", [True, False])
async def test_a_line_dial_lends_only_a_number_the_line_does_not_answer(
    monkeypatch: pytest.MonkeyPatch, on_the_line: bool
) -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    number_id = await _number(tenant_id, agent_id, ref=f"num_{uuid.uuid4().hex[:10]}")
    await _on_carrier(tenant_id, number_id)
    line_id = await _line(tenant_id, agent_id)
    if on_the_line:
        await _attach(tenant_id, line_id, number_id)
    line_ref = await put_line_live(tenant_id=tenant_id, line_id=line_id)
    await _forget_own_ref(tenant_id, agent_id)
    lent: list[tuple[str, str]] = []

    async def _lend(number_ref: str, agent_ref: str) -> bool:
        lent.append((number_ref, agent_ref))
        return True

    monkeypatch.setattr(agents_service, "outbound_number_provider", lambda: "thinnest")
    monkeypatch.setattr(engine_numbers, "lend_client_number", _lend)
    through = await _through(tenant_id, agent_id)
    assert through.line is not None
    assert (number_id in through.line.routed_number_ids) is on_the_line

    async with tenant_session(tenant_id) as session:
        await agents_service.dispatch_call(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            lead_id=None,
            phone_e164=_phone(),
            line=through.line,
        )

    if on_the_line:
        assert lent == [], "a number the line answers was lent to it"
    else:
        assert [ref for _n, ref in lent] == [line_ref], "the number was not lent to the line"


async def test_a_dial_rings_through_one_holder_only() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _live_line(tenant_id, agent_id)
    through = await _through(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ValueError):
            await agents_service.dispatch_call(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                lead_id=None,
                phone_e164=_phone(),
                line=through.line,
                campaign=CampaignDial(ref="ag_x", campaign_id=uuid7()),
            )


# --- 3. the gate -------------------------------------------------------------------------


async def _gate(tenant_id: UUID, agent_id: UUID, **kwargs: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=_phone(), **kwargs
        )


async def test_the_truthful_answer_verdict_is_the_dialled_lines_own() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    broken, broken_ref = await _live_line(tenant_id, agent_id)
    sound, _sound_ref = await _live_line(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET drift_state = :s, drift_checked_at = now() "
                "WHERE engine_agent_ref = :r"
            ),
            {"s": TRUTHFUL_ANSWER_MISSING, "r": broken_ref},
        )
    via_broken = await _through(
        tenant_id, agent_id, origin_call_id=await _call(tenant_id, agent_id, line_id=broken)
    )
    via_sound = await _through(
        tenant_id, agent_id, origin_call_id=await _call(tenant_id, agent_id, line_id=sound)
    )
    assert via_broken.line.line_id == broken and via_sound.line.line_id == sound

    refused = await _gate(tenant_id, agent_id, line=via_broken.line)
    other = await _gate(tenant_id, agent_id, line=via_sound.line)

    assert refused.rule == TRUTHFUL_ANSWER_DRIFT_RULE
    assert other.rule != TRUTHFUL_ANSWER_DRIFT_RULE, "one line's verdict stopped another line"


async def test_an_agent_that_only_answers_may_call_back_through_its_line() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
    await _live_line(tenant_id, agent_id)
    through = await _through(tenant_id, agent_id)

    alone = await _gate(tenant_id, agent_id)
    via_line = await _gate(tenant_id, agent_id, line=through.line)

    assert alone.rule == "agent_inbound_only"
    assert via_line.rule != "agent_inbound_only"


async def test_a_call_with_nothing_to_ring_through_is_refused_by_the_gate() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _forget_own_ref(tenant_id, agent_id)
    through = await _through(tenant_id, agent_id)

    decision = await _gate(tenant_id, agent_id, unassigned=through.unassigned)

    assert not decision.allowed and decision.rule == NO_ASSIGNMENT_RULE
    assert "inbound line live" in (decision.reason or "")


async def test_a_test_call_through_the_test_copy_is_not_refused_as_not_ready() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    await _forget_own_ref(tenant_id, agent_id)

    own = await _gate(tenant_id, agent_id, trial_call=True)
    copy = await _gate(tenant_id, agent_id, trial_call=True, through_test_copy=True)

    assert own.rule == "agent_not_ready"
    assert copy.rule != "agent_not_ready"


# --- 4. tenancy --------------------------------------------------------------------------


async def test_another_accounts_line_is_never_resolved() -> None:
    _fresh_engine()
    tenant_a, agent_a = await _live_agent()
    line_a, _ref = await _live_line(tenant_a, agent_a)
    origin_a = await _call(tenant_a, agent_a, line_id=line_a)
    tenant_b, agent_b = await _live_agent()
    await _forget_own_ref(tenant_b, agent_b)

    through_b = await _through(tenant_b, agent_b, origin_call_id=origin_a)
    foreign = await _through(tenant_b, agent_a, origin_call_id=origin_a)

    assert through_b.unassigned, "tenant B's call resolved tenant A's line"
    assert foreign.unassigned and foreign.holder is None


# --- 5. D2: a line's engine agent places calls ---------------------------------------------


async def test_a_lines_engine_agent_is_composed_to_place_calls_and_the_agent_is_not() -> None:
    _fresh_engine()
    tenant_id, agent_id = await _live_agent()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
    line_id = await _line(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        line_cfg = await agents_service.line_config(session, tenant_id=tenant_id, line_id=line_id)
        agent = await agents_service._load_agent(session, tenant_id, agent_id)
    own_cfg = agents_service._to_config(tenant_id, agent, engine=_fresh_engine())

    line_prompt = compose_engine_prompt(line_cfg)
    own_prompt = compose_engine_prompt(own_cfg)

    assert line_cfg.direction == "inbound" and line_cfg.places_call_backs
    assert PHONE_LINE in line_prompt and PLACED_CALL_PERMISSION_RULE in line_prompt
    assert "AI assistant on phone calls for" in line_prompt
    assert PHONE_LINE not in own_prompt and PLACED_CALL_PERMISSION_RULE not in own_prompt
    # The notices the line says are the agent's: placing calls moves none of them.
    assert line_cfg.opening_line == own_cfg.opening_line
