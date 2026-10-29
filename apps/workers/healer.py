"""The auto-healer's two clocks (D-701).

`score_agent_health` (four times an hour) turns real calls into per-agent health windows,
judges them against each agent's own baseline, and opens an incident for an agent that has
been unwell for long enough or whose line is broken — or one platform incident when the
voice platform itself is failing.

`run_healer` (every minute) does everything else, in this order: opens incidents for open
alarm episodes a playbook answers; advances every due incident one step (act, verify,
retry, escalate, protect, restore); pages the founder on WhatsApp for new `page` alarms;
and tells clients about their line.

`healer_sweep` wraps the seven repair sweeps so each runs as its playbook: under the kill
switches and into the same ledger. Their schedules stay in `workers/settings.CRON_JOBS`.

Every step is recorded in `heal_actions`. A failure in one incident never stops the rest
of the tick.
"""

from __future__ import annotations

import asyncio
import functools
import json
from collections import Counter
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any, Final
from uuid import UUID

from sqlalchemy import text

from apps.api.agents.engine_settings import check_agent_settings
from apps.api.agents.publishing import engine_drift_for
from apps.api.core.alerting import alert
from apps.api.core.logging import get_logger
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.health import SPIKE_THRESHOLD, PlatformStatus, ReportsPlatformStatus
from apps.api.healer import health, incidents, ledger, money, notices, proposals, protection
from apps.api.healer.incidents import Incident
from apps.api.healer.playbooks import (
    AGENT_HEALTH_DEGRADED,
    AGENT_LINE_BROKEN,
    ENGINE_PLATFORM_OUTAGE,
    MONEY_REVIEW,
    PLAYBOOK_BY_JOB,
    PLAYBOOK_BY_KEY,
    PLAYBOOK_BY_TRIGGER,
    may_run,
)
from apps.api.reliability.engine_actions import check_agent_actions
from apps.api.reliability.engine_webhooks import ensure_agent_webhook
from apps.api.reliability.service import read_dead_letter_queue, replay_dead_letters
from apps.api.tenancy.engine_workspace import queue_workspace_provisioning, read_workspace_state

log = get_logger(__name__)

#: When the scorer runs: two minutes after each fifteen-minute window closes, on minutes
#: no other fleet-wide walk uses (`tests/job_registration_test.py`).
SCORE_MINUTES: Final = frozenset({1, 16, 32, 47})
#: How many due incidents one `run_healer` tick advances.
INCIDENT_BATCH: Final = 20
#: How many tenants' notices one tick delivers.
NOTICE_BATCH: Final = 25
#: How long a client notice that reached nobody is retried, once a tick, before it is
#: recorded as undelivered.
NOTICE_RETRY_WINDOW: Final = timedelta(minutes=30)
#: How far back a new page alarm is still worth a WhatsApp.
PAGE_FRESHNESS: Final = timedelta(hours=1)
#: The scorer opens one platform incident when this many clients' lines break at once.
OUTAGE_TENANTS: Final = 3
#: Or when the voice platform failed this many requests in `OUTAGE_WINDOW_MIN` minutes.
OUTAGE_ENGINE_FAILURES: Final = 2 * SPIKE_THRESHOLD
OUTAGE_WINDOW_MIN: Final = 10
#: A platform that has answered without errors this long is considered back.
QUIET_MINUTES: Final = 15
#: How long a restored line is watched before its incident closes.
PROBATION: Final = timedelta(hours=2)
#: A held line is not given back sooner than this, however clean the checks look.
MIN_HOLD: Final = timedelta(minutes=30)
#: How often an escalated incident is looked at again.
ESCALATED_RECHECK_S: Final = 6 * 60 * 60
#: How long an incident with no calls since its repair waits before closing as quiet.
QUIET_CLOSE: Final = timedelta(hours=2)
#: How often a money incident's evidence is read again: the charge sweep's own cadence.
MONEY_RECHECK_S: Final = 60 * 60

#: The alarm codes the scorer raises itself; their incidents are opened by the scorer
#: with the agent they are about, never from the alarm episode, which names only one.
SELF_OPENED: Final = frozenset({AGENT_HEALTH_DEGRADED, AGENT_LINE_BROKEN, ENGINE_PLATFORM_OUTAGE})


def _now() -> datetime:
    return datetime.now(UTC)


async def _record(**kwargs: Any) -> None:
    async with untenanted_session() as session:
        await ledger.record(session, **kwargs)


# --- the absorbed repair sweeps -------------------------------------------------------


def healer_sweep(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    """Run a repair sweep as its playbook: skipped under a kill switch, ledgered either way.

    `functools.wraps` keeps the arq job name, which is the sweep's own."""
    playbook = PLAYBOOK_BY_JOB[fn.__name__]

    @functools.wraps(fn)
    async def wrapper(ctx: dict[str, Any], *args: Any, **kwargs: Any) -> str:
        if not may_run(playbook.key):
            await _record(
                playbook=playbook.key,
                step="schedule",
                outcome="skipped",
                detail="paused by a kill switch",
            )
            return "skipped:healer_paused"
        try:
            result = await fn(ctx, *args, **kwargs)
        except Exception as exc:
            await _record(
                playbook=playbook.key,
                step="schedule",
                outcome="failed",
                attempt=int(ctx.get("job_try") or 1),
                detail=type(exc).__name__,
            )
            raise
        await _record(
            playbook=playbook.key,
            step="schedule",
            outcome="ok",
            attempt=int(ctx.get("job_try") or 1),
            detail=str(result)[:200],
        )
        return result

    # Read by `tests/healer_registry_test.py`: `functools.wraps` copies it outward through
    # `traced_job`, so the scheduled coroutine itself says which playbook it runs as.
    wrapper.healer_playbook = playbook.key  # type: ignore[attr-defined]
    return wrapper


# --- detection: alarms ------------------------------------------------------------------


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value)) if value else None
    except ValueError:
        return None


