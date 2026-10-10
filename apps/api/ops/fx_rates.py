"""The FX observation store, and the seam between it and the in-memory holder.

Four jobs, all of them the ops side of `core/fx.py`'s holder:

* `record_observation` — the WRITE the five-minute pull performs, idempotent and
  single-flighted, with the plausibility guard that stops a changed vendor unit from
  repricing the platform;
* `record_check` / `last_check` — when the pull last completed, which the observation
  rows cannot say (below);
* `latest_observation` / `recent_observations` — the READS the console renders;
* `refresh_fx_snapshot` / `start_fx_refresher` — the poll that puts the current
  observation into `core/fx`'s holder so a synchronous conversion can reach it.

The shape is `ops/pricing_snapshot.py`'s, and deliberately: durable truth in Postgres, an
in-memory snapshot in front, a background poll that refreshes it off the request path.
What differs is the ceiling — an attested price does not go stale, a rate does — so this
module also owns the ALARM for a rate in force that has aged past `core/fx.MAX_QUOTE_AGE`:
money keeps converting at it, and doing that silently is the failure this feature exists
to prevent.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import Sequence
from contextlib import suppress
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Final

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.billing.rates import ROUNDING
from apps.api.core.alerting import alert
from apps.api.core.fx import MAX_QUOTE_AGE, FxQuote, install_fx_quote
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

#: How often a process re-reads the store into its holder. Slower than the five-minute
#: pull would strictly need, because a missed beat costs nothing (the next one lands the
#: same value) and faster than the pull, so a new rate is in force within a minute of
#: being written rather than within a poll of the writer's own cadence.
_POLL_INTERVAL_S = 60.0

#: The currency pair this product converts. A pair and not a bare "the rate", for the
#: reason the columns exist: a direction that is only implied cannot be checked.
BASE_CURRENCY = "USD"
QUOTE_CURRENCY = "INR"

#: How far one observation may move from the previous one before it is REFUSED.
#:
#: USD/INR does not move 10% in a day — the 2013 taper-tantrum slide, the sharpest move in
#: the pair's modern history, took months — so a jump this size is not a market event, it is
#: a changed unit, a changed pair, or a parser reading the wrong field. This repo has
#: already paid for exactly that class of defect once on the cost path (a rented engine's
#: minor-unit assumption metered every call at 1/100th of cost, D-411), and an FX feed is
#: the same hazard with a bigger blast radius. So the new observation is refused, the
#: previous one keeps serving until it ages out on its own, and an operator is paged — the
#: fail-safe direction, because a rejected real move costs a few paise of drift for a day
#: and an accepted wrong one reprices every invoice.
MAX_PLAUSIBLE_MOVE = Decimal("0.10")

#: Sanity bounds on the number itself, mirroring `Settings.usd_inr_rate`'s field bounds
#: for its stated reason: a `0` makes every vendor minute free and nobody notices until
#: the month closes. Enforced here AND as a CHECK on the table, because a NUMERIC column
#: is reachable by any writer holding the untenanted role.
MIN_RATE = Decimal("1")
MAX_RATE = Decimal("1000")

#: The stored scale — `fx_rate_observations.rate` is NUMERIC(12,6). Spelled from the
#: column rather than as a literal repeated in two places.
_RATE_QUANTUM = Decimal(1).scaleb(-6)


class ImplausibleRateError(ValueError):
    """A pulled rate this store refuses to believe. Carries the operator's sentence."""


@dataclass(frozen=True, slots=True)
class FxObservation:
    """One stored row, as the console and the pull read it back."""

    id: uuid.UUID
    base_currency: str
    quote_currency: str
    rate: Decimal
    as_of: date
    source: str
    source_url: str
    observed_at: datetime

    def as_quote(self) -> FxQuote:
        return FxQuote(
            rate=self.rate, as_of=self.as_of, source=self.source, observed_at=self.observed_at
        )


def observation_key(*, source: str, as_of: date, rate: Decimal) -> str:
    """The natural key that makes a five-minute poll of a daily publication idempotent.

    `source|base|quote|as_of|rate`. The RATE is in the key on purpose: without it a
    provider that CORRECTS a published rate for a date it has already published — which
    reference-rate administrators do — would be silently dropped as a duplicate, and the
    correction is the one observation nobody may lose. With it, a correction is a new row
    and the history shows both, which is what an append-only table is for.
    """
    return f"{source}|{BASE_CURRENCY}|{QUOTE_CURRENCY}|{as_of.isoformat()}|{rate}"


