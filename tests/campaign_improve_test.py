"""The Improve tab (D-992 item 8): best hours counted by people and applied in one press,
retries spread over the day, the re-call draft that carries what was learned, and the
opening test decided by a Bayesian chance with a minimum sample."""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from apps.api.agents.service import campaign_agent_row, campaign_first_words, posture_of
from apps.api.campaigns import controls, improve, learning
from apps.api.campaigns import service as campaigns_service
from apps.api.campaigns.call_timing import Block, blocks_within, spread_retry_at
from apps.api.compliance.service import add_to_dnc
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import dispatch_campaign_tick
from calevate_shared.call_script import CallScript
from calevate_shared.calling_window import IST
from calevate_shared.engine import notice_fields
from calevate_shared.opening_notices import first_words_disclose
from sqlalchemy import text
from tests.campaign_controls_test import Account, _account, _campaign, _one
from tests.campaigns_test import _daytime as _daytime
from tests.campaigns_test import _quiesce, _ready_campaign
from tests.campaigns_test import _roomy_platform_pool as _roomy_platform_pool

DAY = date(2026, 11, 10)
OWN_OPENING = "Namaste, this is Asha from Sri Ram Stores, calling about your order."
SECOND_OPENING = "Namaste, Asha here from Sri Ram Stores, with good news about your order."


async def _tried(
    account: Account,
    campaign_id: uuid.UUID,
    *,
    hour: int,
    people: int,
    reached: int,
    first: int = 0,
    tries: int = 1,
) -> None:
    """`people` people rung `tries` times each at `hour` IST; the first `reached` of them
    pick up on their last try."""
    at = datetime.combine(DAY, time(hour, 5), IST)
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "campaign_id, to_e164, duration_s, started_at, ended_at, created_at, updated_at) "
                "SELECT gen_random_uuid(), :tid, :aid, 'exec_' || gen_random_uuid(), 'outbound', "
                "CASE WHEN p < :reached AND t = :tries THEN 'completed' ELSE 'no_answer' END, "
                "CAST(:cid AS uuid), '+91' || (9100000000 + :first + p)::text, "
                "CASE WHEN p < :reached AND t = :tries THEN 60 ELSE 0 END, "
                "CAST(:at AS timestamptz) + make_interval(mins => t), CAST(:at AS timestamptz), "
                "now(), now() FROM generate_series(0, :people - 1) p, generate_series(1, :tries) t"
            ),
            {
                "tid": account.tenant_id,
                "aid": account.agent_id,
                "cid": campaign_id,
                "reached": reached,
                "tries": tries,
                "first": first,
                "people": people,
                "at": at,
            },
        )


async def _opening_trial(
    account: Account,
    campaign_id: uuid.UUID,
    *,
    side: str,
    answered: int,
    stayed: int,
    first: int,
    hour: int = 19,
) -> None:
    """`answered` people given opening `side` who picked up, `stayed` of them past twenty
    seconds; each a connected contact with one call."""
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, status, "
                "attempts, opening_variant, created_at, updated_at) SELECT gen_random_uuid(), "
                ":tid, :cid, '+91' || (9200000000 + :first + p)::text, 'connected', 1, :side, "
                "now(), now() FROM generate_series(0, :n - 1) p"
            ),
            {
                "tid": account.tenant_id,
                "cid": campaign_id,
                "first": first,
                "n": answered,
                "side": side,
            },
        )
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "campaign_id, to_e164, duration_s, started_at, ended_at, created_at, updated_at) "
                "SELECT gen_random_uuid(), :tid, :aid, 'exec_' || gen_random_uuid(), 'outbound', "
                "'completed', :cid, '+91' || (9200000000 + :first + p)::text, "
                "CASE WHEN p < :stayed THEN 90 ELSE 8 END, CAST(:at AS timestamptz), "
                "CAST(:at AS timestamptz), now(), now() "
                "FROM generate_series(0, :n - 1) p"
            ),
            {
                "tid": account.tenant_id,
                "aid": account.agent_id,
                "cid": campaign_id,
                "first": first,
                "n": answered,
                "stayed": stayed,
                "at": datetime.combine(DAY, time(hour, 10), IST),
            },
        )


