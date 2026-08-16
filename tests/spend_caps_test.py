"""Spend caps: the plan ceilings the compliance gate is supposed to enforce (TRD §9).

`plans.hard_cap_min` and `plans.hard_cap_spend` are shown in the client usage panel and
in the admin console, but the ONLY thing that can stop a dial is `spend_state.capped` —
`compliance.service.check_dispatch` reads that boolean and nothing else. So every test
here ends at the gate rather than at the column: asserting `capped is true` alone would
still pass in a world where the gate ignored it, and the claim being made is "this
tenant cannot place another call", not "this row has a flag set".

Two failures these were written against:

- **Nothing ever set `capped`.** The pipeline's `spend_state` upsert wrote a literal
  `false` on insert and never touched the column on update, so both ceilings were
  reported by the panel and enforced by nothing.
- **The month rollover carried the flag.** The upsert resets `minutes_used`/`spend_used`
  when the month changes but left `capped` as it was, so a tenant capped in July stayed
  capped in August forever.

Scope discipline (other suites share this database): every test creates its own tenant
and asserts only on rows it created. Nothing here counts globally.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.billing.service import current_billing_month
from apps.api.compliance.service import DispatchDecision, check_dispatch
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.workers.pipeline import _meter, ingest_engine_event, run_post_call_pipeline
from calevate_shared.engine import CostBreakdown, ExecutionSnapshot
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant


@pytest.fixture(autouse=True)
def _stub_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    """Same substitution the smoke test makes: a bucket is an environment concern."""

    async def _fake_copy(*, source_url: str, tenant_id: UUID, call_id: UUID) -> str:
        return f"recordings/{tenant_id}/{call_id}.wav"

    monkeypatch.setattr("apps.workers.pipeline.copy_recording", _fake_copy)


@pytest.fixture(autouse=True)
def _gate_reaches_the_spend_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the two checks that sit AROUND the spend cap in `check_dispatch` and would
    otherwise make these tests depend on wall-clock time and on what another suite did
    to the shared database.

    - calling hours (9-21 IST) is checked AFTER the spend cap, so it can only mask an
      ALLOWED result — a suite run at 22:00 IST would see every "not capped" assertion
      fail for a reason that has nothing to do with caps.
    - the big red switch is checked BEFORE it, and it is global platform state that a
      concurrently running suite can flip.

    Neither is weakened for the refusal cases: those assert `rule == "spend_cap"`, which
    no amount of stubbing here can manufacture.
    """
    from apps.api.core.loadshed import PlatformStatus

    async def _running(*, force_refresh: bool = False) -> PlatformStatus:
        return PlatformStatus(mode="normal", outbound_halted=False)

    monkeypatch.setattr("apps.api.compliance.service.get_platform_status", _running)
    monkeypatch.setattr("apps.api.compliance.service.within_calling_hours", lambda *a, **k: True)


# --- fixtures -----------------------------------------------------------------


async def _tenant(label: str) -> tuple[UUID, UUID, str]:
    """A provisioned tenant with an engine-routed inbound agent (so the real pipeline
    can run for it) plus a live OUTBOUND agent, which is what `check_dispatch` needs to
    reach the spend-cap check at all — an inbound agent is refused two rules earlier.

    Returns (tenant_id, outbound_agent_id, engine_agent_ref).
    """
    agent_ref = f"fakeagent_{label}_{uuid.uuid4().hex[:8]}"
    tenant_id, _inbound_agent_id = await _seed_tenant(agent_ref)
    outbound_agent_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, "
                "'Follow-up caller', 'outbound', 'Idi AI assistant. Call record avutundi.', "
                "'live', 'fake', :ref, now(), now())"
            ),
            {"id": outbound_agent_id, "tid": tenant_id, "ref": f"{agent_ref}_out"},
        )
    return tenant_id, outbound_agent_id, agent_ref


#: The overage rate every plan below quotes. Named because the rupee-ceiling tests now
#: have to reason in the CLIENT's currency: the cap is compared against
#: `spend_state.billed_inr`, which the meter accrues at this rate on the minutes past
#: `included_min` (P1.3). Before that it was compared against our supplier cost, so those
#: tests could pick any ceiling and any `spend=` and the two never had to relate.
_OVERAGE_RATE = Decimal("8.0000")


