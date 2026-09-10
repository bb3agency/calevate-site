"""The maintenance window's actuator: one tick, every edge, nothing else moves it.

D-544. `apps/api/ops/maintenance.py` holds the state machine and argues the design; this
holds the WORK each transition owes and the probe that decides whether the middle one may
happen at all.

═══ WHY EVERYTHING IS IN THE TICK, INCLUDING WHAT AN OPERATOR PRESSES ═══

Entering a window pauses every running campaign in the fleet and rewrites what every live
inbound agent says, one vendor round trip at a time; leaving it republishes them all. That
is a fleet-wide walk with third-party I/O in it, which BACKEND-PATTERNS puts in a worker
and nowhere else — a request handler that did it would hold a connection for the length of
the client list and time out on the deployment where it matters most.

So the ops routes never actuate. They move the ROW — schedule, amend, cancel, or set
`ends_at = now()` for "end it now" — and then NUDGE this job. One actuator, so there is no
second implementation of "what entering a window means" to drift from this one, and an
operator still gets their action inside a second rather than at the next cron beat.

═══ THE ORDER OF OPERATIONS AT EACH EDGE, WHICH IS NOT ARBITRARY ═══

Entering `draining`:

  1. transition the row (CAS — the loser of a race between two workers does nothing);
  2. pause running campaigns and audit each one;
  3. tell the engine what inbound agents should now say.

The transition is FIRST because it is what makes `PlatformStatus.accepting_new_work` false
everywhere — the dial gate, the campaign tick, the callback dialler. Pausing campaigns
before that would leave a gap in which the tick re-reads a campaign it just paused; doing
it after is idempotent (a paused campaign is not `running`, so the set-based CAS finds
nothing to do on a second pass).

The engine work is LAST because it is the only step that can fail per-item at a third
party, and none of the first two should wait behind it. A window whose caller message did
not reach every agent is still a window; an alert says how many, and `sweep_engine_drift`
finds the rest.

Leaving is the same list in reverse, with one asymmetry that is deliberate:
`agents.service.publish_agent` is the restore, not `override_call_script`. The override is
a temporary partial write we deliberately do not read back; the restore comes from OUR row
through the verified path, so what an agent ends the window saying is what our record says
it says, proved rather than assumed (`VoiceEngine.override_call_script` argues it).

═══ WHAT THIS JOB WILL NOT DO ═══

It will not hang up a live call, and it will not kill a wedged job. `ops/maintenance.py`
carries the full argument; the short form is that the drain deadline bounds how long the
PLATFORM waits, not how long other people's work is allowed to take. A caller mid-sentence
is a person, and the post-call pipeline behind them runs through the window untouched
because `/hooks` is never shed and voice-runtime mounts no shed middleware at all.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from arq import Retry
from calevate_shared.calling_window import IST
from calevate_shared.engine import (
    TRUTHFUL_ANSWER_DIRECTIVE,
    DisclosurePosture,
    compose_opening_line,
)
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.campaigns.service import (
    pause_campaigns_for_maintenance,
    resume_campaigns_after_maintenance,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.alerting import alert
from apps.api.core.loadshed import LoadShedMode, get_platform_status, set_platform_status
from apps.api.core.logging import get_logger
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.transport import get_transport
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.ops.maintenance import (
    InFlight,
    MaintenanceWindow,
    NoticeKind,
    activate,
    advance_notice_lead,
    begin_drain,
    claim_notice,
    complete_window,
    read_open_window,
    record_probe,
)
from apps.api.reliability.service import enqueue_outbox
from apps.workers.email_render import from_text
from apps.workers.fleet_walk import WalkBudget

log = get_logger(__name__)

#: Every fifteen seconds. The cadence IS the resolution of three promises — how soon after
#: `starts_at` the platform stops accepting work, how soon after the last call ends the
#: window activates, and how soon after `ends_at` the clients get their portal back — so it
#: is short. It costs one indexed read of a one-row table on the ticks where no window is
#: open, which is every tick on almost every day; the probe only runs while draining.
TICK_SECONDS = frozenset({0, 15, 30, 45})

#: The outbox job that mails one client. Named here because the enqueue and the
#: registration in `settings.FUNCTIONS` must be the same string — `check_job_wiring`
#: derives that agreement rather than trusting it (D-199).
NOTIFY_JOB = "notify_maintenance"

#: The three notices a client gets, plus the amendment. `advance` goes out
#: `ADVANCE_NOTICE` before the window; `active` when the portal actually closes; `ended`
#: when it opens again; `amended` whenever an announced window's client-visible facts move.
NOTICE_SUBJECTS: dict[str, str] = {
    "advance": "Planned Calevate maintenance",
    "amended": "Change to the planned Calevate maintenance",
    "active": "Calevate is in maintenance now",
    "ended": "Calevate maintenance is finished",
}

#: Non-terminal call statuses — the complement of `calevate_shared.events.
#: TERMINAL_STATUSES`, spelled as SQL. Not derived from that frozenset at runtime because
#: `check_raw_sql` requires every character of an interpolated fragment to be our own
#: literal text, and a set rendered from a Python value is not.
#: `tests/maintenance_drain_test.py` asserts the two agree, which is the property that
#: matters — a sixth terminal status added there and forgotten here would make the drain
#: wait for calls that are over.
_ACTIVE_CALL_SQL = text(
    "SELECT count(*) FROM calls WHERE status IN ('queued', 'ringing', 'in_progress')"
)

#: Queued work that has been ACCEPTED and not yet finished, in one query over two
#: platform-scoped tables. See `InFlight` for why this and not arq's own key space.
_QUEUED_WORK_SQL = text(
    "SELECT (SELECT count(*) FROM outbox_messages WHERE status = 'pending') "
    "+ (SELECT count(*) FROM webhook_inbox_events "
    "   WHERE status IN ('processing', 'enqueued'))"
)

#: Every tenant that can hold a call. `engine_agent_routes` is the non-tenant-scoped
#: bridge (`db/registry.RLS_EXEMPT_TENANT_COLUMNS` records the read exemption), and it is
#: the SAME source `pipeline.callable_tenants` uses for the same reason — a call row only
#: ever exists for an agent the engine knows. ORDER BY so a truncated walk starves a
#: STABLE tail rather than a different random slice each tick.
_CALLABLE_TENANTS_SQL = text(
    "SELECT DISTINCT tenant_id FROM engine_agent_routes ORDER BY tenant_id"
)

#: Live agents that can ANSWER a call, with the handle the engine knows them by and the
#: four columns `compose_opening_line` needs. Outbound-only agents are excluded: they never
#: receive a call, so overriding their script would change nothing a caller can hear and
#: would spend a vendor round trip saying so.
_ANSWERING_AGENTS_SQL = text(
    "SELECT id, engine_agent_ref, ai_disclosure_line, ai_disclosure_enabled, "
    "recording_notice_line, recording_notice_enabled, caller_memory_notice_line, "
    "caller_memory_enabled FROM agents "
    "WHERE status = 'live' AND engine_agent_ref IS NOT NULL "
    "AND direction IN ('inbound', 'both') AND deleted_at IS NULL AND archived_at IS NULL "
    "ORDER BY id"
)

#: Who gets a client notice: every client who still has a portal to lose.
#:
#: ⚠ **READ UNDER `admin_session`, NEVER `untenanted_session`.** `organizations` carries the
#: FORCEd tenant policy matched on `id`, so an untenanted read of it returns ZERO ROWS —
#: not an error, not a subset: nothing. This query is what decides who is told about an
#: outage, so on the wrong session the whole notice apparatus runs, claims its stamps,
#: reports success and mails nobody. `app.admin` widens `USING` on this table and ONLY this
#: table (migration b57e2f9c4a13), which is exactly what a directory read needs and is the
#: same session `campaign_dispatch` uses for the same purpose.
#:
#: `churned`, not `closed`: `tenancy.models.ORG_STATUSES` is
#: `prospect|onboarding|active|suspended|churned` and there is no `closed` member, so the
#: predicate this replaced excluded nobody at all and quietly mailed departed clients about
#: an outage of a dashboard they no longer have.
_OPEN_TENANTS_SQL = text(
    "SELECT id FROM organizations WHERE deleted_at IS NULL AND status <> 'churned' ORDER BY id"
)


@dataclass(frozen=True, slots=True)
class EngineScriptOutcome:
    """How far the caller-message write got. Counts only — never an agent's words."""

    applied: int
    failed: int
    unsupported: bool