async def _with_test(account: Account, campaign_id: uuid.UUID) -> None:
    """The campaign's own script with its opening, and a second opening under test."""
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb), opening_b = :b WHERE id = :c"),
            {
                "s": CallScript(opening_line=OWN_OPENING).model_dump_json(),
                "b": SECOND_OPENING,
                "c": campaign_id,
            },
        )


async def _best_hours_data(account: Account, campaign_id: uuid.UUID) -> None:
    """Few answer in the morning, most in the evening: clearly the 6pm-9pm block."""
    await _tried(account, campaign_id, hour=10, people=60, reached=10, first=0)
    await _tried(account, campaign_id, hour=19, people=60, reached=50, first=1000)


# --- the statistics, on fixtures ----------------------------------------------------------


def test_the_chance_is_exact_on_fixtures_known_in_closed_form() -> None:
    # Nothing known about either: a coin.
    assert learning.chance_better(
        base_successes=0, base_people=0, other_successes=0, other_people=0
    ) == pytest.approx(0.5)
    # Beta(2,1) against Beta(1,1): the integral of 2x * x over [0,1] is 2/3.
    assert learning.chance_better(
        base_successes=0, base_people=0, other_successes=1, other_people=1
    ) == pytest.approx(2 / 3)
    # The same counts on both sides are a coin, however many.
    assert learning.chance_better(
        base_successes=150, base_people=400, other_successes=150, other_people=400
    ) == pytest.approx(0.5, abs=1e-9)
    # Symmetric: swapping the sides gives the complement.
    one = learning.chance_better(
        base_successes=30, base_people=100, other_successes=40, other_people=100
    )
    other = learning.chance_better(
        base_successes=40, base_people=100, other_successes=30, other_people=100
    )
    assert one + other == pytest.approx(1.0)
    assert 0.9 < one < 0.97


def test_the_minimum_sample_is_the_fleiss_figure() -> None:
    assert learning.people_needed(0.4, 0.5) == 388
    assert learning.people_needed(0.2, 0.3) == 294
    assert learning.MIN_ANSWERED_PER_OPENING == 388


def test_a_lucky_start_does_not_decide_and_the_sample_does() -> None:
    small = [
        learning.OpeningResult("a", 50, 50, 10, 0),
        learning.OpeningResult("b", 50, 50, 40, 0),
    ]
    assert learning.opening_verdict(small).state == "too_few"
    big = [
        learning.OpeningResult("a", 400, 400, 200, 0),
        learning.OpeningResult("b", 400, 400, 260, 0),
    ]
    verdict = learning.opening_verdict(big)
    assert verdict.state == "decided" and verdict.winner == "b"
    assert verdict.chance_b_better > learning.WIN_CHANCE
    even = [
        learning.OpeningResult("a", 400, 400, 200, 0),
        learning.OpeningResult("b", 400, 400, 205, 0),
    ]
    assert learning.opening_verdict(even).state == "measuring"


# --- best hours ---------------------------------------------------------------------------


async def test_an_hour_counts_people_not_calls() -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    # One person rung three times at 10am and never reached, one reached at the first try:
    # four calls, one answered, but two people and one of them reached.
    await _tried(account, campaign_id, hour=10, people=1, reached=0, tries=3, first=0)
    await _tried(account, campaign_id, hour=10, people=1, reached=1, first=1)
    async with tenant_session(account.tenant_id) as session:
        rates = await learning.answer_rate_by_hour(session, campaign_id)
    assert rates == [learning.HourRate(hour=10, people=2, reached=1)]


def test_the_block_is_clamped_inside_the_platform_and_the_campaigns_hours() -> None:
    assert improve.clamped_window(Block(time(7), time(10)), None) == {
        "start": "09:00",
        "end": "10:00",
    }
    assert improve.clamped_window(Block(time(20), time(22)), None) == {
        "start": "20:00",
        "end": "21:00",
    }
    assert improve.clamped_window(
        Block(time(18), time(21)), {"start": "09:00", "end": "19:30"}
    ) == {"start": "18:00", "end": "19:30"}
    assert (
        improve.clamped_window(Block(time(9), time(12)), {"start": "13:00", "end": "17:00"}) is None
    )


def test_the_grid_is_cut_to_the_campaigns_hours() -> None:
    assert [(b.start, b.end) for b in blocks_within({"start": "10:30", "end": "16:00"})] == [
        (time(10, 30), time(12)),
        (time(12), time(15)),
        (time(15), time(16)),
    ]


