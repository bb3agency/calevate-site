"""Trial periods (D-536) — the gate arm, the meter, the boundary, and what is NOT exempt.

The founder: *"any client can be given any no.of days of trail period ... for those no.of
days we don't bill anything to the client and everything is on us and their dashboard
should show the usage and all but should not charge them anything and when the trail is
lifted or over or stopped by calevate the numbers should start form 0 again"*.

The tests that matter most here are the negative ones. A trial is a BILLING state, so the
things it must NOT do — touch a ledger, exempt a compliance gate, keep bypassing the credit
gate after its end date, or charge a client for a minute that was free when they spoke it —
are each pinned separately, because every one of them is a plausible way to build this
wrongly.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.service import get_balance, record_entry
from apps.api.billing.trials import (
    DEFAULT_ERASURE_GRACE_DAYS,
    MAX_TRIAL_DAYS,
    counter_epoch,
    end_trial,
    read_trial,
    start_trial,
    trial_billing_active,
    trial_covers,
)
from apps.api.compliance import service as compliance_service
from apps.api.compliance.service import check_dispatch, credits_exhausted
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import accept_agreements, arm_agent_for_outbound

pytestmark = pytest.mark.asyncio


async def _org(plan_tier: str = "prepaid") -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Trial Clinic",
        slug=f"trial-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET plan_tier = :t WHERE id = :i"),
            {"t": plan_tier, "i": tenant_id},
        )
    return tenant_id, uuid.UUID(str(created["agent_id"]))


# --- the gate arm ------------------------------------------------------------------


async def test_an_empty_wallet_stops_a_prepaid_client_dialling() -> None:
    """The control. Without this the next test proves nothing — a gate that never refused
    would "pass" the trial case for the wrong reason."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        assert await credits_exhausted(session, tenant_id=tenant_id)


async def test_a_trial_bypasses_the_credit_gate_without_a_single_ledger_row() -> None:
    """The founder explicitly refused "grant them credit and let the normal gate honour
    it", because the ledger would then say they were given money nobody gave them. So the
    wallet stays empty, the ledger stays empty, and the gate stops refusing."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)
        assert not await credits_exhausted(session, tenant_id=tenant_id)
        balance = await get_balance(session, tenant_id=tenant_id)
        rows = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert balance.amount_inr == Decimal("0")
    assert rows == 0


async def test_a_trial_past_its_end_date_stops_bypassing_before_any_sweep_runs() -> None:
    """THE PROPERTY THAT MAKES A DAILY SWEEP SAFE. The row still reads `active` — nothing
    has run — and the predicate asks the clock as well as the status, so a late tick cannot
    hand out a day of free calling."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session,
            tenant_id=tenant_id,
            days=1,
            actor_user_id=None,
            at=datetime.now(UTC) - timedelta(days=3),
        )
        trial = await read_trial(session, tenant_id=tenant_id)
        assert trial is not None and trial.status == "active"
        assert not await trial_billing_active(session, tenant_id=tenant_id)
        assert await credits_exhausted(session, tenant_id=tenant_id)


async def test_a_managed_client_is_unaffected_in_both_directions() -> None:
    """A managed client is invoiced against a retainer, so the credit gate never applied to
    them and a trial changes nothing about that. The trial machinery must not become a
    second opinion about which tier pays from a wallet."""
    tenant_id, _ = await _org(plan_tier="managed")
    async with tenant_session(tenant_id) as session:
        assert not await credits_exhausted(session, tenant_id=tenant_id)
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        assert not await credits_exhausted(session, tenant_id=tenant_id)


# --- and NOTHING else is exempt -----------------------------------------------------


async def test_a_trial_is_not_a_compliance_exemption() -> None:
    """ONLY the credit gate. A client on a trial with no DLT paperwork is still refused,
    and the refusal is a compliance one — if this ever comes back `allowed=True` the
    feature has become a TRAI violation with a friendly name."""
    tenant_id, agent_id = await _org()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=30, actor_user_id=None)
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000001"
        )
    assert not decision.allowed
    # Whatever the first unmet gate is, it must not be the money one — that is the only
    # gate a trial is allowed to answer.
    assert decision.rule != "no_credits"


