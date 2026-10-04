"""A closed or erased account's agents hold no conversation (D-538's open half).

Closing an account left its agents `live` and its numbers pointed at them, and the owned
runtime's answer route serves any ref without a DB read (hard rule 3) — so a caller dialling
a closed clinic was greeted by its receptionist, and after the erasure the certificate said
so. What is asserted here:

1. the worker's session read refuses a closed account's agent and an erased one's by name
   (`worker_account_closed`) and alarms, while a SUSPENDED account still answers;
2. the close detaches the account's numbers at the carrier and the undo re-attaches the
   numbers of its live answering agents — over HTTP, through the real route;
3. a hangup for an erased account writes no caller record.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from apps.api.admin.closure_routes import close_account_confirmation
from apps.api.agents.lifecycle import release_account_numbers, restore_account_numbers
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.engine.pipecat import PipecatEngine
from apps.api.worker import service as worker_service
from apps.workers import carrier_events
from sqlalchemy import text
from tests.caller_id_and_inbound_routing_test import _number, _publish
from tests.caller_id_and_inbound_routing_test import _tenant as _published_tenant
from tests.pipecat_engine_test import _config, _make_the_agent_live, _org
from tests.tenant_closure_test import BASE, _admin, _client, _close

pytestmark = [pytest.mark.rls]


def _alerts(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [
        str(record.__dict__.get("code")) for record in caplog.records if record.message == "alert"
    ]


async def _live_runtime_agent() -> tuple[uuid.UUID, uuid.UUID, str]:
    tenant_id, agent_id = await _org()
    ref = await PipecatEngine().create_agent(_config(tenant_id, agent_id))
    await _make_the_agent_live(tenant_id, agent_id, ref)
    return tenant_id, agent_id, ref


async def _set_account(tenant_id: uuid.UUID, statement: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(text(statement), {"t": tenant_id})


_CLOSE = (
    "UPDATE organizations SET status = 'churned', closed_at = now(), "
    "erase_after = now() + interval '30 days' WHERE id = :t"
)
_ERASE = (
    "UPDATE organizations SET status = 'churned', closed_at = now(), erase_after = NULL, "
    "deleted_at = now() WHERE id = :t"
)


async def test_a_closed_accounts_agent_is_refused_by_name_and_alarms(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id, _agent_id, ref = await _live_runtime_agent()
    served = await worker_service.load_session(ref)
    assert served.tenant_id == tenant_id, "the fixture must be servable before the close"

    await _set_account(tenant_id, _CLOSE)

    with pytest.raises(ProblemError) as refused:
        await worker_service.load_session(ref)
    assert refused.value.code == "worker_account_closed"
    assert "inbound_call_on_closed_account" in _alerts(caplog)


async def test_an_erased_accounts_agent_is_refused_the_same_way() -> None:
    tenant_id, _agent_id, ref = await _live_runtime_agent()

    await _set_account(tenant_id, _ERASE)

    with pytest.raises(ProblemError) as refused:
        await worker_service.load_session(ref)
    assert refused.value.code == "worker_account_closed"


async def test_a_pre_closure_churned_account_is_refused_too() -> None:
    """`churned` with no `closed_at` is how accounts were ended before D-546."""
    tenant_id, _agent_id, ref = await _live_runtime_agent()

    await _set_account(tenant_id, "UPDATE organizations SET status = 'churned' WHERE id = :t")

    with pytest.raises(ProblemError) as refused:
        await worker_service.load_session(ref)
    assert refused.value.code == "worker_account_closed"


async def test_a_suspended_account_still_answers() -> None:
    """Suspension stops US dialling out; a suspended client's own customers still ring."""
    tenant_id, agent_id, ref = await _live_runtime_agent()

    await _set_account(tenant_id, "UPDATE organizations SET status = 'suspended' WHERE id = :t")

    served = await worker_service.load_session(ref)
    assert served.agent_id == agent_id


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


async def test_an_erased_account_is_seen_as_erased_by_the_hangup_path() -> None:
    """The orphan-inbound writer asks this before minting a call row, so a hangup for an
    erased account never acquires a caller record or a carrier CDR read."""
    tenant_id, _agent_id, _ref = await _live_runtime_agent()
    assert await carrier_events._account_erased(tenant_id) is False

    await _set_account(tenant_id, _ERASE)

    assert await carrier_events._account_erased(tenant_id) is True