async def test_best_hours_apply_in_one_press_and_undo_puts_them_back() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    await _best_hours_data(account, campaign_id)
    async with tenant_session(account.tenant_id) as session:
        verdict = await improve.read_best_hours(session, campaign_id)
        assert verdict.state == "actionable" and verdict.best is not None
        assert verdict.best.block == Block(time(18), time(21))
        await improve.apply_best_hours(session, campaign_id, by="owner")
    row = await _one(
        account.tenant_id,
        "SELECT calling_hours, best_hours_applied FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert row[0] == {"start": "18:00", "end": "21:00"}
    assert row[1]["before"] is None and row[1]["by"] == "owner"
    async with tenant_session(account.tenant_id) as session:
        await improve.undo_best_hours(session, campaign_id)
    row = await _one(
        account.tenant_id,
        "SELECT calling_hours, best_hours_applied FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert row[0] is None and row[1] is None


async def test_pip_applies_only_when_allowed_and_its_undo_turns_it_off() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    await _best_hours_data(account, campaign_id)
    async with tenant_session(account.tenant_id) as session:
        assert (await improve.run_improve(session, campaign_id)).hours_applied is False
        await improve.set_best_hours_auto(session, campaign_id, on=True)
        assert (await improve.run_improve(session, campaign_id)).hours_applied is True
        assert (await improve.run_improve(session, campaign_id)).hours_applied is False
        await improve.undo_best_hours(session, campaign_id)
    row = await _one(
        account.tenant_id,
        "SELECT calling_hours, best_hours_auto FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert row[0] is None and row[1] is False


async def test_undo_is_refused_once_the_hours_were_changed_by_hand() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    await _best_hours_data(account, campaign_id)
    async with tenant_session(account.tenant_id) as session:
        await improve.apply_best_hours(session, campaign_id, by="owner")
        await controls.update_draft(
            session,
            campaign_id=campaign_id,
            changes={"calling_hours": {"start": "10:00", "end": "12:00"}},
        )
        with pytest.raises(ProblemError) as refused:
            await improve.undo_best_hours(session, campaign_id)
    assert refused.value.code == "campaign_best_hours_nothing_to_undo"


async def test_too_few_people_recommend_nothing_and_apply_is_refused() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    await _tried(account, campaign_id, hour=10, people=8, reached=1)
    await _tried(account, campaign_id, hour=19, people=8, reached=8, first=100)
    async with tenant_session(account.tenant_id) as session:
        assert (await improve.read_best_hours(session, campaign_id)).state == "too_few"
        with pytest.raises(ProblemError) as refused:
            await improve.apply_best_hours(session, campaign_id, by="owner")
    assert refused.value.code == "campaign_best_hours_not_ready"


# --- retries spread over the day ----------------------------------------------------------


def _ist(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), IST)


def test_a_retry_moves_to_another_block_of_the_day() -> None:
    failed = _ist(DAY, 10)
    at = spread_retry_at(
        failed_at=failed, earliest=failed + timedelta(minutes=30), calling_hours=None
    )
    assert at == _ist(DAY, 12)


def test_a_retry_after_the_window_closes_goes_to_the_next_mornings_block() -> None:
    failed = _ist(DAY, 19)
    at = spread_retry_at(failed_at=failed, earliest=failed + timedelta(hours=2), calling_hours=None)
    assert at == _ist(DAY + timedelta(days=1), 9)


def test_a_day_later_at_the_same_time_is_moved_on_to_another_block() -> None:
    failed = _ist(DAY, 10)
    at = spread_retry_at(failed_at=failed, earliest=failed + timedelta(days=1), calling_hours=None)
    assert at == _ist(DAY + timedelta(days=1), 12)


def test_one_block_of_hours_retries_on_another_day_inside_them() -> None:
    failed = _ist(DAY, 10, 30)
    hours = {"start": "10:00", "end": "12:00"}
    at = spread_retry_at(
        failed_at=failed, earliest=failed + timedelta(minutes=30), calling_hours=hours
    )
    assert at == _ist(DAY + timedelta(days=1), 10)


def test_spreading_never_rings_sooner_than_the_gap() -> None:
    failed = _ist(DAY, 11, 50)
    earliest = failed + timedelta(minutes=30)
    assert spread_retry_at(failed_at=failed, earliest=earliest, calling_hours=None) == earliest


async def _dialing_contact(account: Account, campaign_id: uuid.UUID) -> uuid.UUID:
    contact_id = uuid.uuid4()
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, status, "
                "attempts, last_attempt_at, created_at, updated_at) VALUES (:id, :tid, :cid, "
                "'+919300000001', 'dialing', 1, now(), now(), now())"
            ),
            {"id": contact_id, "tid": account.tenant_id, "cid": campaign_id},
        )
    return contact_id