async def test_a_trial_does_not_let_a_dnc_number_be_dialled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The named version of the test above, on the gate a client would be most tempted to
    ask us to lift 'just for the trial'.

    The calling-hours window is pinned open rather than left to the wall clock: it sits
    BEFORE the DNC read in the gate's order, so an unpinned run of this test would pass all
    day and assert nothing after 21:00 IST. Pinning the one gate that depends on when the
    suite happens to run is what makes the assertion about DNC.
    """
    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda: True)
    tenant_id, agent_id = await _org()
    async with tenant_session(tenant_id) as session:
        await arm_agent_for_outbound(tenant_id, agent_id)
        # Published and outbound-capable, so the gate reaches the money and the DNC list
        # instead of stopping at `agent_not_live` — the earlier test asserts the general
        # property, this one has to reach one specific gate.
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound' "
                "WHERE id = :a AND tenant_id = :t"
            ),
            {"a": agent_id, "t": tenant_id},
        )
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=30, actor_user_id=None)
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, source) "
                "VALUES (gen_random_uuid(), :t, :p, 'caller_request')"
            ),
            {"t": tenant_id, "p": "+919000000002"},
        )
    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000002"
        )
    assert not decision.allowed
    assert decision.rule == "dnc"


# --- the meter ----------------------------------------------------------------------


async def test_the_meter_asks_about_the_calls_own_instant_not_the_clock() -> None:
    """A call can end inside a trial and settle after it — an ARQ retry ladder, or the
    reconciliation poller. Charging a client for a minute that was free when they spoke it
    is the one direction of error they will notice and be right about."""
    tenant_id, _ = await _org()
    started = datetime.now(UTC) - timedelta(days=10)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=5, actor_user_id=None, at=started)
        # Spoken on day two of the trial, settling now, five days after it ran out.
        assert await trial_covers(session, tenant_id=tenant_id, at=started + timedelta(days=2))
        # And a call placed after the end is NOT covered, however late the sweep is.
        assert not await trial_covers(session, tenant_id=tenant_id, at=started + timedelta(days=6))


async def test_a_trial_stopped_early_stops_covering_calls_at_the_moment_it_stopped() -> None:
    """`ends_at` is when it WOULD have ended; `ended_at` is when it did. The meter takes
    the earlier of the two, or an operator who stopped a runaway trial would go on funding
    it until its original date."""
    tenant_id, _ = await _org()
    started = datetime.now(UTC) - timedelta(days=10)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=30, actor_user_id=None, at=started)
        await end_trial(
            session,
            tenant_id=tenant_id,
            outcome="stopped",
            reason="Burning money.",
            at=started + timedelta(days=3),
        )
        assert await trial_covers(session, tenant_id=tenant_id, at=started + timedelta(days=1))
        assert not await trial_covers(session, tenant_id=tenant_id, at=started + timedelta(days=4))


# --- the boundary -------------------------------------------------------------------


async def test_ending_a_trial_moves_the_counting_window_and_deletes_nothing() -> None:
    """ "The numbers start from 0 again" is a WINDOW moving, never a row going away. Hard
    rule 4 is untouched — and the ledger row planted here is still on the ledger after the
    boundary, which is the whole assertion."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=Decimal("100"), reason="topup", ref="UTR-9"
        )
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        during = await counter_epoch(session, tenant_id=tenant_id)
        ended = await end_trial(
            session, tenant_id=tenant_id, outcome="converted", reason="They bought."
        )
        after = await counter_epoch(session, tenant_id=tenant_id)
        rows = (
            await session.execute(
                text("SELECT count(*) FROM credit_ledger WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()

    assert during is not None and after is not None
    assert after > during, "the epoch moves forward at the boundary"
    assert after == ended.ended_at
    assert rows == 1, "nothing was deleted from the ledger"


async def test_a_converting_client_is_never_scheduled_for_erasure() -> None:
    """Their leads, calls and transcripts are the value they just built, and one of those
    callers may be a patient waiting to be rung back."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        state = await end_trial(
            session, tenant_id=tenant_id, outcome="converted", reason="They bought."
        )
    assert state.erase_after is None


async def test_a_non_converting_client_gets_the_agreed_grace_from_the_real_end() -> None:
    """The grace is a term of THIS arrangement, frozen at start so a platform default that
    moves later cannot move the erasure date of a client already inside their window — and
    re-applied from the REAL end, so stopping a trial early does not shorten the grace."""
    tenant_id, _ = await _org()
    stopped_at = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await start_trial(
            session,
            tenant_id=tenant_id,
            days=30,
            actor_user_id=None,
            erasure_grace_days=45,
            at=stopped_at - timedelta(days=2),
        )
        state = await end_trial(
            session,
            tenant_id=tenant_id,
            outcome="stopped",
            reason="No response from the client.",
            at=stopped_at,
        )
    assert state.erase_after is not None
    assert abs((state.erase_after - (stopped_at + timedelta(days=45))).total_seconds()) < 1


async def test_the_platform_default_grace_applies_when_none_is_named() -> None:
    tenant_id, _ = await _org()
    at = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None, at=at)
        state = await end_trial(
            session, tenant_id=tenant_id, outcome="stopped", reason="Not for them.", at=at
        )
    assert state.erase_after is not None
    expected = at + timedelta(days=DEFAULT_ERASURE_GRACE_DAYS)
    assert abs((state.erase_after - expected).total_seconds()) < 1


async def test_the_boundary_zeroes_the_live_spend_counter() -> None:
    """`spend_state` is a derived counter no epoch can filter — the cap machinery reads it
    directly — so it is zeroed the way its own month-roll zeroes it. `capped` goes with it:
    a flag left set would refuse a client's calls on the strength of a ceiling nothing has
    reached."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped) VALUES (:t, '2026-09', 120, 240, 600, true)"
            ),
            {"t": tenant_id},
        )
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        await end_trial(session, tenant_id=tenant_id, outcome="converted", reason="Bought.")
        row = (
            await session.execute(
                text(
                    "SELECT minutes_used, spend_used, billed_inr, capped FROM spend_state "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
    assert row is not None
    assert row[0] == Decimal("0") and row[1] == Decimal("0") and row[2] == Decimal("0")
    assert row[3] is False


# --- the state machine --------------------------------------------------------------


async def test_only_one_trial_can_be_open_at_a_time() -> None:
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        with pytest.raises(ProblemError) as exc:
            await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
    assert exc.value.code == "trial_already_open"


async def test_a_second_trial_is_allowed_once_the_first_has_closed() -> None:
    """The uniqueness is on OPEN trials, not on the client. A client who trialled, went
    away and came back is a real client."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        await end_trial(session, tenant_id=tenant_id, outcome="stopped", reason="Paused.")
        second = await start_trial(session, tenant_id=tenant_id, days=14, actor_user_id=None)
    assert second.status == "active"


async def test_ending_a_trial_nobody_started_is_refused_by_name() -> None:
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as exc:
            await end_trial(session, tenant_id=tenant_id, outcome="converted", reason="Bought.")
    assert exc.value.code == "no_open_trial"


async def test_the_day_bounds_are_enforced_by_the_database_too() -> None:
    """A bound that only a route enforces is not a bound against a script, and days are the
    ONLY bound this arrangement has — the founder chose no spend ceiling."""
    tenant_id, _ = await _org()
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO tenant_trials (id, tenant_id, days, started_at, ends_at, status) "
                    "VALUES (gen_random_uuid(), :t, 9999, now(), now() + interval '1 day', "
                    "'active')"
                ),
                {"t": tenant_id},
            )
    assert MAX_TRIAL_DAYS == 365


async def test_an_ended_trial_cannot_read_as_open() -> None:
    """`(status = 'active') = (ended_at IS NULL)` is one fact stored once. A row reading
    `expired` with a NULL `ended_at` is one the erasure sweep would schedule from a NULL and
    skip for ever."""
    tenant_id, _ = await _org()
    with pytest.raises(DBAPIError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO tenant_trials (id, tenant_id, days, started_at, ends_at, status) "
                    "VALUES (gen_random_uuid(), :t, 7, now(), now() + interval '7 days', "
                    "'expired')"
                ),
                {"t": tenant_id},
            )


async def test_no_trial_means_no_epoch_and_the_plain_billing_month() -> None:
    """An account that never had a trial must not acquire a second, invisible window."""
    tenant_id, _ = await _org()
    async with tenant_session(tenant_id) as session:
        assert await counter_epoch(session, tenant_id=tenant_id) is None
