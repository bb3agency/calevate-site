"""The Monday run writing each account's weekly summary (`campaigns/weekly_summary`).

One model call per account per IST week, on the background leg (`background_leg`: our Gemini
first, Azure only where configured, never the Sarvam standby, whose terms permit training on
its inputs). The input is `WeekFigures`, counts and the account's own campaign and step names,
never a transcript (hard rule 6), and it waits for the owner to have turned Pip on, as every
background read of account content does (`account_content_may_reach_models`).

IDEMPOTENCY. Each account is written inside one transaction holding a transaction-scoped
advisory lock on (account, week): a retried or overlapping run either waits out the first or
finds its row (`has_summary`) and pays for nothing. The row and its `usage_events` row commit
together, so a paragraph we paid for is never off the books (hard rule 7); the spend is ours,
`ASSIST_FEATURE_WEEKLY_SUMMARY` is absorbed.

The schedule does not decide the week: `closed_week` converts the firing instant to IST and
only ever names the week that has ended.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final
from uuid import UUID

import httpx
from arq import Retry
from calevate_shared.backoff import jittered_delay_s
from sqlalchemy import text

from apps.api.billing.ai_quota import new_assist_ref, platform_brake_tripped, record_ai_assist_usage
from apps.api.billing.models import ASSIST_FEATURE_WEEKLY_SUMMARY
from apps.api.campaigns import weekly_summary
from apps.api.copilot.consent import account_content_may_reach_models
from apps.api.core import provider_health
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES, job_try
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import chat
from apps.workers.background_leg import BackgroundLeg, background_leg
from apps.workers.extraction import azure_credentials
from apps.workers.fleet_walk import WalkBudget

log = get_logger(__name__)

#: Monday 07:50 IST (`settings.CRON_TIMEZONE`): after the week closed at midnight and after
#: the QA draw at 07:20, before an owner opens the console.
SUMMARY_WEEKDAY: Final = 0
SUMMARY_HOUR: Final = 7
SUMMARY_MINUTE: Final = 50

#: Accounts written per run; the rest are reached the next Monday.
MAX_TENANTS_PER_RUN: Final = 500
SUMMARY_TIMEOUT_S: Final = 60.0
#: About 80 words of English, with room: the paragraph is cut to the column's limit anyway.
SUMMARY_MAX_TOKENS: Final = 300

_TENANTS_SQL: Final = (
    "SELECT DISTINCT tenant_id FROM engine_agent_routes WHERE active "
    "ORDER BY tenant_id LIMIT :limit"
)
_LOCK_SQL: Final = "SELECT pg_try_advisory_xact_lock(hashtext(:key))"


async def summarise_tenant(tenant_id: UUID, *, leg: BackgroundLeg, moment: datetime) -> str:
    """One account's week → its stored summary. Returns what happened, for the run's log."""
    async with tenant_session(tenant_id) as session:
        if not await account_content_may_reach_models(session, tenant_id=tenant_id):
            return "pip_off"
        monday, _, _ = weekly_summary.closed_week(moment)
        locked = (
            await session.execute(
                text(_LOCK_SQL), {"key": f"weekly_summary:{tenant_id}:{monday.isoformat()}"}
            )
        ).scalar()
        if not locked or await weekly_summary.has_summary(session, monday):
            return "done"
        figures = await weekly_summary.week_figures(session, moment)
        if figures.calls < weekly_summary.MIN_CALLS:
            return "quiet"
        async with provider_health.watch(
            "weekly_summary", chat.provider_of(leg.leg), model=leg.leg.wire_model
        ):
            outcome, tier = await leg.complete(
                [
                    {"role": "system", "content": weekly_summary.SYSTEM_PROMPT},
                    {"role": "user", "content": weekly_summary.prompt_figures(figures)},
                ],
                timeout_s=SUMMARY_TIMEOUT_S,
                temperature=0.2,
                max_tokens=SUMMARY_MAX_TOKENS,
            )
        summary = weekly_summary.clean_summary(outcome.content)
        if summary:
            await weekly_summary.store(
                session,
                tenant_id=tenant_id,
                figures=figures,
                summary=summary,
                model=leg.meter_model,
            )
        if outcome.usage is not None:
            await record_ai_assist_usage(
                session,
                tenant_id=tenant_id,
                ref=new_assist_ref(),
                tokens_in=outcome.usage.prompt_tokens,
                tokens_out=outcome.usage.output_tokens,
                cached_tokens_in=outcome.usage.cached_tokens_in,
                model=leg.meter_model,
                feature=ASSIST_FEATURE_WEEKLY_SUMMARY,
                service_tier=tier,
            )
        else:
            alert(
                "CORE_LOGIC",
                "weekly_summary_unmeterable",
                detail=(
                    "A weekly summary was paid for and the provider returned no usage block, "
                    "so it could not be metered. Nothing was estimated."
                ),
                tenant_id=str(tenant_id),
            )
        return "written" if summary else "empty"


async def write_weekly_summaries(ctx: dict[str, Any]) -> str:
    """Weekly. Each account with a live agent gets one paragraph about the week that closed."""
    leg = background_leg(azure_credentials(), call="weekly_summary")
    if leg is None:
        log.info("weekly_summary_no_provider")
        return "no_provider"
    try:
        async with untenanted_session() as session:
            tenants = [
                UUID(str(row))
                for row in (
                    await session.execute(text(_TENANTS_SQL), {"limit": MAX_TENANTS_PER_RUN})
                )
                .scalars()
                .all()
            ]
            brake = await platform_brake_tripped(session)
    except Exception as failure:
        attempt = job_try(ctx)
        if attempt < WORKER_MAX_TRIES:
            raise Retry(defer=jittered_delay_s(attempt * 30)) from failure
        alert(
            "WORKER_TERMINAL",
            "weekly_summary_worklist_failed",
            detail="the weekly summary run could not read which accounts have live agents",
            error=type(failure).__name__,
        )
        raise
    if brake:
        log.warning("weekly_summary_brake_tripped")
        return "brake_tripped"

    moment = datetime.now(UTC)
    clock = WalkBudget()
    tally: dict[str, int] = {}
    failed = 0
    for tenant_id in tenants:
        if clock.spent():
            break
        try:
            result = await summarise_tenant(tenant_id, leg=leg, moment=moment)
        except (httpx.HTTPError, TimeoutError) as failure:
            log.warning(
                "weekly_summary_provider_failed",
                extra={"tenant_id": str(tenant_id), "error": type(failure).__name__},
            )
            result = "provider_failed"
        except Exception:
            log.exception("weekly_summary_tenant_failed", extra={"tenant_id": str(tenant_id)})
            failed += 1
            continue
        tally[result] = tally.get(result, 0) + 1
    if failed or clock.exhausted:
        alert(
            "WORKER_TERMINAL",
            "weekly_summary_sweep_incomplete",
            detail=(
                f"{failed} of {len(tenants)} account(s) failed the weekly summary run"
                + ("; the run ran out of time before the rest" if clock.exhausted else "")
            ),
        )
    log.info("weekly_summary_tick", extra={"tenants": len(tenants), **tally})
    return " ".join(f"{key}={value}" for key, value in sorted(tally.items())) or "none"


__all__ = [
    "MAX_TENANTS_PER_RUN",
    "SUMMARY_HOUR",
    "SUMMARY_MINUTE",
    "SUMMARY_WEEKDAY",
    "summarise_tenant",
    "write_weekly_summaries",
]
