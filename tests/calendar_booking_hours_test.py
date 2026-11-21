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
    spoken_time,
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


# --- per-weekday hours, in the business profile's shape -------------------------------------

WEEK = {
    "mon": {"opens": "09:00", "closes": "18:00"},
    "tue": {"opens": "09:00", "closes": "18:00"},
    "sat": {"opens": "10:00", "closes": "14:00"},
    "sun": None,
}


def test_each_day_keeps_its_own_hours_and_an_unlisted_day_takes_none() -> None:
    config = _config(hours=WEEK)
    assert within_booking_hours(config, _ist(13, 17), _ist(13, 18))  # Tuesday
    assert within_booking_hours(config, _ist(17, 10), _ist(17, 11))  # Saturday
    assert not within_booking_hours(config, _ist(17, 15), _ist(17, 16))  # Saturday afternoon
    assert not within_booking_hours(config, _ist(14, 10), _ist(14, 11))  # Wednesday, unlisted
    assert not within_booking_hours(config, _ist(18, 10), _ist(18, 11))  # Sunday, closed
    assert booking_hours_text(config) == (
        "Monday, Tuesday from 09:00 to 18:00; Saturday from 10:00 to 14:00, India time"
    )


def test_an_overnight_window_runs_into_the_next_day() -> None:
    config = _config(hours={"fri": {"opens": "18:00", "closes": "02:00"}})
    assert within_booking_hours(config, _ist(16, 23, 30), _ist(17, 0, 30))  # Fri night
    assert within_booking_hours(config, _ist(17, 1), _ist(17, 2))  # Sat early, Friday's window
    assert not within_booking_hours(config, _ist(17, 1, 30), _ist(17, 2, 30))
    assert not within_booking_hours(config, _ist(17, 19), _ist(17, 20))  # Saturday evening


def test_a_whole_day_is_any_time_of_that_day() -> None:
    config = _config(hours={"sun": {"opens": "00:00", "closes": "00:00"}})
    assert within_booking_hours(config, _ist(18, 0), _ist(18, 1))
    assert within_booking_hours(config, _ist(18, 23), _ist(19, 0))
    assert not within_booking_hours(config, _ist(19, 9), _ist(19, 10))  # Monday
    assert booking_hours_text(config) == "Sunday at any time of day, India time"


@pytest.mark.parametrize(
    "extra",
    [
        {"hours": {"mon": {"opens": "09:00"}}},
        {"hours": {"mon": None}},
        {"hours": {"funday": {"opens": "09:00", "closes": "18:00"}}},
        {"hours": WEEK, "opens": "09:00", "closes": "18:00"},
        {"hours": WEEK, "open_days": [1]},
    ],
)
def test_per_day_hours_that_cannot_be_kept_are_refused(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        _config(**extra)


def test_a_saved_one_window_action_still_loads_and_reads_the_same() -> None:
    config = _config(opens="09:00", closes="18:00", open_days=[1, 2, 3, 4, 5, 6])
    assert config.hours is None
    assert CalendarConfig.model_validate(config.model_dump()) == config


# --- the spoken words come from `spoken_style.json`, English until a language is written -----


def test_times_are_said_in_english_until_the_language_is_written() -> None:
    at = _ist(13, 16)
    english = spoken_time(at)
    assert english == "Tuesday 13 October, 4:00 PM"
    assert spoken_time(at, "te-IN") == english
    assert spoken_time(at, "hi-IN") == english
    assert spoken_time(at, None) == english
    assert spoken_time(_ist(13, 0, 5)) == "Tuesday 13 October, 12:05 AM"
    config = _config(opens="09:00", closes="18:00")
    assert booking_hours_text(config, "te-IN") == booking_hours_text(config)


def test_every_language_row_is_either_complete_or_marked_missing() -> None:
    from calevate_shared import spoken_style

    raw = spoken_style._raw()["languages"]
    for tag, row in raw.items():
        block = row.get("spoken_dates")
        assert isinstance(block, dict), tag
        if tag == spoken_style.SPOKEN_DATES_FALLBACK:
            assert spoken_style._spoken_dates_of(block) is not None
        else:
            assert block.get("missing"), tag


def test_the_english_templates_take_exactly_their_fields() -> None:
    import string

    from calevate_shared import spoken_style

    words = spoken_style.spoken_dates(spoken_style.SPOKEN_DATES_FALLBACK)
    for key, fields in spoken_style.SPOKEN_DATE_TEMPLATES.items():
        named = {f for _, f, _, _ in string.Formatter().parse(words.templates[key]) if f}
        assert named == fields, key


def test_a_language_with_written_words_is_said_in_them(monkeypatch: pytest.MonkeyPatch) -> None:
    from calevate_shared import spoken_style

    english = spoken_style.spoken_dates("en-IN")
    written = spoken_style.SpokenDates(
        weekdays=tuple(f"D{n}" for n in range(1, 8)),
        months=tuple(f"M{n}" for n in range(1, 13)),
        meridiem=("am", "pm"),
        templates={
            **english.templates,
            "moment": "{day} {month} {weekday} {hour}.{minute}{meridiem}",
        },
        list_separator=" / ",
        group_separator=" | ",
    )
    real = spoken_style.spoken_dates
    monkeypatch.setattr(
        "apps.api.actions.execution.spoken_dates",
        lambda tag: written if tag == "xx-IN" else real(tag),
    )
    assert spoken_time(_ist(13, 16), "xx-IN") == "13 M10 D2 4.00pm"
