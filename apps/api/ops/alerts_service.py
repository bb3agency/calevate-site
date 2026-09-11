"""What the alerting path has been raising — the read side of `/admin/ops/alerts` (D-591).

    GET /v1/ops/alerts

The founder's instruction was two sentences: *"I need to see about failures in admin panel
only. I want high priority things only through mail."* `core/alarm_severity.py` and
`core/alerting.py` are the second sentence. This module is the first, and its whole job is
to answer one question at a glance — **is anything actually broken right now** — which an
inbox has never been able to answer, because an inbox sorts by arrival and a `page` from
03:12 sits under forty `record` rows from 03:14.

**OPEN FIRST, AND OPEN IS A FACT ON THE ROW.** `cleared_at IS NULL` means the condition is
still happening: `workers/alerts.sweep_alert_clears` closes an episode once it has been
quiet for an hour, so an open row is one that has been seen recently or has not yet been
swept. The screen shows open episodes above cleared ones and loud above quiet, because
that is the order the question is asked in.

**NO DERIVATION HERE, FOR `engine_latency.py`'s REASON.** The severity is the one recorded
on the row rather than the one `ALARM_SEVERITY` holds today, so a re-classification never
rewrites the history of what was actually mailed; `emailed` is the transport's own answer
and not "severity == page", so a `page` whose SMTP failed twice reads as the unmailed alarm
it is — the single most important row on the screen and the one a derived column would
paint green.

**PLATFORM-SCOPED, SO NO TENANT WALK.** `platform_alerts` carries no `tenant_id` and no
policy (`db/registry.RLS_EXEMPT_TENANT_COLUMNS`), which is why this is one query and not
the per-tenant walk `engine_latency` and `admin/health` have to do. Nothing here can be
traced to a client.

**HARD RULE 6 IS ALREADY SATISFIED AT THE WRITE.** `core/alert_records.py` redacts `detail`
and `ids` with the same function the alert email body uses, before the row exists. This
module does not redact again and must not pretend to: a second pass would imply the column
could hold something unsafe, which is exactly the belief that lets one land there.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

#: How many episodes one page carries. Generous, because the screen's value is seeing the
#: shape of an evening at once; bounded, because an unbounded read of a table that grows
#: with every alarm is the defect this table's own retention arm exists to prevent.
DEFAULT_LIMIT = 100
MAX_LIMIT = 500

#: How far back the screen looks by default. Seven days spans "what happened over the
#: weekend", which is the question an operator opens this with on a Monday.
DEFAULT_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 90

Severity = Literal["page", "attention", "record"]


class AlertEpisode(BaseModel):
    """One episode of one alarm, exactly as the row holds it."""

    id: UUID
    code: str
    stage: str
    severity: Severity
    service: str
    detail: str | None = None
    #: The `**ids` the call site passed, already redacted at the write.
    ids: dict[str, Any] = Field(default_factory=dict)
    first_seen_at: datetime
    last_seen_at: datetime
    occurrences: int
    #: Whether the TRANSPORT said it landed — not whether the severity would have mailed.
    emailed: bool
    emailed_at: datetime | None = None
    #: NULL while the condition is still happening.
    cleared_at: datetime | None = None

    @property
    def open(self) -> bool:
        return self.cleared_at is None


class AlertReport(BaseModel):
    """The screen's whole payload: the rows, and the counts that answer the question."""

    window_days: int
    episodes: list[AlertEpisode]
    #: Open episodes by severity, over the WHOLE table and not only this page — an
    #: operator asking "is anything broken" must not get an answer that depends on how
    #: many rows fitted. Keys are severities; absent means zero.
    open_by_severity: dict[str, int]
    #: Open `page` episodes that were never successfully mailed. THE NUMBER THIS SCREEN
    #: EXISTS FOR after the inbox: an alarm loud enough to wake somebody that did not.
    open_unmailed_pages: int
    #: False when the window held more episodes than `limit`. Named rather than implied,
    #: for `ExecutionListing.complete`'s reason: a truncated list that looks whole is a
    #: screen quietly describing a subset.
    complete: bool


_SELECT = """
SELECT id, code, stage, severity, service, detail, ids,
       first_seen_at, last_seen_at, occurrences, emailed, emailed_at, cleared_at
FROM platform_alerts
WHERE last_seen_at >= now() - make_interval(days => :days)
-- OPEN FIRST, THEN LOUDEST, THEN MOST RECENT. The severity order is written out rather
-- than alphabetical because 'attention' sorts before 'page' and an ORDER BY that put the
-- quiet rung on top would be the inbox's own failure reproduced on a screen.
ORDER BY (cleared_at IS NULL) DESC,
         CASE severity WHEN 'page' THEN 0 WHEN 'attention' THEN 1 ELSE 2 END,
         last_seen_at DESC
LIMIT :limit
"""

#: The counts, over every OPEN episode regardless of window or page. Separate from the
#: listing for the reason `AlertReport.open_by_severity` gives: "is anything broken" may
#: not be answered by whatever happened to fit on one page.
_OPEN_COUNTS = """
SELECT severity,
       count(*) AS total,
       count(*) FILTER (WHERE severity = 'page' AND NOT emailed) AS unmailed
FROM platform_alerts
WHERE cleared_at IS NULL
GROUP BY severity
"""


async def alert_report(
    session: AsyncSession, *, days: int = DEFAULT_WINDOW_DAYS, limit: int = DEFAULT_LIMIT
) -> AlertReport:
    """One window of alert episodes, plus the open counts. Two statements, no walk."""
    capped = min(max(limit, 1), MAX_LIMIT)
    rows = (
        (await session.execute(text(_SELECT), {"days": days, "limit": capped + 1})).mappings().all()
    )
    episodes = [AlertEpisode(**{**row, "ids": row["ids"] or {}}) for row in rows[:capped]]
    counts = (await session.execute(text(_OPEN_COUNTS))).all()
    return AlertReport(
        window_days=days,
        episodes=episodes,
        open_by_severity={row.severity: row.total for row in counts},
        open_unmailed_pages=sum(row.unmailed for row in counts),
        # The +1 row is the tell, so "exactly `limit` episodes exist" does not report
        # itself as truncated.
        complete=len(rows) <= capped,
    )


__all__ = [
    "DEFAULT_LIMIT",
    "DEFAULT_WINDOW_DAYS",
    "MAX_LIMIT",
    "MAX_WINDOW_DAYS",
    "AlertEpisode",
    "AlertReport",
    "alert_report",
]
