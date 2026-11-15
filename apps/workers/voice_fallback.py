"""The healer playbook `voice_fallback` (D-987): an agent whose callers cannot hear it is
moved to its last working voice, told to the owner, and moved back once the failed voice
works again.

Opened on the FIRST failure the caller heard, not on a score: the platform's `voice_failed`
on a live call (`workers/engine_signals`), or a silent answered call the scorer finds in
the call's own quality figures (`healer/health.SILENT_CALL_SQL`). The health score's floor
(`health.BROKEN_MIN_CALLS` calls in two windows) never fires at one small business's volume,
and a silent call is the one failure a caller cannot wait out.

One step per due incident, on `run_healer`'s tick; the switch row (`agent_voice_switches`)
is the truth each step branches on:

SWITCH   Studio: probe the failed voice on our key and read our voice provider's status;
         a failed probe pages. Clear: no probe exists, the call is the evidence. Then, under
         the per-agent cap (one switch per `healer_voice_switch_window_minutes`) and the fleet
         breaker (more than `healer_voice_breaker_agents` agents in
         `healer_voice_breaker_minutes` is an outage, so it stops and pages), the agent is
         moved to the first backup voice (`healer/voice.backup_voices`) through its normal
         voice change (`lifecycle.update_agent`, a verified publish that flips the agent's
         `byok` with the rung). A publish refused or a read-back that does not come back
         applied undoes it (the voice before it published again) and the next backup is
         tried. None left: handed to a person, paged.
WATCH    Every `healer_voice_probe_minutes`. The owner chose a voice (the agent holds neither
         the backup nor its own): the healer stands down. A failure on the backup too:
         held there and paged. Studio: `healer_voice_restore_probes` passing probes in a row
         with the provider not reporting a fault. Clear: the platform reporting calls
         working, at least `healer_voice_clear_recovery_minutes` on the backup, no failure
         on any agent of that voice since the switch, and `healer_voice_clear_recovery_calls`
         clean calls on other agents of it (or, with none, `healer_voice_clear_blind_
         restore_minutes`). Then the agent's own voice goes back with a verified publish.
PROBATION For `healer_voice_watch_minutes`: a failure puts the backup voice back, holds it
         and pages (`voice_switch_relapsed`); quiet closes the incident.

Never the script, the opening line or the AI and recording notices: only `engine_voice_id`
moves, and only to a voice of the same gender, so the agent's AI sentence re-renders as it
was (`healer/voice` module docstring).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.agents import lifecycle
from apps.api.core.alerting import alert
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.engine.voice_provider_status import own_voice_provider_status
from apps.api.healer import incidents, ledger, protection
from apps.api.healer import voice as voices
from apps.api.healer.health import HEARD_SQL, SILENT_CALL_SQL, call_check_params
from apps.api.healer.incidents import Incident
from apps.api.healer.playbooks import (
    AGENT_SILENT_CALL,
    AGENT_VOICE_FAILED,
    VOICE_FALLBACK,
    in_shadow,
)

log = get_logger(__name__)

PLAYBOOK: Final = VOICE_FALLBACK
#: Raised when the healer moved an agent to a backup voice: the owner is told; work, not a page.
SWITCHED: Final = "voice_switched"
#: Pages: a Studio probe failed; no backup voice could be used; the switch could not be made;
#: the fleet breaker tripped; the agent broke again after getting its voice back.
PROBE_FAILED: Final = "voice_probe_failed"
NO_FALLBACK: Final = "voice_switch_no_fallback"
SWITCH_FAILED: Final = "voice_switch_failed"
BREAKER: Final = "voice_switch_breaker"
RELAPSED: Final = "voice_switch_relapsed"
#: Pages: a second failure the caller heard on one agent inside `healer_page_repeat_minutes`.
REPEAT: Final = "caller_heard_failure_repeat"
#: The agent has its own voice back: recorded, the owner is told.
RESTORED: Final = "voice_restored"

_REASON_BY_TRIGGER: Final = {AGENT_VOICE_FAILED: "voice_failed", AGENT_SILENT_CALL: "silent_call"}


def _now() -> datetime:
    return datetime.now(UTC)


def _probe_s() -> int:
    return get_settings().healer_voice_probe_minutes * 60


def dedupe_key(agent_id: UUID) -> str:
    return incidents.dedupe_key(PLAYBOOK, agent_id)


# --- opening -------------------------------------------------------------------------------


async def _heard_in_window(session: AsyncSession, agent_id: UUID) -> int:
    """Calls of this agent inside the paging window on which the caller heard a failure."""
    params = call_check_params(_now())
    return int(
        (
            await session.execute(
                text(
                    "SELECT count(*) FROM (SELECT s.engine_call_id FROM call_engine_signals s "
                    "WHERE s.agent_id = :aid AND s.kind = ANY(CAST(:heard AS text[])) AND "
                    "coalesce(s.occurred_at, s.created_at) > now() - make_interval(mins => :w) "
                    "UNION SELECT c.engine_call_id FROM calls c WHERE c.agent_id = :aid AND "
                    "c.created_at > now() - make_interval(mins => :w) AND "
                    + SILENT_CALL_SQL
                    + ") t"
                ),
                {**params, "aid": agent_id, "w": get_settings().healer_page_repeat_minutes},
            )
        ).scalar_one()
    )


async def on_caller_heard_failure(
    tenant_id: UUID, agent_id: UUID, *, trigger: str, at: datetime | None = None
) -> bool:
    """A failure the caller heard on one of this agent's calls: record it against the voice,
    page on a second one inside the window, and open the voice playbook unless the platform
    incident or a held line already has the agent. True when an incident was opened."""
    when = at or _now()
    async with tenant_session(tenant_id) as session:
        agent = await voices.agent_voice(session, agent_id)
        if agent is None:
            return False
        if agent.voice_id:
            await voices.record_failure(
                session, tenant_id=tenant_id, agent_id=agent_id, voice_id=agent.voice_id, at=when
            )
        heard = await _heard_in_window(session, agent_id)
        held = await protection.healer_holds_line(session, agent_id=agent_id)
    ids = {"tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    if heard >= 2:
        alert(
            "CORE_LOGIC",
            REPEAT,
            detail=f"{heard} calls of this agent in {get_settings().healer_page_repeat_minutes} "
            "minutes where the caller heard a failure (silence, a cut-off or an apology)",
            episode=str(agent_id),
            **ids,
        )
    if held or not agent.published:
        return False
    async with untenanted_session() as session:
        if await incidents.open_for(session, incidents.dedupe_key("engine_outage", "platform")):
            return False
        _, opened = await incidents.open_incident(
            session,
            key=dedupe_key(agent_id),
            playbook=PLAYBOOK,
            trigger_code=trigger,
            scope="agent",
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    if opened:
        detail = (
            "a caller heard a failure on this agent's voice; the healer is moving it to its "
            "last working voice"
        )
        if trigger == AGENT_VOICE_FAILED:
            alert("CORE_LOGIC", "agent_voice_failed", detail=detail, episode=str(agent_id), **ids)
        else:
            alert("CORE_LOGIC", "agent_silent_call", detail=detail, episode=str(agent_id), **ids)
    return opened


# --- the switch row ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Switch:
    id: UUID
    from_voice: str
    to_voice: str
    from_rung: str
    to_rung: str
    state: str
    probes_passed: int
    switched_at: datetime
    restored_at: datetime | None


async def switch_for(session: AsyncSession, incident_id: UUID) -> Switch | None:
    row = (
        await session.execute(
            text(
                "SELECT id, from_voice, to_voice, from_rung, to_rung, state, probes_passed, "
                "switched_at, restored_at FROM agent_voice_switches WHERE incident_id = :i "
                "ORDER BY switched_at DESC, id DESC LIMIT 1"
            ),
            {"i": incident_id},
        )
    ).first()
    if row is None:
        return None
    return Switch(
        id=row[0],
        from_voice=str(row[1]),
        to_voice=str(row[2]),
        from_rung=str(row[3]),
        to_rung=str(row[4]),
        state=str(row[5]),
        probes_passed=int(row[6]),
        switched_at=row[7],
        restored_at=row[8],
    )


async def _insert_switch(
    session: AsyncSession,
    incident: Incident,
    *,
    from_voice: str,
    to_voice: str,
    reason: str,
    state: str,
) -> None:
    await session.execute(
        text(
            "INSERT INTO agent_voice_switches (id, tenant_id, agent_id, incident_id, from_voice, "
            "to_voice, from_rung, to_rung, reason, state, switched_at, settled_at, created_at, "
            "updated_at) VALUES (:id, :tid, :aid, :iid, :f, :t, :fr, :tr, :reason, :state, "
            "now(), CASE WHEN :state = 'shadow' THEN now() END, now(), now())"
        ),
        {
            "id": uuid7(),
            "tid": incident.tenant_id,
            "aid": incident.agent_id,
            "iid": incident.id,
            "f": from_voice,
            "t": to_voice,
            "fr": voices.rung_of(from_voice),
            "tr": voices.rung_of(to_voice),
            "reason": reason,
            "state": state,
        },
    )


async def _set_switch(session: AsyncSession, switch: Switch, sets: str, **values: object) -> bool:
    """`UPDATE agent_voice_switches SET <sets>` as a CAS on the state the step read."""
    result = await session.execute(
        text(
            f"UPDATE agent_voice_switches SET {sets}, updated_at = now() "
            "WHERE id = :sid AND state = :was"
        ),
        {"sid": switch.id, "was": switch.state, **values},
    )
    return bool(getattr(result, "rowcount", 0))


# --- shared steps --------------------------------------------------------------------------


async def _record(incident: Incident, **kwargs: object) -> None:
    async with untenanted_session() as session:
        await ledger.record(
            session,
            playbook=PLAYBOOK,
            incident_id=incident.id,
            tenant_id=incident.tenant_id,
            agent_id=incident.agent_id,
            alarm_code=incident.trigger_code,
            attempt=incident.attempts,
            **kwargs,  # type: ignore[arg-type]
        )


async def _advance(
    incident: Incident,
    *,
    state: incidents.State,
    next_in_s: int | None,
    outcome: str,
    attempted: bool = False,
) -> None:
    async with untenanted_session() as session:
        await incidents.advance(
            session,
            incident,
            state=state,
            next_in_s=next_in_s,
            outcome=outcome,
            attempted=attempted,
        )


def _ids(incident: Incident) -> dict[str, str]:
    return {
        "incident_id": str(incident.id),
        "tenant_id": str(incident.tenant_id),
        "agent_id": str(incident.agent_id),
    }


def _page(code: str, why: str, incident: Incident) -> None:
    """One page per escalation, each code spelled out so the alarm index can see it."""
    ids, episode = _ids(incident), str(incident.agent_id)
    if code == REPEAT:
        alert("CORE_LOGIC", REPEAT, detail=why, episode=episode, **ids)
    elif code == BREAKER:
        alert("CORE_LOGIC", BREAKER, detail=why, **ids)
    elif code == NO_FALLBACK:
        alert("CORE_LOGIC", NO_FALLBACK, detail=why, episode=episode, **ids)
    elif code == SWITCH_FAILED:
        alert("CORE_LOGIC", SWITCH_FAILED, detail=why, episode=episode, **ids)
    else:
        alert("CORE_LOGIC", RELAPSED, detail=why, episode=episode, **ids)


async def _escalate(incident: Incident, *, code: str, why: str) -> None:
    """Hand it to a person with a page under `code`; the agent stays where it is."""
    _page(code, why, incident)
    await _record(incident, step="escalate", outcome="ok", detail=why)
    await _advance(incident, state="escalated", next_in_s=_probe_s(), outcome="escalated")


async def _client_notice(session: AsyncSession, incident: Incident, *, open_: bool) -> None:
    """The owner's line about this switch (`healer/notices.voice_notice`): opened when the
    agent moves to a backup voice, resolved when it has its own back or the owner chose one."""
    if open_:
        await session.execute(
            text(
                "INSERT INTO heal_client_incidents (id, tenant_id, incident_id, agent_id, kind, "
                "protection, state, opened_at, created_at, updated_at) VALUES (:id, :tid, :iid, "
                ":aid, 'voice_switched', 'none', 'open', now(), now(), now()) ON CONFLICT "
                "(incident_id, tenant_id, agent_id) DO UPDATE SET state = 'open', resolved_at = "
                "NULL, notified_at = NULL, notified_by = NULL, restored_notified_at = NULL, "
                "updated_at = now()"
            ),
            {
                "id": uuid7(),
                "tid": incident.tenant_id,
                "iid": incident.id,
                "aid": incident.agent_id,
            },
        )
        return
    await session.execute(
        text(
            "UPDATE heal_client_incidents SET state = 'resolved', resolved_at = now(), "
            "updated_at = now() WHERE incident_id = :iid AND state = 'open'"
        ),
        {"iid": incident.id},
    )


async def _move(tenant_id: UUID, agent_id: UUID, *, to_voice: str) -> str | None:
    """Put the agent on `to_voice` through its normal voice change. None when it went live
    and read back applied; else why not, after the voice before it was published again."""
    try:
        async with tenant_session(tenant_id) as session:
            await lifecycle.update_agent(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine_voice_id=to_voice,
                set_engine_voice_id=True,
            )
            state = (
                await session.execute(
                    text("SELECT live_verify_state FROM agents WHERE id = :aid"), {"aid": agent_id}
                )
            ).scalar()
            if state != "applied":
                raise _NotReadBackError(str(state))
    except (ProblemError, _NotReadBackError) as refused:
        why = refused.code if isinstance(refused, ProblemError) else f"read_back_{refused}"
        await _republish(tenant_id, agent_id)
        return why
    return None


class _NotReadBackError(Exception):
    """The publish answered but its read-back did not prove the voice applied."""


async def _republish(tenant_id: UUID, agent_id: UUID) -> None:
    """Send the agent as our row holds it again, so the platform is not left on a voice
    whose switch was rolled back. A failure here is logged; the next step retries."""
    try:
        async with tenant_session(tenant_id) as session:
            agent = await voices.agent_voice(session, agent_id)
            if agent is None or agent.voice_id is None:
                return
            await lifecycle.update_agent(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine_voice_id=agent.voice_id,
                set_engine_voice_id=True,
            )
    except Exception as exc:
        log.warning(
            "healer_voice_republish_failed",
            extra={"agent_id": str(agent_id), "error": type(exc).__name__},
        )


# --- SWITCH --------------------------------------------------------------------------------


async def _switches_since(*, agent_id: UUID | None, minutes: int) -> int:
    """Switches the healer made inside `minutes` (one agent's, or distinct agents fleet-wide),
    counted on the ledger, which holds every tenant's."""
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(DISTINCT agent_id) FILTER (WHERE CAST(:aid AS uuid) IS NULL)"
                        " + count(*) FILTER (WHERE agent_id = :aid) FROM heal_actions "
                        "WHERE playbook = :p AND step = 'act' AND outcome = 'ok' "
                        "AND at > now() - make_interval(mins => :m)"
                    ),
                    {"aid": agent_id, "p": PLAYBOOK, "m": minutes},
                )
            ).scalar_one()
        )