async def _open_from_alarms(tally: Counter[str]) -> None:
    codes = sorted(set(PLAYBOOK_BY_TRIGGER) - SELF_OPENED)
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT code, ids, last_seen_at FROM platform_alerts WHERE cleared_at IS NULL "
                    "AND code = ANY(CAST(:codes AS text[]))"
                ),
                {"codes": codes},
            )
        ).all()
        for code, ids, last_seen_at in rows:
            playbook = PLAYBOOK_BY_TRIGGER[str(code)]
            tenant = (
                _uuid((ids or {}).get("tenant_id")) if playbook.blast_radius == "tenant" else None
            )
            key = incidents.dedupe_key(playbook.key, code, tenant)
            if await incidents.resolved_since(session, key, last_seen_at):
                # Closed after the alarm's last occurrence: the episode is still waiting out
                # its quiet hour, and reopening would repeat a repair that already worked.
                tally["already_resolved"] += 1
                continue
            _, opened = await incidents.open_incident(
                session,
                key=key,
                playbook=playbook.key,
                trigger_code=str(code),
                scope="tenant" if tenant else "platform",
                tenant_id=tenant,
            )
            tally["opened"] += int(opened)


# --- detection: real calls -------------------------------------------------------------


async def score_agent_health(ctx: dict[str, Any]) -> str:
    """Score the two most recent closed windows for every client, then judge each agent.

    The previous window is scored again because a call's row can land minutes after it
    ended; the upsert makes the second pass correct the first."""
    now = _now()
    latest = health.window_start(now) - health.WINDOW
    tally: Counter[str] = Counter()
    async with admin_session() as directory:
        tenants = [
            UUID(str(r[0]))
            for r in (
                await directory.execute(
                    text("SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id")
                )
            ).all()
        ]
    broken_tenants: set[UUID] = set()
    for tenant_id in tenants:
        try:
            verdicts = await _score_tenant(tenant_id, latest=latest, now=now, tally=tally)
        except Exception as exc:
            tally["tenant_failed"] += 1
            log.warning(
                "healer_score_failed",
                extra={"tenant_id": str(tenant_id), "reason": type(exc).__name__},
            )
            continue
        for verdict in verdicts:
            if verdict.broken:
                broken_tenants.add(tenant_id)
            await _open_for_verdict(tenant_id, verdict, tally)
    await _detect_outage(broken_tenants, tally)
    return json.dumps(dict(tally), sort_keys=True)


async def _score_tenant(
    tenant_id: UUID, *, latest: datetime, now: datetime, tally: Counter[str]
) -> list[health.Verdict]:
    async with tenant_session(tenant_id) as session:
        agents: set[UUID] = set()
        for start in (latest - health.WINDOW, latest):
            for counts in await health.count_window(session, start=start):
                await health.record_window(session, tenant_id=tenant_id, start=start, counts=counts)
                agents.add(counts.agent_id)
                tally["windows"] += 1
        tally["windows_pruned"] += await health.prune(session)
        tally["proposals_expired"] += await proposals.expire_stale(session)
        return [await health.verdict_for(session, agent_id=a, now=now) for a in sorted(agents)]


async def _open_for_verdict(tenant_id: UUID, verdict: health.Verdict, tally: Counter[str]) -> None:
    if not (verdict.broken or verdict.degraded):
        return
    code = AGENT_LINE_BROKEN if verdict.broken else AGENT_HEALTH_DEGRADED
    playbook = PLAYBOOK_BY_TRIGGER[code]
    async with untenanted_session() as session:
        if await incidents.open_for(session, incidents.dedupe_key("engine_outage", "platform")):
            # The platform incident already holds every line; one agent's incident would
            # only race it.
            return
        incident_id, opened = await incidents.open_incident(
            session,
            key=incidents.dedupe_key(playbook.key, verdict.agent_id),
            playbook=playbook.key,
            trigger_code=code,
            scope="agent",
            tenant_id=tenant_id,
            agent_id=verdict.agent_id,
        )
        if opened and verdict.worst_signal:
            await session.execute(
                text("UPDATE heal_incidents SET last_outcome = :w WHERE id = :id"),
                {"w": f"signal:{verdict.worst_signal}", "id": incident_id},
            )
    if opened:
        tally[f"opened_{playbook.key}"] += 1
        ids = {"tenant_id": str(tenant_id), "agent_id": str(verdict.agent_id)}
        if verdict.broken:
            alert(
                "CORE_LOGIC",
                "agent_line_broken",
                detail="most of this agent's recent real calls failed or ended within ten seconds",
                **ids,
            )
        else:
            alert(
                "CORE_LOGIC",
                "agent_health_degraded",
                detail=(
                    "this agent's call health has been below its own baseline for "
                    f"{health.SUSTAINED_WINDOWS} windows in a row (worst: {verdict.worst_signal})"
                ),
                **ids,
            )


async def _engine_failures(minutes: int) -> int:
    async with untenanted_session() as session:
        value = (
            await session.execute(
                text(
                    "SELECT coalesce(sum(server_errors + unreachable), 0) FROM "
                    "platform_engine_health WHERE engine = :engine AND bucket_start >= "
                    "date_trunc('minute', now()) - make_interval(mins => :minutes)"
                ),
                {"engine": get_settings().engine, "minutes": minutes},
            )
        ).scalar_one()
    return int(value)


async def platform_status() -> PlatformStatus | None:
    """The voice platform's own reading of its health, or None when its adapter publishes
    none. Never raises: the scorer must run whatever the platform's status page does."""
    engine = get_engine()
    if not isinstance(engine, ReportsPlatformStatus):
        return None
    try:
        return await engine.platform_status()
    except Exception as exc:
        log.warning("healer_platform_status_unreadable", extra={"reason": type(exc).__name__})
        return PlatformStatus(reachable=False)


def _status_words(status: PlatformStatus | None) -> str:
    if status is None:
        return "The platform publishes no status reading."
    if not status.reachable:
        return "The platform's own status reading did not answer."
    if status.calls_operational:
        return (
            f"The platform reports itself operational ({status.reported}), so look at our "
            "side first: webhook intake, the API key, our network."
        )
    return f"The platform itself reports a fault ({status.reported})."


