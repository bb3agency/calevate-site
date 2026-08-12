"""The client's own spend cap: stricter-wins, immediate, and never looser than the plan.

`plans.hard_cap_min` / `hard_cap_spend` are admin-owned and had no client surface at
all, which SURFACES §2b:89 and D-34's R-11 both say is wrong. `plans.client_cap_min` /
`client_cap_spend` (migration b1d5c8e73f04) are the other half, and every claim this
slice makes is asserted here rather than described:

1. **The effective cap is the STRICTER of the two**, with NULL on either side meaning
   "no constraint from this side" — and the assertion ends at the GATE, not at the
   column, because `compliance.check_dispatch` reading `spend_state.capped` is the only
   thing that can actually stop a dial (the discipline `tests/spend_caps_test.py`
   established for the admin ceiling).
2. **A client cap looser than the admin's is REFUSED, not clamped.** RFC-9457: the
   machine code is the LAST SEGMENT of `type`, and there is no `code` key.
3. **A cap below what has already been spent binds IMMEDIATELY.** This is the product
   decision `billing/caps.py` defends: the client's next dial is refused, not the dial
   after the next call happens to meter. Its converse matters just as much — raising the
   cap back up releases the gate in the same breath, so a mistaken stop is one click to
   undo rather than a support ticket.
4. **Inbound is untouched.** The gate is outbound-only, so a client cannot take their
   own receptionist off the air with this control — which is half of why (3) is safe.
5. **Hard rule 1.** A second tenant can neither read nor write these columns, asserted
   by reading and writing them under the other tenant's RLS session and requiring zero
   rows. That is the cross-tenant test migration b1d5c8e73f04 ships with.
6. **Hard rule 7.** A JSON float is refused at the boundary; money leaves as a string.

CONCURRENCY: every test mints its own tenant and touches no global row, so this file
can run beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.cap_routes import CapsIn, get_caps, set_caps
from apps.api.billing.caps import effective_cap, read_caps
from apps.api.billing.service import current_billing_month
from apps.api.compliance.service import check_dispatch
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from pydantic import ValidationError
from sqlalchemy import text
from tests.spend_caps_test import THIS_MONTH, _bill, _gate, _tenant


@pytest.fixture(autouse=True)
def _gate_reaches_the_spend_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same two pins `tests/spend_caps_test.py` explains: calling hours is checked
    AFTER the spend cap (so at 22:00 IST it would mask every "not capped" assertion) and
    the big red switch is global state a concurrent suite can flip. Neither weakens a
    refusal case — those assert `rule == "spend_cap"`, which no stub can manufacture."""
    from apps.api.core.loadshed import PlatformStatus

    async def _running(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=False)

    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _running)
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)


