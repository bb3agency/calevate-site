"""The ACCOUNT-level knowledge sweep (D-519) — gate 43e's measurement, on a schedule.

`kb_reconciliation.py` sweeps agents and cannot, by construction, see an object no agent
references. `kb/orphans.py` carries the full argument for why that residue matters and why
nothing may be deleted on the strength of it; this module is the tick that goes and looks.

ONE VENDOR CALL PER DAY, AND THAT IS THE WHOLE COST
---------------------------------------------------
`list_account_kb` is an account-wide listing, walked to the end of its pages — the dearest
single read in this adapter and the one the KB drift sweep was deliberately sized to
avoid making per agent. So it is made ONCE, daily, rather than hourly: the residue this
finds is created by crashes and by hand, both of which are rare, and none of the three
verdicts becomes more actionable for being eight hours fresher. An operator acting on an
unclaimed object has to talk to a client first anyway.

**04:40, and the minute is not free.** The hours around it are taken: 03:17 the expiry
sweep, 03:40 retention, 04:05 the TLS probe, and :23 of every hour the KB drift sweep. A
listing that grows with every source every client has ever published does not belong in
the same minute as any of them.

WHY IT IS NOT PART OF THE KB DRIFT SWEEP, which reads the same feature. Three reasons and
the first is enough: that sweep is per agent and takes a per-agent advisory lock to avoid
racing a publish, while this one is per ACCOUNT and holds no lock at all — it cannot, and
it does not need to, because `MIN_ORPHAN_AGE_S` is what keeps a publish in flight from
reading as a finding. Second, they run at different cadences for different reasons.
Third, a failure in either would take the other with it, and the agent sweep is the one
that guards what a caller HEARS.

WHAT IT WRITES: nothing. It logs counts and it alerts. There is deliberately no table —
the report is a diagnostic an operator reads when the alarm fires or when they open the
console, and a stored copy would be a second answer to the same question, stale by up to a
day, that a reader would have to be told not to trust. `GET /v1/ops/kb-orphans` runs the
identical function against a listing it fetches itself.

HARD RULE 6: counts, an engine name, and no handle. A handle is an opaque vendor id and
logging one is permitted, but a log line is not where an operator acts on it — the route
is, and it names them there.
"""

from __future__ import annotations

from typing import Any

from arq import Retry

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine
from apps.api.kb.orphans import KbOrphanReport, reconcile_account_kb

log = get_logger(__name__)

#: The schedule, as `settings.py` reads it. Hour and minute both come from here so the
#: cron registration and the reasoning above cannot drift apart.
ORPHAN_SWEEP_HOUR = frozenset({4})
ORPHAN_SWEEP_MINUTE = frozenset({40})


async def account_kb_report() -> KbOrphanReport | None:
    """The one vendor round trip, plus the cross-tenant read that scores it.

    `None` when the engine has no knowledge base at all: there is no account pool to
    sweep, `publish_source` refuses on the same capability, and asking anyway would report
    every claim as stranded — a permanently red console describing a capability the
    platform never had. The KB drift sweep opens with the identical guard.

    PUBLIC because the ops route calls it too, and the two must not be two readings of the
    same account that can disagree about what "unclaimed" means.
    """
    engine = get_engine()
    if not engine.capabilities.has("knowledge_base"):
        return None
    listing = await engine.list_account_kb()
    async with untenanted_session() as session:
        return await reconcile_account_kb(session, listing, engine=engine.name)


async def _sweep() -> str:
    engine_name = get_engine().name
    report = await account_kb_report()
    if report is None:
        log.info("kb_orphan_sweep_no_knowledge_base", extra={"engine": engine_name})
        return "objects=0 findings=0"
    log.info(
        "kb_orphan_sweep",
        extra={
            "engine": engine_name,
            "accounted": report.accounted,
            "unrecorded": report.unrecorded,
            "unclaimed": report.unclaimed,
            "stranded": report.stranded,
            "listing_complete": report.listing_complete,
        },
    )
    if not report.listing_complete:
        # A LISTING WE COULD NOT FINISH IS ITS OWN ALARM, and it is not the orphan alarm.
        # Reporting "0 findings" from a truncated walk is the failure this whole feature
        # exists to prevent — a client's stranded document unseen because nobody looked
        # properly — so the operator is told that the instrument, not the account, is what
        # was wrong.
        alert(
            "WORKER_STALL",
            "engine_kb_account_listing_incomplete",
            detail=(
                "the voice platform's account-wide knowledge listing could not be read to "
                f"the end ({report.listing_incomplete_reason}), so nothing can be said "
                "about what it holds that no client of ours claims"
            ),
        )
    if report.findings:
        alert(
            # `WORKER_STALL` for `sweep_kb_drift`'s reason: the enum answers "where in the
            # pipeline did this die", and this is a scheduled PROBE reporting a bad state
            # of the world rather than a worker dying. A member per alarm would make the
            # enum a list of alarms.
            "WORKER_STALL",
            "engine_kb_orphans_detected",
            detail=(
                f"{report.unrecorded} knowledge base(s) on the voice platform carry our "
                f"naming and no record, {report.unclaimed} are attributable to nobody, and "
                f"{report.stranded} we believe are live are not there. Nothing has been "
                "deleted — see GET /v1/ops/kb-orphans"
            ),
        )
    return f"objects={report.accounted + report.findings} findings={report.findings}"


async def sweep_kb_orphans(ctx: dict[str, Any]) -> str:
    """THE JOB. One account listing, scored against every claim we hold. Deletes nothing.

    IDEMPOTENT AND KEYED for `sweep_kb_drift`'s reasons: it writes nothing at all, so
    running it twice costs one extra vendor listing and changes no row; the cron's own arq
    id dedupes two workers racing the same tick.

    THE RETRY LADDER is the one `sweep_kb_drift` documents, and it is here for a sharper
    reason than usual. arq retries for `arq.Retry` and nothing else, and the failure this
    job is most likely to suffer is a vendor listing that times out — which is exactly the
    failure that must not be allowed to mean "nothing to report until tomorrow". Three
    attempts, then an alert, because an exhausted arq job is written to a result key
    nothing in this repository reads.
    """
    try:
        return await _sweep()
    except Exception as exc:
        log.warning(
            "kb_orphan_sweep_failed",
            extra={"reason": exc.__class__.__name__, "attempt": ctx.get("job_try")},
        )
        attempt = int(ctx.get("job_try", 1) or 1)
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=30 * attempt) from exc
        alert(
            "WORKER_TERMINAL",
            "kb_orphan_sweep_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s); nothing is watching "
                "the voice platform for knowledge bases no client of ours claims"
            ),
        )
        raise


__all__ = [
    "ORPHAN_SWEEP_HOUR",
    "ORPHAN_SWEEP_MINUTE",
    "account_kb_report",
    "sweep_kb_orphans",
]