async def _detect_outage(broken_tenants: set[UUID], tally: Counter[str]) -> None:
    failures = await _engine_failures(OUTAGE_WINDOW_MIN)
    status = await platform_status()
    platform_says_down = status is not None and status.calls_operational is False
    if status is not None and status.data_operational is False and not platform_says_down:
        alert(
            "CORE_LOGIC",
            "engine_platform_status_degraded",
            detail=(
                f"{_status_words(status)} Calls are reported working; records such as call "
                "results may arrive late. The reconciliation sweeps catch up once it clears."
            ),
            engine=get_settings().engine,
        )
    if (
        len(broken_tenants) < OUTAGE_TENANTS
        and failures < OUTAGE_ENGINE_FAILURES
        and not platform_says_down
    ):
        return
    async with untenanted_session() as session:
        _, opened = await incidents.open_incident(
            session,
            key=incidents.dedupe_key("engine_outage", "platform"),
            playbook="engine_outage",
            trigger_code=ENGINE_PLATFORM_OUTAGE,
            scope="platform",
            component="calls",
            public_title="Calls are not connecting for some customers",
        )
    if opened:
        tally["opened_engine_outage"] += 1
        alert(
            "CORE_LOGIC",
            "engine_platform_outage",
            detail=(
                f"{len(broken_tenants)} client(s) with broken lines and {failures} failed "
                f"voice-platform requests in {OUTAGE_WINDOW_MIN} minutes. "
                f"{_status_words(status)} There is no second platform to move calls to: "
                "every line is being protected and the status page is posted."
            ),
            engine=get_settings().engine,
        )


# --- the per-minute tick ----------------------------------------------------------------


#: Consecutive failed ticks of one step before it alarms. One failed minute is a blip the
#: next tick absorbs; three in a row is a step that is not running.
STEP_FAILURES_BEFORE_ALARM: Final = 3
#: Redis counter of a step's consecutive failures; expires so a count from a long-past
#: run of failures cannot carry into a new one.
_STEP_FAILURES_KEY: Final = "calevate:healer:step-failures:{step}"
_STEP_FAILURES_TTL_S: Final = 3600


async def _count_step_failure(step: str) -> int:
    """This step's consecutive failures, including this one. When Redis cannot count, the
    answer is the threshold: a healer that cannot reach Redis either is not one to trust
    with staying quiet."""
    key = _STEP_FAILURES_KEY.format(step=step)
    try:
        redis = get_redis()
        count = int(await redis.incr(key))
        await redis.expire(key, _STEP_FAILURES_TTL_S)
    except Exception:
        log.warning("healer_step_failure_uncounted", extra={"step": step})
        return STEP_FAILURES_BEFORE_ALARM
    return count


async def _clear_step_failures(step: str) -> None:
    try:
        await get_redis().delete(_STEP_FAILURES_KEY.format(step=step))
    except Exception:
        log.warning("healer_step_failure_unreset", extra={"step": step})


async def run_healer(ctx: dict[str, Any]) -> str:
    tally: Counter[str] = Counter()
    for step in (_open_from_alarms, _advance_due, _page_founder, _deliver_client_notices):
        try:
            await step(tally)
        except Exception as exc:
            tally[f"{step.__name__}_failed"] += 1
            log.warning(
                "healer_step_failed", extra={"step": step.__name__, "reason": type(exc).__name__}
            )
            # The step's exception is swallowed so the other three still run, which also
            # keeps it from arq's terminal alerter: without this a step failing every
            # minute — `_page_founder` included — was a warning line and nothing else.
            if await _count_step_failure(step.__name__) >= STEP_FAILURES_BEFORE_ALARM:
                alert(
                    "CORE_LOGIC",
                    "healer_step_failing",
                    detail=(
                        f"the healer's {step.__name__.lstrip('_')} step has failed "
                        f"{STEP_FAILURES_BEFORE_ALARM} or more ticks in a row "
                        f"({type(exc).__name__})"
                    ),
                    episode=step.__name__.lstrip("_"),
                )
        else:
            await _clear_step_failures(step.__name__)
    return json.dumps(dict(tally), sort_keys=True)


async def _advance_due(tally: Counter[str]) -> None:
    async with untenanted_session() as session:
        due = await incidents.claim_due(session, limit=INCIDENT_BATCH)
    for incident in due:
        playbook = PLAYBOOK_BY_KEY.get(incident.playbook)
        if playbook is None:
            continue
        if playbook.automatic and not may_run(playbook.key):
            await _paused(incident)
            tally["paused"] += 1
            continue
        step = _STEPS.get(playbook.key, _escalate_only)
        try:
            await step(incident)
            tally[f"advanced_{playbook.key}"] += 1
        except Exception as exc:
            tally["step_failed"] += 1
            await _record(
                playbook=playbook.key,
                step="act",
                outcome="failed",
                incident_id=incident.id,
                attempt=incident.attempts,
                tenant_id=incident.tenant_id,
                agent_id=incident.agent_id,
                alarm_code=incident.trigger_code,
                detail=type(exc).__name__,
            )


async def _advance(
    incident: Incident,
    *,
    state: incidents.State,
    next_in_s: int | None,
    outcome: str | None = None,
    attempted: bool = False,
) -> bool:
    async with untenanted_session() as session:
        return await incidents.advance(
            session,
            incident,
            state=state,
            next_in_s=next_in_s,
            outcome=outcome,
            attempted=attempted,
        )


async def _paused(incident: Incident) -> None:
    if incident.last_outcome != "paused":
        await _record(
            playbook=incident.playbook,
            step="act",
            outcome="skipped",
            incident_id=incident.id,
            tenant_id=incident.tenant_id,
            agent_id=incident.agent_id,
            detail="paused by a kill switch",
        )
    await _advance(incident, state=incident.state, next_in_s=300, outcome="paused")  # type: ignore[arg-type]


async def _escalate(incident: Incident, *, why: str, recheck_s: int = ESCALATED_RECHECK_S) -> None:
    alert(
        "WORKER_TERMINAL",
        "healer_needs_person",
        detail=f"playbook={incident.playbook}: {why}",
        incident_id=str(incident.id),
        tenant_id=str(incident.tenant_id) if incident.tenant_id else "",
        agent_id=str(incident.agent_id) if incident.agent_id else "",
    )
    await _record(
        playbook=incident.playbook,
        step="escalate",
        outcome="ok",
        incident_id=incident.id,
        attempt=incident.attempts,
        tenant_id=incident.tenant_id,
        agent_id=incident.agent_id,
        alarm_code=incident.trigger_code,
        detail=why,
    )
    await _advance(incident, state="escalated", next_in_s=recheck_s, outcome="escalated")