async def probe_in_flight(budget: WalkBudget | None = None) -> InFlight:
    """Count what the platform is still doing. The founder's "ONLY when", measured.

    Two halves, and they cost very differently. The queued-work half is one query over two
    platform-scoped tables. The call half is a walk: `calls` is FORCE-RLS'd, so the only
    honest way to ask "is anybody on a call anywhere" is one tenant session at a time
    (hard rule 1 — the policy is the isolation, never a WHERE clause somebody remembers).

    THE WALK IS BUDGETED AND SAYS SO. `WalkBudget` exists because these walks outgrow
    `job_timeout` as the client list grows (D-369), and being cut off by arq would leave
    the tail unmeasured with nothing reporting it. Here the consequence is sharper than
    usual: an unmeasured tail is a tenant whose live call this probe did not see, and a
    zero from a truncated walk is not evidence of zero. So the truncation is carried on
    `InFlight.complete`, `drained` refuses on it, and the drain runs to its deadline
    instead of activating on a number nobody stands behind.
    """
    walk = budget or WalkBudget()
    async with untenanted_session() as session:
        queued = int((await session.execute(_QUEUED_WORK_SQL)).scalar() or 0)
        tenants = list((await session.execute(_CALLABLE_TENANTS_SQL)).scalars().all())

    calls = 0
    unreached = 0
    for index, tenant_id in enumerate(tenants):
        if walk.spent():
            unreached = len(tenants) - index
            break
        async with tenant_session(tenant_id) as session:
            calls += int((await session.execute(_ACTIVE_CALL_SQL)).scalar() or 0)
    return InFlight(calls=calls, jobs=queued, tenants_unreached=unreached, complete=unreached == 0)


