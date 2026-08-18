"""An operator TIGHTENING a client's ceiling stops the next dial, not the dial after next.

`plans.hard_cap_min` / `hard_cap_spend` are written by exactly one function,
`billing/terms.py::record_terms`, and they are half of the ceiling `over_cap_sql`
enforces — `LEAST(hard_cap_*, client_cap_*)`. The other half is the client's own stop
button, and `billing/caps.py::apply_client_caps` re-derives `spend_state.capped` in the
same transaction as the write, arguing why in as many words: "a cap accepted whose gate is
not armed is a cap that does nothing until the next call meters, and for an outbound-only
tenant the next call is exactly what the cap was supposed to stop."

THE DEFECT. The ADMIN half did not do that. `record_terms` inserted the dated row and left
the flag alone, and `compliance.check_dispatch` reads `spend_state.capped` and nothing
else — so the ceiling an operator typed mid-incident bound nothing until some call
happened to complete and meter. Measured on this tree before the fix: ₹480 already billed
for the month, operator writes `hard_cap_spend = ₹100`, `capped` stays `false` and the
gate still returns `allowed=True`.

THE FIX is that `record_terms` calls the same `recompute_capped` the other two writers
call, under the same `lock_tenant_spend_state`, taken before the `plans` read the write
depends on. Three writers of the flag, one definition of "over cap".

Run: uv run pytest -q tests/admin_cap_arms_the_gate_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from apps.api.billing import terms as billing_terms
from apps.api.compliance.service import DispatchDecision, check_dispatch
from apps.api.db.session import tenant_session
from tests.spend_caps_test import _bill, _plan, _spend_state, _tenant

#: The rate `tests/spend_caps_test._plan` quotes, so the rupees below are derivable.
_OVERAGE_RATE = Decimal("8.0000")


async def _gate(tenant_id: UUID, agent_id: UUID) -> DispatchDecision:
    """The only thing that can actually stop a dial. A fresh number each time, so a DNC
    row another suite added can never be what refuses us."""
    phone = f"+9199{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )


async def _write_terms(
    tenant_id: UUID, *, cap_spend: Decimal | None = None, cap_min: int | None = None
) -> billing_terms.TermsWriteResult:
    async with tenant_session(tenant_id) as session:
        return await billing_terms.record_terms(
            session,
            tenant_id=tenant_id,
            terms=billing_terms.CommercialTerms(
                monthly_fee=Decimal("9999.00"),
                included_min=0,
                overage_rate=_OVERAGE_RATE,
                hard_cap_spend=cap_spend,
                hard_cap_min=cap_min,
                concurrency_ceiling=10,
            ),
        )


async def test_tightening_the_rupee_ceiling_stops_the_next_dial() -> None:
    tenant_id, agent_id, _ref = await _tenant(f"acs{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    # Sixty minutes at ₹8 = ₹480 of the client's own money, already billed.
    await _bill(tenant_id, agent_id, seconds=3600, spend="120.0000", ended=datetime.now(UTC))
    assert (await _gate(tenant_id, agent_id)).allowed, "nothing is capped yet"

    result = await _write_terms(tenant_id, cap_spend=Decimal("100.0000"))

    assert result.changed
    assert result.capped_now, "the write must report that it stopped this client's calling"
    _month, _minutes, _spend, capped, billed = await _spend_state(tenant_id)
    assert billed == Decimal("480.0000")
    assert capped, "the flag the gate reads must be armed by the write that lowered the ceiling"
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == "spend_cap", (
        f"the ceiling was accepted and the gate still allows the dial: {decision}"
    )


async def test_tightening_the_minute_ceiling_stops_the_next_dial() -> None:
    """The other ceiling, because `over_cap_sql` is a disjunction and a fix that only
    re-derived one of them would pass the test above and still leave a runaway running."""
    tenant_id, agent_id, _ref = await _tenant(f"acm{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    await _bill(tenant_id, agent_id, seconds=3600, spend="120.0000", ended=datetime.now(UTC))

    result = await _write_terms(tenant_id, cap_min=30)

    assert result.capped_now
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == "spend_cap", decision


async def test_a_ceiling_the_tenant_is_still_inside_leaves_the_gate_open() -> None:
    """The recompute must DERIVE the flag rather than set it: an ordinary onboarding
    write that happens to state a first ceiling must not stop a client who is nowhere
    near it. This is the direction that would be expensive to get wrong."""
    tenant_id, agent_id, _ref = await _tenant(f"aco{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    await _bill(tenant_id, agent_id, seconds=600, spend="20.0000", ended=datetime.now(UTC))

    result = await _write_terms(tenant_id, cap_spend=Decimal("5000.0000"))

    assert result.changed and not result.capped_now
    _month, _minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert not capped
    assert (await _gate(tenant_id, agent_id)).allowed


async def test_re_posting_the_same_terms_writes_nothing_and_reports_nothing() -> None:
    """`record_terms` is idempotent on identical terms, and the recompute must not turn
    a no-op into a write — the reason it sits after the `_same_terms` early return."""
    tenant_id, _agent_id, _ref = await _tenant(f"acn{uuid.uuid4().hex[:6]}")
    first = await _write_terms(tenant_id, cap_spend=Decimal("5000.0000"))
    again = await _write_terms(tenant_id, cap_spend=Decimal("5000.0000"))

    assert first.changed and not again.changed
    assert again.plan_id == first.plan_id
    assert not again.capped_now
