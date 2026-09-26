"""Re-metering: the leg whose price arrived after the call did (founder audit, 19 Sep 2026).

THE DEFECT, IN ONE PARAGRAPH
============================
`worker/service.settle_call` prices each leg of a call independently and records a
`call_metering_refusals` row for every leg no attested rate covers (D-625). That refusal is
permanent by construction — both `usage_events` and `call_metering_refusals` are append-only
under hard rule 4, so there is no UPDATE with which to un-refuse one — and until now nothing
ever looked at those rows again. An operator who entered the missing price in the ops console
a week later billed every call from that moment on and NONE of the calls that were waiting for
it. That is unbillable debt: real spend we absorbed, recorded, and could never invoice.

WHAT MADE IT UNFIXABLE, AND THE HALF OF THE FIX THAT IS NOT IN THIS FILE
========================================================================
The missing piece was never the worker. It was the NUMBER: a refusal row stores the verdict
(`leg`, `code`, `detail`, `remediation`) and not the measurement, the settlement request is
not persisted anywhere, and a refused leg deliberately writes no `usage_events` row at all —
so there was nothing on disk to apply a new price to. `worker/service._record_remeter_demands`
is where that changed: the measurement is now parked, in the settlement's own transaction,
keyed so that one leg of one call can produce exactly one demand ever. Read it before this
file; it carries the argument for the store, the rejected alternative and the 90-day window
the store imposes.

WHAT THIS FILE IS
=================
Two readers of those demands, and they are two different failures rather than one mechanism
written twice:

* `remeter_refused_leg` — the JOB, published once by `dispatch_outbox` within seconds of the
  settlement. It covers the case where the price was attested between the call and the
  dispatcher's next tick, which is rare and free to cover.
* `remeter_refused_legs` — the CRON, and the one that actually recovers the money. A price
  attested today is a fact about calls that settled weeks ago, and nothing re-enqueues an
  outbox row when an operator types into a console. So the sweep re-reads the demands and
  tries again, on a schedule.

WHAT STOPS A DOUBLE BILL
========================
Nothing in this file, and that is deliberate — `worker/service.remeter` states it in full.
The guarantee is the three unique indexes on `usage_events (tenant_id, call_id, unit_type)`
plus `ON CONFLICT DO NOTHING` at the insert, so the second of any two writers — this sweep
twice over, this sweep against the job, either against a late settlement — writes nothing.
`tests/remetering_test.py` runs each of those races and asserts one row.

TENANCY (hard rule 1)
=====================
`outbox_messages` carries no `tenant_id` column and no policy — the dispatcher has to order
one queue across every tenant — so the demand scan runs `untenanted_session`. Every read and
write that follows is per tenant, under `tenant_session`, with the tenant taken from the
payload the settlement wrote under RLS. Nothing here joins a tenant-scoped table from the
untenanted session; it could not, since RLS would answer zero rows.

HARD RULE 6
===========
Ids, unit types, counts. No transcript, no phone number — and there is none on this path to
leak: a demand payload holds two uuids, a leg name, a unit type, a decimal and the worker's
own measurement notes.
"""

from __future__ import annotations

import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.core.logging import get_logger
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.worker.service import (
    REMETER_JOB,
    RemeterDemand,
    parse_remeter_demand,
    remeter,
)

log = get_logger(__name__)

#: Hourly, at a minute nothing else fires on. The work is bounded rather than fleet-wide
#: (`WalkShape`), so it has no collision rule to obey — the minute is chosen clear of its
#: neighbours anyway, on the argument `copilot_memory` makes for :25: a tick that shares a
#: minute competes for the same ten worker slots and the same pool.
#:
#: HOURLY AND NOT FASTER, because of what it waits on. The event that makes a demand
#: settleable is a human entering a price in the ops console; a minute's latency on that buys
#: nothing, and every tick that finds nothing to do still costs one untenanted read.
SWEEP_MINUTE = 41

#: How many demand rows one read of the store returns. A PAGE SIZE, not a cap on the tick:
#: demands stay in `outbox_messages` for their whole 90-day window whether or not they have
#: since been metered, so a tick that read only the oldest N would, once N rows had ever been
#: parked, re-read the same already-settled N every hour and never reach a newer one. The
#: sweep pages through the whole store instead, bounded by `SWEEP_BUDGET_S`.
SWEEP_BATCH = 200

#: Wall clock one tick may spend, checked BETWEEN tenants and between pages. Same instrument
#: and same reason as `engine_reconciliation.SWEEP_BUDGET_S`: the page size bounds one read
#: and this bounds the tick, and a pool that has started answering slowly turns the first
#: into the second.
SWEEP_BUDGET_S = 60.0