async def _plan(
    tenant_id: UUID,
    *,
    cap_min: int | None = None,
    cap_spend: str | None = None,
    age_days: int = 0,
    included_min: int = 100,
) -> None:
    """One plan row. `age_days` backdates `created_at`, because `plans` is
    effective-dated and a tenant that changed plan has several rows — newest wins.

    `included_min` defaults to the allowance every other test here wants and is set to 0
    by the rupee-ceiling tests: a minute inside the allowance is a minute the client has
    already paid a retainer for, so it accrues nothing towards their cap, and a rupee
    ceiling can only be exercised by minutes that are actually charged for."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO plans (id, tenant_id, monthly_fee, included_min, overage_rate, "
                "hard_cap_min, hard_cap_spend, concurrency_ceiling, created_at, updated_at) "
                "VALUES (:i, :t, 9999.00, :inc, :rate, :cmin, :cspend, 10, "
                "now() - CAST(:age AS interval), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "inc": included_min,
                "rate": _OVERAGE_RATE,
                "cmin": cap_min,
                "cspend": Decimal(cap_spend) if cap_spend is not None else None,
                "age": f"{age_days} days",
            },
        )


async def _call_row(tenant_id: UUID, agent_id: UUID) -> UUID:
    """A completed outbound call row for `usage_events` to hang off."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'outbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    return call_id


def _snapshot(*, seconds: int, spend: str, ended: datetime) -> ExecutionSnapshot:
    """A completed call that cost exactly `spend` — Decimal, never float (hard rule 7)."""
    total = Decimal(spend)
    return ExecutionSnapshot(
        engine_call_id=f"exec_{uuid.uuid4().hex[:12]}",
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        ended_at=ended,
        duration_s=seconds,
        cost=CostBreakdown(
            total_inr=total,
            platform_inr=total,
            source_currency="INR",
            source_amount=total,
            fx_rate=Decimal("1"),
        ),
    )


async def _bill(
    tenant_id: UUID, agent_id: UUID, *, seconds: int, spend: str, ended: datetime
) -> None:
    """Meter one call, exactly as the post-call pipeline's step 5 does."""
    call_id = await _call_row(tenant_id, agent_id)
    await _meter(tenant_id, call_id, _snapshot(seconds=seconds, spend=spend, ended=ended))


