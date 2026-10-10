"""The live USD→INR rate, in every process, without a database round trip.

`Settings.usd_inr_rate` is a number a human typed. This module holds the number a machine
pulled, and the two answer different questions: the typed one is what somebody DECIDED
the rate is, the pulled one is what the rate WAS at a published instant. Every converted
figure records which one it used.

## The ladder: published, then last published, then typed

`resolve_usd_inr_rate` is the one spelling of it, and every reader reaches it through
`usd_inr_rate_now`:

1. **Manual override.** `Settings.usd_inr_rate_override` is on, so the typed
   `usd_inr_rate` is used whatever was published. An operator's explicit act, for the day
   a published source is believed wrong.
2. **Published, fresh.** The newest pulled quote, inside `MAX_QUOTE_AGE`.
3. **Published, stale.** The newest pulled quote past the ceiling. Still used, because a
   rate the market published a week ago is closer to today's than a number typed months
   ago, and it never updates itself. It is not silent: the row carries the quote's own
   `as_of`, so an old date is visible on every ledger row, and `ops/fx_rates` raises
   `fx_rate_stale` while it is in force.
4. **Typed, no quote.** Nothing has ever been pulled in this process (a fresh deployment,
   or a store this process cannot read). The typed rate is the only number there is.

The ceiling therefore decides what an operator is TOLD, not what money uses. Rejected:
reverting to the typed rate past the ceiling. That rule made a typed figure that nobody
maintains the rate of record exactly when the feed is down, which is the moment it is
least likely to be current.

## Why a holder in `core/` with no IO in it

A conversion can happen inside an adapter's SYNCHRONOUS snapshot builder, which every
adapter also reaches from the `VoiceEngine` protocol's `parse_webhook` — a normalizer that
must stay IO-free, because the deployable that owns webhooks may not touch a database on
that path (hard rule 3) — and inside request handlers pricing a number rental or a cost
preview. A sync reader physically cannot await a query, so the rate has to already be in
memory when it is asked for.
That is the same argument `core/settings.py` makes for
`_platform_overrides` and `ops/pricing_snapshot.py` makes for the attested prices, and
this module is deliberately the same shape as the first of those: **core owns nothing
but the holder, `apps/api/ops/fx_rates.py` owns the IO**, so the dependency runs one way
(ops → core) and the adapter reaches the rate through an import it already has.

## Staleness is decided HERE, on the read, and that is the safety property

A refresher that dies leaves the last quote installed for ever. If staleness were
decided when the quote was installed, a dead poller in one process would bill months of
calls at a rate nobody could see going stale. So `resolve_usd_inr_rate` re-decides on
every read against `MAX_QUOTE_AGE` and records the answer in `UsdInrRate.basis`, which
makes "a rate past the ceiling is labelled stale" true of the PROCESS rather than of the
refresher's liveness. `ops/fx_rates.py` makes the stale state audible to an operator.

## The pin, and why it is not a second mechanism

`settings_scope()` pins `Settings` for a unit of work so a job cannot read one value at
the start and another at the end. A rate has exactly that problem and worse — a call
costed at two rates is a WRONG number in an append-only ledger, not a stale one — so
`fx_scope()` is the identical gesture over this holder, entered in the same place
(`apps/workers/settings.py::on_job_start`) and released by the same hook. It pins the
quote once, so a unit of work that started under one quote finishes under it even if the
refresher swaps it mid-job; the override flag is pinned by the `settings_scope()` beside
it.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Final, Literal

from apps.api.core.settings import get_settings

#: How old the SOURCE's own publication date may be before the rate in force is reported
#: stale (`fx_rate_stale`, and `basis="stale_published"` on every conversion). Money keeps
#: using it; see the ladder above. Five days, and the number is a property of the source's
#: cadence rather than a comfort setting: the reference rates this product pulls
#: (Financial Benchmarks India, and the ECB behind it) are published ONCE PER BUSINESS
#: DAY, so a legitimately current quote is routinely two days old over a weekend and
#: three over a long one. Five days covers a weekend plus a two-day national holiday —
#: the longest realistic publication gap on the Indian calendar — and calls anything
#: beyond it stale, which is a feed that has actually stopped.
#:
#: Rejected: a ceiling in HOURS, matching the five-minute pull. It would report the rate
#: stale every Sunday, i.e. it would treat the source working normally as an incident,
#: and an alarm that fires every weekend is one nobody reads.
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
    #: Who published it, in the form `"<api>:<publication>"` — `"fbil:refrates"` for the
    #: preferred rung since D-609, and `"frankfurter:FBIL"` / `"frankfurter:default"` for
    #: the rungs below it. `workers/fx_pull.LADDER` is where the set is declared.
    #: Recorded on every converted row, because "which rate" is only half of what a
    #: reconciliation six months later needs to know.
    source: str
    #: When this deployment first stored it. Not when it was last checked: a repeat poll of
    #: one publication stores nothing (`ops/fx_rates.last_check` is the poller's clock).
    observed_at: datetime

    def age(self, now: datetime | None = None) -> timedelta:
        """How old the PUBLICATION is, measured from the end of its own day.

        A rate published today is age zero all day: `as_of` is a date, and treating it as
        midnight would make every afternoon's fresh quote look half a day stale.
        """
        moment = now or datetime.now(UTC)
        published_through = datetime.combine(self.as_of, datetime.max.time(), tzinfo=UTC)
        return max(moment - published_through, timedelta(0))

    def fresh(self, now: datetime | None = None) -> bool:
        """Whether this quote is inside `MAX_QUOTE_AGE`. Past it the quote is still used,
        labelled stale; see the ladder in the module docstring."""
        return self.age(now) <= MAX_QUOTE_AGE


#: The ladder's rungs (module docstring), in the words the ops panel and its tests use.
RateBasis = Literal["published", "stale_published", "manual_override", "manual_no_quote"]


@dataclass(frozen=True, slots=True)
class UsdInrRate:
    """The rate one conversion used, with enough provenance to re-derive it later.

    A rupee in an append-only ledger cannot be corrected in place (hard rule 4), so the
    only way a wrong conversion is ever explained is that the row says which rate and
    whose. `as_of` is None exactly when the typed rate was used: a typed number has no
    publication date, and inventing today's would make it look like a fresh reading.
    """

    rate: Decimal
    source: str
    as_of: date | None
    #: Which rung of the ladder (module docstring) produced `rate`.
    basis: RateBasis


#: What this process last installed, fresh or not. `None` = nothing has ever been pulled
#: here, which is the honest cold-start state and the one every deployment is in until
#: the first tick lands.
_installed: FxQuote | None = None

#: The quote pinned for the unit of work running on this task, if any. The outer
#: `tuple[...]` distinguishes "pinned to no quote" from "not inside a scope": without it a
#: job that opened before the first pull would silently start reading whatever the
#: refresher installed halfway through, which is the straddle the scope prevents.
_pinned: ContextVar[tuple[FxQuote | None] | None] = ContextVar("calevate_fx_pin", default=None)


def install_fx_quote(quote: FxQuote | None) -> None:
    """Publish what the store last said. Called by `ops/fx_rates.py` off the request path.

    A pin already open deliberately survives this, exactly as `apply_platform_overrides`
    leaves an open `settings_scope()` alone: the scope holds a resolved value, not a
    pointer into this module, so work already in flight keeps the rate it started with.
    """
    global _installed
    _installed = quote


def current_fx_quote() -> FxQuote | None:
    """The newest published quote this process holds, of ANY age, or `None` if none.

    Whether it is fresh is `resolve_usd_inr_rate`'s question, not this one's. Zero IO, so
    it is legal on voice-runtime's request path (hard rule 3). Inside `fx_scope()` this
    returns the quote pinned when that scope opened.
    """
    pin = _pinned.get()
    if pin is not None:
        return pin[0]
    return _installed


#: What a converted figure records when the TYPED rate was used, by override or because
#: nothing was ever published. A source string rather than a null, because "we converted at
#: the operator's typed rate" and "we do not know what we converted at" are different facts
#: and only the first one is recoverable six months later.
CONFIGURED_FX_SOURCE: Final = "configured:usd_inr_rate"


def resolve_usd_inr_rate(
    quote: FxQuote | None,
    *,
    manual: Decimal,
    manual_override: bool,
    now: datetime | None = None,
) -> UsdInrRate:
    """THE LADDER (module docstring), and its only spelling.

    Pure: the caller supplies the quote and the typed rate, so the money path
    (`usd_inr_rate_now`, from the in-memory holder) and the ops panel
    (`ops/fx_routes`, from the store) apply one rule to their own inputs and cannot
    disagree about which rung is in force.
    """
    if manual_override:
        return UsdInrRate(
            rate=manual, source=CONFIGURED_FX_SOURCE, as_of=None, basis="manual_override"
        )
    if quote is None:
        return UsdInrRate(
            rate=manual, source=CONFIGURED_FX_SOURCE, as_of=None, basis="manual_no_quote"
        )
    return UsdInrRate(
        rate=quote.rate,
        source=quote.source,
        as_of=quote.as_of,
        basis="published" if quote.fresh(now) else "stale_published",
    )


def usd_inr_rate_now(now: datetime | None = None) -> UsdInrRate:
    """The rate a dollar figure converts at RIGHT NOW, and where it came from.

    **ONE DOOR FOR EVERY READER OF THE RATE.** Callers do not pass the typed rate or the
    override flag: a reader that supplied its own would be a second copy of the ladder's
    inputs, and the day one of them forgot the override the platform would convert at two
    rates. The engine adapter still owns the question this does NOT answer: whether the
    vendor quoted in dollars at all.

    Zero IO, so it stays legal on voice-runtime's request path (hard rule 3). Inside
    `fx_scope()` and `settings_scope()` it returns what those scopes pinned, so a unit of
    work cannot convert two figures at two rates.

    The failure direction is "keep converting at the last rate anybody published", never
    "stop converting". It is not silent: `ops/fx_rates.refresh_fx_snapshot` alarms on a
    rate past its ceiling and `workers/fx_pull` alarms on a puller gone quiet.
    """
    settings = get_settings()
    return resolve_usd_inr_rate(
        current_fx_quote(),
        manual=settings.usd_inr_rate,
        manual_override=settings.usd_inr_rate_override,
        now=now,
    )


@contextmanager
def fx_scope() -> Iterator[FxQuote | None]:
    """Pin the quote ONCE for this unit of work and hold it to the end.

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
    "CONFIGURED_FX_SOURCE",
    "MAX_QUOTE_AGE",
    "FxQuote",
    "RateBasis",
    "UsdInrRate",
    "current_fx_quote",
    "fx_scope",
    "install_fx_quote",
    "reset_for_test",
    "resolve_usd_inr_rate",
    "usd_inr_rate_now",
]
