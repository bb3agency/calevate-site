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
from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session
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

#: How many demands one tick will look at, oldest first.
#:
#: **THE CAP IS NOT A PAGE SIZE, IT IS THE POINT AT WHICH THE BACKLOG IS THE INCIDENT** —
#: `reconcile_outstanding_calls.OUTSTANDING_PROBE_BUDGET`'s argument exactly. Two hundred
#: unpriced legs waiting on an attestation is not a queue to work through politely; it is a
#: rate card with a hole in it, and the answer is the console rather than a faster sweep.
#: A demand past the cut is reached on the next tick, and a demand's window is 90 days.
SWEEP_BATCH = 200

#: Wall clock one tick may spend, checked BETWEEN tenants. Same instrument and same reason as
#: `engine_reconciliation.SWEEP_BUDGET_S`: the batch cap bounds the COUNT and this bounds the
#: TIME, and a pool that has started answering slowly turns the first into the second.
SWEEP_BUDGET_S = 60.0

#: Every demand on the books, oldest first, whatever its dispatch status.
#:
#: **STATUS IS DELIBERATELY NOT IN THE PREDICATE.** The row's `status` describes the
#: DISPATCHER's business with it — did the job get published — and says nothing about whether
#: the leg is now priceable, which is the only question here. A `published` demand whose job
#: ran and found no attested price is exactly the row this sweep exists for.
#:
#: `ORDER BY created_at` for `_due_tenants`' reason: without it the order is planner-dependent
#: and which demands a truncated tick reached would change from tick to tick.
_DEMANDS_SQL = """
SELECT payload FROM outbox_messages
WHERE job = :job
ORDER BY created_at
LIMIT :cap
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


async def remeter_refused_legs(ctx: dict[str, Any]) -> str:
    """Try every parked measurement against today's rate card.

    THE RECOVERY PATH FOR AN ATTESTATION THAT ARRIVED AFTER THE CALL. Nothing tells this
    sweep that a price was entered — there is no event to subscribe to and adding one would
    couple the ops console to the metering path — so it simply asks the rate card again,
    hourly, for every demand on the books. The question is one indexed read and one function
    call per demand, and the answer on a healthy deployment is `already_metered` or nothing
    at all.

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
    async with untenanted_session() as session:
        rows = list(
            (await session.execute(text(_DEMANDS_SQL), {"job": REMETER_JOB, "cap": SWEEP_BATCH}))
            .tuples()
            .all()
        )
    demands, unreadable = _demands(rows)

    by_tenant: dict[UUID, list[RemeterDemand]] = defaultdict(list)
    for demand in demands:
        by_tenant[demand.tenant_id].append(demand)

    metered = 0
    already = 0
    unpriceable = 0
    unreached = 0
    truncated = False
    for tenant_id, tenant_demands in by_tenant.items():
        if time.monotonic() - started >= SWEEP_BUDGET_S:
            truncated = True
            break
        for demand in tenant_demands:
            try:
                verdict = await remeter(demand)
            except Exception:
                # The ids, never the exception's payload: a psycopg error string can quote
                # the row that broke it, and these rows are one client's money.
                log.exception(
                    "remeter_failed",
                    extra={"tenant_id": str(tenant_id), "call_id": str(demand.call_id)},
                )
                unreached += 1
                continue
            if verdict == "metered":
                metered += 1
            elif verdict == "already_metered":
                already += 1
            else:
                unpriceable += 1

    if unpriceable or unreadable or unreached:
        # `error` and not `warning`, for `settle_call`'s reason at the same seam: an unmetered
        # leg is spend we absorbed and cannot bill. It is a LOG LINE and not an `alert()`
        # because this condition has no code in `core/alarm_severity.py` and a call site may
        # not choose its own loudness — the alarm is the one piece of this fix that needs a
        # file outside this change's remit, and `admin/health.calls_unmetered` already stops
        # the account board for the calls it leaves behind.
        log.error(
            "remetering_debt_outstanding",
            extra={
                "unpriceable": unpriceable,
                "unreadable": unreadable,
                "unreached": unreached,
                "tenants": len(by_tenant),
            },
        )
    if truncated:
        # Said out loud for `outstanding_probe_budget_exhausted`'s reason: a sweep that
        # stopped early and reported a smaller number reads exactly like a healthier fleet.
        log.error(
            "remetering_sweep_truncated",
            extra={"budget_s": SWEEP_BUDGET_S, "demands": len(demands)},
        )
    return (
        f"metered={metered} already={already} unpriceable={unpriceable} "
        f"unreadable={unreadable} unreached={unreached}"
    )


__all__ = [
    "SWEEP_BATCH",
    "SWEEP_BUDGET_S",
    "SWEEP_MINUTE",
    "remeter_refused_leg",
    "remeter_refused_legs",
]