async def _spend_state(tenant_id: UUID) -> tuple[str, Decimal, Decimal, bool, Decimal]:
    """`(month, minutes_used, spend_used, capped, billed_inr)`.

    Both money columns, because they are different facts: `spend_used` is the engine's
    charge to US and `billed_inr` is what the client owes at their own rate. The cap is
    compared against the second (P1.3), so a test that reads only the first can no longer
    explain why the flag is where it is."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT month, minutes_used, spend_used, capped, billed_inr "
                    "FROM spend_state WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
    assert row is not None, "metering must leave a spend_state row"
    return str(row[0]), row[1], row[2], bool(row[3]), row[4]


async def _gate(tenant_id: UUID, agent_id: UUID) -> DispatchDecision:
    """The only thing that can actually stop a dial. A fresh number per call, so a DNC
    entry another suite added can never be what refuses us."""
    phone = f"+9199{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )


def _mid_month(offset: int) -> datetime:
    """Noon UTC in the middle of the current IST billing month, shifted by `offset`.

    RELATIVE, not hard-coded. `compliance.spend_capped` compares the metered month with
    the CURRENT one — a cap belonging to a closed month is not a cap, because the meter
    is the only writer and a capped tenant meters nothing (see
    `tests/spend_cap_staleness_test.py` for the deadlock that rule prevents). Fixed
    dates would therefore make these tests assert the deadlock case in every month but
    the one they were written in.
    """
    year, month = (int(part) for part in current_billing_month().split("-"))
    shifted = month + offset
    return datetime(year + (shifted - 1) // 12, (shifted - 1) % 12 + 1, 15, 12, 0, tzinfo=UTC)


LAST_MONTH = _mid_month(-1)
THIS_MONTH = _mid_month(0)


# --- the minute ceiling -------------------------------------------------------


async def test_crossing_the_minute_cap_refuses_the_next_dial() -> None:
    """`hard_cap_min` is the ceiling the managed usage panel counts down from
    ("minutes left"). Reaching it has to stop the dialling, or the number on the panel
    is decoration."""
    tenant_id, agent_id, _ = await _tenant("capmin")
    await _plan(tenant_id, cap_min=2)

    open_gate = await _gate(tenant_id, agent_id)
    assert open_gate.allowed, f"a fresh tenant must be dialable: {open_gate.rule}"

    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=THIS_MONTH)

    month, minutes, spend, capped, _billed = await _spend_state(tenant_id)
    assert minutes == Decimal("3.0000")
    assert capped is True, "3 minutes used against a 2-minute cap is capped"

    decision = await _gate(tenant_id, agent_id)
    assert decision.allowed is False
    assert decision.rule == "spend_cap", f"the gate must refuse on the cap, got {decision.rule}"
    assert month == current_billing_month()
    assert isinstance(spend, Decimal), "money is NUMERIC end to end (hard rule 7)"


async def test_minutes_accumulate_across_calls_before_the_cap_bites() -> None:
    """The cap is a MONTHLY total, not a per-call one: three short calls that add up to
    the ceiling must close the gate just as one long call does."""
    tenant_id, agent_id, _ = await _tenant("capaccum")
    await _plan(tenant_id, cap_min=5)

    for _ in range(2):
        await _bill(tenant_id, agent_id, seconds=120, spend="8.0000", ended=THIS_MONTH)
    _month, minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert minutes == Decimal("4.0000")
    assert capped is False, "4 minutes against a 5-minute cap is still under"
    assert (await _gate(tenant_id, agent_id)).allowed

    await _bill(tenant_id, agent_id, seconds=120, spend="8.0000", ended=THIS_MONTH)
    _month, minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert minutes == Decimal("6.0000")
    assert capped is True
    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"


# --- the rupee ceiling --------------------------------------------------------


async def test_crossing_the_spend_cap_refuses_the_next_dial() -> None:
    """`hard_cap_spend` had no reader at ALL — not the gate, not the panel. A tenant on
    a rupee ceiling with no minute ceiling was completely unprotected."""
    tenant_id, agent_id, _ = await _tenant("capspend")
    # No allowance, so every metered minute is charged and the ceiling is reachable.
    # ₹12 sits between one minute of overage (₹8) and two (₹16).
    await _plan(tenant_id, cap_spend="12.0000", included_min=0)

    await _bill(tenant_id, agent_id, seconds=60, spend="49.5000", ended=THIS_MONTH)
    assert (await _gate(tenant_id, agent_id)).allowed, "under the rupee ceiling"

    await _bill(tenant_id, agent_id, seconds=60, spend="1.0000", ended=THIS_MONTH)

    _month, _minutes, spend, capped, billed = await _spend_state(tenant_id)
    # Both columns, because the whole point of P1.3 is that they are different numbers:
    # `spend` is what the engine charged US for these two calls and `billed` is what the
    # client owes for the same two minutes. Only the second one is compared to the cap.
    assert spend == Decimal("50.5000")
    assert billed == Decimal("2") * _OVERAGE_RATE
    assert capped is True, "₹16 billed against a ₹12 cap is capped"
    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"


async def test_either_ceiling_alone_is_enough_to_cap() -> None:
    """Both ceilings matter independently: a tenant well inside its minute allowance can
    still be burning money (a long-form agent on an expensive voice), and the reverse."""
    tenant_id, agent_id, _ = await _tenant("capeither")
    # ₹5 is under one minute of overage at ₹8, so one call crosses it.
    await _plan(tenant_id, cap_min=1000, cap_spend="5.0000", included_min=0)

    await _bill(tenant_id, agent_id, seconds=60, spend="25.0000", ended=THIS_MONTH)

    _month, minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert minutes == Decimal("1.0000"), "nowhere near the 1000-minute ceiling"
    assert capped is True, "but well over the ₹5 one"
    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"


# --- the absence of a plan is not a cap ---------------------------------------


async def test_a_tenant_with_no_plan_row_is_never_capped() -> None:
    """A client mid-onboarding has usage before they have a plan row (the usage panel
    already handles that case). Treating a missing ceiling as a ceiling of zero would
    take a brand-new client's phones down on their first call.

    Same rule the campaign dispatcher applies to the same missing row: no plan means the
    default, never a refusal.
    """
    tenant_id, agent_id, _ = await _tenant("noplan")

    await _bill(tenant_id, agent_id, seconds=600_000, spend="99999.0000", ended=THIS_MONTH)

    _month, _minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert capped is False, "no plan row is not a zero cap"
    assert (await _gate(tenant_id, agent_id)).allowed


async def test_a_plan_with_null_ceilings_is_not_a_cap() -> None:
    """HOLDS once the flag is computed: an unlimited plan is a row whose ceilings are
    NULL, and NULL must not compare its way into a refusal."""
    tenant_id, agent_id, _ = await _tenant("nullcaps")
    await _plan(tenant_id, cap_min=None, cap_spend=None)

    await _bill(tenant_id, agent_id, seconds=600_000, spend="99999.0000", ended=THIS_MONTH)

    _month, _minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert capped is False
    assert (await _gate(tenant_id, agent_id)).allowed


# --- effective-dated plans ----------------------------------------------------


async def test_the_newest_plan_row_decides_the_cap() -> None:
    """`plans` is effective-dated, so a tenant that upgraded has several rows. Newest
    wins — the rule invoice.py and the campaign dispatcher already use for this table.
    An upgrade that left the old ceiling in force would cap a paying client early."""
    tenant_id, agent_id, _ = await _tenant("upgrade")
    await _plan(tenant_id, cap_min=2, age_days=60)  # last month's starter plan
    await _plan(tenant_id, cap_min=500, age_days=0)  # today's upgrade

    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=THIS_MONTH)

    _month, _minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert capped is False, "3 minutes is over the OLD 2-minute cap, far under the new one"
    assert (await _gate(tenant_id, agent_id)).allowed


async def test_a_downgrade_lowers_the_cap_that_applies() -> None:
    """The mirror of the upgrade case, and the one that catches an implementation that
    picks the LOOSEST row rather than the newest."""
    tenant_id, agent_id, _ = await _tenant("downgrade")
    await _plan(tenant_id, cap_min=500, age_days=60)
    await _plan(tenant_id, cap_min=2, age_days=0)

    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=THIS_MONTH)

    _month, _minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert capped is True
    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"


# --- the month rollover -------------------------------------------------------


async def test_the_cap_clears_when_the_billing_month_rolls_over() -> None:
    """The counters reset on a new IST billing month; the flag has to reset with them.
    Carrying it forward is a tenant capped in July who can never dial again — the
    counters say 1 minute used and the gate says no."""
    tenant_id, agent_id, _ = await _tenant("rollover")
    await _plan(tenant_id, cap_min=2)

    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=LAST_MONTH)
    _stale_month, _m, _s, armed, _billed = await _spend_state(tenant_id)
    assert armed is True, "the meter arms the flag in the month the usage belongs to"

    # The first call of the new month — inbound calls are never gated, which is how a
    # capped tenant still meters something after the rollover.
    await _bill(tenant_id, agent_id, seconds=60, spend="4.0000", ended=THIS_MONTH)

    month, minutes, spend, capped, _billed = await _spend_state(tenant_id)
    assert month == current_billing_month()
    assert minutes == Decimal("1.0000"), (
        "last month's minutes do not follow the tenant into this one"
    )
    assert spend == Decimal("4.0000")
    assert capped is False, "a new month is a new allowance"
    assert (await _gate(tenant_id, agent_id)).allowed, "this month's calls must go out"


async def test_a_new_month_that_is_already_over_the_cap_stays_capped() -> None:
    """Rollover recomputes the flag, it does not blanket-clear it: one call that blows
    the whole month's allowance on the 1st is capped on the 1st."""
    tenant_id, agent_id, _ = await _tenant("rollover2")
    await _plan(tenant_id, cap_min=2)

    await _bill(tenant_id, agent_id, seconds=180, spend="12.0000", ended=LAST_MONTH)
    await _bill(tenant_id, agent_id, seconds=600, spend="40.0000", ended=THIS_MONTH)

    month, minutes, _spend, capped, _billed = await _spend_state(tenant_id)
    assert month == current_billing_month()
    assert minutes == Decimal("10.0000")
    assert capped is True
    assert (await _gate(tenant_id, agent_id)).rule == "spend_cap"


