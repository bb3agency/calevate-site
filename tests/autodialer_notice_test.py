"""The sender's advance autodialer notice — the record, and the outbound gate that reads it.

TCCCPR Regulation 4, relayed as: *"Every Sender shall notify the Originating Access
Provider, in advance, about the use of Auto Dialer or Robo-Calls as well as the intended
objective of such calls in writing."* REPORTED, founder-relayed, 13 Sep 2026
(`docs/evidence/number-series-inbound-vs-outbound-2026-09-13.md` §3.3); `trai.gov.in` is
egress-blocked from this container, so nobody here has opened the regulation.

What this file pins is the shape of the control rather than the shape of the law:

- outbound is refused BY NAME when nothing is recorded, and the three refusals stay
  distinguishable (nothing filed / withdrawn / dated in the future);
- a recorded notice lets the dial through;
- INBOUND is untouched — an inbound agent never reaches the rule;
- the record is tenant-isolated (hard rule 1) and append-only at the database (hard rule 4);
- the obligation is the CLIENT's: nothing here notifies anyone on their behalf.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.autodialer import (
    AUTODIALER_NOTICE_MISSING_REASON,
    AUTODIALER_NOTICE_MISSING_RULE,
    AUTODIALER_NOTICE_NOT_YET_EFFECTIVE_RULE,
    AUTODIALER_NOTICE_WITHDRAWN_RULE,
    NOT_RECORDED,
    AutodialerNotice,
    autodialer_notice_blocker,
    read_autodialer_notice,
    record_autodialer_notice,
)
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text
from tests.conftest import accept_agreements, arm_agent_for_outbound, fund_wallet

pytestmark = pytest.mark.rls

_INDIA = "+919876500001"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST, so a refusal here is never the calling-hours rule by accident."""
    fixed = datetime(2026, 8, 11, 11, 0, tzinfo=UTC)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


async def _tenant_agent(*, direction: str = "outbound") -> tuple[uuid.UUID, uuid.UUID]:
    """A live, published agent whose money and agreements are in order, so a refusal from
    `check_dispatch` is about the paperwork under test rather than about a wallet."""
    created = await admin_service.create_organization(
        name="Dialler Dental",
        slug=f"dial-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    await fund_wallet(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = :d WHERE id = :a"),
            {"d": direction, "a": agent_id},
        )
    return tenant_id, agent_id


async def _member(tenant_id: uuid.UUID) -> uuid.UUID:
    """`recorded_by` is NOT NULL, and a fresh organisation has no member until somebody
    accepts an invitation — so one is made rather than looked up."""
    user_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": user_id, "e": f"owner-{user_id}@example.test"},
        )
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :t, :u, 'owner', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "u": user_id},
        )
    return user_id


async def _notify(
    tenant_id: uuid.UUID,
    *,
    days_ago: int = 7,
    withdraw: bool = False,
    objective: str = "Appointment reminders for our own patients",
) -> uuid.UUID:
    user_id = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        return await record_autodialer_notice(
            session,
            tenant_id=tenant_id,
            access_provider="Airtel",
            objective=objective,
            notified_on=(datetime.now(UTC) - timedelta(days=days_ago)).date(),
            recorded_by=user_id,
            notice_reference="AIRTEL-TKT-4417",
            withdraw=withdraw,
        )


async def _gate(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, phone: str = _INDIA):
    async with tenant_session(tenant_id) as session:
        return await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164=phone
        )


# --- the record --------------------------------------------------------------


async def test_a_tenant_with_no_row_reads_as_not_recorded() -> None:
    """Absence is a value, not an exception: every new account is in this state and the
    gate has to answer for a tenant nobody has ever looked at."""
    tenant_id, _ = await _tenant_agent()
    async with tenant_session(tenant_id) as session:
        assert await read_autodialer_notice(session, tenant_id=tenant_id) == NOT_RECORDED


