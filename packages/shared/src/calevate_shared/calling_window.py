"""THE ONE answer to "may we telephone somebody at this instant", for every deployable.

`IST` and `DEFAULT_WINDOW` were defined in `apps/api/compliance/service.py` and could not
leave it: hard rule 3 forbids `apps/voice-runtime` importing a business module, and
`tests/voice_runtime_import_surface_test.py` enforces that by booting the service and
reading `sys.modules`. So the in-call tool that BOOKS a callback — which has to tell a
caller "we cannot ring you at ten at night" while they are still on the phone — had a
choice between a second spelling of the window and not answering at all. Both are wrong:
a second spelling of a legal boundary is the "one way per problem" defect on the one
constant in this repo where the two copies disagreeing means dialling a household at
04:00.

So the constants moved here and `compliance.service` imports them. Nothing else changed:
`within_calling_hours`, `campaigns.scheduling` and `campaigns.service` all still read the
same two objects, from the same names, and this module imports nothing but the standard
library so it costs the ack path one dict lookup and no IO.

WHAT ELSE IS HERE, AND WHY IT IS HERE RATHER THAN IN THE ROUTE
--------------------------------------------------------------------------------------
`resolve_slot` turns "the model heard 2026-09-08 and 16:00" into either a lawful instant
or a refusal a person can act on. It is pure arithmetic over two short strings, which is
what makes it legal on the 100ms in-call budget (TRD §6.2) — and it must run THERE rather
than in the worker behind it, because a refusal that arrives after the caller has hung up
is not a refusal, it is a broken promise. See `apps/voice-runtime/tool_routes.py`.

THE HALF-OPEN WINDOW IS THE SAME HALF-OPEN WINDOW (D-311). `start <= t < end`: 09:00:00
is inside, 21:00:00 is the first forbidden instant. `compliance.within_calling_hours` and
`campaigns.scheduling.first_dial_not_before` were both corrected to it, and a third
comparison written the obvious way here would put the boundary back one function along.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta

#: India Standard Time as a fixed offset. India has no DST, so an offset is exact and a
#: `ZoneInfo` would be a second spelling that agrees with it — the repo's own convention
#: (`compliance.service.ist_now`, `campaigns.scheduling.first_dial_not_before`).
IST = timedelta(hours=5, minutes=30)

#: The platform calling window, IST wall clock (TRAI/TCCCPR; SEC-COMP §3). Half-open.
DEFAULT_WINDOW = (time(9, 0), time(21, 0))

#: How soon a booked callback may be. A caller who says "call me back in a minute" is
#: asking for something the tick cannot promise (it runs every 30 seconds and the dial
#: takes a round trip), and a slot already in the past is a slot the dispatcher fires
#: immediately — which is not what "call me at four" meant. Five minutes is long enough
#: that the tick and the engine have room and short enough that "call me in ten minutes"
#: still books.
MIN_LEAD = timedelta(minutes=5)

#: How far ahead a caller may book. The bound is `campaigns.scheduling.MAX_HORIZON`'s
#: argument in miniature — the failure it catches is a year typo — sized much shorter
#: because a promise made in a phone call decays: nobody remembers, three months later,
#: the conversation that produced the call they are now receiving. Thirty days.
MAX_AHEAD = timedelta(days=30)


def ist_wall_clock(moment: datetime) -> datetime:
    """`moment` as IST wall-clock time, still carrying UTC's tzinfo.

    The repo's convention (`+ IST`, compared naively, shifted back) rather than a
    localization: see `IST`. Callers use `.time()` and `.date()` off the result and never
    its offset, which is why the tzinfo is deliberately not rewritten.
    """
    return moment.astimezone(UTC) + IST


def within_window(moment_ist: datetime, window: tuple[time, time] = DEFAULT_WINDOW) -> bool:
    """Is this IST wall-clock instant inside the window? Half-open: `start <= t < end`."""
    start, end = window
    return start <= moment_ist.time() < end


def next_window_opening(
    moment_ist: datetime, window: tuple[time, time] = DEFAULT_WINDOW
) -> datetime:
    """The first instant at or after `moment_ist` that the window admits, in IST.

    Returns `moment_ist` unchanged when it is already inside. Before the window opens the
    answer is today's opening; at or after it closes, tomorrow's — which is the same walk
    `campaigns.scheduling.first_dial_not_before` makes, and it is deliberately duplicated
    in neither direction: that function answers for a CAMPAIGN and takes the campaign's
    own narrowed hours, this one answers for a person on a phone and only ever knows the
    platform window.
    """
    start, end = window
    if moment_ist.time() < start:
        return moment_ist.replace(hour=start.hour, minute=start.minute, second=0, microsecond=0)
    if moment_ist.time() >= end:
        return (moment_ist + timedelta(days=1)).replace(
            hour=start.hour, minute=start.minute, second=0, microsecond=0
        )
    return moment_ist


@dataclass(frozen=True, slots=True)
class Slot:
    """A time we are willing to ring somebody at, and the sentence that names it."""

    #: The instant, UTC, for the database (repo convention: timestamptz UTC in the DB).
    at_utc: datetime
    #: The same instant as IST wall clock, for anything a person reads.
    at_ist: datetime
    #: The unambiguous spoken form: "Tuesday 8 September at 4:00 PM". Weekday and month
    #: NAME, never a numeric date — "8/9" is the 9th of August to half the world — and a
    #: 12-hour clock with AM/PM, because that is what the caller said and what they will
    #: recognise when it is read back. The zone is not in the string: the caller is in
    #: India, the agent is speaking Indian time, and "IST" in a spoken sentence is noise.
    spoken: str


@dataclass(frozen=True, slots=True)
class SlotRefusal:
    """A time we will not book, and what the agent should offer instead.

    `say` is ENGLISH GUIDANCE FOR THE MODEL, not a script. The caller may be speaking
    Telugu or Hindi; Bolna feeds our response back to the agent's LLM, which "continues
    the conversation naturally"
    (`bolna-findings/mirror/pages/tool-calling/custom-function-calls.md:42-44`,
    VERIFIED-VENDOR-DOCS), so the model renders this into the caller's own language. What
    we must not do is send back a bare error: the vendor's own troubleshooting section
    treats an error response as a misconfiguration, and the caller would hear nothing
    useful.
    """

    code: str
    say: str
    #: For `outside_calling_hours` only: the nearest lawful slot, so the agent can offer a
    #: real alternative instead of asking an open question the caller has already answered.
    alternative: Slot | None = None


#: Every refusal `resolve_slot` can give. Enumerated so the tool route, the tests and the
#: agent's function description are provably talking about the same set — the vocabulary a
#: caller can hit is small, and a route that invented a fifth code would be a code nobody
#: had written a sentence for.
SLOT_REFUSALS: frozenset[str] = frozenset(
    {"unreadable_time", "too_soon", "too_far_ahead", "outside_calling_hours"}
)


def _spoken(at_ist: datetime) -> str:
    hour = at_ist.hour % 12 or 12
    meridiem = "AM" if at_ist.hour < 12 else "PM"
    # `%-d`/`%-I` are platform-dependent; the arithmetic above is not.
    return f"{at_ist:%A} {at_ist.day} {at_ist:%B} at {hour}:{at_ist:%M} {meridiem}"


def resolve_slot(
    date_text: str | None,
    time_text: str | None,
    *,
    now: datetime,
    window: tuple[time, time] = DEFAULT_WINDOW,
) -> Slot | SlotRefusal:
    """The one place a spoken callback time becomes an instant, or is refused.

    **IT REFUSES; IT NEVER GUESSES.** "Tuesday at 4" is ambiguous in two directions — which
    Tuesday, and which four — and both are resolved by the MODEL, in conversation with the
    caller, before this function is reached: the agent's function description requires a
    full calendar date and a 24-hour clock time, which is the established shape for
    handing a natural-language datetime to a machine (an absolute value with no relative
    words left in it). What arrives here is therefore already a decision, and this
    function's job is to refuse the decisions we may not act on rather than to repair them.

    **THE AM/PM FAILURE IS CLOSED STRUCTURALLY, NOT BY CARE.** The expensive mistake is
    "four" resolved as 04:00 — a phone ringing in a household before dawn. Every hour from
    00:00 to 08:59 is outside the calling window and is refused here, so the dangerous
    half of every am/pm ambiguity cannot be booked at all; the agent hears
    `outside_calling_hours`, is handed the next lawful time, and asks again. The harmless
    half (16:00 heard as 04:00 by a model) costs one more conversational turn. That
    asymmetry is the whole reason the window check lives at BOOKING time as well as at
    dial time.

    `now` is passed rather than read so this stays pure and testable — the same reason
    `client_address.client_ip` takes `app_env`.
    """
    if not date_text or not time_text:
        return SlotRefusal(
            code="unreadable_time",
            say=(
                "I did not catch the day and time. Ask the caller which day and what time "
                "suits them, then try again with the full date."
            ),
        )
    try:
        day = datetime.strptime(date_text.strip(), "%Y-%m-%d").date()
        clock = datetime.strptime(time_text.strip(), "%H:%M").time()
    except ValueError:
        return SlotRefusal(
            code="unreadable_time",
            say=(
                "I could not read that day and time. Ask the caller to say the day and the "
                "hour again, and be clear whether they mean morning or evening."
            ),
        )

    at_ist = datetime.combine(day, clock, tzinfo=UTC)
    at_utc = at_ist - IST
    now_utc = now.astimezone(UTC)

    if at_utc < now_utc + MIN_LEAD:
        return SlotRefusal(
            code="too_soon",
            say=(
                "That time has already gone by. Ask the caller for a later time, or offer "
                "to keep talking now."
            ),
        )
    if at_utc > now_utc + MAX_AHEAD:
        return SlotRefusal(
            code="too_far_ahead",
            say=(
                f"We only book callbacks up to {MAX_AHEAD.days} days ahead. Ask the caller "
                "for a nearer day."
            ),
        )
    if not within_window(at_ist, window):
        opens_ist = next_window_opening(at_ist, window)
        alternative = Slot(at_utc=opens_ist - IST, at_ist=opens_ist, spoken=_spoken(opens_ist))
        start, end = window
        return SlotRefusal(
            code="outside_calling_hours",
            say=(
                f"We are only allowed to ring people between {start:%H:%M} and {end:%H:%M}. "
                f"Offer the caller {alternative.spoken} instead, or ask for another time "
                "inside those hours."
            ),
            alternative=alternative,
        )
    return Slot(at_utc=at_utc, at_ist=at_ist, spoken=_spoken(at_ist))


__all__ = [
    "DEFAULT_WINDOW",
    "IST",
    "MAX_AHEAD",
    "MIN_LEAD",
    "SLOT_REFUSALS",
    "Slot",
    "SlotRefusal",
    "ist_wall_clock",
    "next_window_opening",
    "resolve_slot",
    "within_window",
]