def _maintenance_prompt(window: MaintenanceWindow) -> str:
    """What a live agent is told to do while the platform is down.

    ═══ WHAT THE AGENT IS FOR, DURING A WINDOW ═══

    Not business. The founder's correction — "play a message instead of the call not
    connecting" — asks for the call to be ANSWERED and for the caller to be told, and
    stops there. Everything the agent would otherwise do next depends on machinery that is
    being worked on: the in-call knowledge tools, the action endpoints, the call-back
    booking, the post-call pipeline that turns the conversation into a lead. An agent that
    kept taking bookings through the window would be making promises nothing behind it can
    keep, which is worse than the failed call this replaces.

    ═══ HARD RULE 5 IS UNTOUCHED, IN BOTH ITS HALVES ═══

    `TRUTHFUL_ANSWER_DIRECTIVE` is appended verbatim, so a caller who asks whether they are
    talking to an AI, or whether the call is recorded, gets the truth during a maintenance
    window exactly as they do outside one. The other half — what the agent VOLUNTEERS — is
    preserved by `_maintenance_greeting`, which PREPENDS the agent's own composed opening
    line rather than replacing it: the two disclosure toggles keep doing what the client
    set them to do, and the maintenance sentence is added after them.

    No time is promised that we do not hold: the window's own `ends_at` is rendered in IST
    because every caller of an Indian SMB reads it in IST.
    """
    return "\n\n".join(
        (
            "You are answering a call while the Calevate platform is closed for planned "
            "maintenance. This is the ONLY thing you do on this call.",
            "Say the maintenance message in the caller's language: that the service is "
            "briefly unavailable for planned maintenance, when it is expected back "
            f"({_ist(window.ends_at)}), and that they should call again after that. "
            "Apologise once, briefly.",
            "Do NOT take a booking, a message, an order, a complaint or a call-back "
            "request, and do NOT promise that anyone will ring them back — nothing behind "
            "this call is running to act on it. If the caller insists, say plainly that "
            "you cannot record anything right now and ask them to call back after the "
            "time above.",
            "Then end the call politely. Keep the whole call under thirty seconds.",
            TRUTHFUL_ANSWER_DIRECTIVE,
        )
    )


def _maintenance_greeting(window: MaintenanceWindow, posture: DisclosurePosture) -> str:
    """The agent's own opening line, then the maintenance sentence.

    PREPENDED, NOT REPLACED, and this is the compliance-load-bearing line in this module.
    `opening_line` is what the agent VOLUNTEERS — the AI disclosure and the recording
    notice, each on its own client-set switch (D-163). Replacing it with a maintenance
    sentence would switch both off for the duration of the window, silently, for every
    client at once. So the composed opening survives verbatim and the maintenance sentence
    follows it.

    An agent with BOTH notices off composes to an empty opening line, which is a legitimate
    configuration; the join drops the empty part rather than emitting a leading space.
    """
    opening = compose_opening_line(posture).strip()
    notice = (
        "We are briefly closed for planned maintenance and cannot take details right "
        f"now — please call again after {_ist(window.ends_at)}."
    )
    return f"{opening} {notice}".strip()


def _ist(instant: datetime) -> str:
    """An instant in IST, as a person says it. UTC in the database, IST at the edge.

    `calevate_shared.calling_window.IST` is a `timedelta`, not a `tzinfo` — the repo's
    convention is to ADD it and read the result naively (`ist_now`, `as_ist`), because
    India has no DST and a fixed offset needs no zone database in a module that imports
    only the standard library. Followed here rather than reaching for `ZoneInfo`, which
    would be a second spelling of the one offset this product cares about.
    """
    return (instant.astimezone(UTC) + IST).strftime("%H:%M on %d %b")


def _restore_mode(stored: str | None) -> LoadShedMode:
    """The load-shed mode to put back when a window ends.

    The column is plain text (it is written from a value read at activation time), so it
    is narrowed here rather than trusted. Anything unrecognised — and `maintenance` itself,
    which would end a window by re-entering it — becomes `normal`: the only safe default
    when the record of what to restore is unreadable is the mode that serves clients.
    """
    modes: tuple[LoadShedMode, ...] = ("normal", "reduced", "emergency")
    for mode in modes:
        if stored == mode:
            return mode
    return "normal"


