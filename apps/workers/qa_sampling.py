"""The weekly QA draw — 5% of every client's calls, picked so the pick can be checked.

SURFACES §1: "QA sampling: spot-check ~5% of calls per client per week (queue surfaced
in admin)". `apps/api/quality/sampling.py` holds the draw and argues why it is a keyed
hash rather than `random()`; this file is the tick that runs it for every tenant.

WHICH WEEK IT DRAWS
--------------------
The week that just ENDED, never the current one. A tick on Monday morning drawing
Monday's calls would sample a week that is three hours old and then never look at the
rest of it — the sample would be 5% of Monday, filed as the week. So the job runs early
Monday IST and asks for the previous Monday's week, which is closed by then.

It also re-affirms the week BEFORE that (`_WEEKS_BACK`). A call whose post-call pipeline
finished late — the reconciliation poller resolves executions up to ten minutes after the
fact, and a stalled pipeline longer — can land in a week the draw has already been made
for. Re-running is safe by construction (`draw_week_sample` is idempotent and the unique
constraint absorbs what is already filed), so the cheapest correct answer is to look
again once. A late arrival either does not make the cut, or it does and appears with the
frame it was actually drawn from.

IDEMPOTENCY, KEYING, RETRIES
-----------------------------
The job is idempotent at the row level, so a retry costs a query and inserts nothing.
It is registered with `max_tries` passed EXPLICITLY: `arq.cron()` defaults `max_tries`
to 1, and `WorkerSettings.max_tries` is only the default for functions that do NOT carry
their own — a sampling tick that quietly gave up on its first failure would leave a week
undrawn while every screen looked fine. This bit `issue_one_time_charges` first; the
comment there is the precedent, and `tests/qa_sampling_test.py` verifies the schedule
against a real `arq.worker.Worker` rather than trusting either comment.

A failed tenant does NOT fail the tick: one client's database error must not cost every
other client their week's sample. The failure is counted, alerted and re-raised as a
`Retry` only when EVERY tenant failed, which is the shape that means the problem is ours
rather than one tenant's.

AND THE WALK IS BOUNDED, which it was not. `_DIRECTORY` is EVERY organization and each one
costs a `tenant_session` plus one draw per week in `_WEEKS_BACK` — the same cost shape
`dispatcher.report_overdue_erasures` was bounded for (D-369) and the same one P6.2 took out
of the nightly retention sweep after measuring it at ~3 minutes on ~16k organizations. Past
`WorkerSettings.job_timeout` (300s) arq cancels the tick, and — read off the installed
source rather than assumed (`fleet_walk` cites the lines) — does not retry it: the worker
sees `TimeoutError`, which is none of the three exceptions `retry_jobs` honours, so the
draw is finished on its first attempt with a log line nothing alerts on. The tenants past
the cut are never drawn and the week reads as quiet. `fleet_walk.WalkBudget` stops the pass
while it can still SAY so.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import admin_session, tenant_session
from apps.api.quality.sampling import draw_week_sample, ist_week_start
from apps.workers.fleet_walk import WalkBudget

log = get_logger(__name__)

#: How many closed weeks each tick looks at. 2 = the week that just ended, plus the one
#: before it as a late-arrival sweep. More would be re-querying settled weeks forever.
_WEEKS_BACK = 2

#: `ORDER BY id` is load-bearing rather than tidy: the walk below can run out of its time
#: budget, and an UNORDERED directory starves a different arbitrary slice of the fleet every
#: week — so no client is reliably sampled and nobody can say which were missed. Ordered,
#: the starved tail is stable and the alarm's advice ("the fleet has outgrown one tick") is
#: actionable. The same argument `dispatcher._ERASURE_DIRECTORY` makes for the same walk.
_DIRECTORY = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"


def closed_weeks(now: datetime, *, count: int = _WEEKS_BACK) -> list[date]:
    """The last `count` COMPLETE IST weeks, most recent first.

    `ist_week_start(now)` is the week in progress, so every entry here is one or more
    weeks behind it. A test can pass any instant; the job passes `now()`.
    """
    current = ist_week_start(now)
    return [current - timedelta(weeks=back) for back in range(1, count + 1)]


async def draw_for_tenants(tenant_ids: Sequence[UUID], weeks: Sequence[date]) -> dict[str, int]:
    """One tick over an EXPLICIT tenant list.

    Split out of the job for the reason `retention.sweep_tenants` is: the resolution step
    and the drawing step are separately exercisable, and a test of the draw does not have
    to enumerate every organization in the database to reach it.

    A failed tenant does NOT fail the tick — one client's database error must not cost
    every other client their week's sample.
    """
    drawn = 0
    scanned = 0
    failed = 0
    probed = 0
    # The pass stops itself rather than being cancelled by arq mid-tenant and re-run from
    # the top — see the module docstring and `fleet_walk.WalkBudget`.
    budget = WalkBudget()
    for tenant_id in tenant_ids:
        if budget.spent():
            break
        probed += 1
        try:
            async with tenant_session(tenant_id) as scoped:
                for week_start in weeks:
                    result = await draw_week_sample(
                        scoped, tenant_id=tenant_id, week_start=week_start
                    )
                    drawn += result.inserted
                    scanned += result.population
        except Exception:  # one tenant's failure is not the tick's — see the docstring
            # The id, never the error's payload: an exception string from psycopg can
            # quote the row that broke it, and these rows name calls.
            log.exception("qa_sample_draw_failed", extra={"tenant_id": str(tenant_id)})
            failed += 1
    return {
        "tenants": len(tenant_ids),
        # What the pass actually REACHED, which is what every other count here is relative
        # to. `tenants` alone reads as coverage and stops being coverage the moment the
        # budget runs out.
        "tenants_probed": probed,
        "weeks": len(weeks),
        "calls_in_frame": scanned,
        "samples_drawn": drawn,
        "tenants_failed": failed,
        "tenants_unreached": len(tenant_ids) - probed,
    }


async def draw_qa_samples(ctx: dict[str, Any]) -> str:
    """Weekly. Draws each tenant's 5% for the weeks that have closed.

    Counts only in the log and in the return value — no call id, no phone number, no
    transcript (hard rule 6).
    """
    # `ctx` IS read now — `job_try` bounds the retry ladder at the bottom of this
    # function (P6.5). It used to be discarded on the first line, which is how the
    # unbounded `Retry` went unnoticed: nothing in the body could see which attempt it was.
    attempt = int(ctx.get("job_try", 1) or 1)
    weeks = closed_weeks(datetime.now(UTC))
    async with admin_session() as directory:
        rows = (await directory.execute(text(_DIRECTORY))).all()
    tenant_ids = [UUID(str(row[0])) for row in rows]

    totals = await draw_for_tenants(tenant_ids, weeks)
    log.info("qa_sample_draw", extra=totals)
    if totals["tenants_unreached"]:
        # A SEPARATE ALARM from the failure one, because it says what the failure count
        # cannot: these tenants were never attempted, so `samples_drawn` is a floor rather
        # than the week's draw. Silence here reads exactly like a quiet week.
        alert(
            "WORKER_DELIVERY",
            "qa_sample_draw_truncated",
            detail=(
                f"the weekly QA draw reached {totals['tenants_probed']} of "
                f"{len(tenant_ids)} tenant(s) inside its time budget and stopped there; "
                f"{totals['tenants_unreached']} tenant(s) have no sample for the week. "
                "The walk costs one session per organization, so this is the fleet "
                "outgrowing one tick rather than a transient failure"
            ),
        )
    if totals["tenants_failed"]:
        alert(
            "WORKER_DELIVERY",
            "qa_sample_draw_failed",
            detail=f"{totals['tenants_failed']} tenants",
        )
    # AGAINST WHAT THE PASS REACHED, not against the directory. The two were the same
    # number until the walk grew a time budget; now a truncated pass in which every
    # attempted tenant failed would have `tenants_failed < len(tenant_ids)` and slip past
    # this arm entirely — the "database or deploy" verdict is about the tenants that were
    # actually asked, and the ones never reached are the other alarm's business.
    if totals["tenants_probed"] and totals["tenants_failed"] == totals["tenants_probed"]:
        # Everybody failed: that is a database or a deploy, not a tenant. Ask for the
        # retry ladder — `WorkerSettings.retry_jobs` only honours `Retry`, so a plain
        # raise here would be a single silent attempt.
        #
        # BOUNDED, and it was not (P6.5). This raised `Retry` unconditionally, and arq does
        # not honour it on the final attempt: the job finishes with `JobExecutionFailed`
        # and a `logger.warning` that nothing reads. The per-tenant alert above HAD already
        # fired, which is why this job was closer to correct than its two siblings — but
        # "some tenants failed" and "the whole weekly draw was abandoned" are different
        # incidents and only the first of them was ever reported.
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=300)
        alert(
            "WORKER_TERMINAL",
            "qa_sample_draw_abandoned",
            detail=(
                f"the weekly draw failed for all {totals['tenants_probed']} tenant(s) "
                "it reached after "
                f"{attempt} attempt(s); this week's 5% sample is undrawn and the next "
                "tick is seven days away"
            ),
        )
        raise RuntimeError(f"qa sample draw abandoned after {attempt} attempt(s)")
    return json.dumps(totals)


__all__ = ["closed_weeks", "draw_for_tenants", "draw_qa_samples"]