#: One page of demands, in a total order, whatever their dispatch status.
#:
#: **STATUS IS DELIBERATELY NOT IN THE PREDICATE.** The row's `status` describes the
#: DISPATCHER's business with it — did the job get published — and says nothing about whether
#: the leg is now priceable, which is the only question here. A `published` demand whose job
#: ran and found no attested price is exactly the row this sweep exists for.
#:
#: Keyset on `(created_at, id)` rather than OFFSET: rows parked while the tick runs cannot
#: shift a page boundary and make one demand be skipped or read twice.
_DEMANDS_SQL = """
SELECT id, created_at, payload FROM outbox_messages
WHERE job = :job
  AND (CAST(:after_at AS timestamptz) IS NULL
       OR (created_at, id) > (CAST(:after_at AS timestamptz), CAST(:after_id AS uuid)))
ORDER BY created_at, id
LIMIT :cap
"""

#: Which of one tenant's demanded legs already have their row. Read once per tenant per page
#: so a store full of settled demands costs one query per tenant rather than one session per
#: demand; `remeter` still answers the same question itself for any demand this lets through.
_METERED_SQL = """
SELECT call_id, unit_type FROM usage_events
WHERE call_id = ANY(CAST(:calls AS uuid[]))
"""


def _demands(rows: list[Any]) -> tuple[list[RemeterDemand], int]:
    """Parse what the scan returned; count what would not parse rather than failing the tick.

    A payload this cannot read is one demand lost, and it is already lost — raising would
    throw away the other hundred and ninety-nine, which is the shape R-4 calls "one tenant's
    failure is not the sweep's". The count rides the return string so the number of recoveries
    reads as a FLOOR.
    """
    demands: list[RemeterDemand] = []
    unreadable = 0
    for (payload,) in rows:
        try:
            demands.append(parse_remeter_demand(payload))
        except (KeyError, TypeError, ValueError, ArithmeticError):
            # The exception is NOT logged: it renders the payload it choked on, and a payload
            # is the one thing hard rule 6 keeps out of a log line even when it holds no PII
            # today. What an operator needs is that one exists.
            unreadable += 1
    return demands, unreadable


