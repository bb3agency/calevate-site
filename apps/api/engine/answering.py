"""Every engine request's run of failures, for the operator panel and for not dropping a save.

Three facts about an engine outage live in three places, each for its own reason:

* `health.py` counts failures per minute: a RATE, which is what the paging spike alarm needs.
* `outage.py` holds every dial while dials fail (Redis, probed by a read, lifted on answer).
  It is what clients are shown: the "calls are paused" banner, the paused test-call button
  and the campaign that waits all read `outage.hold_is_on()`, so they cannot disagree with
  what the dialler is actually doing.
* this module keeps the RUN of consecutive failures across every request, not only dials:
  what failed last, on which route, since when. The operator panel shows it, and
  `still_not_answering` reads it beside the hold, because a put-live or a live apply can
  meet an outage that no dial has tripped (no campaign is running), and a saved change must
  be waited out rather than given up on either way.

THE STATE IS A RUN, NOT A RATE. `platform_engine_state` keeps one row per engine: the number
of consecutive failures, when the run began and what failed last. Any answer from the engine
ends the run. "Failing" is a run of at least `OUTAGE_MIN_FAILURES` whose newest failure is
inside `OUTAGE_STALE_AFTER`:

* three, because one owner action makes one or two engine requests, so a single slow request
  is not an outage, and an answer between failures resets the count, so a flaky route among
  healthy ones never reads as one;
* the staleness bound because with no traffic nothing can end the run: after
  `health.SPIKE_WINDOW_MINUTES` with no new failure we stop claiming an outage we can no
  longer see, and the next request either answers or starts a new run.

WRITES ARE CHEAP ON THE HEALTHY PATH. A failure always writes (it already writes the minute
counter). An answer writes only when this process saw a failure since its last write, or at
most once per `ANSWER_CHECK_S` otherwise, so a process that saw no failure still ends a run
another process started. The write is a primary-key UPDATE that matches nothing when the run
is already zero.

Never raises: a read that cannot reach the state says "answering", because an outage
invented by a database hiccup is worse than one missed for a moment.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger

log = get_logger(__name__)

FailureKind = Literal["server_error", "unreachable"]

#: Consecutive failures, with no answer between them, that make an outage.
OUTAGE_MIN_FAILURES: Final = 3
#: A run whose newest failure is older than this is no longer evidence of anything. The
#: spike alarm's own window, so the two read the same five minutes.
OUTAGE_STALE_AFTER: Final = timedelta(minutes=5)
#: How often a process that saw no failure itself still tells the table it got an answer.
ANSWER_CHECK_S: Final = 30.0

_FAILURE_SQL = text(
    "INSERT INTO platform_engine_state (engine, consecutive_failures, failing_since, "
    "last_failure_at, last_kind, last_error, last_route) "
    "VALUES (:engine, 1, now(), now(), :kind, :error, :route) "
    "ON CONFLICT (engine) DO UPDATE SET "
    # A run that went stale starts again: its old start time would claim an outage that
    # nobody observed in between.
    "  consecutive_failures = CASE WHEN platform_engine_state.consecutive_failures = 0 "
    "    OR platform_engine_state.last_failure_at < now() - make_interval(secs => :stale) "
    "    THEN 1 ELSE platform_engine_state.consecutive_failures + 1 END, "
    "  failing_since = CASE WHEN platform_engine_state.consecutive_failures = 0 "
    "    OR platform_engine_state.last_failure_at < now() - make_interval(secs => :stale) "
    "    THEN now() ELSE platform_engine_state.failing_since END, "
    "  last_failure_at = now(), last_kind = EXCLUDED.last_kind, "
    "  last_error = EXCLUDED.last_error, last_route = EXCLUDED.last_route"
)

# `recovered_at` moves only when the run that ended was an outage, so the panel's "last
# outage ended" is not overwritten by every single failed request that was answered next.
_ANSWER_SQL = text(
    "UPDATE platform_engine_state SET "
    "  recovered_at = CASE WHEN consecutive_failures >= :min "
    "    AND last_failure_at >= now() - make_interval(secs => :stale) "
    "    THEN now() ELSE recovered_at END, "
    "  consecutive_failures = 0, failing_since = NULL, last_answer_at = now() "
    "WHERE engine = :engine AND consecutive_failures > 0"
)

_READ_SQL = text(
    "SELECT consecutive_failures, failing_since, last_failure_at, last_answer_at, "
    "recovered_at, last_kind, last_error, last_route, "
    "last_failure_at >= now() - make_interval(secs => :stale) AS fresh "
    "FROM platform_engine_state WHERE engine = :engine"
)

#: Engines this process saw fail since it last wrote an answer.
_failed_here: set[str] = set()
#: When this process last wrote an answer, per engine (monotonic seconds).
_answer_written: dict[str, float] = {}


@dataclass(frozen=True, slots=True)
class EngineOutage:
    """What every outage surface reads. `failing` is the only field a client is shown."""

    engine: str
    failing: bool
    #: The first failure of the current run; None while answering.
    since: datetime | None = None
    consecutive_failures: int = 0
    last_failure_at: datetime | None = None
    last_answer_at: datetime | None = None
    recovered_at: datetime | None = None
    last_kind: FailureKind | None = None
    #: An exception class name or an HTTP status, never a message.
    last_error: str | None = None
    #: Our route template, never a filled URL.
    last_route: str | None = None


def _stale_s() -> float:
    return OUTAGE_STALE_AFTER.total_seconds()


async def record_failure(
    session: AsyncSession,
    engine: str,
    *,
    kind: FailureKind,
    route: str | None,
    error: str | None,
) -> None:
    """Extend the engine's run of failures, in the caller's transaction (`health`'s)."""
    await session.execute(
        _FAILURE_SQL,
        {
            "engine": engine,
            "kind": kind,
            "error": (error or "")[:64] or None,
            "route": (route or "")[:120] or None,
            "stale": _stale_s(),
        },
    )
    _failed_here.add(engine)


async def record_answer(engine: str) -> None:
    """The engine answered: end its run of failures. Never raises; usually writes nothing."""
    now = time.monotonic()
    if engine not in _failed_here and now - _answer_written.get(engine, 0.0) < ANSWER_CHECK_S:
        return
    _failed_here.discard(engine)
    _answer_written[engine] = now
    try:
        from apps.api.db.session import untenanted_session

        async with untenanted_session() as session:
            await session.execute(
                _ANSWER_SQL,
                {"engine": engine, "min": OUTAGE_MIN_FAILURES, "stale": _stale_s()},
            )
    except Exception as exc:
        log.warning(
            "engine_answer_unrecordable", extra={"engine": engine, "error": type(exc).__name__}
        )


async def engine_outage(engine: str | None = None) -> EngineOutage:
    """The engine's state now. `engine` defaults to the active one (`Settings.engine`, the
    name every adapter counts under), read without building the adapter."""
    if engine is None:
        from apps.api.core.settings import get_settings

        engine = get_settings().engine
    try:
        from apps.api.db.session import untenanted_session

        async with untenanted_session() as session:
            row = (
                await session.execute(_READ_SQL, {"engine": engine, "stale": _stale_s()})
            ).first()
    except Exception as exc:
        log.warning(
            "engine_outage_unreadable", extra={"engine": engine, "error": type(exc).__name__}
        )
        return EngineOutage(engine=engine, failing=False)
    if row is None:
        return EngineOutage(engine=engine, failing=False)
    count = int(row[0])
    failing = count >= OUTAGE_MIN_FAILURES and bool(row[8])
    kind = row[5] if row[5] in ("server_error", "unreachable") else None
    return EngineOutage(
        engine=engine,
        failing=failing,
        since=row[1] if failing else None,
        consecutive_failures=count,
        last_failure_at=row[2],
        last_answer_at=row[3],
        recovered_at=row[4],
        last_kind=kind,
        last_error=row[6],
        last_route=row[7],
    )


#: What an owner reads when a request found the engine not answering. Client-facing, so no
#: provider is named (D-679); "phone service" is the word the client banner uses too.
ENGINE_NOT_ANSWERING_TITLE: Final = "Our phone service is not answering"
ENGINE_NOT_ANSWERING_REMEDIATION: Final = "It usually comes back within minutes. Try again then."

#: The code of a save that was kept and will go live by itself once the engine answers.
SAVED_GOES_LIVE_LATER_CODE: Final = "saved_goes_live_later"


def saved_goes_live_later() -> ProblemError:
    """The answer to a save that committed and whose put-live is queued until the engine
    answers. A 503 rather than a 200 so a screen cannot read it as "live now"; the screens
    match on the code and show it as a plain notice, not a failure."""

    return ProblemError(
        kind="dependency",
        code=SAVED_GOES_LIVE_LATER_CODE,
        title="Saved",
        detail="It goes live when our phone service answers again, usually within minutes.",
        remediation="Nothing to do: it goes live by itself.",
        failure_stage="CORE_LOGIC",
    )


async def still_not_answering() -> bool:
    """Whether a change waiting to reach the engine should keep waiting: dials are held
    (`outage.hold_is_on`), or the run of failures across every request is an outage. Read
    by the retry ladders that would otherwise give a saved change up."""
    # Imported here: `outage` imports `vendor_http`, which imports this module.
    from apps.api.engine.outage import hold_is_on

    return await hold_is_on() or (await engine_outage()).failing


def reset_process_state() -> None:
    """Forget this process's answer bookkeeping (tests)."""
    _failed_here.clear()
    _answer_written.clear()


__all__ = [
    "ANSWER_CHECK_S",
    "ENGINE_NOT_ANSWERING_REMEDIATION",
    "ENGINE_NOT_ANSWERING_TITLE",
    "OUTAGE_MIN_FAILURES",
    "OUTAGE_STALE_AFTER",
    "SAVED_GOES_LIVE_LATER_CODE",
    "EngineOutage",
    "FailureKind",
    "engine_outage",
    "record_answer",
    "record_failure",
    "reset_process_state",
    "saved_goes_live_later",
    "still_not_answering",
]