async def test_the_recorded_notice_keeps_what_was_notified() -> None:
    """The provider, the objective and the date are the three things Regulation 4 names,
    so all three survive the round trip — a record that lost the objective would not be
    evidence of the notice the regulation describes."""
    tenant_id, _ = await _tenant_agent()
    await _notify(tenant_id, days_ago=3, objective="Appointment reminders and recalls")
    async with tenant_session(tenant_id) as session:
        notice = await read_autodialer_notice(session, tenant_id=tenant_id)
    assert notice.recorded and notice.state == "notified"
    assert notice.access_provider == "Airtel"
    assert notice.objective == "Appointment reminders and recalls"
    assert notice.notice_reference == "AIRTEL-TKT-4417"
    assert notice.is_effective()


async def test_a_withdrawal_appends_and_the_latest_row_decides() -> None:
    """Hard rule 4: both rows survive, so "the notice was live when last month's calls
    were placed" stays answerable after it is retracted."""
    tenant_id, _ = await _tenant_agent()
    await _notify(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert (await read_autodialer_notice(session, tenant_id=tenant_id)).is_effective()
    await _notify(tenant_id, withdraw=True)
    async with tenant_session(tenant_id) as session:
        assert not (await read_autodialer_notice(session, tenant_id=tenant_id)).is_effective()
        kept = (
            await session.execute(
                text("SELECT count(*) FROM autodialer_notices WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
    assert kept == 2, "a withdrawal must append, never replace"


async def test_the_ledger_refuses_an_update_and_a_delete() -> None:
    """Hard rule 4 at the DATABASE, not in the module. A correction is a new row."""
    tenant_id, _ = await _tenant_agent()
    await _notify(tenant_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(Exception, match=r"(?i)append.only|immutable|not allowed"):
            await session.execute(
                text("UPDATE autodialer_notices SET state = 'withdrawn' WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(Exception, match=r"(?i)append.only|immutable|not allowed"):
            await session.execute(
                text("DELETE FROM autodialer_notices WHERE tenant_id = :t"), {"t": tenant_id}
            )


async def test_another_tenant_sees_zero_rows() -> None:
    """Hard rule 1's cross-tenant clause over the new table — and the neighbour's own
    answer must be "not recorded", never someone else's yes."""
    owner, _ = await _tenant_agent()
    await _notify(owner)
    stranger, _ = await _tenant_agent()
    async with tenant_session(stranger) as session:
        visible = (
            await session.execute(text("SELECT count(*) FROM autodialer_notices"))
        ).scalar_one()
        assert await read_autodialer_notice(session, tenant_id=owner) == NOT_RECORDED
        assert await read_autodialer_notice(session, tenant_id=stranger) == NOT_RECORDED
    assert visible == 0


async def test_a_blank_provider_or_objective_is_refused_at_the_door() -> None:
    """A notice that cannot say who was told, or what for, is not evidence of the notice
    Regulation 4 describes."""
    tenant_id, _ = await _tenant_agent()
    user_id = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        for provider, objective, code in (
            ("   ", "Reminders", "autodialer_notice_provider_invalid"),
            ("Airtel", "  ", "autodialer_notice_objective_invalid"),
        ):
            with pytest.raises(ProblemError) as raised:
                await record_autodialer_notice(
                    session,
                    tenant_id=tenant_id,
                    access_provider=provider,
                    objective=objective,
                    notified_on=datetime.now(UTC).date(),
                    recorded_by=user_id,
                )
            assert raised.value.code == code


# --- the predicate -----------------------------------------------------------


def test_the_three_states_are_told_apart_without_a_database() -> None:
    """Pure state logic. Each of these sends a client to a different next action, which is
    why they are three rules and not one."""
    today = datetime(2026, 9, 20, tzinfo=UTC).date()
    live = AutodialerNotice(
        recorded=True,
        state="notified",
        access_provider="Airtel",
        objective="Reminders",
        notified_on=today - timedelta(days=1),
        notice_reference=None,
        created_at=None,
    )
    assert live.is_effective(today=today)
    assert not NOT_RECORDED.is_effective(today=today)
    # Dated in the future: recorded, honest, and not yet the advance notice the
    # regulation asks for.
    future = replace(live, notified_on=today + timedelta(days=3))
    assert not future.is_effective(today=today)
    assert not replace(live, state="withdrawn").is_effective(today=today)
    # Given TODAY counts: "in advance" of a call placed later the same day.
    assert replace(live, notified_on=today).is_effective(today=today)


async def test_the_blocker_names_each_failure_separately() -> None:
    tenant_id, _ = await _tenant_agent()
    async with tenant_session(tenant_id) as session:
        assert (await autodialer_notice_blocker(session, tenant_id=tenant_id)) == (
            AUTODIALER_NOTICE_MISSING_RULE,
            AUTODIALER_NOTICE_MISSING_REASON,
        )
    await _notify(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert await autodialer_notice_blocker(session, tenant_id=tenant_id) is None
    await _notify(tenant_id, withdraw=True)
    async with tenant_session(tenant_id) as session:
        blocked = await autodialer_notice_blocker(session, tenant_id=tenant_id)
    assert blocked is not None and blocked[0] == AUTODIALER_NOTICE_WITHDRAWN_RULE


async def test_a_future_dated_notice_is_recorded_and_still_refuses() -> None:
    """A client who has written to their provider naming a start date next Monday has done
    the right thing and must be able to record it — what must not happen is that it opens
    the gate before Monday."""
    tenant_id, _ = await _tenant_agent()
    await _notify(tenant_id, days_ago=-5)
    async with tenant_session(tenant_id) as session:
        blocked = await autodialer_notice_blocker(session, tenant_id=tenant_id)
    assert blocked is not None and blocked[0] == AUTODIALER_NOTICE_NOT_YET_EFFECTIVE_RULE
    assert "in the future" in blocked[1]


def test_the_refusal_tells_the_client_it_is_theirs_to_send() -> None:
    """Regulation 4 binds the SENDER, which under our model is the client. A message that
    let them think Calevate notifies on their behalf would be the one wrong outcome."""
    lowered = AUTODIALER_NOTICE_MISSING_REASON.lower()
    assert "rather than from calevate" in lowered
    assert "in writing" in lowered and "in advance" in lowered
    assert "answering incoming calls is unaffected" in lowered


# --- the gate ----------------------------------------------------------------


async def test_an_outbound_dial_is_refused_by_name_without_a_notice() -> None:
    """The whole point: a tenant whose DLT paperwork is otherwise complete still cannot
    autodial until it has told its access provider that it autodials."""
    tenant_id, agent_id = await _tenant_agent()
    await arm_agent_for_outbound(tenant_id, agent_id, autodialer_notice=False)
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed
    assert decision.rule == AUTODIALER_NOTICE_MISSING_RULE
    assert decision.reason == AUTODIALER_NOTICE_MISSING_REASON


async def test_a_recorded_notice_lets_the_dial_through() -> None:
    tenant_id, agent_id = await _tenant_agent()
    await arm_agent_for_outbound(tenant_id, agent_id, autodialer_notice=False)
    assert not (await _gate(tenant_id, agent_id)).allowed
    await _notify(tenant_id)
    assert (await _gate(tenant_id, agent_id)).allowed


async def test_a_withdrawn_notice_stops_the_dialling_again() -> None:
    """The record is not write-once: a sender who retracts its notice stops being covered
    on the next dial, with no campaign edit and no republish."""
    tenant_id, agent_id = await _tenant_agent()
    await arm_agent_for_outbound(tenant_id, agent_id)
    assert (await _gate(tenant_id, agent_id)).allowed
    await _notify(tenant_id, withdraw=True)
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed and decision.rule == AUTODIALER_NOTICE_WITHDRAWN_RULE


async def test_an_inbound_agent_never_reaches_the_rule() -> None:
    """Regulation 4 is about the USE of an auto dialler. A receptionist answering a call
    the customer placed dials nothing, so an inbound agent with no notice at all is
    refused two rules earlier and answering is unaffected."""
    tenant_id, agent_id = await _tenant_agent(direction="inbound")
    decision = await _gate(tenant_id, agent_id)
    assert not decision.allowed
    assert decision.rule == "agent_inbound_only", (
        "inbound must stop before the autodialer rule, not be gated by it"
    )
