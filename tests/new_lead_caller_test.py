"""Who calls a new lead: the "Call new leads" Follow-up names the agent, and nothing else
sets it (`ingest.service.new_lead_caller`, `follow_ups.service.make_new_lead_caller`)."""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.agents.lifecycle import create_agent
from apps.api.db.session import tenant_session
from apps.api.follow_ups import definition as d
from apps.api.follow_ups import runner
from apps.api.follow_ups import service as follow_ups
from apps.api.ingest import service
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Caller Estates",
        slug=f"nlc-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :ref WHERE id = :aid"
            ),
            {"ref": f"fakeagent_{uuid.uuid4().hex[:8]}", "aid": agent_id},
        )


async def _agent(tenant_id: uuid.UUID, name: str, **kwargs: Any) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await create_agent(
            session,
            tenant_id=tenant_id,
            name=name,
            direction="outbound",
            language_primary="te-IN",
            **kwargs,
        )


async def _source(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        webhook_id, _secret = await service.create_lead_source(
            session, tenant_id=tenant_id, source="website_form", mapping={}, supplied_secret=None
        )
    return webhook_id


async def _caller(tenant_id: uuid.UUID, source_id: uuid.UUID) -> service.SourceCaller:
    async with tenant_session(tenant_id) as session:
        sources = await service.list_lead_sources(session)
        return (await service.source_callers(session, sources))[source_id]


async def _first_call_agent(tenant_id: uuid.UUID) -> tuple[uuid.UUID | None, str]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT id, status FROM follow_ups WHERE starter = 'call_new_leads'")
            )
        ).one()
        found = await follow_ups.get(session, uuid.UUID(str(row[0])))
    first = d.first_step(found.steps)
    assert isinstance(first, d.CallStep)
    return first.agent_id, str(row[1])


async def test_the_follow_up_agent_wins_then_the_source_then_the_account() -> None:
    tenant_id, receptionist = await _tenant()
    source_id = await _source(tenant_id)

    # Nobody can call yet: a new source has no agent and no agent is published.
    nobody = await _caller(tenant_id, source_id)
    assert nobody.caller.agent_id is None
    assert nobody.called is True
    assert nobody.follow_up_name == "Call new leads"

    # The step says "the lead's own agent": the account's oldest calling agent calls.
    await _publish(tenant_id, receptionist)
    later = await _agent(tenant_id, "Later caller")
    await _publish(tenant_id, later)
    account = await _caller(tenant_id, source_id)
    assert (account.caller.agent_id, account.caller.chosen_by) == (receptionist, "account")

    # A source set up with an agent before the choice moved to the Follow-up keeps it.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_webhooks SET agent_id = :aid WHERE id = :id"),
            {"aid": later, "id": source_id},
        )
    legacy = await _caller(tenant_id, source_id)
    assert (legacy.caller.agent_id, legacy.caller.chosen_by) == (later, "source")
    assert legacy.agent_name == "Later caller"

    # An agent made for "Call new leads instantly" is named in the Follow-up at once, and is
    # passed over until it is published.
    instant = await _agent(tenant_id, "Instant caller", starter="call_new_leads")
    assert (await _first_call_agent(tenant_id))[0] == instant
    assert (await _caller(tenant_id, source_id)).caller.agent_id == later
    await _publish(tenant_id, instant)
    chosen = await _caller(tenant_id, source_id)
    assert (chosen.caller.agent_id, chosen.caller.chosen_by) == (instant, "follow_up")


async def test_naming_the_caller_keeps_a_turned_off_follow_up_off() -> None:
    tenant_id, receptionist = await _tenant()
    source_id = await _source(tenant_id)
    async with tenant_session(tenant_id) as session:
        follow_up_id = uuid.UUID(
            str(
                (
                    await session.execute(
                        text("SELECT id FROM follow_ups WHERE starter = 'call_new_leads'")
                    )
                ).scalar_one()
            )
        )
        before = (await follow_ups.get(session, follow_up_id)).live_number
        await follow_ups.turn_off(session, follow_up_id)
        await follow_ups.make_new_lead_caller(
            session, tenant_id=tenant_id, agent_id=receptionist, user_id=None
        )
        after = await follow_ups.get(session, follow_up_id)
    assert after.live_number == (before or 0) + 1
    assert after.has_unpublished_changes is False
    assert await _first_call_agent(tenant_id) == (receptionist, "off")

    off = await _caller(tenant_id, source_id)
    assert off.called is False
    assert off.follow_up_id == follow_up_id


async def test_a_lead_from_a_source_with_no_agent_is_refused_only_when_nobody_can_call() -> None:
    tenant_id, receptionist = await _tenant()
    async with tenant_session(tenant_id) as session:
        follow_up = await runner.new_lead_follow_up(session, source_id=None)
        step = service.first_call_step(follow_up)
        assert step is not None
        named = await service.new_lead_caller(
            session,
            step_agent_id=receptionist,
            source_agent_id=None,
            account_agent_id=None,
        )
        unnamed = await service.new_lead_caller(
            session, step_agent_id=None, source_agent_id=None, account_agent_id=None
        )
    # A named draft is `agent_not_published`; nobody named at all is `ingest_no_agent`.
    assert (named.agent_id, named.named) == (None, True)
    assert (unnamed.agent_id, unnamed.named) == (None, False)
