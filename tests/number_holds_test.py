"""A stopped client's rented numbers: held, resumed, released before the next renewal (D-860).

The vendor is `tests/thinnest_fake_account.py` (its numbers carry `since`, as
`snapshots/2026-10-19/pages/api-reference/phone-numbers/get-phone-number.md:702-707` does).
"""

from __future__ import annotations

import secrets
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing.plans import IST
from apps.api.campaigns import engine_numbers
from apps.api.campaigns import number_holds as holds
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.tenancy import closure
from apps.api.tenancy import engine_workspace as resolver
from apps.workers import engine_workspaces as workspace_jobs
from apps.workers import number_holds as jobs
from apps.workers import number_rental as rental_jobs
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist
from tests.thinnest_fake_account import FakeAccount
from tests.workspace_support import give_own_workspace

pytestmark = [pytest.mark.rls]


def _ist(y: int, m: int, d: int, hh: int = 0, mm: int = 0) -> datetime:
    return datetime(y, m, d, hh, mm, tzinfo=IST)


# --- when a held number is released ------------------------------------------------------


def test_a_hold_ends_a_day_before_the_next_renewal_day_begins_in_ist() -> None:
    rented = datetime(2026, 10, 8, 7, 15, tzinfo=UTC)
    release = holds.release_instant(held_at=_ist(2026, 10, 20, 10), anchors=[rented])
    assert release == _ist(2026, 11, 7)


def test_a_rent_day_that_differs_between_utc_and_ist_releases_before_the_earlier() -> None:
    # 20:00 UTC on the 5th is 01:30 IST on the 6th: either could be the platform's day.
    rented = datetime(2026, 10, 5, 20, 0, tzinfo=UTC)
    release = holds.release_instant(held_at=_ist(2026, 10, 20, 10), anchors=[rented])
    assert release == _ist(2026, 11, 4)


def test_our_later_record_never_moves_the_release_past_the_platforms_rent_day() -> None:
    rented = datetime(2026, 10, 8, 7, 15, tzinfo=UTC)
    recorded = datetime(2026, 10, 12, 9, 0, tzinfo=UTC)
    release = holds.release_instant(held_at=_ist(2026, 10, 20), anchors=[recorded, rented])
    assert release == _ist(2026, 11, 7)


def test_a_number_rented_on_the_31st_renews_on_the_last_day_of_a_short_month() -> None:
    rented = _ist(2027, 1, 31, 12)
    release = holds.release_instant(held_at=_ist(2027, 2, 10, 12), anchors=[rented])
    assert release == _ist(2027, 2, 27)


def test_a_hold_that_starts_inside_the_margin_releases_at_once() -> None:
    rented = _ist(2026, 10, 8, 12)
    held = _ist(2026, 11, 7, 12)
    assert holds.release_instant(held_at=held, anchors=[rented]) == held


def test_a_renewal_day_already_begun_counts_as_charged_and_the_next_one_is_beaten() -> None:
    rented = _ist(2026, 10, 8, 12)
    release = holds.release_instant(held_at=_ist(2026, 11, 8, 3), anchors=[rented])
    assert release == _ist(2026, 12, 7)


def test_no_hold_is_longer_than_thirty_days_and_every_release_beats_its_renewal() -> None:
    rented = _ist(2026, 1, 31, 23, 50)
    held = _ist(2026, 2, 1)
    while held < _ist(2027, 2, 1):
        release = holds.release_instant(held_at=held, anchors=[rented])
        renewal = holds.next_renewal_start([rented], after=held)
        assert held <= release <= held + holds.MAX_HOLD
        assert release == held or release <= renewal - holds.RELEASE_MARGIN
        held += timedelta(hours=13)


def test_the_reminder_goes_three_days_before_at_nine_and_only_on_a_long_hold() -> None:
    held = _ist(2026, 10, 20, 10)
    release = _ist(2026, 11, 7)
    assert holds.reminder_instant(held_at=held, release_at=release) == _ist(2026, 11, 4, 9)
    assert holds.reminder_instant(held_at=_ist(2026, 11, 3), release_at=release) is None


# --- the emails --------------------------------------------------------------------------