# --- the real pipeline --------------------------------------------------------


async def test_the_post_call_pipeline_arms_the_cap_end_to_end() -> None:
    """Not `_meter` in isolation: a real engine event through the real pipeline, because
    the cap is only worth anything if the path that actually runs in production sets it.

    The fake engine's sample call is 95 seconds at the verified rate card (~₹6.41), so a
    ₹1 ceiling is one call away from closed.
    """
    tenant_id, outbound_agent_id, agent_ref = await _tenant("e2e")
    await _plan(tenant_id, cap_spend="1.0000", included_min=0)

    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    get_engine().seed_inbound_call(  # type: ignore[attr-defined]
        call_id=execution_id,
        agent_ref=agent_ref,
        from_e164=f"+9198{uuid.uuid4().int % 100000000:08d}",
        to_e164="+911140000000",
    )
    await ingest_engine_event(
        {}, {"engine": "fake", "execution_id": execution_id, "engine_agent_ref": agent_ref}
    )
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).scalar()
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )

    _month, _minutes, spend, capped, _billed = await _spend_state(tenant_id)
    assert spend > Decimal("1.0000"), "the sample call costs more than the ceiling"
    assert capped is True
    decision = await _gate(tenant_id, outbound_agent_id)
    assert decision.allowed is False
    assert decision.rule == "spend_cap"
