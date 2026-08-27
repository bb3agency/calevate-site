"""The DLT + India-only layer of `check_dispatch`, for the SINGLE-LEAD and instant
callback paths (LEGAL-OPS-PLAYBOOK §10.8 / §16-C).

Campaigns were always gated on Calevate's TM registration, the client's PE-TM chain and
the calling number's series/registration (`campaigns.service.dispatch_blockers`). The
D-21 "call this lead" button and the instant-callback webhook went through
`check_dispatch`, which had none of that — so a requested callback, which the playbook
calls regulated outbound, could go out with no PE-TM chain and from the engine's shared
pool number.

These tests pin the closure:

- the shared entity check (`outbound_entity_blockers`) is the ONE implementation the
  campaign gate and `check_dispatch` both read — TM live AND the client's PE-TM chain
  active;
- the single-lead header check (`agent_outbound_number_blocker`) refuses a dial that
  would present the engine's pool number instead of the agent's own registered header;
- the India-only freeze is enforced at the destination (`destination_not_india`);
- INBOUND never reaches any of it — an inbound agent is refused two rules earlier.

The refusals are asked through `check_dispatch` (not the helpers in isolation) because
the property under test is that the gate every dial path converges on now carries them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.service import agent_outbound_number_blocker
from apps.api.compliance.service import check_dispatch
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.conftest import accept_agreements, arm_agent_for_outbound

_INDIA = "+919876500001"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so a refusal here is never the calling-hours rule by accident."""
    fixed = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _tenant_agent(*, direction: str = "outbound") -> tuple[uuid.UUID, uuid.UUID]:
    """A live, published agent with a disclosure line — so the gate reaches the DLT layer
    rather than stopping on an agent question. NOTHING is armed: each test adds exactly
    the paperwork it is measuring."""
    created = await admin_service.create_organization(
        name="Reg Motors",
        slug=f"reg-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = :dir WHERE id = :a"),
            {"dir": direction, "a": agent_id},
        )
    return tenant_id, agent_id


async def _record_pe(tenant_id: uuid.UUID, *, status: str, tm_link_status: str) -> None:
    from apps.api.campaigns import service as campaigns

    async with tenant_session(tenant_id) as session:
        await campaigns.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Reg Motors Pvt Ltd",
            status=status,
            tm_link_status=tm_link_status,
            registered_at=datetime.now(UTC) - timedelta(days=10),
        )


async def _bind_number(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, dlt_status: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, :e, '140', :dlt, now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "e": f"+9180{uuid.uuid4().int % 100000000:08d}",
                "dlt": dlt_status,
            },
        )


async def _gate(tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str = _INDIA) -> object:
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )


# --- the entity half: WHO may place the call ---------------------------------


async def test_single_lead_refused_when_pe_registration_missing() -> None:
    """A client with no DLT Principal Entity registration cannot place a callback, even
    with a registered number bound — the entity is checked before the header."""
    tenant_id, agent_id = await _tenant_agent()
    await _bind_number(tenant_id, agent_id, dlt_status="registered")
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == "pe_registration_missing"


async def test_single_lead_refused_when_pe_not_active() -> None:
    tenant_id, agent_id = await _tenant_agent()
    await _bind_number(tenant_id, agent_id, dlt_status="registered")
    await _record_pe(tenant_id, status="submitted", tm_link_status="pending")
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == "pe_registration_not_active"


async def test_single_lead_refused_when_tm_link_not_active() -> None:
    """PE registered but its PE-TM chain to Calevate is not Active — the client has to
    bind and approve the TM before any outbound (playbook §10.4)."""
    tenant_id, agent_id = await _tenant_agent()
    await _bind_number(tenant_id, agent_id, dlt_status="registered")
    await _record_pe(tenant_id, status="active", tm_link_status="pending")
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == "tm_link_not_active"


# --- the header half: from WHAT number ---------------------------------------


