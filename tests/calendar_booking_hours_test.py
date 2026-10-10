"""A calendar action's booking hours are a rule the server keeps, not only a sentence the
agent is told (D-700 follow-up, redesign #2).

Hours and days are in India time. A booking outside them is refused before the calendar is
asked; an availability check offers only free times inside them.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from apps.api.actions import in_call
from apps.api.actions.execution import (
    ExecutionResult,
    booking_hours_text,
    free_slots,
    within_booking_hours,
)
from apps.api.actions.schema import CalendarConfig
from pydantic import ValidationError

IST = timezone(timedelta(hours=5, minutes=30))
BASE = {"operation": "book", "start_param": "time", "duration_min": 60}


def _config(**extra: object) -> CalendarConfig:
    return CalendarConfig.model_validate({**BASE, **extra})


def _ist(day: int, hour: int, minute: int = 0) -> datetime:
    # 13 Oct 2026 is a Tuesday.
    return datetime(2026, 10, day, hour, minute, tzinfo=IST)


def test_no_hours_means_any_time_as_before() -> None:
    config = _config()
    assert within_booking_hours(config, _ist(13, 23), _ist(13, 23, 59))
    assert booking_hours_text(config) == "at any time of day, every day"


def test_a_booking_inside_the_hours_is_allowed_and_one_past_closing_is_not() -> None:
    config = _config(opens="09:00", closes="18:00")
    assert within_booking_hours(config, _ist(13, 9), _ist(13, 10))
    assert within_booking_hours(config, _ist(13, 17), _ist(13, 18))
    assert not within_booking_hours(config, _ist(13, 17, 30), _ist(13, 18, 30))
    assert not within_booking_hours(config, _ist(13, 8), _ist(13, 9))


def test_the_hours_are_india_time_whatever_zone_the_instant_carries() -> None:
    config = _config(opens="09:00", closes="18:00")
    start = _ist(13, 10).astimezone(UTC)
    assert within_booking_hours(config, start, start + timedelta(hours=1))


def test_a_closed_day_refuses_any_time() -> None:
    config = _config(opens="09:00", closes="18:00", open_days=[1, 2, 3, 4, 5, 6])
    assert within_booking_hours(config, _ist(13, 10), _ist(13, 11))  # Tuesday
    assert not within_booking_hours(config, _ist(18, 10), _ist(18, 11))  # Sunday
    assert booking_hours_text(config) == (
        "from 09:00 to 18:00 India time, on Monday, Tuesday, Wednesday, Thursday, Friday, Saturday"
    )


def test_a_booking_across_midnight_is_never_inside() -> None:
    config = _config(opens="00:00", closes="23:59")
    assert not within_booking_hours(config, _ist(13, 23, 30), _ist(14, 0, 30))


@pytest.mark.parametrize(
    "extra",
    [
        {"opens": "09:00"},
        {"closes": "18:00"},
        {"opens": "18:00", "closes": "09:00"},
        {"opens": "9:00", "closes": "18:00"},
        {"opens": "09:00", "closes": "24:00"},
        {"open_days": [0]},
        {"open_days": [1, 1]},
        {"open_days": []},
    ],
)
def test_hours_that_cannot_be_kept_are_refused_at_save(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _config(**extra)


def test_free_times_are_offered_only_inside_the_hours() -> None:
    config = _config(opens="09:00", closes="12:00")
    slots = free_slots(
        window_start=_ist(13, 8),
        window_end=_ist(13, 14),
        minutes=60,
        busy=[(_ist(13, 10), _ist(13, 11))],
        allowed=lambda start, end: within_booking_hours(config, start, end),
    )
    assert [s.astimezone(IST).hour for s in slots] == [9, 11]


def test_the_agent_is_told_the_hours_and_todays_date() -> None:
    result = ExecutionResult(
        ok=False,
        payload={"error": "outside_hours", "hours": "from 09:00 to 18:00 India time, every day"},
        status="outside_hours",
    )
    said = in_call.say_for(result, now=datetime(2026, 10, 13, 6, 0, tzinfo=UTC))
    assert "Do NOT say it is booked" in said
    assert "It takes bookings from 09:00 to 18:00 India time, every day." in said
    assert "2026-10-13" in said