def test_the_hold_email_names_the_agent_and_the_ist_day_and_no_number_or_provider() -> None:
    subject, body = jobs.compose(
        event=holds.NOTICE_HELD,
        business="Sri Clinic",
        slug="sri-clinic",
        rows=[("wallet_negative", datetime(2026, 11, 6, 18, 30, tzinfo=UTC), "Anjali")],
    )
    assert subject == "Calls to your phone number have stopped"
    assert "The number your agent Anjali answers: Saturday 7 November 2026." in body
    assert "/c/sri-clinic/credits" in body
    assert "below zero for 7 days" in body
    lowered = body.lower()
    assert "thinnest" not in lowered and "+91" not in body


def test_the_closed_account_email_asks_for_a_reopening_not_a_top_up() -> None:
    _subject, body = jobs.compose(
        event=holds.NOTICE_REMINDER,
        business="Sri Clinic",
        slug="sri-clinic",
        rows=[
            ("account_closed", _ist(2026, 11, 7), None),
            ("account_closed", _ist(2026, 11, 9), "Ravi"),
        ],
    )
    assert body.startswith("This is a reminder.")
    assert "reopen your account" in body and "/credits" not in body
    assert "Your number with no agent on it: Saturday 7 November 2026." in body


# --- the flow, end to end ----------------------------------------------------------------


async def _tenant() -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Hold Clinic",
        slug=f"hold-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="owner@example.com",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"]))


async def _rented(account: FakeAccount, tenant_id: UUID, agent_id: UUID) -> tuple[UUID, str, str]:
    """A paying tenant with its own workspace, a live inbound agent there, and a number rented
    there and answered by it."""
    workspace = await give_own_workspace(tenant_id)
    account.ws(workspace)
    account.customers[workspace] = {
        "id": workspace,
        "externalId": resolver.external_ref_for(tenant_id),
        "archivedAt": None,
        "eraseAfter": None,
    }
    agent_ref = f"ag_{uuid.uuid4().hex[:8]}@{workspace}"
    number = f"9180{secrets.randbelow(10**8):08d}"
    account.hold(workspace, number, agent=agent_ref.split("@")[0])
    number_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE organizations SET first_paid_at = now(), first_paid_via = 'wallet_topup' "
                "WHERE id = :t"
            ),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', engine_agent_ref = :ref, "
                "direction = 'inbound' WHERE id = :aid"
            ),
            {"ref": agent_ref, "aid": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, provider, "
                "engine_number_ref, engine_owned, client_inr_per_month, direction, created_at, "
                "updated_at) VALUES (:id, :tid, :aid, :e164, 'standard', 'thinnest', :ref, true, "
                "500, 'both', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e164": f"+{number}",
                "ref": f"{number}@{workspace}",
            },
        )
    return number_id, number, workspace


async def _hold_rows(tenant_id: UUID) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT reason, release_at, detached_at, start_notice_at, ended_at, "
                        "end_reason, release_notice_at, agent_id FROM phone_number_holds "
                        "ORDER BY created_at"
                    )
                )
            ).all()
        )


async def _outbox(job: str, tenant_id: UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid ORDER BY created_at"
                ),
                {"job": job, "tid": str(tenant_id)},
            )
        ).scalars()
        return [dict(r) for r in rows]


