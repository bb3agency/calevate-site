"""The `engine_error_spike` alarm — OPERATIONS §4's "engine 5xx spike", made real.

WHAT WAS WRONG. §4 has listed "engine 5xx spike" among the things that trigger an alert
since the section was written, and nothing in this tree raised one. The adapter logged
`engine_error` at WARNING and moved on, so a voice platform failing every request
produced a rising line in a log file nobody watches and no page at all — while every
dial burned a contact's retry budget and every publish failed with a 502 the client saw
before we did.

WHY IT COULD NOT BE A COUNTER IN THE PROCESS. A spike is a RATE. The processes that
observe engine failures are `api` (two uvicorn workers) and `workers` (one arq process,
more when scaled), and a module global gives each of them its own private idea of how
broken the vendor is — the threshold then means N-times-more than it says. That is the
identical defect D-160 fixed for the alert suppression window, and `platform_engine_health`
is the same answer: put the count where every process shares it. Postgres and not Redis
because this counter CREATES a page while `alert_admission`'s may only ever suppress one
(migration `c4f70b1e28da` carries the full argument).

WHAT COUNTS AS A FAILURE. A 5xx, and a request that got no answer at all. They are
separate columns and one alarm: the first move differs (the vendor's application vs the
path to it), but a dial does not care which of the two stopped it. Counting only 5xx —
which is what the doc's wording literally says — would have been the worse reading: a
platform that is entirely down refuses connections rather than answering 502, so the
alarm would have been silent through the total outage and loud only through the partial
one.

WHAT DOES *NOT* COUNT, and each exclusion is a decision:

* **429 / throttling.** It is the vendor working as designed and it has its own ladder
  (`bolna.THROTTLE_MAX_ATTEMPTS`) and its own transient error code. Rate limiting is a
  capacity conversation, not an outage.
* **4xx other than 429.** `engine_rejected` on a 400 or a 404 is OUR request being
  wrong. It deserves the log line it already gets and would drown this signal.
* **A non-JSON 2xx** (`engine_bad_response`). The vendor answered; something in front of
  it is interfering. Real, rare, and a different investigation.

NOT ON THE VOICE-RUNTIME ACK PATH. This module writes to the database, which hard rule 3
forbids on the 500ms path — and it never runs there, structurally: voice-runtime does not
import `apps.api.engine` at all (`tests/voice_runtime_import_surface_test.py` enforces
it), and its engine twin `engine_intake.py` makes no HTTP calls. The only callers are the
two adapters, which run in `api` and in `workers`.
"""

from __future__ import annotations

from typing import Literal

from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES

log = get_logger(__name__)

FailureKind = Literal["server_error", "unreachable"]

#: How far back the spike rule looks. Five minutes is the window OPERATIONS §4 already
#: uses for "webhook failures > 3/5min" — one window vocabulary for the section rather
#: than a second number an operator has to hold — and it is ten campaign dispatch ticks,
#: so a vendor blip that self-heals inside two ticks cannot fill it.
SPIKE_WINDOW_MINUTES = 5

#: DERIVED FROM THE RETRY LADDER, not chosen for its roundness. One genuinely unlucky
#: operation already produces up to `WORKER_MAX_TRIES` failures on its own — the arq
#: ladder retries it — so any threshold at or below 3 fires for a single call having a
#: bad afternoon, and an alarm that fires on healthy traffic is one nobody reads when a
#: real one arrives. Three distinct operations failing every attempt they have, plus one,
#: is the first count that cannot be explained by a single request: 10.
#:
#: It is written as arithmetic on `WORKER_MAX_TRIES` so that widening the ladder moves
#: the threshold with it. A constant `10` here would quietly become "three retries" the
#: day somebody made it five.
SPIKE_THRESHOLD = 3 * WORKER_MAX_TRIES + 1

#: How long the minute buckets are kept. Nothing READS more than
#: `SPIKE_WINDOW_MINUTES`; the rest is for the operator who opens the table during an
#: incident and wants to know when it started. Seven days x 1,440 minutes x one row is a
#: table that never needs an index or a vacuum conversation.
RETENTION_DAYS = 7