async def _speak_maintenance(window: MaintenanceWindow, budget: WalkBudget) -> EngineScriptOutcome:
    """Tell every live answering agent to say the maintenance message instead.

    THE ENGINE MAY SIMPLY NOT BE ABLE TO, and that is reported rather than papered over.
    `EngineCapabilities.script_override` is the declaration; when it is False this returns
    `unsupported=True` without a single vendor call and the caller alerts. A window still
    runs — the portal still closes, the drain still drains — and the operator is told, in
    those words, that callers will reach their ordinary agent for its duration.

    PER-AGENT ISOLATION. One agent's vendor failure must not cost the other ninety-nine
    theirs: a failure is counted and the walk continues; the alert carries the count and
    `sweep_engine_drift` scores every live agent against our record independently.

    **IT RUNS ON THE TWO EDGES, NOT ON EVERY TICK.** The override is applied when the
    window starts DRAINING and again when it goes ACTIVE — two passes, so a vendor blip on
    the first is usually cleared by the second. It is NOT re-applied on every fifteen-second
    tick, because that is O(agents) vendor round trips per tick for the length of the window
    and a large fleet would spend the whole drain talking to the engine.

    **THE GAP THAT USED TO LEAVE IS CLOSED AT THE OTHER END.** An agent published between
    the two edges — the portal is still open while draining, so a client can reach it —
    would have arrived with its ordinary script and kept it for the rest of the window.
    `agents/service.publish_agent` now REFUSES while a window is draining or active, which
    is the right place for it: eleven paths reach that function and every one of them writes
    the agent to the engine, so a guard on the publish route would have covered one. See its
    own argument at the raise site, and `runbooks/maintenance-window.md` §6.
    """
    engine = get_engine()
    if not engine.capabilities.has("script_override"):
        return EngineScriptOutcome(applied=0, failed=0, unsupported=True)

    prompt = _maintenance_prompt(window)
    applied = 0
    failed = 0
    async with untenanted_session() as session:
        tenants = list((await session.execute(_CALLABLE_TENANTS_SQL)).scalars().all())
    for tenant_id in tenants:
        if budget.spent():
            break
        async with tenant_session(tenant_id) as session:
            rows = (await session.execute(_ANSWERING_AGENTS_SQL)).all()
        for row in rows:
            greeting = _maintenance_greeting(window, _posture_of_row(row))
            try:
                await engine.override_call_script(
                    str(row[1]), opening_line=greeting, system_prompt=prompt
                )
            except Exception:
                # IDS ONLY, and no re-raise. The vendor's own message never reaches a log
                # line here (hard rule 6 keeps client-shaped data out; the adapter has
                # already logged the vendor detail under its own key), and one agent is
                # not a reason to abandon the rest of the fleet.
                failed += 1
                log.warning("maintenance_script_failed", extra={"agent_id": str(row[0])})
            else:
                applied += 1
    return EngineScriptOutcome(applied=applied, failed=failed, unsupported=False)


def _posture_of_row(row: Any) -> DisclosurePosture:
    """`_ANSWERING_AGENTS_SQL`'s six disclosure columns as the composer's one value.

    Positional rather than by name because the query is two lines above it; the SELECT and
    this constructor are read together or not at all.
    """
    return DisclosurePosture(
        ai_disclosure_line=str(row[2]),
        ai_disclosure_enabled=bool(row[3]),
        recording_notice_line=str(row[4]),
        recording_notice_enabled=bool(row[5]),
        caller_memory_notice_line=str(row[6]),
        caller_memory_enabled=bool(row[7]),
    )


async def _restore_scripts(budget: WalkBudget) -> EngineScriptOutcome:
    """Put every live answering agent back to saying its own words.

    THROUGH `publish_agent`, NOT THROUGH THE OVERRIDE. The override is a partial write
    from strings this module composed; the restore has to come from our own record and be
    READ BACK, because an agent still saying "we are closed for maintenance" after the
    window is the failure clients would actually notice, one caller at a time, for as long
    as nobody looked. `publish_agent` is the one path that verifies (D-64).

    Failures are counted and alerted, never raised: a restore that could not reach three
    agents must not abandon the rest, and the window is over either way.
    """
    from apps.api.agents.service import publish_agent

    applied = 0
    failed = 0
    async with untenanted_session() as session:
        tenants = list((await session.execute(_CALLABLE_TENANTS_SQL)).scalars().all())
    for tenant_id in tenants:
        if budget.spent():
            break
        async with tenant_session(tenant_id) as session:
            agent_ids = [row[0] for row in (await session.execute(_ANSWERING_AGENTS_SQL)).all()]
        for agent_id in agent_ids:
            try:
                async with tenant_session(tenant_id) as session:
                    await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
            except Exception:
                failed += 1
                log.warning("maintenance_restore_failed", extra={"agent_id": str(agent_id)})
            else:
                applied += 1
    return EngineScriptOutcome(applied=applied, failed=failed, unsupported=False)


