"""A vendor's negative call duration must not be able to break metering.

`ExecutionSnapshot.duration_s` is `int | None` with no floor, and both adapters build it
as `int(duration) if isinstance(duration, int | float) else None`
(`apps/api/engine/bolna.py`, `apps/api/engine/cartesia.py`). A `-1` "unknown" sentinel, or
a duration derived from two clocks that disagree, therefore arrives in `_meter` as a real
quantity and is multiplied through the whole money path.

THE DEFECT. Taking seconds AWAY makes `month_increment`'s `after < before`, so the call's
contribution to `spend_state.billed_inr` is NEGATIVE — the one input to that counter that
is not monotone, which is why the column's `>= 0` CHECK had never been reachable. And the
accumulated total staying positive does not save it: PostgreSQL evaluates a CHECK against
the row an `INSERT ... ON CONFLICT DO UPDATE` PROPOSES, before the conflict is arbitrated.
Measured against this pg16 rather than recalled:

    INSERT INTO t VALUES (1, -5) ON CONFLICT (k) DO UPDATE SET v = t.v + EXCLUDED.v;
    ERROR:  new row for relation "t" violates check constraint "t_v_check"
    DETAIL:  Failing row contains (1, -5).

So the whole metering transaction aborted — no usage rows, no wallet debit, no counters —
and every ARQ retry hit the same constraint, so the call could never settle on its own.
Measured before the fix, on a tenant with ₹120.96 already accrued for the month:

    _meter(..., duration_s=-1)
      -> psycopg.errors.CheckViolation: new row for relation "spend_state" violates
         check constraint "ck_spend_state_billed_inr_nonnegative"

THE FIX is `pipeline._billable_seconds`: a negative duration is clamped to zero and
announced. Zero is the already-designed answer for "real leg cost, no countable seconds"
— `_unit_price` keeps the leg whole at `qty <= 0` — so the call still meters, its costs
still reach the margin panel, and the client is billed for no minutes, which is the
client-favourable direction.

Run: uv run pytest -q tests/negative_duration_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.service import tier_usage, usage_summary
from apps.api.db.session import tenant_session
from apps.workers.pipeline import _meter
from sqlalchemy import text
from tests.spend_caps_test import _bill, _call_row, _plan, _snapshot, _spend_state, _tenant


async def _premium_voice(tenant_id: UUID, agent_id: UUID) -> None:
    """Metering reads the agent's configured voice to pick the rung (`billing/rates.py`),
    so the fixture pins one rather than leaving the call `unproven`."""
    from apps.api.agents.voices import CATALOG

    premium = next(v.id for v in CATALOG if v.tier == "premium")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET tts_voice = :v WHERE id = :i"),
            {"v": premium, "i": agent_id},
        )


async def test_a_negative_duration_does_not_abort_the_meter() -> None:
    """The call meters, the counters do not go backwards, and nothing raises.

    The month is deliberately NOT empty first: the abort this pins is the one that fires
    even though the accumulated total would have stayed comfortably positive, which is
    the half of it that is about `ON CONFLICT` rather than about arithmetic.
    """
    tenant_id, agent_id, _ref = await _tenant(f"neg{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    await _premium_voice(tenant_id, agent_id)
    now = datetime.now(UTC)
    await _bill(tenant_id, agent_id, seconds=600, spend="20.0000", ended=now)
    _month, minutes_before, spend_before, _capped, billed_before = await _spend_state(tenant_id)
    assert billed_before > 0, "the fixture must leave real money on the counter"

    call_id = await _call_row(tenant_id, agent_id)
    wrote = await _meter(tenant_id, call_id, _snapshot(seconds=-1, spend="1.0000", ended=now))

    assert wrote > 0, "a call the engine priced must still leave usage rows"
    _month, minutes_after, spend_after, _capped, billed_after = await _spend_state(tenant_id)
    assert minutes_after == minutes_before, "a duration we cannot trust buys no minutes"
    assert billed_after == billed_before, "and charges the client nothing"
    assert spend_after == spend_before + Decimal("1.0000"), (
        "our own supplier cost is real and still lands: the vendor charged us for this call"
    )


async def test_the_negative_duration_is_announced_and_not_swallowed() -> None:
    """An adapter and a vendor disagreeing about a payload is an alert, not a log line —
    the same treatment `call_billable_without_cost` gets, from the same failure stage."""
    fired: list[tuple[str, str, dict[str, Any]]] = []

    def _capture(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        fired.append((stage, code, ids))

    tenant_id, agent_id, _ref = await _tenant(f"nga{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    await _premium_voice(tenant_id, agent_id)
    call_id = await _call_row(tenant_id, agent_id)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("apps.workers.pipeline.alert", _capture)
        await _meter(
            tenant_id,
            call_id,
            _snapshot(seconds=-1, spend="1.0000", ended=datetime.now(UTC)),
        )

    codes = [code for _stage, code, _ids in fired]
    assert "call_duration_negative" in codes, f"nothing announced it: {codes}"
    (stage, _code, ids) = next(item for item in fired if item[1] == "call_duration_negative")
    assert stage == "WORKER_TERMINAL"
    assert ids["call_id"] == str(call_id) and ids["tenant_id"] == str(tenant_id)
    # The value itself, so an operator can tell a sentinel apart from a clock-skew
    # subtraction. It is not PII and it is the one fact that decides which it is.
    assert ids["duration_s"] == "-1"


async def test_the_panels_still_render_after_one() -> None:
    """`allocate_paise` refuses a breakdown whose parts cannot add to its total, so a
    negative bucket is not merely a wrong number on the usage panel — it is a 500 on it.
    Both readers are exercised because they allocate the same minutes."""
    tenant_id, agent_id, _ref = await _tenant(f"ngp{uuid.uuid4().hex[:6]}")
    await _plan(tenant_id, included_min=0)
    await _premium_voice(tenant_id, agent_id)
    now = datetime.now(UTC)
    await _bill(tenant_id, agent_id, seconds=307, spend="10.0000", ended=now)
    call_id = await _call_row(tenant_id, agent_id)
    await _meter(tenant_id, call_id, _snapshot(seconds=-1, spend="1.0000", ended=now))

    async with tenant_session(tenant_id) as session:
        summary = await usage_summary(session, tenant_id=tenant_id)
        tiers = await tier_usage(session, tenant_id=tenant_id)

    assert summary["minutes_used"] == Decimal("5.12"), "307 seconds, and nothing negative"
    assert (
        tiers["minutes_premium"] + tiers["minutes_value"] + tiers["minutes_unattributed"]
        == summary["minutes_used"]
    )
