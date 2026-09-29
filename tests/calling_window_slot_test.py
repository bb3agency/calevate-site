"""The call-back slot resolver, and the one thing it refuses to guess (D-514).

**GETTING A TIME WRONG RINGS SOMEBODY AT 4AM.** `resolve_slot` is what the in-call booking
tool (`apps/api/worker/tools.book_callback`) runs before anything else: it refuses a time
with no full date, every hour before the calling window opens (so "four" heard as 04:00
cannot be booked at all), and a time already gone or too far ahead, and it hands back an
unambiguous spoken form for the agent to read out. Pure, so it is tested without a route.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

from calevate_shared.calling_window import (
    DEFAULT_WINDOW,
    IST,
    MAX_AHEAD,
    SLOT_REFUSALS,
    Slot,
    SlotRefusal,
    resolve_slot,
    within_window,
)

#: 11:30 IST on a Wednesday.
NOW = datetime(2026, 9, 2, 6, 0, tzinfo=UTC)


def test_a_time_with_no_full_date_is_refused_and_never_guessed() -> None:
    """ "Tuesday at four" is ambiguous in two directions and both are resolved by the MODEL,
    in conversation, before this is reached. What arrives here is already a decision, and
    this function's job is to refuse the ones we may not act on."""
    for date_text, time_text in (
        (None, "16:00"),
        ("2026-09-08", None),
        ("next tuesday", "16:00"),
        ("2026-09-08", "four in the afternoon"),
    ):
        refusal = resolve_slot(date_text, time_text, now=NOW)
        assert isinstance(refusal, SlotRefusal)
        assert refusal.code == "unreadable_time"


def test_every_hour_before_the_window_opens_is_unbookable() -> None:
    """THE 4AM TEST, and it is structural rather than careful: the model mis-hearing
    "four" as 04:00 produces a time this function cannot book at all, so the expensive half
    of the ambiguity has no path through the product."""
    for hour in range(0, 9):
        refusal = resolve_slot("2026-09-08", f"{hour:02d}:00", now=NOW)
        assert isinstance(refusal, SlotRefusal), f"{hour:02d}:00 IST was bookable"
        assert refusal.code == "outside_calling_hours"
        # AND IT OFFERS A REAL ALTERNATIVE rather than asking an open question the caller
        # has already answered.
        assert refusal.alternative is not None
        assert within_window(refusal.alternative.at_ist, DEFAULT_WINDOW)


def test_the_window_is_half_open_at_both_ends() -> None:
    """D-311's boundary, and a third comparison written the obvious way would have put it
    back one function along: 09:00:00 is inside, 21:00:00 is the first forbidden instant."""
    start, end = DEFAULT_WINDOW
    assert start == time(9, 0) and end == time(21, 0)
    assert isinstance(resolve_slot("2026-09-08", "09:00", now=NOW), Slot)
    assert isinstance(resolve_slot("2026-09-08", "20:59", now=NOW), Slot)
    refusal = resolve_slot("2026-09-08", "21:00", now=NOW)
    assert isinstance(refusal, SlotRefusal) and refusal.code == "outside_calling_hours"


def test_a_time_already_gone_and_a_time_a_year_away_are_both_refused() -> None:
    past = resolve_slot("2026-09-01", "16:00", now=NOW)
    assert isinstance(past, SlotRefusal) and past.code == "too_soon"
    far = resolve_slot((NOW + MAX_AHEAD + timedelta(days=2)).strftime("%Y-%m-%d"), "16:00", now=NOW)
    assert isinstance(far, SlotRefusal) and far.code == "too_far_ahead"


def test_the_spoken_form_a_caller_hears_back_cannot_be_misread() -> None:
    """A numeric date is the 9th of August to half the world, and a 24-hour clock is not
    what the caller said. Weekday and month NAME, 12-hour clock with AM/PM."""
    slot = resolve_slot("2026-09-08", "16:00", now=NOW)
    assert isinstance(slot, Slot)
    assert slot.spoken == "Tuesday 8 September at 4:00 PM"
    # UTC in, IST out (repo convention). 16:00 IST is 10:30 UTC.
    assert slot.at_utc == datetime(2026, 9, 8, 10, 30, tzinfo=UTC)
    assert slot.at_ist == slot.at_utc + IST


def test_the_refusal_vocabulary_is_closed() -> None:
    """The booking tool, these tests and the agent's function description have to be
    provably talking about one set — a fifth code would be a code nobody had written a
    sentence for."""
    seen = {
        resolve_slot(*args, now=NOW).code  # type: ignore[union-attr]
        for args in (
            (None, "16:00"),
            ("2026-09-01", "16:00"),
            ((NOW + MAX_AHEAD + timedelta(days=2)).strftime("%Y-%m-%d"), "16:00"),
            ("2026-09-08", "04:00"),
        )
    }
    assert seen == SLOT_REFUSALS