async def _switch(incident: Incident) -> None:
    assert incident.tenant_id is not None and incident.agent_id is not None
    tenant_id, agent_id = incident.tenant_id, incident.agent_id
    settings = get_settings()
    async with tenant_session(tenant_id) as session:
        agent = await voices.agent_voice(session, agent_id)
        held = await protection.healer_holds_line(session, agent_id=agent_id)
    if agent is None or agent.voice_id is None or not agent.published:
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    if held:
        # Line protection has the agent; a voice publish would race its hold.
        await _advance(incident, state="open", next_in_s=_probe_s(), outcome="voice_waiting")
        return
    failed = agent.voice_id
    findings: list[str] = [f"voice {voices.rung_of(failed)}"]
    if voices.rung_of(failed) == "studio":
        probe = await voices.probe_studio_voice(failed, agent)
        status = await own_voice_provider_status()
        findings += [f"probe {'passed' if probe.ok else 'failed'} ({probe.why})", status.words()]
        if not probe.ok:
            alert(
                "CORE_LOGIC",
                PROBE_FAILED,
                detail=f"a Studio voice failed its probe on our key ({probe.why}); "
                f"{status.words()}. The agent is being moved to a Clear voice.",
                episode=str(agent_id),
                **_ids(incident),
            )
    else:
        findings.append("no probe exists for a Clear voice; the call is the evidence")
    candidates = await voices.backup_voices(
        tenant_id, agent_id, failed=failed, language=agent.language
    )
    reason = _REASON_BY_TRIGGER.get(incident.trigger_code, "voice_failed")
    if in_shadow(PLAYBOOK):
        await _shadow(incident, failed=failed, candidates=candidates, reason=reason)
        return
    if await _switches_since(
        agent_id=agent_id, minutes=settings.healer_voice_switch_window_minutes
    ):
        await _escalate(
            incident,
            code=REPEAT,
            why=f"this agent's voice was already switched in the last "
            f"{settings.healer_voice_switch_window_minutes} minutes; held for a person",
        )
        return
    fleet = await _switches_since(agent_id=None, minutes=settings.healer_voice_breaker_minutes)
    if fleet >= settings.healer_voice_breaker_agents:
        await _escalate(
            incident,
            code=BREAKER,
            why=f"{fleet} agents' voices switched in {settings.healer_voice_breaker_minutes} "
            "minutes: that is an outage, so no more are switched until a person looks",
        )
        return
    if not candidates:
        await _escalate(
            incident,
            code=NO_FALLBACK,
            why="no working voice and no voice added for clients of the same gender and "
            f"language to move to ({'; '.join(findings)})",
        )
        return
    refusals: list[str] = []
    for to_voice in candidates:
        refused = await _move(tenant_id, agent_id, to_voice=to_voice)
        if refused is not None:
            refusals.append(refused)
            await _record(
                incident, step="act", outcome="failed", detail=f"to {to_voice}: {refused}"
            )
            continue
        async with tenant_session(tenant_id) as session:
            await _insert_switch(
                session,
                incident,
                from_voice=failed,
                to_voice=to_voice,
                reason=reason,
                state="switched",
            )
            await _client_notice(session, incident, open_=True)
            await ledger.record(
                session,
                playbook=PLAYBOOK,
                step="act",
                outcome="ok",
                incident_id=incident.id,
                attempt=incident.attempts + 1,
                tenant_id=tenant_id,
                agent_id=agent_id,
                alarm_code=incident.trigger_code,
                detail=(
                    f"moved from {failed} ({voices.rung_of(failed)}) to {to_voice} "
                    f"({voices.rung_of(to_voice)}); {'; '.join(findings)}"
                ),
            )
        alert(
            "CORE_LOGIC",
            SWITCHED,
            detail=f"moved from a {voices.rung_of(failed)} voice to a "
            f"{voices.rung_of(to_voice)} voice after a failure callers heard",
            episode=str(agent_id),
            **_ids(incident),
        )
        await _advance(
            incident,
            state="mitigated",
            next_in_s=_probe_s(),
            outcome="voice_switched",
            attempted=True,
        )
        return
    await _escalate(
        incident,
        code=SWITCH_FAILED,
        why=f"no backup voice could be put live: {', '.join(refusals)}; the agent is still on "
        "the failing voice",
    )