async def _pause_campaigns(window: MaintenanceWindow, budget: WalkBudget) -> int:
    """Pause every running campaign in the fleet, one audit row each."""
    paused = 0
    async with untenanted_session() as session:
        tenants = list((await session.execute(_CALLABLE_TENANTS_SQL)).scalars().all())
    for tenant_id in tenants:
        if budget.spent():
            break
        async with tenant_session(tenant_id) as session:
            for campaign_id in await pause_campaigns_for_maintenance(session, window_id=window.id):
                # ONE ROW PER CAMPAIGN, like the client's own pause button and like
                # `complaint_spike`: "who stopped the calls, and when" must have one
                # answer whether the answer is a person, a safety or a window.
                await write_audit(
                    session,
                    action="campaign.paused",
                    actor_type="system",
                    tenant_id=tenant_id,
                    object_type="campaign",
                    object_id=str(campaign_id),
                    summary={"reason": "platform_maintenance", "window_id": str(window.id)},
                )
                paused += 1
    return paused


async def _resume_campaigns(window: MaintenanceWindow, budget: WalkBudget) -> int:
    """Put back exactly the campaigns this window paused."""
    resumed = 0
    async with untenanted_session() as session:
        tenants = list((await session.execute(_CALLABLE_TENANTS_SQL)).scalars().all())
    for tenant_id in tenants:
        if budget.spent():
            break
        async with tenant_session(tenant_id) as session:
            for campaign_id in await resume_campaigns_after_maintenance(
                session, window_id=window.id
            ):
                await write_audit(
                    session,
                    action="campaign.resumed",
                    actor_type="system",
                    tenant_id=tenant_id,
                    object_type="campaign",
                    object_id=str(campaign_id),
                    summary={"reason": "platform_maintenance", "window_id": str(window.id)},
                )
                resumed += 1
    return resumed


async def _open_tenants() -> list[UUID]:
    """Every client who still has a portal to lose, on the ONE session that can see them.

    Its own function and its own session for the reason `_OPEN_TENANTS_SQL` gives: the read
    needs `app.admin`, and the write beside it (the claim plus the outbox rows) belongs on
    the caller's transaction. Sequential rather than nested — this session closes before the
    caller's opens — so `db/session.MAX_NESTED_CONNECTIONS` is untouched.
    """
    async with admin_session() as session:
        return list((await session.execute(_OPEN_TENANTS_SQL)).scalars().all())


async def _fan_out(session: AsyncSession, *, window: MaintenanceWindow, kind: NoticeKind) -> int:
    """Queue one notice per open client, IN THE CALLER'S TRANSACTION.

    Exactly-once, and the two halves of that are one transaction: `claim_notice` stamps the
    window (CAS on `<kind>_notice_at IS NULL`) and the outbox rows are written beside it.
    A worker that loses the claim writes nothing; a transaction that rolls back un-claims
    itself, so the next tick tries again. There is no window in which a client is mailed
    twice or a claim survives with no mail behind it.

    Through the OUTBOX rather than a direct enqueue (BACKEND-PATTERNS §4): the promise and
    the domain write share a fate, and a Redis blip at 02:00 does not cost a client their
    notice.

    THE CLAIM IS TAKEN BEFORE THE DIRECTORY IS READ, so a worker that loses the race spends
    no read at all — and a directory read that raises rolls the claim back with it.
    """
    if not await claim_notice(session, window_id=window.id, kind=kind):
        return 0
    tenants = await _open_tenants()
    for tenant_id in tenants:
        await enqueue_outbox(
            session,
            job=NOTIFY_JOB,
            payload={
                "tenant_id": str(tenant_id),
                "kind": kind,
                "window_id": str(window.id),
                "reason": window.reason,
                "starts_at": window.starts_at.isoformat(),
                "ends_at": window.ends_at.isoformat(),
            },
        )
    return len(tenants)


async def maintenance_tick(ctx: dict[str, Any]) -> str:
    """Advance the open window by whatever the clock and the fleet now say.

    ONE STEP PER TICK, deliberately. Each edge is a CAS plus a fleet walk, and doing two
    in one pass would mean a window that started and activated inside the same fifteen
    seconds had never been draining — which is exactly the state the founder's "ONLY when"
    forbids. The next tick is fifteen seconds away.

    Returns a short outcome string; every branch names what it did, because a cron whose
    every answer is "ok" is a cron nobody can debug from a log.
    """
    now = datetime.now(UTC)
    budget = WalkBudget()
    async with untenanted_session() as session:
        window = await read_open_window(session)
    if window is None:
        return "no_window"

    # THE AMENDMENT NOTICE, FROM EVERY OPEN STATE, and it is here rather than in
    # `_tick_scheduled` because the amendment an operator is most likely to make is the one
    # they make DURING the window: extending `ends_at` because the work is running long.
    # Handled only on the scheduled arm, that correction never reached a client, and the
    # clients holding the old end time are exactly the ones who planned around it.
    #
    # `announced and amended_notice_at is None` is the whole condition: the advance claim
    # settles the amendment slot with it (`claim_notice`), so NULL here can only have been
    # produced by an actual amendment to an announced window.
    if window.announced and window.amended_notice_at is None:
        async with untenanted_session() as session:
            await _fan_out(session, window=window, kind="amended")

    if window.state == "scheduled":
        return await _tick_scheduled(window, now=now, budget=budget)
    if window.state == "draining":
        return await _tick_draining(window, now=now, budget=budget)
    return await _tick_active(window, now=now, budget=budget)


