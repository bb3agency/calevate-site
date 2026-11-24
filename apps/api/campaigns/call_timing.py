"""When a campaign's calls ring: the day's calling window cut into fixed blocks, and the
instant a retry moves to so it rings at a different time of day than the try that failed.

The blocks are a fixed three-hour grid from the platform window's start (9am-12pm, 12-3pm,
3-6pm, 6-9pm IST), cut down to a campaign's own narrowed hours. Best hours
(`campaigns/learning.best_block`) and retry spreading read the same grid, so "the block
people answer in" and "a different time of day" mean the same thing on both cards. A fixed
grid rather than a sliding one: a sliding window chooses among many overlapping candidates,
which multiplies the chances of a lucky-looking pick, where four fixed blocks keep the
comparison count small enough to correct for (`learning.BLOCK_CHANCE`).

Every time here is IST wall clock (D-709); instants are timezone-aware.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final

from calevate_shared.calling_window import DEFAULT_WINDOW, IST

BLOCK_MINUTES: Final = 180
#: How many days ahead a spread retry is looked for before falling back to the plain gap.
SEARCH_DAYS: Final = 8


@dataclass(frozen=True, slots=True)
class Block:
    """A half-open stretch of the calling day, IST."""

    start: time
    end: time

    def contains(self, moment: time) -> bool:
        return self.start <= moment < self.end

    def hours(self) -> range:
        """The whole hours whose calls count towards this block (by the hour they started)."""
        last = self.end.hour if self.end.minute == 0 else self.end.hour + 1
        return range(self.start.hour, last)

    def as_window(self) -> dict[str, str]:
        """In `campaigns.calling_hours`'s stored shape."""
        return {"start": self.start.strftime("%H:%M"), "end": self.end.strftime("%H:%M")}


def _minutes(moment: time) -> int:
    return moment.hour * 60 + moment.minute


def _clock(minutes: int) -> time:
    return time(minutes // 60, minutes % 60)


def calling_window(calling_hours: dict[str, Any] | None) -> tuple[time, time] | None:
    """The platform window narrowed by the campaign's own hours, or None when the two do not
    overlap or the stored hours cannot be read (closed, as `service.campaign_window_open`)."""
    start, end = DEFAULT_WINDOW
    if not calling_hours:
        return start, end
    try:
        own_start = datetime.strptime(str(calling_hours["start"]), "%H:%M").time()
        own_end = datetime.strptime(str(calling_hours["end"]), "%H:%M").time()
    except (KeyError, TypeError, ValueError):
        return None
    start, end = max(start, own_start), min(end, own_end)
    return (start, end) if start < end else None


def grid_blocks() -> tuple[Block, ...]:
    """The platform window in fixed blocks of `BLOCK_MINUTES`."""
    start, end = (_minutes(t) for t in DEFAULT_WINDOW)
    return tuple(
        Block(_clock(at), _clock(min(at + BLOCK_MINUTES, end)))
        for at in range(start, end, BLOCK_MINUTES)
    )


def blocks_within(calling_hours: dict[str, Any] | None) -> list[Block]:
    """The grid cut to the campaign's window; empty when it has none."""
    window = calling_window(calling_hours)
    if window is None:
        return []
    low, high = (_minutes(t) for t in window)
    out = []
    for block in grid_blocks():
        start = max(_minutes(block.start), low)
        end = min(_minutes(block.end), high)
        if start < end:
            out.append(Block(_clock(start), _clock(end)))
    return out


def block_index(moment: time, blocks: list[Block]) -> int | None:
    return next((i for i, block in enumerate(blocks) if block.contains(moment)), None)


def spread_retry_at(
    *, failed_at: datetime, earliest: datetime, calling_hours: dict[str, Any] | None
) -> datetime:
    """The first instant at or after `earliest`, inside the campaign's calling window, in a
    different block of the day than `failed_at`. A window of one block has no other time
    of day, so the retry goes to a later day instead. `earliest` (the gap the policy asks
    for) is never shortened: spreading only ever waits longer.

    Falls back to `earliest` when nothing fits within `SEARCH_DAYS`; the dispatcher still
    holds every dial to the window, so the fallback only loses the spreading."""
    blocks = blocks_within(calling_hours)
    if not blocks:
        return earliest
    failed = failed_at.astimezone(IST)
    failed_block = block_index(failed.time(), blocks)
    start = earliest.astimezone(IST)
    for offset in range(SEARCH_DAYS):
        day: date = start.date() + timedelta(days=offset)
        for index, block in enumerate(blocks):
            opens = datetime.combine(day, block.start, IST)
            closes = datetime.combine(day, block.end, IST)
            candidate = max(opens, start)
            if candidate >= closes:
                continue
            other_time = day != failed.date() if len(blocks) == 1 else index != failed_block
            if other_time:
                return candidate.astimezone(UTC)
    return earliest


__all__ = [
    "BLOCK_MINUTES",
    "Block",
    "block_index",
    "blocks_within",
    "calling_window",
    "grid_blocks",
    "spread_retry_at",
]
