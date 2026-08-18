"""The calling window's own edges (D-311).

TCCCPR 2018 states the rule as a PROHIBITION — no commercial communication between 2100
and 0900 hours — so the two ends are not symmetrical: 09:00:00 is the first instant
outside the forbidden band and 21:00:00 is the first instant inside it. Both gates that
own a window (`compliance.service.within_calling_hours`, the platform's; and
`campaigns.service.campaign_window_open`, the campaign's narrowing of it) are asserted
here at the second, because that is where an inclusive comparison and a half-open one
differ and nowhere else — and the difference is a dial placed at 21:00 that a
subscriber's complaint would timestamp as such.
"""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest
from apps.api.campaigns.service import campaign_window_open
from apps.api.compliance.service import DEFAULT_WINDOW, within_calling_hours

IST = timedelta(hours=5, minutes=30)


def _ist(hour: int, minute: int, second: int = 0, micro: int = 0) -> datetime:
    """An instant already expressed in IST wall clock, the way `ist_now` returns one."""
    return datetime(2026, 8, 18, hour, minute, second, micro, tzinfo=UTC)


@pytest.mark.parametrize(
    ("moment", "open_"),
    [
        (_ist(8, 59, 59), False),
        (_ist(9, 0, 0), True),  # the window OPENS on 09:00:00
        (_ist(20, 59, 59, 999999), True),
        (_ist(21, 0, 0), False),  # ... and is already shut on 21:00:00
        (_ist(21, 0, 1), False),
    ],
)
def test_the_platform_window_is_half_open_at_the_top(moment: datetime, open_: bool) -> None:
    assert within_calling_hours(moment) is open_


@pytest.mark.parametrize(
    ("moment", "open_"),
    [
        (_ist(9, 0, 0), True),
        (_ist(11, 59, 59), True),
        (_ist(12, 0, 0), False),
    ],
)
def test_a_narrowed_campaign_window_closes_on_its_own_end(moment: datetime, open_: bool) -> None:
    assert campaign_window_open({"start": "09:00", "end": "12:00"}, moment) is open_


def test_the_two_windows_agree_at_the_platform_edge() -> None:
    """A campaign that names the platform's own hours must not out-permit the platform.

    The two functions are separate — one is per dial and one is per campaign — so the
    only thing stopping them drifting is an assertion that they answer the same question
    the same way at the one instant where a convention shows.
    """
    start, end = DEFAULT_WINDOW
    assert (start, end) == (time(9, 0), time(21, 0))
    edge = _ist(21, 0, 0)
    assert within_calling_hours(edge) is False
    assert campaign_window_open({"start": "09:00", "end": "21:00"}, edge) is False
