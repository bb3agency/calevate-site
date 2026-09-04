"""The live USD→INR rate, in every process, without a database round trip.

`Settings.usd_inr_rate` is a number a human typed. This module is the number a machine
pulled, and it exists because the two answer different questions: the configured one is
what this deployment DECIDED the rate is, the pulled one is what the rate WAS at a
published instant. Money uses the pulled one while it is fresh and the configured one
when it is not, and every converted figure records which.

## Why a holder in `core/` with no IO in it

The conversion happens inside `engine/bolna.py::_cost`, which is SYNCHRONOUS: it hangs
off `_snapshot`, which every adapter also reaches from the `VoiceEngine` protocol's
`parse_webhook` — a normalizer that must stay IO-free, because the deployable that owns
webhooks may not touch a database on that path (hard rule 3). A sync reader physically
cannot await a query, so the rate has to already be in memory when it is asked for.
That is the same argument `core/settings.py` makes for
`_platform_overrides` and `ops/pricing_snapshot.py` makes for the attested prices, and
this module is deliberately the same shape as the first of those: **core owns nothing
but the holder, `apps/api/ops/fx_rates.py` owns the IO**, so the dependency runs one way
(ops → core) and the adapter reaches the rate through an import it already has.

## The ceiling is enforced HERE, on the read, and that is the whole safety property

A refresher that dies leaves the last quote installed for ever. If usability were
decided when the quote was installed, a dead poller in one process would bill months of
calls at a rate nobody could see going stale — the silent failure this feature exists to
prevent. So `current_fx_quote()` re-decides on every read against `MAX_QUOTE_AGE`, which
makes "money never converts at a rate older than the ceiling" true of the PROCESS rather
than true of the refresher's liveness. Past the ceiling the reader returns `None`, the
caller falls back to its configured rate, and `ops/fx_rates.py` is what makes the
fallback audible to an operator.

## The pin, and why it is not a second mechanism

`settings_scope()` pins `Settings` for a unit of work so a job cannot read one value at
the start and another at the end. A rate has exactly that problem and worse — a call
costed at two rates is a WRONG number in an append-only ledger, not a stale one — so
`fx_scope()` is the identical gesture over this holder, entered in the same place
(`apps/workers/settings.py::on_job_start`) and released by the same hook. It resolves
once, including the usability decision, so a unit of work that started under a fresh
quote finishes under it even if the quote ages out or the refresher swaps it mid-job.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final

#: How old the SOURCE's own publication date may be before money stops using the pulled
#: rate. Five days, and the number is a property of the source's cadence rather than a
#: comfort setting: the reference rates this product pulls (Financial Benchmarks India,
#: and the ECB behind it) are published ONCE PER BUSINESS DAY, so a legitimately current
#: quote is routinely two days old over a weekend and three over a long one. Five days
#: covers a weekend plus a two-day national holiday — the longest realistic publication
#: gap on the Indian calendar — and refuses anything beyond it, which is a feed that has
#: actually stopped.
#:
#: Rejected: a ceiling in HOURS, matching the five-minute pull. It would put the platform
#: on the configured fallback every Sunday, i.e. it would treat the source working
#: normally as an incident, and an alarm that fires every weekend is one nobody reads.
#: The pull cadence and the data cadence are different facts and are bounded separately —
#: `apps/workers/fx_pull.py::MAX_PULL_SILENCE` is the other half.
MAX_QUOTE_AGE = timedelta(days=5)


@dataclass(frozen=True, slots=True)
class FxQuote:
    """One published USD→INR observation, with the provenance to explain it later.

    `rate` is INR per ONE US dollar, as a `Decimal` (hard rule 7). It never passes
    through a float anywhere in this system: the pull parses the vendor's JSON number
    from its TEXT form, and it reaches the ledger as a string.
    """

    #: INR per 1 USD.
    rate: Decimal
    #: The date the SOURCE stamped on this rate — not the date we fetched it. A daily
    #: reference rate fetched five times an hour has one `as_of` and five fetches.
    as_of: date
    #: Who published it, in the form `"<api>:<provider>"` (e.g. `"frankfurter:FBIL"`).
    #: Recorded on every converted row, because "which rate" is only half of what a
    #: reconciliation six months later needs to know.
    source: str
    #: When THIS deployment last saw it. Bounds the poller, not the data.
    observed_at: datetime

    def age(self, now: datetime | None = None) -> timedelta:
        """How old the PUBLICATION is, measured from the end of its own day.

        A rate published today is age zero all day: `as_of` is a date, and treating it as
        midnight would make every afternoon's fresh quote look half a day stale.
        """
        moment = now or datetime.now(UTC)
        published_through = datetime.combine(self.as_of, datetime.max.time(), tzinfo=UTC)
        return max(moment - published_through, timedelta(0))

    def usable(self, now: datetime | None = None) -> bool:
        """Whether money may convert at this rate. See `MAX_QUOTE_AGE`."""
        return self.age(now) <= MAX_QUOTE_AGE


@dataclass(frozen=True, slots=True)
class UsdInrRate:
    """The rate one conversion used, with enough provenance to re-derive it later.

    THREE FIELDS BECAUSE THE ROW NEEDS THREE. A rupee in an append-only ledger cannot be
    corrected in place (hard rule 4), so the only way a wrong conversion is ever explained
    is that the row says which rate and whose. `as_of` is None exactly when the configured
    rate was used — a typed number has no publication date, and inventing today's would
    make a stale fallback look like a fresh reading.
    """

    rate: Decimal
    source: str
    as_of: date | None


#: What this process last installed, fresh or not. `None` = nothing has ever been pulled
#: here, which is the honest cold-start state and the one every deployment is in until
#: the first tick lands.
_installed: FxQuote | None = None

#: The quote pinned for the unit of work running on this task, if any. The outer
#: `tuple[...]` distinguishes "pinned to no usable quote" from "not inside a scope" —
#: without it a job that opened under a stale feed would silently start reading whatever
#: the refresher installed halfway through, which is the straddle the scope prevents.
_pinned: ContextVar[tuple[FxQuote | None] | None] = ContextVar("calevate_fx_pin", default=None)


def install_fx_quote(quote: FxQuote | None) -> None:
    """Publish what the store last said. Called by `ops/fx_rates.py` off the request path.

    A pin already open deliberately survives this, exactly as `apply_platform_overrides`
    leaves an open `settings_scope()` alone: the scope holds a resolved value, not a
    pointer into this module, so work already in flight keeps the rate it started with.
    """
    global _installed
    _installed = quote


def current_fx_quote(now: datetime | None = None) -> FxQuote | None:
    """The rate money may convert at, or `None` to fall back to the configured one.

    Zero IO, so it is legal on voice-runtime's request path (hard rule 3). Inside
    `fx_scope()` this returns the answer resolved when that scope opened.
    """
    pin = _pinned.get()
    if pin is not None:
        return pin[0]
    quote = _installed
    return quote if quote is not None and quote.usable(now) else None


#: What a converted figure records when nothing was published and the CONFIGURED rate was
#: used instead. A source string rather than a null, because "we converted at the
#: operator's typed rate" and "we do not know what we converted at" are different facts and
#: only the first one is recoverable six months later.
CONFIGURED_FX_SOURCE: Final = "configured:usd_inr_rate"


def usd_inr_rate_now(configured: Decimal, now: datetime | None = None) -> UsdInrRate:
    """The rate a dollar figure converts at RIGHT NOW, and where it came from.

    **ONE SPELLING OF THE FALLBACK RULE, for every writer of money.** It was written twice
    — once inside `engine/bolna.py::_conversion_rate` for a call's cost, and again the day
    a recurring number rental needed converting (D-535) — and two copies of "use the
    published rate while it is fresh, else the operator's typed one" is two places the
    fallback can quietly stop happening. The engine adapter still owns the question this
    does NOT answer: whether the vendor quoted in dollars at all.

    Zero IO, so it stays legal on voice-runtime's request path (hard rule 3), and inside
    `fx_scope()` it returns the quote that scope resolved — so a unit of work cannot
    convert two figures at two rates.

    The failure direction is "the platform converts as it did last release", never "the
    platform stops converting". It is not silent: `ops/fx_rates.refresh_fx_snapshot`
    alarms on a rate past its ceiling and `workers/fx_pull` alarms on a puller gone quiet.
    """
    quote = current_fx_quote(now)
    if quote is None:
        return UsdInrRate(rate=configured, source=CONFIGURED_FX_SOURCE, as_of=None)
    return UsdInrRate(rate=quote.rate, source=quote.source, as_of=quote.as_of)


@contextmanager
def fx_scope() -> Iterator[FxQuote | None]:
    """Resolve the rate ONCE for this unit of work and hold that answer to the end.

    Nested scopes reuse the outer pin, for `settings_scope()`'s reason: an inner unit of
    work is part of the outer one, and re-resolving would reintroduce the straddle.
    """
    existing = _pinned.get()
    if existing is not None:
        yield existing[0]
        return
    token = _pinned.set((current_fx_quote(),))
    try:
        pin = _pinned.get()
        yield pin[0] if pin is not None else None
    finally:
        _pinned.reset(token)


def reset_for_test() -> None:
    """Drop the installed quote. Test seam, named as one — the mirror of
    `platform_config.reset_for_test`, and used for the same reason: a quote leaking
    between cases would make one test's rate another test's money."""
    install_fx_quote(None)


__all__ = [
    "MAX_QUOTE_AGE",
    "FxQuote",
    "current_fx_quote",
    "fx_scope",
    "install_fx_quote",
    "reset_for_test",
]