async def _shadow(incident: Incident, *, failed: str, candidates: list[str], reason: str) -> None:
    """Dry run: write what the switch would have been, change nothing, close."""
    if candidates:
        async with tenant_session(incident.tenant_id) as session:  # type: ignore[arg-type]
            await _insert_switch(
                session,
                incident,
                from_voice=failed,
                to_voice=candidates[0],
                reason=reason,
                state="shadow",
            )
    await _record(
        incident,
        step="act",
        outcome="shadow",
        detail=(
            f"dry run: would move from {failed} to {candidates[0]}"
            if candidates
            else f"dry run: would hand to a person, no backup voice for {failed}"
        ),
    )
    await _advance(incident, state="resolved", next_in_s=None, outcome="shadow")


# --- WATCH and PROBATION ---------------------------------------------------------------------


async def _agent_voice_now(tenant_id: UUID, agent_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        agent = await voices.agent_voice(session, agent_id)
    return None if agent is None else agent.voice_id


async def _heard_since(tenant_id: UUID, agent_id: UUID, since: datetime) -> bool:
    """Whether a call that STARTED after `since` failed in a way the caller heard.

    A call keeps the voice it started on, so a call already under way at the switch (or the
    restore) is evidence about the voice before it, never this one. Its row is first written
    when it ends (`call.completed`), stamped with the agent's voice at that moment, so
    neither `created_at` nor the stamp says which voice spoke; `started_at` does. A signal
    counts only for a call no row or earlier signal places before `since`."""
    async with tenant_session(tenant_id) as session:
        params = call_check_params(_now())
        row = (
            await session.execute(
                text(
                    "SELECT 1 FROM call_engine_signals s WHERE s.agent_id = :aid AND s.kind = "
                    "ANY(CAST(:heard AS text[])) AND coalesce(s.occurred_at, s.created_at) > "
                    ":since AND NOT EXISTS (SELECT 1 FROM calls b WHERE b.engine_call_id = "
                    "s.engine_call_id AND coalesce(b.started_at, b.created_at) <= :since) "
                    "AND NOT EXISTS (SELECT 1 FROM call_engine_signals e WHERE e.engine_call_id "
                    "= s.engine_call_id AND coalesce(e.occurred_at, e.created_at) <= :since) "
                    "UNION ALL SELECT 1 FROM calls c WHERE c.agent_id = :aid AND "
                    "c.created_at > :since AND coalesce(c.started_at, c.created_at) > :since "
                    "AND " + SILENT_CALL_SQL + " LIMIT 1"
                ),
                {**params, "aid": agent_id, "since": since},
            )
        ).first()
    return row is not None


async def _stand_down(incident: Incident, switch: Switch) -> None:
    """The owner (or a person) chose the agent's voice: the healer stops here."""
    async with tenant_session(incident.tenant_id) as session:  # type: ignore[arg-type]
        await _set_switch(session, switch, "state = 'stood_down', settled_at = now()")
        await _client_notice(session, incident, open_=False)
    await _record(
        incident,
        step="decide",
        outcome="ok",
        detail="the agent's voice was chosen by someone else; the healer stood down",
    )
    await _advance(incident, state="resolved", next_in_s=None, outcome="stood_down")


async def _clear_voice_back(switch: Switch) -> tuple[bool, str]:
    """Whether a failed Clear catalogue voice is proven back, and the evidence, read across
    every client's agents on that voice since the switch."""
    from apps.workers.healer import platform_status

    settings = get_settings()
    now = _now()
    status = await platform_status()
    if status is not None and status.calls_operational is not True:
        return False, "the platform does not report calls working"
    if now - switch.switched_at < timedelta(minutes=settings.healer_voice_clear_recovery_minutes):
        return False, "not long enough on the backup voice"
    clean = failed = 0
    async with admin_session() as directory:
        tenants = [
            UUID(str(r[0]))
            for r in (
                await directory.execute(
                    text("SELECT id FROM organizations WHERE deleted_at IS NULL ORDER BY id")
                )
            ).all()
        ]
    for tenant_id in tenants:
        async with tenant_session(tenant_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT count(*) FILTER (WHERE NOT " + HEARD_SQL + "), "
                        "count(*) FILTER (WHERE " + HEARD_SQL + ") FROM calls c "
                        "WHERE c.created_at > :since AND c.status = 'completed' AND "
                        "c.voice_settings ->> 'engine_voice' = :v"
                    ),
                    {**call_check_params(now), "since": switch.switched_at, "v": switch.from_voice},
                )
            ).one()
        clean, failed = clean + int(row[0]), failed + int(row[1])
    if failed:
        return False, f"{failed} call(s) on that voice failed since the switch"
    if clean >= settings.healer_voice_clear_recovery_calls:
        return True, f"{clean} clean call(s) on that voice since the switch"
    blind = timedelta(minutes=settings.healer_voice_clear_blind_restore_minutes)
    if clean == 0 and now - switch.switched_at >= blind:
        return True, "no other agent took calls on that voice; waited the full blind period"
    return False, f"only {clean} clean call(s) on that voice since the switch"


