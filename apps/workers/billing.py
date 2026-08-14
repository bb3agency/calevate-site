"""The billing charges the platform owes itself — today the onboarding setup fee.

WHY THIS JOB EXISTS
-------------------
`billing/charges.py` shipped the setup fee (D-63) with the write on the RENDER of the
invoice carrying it, and named the hole in its own docstring: `GET /v1/admin/tenants/
{id}/invoice` was the only caller, so **a tenant whose first invoice nobody opened was
never charged**. Revenue that depends on a human remembering to open a screen is the
condition that module was written to end, one step removed — the fee stopped being
collected out of band and started being billed out of band.

This is the scheduled half. It asks one question of the database every night — *which
tenants are owed a setup fee that has not been recorded?* — and issues the ones it
finds through `issue_setup_fee`, the SAME function and the same unconditional
`INSERT … ON CONFLICT DO NOTHING` the rest of the system uses. Nothing here decides
what a client is charged; that decision has one home, and this is what makes it happen
without being asked.

DAILY, NOT MONTHLY — and it is not the schedule that picks the month
--------------------------------------------------------------------
The obvious reading of "a monthly invoicing job" was rejected after being written out:
the fee is owed the moment an operator puts a plan quoting one on a tenant, not at a
month boundary, so a monthly run would leave a tenant onboarded on the 2nd showing no
setup line on their own in-progress statement for 29 days and then growing one. Daily
bounds that at a day.

**Which month the charge lands on is not this schedule's business at all**, which is
what makes the choice safe: `issue_setup_fee` derives the billing month from the
TENANT's `organizations.created_at` through `ist_billing_month`, so the answer is the
same whether this job runs tonight, tomorrow or (after an outage) next week. The IST
shift is the load-bearing part — a client created at 23:00 UTC on 31 July was onboarded
on 1 August in the only timezone this business bills in — and it is asserted on the job
itself in `tests/setup_fee_test.py`, not only on the helper.

The corollary is that this job never needs to know what "the current month" is, and
deliberately does not ask: a cron's firing instant is the worker's LOCAL clock (arq
evaluates `cron()` fields against the process timezone unless `WorkerSettings.timezone`
is set, which this repo does not set), so any logic keyed on the tick's own date would
be a billing decision made by a container's TZ environment variable.

IDEMPOTENT, KEYED, RETRIED (TRD §8, BACKEND-PATTERNS §5)
--------------------------------------------------------
* IDEMPOTENT at the row: the once-ness is `ux_one_time_charges_tenant_kind_ref` and an
  unconditional insert. Running this twice in a second, or concurrently with an invoice
  render, or after a partial failure, cannot double-charge — the second writer blocks
  on the index entry and writes nothing. There is no read-then-write guard anywhere on
  the path, and the probe below is NOT one: it is a cost filter that may be stale by
  the time the write runs, which is exactly why the write does not trust it.
* KEYED: it is a cron, so arq's job id is `issue_one_time_charges:<intended run>` and
  two WORKERS cannot both run the same tick (`arq/worker.py::run_cron`). Two
  consecutive ticks overlapping is not a concern here the way it is for the dispatch
  tick — a day apart, and harmless if it ever happened, per the paragraph above.
* RETRIED 3 TIMES then DLQ: `cron()` defaults `max_tries=1`, which would silently cost this
  job the ladder every other job in this repo has, so it is passed explicitly in
  `settings.py`. A failing tenant raises `Retry` (arq only retries `Retry`/`RetryJob` —
  see `WorkerSettings.retry_jobs`), and the last attempt alerts instead: a fee that
  could not be issued must be a page an operator can act on, not a silent zero in a
  log.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.billing.charges import SETUP_FEE_KIND, SETUP_FEE_REF, issue_setup_fee
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import admin_session, tenant_session

log = get_logger(__name__)

# Backoff between attempts, in seconds by attempt number. Far longer than the webhook
# ladder's seconds, because nothing is waiting on this tick: a fee issued ten minutes
# late is invisible to everyone, and whatever made a tenant's write fail (a lock, a
# saturated pool, a failover) is likelier to have passed in ten minutes than in ten
# seconds. The last attempt alerts rather than deferring again.
_RETRY_AFTER_S = (60, 600)


def _retry_after(attempt: int) -> int:
    return _RETRY_AFTER_S[min(attempt, len(_RETRY_AFTER_S)) - 1]


async def owed_setup_fees() -> list[tuple[UUID, datetime]]:
    """The tenants that may owe an unrecorded setup fee, with their onboarding instant.

    ONE query, RLS fully applied, and the session count of the tick is therefore
    proportional to the WORK rather than to the client list — the shape D-57 imposed on
    the dispatch tick after measuring that two thirds of it was session machinery.
    `unbilled_setup_fees()` (migration e3f9c2a71d84) is SECURITY INVOKER and re-scopes
    `app.tenant_id` per tenant inside the loop, so every row it reads is a row that
    tenant's own policy admits; the migration carries the whole argument, including why
    the enumeration cannot ride on `engine_agent_routes` the way the dispatch tick's
    does (for a setup fee that bridge is a SUBSET, and c7e4b19d3f52's rule is "a
    superset here and a subset never").

    `admin_session` is what lets the function see the client directory, and it is the
    narrow thing it sounds like: `app.admin` widens `USING` on `organizations` and
    NOTHING else (b57e2f9c4a13), so the money — `plans`, `one_time_charges` — is read
    under `app.tenant_id` here exactly as it is in a request, and written below inside
    an ordinary `tenant_session`. This is not the admin DB ROLE that hard rule 1
    forbids; it is the same directory read `scripts/reconcile_credit_ledger` calls "the
    one sanctioned enumeration surface", for the same platform-money reason.

    Stated plainly because two other workers refuse this session and their tests say so:
    `campaign_dispatch` and `retention` do not need it, because a global bridge already
    covers the population they act on. A tenant owing an onboarding fee may never have
    published an agent, so nothing covers this one — and the alternative, a third entry
    in `RLS_EXEMPT_TENANT_COLUMNS` making every client's commercial terms globally
    readable, is a much larger hole than a directory read that returns ids and a
    timestamp.

    The result is a SUPERSET on purpose (see the migration): `issue_setup_fee` makes the
    real decision per tenant and may decline.
    """
    async with admin_session() as session:
        rows = (
            await session.execute(
                text("SELECT owed_tenant_id, onboarded_at FROM unbilled_setup_fees(:kind, :ref)"),
                {"kind": SETUP_FEE_KIND, "ref": SETUP_FEE_REF},
            )
        ).all()
    return [(UUID(str(row[0])), row[1]) for row in rows]


async def issue_one_time_charges(ctx: dict[str, Any]) -> str:
    """Daily. Issue every setup fee that is owed and has not been recorded.

    Returns a small JSON summary (arq stores it), which is what makes "the tick ran and
    charged nobody" answerable without reading a month of logs.

    A tenant that fails does NOT stop the others: the fees are independent obligations
    and one tenant's broken plan row must not hold up everyone else's billing. The
    failures are counted, and the tick ends by asking for the retry ladder — on which
    every tenant is attempted again, which is free, because issuing is idempotent.
    """
    attempt = int(ctx.get("job_try", 1))
    candidates = await owed_setup_fees()
    issued = 0
    failed = 0
    for tenant_id, onboarded_at in candidates:
        try:
            async with tenant_session(tenant_id) as session:
                if await issue_setup_fee(session, tenant_id=tenant_id, onboarded_at=onboarded_at):
                    issued += 1
        except Exception as exc:
            # Never swallowed: counted here, alerted below if the ladder runs out, and
            # the type is enough for an operator to act on without a client's terms
            # appearing in log aggregation (hard rule 6's discipline, applied to money).
            failed += 1
            log.warning(
                "setup_fee_issue_failed",
                extra={"tenant_id": str(tenant_id), "error": type(exc).__name__},
            )

    totals = {"candidates": len(candidates), "issued": issued, "failed": failed}
    log.info("setup_fees_issued", extra=totals)
    if failed:
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=_retry_after(attempt))
        # Out of attempts: alert, and then FAIL. Returning here would file the tick as a
        # success with a number in it that nobody reads, and a fee that was never issued
        # is not a green run — `optout.py` makes the same pair of gestures for the same
        # reason. The failure is what puts the job in the DLQ.
        alert(
            "WORKER_TERMINAL",
            "setup_fees_unissued",
            detail=f"{failed} tenant(s) after {attempt} attempt(s)",
        )
        raise RuntimeError(f"{failed} setup fee(s) could not be issued")
    return json.dumps(totals)


__all__ = ["issue_one_time_charges", "owed_setup_fees"]