async def _escalate_only(incident: Incident) -> None:
    """A playbook the healer must not act on and has no evidence for: page once, wait for a
    person."""
    if incident.state == "open":
        await _escalate(incident, why="the healer does not act on this; a person must")
    else:
        await _advance(incident, state="escalated", next_in_s=ESCALATED_RECHECK_S)


async def _money_review(incident: Incident) -> None:
    """Hand a charge alarm to a person WITH its evidence, then re-read the evidence hourly
    and close the incident once the calls show the problem is over (`MoneyEvidence.
    settled`). Nothing is attested, restated or re-priced here: a rate is the operator's to
    attest (hard rules 7 and 11), which Pip prepares for them to confirm."""
    try:
        evidence = await money.gather(since=incident.opened_at - money.LOOKBACK)
    except Exception as exc:
        log.warning(
            "healer_money_evidence_failed",
            extra={"incident_id": str(incident.id), "reason": type(exc).__name__},
        )
        if incident.state == "open":
            await _escalate(
                incident,
                why="the healer does not act on money, and its evidence could not be read",
                recheck_s=MONEY_RECHECK_S,
            )
        else:
            await _advance(incident, state="escalated", next_in_s=MONEY_RECHECK_S)
        return
    finding = evidence.summary()
    if incident.state == "open":
        await _escalate(incident, why=finding, recheck_s=MONEY_RECHECK_S)
        return
    settled = evidence.settled(incident.trigger_code, after=incident.opened_at)
    async with untenanted_session() as session:
        last = (await ledger.latest_findings(session, [incident.id])).get(incident.id)
    if settled or last != finding:
        await _record(
            playbook=incident.playbook,
            step="verify",
            outcome="ok" if settled else "failed",
            incident_id=incident.id,
            alarm_code=incident.trigger_code,
            detail=finding,
        )
    if settled:
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
    else:
        await _advance(incident, state="escalated", next_in_s=MONEY_RECHECK_S)


async def _wait_for_person(incident: Incident) -> None:
    """A status post an operator wrote: nothing to do and nobody to page."""
    await _advance(incident, state=incident.state, next_in_s=ESCALATED_RECHECK_S)  # type: ignore[arg-type]


# --- generic act / verify playbooks ---------------------------------------------------------

Act = Callable[[Incident], Awaitable[str]]
Verify = Callable[[Incident], Awaitable[bool]]


def _generic(act: Act, verify: Verify) -> Callable[[Incident], Awaitable[None]]:
    async def step(incident: Incident) -> None:
        playbook = PLAYBOOK_BY_KEY[incident.playbook]
        if incident.state == "open":
            await _act(incident, act)
            return
        ok = await verify(incident)
        if ok or incident.state != "escalated":
            # An escalated incident is re-checked every cooldown; only the check that
            # clears it is worth a ledger row.
            await _record(
                playbook=playbook.key,
                step="verify",
                outcome="ok" if ok else "failed",
                incident_id=incident.id,
                attempt=incident.attempts,
                tenant_id=incident.tenant_id,
                alarm_code=incident.trigger_code,
            )
        if ok:
            await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        elif incident.state == "mitigated" and incident.attempts < playbook.max_attempts:
            await _act(incident, act)
        elif incident.state == "mitigated":
            await _escalate(
                incident,
                why=f"{incident.attempts} repair(s) did not clear it",
                recheck_s=playbook.cooldown_s,
            )
        else:
            await _advance(incident, state="escalated", next_in_s=playbook.cooldown_s)

    return step


async def _act(incident: Incident, act: Act) -> None:
    playbook = PLAYBOOK_BY_KEY[incident.playbook]
    try:
        detail = await act(incident)
        outcome = "ok"
    except Exception as exc:
        detail, outcome = type(exc).__name__, "failed"
    await _record(
        playbook=playbook.key,
        step="act",
        outcome=outcome,
        incident_id=incident.id,
        attempt=incident.attempts + 1,
        tenant_id=incident.tenant_id,
        alarm_code=incident.trigger_code,
        detail=detail,
    )
    await _advance(
        incident,
        state="mitigated",
        next_in_s=playbook.cooldown_s,
        outcome="acted" if outcome == "ok" else "act_failed",
        attempted=True,
    )


async def _act_webhooks(incident: Incident) -> str:
    from apps.workers.engine_webhooks import reconcile_engine_webhooks

    return await reconcile_engine_webhooks({"job_try": 1})


async def _verify_alarm_quiet(incident: Incident) -> bool:
    """The alarm that woke the playbook has not recurred within its cooldown."""
    playbook = PLAYBOOK_BY_KEY[incident.playbook]
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT 1 FROM platform_alerts WHERE code = :code AND cleared_at IS NULL "
                    "AND last_seen_at > now() - make_interval(secs => :s) LIMIT 1"
                ),
                {"code": incident.trigger_code, "s": playbook.cooldown_s},
            )
        ).first()
    return row is None


async def _act_workspace(incident: Incident) -> str:
    if incident.tenant_id is None:
        return "no_tenant"
    async with tenant_session(incident.tenant_id) as session:
        queued = await queue_workspace_provisioning(
            session, tenant_id=incident.tenant_id, reopen=True
        )
    return "queued" if queued else "not_owed"


async def _verify_workspace(incident: Incident) -> bool:
    if incident.tenant_id is None:
        return await _verify_alarm_quiet(incident)
    async with tenant_session(incident.tenant_id) as session:
        state = await read_workspace_state(session, incident.tenant_id)
    return bool(state.active)


async def _act_replay(incident: Incident) -> str:
    replayed = 0
    async with untenanted_session() as session:
        queue = await read_dead_letter_queue(session)
        for job in queue.by_job:
            replayed += await replay_dead_letters(session, job=job.job)
    return f"replayed={replayed}"


async def _verify_dlq_empty(incident: Incident) -> bool:
    async with untenanted_session() as session:
        return (await read_dead_letter_queue(session)).depth == 0


# --- agent playbooks ------------------------------------------------------------------------


async def _agent_ref(tenant_id: UUID, agent_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :aid AND deleted_at IS NULL"),
                {"aid": agent_id},
            )
        ).first()
    return str(row[0]) if row and row[0] else None