_UPSERT_SQL = text(
    "INSERT INTO platform_engine_health (engine, bucket_start, server_errors, unreachable) "
    "VALUES (:engine, date_trunc('minute', now()), :server_errors, :unreachable) "
    "ON CONFLICT (engine, bucket_start) DO UPDATE SET "
    "  server_errors = platform_engine_health.server_errors + EXCLUDED.server_errors, "
    "  unreachable = platform_engine_health.unreachable + EXCLUDED.unreachable "
    # `xmax = 0` distinguishes the row this statement INSERTED from the one it updated.
    # It is used here only to decide whether to run the prune, so both answers are safe:
    # a wrong read prunes a little more often or a little later than a fresh bucket
    # deserves, and nothing about the alarm depends on it.
    "RETURNING (xmax = 0) AS inserted"
)

_WINDOW_SQL = text(
    "SELECT coalesce(sum(server_errors), 0), coalesce(sum(unreachable), 0) "
    "FROM platform_engine_health "
    "WHERE engine = :engine AND bucket_start >= date_trunc('minute', now()) "
    "  - make_interval(mins => :minutes)"
)

_PRUNE_SQL = text(
    "DELETE FROM platform_engine_health WHERE bucket_start < now() - make_interval(days => :days)"
)


async def record_engine_failure(engine: str, *, kind: FailureKind) -> None:
    """Count one engine failure, and page when the window says it is an outage.

    NEVER RAISES. It is called from the failure branch of an adapter that is already
    reporting a problem to its caller; a database hiccup here must not replace the
    vendor's error with ours. What it costs when the database is unreachable is the
    spike signal, and that is logged rather than swallowed.

    One statement to count and one to read the window. They are deliberately NOT one
    statement: the read has to include the increment this call just made (otherwise the
    tenth failure reports nine and the alarm is permanently one event late), and they
    share a transaction, so it sees it.

    NO SUPPRESSION OF ITS OWN. Past the threshold every subsequent failure re-evaluates
    true, and `alert()`'s per-fingerprint window (15 minutes, shared across processes
    since D-160) is what turns that into one page and a count of the rest. A second
    "have I already said this" flag here would be a second dedupe window on one fact,
    which is the mistake `notify.sh` is written up for not making.
    """
    try:
        from apps.api.db.session import untenanted_session

        async with untenanted_session() as session:
            row = (
                await session.execute(
                    _UPSERT_SQL,
                    {
                        "engine": engine,
                        "server_errors": 1 if kind == "server_error" else 0,
                        "unreachable": 1 if kind == "unreachable" else 0,
                    },
                )
            ).first()
            window = (
                await session.execute(
                    _WINDOW_SQL, {"engine": engine, "minutes": SPIKE_WINDOW_MINUTES}
                )
            ).one()
            if row is not None and bool(row[0]):
                await session.execute(_PRUNE_SQL, {"days": RETENTION_DAYS})
    except Exception as exc:
        # The engine is failing AND we cannot write the counter. Both facts belong in the
        # log; neither may propagate into the caller's error, which is about the vendor.
        log.warning(
            "engine_health_unrecordable",
            extra={"engine": engine, "kind": kind, "reason": type(exc).__name__},
        )
        return

    server_errors, unreachable = int(window[0]), int(window[1])
    total = server_errors + unreachable
    if total < SPIKE_THRESHOLD:
        return
    alert(
        "CORE_LOGIC",
        "engine_error_spike",
        detail=(
            f"{total} failed engine requests in {SPIKE_WINDOW_MINUTES} minutes "
            f"({server_errors} answered 5xx, {unreachable} got no answer); "
            f"threshold is {SPIKE_THRESHOLD}"
        ),
        # The engine NAME, which is ours (`bolna`, `cartesia`), never a route, a payload
        # or a vendor error string — hard rule 6, and the same reason `_request` refuses
        # to echo a vendor body to a client.
        engine=engine,
    )


__all__ = [
    "RETENTION_DAYS",
    "SPIKE_THRESHOLD",
    "SPIKE_WINDOW_MINUTES",
    "FailureKind",
    "record_engine_failure",
]