def _principal(tenant_id: UUID) -> Principal:
    return Principal(
        realm="client",
        user_id=uuid.uuid4(),
        clerk_user_id="u",
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


async def _admin_plan(tenant_id: UUID, *, cap_min: int | None, cap_spend: str | None) -> None:
    """One plan row carrying only the ADMIN ceilings — the state every existing tenant
    is in before a client ever touches their own cap."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "hard_cap_min, hard_cap_spend, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, 9999.00, 100, 8.0000, :cmin, :cspend, 10, now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "cmin": cap_min,
                "cspend": Decimal(cap_spend) if cap_spend is not None else None,
            },
        )


async def _put(tenant_id: UUID, *, minutes: int | None, spend: str | None):  # type: ignore[no-untyped-def]
    async with tenant_session(tenant_id) as session:
        return await set_caps(
            CapsIn(
                cap_minutes=minutes,
                cap_spend_inr=Decimal(spend) if spend is not None else None,
            ),
            session,
            _principal(tenant_id),
        )


# ============================================================================
# 1. The stricter of the two wins
# ============================================================================


def test_the_effective_cap_is_the_stricter_and_null_constrains_nothing() -> None:
    """The identity the SQL `LEAST` implements, pinned in Python so the two cannot
    drift: NULL on either side is "no constraint from this side", NULL on both is no
    cap at all, and otherwise the smaller number wins whichever side it came from."""
    assert effective_cap(None, None) is None
    assert effective_cap(500, None) == Decimal("500")
    assert effective_cap(None, 120) == Decimal("120")
    assert effective_cap(500, 120) == Decimal("120"), "the client's is stricter"
    assert effective_cap(120, 500) == Decimal("120"), "the admin's is stricter"


async def test_a_client_cap_stops_a_dial_the_admin_ceiling_would_have_allowed() -> None:
    """The whole point of the feature, asserted at the gate. 200 admin minutes leaves
    plenty of room after 120 metered minutes; a client cap of 100 does not."""
    tenant_id, agent_id, _ = await _tenant("clientcap")
    await _admin_plan(tenant_id, cap_min=200, cap_spend=None)
    await _bill(tenant_id, agent_id, seconds=7200, spend="500.00", ended=THIS_MONTH)

    allowed = await _gate(tenant_id, agent_id)
    assert allowed.allowed is True, "120 of 200 admin minutes is not a cap"

    result = await _put(tenant_id, minutes=100, spend=None)
    assert result.effective_cap_minutes == 100, "the client's 100 beats the admin's 200"
    assert result.plan_cap_minutes == 200, "the admin's ceiling is still visible"
    assert result.capped is True

    refused = await _gate(tenant_id, agent_id)
    assert refused.allowed is False
    assert refused.rule == "spend_cap"


async def test_the_admin_ceiling_still_binds_when_the_client_sets_a_looser_one() -> None:
    """A client cap BELOW the admin's is the interesting direction, but the other one
    must not quietly widen anything — and the only way to be sure is to have the client
    set a cap that is stricter on one axis while the admin's binds on the other."""
    tenant_id, agent_id, _ = await _tenant("adminwins")
    await _admin_plan(tenant_id, cap_min=100, cap_spend=None)
    await _put(tenant_id, minutes=None, spend="1000.00")
    await _bill(tenant_id, agent_id, seconds=7200, spend="500.00", ended=THIS_MONTH)

    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is False and decision.rule == "spend_cap", (
        "120 minutes is over the admin's 100 even though the client's rupee cap is miles away"
    )


# ============================================================================
# 2. A client may never loosen the plan's ceiling
# ============================================================================


async def test_a_client_cap_looser_than_the_plans_is_refused_not_clamped() -> None:
    tenant_id, _agent_id, _ = await _tenant("looser")
    await _admin_plan(tenant_id, cap_min=200, cap_spend="5000.00")

    with pytest.raises(ProblemError) as raised:
        await _put(tenant_id, minutes=900, spend=None)
    problem = raised.value.as_problem("/v1/billing/caps")
    assert problem["type"].rsplit("/", 1)[-1] == "client_cap_exceeds_plan_cap"
    assert "code" not in problem, "RFC-9457 carries the machine code in `type`"

    with pytest.raises(ProblemError):
        await _put(tenant_id, minutes=None, spend="9000.00")

    async with tenant_session(tenant_id) as session:
        caps = await read_caps(session, tenant_id=tenant_id)
    assert caps.client_cap_min is None and caps.client_cap_spend is None, (
        "a refused write must leave nothing behind — not a clamped value, not a partial one"
    )


async def test_clearing_a_client_cap_returns_to_the_plans_ceiling_and_is_not_a_raise() -> None:
    """Clearing is allowed even when the plan's ceiling is looser than what the client
    had: they are returning to where they started, not raising past the admin."""
    tenant_id, _agent_id, _ = await _tenant("clearcap")
    await _admin_plan(tenant_id, cap_min=200, cap_spend=None)
    await _put(tenant_id, minutes=50, spend=None)

    cleared = await _put(tenant_id, minutes=None, spend=None)
    assert cleared.client_cap_minutes is None
    assert cleared.effective_cap_minutes == 200, "back on the admin's ceiling, not unlimited"


async def test_a_tenant_with_no_plan_row_may_still_set_a_cap() -> None:
    """Nothing in the codebase creates a `plans` row, so a self-serve tenant has none —
    and "you cannot limit your spending until an operator writes you a plan" is not an
    acceptable answer for the surface R-11 requires."""
    tenant_id, agent_id, _ = await _tenant("noplan")
    result = await _put(tenant_id, minutes=10, spend=None)
    assert result.effective_cap_minutes == 10
    assert result.plan_cap_minutes is None

    await _bill(tenant_id, agent_id, seconds=1200, spend="80.00", ended=THIS_MONTH)
    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is False and decision.rule == "spend_cap"


# ============================================================================
# 3. Below-current-spend binds immediately, and so does releasing it
# ============================================================================


async def test_a_cap_below_this_months_spend_stops_the_next_dial_not_the_next_meter() -> None:
    """The decision `billing/caps.py` defends. Without the recompute in that write, the
    flag would sit at `false` until some call completed — and for an outbound-only
    tenant the next call is exactly the one the cap was set to prevent."""
    tenant_id, agent_id, _ = await _tenant("panic")
    await _bill(tenant_id, agent_id, seconds=7200, spend="500.00", ended=THIS_MONTH)
    assert (await _gate(tenant_id, agent_id)).allowed is True

    result = await _put(tenant_id, minutes=None, spend="100.00")
    assert result.capped is True, "the response tells the client they have stopped themselves"

    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is False and decision.rule == "spend_cap", (
        "no call metered in between — the write itself had to arm the gate"
    )


async def test_raising_the_cap_back_releases_the_gate_in_the_same_breath() -> None:
    """The recompute is symmetric on purpose: a mistaken stop costs one more click. A
    one-way arm would leave a client stopped until a call they cannot place completes."""
    tenant_id, agent_id, _ = await _tenant("undo")
    await _bill(tenant_id, agent_id, seconds=7200, spend="500.00", ended=THIS_MONTH)
    await _put(tenant_id, minutes=None, spend="100.00")
    assert (await _gate(tenant_id, agent_id)).allowed is False

    released = await _put(tenant_id, minutes=None, spend="5000.00")
    assert released.capped is False
    assert (await _gate(tenant_id, agent_id)).allowed is True


async def test_an_inbound_agent_is_never_affected_by_a_client_cap() -> None:
    """Half of why an immediate hard stop is safe: the gate is outbound-only, so a
    client cannot take their own receptionist off the air. `_tenant` returns the inbound
    agent's engine ref, and the inbound agent is refused by an EARLIER rule than the
    spend cap — which is the assertion: the refusal reason is never `spend_cap`."""
    tenant_id, _outbound_agent_id, agent_ref = await _tenant("inbound")
    await _bill(tenant_id, _outbound_agent_id, seconds=7200, spend="500.00", ended=THIS_MONTH)
    await _put(tenant_id, minutes=None, spend="1.00")

    async with tenant_session(tenant_id) as session:
        inbound_id = (
            await session.execute(
                text("SELECT id FROM agents WHERE tenant_id = :t AND engine_agent_ref = :r"),
                {"t": tenant_id, "r": agent_ref},
            )
        ).scalar()
        decision = await check_dispatch(
            session,
            tenant_id=tenant_id,
            agent_id=UUID(str(inbound_id)),
            phone_e164=f"+9199{uuid.uuid4().int % 100000000:08d}",
        )
    assert decision.rule != "spend_cap", (
        "an inbound agent is refused for being inbound, not for a cap that does not apply to it"
    )


async def test_the_read_route_reports_all_three_answers_and_the_current_month() -> None:
    tenant_id, agent_id, _ = await _tenant("readcaps")
    await _admin_plan(tenant_id, cap_min=200, cap_spend="5000.00")
    await _put(tenant_id, minutes=150, spend=None)
    await _bill(tenant_id, agent_id, seconds=600, spend="42.50", ended=THIS_MONTH)

    async with tenant_session(tenant_id) as session:
        view = await get_caps(session, _principal(tenant_id))

    assert view.month == current_billing_month()
    assert (view.plan_cap_minutes, view.client_cap_minutes, view.effective_cap_minutes) == (
        200,
        150,
        150,
    )
    assert view.plan_cap_spend_inr == "5000.00"
    assert view.client_cap_spend_inr is None
    assert view.effective_cap_spend_inr == "5000.00"
    assert view.minutes_used == "10.00" and view.spend_used_inr == "42.50"
    # Money is an exact decimal STRING, never a JSON float (hard rule 7).
    assert isinstance(view.spend_used_inr, str)


# ============================================================================
# Boundary + hard rule 7
# ============================================================================


def test_a_json_float_is_refused_at_the_boundary() -> None:
    """`2500.10` as a JSON number has already been through a binary float by the time
    we see it — the identical guard both top-up routes carry."""
    with pytest.raises(ValidationError):
        CapsIn(cap_spend_inr=2500.10)  # type: ignore[arg-type]
    assert CapsIn(cap_spend_inr=Decimal("2500.10")).cap_spend_inr == Decimal("2500.10")


def test_a_negative_cap_is_refused_and_zero_is_not() -> None:
    """Zero is "stop my outbound calling now", which is the emergency the control exists
    for. Negative is a typo that would read as a stricter cap."""
    assert CapsIn(cap_minutes=0).cap_minutes == 0
    with pytest.raises(ValidationError):
        CapsIn(cap_minutes=-1)
    with pytest.raises(ValidationError):
        CapsIn(cap_spend_inr=Decimal("-1.00"))


async def test_a_zero_cap_stops_outbound_for_a_tenant_that_has_spent_nothing() -> None:
    """`>=` on the ceiling means zero minutes used already meets a zero cap. A client
    who says "stop" before any call this month must be stopped, not stopped-once-they-
    have-spent-something."""
    tenant_id, agent_id, _ = await _tenant("zerocap")
    await _bill(tenant_id, agent_id, seconds=60, spend="8.00", ended=THIS_MONTH)
    result = await _put(tenant_id, minutes=0, spend=None)
    assert result.capped is True
    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"


# ============================================================================
# Hard rule 1 — the cross-tenant zero-rows test migration b1d5c8e73f04 ships with
# ============================================================================


async def test_a_second_tenant_can_neither_read_nor_write_another_tenants_caps() -> None:
    """`plans` carries its FORCEd `tenant_isolation` policy and the three new columns
    inherit it — a column is not a separate security object. Asserted by reading AND
    writing them from another tenant's session and requiring zero rows both ways."""
    victim, _agent, _ = await _tenant("victim")
    intruder, _agent2, _ = await _tenant("intruder")
    await _admin_plan(victim, cap_min=200, cap_spend="5000.00")
    await _put(victim, minutes=42, spend="99.00")

    async with tenant_session(intruder) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT client_cap_min, client_cap_spend, overage_rate_value "
                    "FROM plans WHERE tenant_id = :t"
                ),
                {"t": victim},
            )
        ).all()
        assert rows == [], "another tenant's plan row must be invisible"

        written = await session.execute(
            text(
                "UPDATE plans SET client_cap_min = 999999, overage_rate_value = 1.0000 "
                "WHERE tenant_id = :t"
            ),
            {"t": victim},
        )
        assert written.rowcount == 0, "and unwritable"

    async with tenant_session(victim) as session:
        caps = await read_caps(session, tenant_id=victim)
    assert caps.client_cap_min == 42, "the victim's own value is untouched"
