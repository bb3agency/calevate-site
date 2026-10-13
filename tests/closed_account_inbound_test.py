"""A closed account's numbers stop answering, and the undo re-attaches them (D-538).

Closing an account left its agents `live` and its numbers pointed at them, so a caller
dialling a closed business was greeted by its receptionist. What is asserted here: the
close detaches the account's numbers at the engine and the undo re-attaches the numbers of
its live answering agents, over HTTP, through the real route.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from apps.api.admin.closure_routes import close_account_confirmation
from apps.api.agents.lifecycle import release_account_numbers, restore_account_numbers
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from sqlalchemy import text
from tests.caller_id_and_inbound_routing_test import _number, _publish
from tests.caller_id_and_inbound_routing_test import _tenant as _published_tenant
from tests.tenant_closure_test import BASE, _admin, _client, _close

pytestmark = [pytest.mark.rls]


async def test_closing_detaches_the_numbers_and_reopening_reattaches_them() -> None:
    tenant_id, agent_id = await _published_tenant()
    handle = f"num_close_{uuid.uuid4().hex[:8]}"
    await _number(tenant_id, agent_id=agent_id, engine_number_ref=handle)
    ref = await _publish(tenant_id, agent_id, direction="inbound")
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    assert engine.inbound_agent_for(handle) == ref
    token = await _admin()

    closed = await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    assert closed.status_code == 200, closed.text
    assert engine.inbound_agent_for(handle) is None, "a closed account's number still answers"

    async with _client() as http:
        reopened = await http.delete(
            BASE.format(tenant_id=tenant_id), headers={"Authorization": f"Bearer {token}"}
        )

    assert reopened.status_code == 200, reopened.text
    assert engine.inbound_agent_for(handle) == ref, "the undo left the number dark"


async def test_the_closure_audit_counts_what_reached_the_carrier(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`audit_log` has no summary column; the summary rides the audit log line."""
    caplog.set_level(logging.INFO)
    tenant_id, agent_id = await _published_tenant()
    await _number(tenant_id, agent_id=agent_id, engine_number_ref=f"num_{uuid.uuid4().hex[:8]}")
    await _publish(tenant_id, agent_id, direction="inbound")
    token = await _admin()

    await _close(token, tenant_id, confirm=close_account_confirmation(tenant_id))

    counted = [
        record.__dict__
        for record in caplog.records
        if record.message == "audit" and "numbers_detached" in record.__dict__
    ]
    assert len(counted) == 1
    assert counted[0]["numbers_detached"] == 1
    assert counted[0]["numbers_not_detached"] == 0


async def test_a_reopen_does_not_reattach_an_agent_silenced_for_the_truthful_answer() -> None:
    """That silence is an unbind of its own; reopening the account must not undo it."""
    tenant_id, agent_id = await _published_tenant()
    handle = f"num_silenced_{uuid.uuid4().hex[:8]}"
    await _number(tenant_id, agent_id=agent_id, engine_number_ref=handle)
    await _publish(tenant_id, agent_id, direction="inbound")
    engine = get_engine()
    assert isinstance(engine, FakeEngine)

    async with tenant_session(tenant_id) as session:
        await release_account_numbers(session)
        await session.execute(
            text(
                "UPDATE agents SET inbound_silenced_at = now(), "
                "inbound_silence_reason = 'truthful_answer_missing' WHERE id = :a"
            ),
            {"a": agent_id},
        )
        restored = await restore_account_numbers(session)

    assert restored.moved == 0
    assert engine.inbound_agent_for(handle) is None


async def test_a_paused_agents_numbers_are_not_reattached_by_a_reopen() -> None:
    tenant_id, agent_id = await _published_tenant()
    handle = f"num_paused_{uuid.uuid4().hex[:8]}"
    await _number(tenant_id, agent_id=agent_id, engine_number_ref=handle)
    await _publish(tenant_id, agent_id, direction="inbound")
    engine = get_engine()
    assert isinstance(engine, FakeEngine)

    async with tenant_session(tenant_id) as session:
        released = await release_account_numbers(session)
        await session.execute(
            text("UPDATE agents SET status = 'paused' WHERE id = :a"), {"a": agent_id}
        )
        restored = await restore_account_numbers(session)

    assert released.moved == 1
    assert restored.moved == 0
    assert engine.inbound_agent_for(handle) is None
