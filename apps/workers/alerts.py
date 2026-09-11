"""Close alarm episodes that have gone quiet, and say so once (D-591).

WHY A SWEEP AND NOT A TIMER. `core/alerting.py` mails a `page` on the occurrence that
OPENS an episode and on no other, which is the whole fix for the twenty-six-message
`fx_rate_stale` thread. That rule has a consequence somebody has to pay for: an episode
that never closes is a code that can never mail again. Nothing in the process knows when a
condition has STOPPED — the absence of an alert is not an event, and no callback fires on
it — so the only thing that can notice is a clock looking at `last_seen_at`.

**A CLEAR IS WORTH A MESSAGE OF ITS OWN.** "The FX feed is back" and "the archiver is
succeeding again" are things the person who was woken at 3am is owed; an alerting system
that only ever tells you about onsets leaves every incident open in the reader's head. One
line, to the same mailbox, and only for an episode that actually WOKE somebody — a `page`
that was emailed. Clearing an `attention` or a `record` silently is the point of those
rungs, and mailing a clear for something whose onset was never mailed would be the
noise this decision exists to remove, arriving from the other direction.

**THE QUIET PERIOD IS FOUR FLUSH WINDOWS** (`ALERT_CLEAR_AFTER_S`, an hour, against
`ALERT_REPEAT_INTERVAL_S`'s fifteen minutes). An ongoing condition refreshes `last_seen_at`
on every flush, so an hour of silence is four missed refreshes rather than a jitter — and
closing early is the failure that costs something, because the next occurrence would then
open a fresh episode and mail again, which is the storm coming back one hour at a time.

**IT IS NOT A RETENTION SWEEP.** Closed episodes stay on `/admin/ops/alerts` until
`workers/retention.prune_reliability_tables` forgets them with the other never-tenant-scoped
infra tables. "It cleared" and "it is old enough to forget" are different clocks.
"""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text

from apps.api.core.alerting import ALERT_CLEAR_AFTER_S
from apps.api.core.logging import get_logger
from apps.api.db.session import untenanted_session

log = get_logger(__name__)

#: How many episodes one tick will close and announce. A bound rather than an unbounded
#: UPDATE for `_sweep_in_batches`' reason one module over: a tick that finds a thousand
#: episodes has met something structural, and a thousand emails is the failure mode this
#: whole decision exists to prevent. What it does not reach this tick it reaches the next.
CLEAR_BATCH = 50

#: Closes every episode whose last observation is older than the quiet period, and hands
#: back exactly what a clear notice needs. ONE statement: `RETURNING` on the UPDATE means
#: there is no window between choosing the rows and claiming them, so two workers running
#: this tick cannot both announce the same clear.
_CLOSE_SQL = """
UPDATE platform_alerts SET cleared_at = now()
WHERE id IN (
    SELECT id FROM platform_alerts
    WHERE cleared_at IS NULL
      AND last_seen_at < now() - make_interval(secs => :quiet_s)
    ORDER BY last_seen_at
    LIMIT :batch
    FOR UPDATE SKIP LOCKED
)
RETURNING code, stage, severity, service, occurrences, emailed, first_seen_at, last_seen_at
"""


async def sweep_alert_clears(ctx: dict[str, Any]) -> str:
    """Close quiet episodes; mail one line for each that had woken somebody.

    Counts and codes only in the log line. An alarm CODE is ours and carries no personal
    data (hard rule 6 is satisfied at the write, in `core/alert_records.py`), but the
    `detail` and `ids` on the row are not read here at all — a clear notice says that a
    condition ended, and the condition's particulars are on the console screen.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(_CLOSE_SQL), {"quiet_s": ALERT_CLEAR_AFTER_S, "batch": CLEAR_BATCH}
            )
        ).all()
        await session.commit()

    announced = 0
    for row in rows:
        # Only an episode that actually MAILED gets a clear. See the module docstring.
        if row.emailed:
            announced += int(_announce_clear(row))
    totals = {
        "cleared": len(rows),
        "announced": announced,
        "codes": sorted({row.code for row in rows}),
    }
    log.info("alert_episodes_cleared", extra=totals)
    return json.dumps(totals)


def _announce_clear(row: Any) -> bool:
    """One plain-text line to the alert mailbox. Returns whether it landed.

    PLAIN TEXT and the same transport as the onset, for `core/alerting._deliver`'s stated
    reason: this reader greps, forwards and pastes, and a multipart alternative renders as
    a mess in all three. Best effort — a clear notice that cannot be sent is a log line,
    never an exception that leaves the rest of the batch unannounced.
    """
    from apps.api.core.settings import get_settings
    from apps.api.core.transport import get_transport

    settings = get_settings()
    recipient = settings.alerts_email or None
    if not recipient:
        return False
    minutes = (row.last_seen_at - row.first_seen_at).total_seconds() / 60
    body = "\n".join(
        [
            f"stage:   {row.stage}",
            f"code:    {row.code}",
            f"service: {row.service}",
            f"status:  CLEARED — no further occurrence for {ALERT_CLEAR_AFTER_S / 60:.0f} minutes",
            f"lasted:  {minutes:.0f} minute(s), {row.occurrences} occurrence(s)",
            "",
            "Nothing is required. The full history is on /admin/ops/alerts.",
        ]
    )
    try:
        return get_transport().send(
            to=recipient,
            subject=f"[calevate/{settings.app_env}/{row.service}] {row.code} cleared",
            body=body,
        )
    except Exception as exc:  # pragma: no cover - transport failures are logged, not raised
        log.warning("alert_clear_notice_failed", extra={"reason": type(exc).__name__})
        return False


__all__ = ["CLEAR_BATCH", "sweep_alert_clears"]