async def latest_observation(session: AsyncSession) -> FxObservation | None:
    """The most recently PUBLISHED observation for the pair, or `None` if there is none.

    Ordered by `as_of DESC, seq DESC`: the newest PUBLICATION wins, and among rows sharing
    a publication date the one we learned last wins — which is what makes a provider's
    correction supersede the figure it corrects.

    NEITHER HALF IS ARBITRARY. Ordering by `observed_at` alone would let a backfill of an
    older date overwrite today's rate. Using `observed_at` as the tiebreak looks equivalent
    to `seq` and is not: `now()` in Postgres is TRANSACTION start time, so two rows written
    in one transaction carry the SAME instant and the tie is then broken at random — a
    correction losing to the figure it corrects, by coin flip, on a number that reaches
    money. A test caught exactly that (`test_a_corrected_rate_for_a_published_date_is_a_new_row`).
    """
    row = (
        await session.execute(
            text(
                "SELECT id, base_currency, quote_currency, rate, as_of, source, source_url, "
                "observed_at FROM fx_rate_observations "
                "WHERE base_currency = :base AND quote_currency = :quote "
                "ORDER BY as_of DESC, seq DESC LIMIT 1"
            ),
            {"base": BASE_CURRENCY, "quote": QUOTE_CURRENCY},
        )
    ).first()
    return _row_to_observation(row) if row is not None else None


async def recent_observations(session: AsyncSession, *, limit: int = 20) -> list[FxObservation]:
    """The last `limit` observations, newest publication first. For the ops panel.

    BOUNDED at the call site and again here (`check_list_bounds`): an unbounded read of
    an append-only table grows without limit, and this one gains 288 rows a day in the
    worst case.
    """
    rows = (
        await session.execute(
            text(
                "SELECT id, base_currency, quote_currency, rate, as_of, source, source_url, "
                "observed_at FROM fx_rate_observations "
                "WHERE base_currency = :base AND quote_currency = :quote "
                "ORDER BY as_of DESC, seq DESC LIMIT :limit"
            ),
            {"base": BASE_CURRENCY, "quote": QUOTE_CURRENCY, "limit": min(limit, 100)},
        )
    ).all()
    return [_row_to_observation(row) for row in rows]


def _row_to_observation(row: Sequence[object]) -> FxObservation:
    return FxObservation(
        id=row[0],  # type: ignore[arg-type]
        base_currency=str(row[1]),
        quote_currency=str(row[2]),
        rate=row[3],  # type: ignore[arg-type]
        as_of=row[4],  # type: ignore[arg-type]
        source=str(row[5]),
        source_url=str(row[6]),
        observed_at=row[7],  # type: ignore[arg-type]
    )


def _check_plausible(rate: Decimal, previous: FxObservation | None) -> None:
    """Refuse a number this store will not believe. Raises `ImplausibleRateError`.

    The absolute bounds first (they need no history), then the relative move. A first
    observation has nothing to move from and passes the second test by construction —
    which is correct: there is no prior belief to contradict, and the absolute band is
    what stops a bootstrap from installing nonsense.
    """
    if not (MIN_RATE <= rate <= MAX_RATE):
        raise ImplausibleRateError(
            f"{BASE_CURRENCY}/{QUOTE_CURRENCY} of {rate} is outside the band this store "
            f"accepts {MIN_RATE} to {MAX_RATE}. The feed's unit or pair has probably changed."
        )
    if previous is None:
        return
    move = abs(rate - previous.rate) / previous.rate
    if move > MAX_PLAUSIBLE_MOVE:
        raise ImplausibleRateError(
            f"{BASE_CURRENCY}/{QUOTE_CURRENCY} moved from {previous.rate} to {rate} "
            f"({move:.1%}), more than the {MAX_PLAUSIBLE_MOVE:.0%} this store accepts in "
            "one step. The previous rate keeps serving until it ages out."
        )