async def _tick_scheduled(window: MaintenanceWindow, *, now: datetime, budget: WalkBudget) -> str:
    """Announce it when it is close enough; open it when its time comes."""
    if now < window.starts_at:
        sent = 0
        if now >= window.starts_at - advance_notice_lead():
            async with untenanted_session() as session:
                sent = await _fan_out(session, window=window, kind="advance")
        return f"scheduled notices={sent}"

    async with untenanted_session() as session:
        if not await begin_drain(
            session, window_id=window.id, max_drain_minutes=window.max_drain_minutes
        ):
            return "drain_lost_race"
        await write_audit(
            session,
            action="ops.maintenance_draining",
            actor_type="system",
            object_type="platform_maintenance_window",
            object_id=str(window.id),
            summary={"max_drain_minutes": window.max_drain_minutes},
        )
    paused = await _pause_campaigns(window, budget)
    voice = await _speak_maintenance(window, budget)
    _alert_engine_outcome(window, voice, edge="draining")
    log.info(
        "maintenance_draining",
        extra={
            "window_id": str(window.id),
            "campaigns_paused": paused,
            "agents_overridden": voice.applied,
        },
    )
    return f"draining paused={paused} agents={voice.applied}"


async def _tick_draining(window: MaintenanceWindow, *, now: datetime, budget: WalkBudget) -> str:
    """Measure, publish the measurement, and activate when — and only when — it is safe.

    THE PROBE RUNS BEFORE THE DEADLINE IS CONSULTED, always. A drain that timed out would
    otherwise activate with no numbers on the row, and the straggler list is the entire
    value of the deadline to the operator standing in front of it.
    """
    # ENDING EARLY DURING A DRAIN FINISHES THE WINDOW, it does not wait for the drain.
    # "End now" sets `ends_at` to this instant (`maintenance_routes.end_maintenance`), and
    # an operator who presses it while the platform is still draining means STOP — not
    # "activate as soon as the last call ends, then stop". Without this arm the button did
    # nothing until the drain resolved, which on a wedged job is the whole drain bound.
    # `_tick_active` does the same work from the other state; both reach `complete_window`,
    # which is why it accepts either.
    if now >= window.ends_at:
        return await _complete(window, budget=budget)

    in_flight = await probe_in_flight(budget)
    async with untenanted_session() as session:
        await record_probe(session, window_id=window.id, in_flight=in_flight)

    overdue = window.drain_overdue(now)
    if not in_flight.drained and not overdue:
        return f"draining calls={in_flight.calls} jobs={in_flight.jobs}"

    # The mode to put back at the end, read immediately before the write that stores it.
    # A window that opened during a `reduced` shed must not end by declaring the platform
    # healthy — the shed is somebody else's decision and has its own reason.
    restore_mode: LoadShedMode = (await get_platform_status(force_refresh=True)).mode
    async with untenanted_session() as session:
        if not await activate(
            session,
            window_id=window.id,
            forced=overdue and not in_flight.drained,
            stragglers=json.dumps(in_flight.as_json()) if not in_flight.drained else None,
            restore_mode=restore_mode if restore_mode != "maintenance" else "normal",
        ):
            return "activate_lost_race"
        await write_audit(
            session,
            action="ops.maintenance_active",
            actor_type="system",
            object_type="platform_maintenance_window",
            object_id=str(window.id),
            summary={"forced": overdue and not in_flight.drained, **in_flight.as_json()},
        )
        await _fan_out(session, window=window, kind="active")

    # THE MODE FLIP IS LAST, and it is what actually shuts the client surface. After the
    # transition and after the notice, because a client locked out of a portal that has
    # not yet told them why is the generic-error experience this feature replaces. The
    # notice is queued, not delivered, at this point — but it is queued DURABLY, and the
    # outbox dispatcher is not shed.
    await set_platform_status(mode="maintenance", actor_id=None)

    # THE SECOND PASS. Re-applying here costs one walk per window and buys two things: an
    # agent whose override failed at the draining edge gets another go, and an agent
    # published DURING the drain — the portal is open then — is caught before the window
    # actually shuts. `_speak_maintenance` argues the residual gap this does not close.
    voice = await _speak_maintenance(window, budget)
    _alert_engine_outcome(window, voice, edge="active")

    if overdue and not in_flight.drained:
        alert(
            "WORKER_STALL",
            "maintenance_drain_forced",
            detail=(
                f"the drain deadline passed with {in_flight.calls} call(s) and "
                f"{in_flight.jobs} queued job(s) still in flight; maintenance is ACTIVE "
                "and nothing was cancelled — those calls are still up and their post-call "
                "pipelines will still run"
            ),
        )
    log.info(
        "maintenance_active",
        extra={
            "window_id": str(window.id),
            "forced": overdue and not in_flight.drained,
            "calls": in_flight.calls,
            "jobs": in_flight.jobs,
        },
    )
    return f"active forced={overdue and not in_flight.drained}"