async def test_single_lead_refused_when_agent_has_no_registered_number() -> None:
    """The chain is active but the agent has no number bound, so the dial would present
    the engine's pool number — refused (playbook §10.8), not silently allowed."""
    tenant_id, agent_id = await _tenant_agent()
    await _record_pe(tenant_id, status="active", tm_link_status="active")
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == "number_not_bound_to_agent"


async def test_single_lead_refused_when_bound_number_not_registered() -> None:
    tenant_id, agent_id = await _tenant_agent()
    await _record_pe(tenant_id, status="active", tm_link_status="active")
    await _bind_number(tenant_id, agent_id, dlt_status="pending")
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == "number_not_registered"


async def test_single_lead_allowed_when_chain_active_and_number_registered() -> None:
    """The positive case, without which every refusal above proves nothing."""
    tenant_id, agent_id = await _tenant_agent()
    await arm_agent_for_outbound(tenant_id, agent_id)
    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed, f"a fully-registered outbound dial was refused: {decision.rule}"


# --- the India-only freeze ---------------------------------------------------


async def test_non_india_destination_is_refused_even_when_everything_else_passes() -> None:
    """A +1 number is out of scope for the freeze and refused at the destination, before
    any line is seized — on a tenant that could otherwise lawfully dial."""
    tenant_id, agent_id = await _tenant_agent()
    await arm_agent_for_outbound(tenant_id, agent_id)
    decision = await _gate(tenant_id, agent_id, phone="+15551234567")
    assert not decision.allowed and decision.rule == "destination_not_india"


async def test_india_destination_passes_the_freeze_check() -> None:
    tenant_id, agent_id = await _tenant_agent()
    await arm_agent_for_outbound(tenant_id, agent_id)
    decision = await _gate(tenant_id, agent_id, phone="+919000012345")
    assert decision.allowed


# --- inbound is untouched ----------------------------------------------------


async def test_inbound_agent_never_reaches_the_registration_gate() -> None:
    """An inbound-only agent is refused two rules earlier (`agent_inbound_only`), so
    answering calls needs no TM, no PE-TM chain and no registered outbound header — the
    freeze and the DLT layer are OUTBOUND-only (playbook §10.1)."""
    tenant_id, agent_id = await _tenant_agent(direction="inbound")
    # Deliberately unarmed: an inbound agent must not depend on any of it.
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == "agent_inbound_only"


# --- the header helper, and its tenant isolation -----------------------------


async def test_number_blocker_cannot_see_another_tenants_numbers() -> None:
    """`agent_outbound_number_blocker`'s query is RLS-scoped (hard rule 1): tenant B's
    session cannot see tenant A's registered number, so it reads zero rows and refuses —
    a foreign agent id can never launder itself into a lawful header."""
    a_tenant, a_agent = await _tenant_agent()
    await _bind_number(a_tenant, a_agent, dlt_status="registered")
    b_tenant, _b_agent = await _tenant_agent()

    async with tenant_session(a_tenant) as session:
        own = await agent_outbound_number_blocker(session, agent_id=a_agent)
    assert own is None, "the agent's own tenant sees its registered number"

    async with tenant_session(b_tenant) as session:
        cross = await agent_outbound_number_blocker(session, agent_id=a_agent)
    assert cross == (
        "number_not_bound_to_agent",
        cross[1] if cross else "",
    ), "another tenant sees zero rows and is refused"


async def test_untenanted_session_sees_no_numbers() -> None:
    """No tenant GUC → RLS shows zero rows → refuse, the same fail-closed direction the
    rest of the gate takes."""
    a_tenant, a_agent = await _tenant_agent()
    await _bind_number(a_tenant, a_agent, dlt_status="registered")
    async with untenanted_session() as session:
        blocked = await agent_outbound_number_blocker(session, agent_id=a_agent)
    assert blocked is not None and blocked[0] == "number_not_bound_to_agent"