async def record_observation(
    session: AsyncSession,
    *,
    rate: Decimal,
    as_of: date,
    source: str,
    source_url: str,
) -> tuple[FxObservation, bool]:
    """Store one pulled rate. Returns `(the row in force, whether THIS call inserted it)`.

    **Single-flight and idempotent, and both are structural rather than hopeful.** Two
    workers that tick at the same second take `pg_advisory_xact_lock` on this pair first,
    so the plausibility test and the insert are one critical section rather than a
    read-then-write race (BACKEND-PATTERNS §5: the guard is in the transaction, not in a
    TTL lease that can outlive itself). The loser then finds the winner's row through
    `ON CONFLICT (observation_key) DO NOTHING` and returns `inserted=False` — the same
    outcome as a poll that found nothing new, which is the overwhelmingly common case
    when a five-minute pull meets a once-a-day publication.

    A reader can never see a half-written pair: `rate` and `as_of` are columns of ONE row
    inserted in ONE statement, so there is no window in which they disagree. That is why
    this is a table of immutable observations rather than a mutable "current rate" row —
    the mutable version needs a transaction to keep two columns in step, and the
    immutable one cannot have the problem.
    """
    # THE COLUMN'S OWN SCALE, WITH THE MODE STATED. NUMERIC(12,6) would round this on the
    # way in anyway; doing it here means the value the plausibility check judges and the
    # value stored are the same number, and that the ROUNDING is ours rather than the
    # database's. `rounding=` is passed for the reason every quantize in this repo passes
    # it (`billing/rates.ROUNDING`): the ambient `decimal` context is process-global,
    # mutable by any library in the image, and defaults to banker's rounding — a money
    # figure that depends on what some other import did to a global is not one we can
    # defend. Half-up on the sixth decimal of an exchange rate is a ten-millionth of a
    # rupee per dollar; what matters is that it is deterministic and named.
    quantized = rate.quantize(_RATE_QUANTUM, rounding=ROUNDING)
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"fx:{BASE_CURRENCY}:{QUOTE_CURRENCY}"},
    )
    previous = await latest_observation(session)
    _check_plausible(quantized, previous)
    key = observation_key(source=source, as_of=as_of, rate=quantized)
    row = (
        await session.execute(
            text(
                "INSERT INTO fx_rate_observations "
                "(id, base_currency, quote_currency, rate, as_of, source, source_url, "
                "observation_key) "
                "VALUES (:id, :base, :quote, :rate, :as_of, :source, :url, :key) "
                "ON CONFLICT (observation_key) DO NOTHING "
                "RETURNING id, base_currency, quote_currency, rate, as_of, source, "
                "source_url, observed_at"
            ),
            {
                "id": uuid.uuid4(),
                "base": BASE_CURRENCY,
                "quote": QUOTE_CURRENCY,
                "rate": quantized,
                "as_of": as_of,
                "source": source,
                "url": source_url,
                "key": key,
            },
        )
    ).first()
    if row is not None:
        return _row_to_observation(row), True
    existing = (
        await session.execute(
            text(
                "SELECT id, base_currency, quote_currency, rate, as_of, source, source_url, "
                "observed_at FROM fx_rate_observations WHERE observation_key = :key"
            ),
            {"key": key},
        )
    ).one()
    return _row_to_observation(existing), False


#: Where the pull's last completed tick is recorded.
#:
#: Not in `fx_rate_observations`: that table is append-only and its `observation_key`
#: makes a repeat poll of one publication a no-op, so a row's `observed_at` is when that
#: publication was FIRST seen and a healthy poller looks stuck behind it. Not a Postgres
#: row either: it would be a mutable row rewritten 288 times a day, for a value nothing
#: reconciles money against. Redis loses it only on a flush, which costs one tick of
#: "not checked yet" on the panel and nothing else.
LAST_CHECK_KEY: Final = "calevate:fx:last_check"

#: How long one Redis round trip may take before the record is skipped. A tick or a
#: panel read must never wait on telemetry.
_CHECK_BUDGET_S: Final = 0.5


@dataclass(frozen=True, slots=True)
class FxCheck:
    """One completed pull tick: when, and which source it found serving."""

    checked_at: datetime
    #: The rung that served, or `None` when every rung answered with a publication past
    #: the ceiling (the feeds work and are behind).
    serving_source: str | None
    serving_as_of: date | None


async def record_check(check: FxCheck) -> None:
    """Record a completed tick. Never raises: a lost record costs a panel line, while a
    raise here would file a good tick as a failure."""
    payload = json.dumps(
        {
            "checked_at": check.checked_at.isoformat(),
            "serving_source": check.serving_source,
            "serving_as_of": check.serving_as_of.isoformat() if check.serving_as_of else None,
        }
    )
    try:
        await asyncio.wait_for(get_redis().set(LAST_CHECK_KEY, payload), timeout=_CHECK_BUDGET_S)
    except Exception as exc:
        log.warning("fx_check_record_failed", extra={"reason": type(exc).__name__})


