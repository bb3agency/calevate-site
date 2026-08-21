"""The compliance-flag sweep — the obligation nobody was watching.

WHY THIS CRON EXISTS. Bolna raises **violations** against the account we place every
regulated Indian call through — *"Flagged call violations — content policy, regulatory, or
fraud"* (`bolna-findings/mirror/pages/build-with-ai/mcp-tool-list.md`) — and it publishes
them on a LIST endpoint and nowhere else. There is no webhook for a violation, and this
vendor signs nothing anyway (TRD §5), so unless something of ours reads that list on a
schedule the entire channel is silent. `docs/evidence/bolna-compliance-residency.md` §1
is the full finding; the short version is that an unread flag is discovered at
enforcement, on the one account every client's calling depends on.

WHAT IT IS AND IS NOT
----------------------
It is a READ. It submits nothing. `POST /violations/submit` takes an evidence FILE and a
machine cannot produce evidence — an automated submitter would file something against a
compliance finding to clear a queue, which is the exact failure this sweep exists to
catch. The operator submits, from the vendor console, with `runbooks/engine-violations.md`
open. `engine/violations.py` argues that boundary at length.

WHY HOURLY, AND WHY NOT MORE OFTEN
-----------------------------------
No deadline is documented anywhere on the three vendor pages, so there is no interval to
derive — which cuts both ways. Too slow and a clock we cannot see runs out; too fast and
this is a request per hour against an endpoint whose rate limit is unpublished, re-reading
a list that changes daily at most. **Hourly at :50** keeps time-to-notice under an hour on
an obligation whose remedy is a human action anyway (nobody submits evidence at 3am),
costs ~24 requests a day, and lands clear of every other fleet-wide fan-out in
`settings.py` (:00/:05/:10/:15/:25/:35/:45 are all taken).

**The alarm is deduped, so the flag being OPEN for a week is not a page an hour.**
`core/alerting.py` bounds one page per `stage:code` per 15 minutes and 20/hour globally,
and the suppressed count rides the next delivery — so a standing violation reads as
"still open, N times", which is what an operator needs from a condition only they can
clear.

WHAT IT ATTRIBUTES, AND WHAT IT CANNOT
---------------------------------------
Their record names an `agent_id`, which is our `engine_agent_ref`, so `engine_agent_routes`
turns a flag into the TENANT whose call was flagged. That table is the listed, reasoned
RLS exemption (`db/registry.py`) and is readable untenanted, which is why this attribution
costs one query rather than a per-tenant fan-out. A flag whose agent we cannot resolve —
an agent deleted at the vendor, or one from before the route existed — is COUNTED as
unattributed rather than dropped: "three flags, one of them against an agent we cannot
name" is a materially different sentence from "two flags".

HARD RULE 6. Every id here is vendor-issued and opaque (`violation_id`, `engine_agent_ref`)
or one of ours (`tenant_id`). The phone numbers, the email and the evidence URL on their
payload never reach this module — `engine/violations.py` drops them at the adapter edge,
and its docstring explains why the URL is the dangerous one.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import Retry
from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.violations import (
    OPEN_STATUS,
    EngineViolation,
    SupportsViolations,
    ViolationListing,
)

log = get_logger(__name__)

#: Minutes past the hour. `settings.py` builds the `cron()` registration from this so the
#: schedule and the reason for it are not two facts in two files.
SWEEP_MINUTE = 50

#: How many violation ids an alert body names before it stops listing them. An operator
#: reads the runbook and the console for the rest; an email carrying forty uuids is an
#: email nobody reads.
_ALERT_ID_LIMIT = 5


def _oldest_age_days(violations: tuple[EngineViolation, ...], *, now: datetime) -> int | None:
    """Age in whole days of the oldest flag that carries a `created_at`.

    None when not one of them does — reported as unknown rather than as zero, because
    "raised today" and "we cannot tell when it was raised" must not read the same on the
    one number an operator uses to judge urgency against a deadline nobody has published.
    """
    raised = [v.raised_at for v in violations if v.raised_at is not None]
    if not raised:
        return None
    return max((now - stamp).days for stamp in raised)


async def _tenants_for(refs: set[str]) -> dict[str, UUID]:
    """`engine_agent_ref` → tenant, for the refs a sweep actually saw.

    Untenanted by design: `engine_agent_routes` is the listed RLS exemption and this is a
    platform-wide question with no tenant whose answer it could be — the same argument
    `agents/reconciliation.claim_drift_batch` makes.

    Not filtered on `active`. A withdrawn route is exactly the case where attribution
    matters most: a flag raised against an offboarded client's agent still names a call we
    placed, and reporting it as unattributed would hide who made it.
    """
    if not refs:
        return {}
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref, tenant_id FROM engine_agent_routes "
                    "WHERE engine_agent_ref = ANY(:refs)"
                ),
                {"refs": sorted(refs)},
            )
        ).all()
    return {str(row[0]): UUID(str(row[1])) for row in rows}


async def _sweep() -> str:
    """One tick: read the open compliance flags, attribute them, alert if there are any."""
    engine = get_engine()
    if not isinstance(engine, SupportsViolations):
        # A stated no-op, the shape `check_tls_expiry` uses for `local`. `fake` and
        # `cartesia` publish no violations surface; that is a property of the vendor, not
        # a failure of the sweep, and it must not read like a clean account either.
        log.info("engine_violation_sweep_skipped", extra={"reason": "no_violations_surface"})
        return "skipped_unsupported"
    if not engine.holds_credentials():
        # An engine configured by name with no key cannot be asked. Saying so is the
        # difference between "no open flags" and "we never looked".
        log.warning("engine_violation_sweep_skipped", extra={"reason": "no_credentials"})
        return "skipped_no_credentials"

    listing: ViolationListing = await engine.list_violations(status=OPEN_STATUS)
    open_flags = listing.open_violations
    tenants = await _tenants_for({v.engine_agent_ref for v in open_flags if v.engine_agent_ref})
    attributed = {
        tenants[v.engine_agent_ref]
        for v in open_flags
        if v.engine_agent_ref is not None and v.engine_agent_ref in tenants
    }
    unattributed = sum(
        1 for v in open_flags if v.engine_agent_ref is None or v.engine_agent_ref not in tenants
    )
    age_days = _oldest_age_days(open_flags, now=datetime.now(UTC))

    log.info(
        "engine_violation_sweep",
        extra={
            "engine": engine.name,
            "open": len(open_flags),
            "tenants": len(attributed),
            "unattributed": unattributed,
            "oldest_age_days": age_days,
            "unreadable_rows": listing.unreadable_rows,
            "pages_fetched": listing.pages_fetched,
            "complete": listing.complete,
        },
    )

    if not listing.complete:
        # BEFORE the count, because an incomplete sweep's count is a FLOOR and reporting
        # "0 open" off a walk that stopped at its page cap is the one wrong answer here.
        alert(
            "WORKER_DELIVERY",
            "engine_violation_sweep_incomplete",
            detail=(
                f"the violations listing could not promise it saw everything "
                f"({listing.incomplete_reason}); {len(open_flags)} open flag(s) is a floor, "
                "not a total"
            ),
        )

    if open_flags:
        named = ", ".join(sorted(v.violation_id for v in open_flags)[:_ALERT_ID_LIMIT])
        age = "age unknown" if age_days is None else f"oldest raised {age_days} day(s) ago"
        alert(
            # WORKER_STALL for `engine_agent_drift_detected`'s reason: this is a scheduled
            # PROBE reporting a bad state of the world it went and measured, not a worker
            # dying. Nothing is retried by reporting it — only a person can clear it.
            "WORKER_STALL",
            "engine_violation_open",
            detail=(
                f"{len(open_flags)} compliance flag(s) are open against the voice platform "
                f"account, affecting {len(attributed)} tenant(s) with {unattributed} "
                f"unattributed; {age}. Evidence submission is manual and the vendor "
                f"publishes no deadline. Ids: {named}"
            ),
        )

    return f"open={len(open_flags)} tenants={len(attributed)} complete={listing.complete}"


async def sweep_engine_violations(ctx: dict[str, Any]) -> str:
    """THE JOB. Read the account's open compliance flags and page a human if there are any.

    IDEMPOTENT AND KEYED. Idempotent to the point of being read-only: one vendor listing
    and one indexed lookup, no writes at all, so a retried attempt costs a round trip and
    changes nothing. Keyed by the cron's own arq id (`f'{name}:{to_unix_ms(next_run)}'`),
    which dedupes two workers racing the same tick — there is no business key to add,
    because the unit of work is "the account's open flags right now".

    THE RETRY LADDER IS SPELLED HERE for the reason `sweep_engine_drift` spells it: arq
    0.28 retries for `arq.Retry` and for nothing else, so a job that dies any other way is
    finished on its first attempt whatever `max_tries` says. Three attempts, then an ALERT
    — there is no dead-letter queue (P6.5), an exhausted arq job is `zrem`'d off the queue
    and written to a result key nothing in this repository reads, so the alert on the last
    attempt IS the dead-letter mechanism.

    A VENDOR FAILURE IS IN SCOPE HERE, unlike the drift sweep. There is no per-object
    verdict to record and no partial progress to keep: either we read the list or we did
    not, and "we did not" is a compliance obligation going unwatched for the hour.
    """
    try:
        return await _sweep()
    except Exception as exc:
        log.warning(
            "engine_violation_sweep_failed",
            extra={"reason": exc.__class__.__name__, "attempt": ctx.get("job_try")},
        )
        attempt = int(ctx.get("job_try", 1) or 1)
        if attempt < WORKER_MAX_TRIES:
            # Climbing `defer`, the ladder BACKEND-PATTERNS §4 asks for: a vendor that is
            # rate-limiting or restarting is not helped by three sweeps in ninety seconds.
            raise Retry(defer=30 * attempt) from exc
        alert(
            "WORKER_TERMINAL",
            "engine_violation_sweep_abandoned",
            detail=(
                f"{exc.__class__.__name__} after {attempt} attempt(s); the voice platform's "
                "compliance flags are unwatched until this cron succeeds"
            ),
        )
        raise


__all__ = ["SWEEP_MINUTE", "sweep_engine_violations"]
