"""A paying client's test copy carries the client's knowledge (D-859 option A, D-964).

The test copy is the developer-workspace vendor agent a paying client's test call rings
through before the client has a number of its own. It is its own vendor agent, so like an
experiment arm (D-806) it holds its own copy of every live source, claimed in
`engine_kb_routes` with `test_copy`: attached when the copy is made or made again, kept in
step by every publish and withdrawal, and released when the copy is retired. Without it the
owner tested an agent that answered without the client's documents.

Driven through the real paths (`agents.service.publish_agent(onto_test_copy=True)`,
`kb.service.publish_source` / `withdraw_source`, the retire job) on the shared fake engine.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import service as agents_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.kb import service as kb_service
from apps.api.kb.reconciliation import handles_if_no_publish_in_flight
from apps.workers import engine_workspaces as workspace_jobs
from calevate_shared.engine import KBSourceRef
from sqlalchemy import text
from tests.experiment_arm_knowledge_test import FEES, HOURS, _publish
from tests.kb_workflow_test import _tenant_with_published_agent


def _engine() -> FakeEngine:
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    return engine


async def _publish_copy(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return await agents_service.publish_agent(
            session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False, onto_test_copy=True
        )


async def _claims(tenant_id: uuid.UUID, *, test_copy: bool) -> dict[uuid.UUID, str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT source_id, engine_kb_ref FROM engine_kb_routes "
                    "WHERE test_copy = :c AND variant_id IS NULL"
                ),
                {"c": test_copy},
            )
        ).all()
    return {uuid.UUID(str(row[0])): str(row[1]) for row in rows}


async def _copy_ref(tenant_id: uuid.UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        value = (
            await session.execute(text("SELECT engine_agent_ref FROM agent_test_copies"))
        ).scalar()
    return None if value is None else str(value)


async def _retire(
    monkeypatch: pytest.MonkeyPatch, tenant_id: uuid.UUID, agent_id: uuid.UUID, ref: str
) -> None:
    async def _no_live_call(_ref: str) -> bool:
        return False

    async def _nothing(*_a: Any, **_k: Any) -> int:
        return 0

    monkeypatch.setattr(
        workspace_jobs, "thinnest_actions", lambda: SimpleNamespace(has_live_call=_no_live_call)
    )
    monkeypatch.setattr(workspace_jobs, "retire_in_call_actions", _nothing)
    payload = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "old_ref": ref}
    assert await workspace_jobs.retire_moved_engine_agent({"job_try": 1}, payload) == "retired"


async def _retire_jobs(tenant_id: uuid.UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload->>'old_ref' FROM outbox_messages "
                    "WHERE job = 'retire_moved_engine_agent' AND payload->>'tenant_id' = :t"
                ),
                {"t": str(tenant_id)},
            )
        ).scalars()
        return [str(row) for row in rows]


async def test_a_copy_is_made_holding_the_live_knowledge() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish(tenant_id, "Fees", FEES)

    copy = await _publish_copy(tenant_id, agent_id)

    claims = await _claims(tenant_id, test_copy=True)
    assert set(claims) == {source_id}
    listed = await _engine().list_kb(copy)
    assert claims[source_id] in listed
    assert set(await _claims(tenant_id, test_copy=False)) == {source_id}, "the agent keeps its own"
    # The drift sweep scores the copy's route against the copy's own claims.
    async with tenant_session(tenant_id) as session:
        recorded = await handles_if_no_publish_in_flight(
            session, tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=copy
        )
    assert recorded is not None and set(listed) <= recorded


async def test_a_source_published_or_withdrawn_later_reaches_the_copy() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    copy = await _publish_copy(tenant_id, agent_id)
    assert await _claims(tenant_id, test_copy=True) == {}

    source_id = await _publish(tenant_id, "Hours", HOURS)
    handle = (await _claims(tenant_id, test_copy=True))[source_id]
    assert handle in await _engine().list_kb(copy)

    async with tenant_session(tenant_id) as session:
        assert await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)
    assert await _claims(tenant_id, test_copy=True) == {}
    assert handle not in await _engine().list_kb(copy)


async def test_a_retired_copy_releases_its_claims_and_a_new_one_gets_them_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish(tenant_id, "Fees", FEES)
    first = await _publish_copy(tenant_id, agent_id)
    assert set(await _claims(tenant_id, test_copy=True)) == {source_id}

    await _retire(monkeypatch, tenant_id, agent_id, first)

    assert await _copy_ref(tenant_id) is None
    assert await _claims(tenant_id, test_copy=True) == {}
    assert set(await _claims(tenant_id, test_copy=False)) == {source_id}, "the agent's stay"

    again = await _publish_copy(tenant_id, agent_id)
    assert await _copy_ref(tenant_id) == again
    claims = await _claims(tenant_id, test_copy=True)
    assert set(claims) == {source_id}
    assert claims[source_id] in await _engine().list_kb(again)


async def test_retiring_a_copy_already_replaced_keeps_the_new_copys_claims(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish(tenant_id, "Fees", FEES)
    await _publish_copy(tenant_id, agent_id)

    await _retire(monkeypatch, tenant_id, agent_id, f"fakeagent_gone_{uuid.uuid4().hex[:8]}")

    assert set(await _claims(tenant_id, test_copy=True)) == {source_id}


async def test_a_move_hands_the_agents_copies_to_the_kept_test_copy() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    source_id = await _publish(tenant_id, "Fees", FEES)
    own = await _claims(tenant_id, test_copy=False)
    async with tenant_session(tenant_id) as session:
        old_ref = str(
            (
                await session.execute(
                    text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
                )
            ).scalar_one()
        )
        # As the publish that recreated it in the client's workspace has just written.
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"),
            {"r": f"fakeagent_moved_{uuid.uuid4().hex[:8]}@org_test", "a": agent_id},
        )
        await agents_service._after_workspace_move(
            session, tenant_id=tenant_id, agent_id=agent_id, old_ref=old_ref
        )

    assert await _copy_ref(tenant_id) == old_ref
    assert await _claims(tenant_id, test_copy=True) == own
    assert await _claims(tenant_id, test_copy=False) == {}
    assert source_id in own


async def test_a_copy_that_will_not_release_a_withdrawn_document_is_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    engine = _engine()
    source_id = await _publish(tenant_id, "Fees", FEES)
    copy = await _publish_copy(tenant_id, agent_id)
    detach = engine.detach_kb

    async def _refuse_on_copy(ref: str, kb: str, *, agent: Any = None) -> None:
        if ref == copy:
            raise ProblemError(kind="dependency", code="engine_rejected", title="No", detail="No")
        await detach(ref, kb, agent=agent)

    monkeypatch.setattr(engine, "detach_kb", _refuse_on_copy)

    async with tenant_session(tenant_id) as session:
        assert await kb_service.withdraw_source(session, tenant_id=tenant_id, source_id=source_id)

    assert await _claims(tenant_id, test_copy=False) == {}, "the client's withdrawal went through"
    assert await _claims(tenant_id, test_copy=True) == {}
    assert copy in await _retire_jobs(tenant_id)


async def test_a_copy_holding_unrecorded_knowledge_is_replaced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A copy kept by a move before D-964 holds documents no claim names."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    engine = _engine()
    legacy = await _publish_copy(tenant_id, agent_id)
    await engine.attach_kb(legacy, KBSourceRef(kb_id=str(uuid.uuid4()), title="Old", text=FEES))

    # The client's publish is not held back by the copy it cannot account for.
    source_id = await _publish(tenant_id, "Hours", HOURS)
    assert set(await _claims(tenant_id, test_copy=False)) == {source_id}
    assert await _claims(tenant_id, test_copy=True) == {}

    # The vendor names a new agent on every create; the fake derives one name per agent.
    async def _create(cfg: Any) -> str:
        ref = f"fakeagent_{uuid.uuid4().hex[:12]}"
        engine._agents[ref] = cfg
        return ref

    monkeypatch.setattr(engine, "create_agent", _create)

    fresh = await _publish_copy(tenant_id, agent_id)

    assert fresh != legacy
    assert await _copy_ref(tenant_id) == fresh
    claims = await _claims(tenant_id, test_copy=True)
    assert set(claims) == {source_id}
    assert claims[source_id] in await engine.list_kb(fresh)
    assert legacy in await _retire_jobs(tenant_id)