async def repair_agent_plumbing(tenant_id: UUID, agent_id: UUID) -> str:
    """Re-check and repair the parts of one agent that our own records decide: its call
    settings, its call-event endpoint and its in-call actions. Never its script."""
    ref = await _agent_ref(tenant_id, agent_id)
    if ref is None:
        return "not_published"
    engine = get_settings().engine
    checked = await check_agent_settings(
        tenant_id=tenant_id, agent_id=agent_id, engine_agent_ref=ref
    )
    async with tenant_session(tenant_id) as session:
        webhook = await ensure_agent_webhook(session, engine=engine, engine_agent_ref=ref)
    actions = await check_agent_actions(tenant_id=tenant_id, engine=engine, engine_agent_ref=ref)
    settings_outcome = (
        "unchecked" if checked is None else ("repaired" if checked.repaired else "clean")
    )
    return f"settings={settings_outcome} webhook={webhook.outcome} actions={actions}"


async def _agent_reads_back(tenant_id: UUID, agent_id: UUID) -> bool:
    try:
        drift = await engine_drift_for(tenant_id=tenant_id, agent_id=agent_id)
    except Exception as exc:
        # Unreadable counts as "not verified", which keeps the line held; the operator
        # still learns why the verify step could not run.
        log.warning(
            "healer_verify_read_failed",
            extra={"agent_id": str(agent_id), "error": type(exc).__name__},
        )
        return False
    return drift.state not in ("unreachable", "unreadable") and (
        drift.truthful_answer_applied is not False
    )