async def _watch(incident: Incident, switch: Switch) -> None:
    assert incident.tenant_id is not None and incident.agent_id is not None
    tenant_id, agent_id = incident.tenant_id, incident.agent_id
    settings = get_settings()
    now_voice = await _agent_voice_now(tenant_id, agent_id)
    if now_voice != switch.to_voice:
        await _stand_down(incident, switch)
        return
    if await _heard_since(tenant_id, agent_id, switch.switched_at):
        async with tenant_session(tenant_id) as session:
            await _set_switch(session, switch, "state = 'held'")
        await _escalate(
            incident,
            code=REPEAT,
            why="callers heard a failure on the backup voice too; the agent is held on it",
        )
        return
    if switch.from_rung == "studio":
        async with tenant_session(tenant_id) as session:
            agent = await voices.agent_voice(session, agent_id)
        assert agent is not None
        probe = await voices.probe_studio_voice(switch.from_voice, agent)
        status = await own_voice_provider_status()
        passed = probe.ok and status.operational is not False
        async with tenant_session(tenant_id) as session:
            await _set_switch(
                session,
                switch,
                "probes_passed = CASE WHEN :ok THEN probes_passed + 1 ELSE 0 END",
                ok=passed,
            )
        await _record(
            incident,
            step="verify",
            outcome="ok" if passed else "failed",
            detail=f"probe {probe.why}; {status.words()}",
        )
        back = passed and switch.probes_passed + 1 >= settings.healer_voice_restore_probes
        evidence = f"{switch.probes_passed + 1 if passed else 0} passing probe(s) in a row"
    else:
        back, evidence = await _clear_voice_back(switch)
        await _record(incident, step="verify", outcome="ok" if back else "failed", detail=evidence)
    if not back:
        await _advance(incident, state="mitigated", next_in_s=_probe_s(), outcome="voice_switched")
        return
    refused = await _move(tenant_id, agent_id, to_voice=switch.from_voice)
    if refused is not None:
        await _record(incident, step="restore", outcome="failed", detail=refused)
        await _advance(incident, state="mitigated", next_in_s=_probe_s(), outcome="voice_switched")
        return
    async with tenant_session(tenant_id) as session:
        await _set_switch(session, switch, "state = 'restored', restored_at = now()")
        await _client_notice(session, incident, open_=False)
        await ledger.record(
            session,
            playbook=PLAYBOOK,
            step="restore",
            outcome="ok",
            incident_id=incident.id,
            tenant_id=tenant_id,
            agent_id=agent_id,
            alarm_code=incident.trigger_code,
            detail=f"back on {switch.from_voice}: {evidence}",
        )
    alert(
        "CORE_LOGIC",
        RESTORED,
        detail=f"back on its own voice: {evidence}",
        episode=str(agent_id),
        **_ids(incident),
    )
    await _advance(
        incident,
        state="mitigated",
        next_in_s=settings.healer_voice_watch_minutes * 60,
        outcome="voice_probation",
    )