async def _complete(window: MaintenanceWindow, *, budget: WalkBudget) -> str:
    """End the window and put everything back — from `active` or from `draining`.

    ONE function for both, because both owe the identical work and a second copy is how
    the two paths start differing. The ORDER is the part that matters and it mirrors the
    way in: the load-shed mode goes back FIRST so clients have their portal while the fleet
    work runs, because that work is minutes of vendor round trips and none of it is a
    reason to keep anybody locked out.
    """
    async with untenanted_session() as session:
        if not await complete_window(session, window_id=window.id):
            return "complete_lost_race"
        await write_audit(
            session,
            action="ops.maintenance_completed",
            actor_type="system",
            object_type="platform_maintenance_window",
            object_id=str(window.id),
            summary={"forced": window.forced, "from": window.state},
        )
        # THE "IT IS OVER" NOTICE IS SENT FROM EITHER STATE, including a window ended
        # mid-drain that never shut the portal at all. A client who was told at 9am that
        # we would be down at midnight is owed the correction whether or not the outage
        # they were promised actually happened.
        await _fan_out(session, window=window, kind="ended")

    await set_platform_status(mode=_restore_mode(window.restore_load_shed_mode), actor_id=None)
    resumed = await _resume_campaigns(window, budget)
    voice = await _restore_scripts(budget)
    _alert_engine_outcome(window, voice, edge="completed")
    log.info(
        "maintenance_completed",
        extra={
            "window_id": str(window.id),
            "from": window.state,
            "campaigns_resumed": resumed,
            "agents_restored": voice.applied,
        },
    )
    return f"completed resumed={resumed} agents={voice.applied}"


async def _tick_active(window: MaintenanceWindow, *, now: datetime, budget: WalkBudget) -> str:
    """End it when its time is up. An operator ending it early sets `ends_at` to now.

    AND RE-ASSERT THE SHED MODE WHILE IT RUNS, which is not belt-and-braces. The window
    and `platform_state.load_shed_mode` are two rows, and the ops switchboard can move the
    second on its own: an operator clearing a shed mid-window — plausibly, because the
    console shows `maintenance` and they read it as a leftover — would reopen every client
    portal while the window still says ACTIVE and the migration is still running. Nothing
    would put it back until the window ENDED, which is the wrong direction entirely.

    So the mode is a property the window MAINTAINS rather than one it sets once. It costs a
    cached read per tick (`get_platform_status` is memoised for 5s) and a write only on the
    tick that finds a disagreement.
    """
    if now < window.ends_at:
        if (await get_platform_status()).mode != "maintenance":
            log.warning("maintenance_mode_reasserted", extra={"window_id": str(window.id)})
            await set_platform_status(mode="maintenance", actor_id=None)
            return "active mode_reasserted"
        return "active"

    return await _complete(window, budget=budget)


def _alert_engine_outcome(
    window: MaintenanceWindow, outcome: EngineScriptOutcome, *, edge: str
) -> None:
    """Say what the engine could not be told, in the two ways it can fail.

    The two are different problems with different owners and are deliberately different
    alarms: `unsupported` is a property of the engine this deployment selected and is a
    fact for the operator to plan around before the next window; `failed` is N agents that
    did not take the write and is a thing to go and look at now.
    """
    if outcome.unsupported:
        alert(
            "CORE_LOGIC",
            "maintenance_voice_unsupported",
            detail=(
                "the selected voice platform cannot change what a published agent says, "
                f"so inbound callers will reach their ordinary agent for this window "
                f"({edge})"
            ),
        )
        return
    if outcome.failed:
        alert(
            "CORE_LOGIC",
            "maintenance_voice_incomplete",
            detail=(
                f"{outcome.failed} agent(s) did not take the {edge} script change "
                f"({outcome.applied} did). The DRAINING pass is re-run when the window "
                "goes active, so a blip on the first edge usually clears itself; a "
                "failure on the COMPLETED edge does not, and leaves those agents telling "
                "callers the platform is down"
            ),
        )


