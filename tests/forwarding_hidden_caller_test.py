"""A forwarded call that shows the business's own number instead of the caller's (D-746): the
agent is told to ask for a call-back number, the call is marked, and the lead is filed under
the number the caller gave, never under the business's own."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.api.forwarding import testing
from apps.workers import pipeline
from calevate_shared.engine import (
    CALLER_HIDDEN_VARIABLE,
    FORWARDED_LINE_RULE,
    AgentConfig,
    compose_engine_prompt,
)
from sqlalchemy import text
from tests.forwarding_fixtures import add_line, give_calevate_number, make_client

pytestmark = [pytest.mark.rls]


def _config(**kwargs: object) -> AgentConfig:
    return AgentConfig(
        tenant_id="t",
        agent_id="a",
        name="A",
        direction="inbound",
        language_primary="te-IN",
        system_prompt="Answer questions.",
        opening_line="",
        call_is_recorded=True,
        **kwargs,  # type: ignore[arg-type]
    )


def test_only_a_client_with_a_forwarded_number_carries_the_line() -> None:
    plain = compose_engine_prompt(_config())
    forwarded = compose_engine_prompt(_config(forwarded_line=True))
    assert FORWARDED_LINE_RULE not in plain
    assert FORWARDED_LINE_RULE in forwarded
    assert "{{" + CALLER_HIDDEN_VARIABLE + "}}" in forwarded
    # The owner's headroom: one short line, nothing more.
    assert len(forwarded) - len(plain) <= 200


async def test_the_lookup_marks_the_business_number_hidden_and_not_a_caller() -> None:
    tenant_id, agent_id, _ = await make_client("hidden")
    await give_calevate_number(tenant_id, agent_id)
    line = await add_line(tenant_id)
    async with tenant_session(tenant_id) as session:
        hidden = await testing.record_lookup_arrival(
            session, tenant_id=tenant_id, caller_e164=line.e164, engine_call_id="conv_9"
        )
        caller = await testing.record_lookup_arrival(
            session, tenant_id=tenant_id, caller_e164="+919700000003", engine_call_id="conv_10"
        )
    assert hidden.caller_hidden and hidden.test_id is None
    assert not caller.caller_hidden


async def test_a_client_without_a_forwarded_number_is_never_hidden() -> None:
    tenant_id, _, _ = await make_client("plain")
    async with tenant_session(tenant_id) as session:
        verdict = await testing.record_lookup_arrival(
            session, tenant_id=tenant_id, caller_e164="+919700000004", engine_call_id=None
        )
    assert not verdict.caller_hidden


async def _hidden_call(tenant_id: UUID, agent_id: UUID, business: str) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, from_e164, "
                "status, started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', "
                ":f, 'completed', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"in_{call_id}", "f": business},
        )
        claim = await testing.claim_inbound_call(
            session, call_id=call_id, from_e164=business, started_at=datetime.now(UTC)
        )
    assert claim.caller_hidden
    return call_id


async def test_the_lead_takes_the_call_back_number_or_is_not_filed() -> None:
    from calevate_shared.engine import ExecutionSnapshot

    tenant_id, agent_id, _ = await make_client("lead")
    await give_calevate_number(tenant_id, agent_id)
    line = await add_line(tenant_id)
    call_id = await _hidden_call(tenant_id, agent_id, line.e164)
    snapshot = ExecutionSnapshot(
        engine_call_id=f"in_{call_id}",
        direction="inbound",
        status="completed",
        raw_status="ended",
        terminal=True,
        billable_ready=True,
        from_e164=line.e164,
    )
    filed = await pipeline._upsert_lead(
        tenant_id,
        agent_id,
        call_id,
        snapshot,
        direction="inbound",
        data={"name": "Ravi", "other_number": "98480 12345"},
        schema_version=1,
    )
    assert filed is not None
    async with tenant_session(tenant_id) as session:
        phone = (
            await session.execute(text("SELECT phone_e164 FROM leads WHERE id = :i"), {"i": filed})
        ).scalar()
        hidden = (
            await session.execute(
                text("SELECT caller_id_hidden FROM calls WHERE id = :i"), {"i": call_id}
            )
        ).scalar()
    assert phone == "+919848012345" and hidden is True

    second = await _hidden_call(tenant_id, agent_id, line.e164)
    assert (
        await pipeline._upsert_lead(
            tenant_id,
            agent_id,
            second,
            snapshot.model_copy(update={"engine_call_id": f"in_{second}"}),
            direction="inbound",
            data={"name": "Asha"},
            schema_version=1,
        )
        is None
    )