async def test_a_closed_accounts_number_is_held_and_a_reopening_gives_it_back(
    account: FakeAccount,
) -> None:
    tenant_id, agent_id = await _tenant()
    number_id, number, workspace = await _rented(account, tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await closure.close_account(session, tenant_id=tenant_id, reason="test", closed_by=None)

    [hold] = await _hold_rows(tenant_id)
    assert hold.reason == "account_closed" and hold.release_at is None
    assert hold.agent_id == agent_id
    assert await _outbox(holds.SETTLE_JOB, tenant_id)
    # The workspace's offboarding waits for the hold: no release, no agent deleted.
    waits = await workspace_jobs.offboard_engine_workspace({}, {"tenant_id": str(tenant_id)})
    assert waits == "waiting_for_holds=1"
    assert number in account.ws(workspace).numbers

    tally, failed = await jobs.settle_tenant(tenant_id)

    assert failed == 0 and tally["applied"] == 1 and tally["detached"] == 1
    [hold] = await _hold_rows(tenant_id)
    # `since` is 2026-10-08T07:15:40Z in the fake, so the release beats the 8th's renewal.
    assert hold.release_at.astimezone(IST).time() == time.min
    assert hold.release_at.astimezone(IST).day == 7
    assert hold.detached_at is not None and hold.start_notice_at is not None
    assert account.ws(workspace).numbers[number]["agent"] is None
    [notice] = await _outbox(jobs.NOTICE_JOB, tenant_id)
    assert notice["event"] == holds.NOTICE_HELD

    async with tenant_session(tenant_id) as session:
        await closure.restore_account(session, tenant_id=tenant_id)
    await jobs.settle_tenant(tenant_id)

    [hold] = await _hold_rows(tenant_id)
    assert hold.end_reason == "resumed"
    async with tenant_session(tenant_id) as session:
        agent_ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert account.ws(workspace).numbers[number]["agent"] == str(agent_ref).split("@")[0]
    assert (
        await workspace_jobs.offboard_engine_workspace({}, {"tenant_id": str(tenant_id)})
        == "not_owed"
    )
    async with tenant_session(tenant_id) as session:
        released = (
            await session.execute(
                text("SELECT released_at FROM phone_numbers WHERE id = :id"), {"id": number_id}
            )
        ).scalar()
    assert released is None


async def test_a_due_hold_releases_the_number_and_then_lets_the_offboarding_finish(
    account: FakeAccount,
) -> None:
    tenant_id, agent_id = await _tenant()
    number_id, number, workspace = await _rented(account, tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await closure.close_account(session, tenant_id=tenant_id, reason="test", closed_by=None)
    await jobs.settle_tenant(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE phone_number_holds SET held_at = now() - interval '2 days', "
                "release_at = now() - interval '1 minute'"
            )
        )

    tally, failed = await jobs.settle_tenant(tenant_id)

    assert failed == 0 and tally["released"] == 1 and tally["offboarding_resumed"] == 1
    release = next(
        s for s in account.sent if s.method == "DELETE" and s.path.endswith(f"/{number}")
    )
    assert (release.workspace, release.query.get("confirm")) == (workspace, "release")
    [hold] = await _hold_rows(tenant_id)
    assert hold.end_reason == "released" and hold.release_notice_at is not None
    events = [n["event"] for n in await _outbox(jobs.NOTICE_JOB, tenant_id)]
    assert events == [holds.NOTICE_HELD, holds.NOTICE_RELEASED]
    async with tenant_session(tenant_id) as session:
        released = (
            await session.execute(
                text("SELECT released_at FROM phone_numbers WHERE id = :id"), {"id": number_id}
            )
        ).scalar()
    assert released is not None

    result = await workspace_jobs.offboard_engine_workspace({}, {"tenant_id": str(tenant_id)})
    assert result.startswith("released=0")
    assert account.customers[workspace]["archivedAt"] is not None

    # A second pass finds nothing to do: no second release, no second email.
    again, _ = await jobs.settle_tenant(tenant_id)
    assert again["released"] == 0
    assert len(await _outbox(jobs.NOTICE_JOB, tenant_id)) == 2


async def test_a_held_number_released_by_hand_still_lets_the_offboarding_finish(
    account: FakeAccount,
) -> None:
    """FAILS IF: only a release by the hold job resumes the offboarding, so a closed account
    whose held number an operator released keeps its workspace and agents at the platform."""
    tenant_id, agent_id = await _tenant()
    number_id, _number, _workspace = await _rented(account, tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await closure.close_account(session, tenant_id=tenant_id, reason="test", closed_by=None)
    await jobs.settle_tenant(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE phone_numbers SET released_at = now() WHERE id = :id"), {"id": number_id}
        )
    before = len(await _outbox(resolver.OFFBOARD_JOB, tenant_id))

    tally, failed = await jobs.settle_tenant(tenant_id)

    assert failed == 0 and tally["closed_elsewhere"] == 1
    assert tally["offboarding_resumed"] == 1
    assert len(await _outbox(resolver.OFFBOARD_JOB, tenant_id)) == before + 1


async def _overdrawn(tenant_id: UUID, *, days: int) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, balance_after, "
                "occurred_at, created_at) VALUES (:id, :tid, -250, 'usage', :ref, -250, "
                "now() - make_interval(days => :days), now() - make_interval(days => :days))"
            ),
            {"id": uuid7(), "tid": tenant_id, "ref": f"call:{uuid.uuid4()}", "days": days},
        )