async def _probation(incident: Incident, switch: Switch) -> None:
    assert incident.tenant_id is not None and incident.agent_id is not None
    assert switch.restored_at is not None
    tenant_id, agent_id = incident.tenant_id, incident.agent_id
    settings = get_settings()
    if await _agent_voice_now(tenant_id, agent_id) != switch.from_voice:
        await _advance(incident, state="resolved", next_in_s=None, outcome="stood_down")
        return
    if await _heard_since(tenant_id, agent_id, switch.restored_at):
        refused = await _move(tenant_id, agent_id, to_voice=switch.to_voice)
        async with tenant_session(tenant_id) as session:
            if refused is None:
                await _insert_switch(
                    session,
                    incident,
                    from_voice=switch.from_voice,
                    to_voice=switch.to_voice,
                    reason="voice_failed",
                    state="held",
                )
                await _client_notice(session, incident, open_=True)
            await ledger.record(
                session,
                playbook=PLAYBOOK,
                step="protect",
                outcome="ok" if refused is None else "failed",
                incident_id=incident.id,
                tenant_id=tenant_id,
                agent_id=agent_id,
                alarm_code=incident.trigger_code,
                detail=f"relapse: backup {switch.to_voice} put back"
                if refused is None
                else f"relapse: the backup could not be put back ({refused})",
            )
        await _escalate(
            incident,
            code=RELAPSED,
            why="the agent's own voice failed again after it was given back; the backup voice "
            "is held until a person decides",
        )
        return
    if switch.restored_at + timedelta(minutes=settings.healer_voice_watch_minutes) <= _now():
        await _record(incident, step="verify", outcome="ok", detail="quiet through the watch")
        await _advance(incident, state="resolved", next_in_s=None, outcome="verified")
        return
    await _advance(incident, state="mitigated", next_in_s=_probe_s(), outcome="voice_probation")