async def _agent_repair(incident: Incident) -> None:
    assert incident.tenant_id is not None and incident.agent_id is not None
    tenant_id, agent_id = incident.tenant_id, incident.agent_id
    playbook = PLAYBOOK_BY_KEY[incident.playbook]
    if incident.state == "open":
        detail = await repair_agent_plumbing(tenant_id, agent_id)
        signal = (incident.last_outcome or "").removeprefix("signal:") or None
        async with tenant_session(tenant_id) as session:
            await protection.client_incident(
                session,
                tenant_id=tenant_id,
                incident_id=incident.id,
                agent_id=agent_id,
                kind="agent_unwell",
            )
            made = await proposals.propose_for(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                incident_id=incident.id,
                worst_signal=signal,
                since=incident.opened_at,
            )
            if made:
                await session.execute(
                    text(
                        "UPDATE heal_client_incidents SET must_act = true, updated_at = now() "
                        "WHERE incident_id = :iid AND agent_id = :aid"
                    ),
                    {"iid": incident.id, "aid": agent_id},
                )
                await ledger.record(
                    session,
                    playbook=playbook.key,
                    step="propose",
                    outcome="ok",
                    incident_id=incident.id,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    detail=",".join(made),
                )
            await ledger.record(
                session,
                playbook=playbook.key,
                step="act",
                outcome="ok",
                incident_id=incident.id,
                attempt=1,
                tenant_id=tenant_id,
                agent_id=agent_id,
                alarm_code=incident.trigger_code,
                detail=detail,
            )
        await _advance(
            incident,
            state="mitigated",
            next_in_s=playbook.cooldown_s,
            outcome="repaired",
            attempted=True,
        )
        return
    async with tenant_session(tenant_id) as session:
        verdict = await health.verdict_for(session, agent_id=agent_id, now=_now())
    if not verdict.degraded:
        async with tenant_session(tenant_id) as session:
            await protection.resolve_client_rows(session, incident_id=incident.id)
        await _record(
            playbook=playbook.key,
            step="verify",
            outcome="ok",
            incident_id=incident.id,
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    if incident.state == "mitigated" and incident.attempts < playbook.max_attempts:
        detail = await repair_agent_plumbing(tenant_id, agent_id)
        await _record(
            playbook=playbook.key,
            step="act",
            outcome="ok",
            incident_id=incident.id,
            attempt=incident.attempts + 1,
            tenant_id=tenant_id,
            agent_id=agent_id,
            detail=detail,
        )
        await _advance(incident, state="mitigated", next_in_s=playbook.cooldown_s, attempted=True)
    elif incident.state == "mitigated":
        await _escalate(
            incident,
            why="the agent is still below its baseline after repairs",
            recheck_s=playbook.cooldown_s,
        )
    else:
        await _advance(incident, state="escalated", next_in_s=playbook.cooldown_s)


async def _last_step_at(incident_id: UUID, step: str) -> datetime | None:
    async with untenanted_session() as session:
        value = (
            await session.execute(
                text(
                    "SELECT max(at) FROM heal_actions WHERE incident_id = :iid AND step = :step "
                    "AND outcome = 'ok'"
                ),
                {"iid": incident_id, "step": step},
            )
        ).scalar_one()
    return value if isinstance(value, datetime) else None


async def _hold(incident: Incident, *, forward: bool = True) -> str:
    assert incident.tenant_id is not None and incident.agent_id is not None
    async with tenant_session(incident.tenant_id) as session:
        held = await protection.protect_agent(
            session,
            tenant_id=incident.tenant_id,
            incident_id=incident.id,
            agent_id=incident.agent_id,
            forward=forward,
        )
        await ledger.record(
            session,
            playbook=incident.playbook,
            step="protect",
            outcome="ok" if held.hold in ("paused", "forwarded", "held") else "refused",
            incident_id=incident.id,
            tenant_id=incident.tenant_id,
            agent_id=incident.agent_id,
            detail=f"line={held.hold} campaigns_paused={held.campaigns_paused}",
        )
    return held.hold


async def _restore(
    incident: Incident, *, actor_type: str = "healer", actor_id: UUID | None = None
) -> None:
    assert incident.tenant_id is not None and incident.agent_id is not None
    async with tenant_session(incident.tenant_id) as session:
        restored = await protection.restore_agent(
            session,
            tenant_id=incident.tenant_id,
            incident_id=incident.id,
            agent_id=incident.agent_id,
        )
        await ledger.record(
            session,
            playbook=incident.playbook,
            step="restore",
            outcome="ok",
            incident_id=incident.id,
            tenant_id=incident.tenant_id,
            agent_id=incident.agent_id,
            detail=(
                f"lifted={restored.lifted} resumed={restored.campaigns_resumed} "
                f"requeued={restored.requeued} missed={restored.missed_calls}"
            ),
            actor_type=actor_type,  # type: ignore[arg-type]
            actor_id=actor_id,
        )


async def _line_protection(incident: Incident) -> None:
    assert incident.tenant_id is not None and incident.agent_id is not None
    tenant_id, agent_id = incident.tenant_id, incident.agent_id
    now = _now()
    outcome = incident.last_outcome or ""
    if incident.state == "open":
        detail = await repair_agent_plumbing(tenant_id, agent_id)
        await _record(
            playbook=incident.playbook,
            step="act",
            outcome="ok",
            incident_id=incident.id,
            attempt=1,
            tenant_id=tenant_id,
            agent_id=agent_id,
            alarm_code=incident.trigger_code,
            detail=detail,
        )
        await _advance(
            incident, state="mitigated", next_in_s=15 * 60, outcome="repaired", attempted=True
        )
        return
    if outcome == "repaired":
        since = incident.mitigated_at or incident.opened_at
        async with tenant_session(tenant_id) as session:
            calls, broken = await health.calls_since(session, agent_id=agent_id, since=since)
        if health.looks_broken(calls, broken):
            hold = await _hold(incident)
            await _advance(incident, state="mitigated", next_in_s=15 * 60, outcome=f"held:{hold}")
        elif calls >= health.MIN_WINDOW_CALLS or now - since > QUIET_CLOSE:
            await _close_quietly(incident)
        else:
            await _advance(incident, state="mitigated", next_in_s=15 * 60)
        return
    if outcome.startswith("held:"):
        await _held_step(incident, now=now)
        return
    if outcome == "probation":
        await _probation_step(incident, now=now)
        return
    # `held_for_person` and anything unexpected: a person restores it from the console.
    await _advance(incident, state=incident.state, next_in_s=ESCALATED_RECHECK_S)  # type: ignore[arg-type]


async def _close_quietly(incident: Incident) -> None:
    assert incident.tenant_id is not None
    async with tenant_session(incident.tenant_id) as session:
        await protection.resolve_client_rows(session, incident_id=incident.id)
    await _advance(incident, state="resolved", next_in_s=None, outcome="verified")


async def _held_step(incident: Incident, *, now: datetime) -> None:
    assert incident.tenant_id is not None and incident.agent_id is not None
    held_at = await _last_step_at(incident.id, "protect") or now
    if incident.last_outcome == "held:forwarded":
        # The hand-over relies on the agent itself (gate T-26); if callers still drop,
        # fall back to the plain unavailable message.
        async with tenant_session(incident.tenant_id) as session:
            calls, broken = await health.calls_since(
                session, agent_id=incident.agent_id, since=held_at
            )
        if health.looks_broken(calls, broken):
            hold = await _hold(incident, forward=False)
            await _advance(incident, state="mitigated", next_in_s=15 * 60, outcome=f"held:{hold}")
            return
    if now - held_at < MIN_HOLD:
        await _advance(incident, state="mitigated", next_in_s=15 * 60)
        return
    reads_back = await _agent_reads_back(incident.tenant_id, incident.agent_id)
    quiet = await _engine_failures(QUIET_MINUTES) == 0
    await _record(
        playbook=incident.playbook,
        step="verify",
        outcome="ok" if reads_back and quiet else "failed",
        incident_id=incident.id,
        tenant_id=incident.tenant_id,
        agent_id=incident.agent_id,
        detail=f"reads_back={reads_back} platform_quiet={quiet}",
    )
    if not (reads_back and quiet):
        await _advance(incident, state="mitigated", next_in_s=15 * 60)
        return
    await _restore(incident)
    await _advance(
        incident, state="mitigated", next_in_s=int(PROBATION.total_seconds()), outcome="probation"
    )


async def _probation_step(incident: Incident, *, now: datetime) -> None:
    assert incident.tenant_id is not None and incident.agent_id is not None
    restored_at = await _last_step_at(incident.id, "restore") or now
    async with tenant_session(incident.tenant_id) as session:
        calls, broken = await health.calls_since(
            session, agent_id=incident.agent_id, since=restored_at
        )
    if health.looks_broken(calls, broken):
        await _hold(incident, forward=True)
        alert(
            "CORE_LOGIC",
            "healer_line_relapsed",
            detail="a line the healer gave back broke again within its watch; it is held "
            "until a person restores it",
            tenant_id=str(incident.tenant_id),
            agent_id=str(incident.agent_id),
        )
        async with tenant_session(incident.tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE heal_client_incidents SET must_act = true, updated_at = now() "
                    "WHERE incident_id = :iid AND agent_id = :aid"
                ),
                {"iid": incident.id, "aid": incident.agent_id},
            )
        await _advance(
            incident, state="escalated", next_in_s=ESCALATED_RECHECK_S, outcome="held_for_person"
        )
        return
    if now - restored_at >= PROBATION:
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
    else:
        await _advance(incident, state="mitigated", next_in_s=15 * 60)


async def restore_by_person(incident: Incident, *, actor_type: str, actor_id: UUID | None) -> None:
    """A person gave the line back (console or the client's own button)."""
    if incident.scope == "platform":
        await _restore_platform(incident, actor_type=actor_type, actor_id=actor_id)
    elif incident.agent_id is not None and incident.tenant_id is not None:
        await _restore(incident, actor_type=actor_type, actor_id=actor_id)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE heal_incidents SET state = 'resolved', resolved_at = now(), "
                "last_outcome = 'restored_by_person', updated_at = now() WHERE id = :id "
                "AND resolved_at IS NULL"
            ),
            {"id": incident.id},
        )


# --- the platform outage ----------------------------------------------------------------------


async def _platform_tenants() -> list[UUID]:
    async with admin_session() as directory:
        rows = (
            await directory.execute(
                text("SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id")
            )
        ).all()
    return [UUID(str(r[0])) for r in rows]


