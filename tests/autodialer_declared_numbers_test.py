"""The autodialer notice names the numbers the calls come from, and the gate holds it to them.

The TCCCPR Third Amendment (18 Sep 2026) requires an automated caller to declare its CLIs to
its access provider in advance and treats a call from an undeclared one as unsolicited
commercial communication (REPORTED, `docs/evidence/trai-tcccpr-third-amendment-2026-09-18.md`
row 2). These drive the real recorder, the real dial gate, readiness and the route.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from apps.api.agents.service import agent_registered_numbers, resolve_caller_id
from apps.api.compliance import autodialer
from apps.api.compliance.autodialer import (
    AUTODIALER_NOTICE_CLI_UNDECLARED_RULE,
    MAX_DECLARED_CLIS,
    declared_cli,
    read_autodialer_notice,
    record_autodialer_notice,
)
from apps.api.core.errors import ProblemError
from apps.api.core.loadshed import PlatformStatus
from apps.api.db.session import tenant_session
from apps.api.legal.readiness import _UNKNOWN, ROW_COPY, readiness_rows
from sqlalchemy import text
from tests.autodialer_notice_route_test import PATH, _body, _client, _headers
from tests.autodialer_notice_route_test import _tenant as _bare_tenant
from tests.outbound_consent_policy_test import _fresh_phone, _gate, _tenant

pytestmark = pytest.mark.asyncio


async def _recorder(tenant_id: UUID) -> UUID:
    user_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.test"},
        )
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, 'owner', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
        await session.commit()
    return user_id


async def _record(tenant_id: UUID, numbers: list[str], *, withdraw: bool = False) -> None:
    by = await _recorder(tenant_id)
    async with tenant_session(tenant_id) as session:
        await record_autodialer_notice(
            session,
            tenant_id=tenant_id,
            access_provider="Airtel",
            objective="Appointment reminders for our own customers",
            notified_on=(datetime.now(UTC) - timedelta(days=5)).date(),
            declared_clis=numbers,
            recorded_by=by,
            withdraw=withdraw,
        )
        await session.commit()


def test_a_header_typed_as_issued_is_stored_as_the_number_the_agent_presents() -> None:
    assert declared_cli("1409876543") == "+911409876543"
    assert declared_cli("+91 160 123 4567") == "+911601234567"
    assert declared_cli("98480 22338") == "+919848022338"


def test_a_string_that_is_no_callable_number_is_refused() -> None:
    assert declared_cli("1234567890") is None
    assert declared_cli("not a number") is None


async def test_the_recorder_normalises_and_collapses_repeats() -> None:
    org = await _bare_tenant()
    tenant_id = UUID(str(org["id"]))
    await _record(tenant_id, ["98480 22338", "+919848022338", "1409876543", "  "])
    async with tenant_session(tenant_id) as session:
        notice = await read_autodialer_notice(session, tenant_id=tenant_id)
    assert notice.declared_clis == ("+919848022338", "+911409876543")


async def test_a_notice_must_name_at_least_one_number() -> None:
    org = await _bare_tenant()
    with pytest.raises(ProblemError) as refused:
        await _record(UUID(str(org["id"])), [])
    assert refused.value.code == "autodialer_notice_numbers_missing"


async def test_a_withdrawal_need_not_name_any() -> None:
    org = await _bare_tenant()
    tenant_id = UUID(str(org["id"]))
    await _record(tenant_id, ["+919848022338"])
    await _record(tenant_id, [], withdraw=True)
    async with tenant_session(tenant_id) as session:
        assert (await read_autodialer_notice(session, tenant_id=tenant_id)).state == "withdrawn"


async def test_one_bad_entry_refuses_the_whole_notice() -> None:
    org = await _bare_tenant()
    with pytest.raises(ProblemError) as refused:
        await _record(UUID(str(org["id"])), ["+919848022338", "1234567890"])
    assert refused.value.code == "autodialer_notice_number_invalid"


async def test_more_numbers_than_a_notice_holds_is_refused() -> None:
    org = await _bare_tenant()
    too_many = [f"+91980000{n:04d}" for n in range(MAX_DECLARED_CLIS + 1)]
    with pytest.raises(ProblemError) as refused:
        await _record(UUID(str(org["id"])), too_many)
    assert refused.value.code == "autodialer_notice_numbers_too_many"


async def test_the_resolved_caller_id_is_the_whole_number() -> None:
    """`resolve_caller_id` now reads `agent_registered_numbers`, whose rows are strings."""
    tenant_id, agent_id = await _tenant("clis-resolve")
    async with tenant_session(tenant_id) as session:
        numbers = await agent_registered_numbers(session, agent_id=agent_id)
        caller_id = await resolve_caller_id(session, agent_id=agent_id)
    assert len(numbers) == 1
    assert caller_id == numbers[0]
    assert caller_id is not None and caller_id.startswith("+91") and len(caller_id) == 13


async def test_a_dial_from_a_declared_number_is_allowed() -> None:
    tenant_id, agent_id = await _tenant("clis-declared")
    decision = await _gate(tenant_id, agent_id, _fresh_phone())
    assert decision.allowed is True, decision.rule


async def test_a_dial_from_a_number_the_notice_omits_is_refused() -> None:
    tenant_id, agent_id = await _tenant("clis-omitted")
    await _record(tenant_id, ["+919848022338"])

    decision = await _gate(tenant_id, agent_id, _fresh_phone())

    assert decision.allowed is False
    assert decision.rule == AUTODIALER_NOTICE_CLI_UNDECLARED_RULE


async def test_readiness_names_the_refusal_the_dial_would_give() -> None:
    tenant_id, _agent_id = await _tenant("clis-ready")
    await _record(tenant_id, ["+919848022338"])
    async with tenant_session(tenant_id) as session:
        rows = await readiness_rows(
            session,
            tenant_id=tenant_id,
            platform=PlatformStatus(mode="normal", outbound_halted=False),
        )
    [row] = [row for row in rows if row.rule == AUTODIALER_NOTICE_CLI_UNDECLARED_RULE]
    # The client's move, with the client's next step — not the fallback row that tells
    # them to contact support about a refusal only they can clear.
    assert row.actor == "client"
    assert row.title != _UNKNOWN.title and row.next_step != _UNKNOWN.next_step


def test_every_autodialer_rule_the_gate_emits_has_readiness_copy() -> None:
    rules = {
        value
        for name, value in vars(autodialer).items()
        if name.startswith("AUTODIALER_NOTICE_") and name.endswith("_RULE")
    }
    assert len(rules) == 4, rules
    assert rules <= set(ROW_COPY), sorted(rules - set(ROW_COPY))


async def test_the_route_lists_what_is_declared_and_what_is_not() -> None:
    tenant_id, agent_id = await _tenant("clis-route")
    async with tenant_session(tenant_id) as session:
        agent_number = (await agent_registered_numbers(session, agent_id=agent_id))[0]
    org = {"id": tenant_id, "slug": await _slug(tenant_id)}
    async with _client() as http:
        posted = await http.post(
            PATH, headers=await _headers(org), json=_body(declared_clis=["98480 22338"])
        )
    assert posted.status_code == 201, posted.text
    body = posted.json()
    assert body["declared_clis"] == ["+919848022338"]
    assert body["undeclared_clis"] == [agent_number]


async def _slug(tenant_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
        )