async def _held(incident: Incident, switch: Switch | None) -> None:
    """Handed to a person. Closes itself only when someone chose the agent's voice."""
    if switch is not None and switch.state in ("switched", "held") and incident.tenant_id:
        assert incident.agent_id is not None
        now_voice = await _agent_voice_now(incident.tenant_id, incident.agent_id)
        if now_voice not in (switch.to_voice, None):
            await _stand_down(incident, switch)
            return
    await _advance(incident, state="escalated", next_in_s=_probe_s(), outcome="escalated")


async def voice_fallback(incident: Incident) -> None:
    """One step of one switch (`_STEPS["voice_fallback"]`)."""
    assert incident.tenant_id is not None and incident.agent_id is not None
    async with tenant_session(incident.tenant_id) as session:
        switch = await switch_for(session, incident.id)
    if incident.state == "escalated":
        await _held(incident, switch)
        return
    if switch is None or switch.state == "shadow":
        await _switch(incident)
        return
    if switch.state == "switched":
        await _watch(incident, switch)
        return
    if switch.state == "restored":
        await _probation(incident, switch)
        return
    await _held(incident, switch)


__all__ = [
    "BREAKER",
    "NO_FALLBACK",
    "PLAYBOOK",
    "PROBE_FAILED",
    "RELAPSED",
    "REPEAT",
    "RESTORED",
    "SWITCHED",
    "SWITCH_FAILED",
    "Switch",
    "dedupe_key",
    "on_caller_heard_failure",
    "switch_for",
    "voice_fallback",
]
