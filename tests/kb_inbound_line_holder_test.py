"""An inbound line's engine agent carries the client's knowledge like every other engine agent
of the client (D-689, D-997).

A line answers its numbers with its own engine agent (`agents/service.publish_line`), so a
published source must reach it as its own copy, claimed in `engine_kb_routes` with the line as
holder, and attached with the LINE's config: an attach replaces the whole agent on the
platform (D-488), so the agent's config would overwrite the line's script.

Driven through the real paths on the shared fake engine.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import service as agent_service
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.inbound import lines
from apps.api.kb import service as kb_service
from calevate_shared.call_script import CallScript
from calevate_shared.engine import AgentConfig, KBSourceRef
from sqlalchemy import text
from tests.kb_workflow_test import _tenant_with_published_agent

FEES = "A consultation costs 500 rupees and is payable at reception."
HOURS = "We are open from nine in the morning to eight at night."
LINE_SCRIPT = CallScript(
    schema_version=2,
    business_line="The clinic answers calls about appointments.",
    opening_line="Hello, you have reached the clinic's appointments line.",
)


async def _publish(tenant_id: uuid.UUID, name: str, body: str) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        submitted = await kb_service.submit_source(
            session, tenant_id=tenant_id, name=name, body=body, auto_approve=True
        )
    source_id = uuid.UUID(str(submitted["id"]))
    async with tenant_session(tenant_id) as session:
        await kb_service.publish_source(session, tenant_id=tenant_id, source_id=source_id)
    return source_id


async def _published_line(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[uuid.UUID, str]:
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Appointments",
            script=LINE_SCRIPT,
            created_by=None,
        )
    async with tenant_session(tenant_id) as session:
        ref = await agent_service.publish_line(session, tenant_id=tenant_id, line_id=line_id)
    return line_id, ref


async def _line_claims(tenant_id: uuid.UUID, line_id: uuid.UUID) -> dict[uuid.UUID, str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT source_id, engine_kb_ref FROM engine_kb_routes "
                    "WHERE inbound_line_id = :l"
                ),
                {"l": line_id},
            )
        ).all()
    return {uuid.UUID(str(row[0])): str(row[1]) for row in rows}


async def _own_claims(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> dict[uuid.UUID, str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT source_id, engine_kb_ref FROM engine_kb_routes WHERE agent_id = :a "
                    "AND variant_id IS NULL AND NOT test_copy AND inbound_line_id IS NULL"
                ),
                {"a": agent_id},
            )
        ).all()
    return {uuid.UUID(str(row[0])): str(row[1]) for row in rows}


def _fake() -> FakeEngine:
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    return engine


async def test_a_published_line_is_a_vendor_target_and_catches_up_on_live_knowledge() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    engine = _fake()
    source_id = await _publish(tenant_id, "Fees", FEES)

    line_id, line_ref = await _published_line(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        targets = await kb_service.vendor_targets(session, tenant_id=tenant_id)
    assert (
        kb_service.KbTarget(agent_id=agent_id, engine_ref=line_ref, inbound_line_id=line_id)
        in targets
    )
    claims = await _line_claims(tenant_id, line_id)
    assert set(claims) == {source_id}
    assert claims[source_id] in await engine.list_kb(line_ref)
    # The agent's own claim on the same source is a separate holder in the unique key.
    assert set(await _own_claims(tenant_id, agent_id)) == {source_id}
    async with tenant_session(tenant_id) as session:
        recorded = await kb_service.recorded_handles_of_agent(
            session, agent_id, inbound_line_id=line_id
        )
    assert claims[source_id] in recorded


async def test_a_source_published_after_the_line_fans_out_with_the_lines_config(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    engine = _fake()
    line_id, line_ref = await _published_line(tenant_id, agent_id)
    sent: dict[str, AgentConfig | None] = {}
    attach = engine.attach_kb

    async def spy(ref: str, source: KBSourceRef, *, agent: AgentConfig | None = None) -> Any:
        sent[ref] = agent
        return await attach(ref, source, agent=agent)

    monkeypatch.setattr(engine, "attach_kb", spy)

    source_id = await _publish(tenant_id, "Hours", HOURS)

    claims = await _line_claims(tenant_id, line_id)
    assert set(claims) == {source_id}
    assert claims[source_id] in await engine.list_kb(line_ref)
    config = sent[line_ref]
    assert config is not None and config.holder == str(line_id)

    async with tenant_session(tenant_id) as session:
        assert await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)
    assert await _line_claims(tenant_id, line_id) == {}
    assert claims[source_id] not in await engine.list_kb(line_ref)


async def test_an_archived_lines_knowledge_is_withdrawn_and_it_is_not_targeted() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    engine = _fake()
    source_id = await _publish(tenant_id, "Fees", FEES)
    line_id, line_ref = await _published_line(tenant_id, agent_id)
    handle = (await _line_claims(tenant_id, line_id))[source_id]

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET archived_at = now() WHERE id = :l"), {"l": line_id}
        )
        withdrawn = await kb_service.withdraw_line_knowledge(
            session, tenant_id=tenant_id, line_id=line_id
        )

    assert withdrawn == 1
    assert await _line_claims(tenant_id, line_id) == {}
    assert handle not in await engine.list_kb(line_ref)
    async with tenant_session(tenant_id) as session:
        targets = await kb_service.vendor_targets(session, tenant_id=tenant_id)
    assert all(target.inbound_line_id is None for target in targets)


async def test_another_tenants_line_is_invisible() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    other_id, _other_agent = await _tenant_with_published_agent()
    await _publish(tenant_id, "Fees", FEES)
    line_id, _ref = await _published_line(tenant_id, agent_id)
    assert await _line_claims(tenant_id, line_id)

    async with tenant_session(other_id) as session:
        targets = await kb_service.vendor_targets(session, tenant_id=tenant_id)
        lines_seen = (
            await session.execute(
                text("SELECT count(*) FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
        handles = await kb_service.recorded_handles_of_agent(
            session, agent_id, inbound_line_id=line_id
        )
        running = await kb_service.running_lines(session, agent_id=agent_id)
    assert targets == []
    assert lines_seen == 0
    assert handles == set()
    assert running == []