async def _no_trial(*_a: Any, **_kw: Any) -> bool:
    return False


async def test_a_wallet_below_zero_long_enough_holds_and_a_top_up_resumes(
    account: FakeAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(holds, "trial_billing_active", _no_trial)
    tenant_id, agent_id = await _tenant()
    number_id, number, workspace = await _rented(account, tenant_id, agent_id)
    await _overdrawn(tenant_id, days=6)
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        assert await holds.stopped_reason(session, tenant_id=tenant_id, now=now) is None
        assert (
            await holds.stopped_reason(
                session, tenant_id=tenant_id, now=now + timedelta(days=1, minutes=1)
            )
            == "wallet_negative"
        )
    await _overdrawn(tenant_id, days=8)

    await jobs.settle_tenant(tenant_id)

    [hold] = await _hold_rows(tenant_id)
    assert hold.reason == "wallet_negative" and hold.detached_at is not None
    async with tenant_session(tenant_id) as session:
        renewing = {r[0] for r in (await session.execute(text(rental_jobs._RENEWING))).all()}
        assert number_id not in renewing
        assert (await holds.held_numbers(session))[number_id] == hold.release_at

    from apps.api.billing.service import record_entry

    async with tenant_session(tenant_id) as session:
        await record_entry(
            session, tenant_id=tenant_id, delta=holds_top_up(), reason="grant", ref="top-up-1"
        )
    assert len(await _outbox(holds.SETTLE_JOB, tenant_id)) == 1
    await jobs.settle_number_holds({}, {"tenant_id": str(tenant_id)})

    [hold] = await _hold_rows(tenant_id)
    assert hold.end_reason == "resumed"
    assert account.ws(workspace).numbers[number]["agent"] is not None
    async with tenant_session(tenant_id) as session:
        renewing = {r[0] for r in (await session.execute(text(rental_jobs._RENEWING))).all()}
    assert number_id in renewing


def holds_top_up() -> Any:
    from decimal import Decimal

    return Decimal("500.00")


async def test_a_number_lent_from_our_own_workspace_is_never_held(account: FakeAccount) -> None:
    tenant_id, _agent_id = await _tenant()
    await give_own_workspace(tenant_id)
    number = f"9180{secrets.randbelow(10**8):08d}"
    account.hold(None, number)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, provider, "
                "engine_number_ref, engine_owned, direction, created_at, updated_at) VALUES "
                "(:id, :tid, :e164, 'standard', 'thinnest', :ref, true, 'both', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "e164": f"+{number}", "ref": number},
        )
        placed = await holds.place_holds(session, tenant_id=tenant_id, reason="account_closed")
    assert placed == []


def test_a_held_number_answers_nothing() -> None:
    kwargs: dict[str, Any] = {
        "engine_number_ref": "918012345678@org_x",
        "agent_ref": "ag_1@org_x",
        "agent_status": "live",
        "agent_direction": "inbound",
        "agent_deleted": False,
    }
    assert engine_numbers.answers_calls(**kwargs) is True
    assert engine_numbers.answers_calls(**kwargs, held=True) is False


async def test_another_tenant_sees_none_of_a_tenants_holds(account: FakeAccount) -> None:
    tenant_id, agent_id = await _tenant()
    other, _ = await _tenant()
    await _rented(account, tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        assert await holds.place_holds(session, tenant_id=tenant_id, reason="account_closed")
    async with tenant_session(other) as session:
        seen = (await session.execute(text("SELECT count(*) FROM phone_number_holds"))).scalar()
    assert seen == 0
    async with untenanted_session() as session:
        seen = (await session.execute(text("SELECT count(*) FROM phone_number_holds"))).scalar()
    assert seen == 0


def test_release_dates_are_whole_ist_days() -> None:
    assert jobs.ist_day(datetime.combine(date(2026, 11, 6), time(18, 30), tzinfo=UTC)) == (
        "Saturday 7 November 2026"
    )