async def _engine_outage(incident: Incident) -> None:
    if incident.state in ("open", "mitigated") and incident.last_outcome != "restoring":
        held = failed = 0
        for tenant_id in await _platform_tenants():
            async with tenant_session(tenant_id) as session:
                agents = await protection.live_answering_agents(session)
            for agent_id in agents:
                try:
                    async with tenant_session(tenant_id) as session:
                        if await protection.healer_holds_line(session, agent_id=agent_id):
                            continue
                        await protection.protect_agent(
                            session,
                            tenant_id=tenant_id,
                            incident_id=incident.id,
                            agent_id=agent_id,
                            kind="platform_outage",
                        )
                    held += 1
                except Exception as exc:
                    failed += 1
                    log.warning(
                        "healer_outage_hold_failed",
                        extra={"agent_id": str(agent_id), "reason": type(exc).__name__},
                    )
        if held or failed:
            await _record(
                playbook=incident.playbook,
                step="protect",
                outcome="ok" if not failed else "failed",
                incident_id=incident.id,
                detail=f"held={held} failed={failed}",
            )
    if incident.state == "open":
        await _advance(
            incident, state="mitigated", next_in_s=5 * 60, outcome="held", attempted=True
        )
        return
    quiet = await _engine_failures(QUIET_MINUTES) == 0
    await _record(
        playbook=incident.playbook,
        step="verify",
        outcome="ok" if quiet else "failed",
        incident_id=incident.id,
        detail=f"platform_quiet={quiet}",
    )
    if not quiet:
        await _advance(incident, state="mitigated", next_in_s=5 * 60)
        return
    await _restore_platform(incident, actor_type="healer", actor_id=None)
    await _advance(incident, state="resolved", next_in_s=None, outcome="verified")


async def _restore_platform(incident: Incident, *, actor_type: str, actor_id: UUID | None) -> None:
    restored = 0
    for tenant_id in await _platform_tenants():
        async with tenant_session(tenant_id) as session:
            agents = [
                UUID(str(r[0]))
                for r in (
                    await session.execute(
                        text(
                            "SELECT agent_id FROM heal_client_incidents WHERE incident_id = :iid "
                            "AND state = 'open' AND agent_id IS NOT NULL"
                        ),
                        {"iid": incident.id},
                    )
                ).all()
            ]
            for agent_id in agents:
                await protection.restore_agent(
                    session, tenant_id=tenant_id, incident_id=incident.id, agent_id=agent_id
                )
                restored += 1
    await _record(
        playbook=incident.playbook,
        step="restore",
        outcome="ok",
        incident_id=incident.id,
        detail=f"restored={restored}",
        actor_type=actor_type,
        actor_id=actor_id,
    )


_STEPS: Final[dict[str, Callable[[Incident], Awaitable[None]]]] = {
    "engine_webhooks": _generic(_act_webhooks, _verify_alarm_quiet),
    "workspace_retry": _generic(_act_workspace, _verify_workspace),
    "outbox_replay": _generic(_act_replay, _verify_dlq_empty),
    "agent_repair": _agent_repair,
    "line_protection": _line_protection,
    "engine_outage": _engine_outage,
    MONEY_REVIEW: _money_review,
    "status_post": _wait_for_person,
}


# --- telling people ---------------------------------------------------------------------------


async def _founder_destination() -> Any:
    """The founder's WhatsApp, with the console write that set it as the opt-in evidence.

    A number that came from the environment rather than the console has no such record,
    so it is not messaged; the healer page says to set it in the console."""
    from apps.workers.whatsapp import Destination

    number = (get_settings().healer_founder_whatsapp or "").strip()
    if not number:
        return None
    async with untenanted_session() as session:
        set_at = (
            await session.execute(
                text("SELECT updated_at FROM platform_settings WHERE key = :k"),
                {"k": "healer_founder_whatsapp"},
            )
        ).scalar_one_or_none()
    return Destination(to_e164=number, opt_in_at=set_at)


async def _page_founder(tally: Counter[str]) -> None:
    """One WhatsApp per new `page` episode, beside the email `core/alerting` already sent."""
    from apps.workers.whatsapp import WhatsAppMessage, get_whatsapp_transport

    settings = get_settings()
    if not settings.whatsapp_enabled:
        return
    destination = await _founder_destination()
    if destination is None or destination.opt_in_at is None:
        return
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT a.id, a.code FROM platform_alerts a WHERE a.cleared_at IS NULL "
                    "AND a.severity = 'page' AND a.first_seen_at > now() - make_interval(secs "
                    "=> :fresh) AND NOT EXISTS (SELECT 1 FROM heal_actions h WHERE h.alert_id = "
                    "a.id AND h.step = 'notify') ORDER BY a.first_seen_at LIMIT 10"
                ),
                {"fresh": int(PAGE_FRESHNESS.total_seconds())},
            )
        ).all()
    if not rows:
        return
    transport = get_whatsapp_transport()
    for alert_id, code in rows:
        result = await transport.send(
            WhatsAppMessage(
                to_e164=destination.to_e164,
                template=settings.whatsapp_template_healer_page,
                locale=settings.whatsapp_template_locale,
                variables=(str(code), settings.app_env),
            )
        )
        async with untenanted_session() as session:
            await ledger.record(
                session,
                playbook="founder_page",
                step="notify",
                outcome="ok" if result.delivered else "failed",
                alarm_code=str(code),
                alert_id=alert_id,
                detail=result.reason or "whatsapp",
            )
        tally["founder_paged"] += int(result.delivered)


async def _deliver_client_notices(tally: Counter[str]) -> None:
    async with untenanted_session() as session:
        tenants = [
            UUID(str(r[0]))
            for r in (
                await session.execute(
                    text(
                        "SELECT DISTINCT tenant_id FROM heal_client_incidents WHERE "
                        "notified_at IS NULL OR (state = 'resolved' AND restored_notified_at "
                        "IS NULL AND notified_by IS DISTINCT FROM 'dashboard') LIMIT :n"
                    ),
                    {"n": NOTICE_BATCH},
                )
            ).all()
        ]
    for tenant_id in tenants:
        try:
            tally["notices"] += await _notify_tenant(tenant_id)
        except Exception as exc:
            tally["notice_failed"] += 1
            log.warning(
                "healer_notice_failed",
                extra={"tenant_id": str(tenant_id), "reason": type(exc).__name__},
            )


