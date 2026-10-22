"""The DLT + India-only layer of `check_dispatch`, for the SINGLE-LEAD and instant
callback paths (LEGAL-OPS-PLAYBOOK §10.8 / §16-C).

Campaigns were always gated on Calevate's TM registration, the client's PE-TM chain and
the calling number's series/registration (`campaigns.service.dispatch_blockers`). The
D-21 "call this lead" button and the instant-callback webhook went through
`check_dispatch`, which had none of that — so a requested callback, which the playbook
calls regulated outbound, could go out with no PE-TM chain and from the engine's shared
pool number.

⚠ D-692 (8 Oct 2026) RETIRED the DLT half: the founder decided clients do not register on
DLT, so `check_dispatch` no longer asks the entity chain or the bound registered header;
the five DLT tests below now pin that those states do NOT refuse a dial. KYC and the
no-cold-calls pledge replaced them (`tests/kyc_two_paths_test.py`). What these tests
originally pinned:

- the shared entity check (`outbound_entity_blockers`) is the ONE implementation the
  campaign gate and `check_dispatch` both read — TM live AND the client's PE-TM chain
  active;
- the India-only freeze is enforced at the destination (`destination_not_india`);
- INBOUND never reaches any of it — an inbound agent is refused two rules earlier.

The refusals are asked through `check_dispatch` (not the helpers in isolation) because
the property under test is that the gate every dial path converges on now carries them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.agents.service import agent_outbound_numbers
from apps.api.compliance import registration
from apps.api.compliance.service import check_dispatch
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.conftest import (
    accept_agreements,
    arm_agent_for_outbound,
    create_org_with_receptionist,
    fund_wallet,
)

_INDIA = "+919876500001"

#: The DLT refusals D-692 retired from `check_dispatch` (still defined; no gate asks them).
_RETIRED_DLT_RULES = frozenset(
    {
        "tm_registration_missing",
        "pe_registration_missing",
        "pe_registration_not_active",
        "tm_link_not_active",
        "number_not_bound_to_agent",
        "number_not_registered",
    }
)


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so a refusal here is never the calling-hours rule by accident."""
    fixed = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _tenant_agent(*, direction: str = "outbound") -> tuple[uuid.UUID, uuid.UUID]:
    """A live, published agent with a disclosure line — so the gate reaches the DLT layer
    rather than stopping on an agent question. NOTHING is armed: each test adds exactly
    the paperwork it is measuring."""
    created = await create_org_with_receptionist(
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
    # And credit, for the same reason and in the same shape (D-521): `prepaid` is the
    # default motion now, so an unfunded tenant is refused `no_credits` on every
    # outbound dial and this file would report that in place of what it is about.
    await fund_wallet(uuid.UUID(str(created["id"])))
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


async def test_single_lead_is_not_refused_for_a_missing_pe_registration() -> None:
    """A client with no DLT Principal Entity registration cannot place a callback, even
    with a registered number bound — the entity is checked before the header."""
    tenant_id, agent_id = await _tenant_agent()
    await _bind_number(tenant_id, agent_id, dlt_status="registered")
    decision = await _gate(tenant_id, agent_id)
    # D-692: the DLT layer is inactive; this state no longer refuses the dial.
    assert decision.rule not in _RETIRED_DLT_RULES, decision.rule


async def test_single_lead_is_not_refused_for_an_inactive_pe() -> None:
    tenant_id, agent_id = await _tenant_agent()
    await _bind_number(tenant_id, agent_id, dlt_status="registered")
    await _record_pe(tenant_id, status="submitted", tm_link_status="pending")
    decision = await _gate(tenant_id, agent_id)
    # D-692: the DLT layer is inactive; this state no longer refuses the dial.
    assert decision.rule not in _RETIRED_DLT_RULES, decision.rule


async def test_single_lead_is_not_refused_for_an_inactive_tm_link() -> None:
    """PE registered but its PE-TM chain to Calevate is not Active — the client has to
    bind and approve the TM before any outbound (playbook §10.4)."""
    tenant_id, agent_id = await _tenant_agent()
    await _bind_number(tenant_id, agent_id, dlt_status="registered")
    await _record_pe(tenant_id, status="active", tm_link_status="pending")
    decision = await _gate(tenant_id, agent_id)
    # D-692: the DLT layer is inactive; this state no longer refuses the dial.
    assert decision.rule not in _RETIRED_DLT_RULES, decision.rule


async def test_the_retained_entity_check_names_the_first_gap_in_the_chain() -> None:
    """No gate asks `pe_registration_blocker` since D-692, but it is kept with its rule
    names, so what it would answer stays pinned: missing, then not active (naming the
    status), then the TM link."""
    missing, _ = await _tenant_agent()
    submitted, _ = await _tenant_agent()
    await _record_pe(submitted, status="submitted", tm_link_status="pending")
    unlinked, _ = await _tenant_agent()
    await _record_pe(unlinked, status="active", tm_link_status="pending")

    found: dict[str, tuple[str, str] | None] = {}
    for name, tenant_id in (("missing", missing), ("submitted", submitted), ("unlinked", unlinked)):
        async with tenant_session(tenant_id) as session:
            found[name] = await registration.pe_registration_blocker(session, tenant_id=tenant_id)

    assert found["missing"] == ("pe_registration_missing", registration.PE_MISSING_REASON)
    not_active = found["submitted"]
    assert not_active is not None and not_active[0] == "pe_registration_not_active"
    assert "registration is submitted" in not_active[1]
    assert found["unlinked"] == ("tm_link_not_active", registration.TM_LINK_REASON)


# --- the header half: from WHAT number ---------------------------------------


async def test_single_lead_is_not_refused_for_having_no_registered_number() -> None:
    """The chain is active but the agent has no number bound, so the dial would present
    the engine's pool number — refused (playbook §10.8), not silently allowed."""
    tenant_id, agent_id = await _tenant_agent()
    await _record_pe(tenant_id, status="active", tm_link_status="active")
    decision = await _gate(tenant_id, agent_id)
    # D-692: the DLT layer is inactive; this state no longer refuses the dial.
    assert decision.rule not in _RETIRED_DLT_RULES, decision.rule


async def test_single_lead_is_not_refused_for_an_unregistered_number() -> None:
    tenant_id, agent_id = await _tenant_agent()
    await _record_pe(tenant_id, status="active", tm_link_status="active")
    await _bind_number(tenant_id, agent_id, dlt_status="pending")
    decision = await _gate(tenant_id, agent_id)
    # D-692: the DLT layer is inactive; this state no longer refuses the dial.
    assert decision.rule not in _RETIRED_DLT_RULES, decision.rule


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


# --- the caller-id read, and its tenant isolation ----------------------------


async def test_caller_id_numbers_cannot_be_read_across_tenants() -> None:
    """`agent_outbound_numbers` (the caller-id candidates, D-793) is RLS-scoped (hard rule
    1): tenant B's session reads zero rows for tenant A's agent, so a foreign agent id can
    never borrow another client's number as its caller id."""
    a_tenant, a_agent = await _tenant_agent()
    await _bind_number(a_tenant, a_agent, dlt_status="pending")
    b_tenant, _b_agent = await _tenant_agent()

    async with tenant_session(a_tenant) as session:
        own = await agent_outbound_numbers(session, agent_id=a_agent)
    assert len(own) == 1, "the agent's own tenant sees its number"

    async with tenant_session(b_tenant) as session:
        assert await agent_outbound_numbers(session, agent_id=a_agent) == []


async def test_untenanted_session_sees_no_numbers() -> None:
    """No tenant GUC: RLS shows zero rows, so no caller id is presented."""
    a_tenant, a_agent = await _tenant_agent()
    await _bind_number(a_tenant, a_agent, dlt_status="pending")
    async with untenanted_session() as session:
        assert await agent_outbound_numbers(session, agent_id=a_agent) == []
