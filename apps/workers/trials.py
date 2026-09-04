"""The nightly tick that closes trials and, for a client who did not buy, files the
erasure (D-536).

Two acts, both of which are BOOKKEEPING: neither of them is what makes the platform behave
correctly, which is the property that makes a daily job an acceptable place for them.

1. **A trial past its end date is recorded as `expired`.** It has ALREADY stopped bypassing
   the credit gate — `trials.TrialState.is_active` asks the clock as well as the status,
   precisely so that a late sweep cannot hand out free calling — so what this does is move
   the row, stamp `erase_after`, and restart the client's counters at the boundary. Being a
   day late costs a stale word on a screen and a day of counters, never a free minute.

2. **A non-converting client's personal data is scheduled for erasure once the grace
   period is up.** It FILES a tenant erasure through `compliance/tenant_erasure.py` and
   erases nothing itself — there is deliberately no second eraser in this tree, and the one
   that exists already knows about the append-only ledgers, the 90-day recording floor, the
   holds table and the certificate. `erasure_filed_at` is what makes the sweep idempotent:
   `request_tenant_erasure` would return the open request anyway, but a job that re-asks
   every night for ever is a job nobody can tell from a broken one.

**A CONVERTING CLIENT IS NEVER TOUCHED BY THE SECOND ACT.** Their `erase_after` is NULL,
the query cannot see them, and that is not an optimisation: their leads, calls and
transcripts are the value they just built, and one of those callers may be a patient
waiting to be rung back.

**THE ERASURE PRECONDITION IS AN ACCOUNT THAT IS CLOSED, AND THIS JOB DOES NOT CLOSE IT.**
`tenant_erasure.assert_erasable` refuses any tenant that is not already `churned`, because
`deleted_at` must stay a strict refinement of "account closed" or the nine readers of that
column start disagreeing about whether a business exists. Ending a commercial relationship
is a HUMAN act with a reason attached (`admin/routes.py` demands one, and demands a step-up
for the terminal state), and a nightly job that churned accounts on a timer would be that
decision taken by a cron. So when the grace period is up and the account is still open, this
job ALERTS rather than acts: `trial_erasure_blocked` names the client and what has to
happen. That is the honest failure — a person closes the account, and the next tick files
the erasure without further prompting.

**THE WALK IS BOUNDED**, the shape `qa_sampling` and `dispatcher.report_overdue_erasures`
established (D-369): one `tenant_session` per organisation, stopped by a `WalkBudget` before
`WorkerSettings.job_timeout` can cancel the tick mid-tenant, and the truncation is REPORTED
because a pass that silently stopped halfway reads exactly like a quiet night. Almost every
iteration is one indexed lookup that finds no trial and returns — trials are rare — so the
cost is the session, which is the same cost every other fleet walk in this tree pays.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text

from apps.api.billing.trials import (
    EXPIRY_REASON,
    TRIAL_ACTIVE,
    TRIAL_EXPIRED,
    end_trial,
    mark_erasure_filed,
    read_trial,
)
from apps.api.compliance.tenant_erasure import REQUIRED_STATUS, request_tenant_erasure
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.session import admin_session, tenant_session
from apps.workers.fleet_walk import WalkBudget

log = get_logger(__name__)

#: Every live organisation, in a stable order so a truncated pass resumes from the same
#: place next tick rather than sampling a different half of the fleet each night. The same
#: directory `qa_sampling._DIRECTORY` walks, and read through `admin_session`, which widens
#: `USING` on `organizations` ONLY (migration b57e2f9c4a13) and unlocks no client data.
_DIRECTORY = "SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id"

#: The reason recorded on the erasure this job files. It is read by a human later, so it
#: says what happened rather than naming a function.
ERASURE_REASON = (
    "The trial ended without the client converting, and the grace period agreed when the "
    "trial was opened has now passed."
)


async def _close_if_expired(tenant_id: UUID, *, now: datetime) -> bool:
    """End an open trial whose date has passed. True if one was ended.

    Inside a `tenant_session`, so `tenant_trials`' RLS is what scopes it — this job never
    reaches for a wider role to see a client's rows (hard rule 1).
    """
    async with tenant_session(tenant_id) as scoped:
        trial = await read_trial(scoped, tenant_id=tenant_id)
        if trial is None or trial.status != TRIAL_ACTIVE or now < trial.ends_at:
            return False
        await end_trial(
            scoped,
            tenant_id=tenant_id,
            outcome=TRIAL_EXPIRED,
            reason=EXPIRY_REASON,
            # THE END DATE, NOT `now`. The trial ended when its own clock said so, and
            # stamping the sweep's instant would date the counting-period boundary to
            # whenever this job happened to run — a client whose tick was late would have a
            # day of free calling counted into their first paid period.
            at=trial.ends_at,
        )
    log.info("trial_expired", extra={"tenant_id": str(tenant_id), "trial_id": str(trial.id)})
    return True


async def _file_erasure_if_due(tenant_id: UUID, *, now: datetime) -> str | None:
    """File the tenant erasure for a non-converting client whose grace is up.

    Returns `"filed"`, `"blocked"` (the account is still open — a human must close it) or
    None (nothing due). Three outcomes rather than a bool because the caller has to report
    the middle one: an erasure that cannot proceed is a standing condition somebody has to
    clear, not a quiet no-op.
    """
    async with tenant_session(tenant_id) as scoped:
        trial = await read_trial(scoped, tenant_id=tenant_id)
        if (
            trial is None
            # A converting client has NULL here, for ever, and this is the line that keeps
            # their data. It is not a filter for efficiency.
            or trial.erase_after is None
            or trial.erasure_filed_at is not None
            or trial.status == TRIAL_ACTIVE
            or now < trial.erase_after
        ):
            return None
        status = (
            await scoped.execute(
                text("SELECT status FROM organizations WHERE id = :tid"), {"tid": tenant_id}
            )
        ).scalar()
        if str(status) != REQUIRED_STATUS:
            # Not an error and not something to work around — see the module docstring. The
            # account is still commercially open, and closing it is a human decision with a
            # reason and a step-up attached.
            return "blocked"
        await request_tenant_erasure(scoped, tenant_id=tenant_id, reason=ERASURE_REASON)
        await mark_erasure_filed(scoped, trial_id=trial.id, at=now)
    log.info(
        "trial_erasure_filed",
        extra={"tenant_id": str(tenant_id), "trial_id": str(trial.id)},
    )
    return "filed"


async def sweep_trials(ctx: dict[str, Any]) -> str:
    """Daily. Expires trials that have run out, and files the erasures that are due.

    Counts only in the log and the return value — an organisation id is not personal data
    but a client's commercial state is not something to spray across a log line either
    (hard rule 6 governs the fields that matter; this keeps to the same discipline).

    A failing tenant does NOT fail the tick, the rule `qa_sampling.draw_for_tenants`
    states: one client's database error must not stop every other client's trial from
    ending. Failures are counted and alerted.
    """
    del ctx  # the tick takes no arguments; retries are bounded by `cron(max_tries=...)`
    now = datetime.now(UTC)
    async with admin_session() as directory:
        rows = (await directory.execute(text(_DIRECTORY))).all()
    tenant_ids = [UUID(str(row[0])) for row in rows]

    budget = WalkBudget()
    expired = filed = blocked = failed = probed = 0
    for tenant_id in tenant_ids:
        if budget.spent():
            break
        probed += 1
        try:
            if await _close_if_expired(tenant_id, now=now):
                expired += 1
            # ASKED IN THE SAME TICK AS THE EXPIRY ABOVE, deliberately: the two are days
            # apart in practice (the grace period sits between them), so ordering them is
            # free, and a client whose grace was already up when their trial expired — an
            # account nobody touched for a month — is handled on one pass rather than two.
            outcome = await _file_erasure_if_due(tenant_id, now=now)
            if outcome == "filed":
                filed += 1
            elif outcome == "blocked":
                blocked += 1
                # WORKER_DELIVERY: the tick ran and could not complete one client's work.
                # There is no COMPLIANCE stage and one is deliberately not invented for
                # this — `FailureStage` records why a stage nothing can emit is worse than
                # a missing one, and the operator action here is the same shape as every
                # other WORKER_DELIVERY: a named client, a named next step.
                alert(
                    "WORKER_DELIVERY",
                    "trial_erasure_blocked",
                    detail=(
                        f"tenant {tenant_id}: the trial ended without conversion and the "
                        "grace period has passed, but the account is still open so the "
                        "erasure cannot be filed. Close the account on the Account state "
                        "screen; the next nightly tick files the erasure by itself. Until "
                        "then this client's personal data is being kept past the period we "
                        "agreed to keep it for (DPDP s.8(7))"
                    ),
                )
        except Exception:
            failed += 1
            log.exception("trial_sweep_tenant_failed", extra={"tenant_id": str(tenant_id)})

    totals = {
        "tenants_probed": probed,
        "trials_expired": expired,
        "erasures_filed": filed,
        "erasures_blocked": blocked,
        "tenants_failed": failed,
        "tenants_unreached": len(tenant_ids) - probed,
    }
    log.info("trial_sweep", extra=totals)
    if totals["tenants_unreached"]:
        # ITS OWN ALARM, for the reason `qa_sampling` gives: these tenants were never
        # asked, so every count above is a floor. Silence here reads exactly like a night on
        # which no trial happened to end.
        alert(
            "WORKER_DELIVERY",
            "trial_sweep_truncated",
            detail=(
                f"the trial sweep reached {probed} of {len(tenant_ids)} tenant(s) inside "
                f"its time budget; {totals['tenants_unreached']} were not asked, so a trial "
                "that ended today may still read as running and an erasure that is due may "
                "not have been filed"
            ),
        )
    if failed:
        alert("WORKER_DELIVERY", "trial_sweep_failed", detail=f"{failed} tenants")
    return (
        f"expired={expired} erasures_filed={filed} blocked={blocked} "
        f"failed={failed} probed={probed}"
    )


__all__ = ["ERASURE_REASON", "sweep_trials"]