async def remeter_refused_leg(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """One demand, published by the outbox dispatcher moments after the settlement wrote it.

    **IT DOES NOT RETRY ON "STILL UNPRICEABLE", AND THAT IS THE WHOLE POLICY.** The thing a
    demand waits for is an operator in the ops console, which is hours or weeks away; a job
    that raised `Retry` for it would burn its ladder in a minute, dead-letter a row that is
    perfectly healthy, and fire the outbox's DLQ alarm on every refused leg of every call.
    So an unpriceable leg is a SUCCESSFUL tick that reports `unpriceable`, and the mechanism
    that eventually settles it is `remeter_refused_legs` below.

    What DOES retry is a broken database or pool — the ladder `WorkerSettings.max_tries`
    promises — because that is a failure of this attempt rather than a verdict about the leg.
    A payload that will not parse is neither: it is poison, it fails the job once, and the
    dispatcher's own DLQ is where a poison message belongs.
    """
    demand = parse_remeter_demand(payload)
    verdict = await remeter(demand)
    return f"remeter={verdict}"


@dataclass(slots=True)
class _Tally:
    """What one tick did, across every page it read."""

    metered: int = 0
    already: int = 0
    unpriceable: int = 0
    unreadable: int = 0
    unreached: int = 0
    seen: int = 0
    tenants: set[UUID] = field(default_factory=set)


async def _metered_legs(tenant_id: UUID, demands: list[RemeterDemand]) -> set[tuple[UUID, str]]:
    """The `(call, unit_type)` pairs among `demands` that already have a usage row."""
    calls = sorted({str(demand.call_id) for demand in demands})
    async with tenant_session(tenant_id) as session:
        rows = (await session.execute(text(_METERED_SQL), {"calls": calls})).all()
    return {(UUID(str(call_id)), str(unit_type)) for call_id, unit_type in rows}


async def _settle_page(demands: list[RemeterDemand], tally: _Tally, *, started: float) -> bool:
    """Try one page of demands, tenant by tenant. False when the time budget ran out."""
    by_tenant: dict[UUID, list[RemeterDemand]] = defaultdict(list)
    for demand in demands:
        by_tenant[demand.tenant_id].append(demand)
    for tenant_id, tenant_demands in by_tenant.items():
        if time.monotonic() - started >= SWEEP_BUDGET_S:
            return False
        tally.tenants.add(tenant_id)
        tally.seen += len(tenant_demands)
        try:
            metered_legs = await _metered_legs(tenant_id, tenant_demands)
        except Exception:
            log.exception("remeter_failed", extra={"tenant_id": str(tenant_id)})
            tally.unreached += len(tenant_demands)
            continue
        for demand in tenant_demands:
            if (demand.call_id, demand.quantity.unit_type) in metered_legs:
                tally.already += 1
                continue
            try:
                verdict = await remeter(demand)
            except Exception:
                # The ids, never the exception's payload: a psycopg error string can quote
                # the row that broke it, and these rows are one client's money.
                log.exception(
                    "remeter_failed",
                    extra={"tenant_id": str(tenant_id), "call_id": str(demand.call_id)},
                )
                tally.unreached += 1
                continue
            if verdict == "metered":
                tally.metered += 1
            elif verdict == "already_metered":
                tally.already += 1
            else:
                tally.unpriceable += 1
    return True


async def remeter_refused_legs(ctx: dict[str, Any]) -> str:
    """Try every parked measurement against today's rate card.

    THE RECOVERY PATH FOR AN ATTESTATION THAT ARRIVED AFTER THE CALL. Nothing tells this
    sweep that a price was entered — there is no event to subscribe to and adding one would
    couple the ops console to the metering path — so it simply asks the rate card again,
    hourly, for every demand on the books. The question is one read per tenant per page and
    one function call per demand not yet metered, and the answer on a healthy deployment is
    `already_metered` or nothing at all.

    ONE DEMAND'S FAILURE IS NOT THE TICK'S, and one tenant's is not the sweep's (R-4): the
    same isolation `reconcile_outstanding_calls` and `report_stalled_pipeline` take, with
    every counter riding the return string so a recovery count reads as a FLOOR rather than
    a total.

    RETRIES, AND THERE IS NO DLQ (P6.5). `max_tries` is passed EXPLICITLY at the `cron()`
    call site — `cron()` defaults it to 1 and `WorkerSettings.max_tries` does not reach a
    function carrying its own. What reaches that ladder is a tick that could not RUN (the
    untenanted read, the pool), because a failure INSIDE the walk is isolated per demand: a
    demand nobody could settle is a verdict rather than a failure, and is never a reason to
    re-run the other hundred and ninety-nine. A re-run is safe in any case — every verdict
    is idempotent and the second pass answers `already_metered`.
    """
    started = time.monotonic()
    tally = _Tally()
    truncated = False
    after: tuple[datetime, UUID] | None = None
    while True:
        if time.monotonic() - started >= SWEEP_BUDGET_S:
            truncated = True
            break
        async with untenanted_session() as session:
            rows = list(
                (
                    await session.execute(
                        text(_DEMANDS_SQL),
                        {
                            "job": REMETER_JOB,
                            "cap": SWEEP_BATCH,
                            "after_at": None if after is None else after[0],
                            "after_id": None if after is None else after[1],
                        },
                    )
                )
                .tuples()
                .all()
            )
        if not rows:
            break
        after = (rows[-1][1], UUID(str(rows[-1][0])))
        demands, unreadable = _demands([(payload,) for _id, _at, payload in rows])
        tally.unreadable += unreadable
        if not await _settle_page(demands, tally, started=started):
            truncated = True
            break
        if len(rows) < SWEEP_BATCH:
            break

    if tally.unpriceable or tally.unreadable or tally.unreached:
        # `error` and not `warning`, for `settle_call`'s reason at the same seam: an unmetered
        # leg is spend we absorbed and cannot bill. It is a LOG LINE and not an `alert()`
        # because this condition has no code in `core/alarm_severity.py` and a call site may
        # not choose its own loudness — the alarm is the one piece of this fix that needs a
        # file outside this change's remit, and `admin/health.calls_unmetered` already stops
        # the account board for the calls it leaves behind.
        log.error(
            "remetering_debt_outstanding",
            extra={
                "unpriceable": tally.unpriceable,
                "unreadable": tally.unreadable,
                "unreached": tally.unreached,
                "tenants": len(tally.tenants),
            },
        )
    if truncated:
        # Said out loud for `outstanding_probe_budget_exhausted`'s reason: a sweep that
        # stopped early and reported a smaller number reads exactly like a healthier fleet.
        log.error(
            "remetering_sweep_truncated",
            extra={"budget_s": SWEEP_BUDGET_S, "demands": tally.seen},
        )
    return (
        f"metered={tally.metered} already={tally.already} unpriceable={tally.unpriceable} "
        f"unreadable={tally.unreadable} unreached={tally.unreached}"
    )


__all__ = [
    "SWEEP_BATCH",
    "SWEEP_BUDGET_S",
    "SWEEP_MINUTE",
    "remeter_refused_leg",
    "remeter_refused_legs",
]
