"""The alarm on Pip's live success scores (D-937).

Every hour, over the last `ALARM_WINDOW`, for the client Pip and the admin Pip: an area whose
thumbs-down share or action-failure share is at or over the scores page's thresholds (with
enough votes or attempts, `ops/copilot_quality.MIN_VOTES` / `MIN_ATTEMPTS`) raises
`copilot_quality_low` (attention), one episode per realm and area, so two areas going bad are
two conditions with their own onset and clear. The detail names the area and the figures;
the examples are on the page (`/admin/ops/pip-quality`), never in the alarm.

It also prunes the admin Pip's outcome rows past `ADMIN_KEEP` days: that table belongs to
no tenant, so no retention policy names it (the client rows expire on the tenant's own
`copilot_memory` clock, `workers/retention.py`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

from sqlalchemy import text

from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of
from apps.api.db.session import admin_session, untenanted_session
from apps.api.ops.copilot_quality import (
    ACTION_FAILURE_LOW_SHARE,
    MIN_ATTEMPTS,
    MIN_VOTES,
    THUMBS_DOWN_LOW_SHARE,
    QualityRealm,
    build_report,
    read_window,
)

log = get_logger(__name__)

#: The window the alarm judges. A day: long enough to collect `MIN_VOTES`, short enough
#: that a fix clears the episode the next day.
ALARM_WINDOW: Final = timedelta(hours=24)
#: The minute of the hour it runs at; :41 is free of the other fleet-wide walks.
ALARM_MINUTE: Final = frozenset({41})
#: How long the admin Pip's outcome rows are kept: past the page's 30-day window.
ADMIN_KEEP: Final = timedelta(days=90)

_PRUNE_ADMIN_SQL: Final = text(
    "DELETE FROM admin_copilot_answer_outcomes WHERE created_at < :cutoff"
)

REALMS: Final[tuple[QualityRealm, ...]] = ("client", "admin")


def _pct(share: float | None) -> str:
    return f"{round((share or 0) * 100)}%"


async def alarm_copilot_quality(ctx: dict[str, Any]) -> str:
    """Raise `copilot_quality_low` for every area over a threshold; prune old admin rows."""
    del ctx
    now = datetime.now(UTC)
    raised = 0
    for realm in REALMS:
        async with admin_session() as session:
            window = await read_window(session, realm=realm, since=now - ALARM_WINDOW)
        report = build_report(window.answers, window.actions, realm=realm, days=1)
        for area in report.by_area:
            figures = area.figures
            if not figures.low:
                continue
            raised += 1
            problems = []
            if "thumbs_down" in figures.low:
                problems.append(
                    f"{figures.thumbs_down} of {figures.thumbs_up + figures.thumbs_down} "
                    f"thumbs were down ({_pct(figures.thumbs_down_share)}, threshold "
                    f"{_pct(THUMBS_DOWN_LOW_SHARE)} over at least {MIN_VOTES} votes)"
                )
            if "action_failures" in figures.low:
                attempts = figures.actions_done + figures.actions_undone + figures.actions_failed
                problems.append(
                    f"{figures.actions_failed} of {attempts} actions failed "
                    f"({_pct(figures.action_failure_share)}, threshold "
                    f"{_pct(ACTION_FAILURE_LOW_SHARE)} over at least {MIN_ATTEMPTS} attempts)"
                )
            alert(
                "CORE_LOGIC",
                "copilot_quality_low",
                detail=(
                    f"The {realm} Pip's '{area.area}' answers in the last 24 hours: "
                    + "; ".join(problems)
                    + ". Example answers to review are on /admin/ops/pip-quality."
                ),
                episode=f"{realm}:{area.area}",
            )
    async with untenanted_session() as session:
        pruned = rowcount_of(await session.execute(_PRUNE_ADMIN_SQL, {"cutoff": now - ADMIN_KEEP}))
    log.info("copilot_quality_check", extra={"areas_low": raised, "admin_pruned": pruned or 0})
    return f"areas_low={raised} admin_pruned={pruned or 0}"


__all__ = ["ADMIN_KEEP", "ALARM_MINUTE", "ALARM_WINDOW", "REALMS", "alarm_copilot_quality"]
