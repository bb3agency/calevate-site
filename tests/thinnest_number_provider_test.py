"""A ThinnestAI-rented number is recorded as such and presented only on that engine (D-678).

On `ENGINE=thinnest` numbers are rented and attached in ThinnestAI's console
(`thinnest-findings/mirror/pages/api-reference/voices-and-models.md:85-87`), and the founder
decided ThinnestAI calls go out on ThinnestAI numbers only, Vobiz on Pipecat only. So
`phone_numbers.provider` admits `thinnest` (migration a3d9e6f1c204), the admin record route
accepts it only on that engine, and the dial gate presents a number on ThinnestAI only when
it is recorded there. Every other engine's rule is untouched.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.agents import service as agents_service
from apps.api.agents.service import (
    NUMBER_INBOUND_ONLY_REASON,
    NUMBER_INBOUND_ONLY_RULE,
    NUMBER_NOT_ON_CARRIER_RULE,
    agent_outbound_number_blocker,
    resolve_caller_id,
)
from apps.api.compliance.service import check_dispatch
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.conftest import arm_agent_for_outbound
from tests.dlt_admin_routes_test import NUMBERS, _client, _e164, _make_admin, _tenant
from tests.outbound_registration_gate_test import _daytime, _tenant_agent  # noqa: F401

pytestmark = [pytest.mark.rls]


async def _number(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, provider: str | None, direction: str = "both"
) -> str:
    e164 = f"+9180{uuid.uuid4().int % 10**8:08d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "provider, direction, created_at, updated_at) VALUES (:id, :tid, :aid, :e, "
                "'140', 'registered', :prov, :dir, now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "e": e164,
                "prov": provider,
                "dir": direction,
            },
        )
    return e164


@pytest.fixture
def on_thinnest(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")


# --- the column ------------------------------------------------------------------


async def test_the_column_admits_thinnest_and_still_refuses_a_free_text_provider() -> None:
    tenant_id, agent_id = await _tenant_agent()
    await _number(tenant_id, agent_id, provider="thinnest")
    with pytest.raises(IntegrityError):
        await _number(tenant_id, agent_id, provider="exotel")


# --- the dial gate ----------------------------------------------------------------


async def test_on_thinnest_a_registered_thinnest_number_is_presented(on_thinnest: None) -> None:
    tenant_id, agent_id = await _tenant_agent()
    e164 = await _number(tenant_id, agent_id, provider="thinnest")
    async with tenant_session(tenant_id) as session:
        assert await agent_outbound_number_blocker(session, agent_id=agent_id) is None
        assert await resolve_caller_id(session, agent_id=agent_id) == e164


async def test_on_thinnest_a_number_not_recorded_there_is_refused(on_thinnest: None) -> None:
    tenant_id, agent_id = await _tenant_agent()
    await _number(tenant_id, agent_id, provider="vobiz")
    await _number(tenant_id, agent_id, provider=None)
    async with tenant_session(tenant_id) as session:
        blocked = await agent_outbound_number_blocker(session, agent_id=agent_id)
        assert await resolve_caller_id(session, agent_id=agent_id) is None
    assert blocked is not None and blocked[0] == NUMBER_NOT_ON_CARRIER_RULE


async def test_on_thinnest_a_number_bought_for_incoming_calls_is_refused(
    on_thinnest: None,
) -> None:
    tenant_id, agent_id = await _tenant_agent()
    await _number(tenant_id, agent_id, provider="thinnest", direction="inbound")
    async with tenant_session(tenant_id) as session:
        blocked = await agent_outbound_number_blocker(session, agent_id=agent_id)
    assert blocked == (NUMBER_INBOUND_ONLY_RULE, NUMBER_INBOUND_ONLY_REASON)


async def test_on_pipecat_a_thinnest_number_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """The Pipecat deployment's carrier rule, unchanged: a number not on Vobiz is refused."""
    monkeypatch.setattr(agents_service, "outbound_carrier", lambda: "vobiz")
    tenant_id, agent_id = await _tenant_agent()
    await _number(tenant_id, agent_id, provider="thinnest")
    async with tenant_session(tenant_id) as session:
        blocked = await agent_outbound_number_blocker(session, agent_id=agent_id)
    assert blocked is not None and blocked[0] == NUMBER_NOT_ON_CARRIER_RULE


async def test_check_dispatch_admits_an_armed_agent_on_thinnest(on_thinnest: None) -> None:
    tenant_id, agent_id = await _tenant_agent()
    await arm_agent_for_outbound(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000012345"
        )
        provider = (
            await session.execute(
                text("SELECT provider FROM phone_numbers WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert provider == "thinnest"
    assert decision.allowed, decision.rule


async def test_another_tenants_thinnest_number_is_zero_rows(on_thinnest: None) -> None:
    a_tenant, a_agent = await _tenant_agent()
    await _number(a_tenant, a_agent, provider="thinnest")
    b_tenant, _b_agent = await _tenant_agent()
    async with tenant_session(b_tenant) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM phone_numbers WHERE agent_id = :a"), {"a": a_agent}
            )
        ).scalar_one()
        blocked = await agent_outbound_number_blocker(session, agent_id=a_agent)
    assert seen == 0
    assert blocked is not None and blocked[0] == "number_not_bound_to_agent"


# --- the admin record route -----------------------------------------------------------


async def test_the_record_route_takes_thinnest_only_on_thinnest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug = await _tenant()
    token = await _make_admin()
    headers = {"Authorization": f"Bearer {token}"}
    body = {"e164": _e164("140"), "series": "140", "provider": "thinnest", "direction": "both"}
    async with _client() as http:
        refused = await http.post(NUMBERS.format(tenant_id=tenant_id), json=body, headers=headers)
        assert refused.status_code == 422
        assert refused.json()["type"].endswith("/number_provider_not_on_this_engine")
        monkeypatch.setattr(get_settings(), "engine", "thinnest")
        # On its own engine the hand-typed number must be one the platform holds (D-691);
        # it is brought, so it is not priced, and nothing answers it, so nothing is attached.
        from apps.api.campaigns import engine_numbers
        from calevate_shared.engine import ProvisionedNumber

        async def _held(_workspace: object) -> list[ProvisionedNumber]:
            return [
                ProvisionedNumber(
                    e164=body["e164"],
                    provider="thinnest",
                    engine_number_ref=body["e164"].lstrip("+"),
                    engine_owned=False,
                )
            ]

        async def _unchanged(*_a: object, **_k: object) -> str:
            return "unchanged"

        monkeypatch.setattr(engine_numbers, "vendor_numbers", _held)
        monkeypatch.setattr(engine_numbers, "sync_number_attachment", _unchanged)
        recorded = await http.post(NUMBERS.format(tenant_id=tenant_id), json=body, headers=headers)
    assert recorded.status_code in (200, 201), recorded.text
    async with tenant_session(tenant_id) as session:
        provider = (
            await session.execute(
                text("SELECT provider FROM phone_numbers WHERE id = :i"),
                {"i": recorded.json()["id"]},
            )
        ).scalar_one()
    assert provider == "thinnest"