async def _owner_emails(session: Any, tenant_id: UUID) -> list[str]:
    rows = (
        await session.execute(
            text(
                "SELECT o.billing_email FROM organizations o WHERE o.id = :tid UNION "
                "SELECT u.email FROM memberships m JOIN users u ON u.id = m.user_id "
                "WHERE m.tenant_id = :tid AND m.role = 'owner' AND u.deactivated_at IS NULL"
            ),
            {"tid": tenant_id},
        )
    ).all()
    seen: dict[str, str] = {}
    for row in rows:
        address = str(row[0] or "").strip()
        if address:
            seen.setdefault(address.lower(), address)
    return [seen[key] for key in sorted(seen)]


async def _notify_tenant(tenant_id: UUID) -> int:
    from apps.api.core.transport import EmailPurpose, get_transport
    from apps.workers.email_render import from_text
    from apps.workers.whatsapp import WhatsAppMessage, get_whatsapp_transport, resolve_destination

    sent = 0
    settings = get_settings()
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT ci.id, ci.kind, ci.protection, ci.state, ci.campaigns_paused, "
                    "ci.missed_calls, ci.requeued, ci.must_act, ci.notified_at, ci.notified_by, "
                    "a.name, o.slug, i.last_outcome, ci.opened_at, ci.resolved_at "
                    "FROM heal_client_incidents ci "
                    "JOIN organizations o ON o.id = ci.tenant_id "
                    "JOIN heal_incidents i ON i.id = ci.incident_id "
                    "LEFT JOIN agents a ON a.id = ci.agent_id WHERE ci.notified_at IS NULL "
                    "OR (ci.state = 'resolved' AND ci.restored_notified_at IS NULL "
                    "AND ci.notified_by IS DISTINCT FROM 'dashboard') ORDER BY ci.opened_at"
                )
            )
        ).all()
        if not rows:
            return 0
        fallback = await protection.fallback_phone(session)
        recipients = await _owner_emails(session, tenant_id)
        destination = await resolve_destination(session, tenant_id)
        has_proposal = bool(await proposals.pending_for_tenant(session, limit=1))
        transport = get_transport(EmailPurpose.NOTIFICATIONS)
        outage_told: set[str] = set()
        for row in rows:
            (
                row_id,
                kind,
                prot,
                state,
                paused,
                missed,
                requeued,
                must_act,
                notified_at,
                _notified_by,
                agent_name,
                slug,
                last_outcome,
                opened_at,
                resolved_at,
            ) = row
            restored = notified_at is not None
            line_changed = prot != "none" or kind == "platform_outage"
            # One message per platform outage, not one per agent of the same client.
            repeat = kind == "platform_outage" and f"{kind}:{restored}" in outage_told
            loud = not repeat and (line_changed if restored else (must_act or line_changed))
            if not loud:
                # Nothing was taken off the line, nothing is asked of them, or they were
                # just told: the dashboard notice is enough.
                await session.execute(
                    text(
                        "UPDATE heal_client_incidents SET notified_at = COALESCE(notified_at, "
                        "now()), notified_by = COALESCE(notified_by, 'dashboard'), "
                        "restored_notified_at = CASE WHEN state = 'resolved' THEN now() "
                        "ELSE restored_notified_at END WHERE id = :id"
                    ),
                    {"id": row_id},
                )
                continue
            notice = notices.line_notice(
                kind=str(kind),
                protection=str(prot),
                agent_name=agent_name,
                campaigns_paused=int(paused),
                fallback_phone=fallback,
                state=str(state),
                missed_calls=int(missed),
                requeued=int(requeued),
                worst_signal=(last_outcome or "").removeprefix("signal:") or None,
                has_proposal=has_proposal,
            )
            email = from_text(
                subject=notice.headline,
                preheader=notice.what_we_did,
                heading=notice.headline,
                text=notice.as_text(link=notices.incident_link(str(slug))),
            )
            delivered = [
                address
                for address in recipients
                if await asyncio.to_thread(
                    transport.send,
                    to=address,
                    subject=email.subject,
                    body=email.text,
                    html=email.html,
                )
            ]
            channels = ["dashboard"] + (["email"] if delivered else [])
            whatsapp_ok = settings.whatsapp_enabled and destination is not None and line_changed
            if destination is None or destination.opt_in_at is None:
                # An opt-in we cannot evidence is not an opt-in (SEC-COMP §4).
                whatsapp_ok = False
            if whatsapp_ok and destination is not None:
                template = (
                    settings.whatsapp_template_line_restored
                    if restored
                    else settings.whatsapp_template_line_notice
                )
                result = await get_whatsapp_transport().send(
                    WhatsAppMessage(
                        to_e164=destination.to_e164,
                        template=template,
                        locale=settings.whatsapp_template_locale,
                        variables=(str(agent_name or "your agent"),),
                    )
                )
                if result.delivered:
                    channels.append("whatsapp")
            if len(channels) == 1:
                # Nothing reached them. Left unstamped, the next tick (every minute) sends it
                # again, inside `NOTICE_RETRY_WINDOW`. Past it the row is stamped with
                # `undelivered` rather than plain `dashboard`, which is the quiet-row marker
                # and would make the selection above skip this incident's restored notice.
                since = resolved_at if restored else opened_at
                if since is not None and _now() - since < NOTICE_RETRY_WINDOW:
                    log.warning(
                        "healer_notice_retrying",
                        extra={"tenant_id": str(tenant_id), "incident_id": str(row_id)},
                    )
                    continue
                channels.append("undelivered")
            if kind == "platform_outage":
                outage_told.add(f"{kind}:{restored}")
            column = "restored_notified_at" if restored else "notified_at"
            await session.execute(
                text(
                    f"UPDATE heal_client_incidents SET {column} = now(), notified_by = :by, "
                    "updated_at = now() WHERE id = :id"
                ),
                {"id": row_id, "by": ",".join(channels)},
            )
            await ledger.record(
                session,
                playbook="client_notice",
                step="notify",
                outcome="ok" if delivered else "failed",
                tenant_id=tenant_id,
                detail=f"{'restored' if restored else 'opened'} via {','.join(channels)} "
                f"to {len(delivered)} address(es)",
            )
            sent += 1
    return sent


__all__ = [
    "INCIDENT_BATCH",
    "SCORE_MINUTES",
    "healer_sweep",
    "repair_agent_plumbing",
    "restore_by_person",
    "run_healer",
    "score_agent_health",
]