async def last_check() -> FxCheck | None:
    """The last completed tick, or `None` if none is recorded or Redis cannot answer."""
    try:
        raw = await asyncio.wait_for(get_redis().get(LAST_CHECK_KEY), timeout=_CHECK_BUDGET_S)
    except Exception as exc:
        log.warning("fx_check_read_failed", extra={"reason": type(exc).__name__})
        return None
    if not raw:
        return None
    try:
        data = json.loads(raw)
        as_of = data.get("serving_as_of")
        return FxCheck(
            checked_at=datetime.fromisoformat(data["checked_at"]),
            serving_source=data.get("serving_source"),
            serving_as_of=date.fromisoformat(as_of) if as_of else None,
        )
    except (ValueError, KeyError, TypeError) as exc:
        log.warning("fx_check_unreadable", extra={"reason": type(exc).__name__})
        return None


async def refresh_fx_snapshot() -> FxQuote | None:
    """Re-read the store into `core/fx`'s holder. Returns what was installed.

    Never raises, for `platform_config.refresh`'s reason and with the same fail-safe
    direction: a store this process cannot read must not take down the metering path. The
    previously installed quote keeps serving, labelled stale past `MAX_QUOTE_AGE` on every
    read, and the failure is logged.

    IT ALSO RAISES THE STALENESS ALARM, and that is the reason this function is worth
    having rather than installing from the pull job directly. The pull job only runs when
    the pull runs; the case that must be noisy is the one where it does NOT — a feed that
    stopped a week ago produces no job, no exception and no log line anywhere, while every
    conversion keeps using its last rate. This poll is the thing that is still running
    when nothing else is.

    `fx_rate_stale` means the WHOLE source ladder is behind (D-589): a quiet preferred
    source alone raises `fx_source_degraded` from the pull and keeps a fresh published
    rate in force. This function asks whether the newest stored rate, whoever published
    it, is past the ceiling.
    """
    try:
        async with untenanted_session() as session:
            observation = await latest_observation(session)
    except Exception as exc:
        log.error("fx_snapshot_refresh_failed", extra={"reason": type(exc).__name__})
        return None

    if observation is None:
        install_fx_quote(None)
        return None
    quote = observation.as_quote()
    install_fx_quote(quote)
    if not quote.fresh():
        alert(
            "CORE_LOGIC",
            "fx_rate_stale",
            detail=(
                f"Every published USD/INR source is older than {MAX_QUOTE_AGE.days} days, so "
                f"vendor costs are converting at the last published rate, {quote.rate} from "
                f"{quote.as_of.isoformat()} ({quote.source}), and every new usage row carries "
                "that date. The preferred source and its published fallbacks have all gone "
                "quiet, or the puller is not running. Check the fx_rate_pull job and the "
                "upstream feeds."
            ),
            as_of=quote.as_of.isoformat(),
            age_days=str(quote.age().days),
            source=quote.source,
        )
    return quote


_refresher: asyncio.Task[None] | None = None


async def _poll_forever() -> None:
    # Refresh first, then sleep — `platform_config._poll_forever`'s reason: a process that
    # has just started is the one most likely to be converting at the fallback.
    while True:
        await refresh_fx_snapshot()
        await asyncio.sleep(_POLL_INTERVAL_S)


def start_fx_refresher() -> None:
    """Begin polling the FX store in this process. Idempotent.

    THE WHOLE ADOPTION SURFACE, like `start_config_refresher`: a process that calls it
    converts at the pulled rate, one that does not converts at its configured
    `usd_inr_rate` exactly as it did before this feature existed. Both the API and the
    WORKER call it — the worker especially, because `workers/pipeline.py::_meter` is
    where a call's cost is actually converted and written to the ledger.
    """
    global _refresher
    if _refresher is not None and not _refresher.done():
        return
    _refresher = asyncio.get_running_loop().create_task(_poll_forever())


async def stop_fx_refresher() -> None:
    """Cancel the poll. For shutdown and for tests that must not leak a task."""
    global _refresher
    if _refresher is None:
        return
    _refresher.cancel()
    with suppress(asyncio.CancelledError):
        await _refresher
    _refresher = None


__all__ = [
    "BASE_CURRENCY",
    "LAST_CHECK_KEY",
    "MAX_PLAUSIBLE_MOVE",
    "MAX_RATE",
    "MIN_RATE",
    "QUOTE_CURRENCY",
    "FxCheck",
    "FxObservation",
    "ImplausibleRateError",
    "last_check",
    "latest_observation",
    "observation_key",
    "recent_observations",
    "record_check",
    "record_observation",
    "refresh_fx_snapshot",
    "start_fx_refresher",
    "stop_fx_refresher",
]