@pytest.mark.parametrize("spread", [True, False])
async def test_the_dispatcher_writes_the_spread_retry_or_the_plain_gap(spread: bool) -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    contact_id = await _dialing_contact(account, campaign_id)
    policy: dict[str, Any] = {"max_attempts": 3, "backoff_minutes": [30, 120], "spread": spread}
    async with tenant_session(account.tenant_id) as session:
        spent = await campaign_dispatch._record_failure(
            session, contact_id, 1, 3, policy, tenant_id=account.tenant_id, campaign_id=campaign_id
        )
        row = (
            await session.execute(
                text(
                    "SELECT status, next_attempt_at, last_attempt_at, now() FROM "
                    "campaign_contacts WHERE id = :id"
                ),
                {"id": contact_id},
            )
        ).one()
    assert spent is False and row[0] == "pending"
    earliest = row[3] + timedelta(minutes=30)
    expected = (
        spread_retry_at(failed_at=row[2], earliest=earliest, calling_hours=None)
        if spread
        else earliest
    )
    assert abs((row[1] - expected).total_seconds()) < 5


async def test_a_new_campaign_spreads_its_retries_and_an_edit_keeps_the_choice() -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    row = await _one(
        account.tenant_id, "SELECT retry_policy FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert row[0]["spread"] is True
    async with tenant_session(account.tenant_id) as session:
        await improve.set_retry_spread(session, campaign_id, on=False)
        await controls.update_draft(
            session,
            campaign_id=campaign_id,
            changes={"retry_policy": {"max_attempts": 2, "backoff_minutes": [60]}},
        )
    row = await _one(
        account.tenant_id, "SELECT retry_policy FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert row[0] == {"max_attempts": 2, "backoff_minutes": [60], "spread": False}


# --- the re-call draft --------------------------------------------------------------------


async def _contacts(account: Account, campaign_id: uuid.UUID, statuses: dict[str, str]) -> None:
    async with tenant_session(account.tenant_id) as session:
        for phone, status in statuses.items():
            await session.execute(
                text(
                    "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, "
                    "status, attempts, created_at, updated_at) VALUES (gen_random_uuid(), :tid, "
                    ":cid, :p, :s, 1, now(), now())"
                ),
                {"tid": account.tenant_id, "cid": campaign_id, "p": phone, "s": status},
            )


async def _redo(account: Account, source_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(account.tenant_id) as session:
        copy_id, _ = await controls.duplicate_campaign(
            session,
            tenant_id=account.tenant_id,
            source_id=source_id,
            name=None,
            with_unreached=True,
        )
    return copy_id


async def test_the_recall_draft_carries_best_hours_spread_retries_and_the_winning_opening() -> None:
    account = await _account()
    source_id = await _campaign(account, status="completed")
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET retry_policy = CAST(:r AS jsonb) WHERE id = :c"),
            {"r": '{"max_attempts": 2, "backoff_minutes": [60]}', "c": source_id},
        )
    await _best_hours_data(account, source_id)
    await _with_test(account, source_id)
    await _opening_trial(account, source_id, side="a", answered=400, stayed=180, first=0)
    await _opening_trial(account, source_id, side="b", answered=400, stayed=260, first=5000)
    await _contacts(
        account,
        source_id,
        {"+919400000001": "failed", "+919400000002": "pending", "+919400000003": "dnc_blocked"},
    )
    copy_id = await _redo(account, source_id)
    row = await _one(
        account.tenant_id,
        "SELECT calling_hours, retry_policy, script, opening_b FROM campaigns WHERE id = :c",
        c=copy_id,
    )
    assert row[0] == {"start": "18:00", "end": "21:00"}
    assert row[1] == {"max_attempts": 2, "backoff_minutes": [60], "spread": True}
    assert row[2]["opening_line"] == SECOND_OPENING
    assert row[3] is None
    phones = await _one(
        account.tenant_id,
        "SELECT array_agg(phone_e164 ORDER BY phone_e164) FROM campaign_contacts "
        "WHERE campaign_id = :c",
        c=copy_id,
    )
    assert phones[0] == ["+919400000001", "+919400000002"]


async def test_a_paused_campaign_gives_only_the_people_whose_tries_ran_out() -> None:
    account = await _account()
    source_id = await _campaign(account, status="paused")
    await _contacts(account, source_id, {"+919400000011": "failed", "+919400000012": "pending"})
    copy_id = await _redo(account, source_id)
    phones = await _one(
        account.tenant_id,
        "SELECT array_agg(phone_e164) FROM campaign_contacts WHERE campaign_id = :c",
        c=copy_id,
    )
    assert phones[0] == ["+919400000011"]


async def test_a_running_campaign_still_cannot_be_called_again() -> None:
    account = await _account()
    source_id = await _campaign(account, status="running")
    with pytest.raises(ProblemError) as refused:
        await _redo(account, source_id)
    assert refused.value.code == "campaign_still_running"


# --- the opening test ---------------------------------------------------------------------


async def test_the_stronger_opening_wins_on_its_own_keeping_the_notices_and_can_be_undone() -> None:
    account = await _account()
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE organizations SET notice_ai_enabled = true, "
                "notice_recording_enabled = true WHERE id = :t"
            ),
            {"t": account.tenant_id},
        )
    campaign_id = await _campaign(account, status="running")
    await _with_test(account, campaign_id)
    await _opening_trial(account, campaign_id, side="a", answered=400, stayed=180, first=0)
    await _opening_trial(account, campaign_id, side="b", answered=400, stayed=260, first=5000)
    async with tenant_session(account.tenant_id) as session:
        run = await improve.run_improve(session, campaign_id)
    assert run.opening_applied is True
    row = await _one(
        account.tenant_id,
        "SELECT script, opening_b, opening_test_result FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert row[0]["opening_line"] == SECOND_OPENING and row[1] is None
    assert row[2]["winner"] == "b" and row[2]["applied"] is True
    async with tenant_session(account.tenant_id) as session:
        speaker = await campaign_agent_row(
            session, tenant_id=account.tenant_id, campaign_id=campaign_id
        )
        notices = await improve.recent_notices(session, limit=10)
    fields = notice_fields(posture_of(speaker), call_is_recorded=True)
    words = campaign_first_words(speaker, SECOND_OPENING, call_is_recorded=True)
    assert fields["ai_notice"].strip(), "the fixture agent has its AI notice switched on"
    assert first_words_disclose(
        words,
        ai_notice=fields["ai_notice"],
        recording_notice=fields["opening_line"].removeprefix(fields["ai_notice"]).strip(),
    )
    name = (
        await _one(account.tenant_id, "SELECT name FROM campaigns WHERE id = :c", c=campaign_id)
    )[0]
    assert [n.title for n in notices if n.campaign_id == campaign_id] == [
        f"{name}: the second opening won"
    ]
    async with tenant_session(account.tenant_id) as session:
        await improve.undo_opening(session, campaign_id)
    row = await _one(account.tenant_id, "SELECT script FROM campaigns WHERE id = :c", c=campaign_id)
    assert row[0]["opening_line"] == OWN_OPENING


async def test_the_scripts_own_opening_winning_ends_the_test_without_changing_it() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    await _with_test(account, campaign_id)
    await _opening_trial(account, campaign_id, side="a", answered=400, stayed=260, first=0)
    await _opening_trial(account, campaign_id, side="b", answered=400, stayed=180, first=5000)
    async with tenant_session(account.tenant_id) as session:
        assert (await improve.run_improve(session, campaign_id)).opening_applied is False
    row = await _one(
        account.tenant_id,
        "SELECT script, opening_b, opening_test_result FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert row[0]["opening_line"] == OWN_OPENING and row[1] is None
    assert row[2]["winner"] == "a"


async def test_too_few_answered_people_decide_nothing() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    await _with_test(account, campaign_id)
    await _opening_trial(account, campaign_id, side="a", answered=100, stayed=20, first=0)
    await _opening_trial(account, campaign_id, side="b", answered=100, stayed=90, first=5000)
    async with tenant_session(account.tenant_id) as session:
        assert (await improve.run_improve(session, campaign_id)).opening_applied is False
    row = await _one(
        account.tenant_id, "SELECT opening_b FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert row[0] == SECOND_OPENING


async def test_a_small_list_is_told_so_and_gets_the_practice_comparison() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=40)
    async with tenant_session(account.tenant_id) as session:
        size = await learning.list_size(session, campaign_id)
    assert size.people == 40 and size.large_enough is False
    assert size.answered_needed == 2 * learning.MIN_ANSWERED_PER_OPENING
    compared = improve.practice_compare(
        "Hello, this is Asha from Sri Ram Stores. Is this a good time?",
        "Hello [name] — this is Asha / Sri Ram Stores (calling now)",
        language="en-IN",
    )
    assert compared.fewer == "a"
    assert compared.second.mistakes and not compared.own.mistakes


async def test_pip_is_asked_once_per_campaign_and_bucket_and_only_with_work() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    async with tenant_session(account.tenant_id) as session:
        assert not await improve.queue_improve(
            session, tenant_id=account.tenant_id, campaign_id=campaign_id
        )
    await _with_test(account, campaign_id)
    async with tenant_session(account.tenant_id) as session:
        assert await improve.queue_improve(
            session, tenant_id=account.tenant_id, campaign_id=campaign_id
        )
        assert not await improve.queue_improve(
            session, tenant_id=account.tenant_id, campaign_id=campaign_id
        )


# --- another account ----------------------------------------------------------------------


async def test_another_account_sees_and_moves_nothing() -> None:
    owner, other = await _account(), await _account()
    campaign_id = await _campaign(owner, status="running")
    await _best_hours_data(owner, campaign_id)
    async with tenant_session(owner.tenant_id) as session:
        await improve.apply_best_hours(session, campaign_id, by="owner")
    async with tenant_session(other.tenant_id) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM campaigns WHERE best_hours_applied IS NOT NULL")
            )
        ).scalar()
        rates = await learning.answer_rate_by_hour(session, campaign_id)
        notices = await improve.recent_notices(session, limit=10)
        for move in (
            improve.undo_best_hours(session, campaign_id),
            improve.set_best_hours_auto(session, campaign_id, on=True),
            improve.set_retry_spread(session, campaign_id, on=False),
            improve.undo_opening(session, campaign_id),
        ):
            with pytest.raises(ProblemError) as refused:
                await move
            assert refused.value.kind == "not_found"
    assert seen == 0 and rates == [] and notices == []