def _compose(*, kind: str, business: str, reason: str, starts_at: str, ends_at: str) -> str:
    """The client's email, in their terms.

    THE THREE FACTS A CLIENT CAN ACT ON, in every kind: when, why, and what keeps working.
    The last is the one an outage notice usually omits and the one that decides whether
    somebody rings us in a panic — a client whose whole business is a phone number that
    gets answered needs to know that during the window the number still gets answered,
    with a message, and that nothing they have is being deleted.

    The operator's `reason` is quoted verbatim. It is free text a person typed, so it never
    reaches a log line (hard rule 6) — and it is the answer to the only question this email
    raises.
    """
    header = {
        "advance": f"Calevate will be unavailable from {starts_at} to {ends_at}.",
        "amended": f"The planned Calevate maintenance has changed: it now runs from "
        f"{starts_at} to {ends_at}.",
        "active": f"Calevate is in planned maintenance now, until about {ends_at}.",
        "ended": "The planned Calevate maintenance is finished and everything is back.",
    }[kind]
    if kind == "ended":
        return (
            f"{header}\n\n"
            f"Your dashboard for {business} is available again, and any campaign that was "
            "running when the window opened has been resumed from exactly where it "
            "stopped — no contact was skipped and none was called twice.\n\n"
            "Thank you for your patience."
        )
    return (
        f"{header}\n\n"
        f"Why: {reason}\n\n"
        f"What this means for {business}:\n"
        "- Your dashboard, reports and settings will not be reachable during the window.\n"
        "- Your phone numbers keep ringing. Callers are answered and told we are briefly "
        "closed and when to call back, rather than getting a failed call.\n"
        "- Outbound campaigns pause when the window opens and resume by themselves "
        "afterwards, from exactly where they stopped.\n"
        "- Nothing is deleted. Your calls, recordings, leads and settings are untouched.\n\n"
        "There is nothing you need to do."
    )


async def notify_maintenance(ctx: dict[str, Any], payload: dict[str, Any]) -> str:
    """Mail ONE client about the window. Published by `_fan_out` through the outbox.

    Idempotent by construction rather than by a dedupe row: the outbox delivers each
    message once and `_fan_out` writes one per (window, kind, tenant) under a claim that
    can only be taken once. A retry of THIS job re-sends, which is the correct trade for a
    notice — a client seeing a maintenance email twice is a nuisance; a client not seeing
    it is the failure the feature exists to prevent.

    Retried on a transport failure and alerted when the ladder is spent. NOT retried when
    there is nobody to write to: that is a data fix, and the row will be just as empty in
    two minutes (`notify_hot_lead` states the rule this follows).
    """
    tenant_id = UUID(str(payload["tenant_id"]))
    kind = str(payload["kind"])
    attempt = int(ctx.get("job_try", 1))
    if kind not in NOTICE_SUBJECTS:
        alert(
            "WORKER_TERMINAL",
            "maintenance_notice_unknown_kind",
            detail="a maintenance notice named a kind this worker does not send",
        )
        return "unknown_kind"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT o.name, o.billing_email FROM organizations o WHERE o.id = :tid"),
                {"tid": tenant_id},
            )
        ).first()
        if row is None:
            return "tenant_missing"
        recipients = await _recipients(session, tenant_id=tenant_id)

    if not recipients:
        alert(
            "WORKER_TERMINAL",
            "maintenance_notice_no_channel",
            detail=(
                "a client has no billing address and no active owner, so the maintenance "
                "notice cannot be delivered — tell them another way"
            ),
            tenant_id=str(tenant_id),
        )
        return "no_channel"

    email = from_text(
        subject=NOTICE_SUBJECTS[kind],
        preheader=NOTICE_SUBJECTS[kind],
        heading=NOTICE_SUBJECTS[kind],
        text=_compose(
            kind=kind,
            business=str(row[0]),
            reason=str(payload.get("reason") or ""),
            starts_at=_ist(datetime.fromisoformat(str(payload["starts_at"]))),
            ends_at=_ist(datetime.fromisoformat(str(payload["ends_at"]))),
        ),
    )
    transport = get_transport()
    # `to_thread` for the reason `notifications._send_email` documents: the SMTP transport
    # is synchronous socket I/O, and awaiting it directly parks every other job on this
    # worker for the whole timeout — including `dispatch_outbox` on its ten-second beat.
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
    if delivered:
        log.info(
            "maintenance_notice_sent",
            extra={"tenant_id": str(tenant_id), "kind": kind, "recipients": len(delivered)},
        )
        return "sent"
    if attempt < WORKER_MAX_TRIES:
        raise Retry(defer=30.0 * attempt)
    alert(
        "WORKER_DELIVERY",
        "maintenance_notice_exhausted",
        detail=(
            f"a maintenance {kind} notice was undelivered after {attempt} attempt(s); "
            "the client has not been told"
        ),
        tenant_id=str(tenant_id),
    )
    raise RuntimeError("maintenance notice undelivered")


async def _recipients(session: AsyncSession, *, tenant_id: UUID) -> list[str]:
    """The billing address plus every ACTIVE owner, de-duplicated, stably ordered.

    Lifted verbatim in shape from `workers/account_closure._recipients` and for its
    reason: the billing mailbox is often an accountant who does not read it daily, and the
    owner is the person who reschedules their morning around a maintenance window. A
    deactivated user is excluded — a removed owner must not keep receiving the business's
    account notices.
    """
    rows = (
        await session.execute(
            text(
                "SELECT o.billing_email FROM organizations o WHERE o.id = :tid "
                "UNION "
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


__all__ = [
    "NOTICE_SUBJECTS",
    "NOTIFY_JOB",
    "TICK_SECONDS",
    "EngineScriptOutcome",
    "maintenance_tick",
    "notify_maintenance",
    "probe_in_flight",
]