# --- the dispatcher honours the spread retry, and the DNC check before it ------------------


async def _retry_waiting(tenant_id: uuid.UUID, campaign_id: uuid.UUID, *, due_in: str) -> None:
    async with tenant_session(tenant_id) as session:
        await campaigns_service.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
        await session.execute(
            text(
                "UPDATE campaign_contacts SET attempts = 1, last_attempt_at = now() - "
                "interval '3 hours', next_attempt_at = now() + CAST(:due AS interval) "
                "WHERE campaign_id = :c"
            ),
            {"c": campaign_id, "due": due_in},
        )


async def _dialled(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> tuple[str, list[str]]:
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaign_contacts WHERE campaign_id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
        placed = (
            (
                await session.execute(
                    text("SELECT to_e164 FROM calls WHERE campaign_id = :c"), {"c": campaign_id}
                )
            )
            .scalars()
            .all()
        )
    return str(status), [str(p) for p in placed]


async def test_the_tick_waits_for_a_spread_retry_that_is_not_due() -> None:
    tenant_id, _, campaign_id = await _ready_campaign(phones=("9876500001",))
    await _retry_waiting(tenant_id, campaign_id, due_in="2 hours")
    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})
    assert await _dialled(tenant_id, campaign_id) == ("pending", [])


async def test_a_due_retry_is_checked_against_the_dnc_list_before_it_dials() -> None:
    tenant_id, _, campaign_id = await _ready_campaign(phones=("9876500001",))
    await _retry_waiting(tenant_id, campaign_id, due_in="-1 minute")
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(
            session, tenant_id=tenant_id, phone_e164="+919876500001", source="in_call_optout"
        )
    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})
    assert await _dialled(tenant_id, campaign_id) == ("dnc_blocked", [])
