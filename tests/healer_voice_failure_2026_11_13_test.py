"""The healer moves an agent off a voice callers cannot hear (D-987), against a real
database: opened on the first failure, switched to the last working voice through the
agent's own voice change, moved back once the failed voice is proven working, held and paged
on a relapse, and every guardrail around it.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. No vendor is called: the agent's voice change, the probe and the provider's
status are replaced by fakes that write what the real ones would.
"""

from __future__ import annotations

import importlib.util
import logging
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.billing.engine_minutes import engine_minute_cost, rate_key_ran
from apps.api.core.alarm_severity import ALARM_SEVERITY
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest import _byok_value
from apps.api.engine.voice_provider_status import VoiceProviderStatus, read_summary
from apps.api.healer import health, incidents, ledger, notices, playbooks
from apps.api.healer import voice as voices
from apps.api.healer.incidents import Incident
from apps.workers import healer as healer_jobs
from apps.workers import healer_watch, voice_fallback
from sqlalchemy import create_engine, text
from tests.conftest import create_org_with_receptionist

pytestmark = [pytest.mark.rls]

STUDIO = "byok:studio-voice-a"
STUDIO_B = "byok:studio-voice-b"
CLEAR = "engine:clear-voice-a"
CLEAR_B = "engine:clear-voice-b"


async def _agent(prefix: str, voice: str = CLEAR) -> tuple[UUID, UUID]:
    """A published agent on `voice` (status and ref written directly: no engine is called)."""
    created = await create_org_with_receptionist(
        name="Voice Farm",
        slug=f"vf-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', engine_agent_ref = :r, engine_voice_id = :v, "
                "live_verify_state = 'applied' WHERE id = :a"
            ),
            {"r": f"ref_{agent_id.hex}", "v": voice, "a": agent_id},
        )
    return tenant_id, agent_id


async def _voice(tenant_id: UUID, agent_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT engine_voice_id FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()


async def _incident(agent_id: UUID) -> Incident:
    async with untenanted_session() as session:
        found = await incidents.open_for(session, voice_fallback.dedupe_key(agent_id))
    assert found is not None
    return found


async def _step(agent_id: UUID) -> Incident:
    await voice_fallback.voice_fallback(await _incident(agent_id))
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id FROM heal_incidents WHERE dedupe_key = :k ORDER BY opened_at DESC "
                    "LIMIT 1"
                ),
                {"k": voice_fallback.dedupe_key(agent_id)},
            )
        ).scalar_one()
        found = await incidents.read_incident(session, rows)
    assert found is not None
    return found


async def _switch(tenant_id: UUID, incident_id: UUID) -> voice_fallback.Switch | None:
    async with tenant_session(tenant_id) as session:
        return await voice_fallback.switch_for(session, incident_id)


async def _signal(tenant_id: UUID, agent_id: UUID, kind: str = "voice_failed") -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO call_engine_signals (id, tenant_id, agent_id, engine_call_id, kind, "
                "occurred_at, created_at, updated_at) VALUES (:id, :t, :a, :e, :k, now(), now(), "
                "now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "e": f"x_{uuid.uuid4().hex}", "k": kind},
        )


async def _call(
    tenant_id: UUID,
    agent_id: UUID,
    *,
    quality: str | None = '{"turns": 4}',
    duration: int = 40,
    voice: str | None = None,
    ago: timedelta = timedelta(minutes=5),
    updated_ago: timedelta | None = None,
    before_agent: bool | None = None,
    direction: str = "inbound",
    party: str | None = None,
) -> UUID:
    call_id = uuid7()
    started = datetime.now(UTC) - ago
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, ended_at, duration_s, engine_quality, voice_settings, "
                "ended_before_agent, from_e164, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                ":dir, 'completed', :s, :end, :d, CAST(:q AS jsonb), CAST(:vs AS jsonb), :ba, "
                ":party, :s, :u)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"x_{call_id.hex}",
                "dir": direction,
                "s": started,
                "end": started + timedelta(seconds=duration),
                "d": duration,
                "q": quality,
                "vs": None if voice is None else f'{{"engine_voice": "{voice}"}}',
                "ba": before_agent,
                "party": party,
                "u": datetime.now(UTC) - (updated_ago or ago),
            },
        )
    return call_id


class _Mover:
    """`lifecycle.update_agent` for the voice: writes the voice and a read-back state."""

    def __init__(self, refuse: set[str] | None = None) -> None:
        self.refuse = refuse or set()
        self.calls: list[str | None] = []

    async def __call__(self, session: Any, **kwargs: Any) -> None:
        voice = kwargs["engine_voice_id"]
        self.calls.append(voice)
        await session.execute(
            text("UPDATE agents SET engine_voice_id = :v, live_verify_state = :s WHERE id = :a"),
            {
                "v": voice,
                "s": "unreachable" if voice in self.refuse else "applied",
                "a": kwargs["agent_id"],
            },
        )


@pytest.fixture
def pages(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    raised: list[str] = []

    def capture(stage: str, code: str, **_: Any) -> None:
        raised.append(code)

    monkeypatch.setattr(voice_fallback, "alert", capture)
    monkeypatch.setattr(healer_jobs, "alert", capture)
    return raised


@pytest.fixture
def mover(monkeypatch: pytest.MonkeyPatch) -> _Mover:
    moved = _Mover()
    monkeypatch.setattr(voice_fallback.lifecycle, "update_agent", moved)
    return moved


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "healer_enabled", True)
    monkeypatch.setattr(settings, "healer_paused_playbooks", "")
    monkeypatch.setattr(settings, "healer_shadow_playbooks", "")
    monkeypatch.setattr(settings, "healer_new_playbook_shadow_days", 0)
    monkeypatch.setattr(settings, "healer_voice_restore_probes", 2)
    monkeypatch.setattr(settings, "healer_voice_breaker_agents", 1000)
    monkeypatch.setattr(settings, "healer_voice_watch_minutes", 120)


def _backups(monkeypatch: pytest.MonkeyPatch, found: list[str]) -> None:
    async def fake(*_: Any, **__: Any) -> list[str]:
        return list(found)

    monkeypatch.setattr(voices, "backup_voices", fake)


def _probe(monkeypatch: pytest.MonkeyPatch, *, ok: bool) -> None:
    async def fake(*_: Any, **__: Any) -> voices.Probe:
        return voices.Probe(ok=ok, why="spoke" if ok else "no_audio")

    async def status(*_: Any, **__: Any) -> VoiceProviderStatus:
        return VoiceProviderStatus(reachable=True, operational=True, indicator="none")

    monkeypatch.setattr(voices, "probe_studio_voice", fake)
    monkeypatch.setattr(voice_fallback, "own_voice_provider_status", status)


async def _open(tenant_id: UUID, agent_id: UUID) -> bool:
    return await voice_fallback.on_caller_heard_failure(
        tenant_id, agent_id, trigger=playbooks.AGENT_VOICE_FAILED
    )


# --- opening and paging --------------------------------------------------------------------


async def test_the_first_voice_failed_opens_the_playbook_and_a_second_pages(
    pages: list[str],
) -> None:
    tenant_id, agent_id = await _agent("open")
    await _signal(tenant_id, agent_id)
    assert await _open(tenant_id, agent_id) is True
    assert pages == ["agent_voice_failed"]
    await _signal(tenant_id, agent_id)
    assert await _open(tenant_id, agent_id) is False
    assert voice_fallback.REPEAT in pages
    async with tenant_session(tenant_id) as session:
        failed = (
            await session.execute(
                text("SELECT last_failed_at FROM agent_voice_history WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar()
    assert failed is not None


def test_the_paging_rules_are_the_severities() -> None:
    for code in (
        "voice_probe_failed",
        "caller_heard_failure_repeat",
        "voice_domain_failing",
        "engine_call_own_key_failed",
        "voice_switch_relapsed",
        "voice_switch_no_fallback",
        "voice_switch_breaker",
        "call_objective_fast_burn",
        "healer_action_breaker",
    ):
        assert ALARM_SEVERITY[code] == "page", code
    # One voice_failed with a healthy probe stays attention plus the owner's line.
    assert ALARM_SEVERITY["engine_call_voice_failed"] == "attention"
    assert ALARM_SEVERITY["studio_call_voice_failed"] == "attention"
    assert ALARM_SEVERITY["voice_switched"] == "attention"
    assert ALARM_SEVERITY["call_objective_slow_burn"] == "attention"


# --- switching ---------------------------------------------------------------------------


async def test_a_studio_probe_that_fails_pages_and_moves_the_agent_to_clear(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    tenant_id, agent_id = await _agent("sfail", STUDIO)
    _probe(monkeypatch, ok=False)
    _backups(monkeypatch, [CLEAR])
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    assert voice_fallback.PROBE_FAILED in pages and voice_fallback.SWITCHED in pages
    assert await _voice(tenant_id, agent_id) == CLEAR
    switch = await _switch(tenant_id, incident.id)
    assert switch is not None and switch.state == "switched"
    assert (switch.from_rung, switch.to_rung) == ("studio", "clear")
    assert incident.state == "mitigated" and incident.last_outcome == "voice_switched"


async def test_a_studio_probe_that_passes_still_moves_on_call_evidence_without_paging(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    tenant_id, agent_id = await _agent("spass", STUDIO)
    _probe(monkeypatch, ok=True)
    _backups(monkeypatch, [CLEAR])
    await _open(tenant_id, agent_id)
    await _step(agent_id)
    assert voice_fallback.PROBE_FAILED not in pages
    assert await _voice(tenant_id, agent_id) == CLEAR


async def test_a_clear_agent_moves_to_studio(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    tenant_id, agent_id = await _agent("clear", CLEAR)
    _backups(monkeypatch, [STUDIO])
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    switch = await _switch(tenant_id, incident.id)
    assert switch is not None and (switch.from_rung, switch.to_rung) == ("clear", "studio")
    assert await _voice(tenant_id, agent_id) == STUDIO


def test_the_byok_scope_flips_with_the_rung() -> None:
    model = "gemini-2.5-flash-lite"
    assert _byok_value(voices.rung_of(STUDIO) == "studio", model) == "llm_voice"
    assert _byok_value(voices.rung_of(CLEAR) == "studio", model) == "llm"
    assert _byok_value(True) == "voice" and _byok_value(False) == "off"


async def test_a_switch_that_does_not_read_back_is_undone_and_the_next_voice_tried(
    monkeypatch: pytest.MonkeyPatch, pages: list[str]
) -> None:
    tenant_id, agent_id = await _agent("undo", CLEAR)
    moved = _Mover(refuse={STUDIO})
    monkeypatch.setattr(voice_fallback.lifecycle, "update_agent", moved)
    _backups(monkeypatch, [STUDIO, CLEAR_B])
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    # Tried Studio, read back unproven: the write rolled back and the voice before it was
    # published again, then the next backup.
    assert moved.calls[:3] == [STUDIO, CLEAR, CLEAR_B]
    assert await _voice(tenant_id, agent_id) == CLEAR_B
    async with untenanted_session() as session:
        rows = await ledger.list_actions(session, incident_id=incident.id, limit=10)
    assert any(r.step == "act" and r.outcome == "failed" for r in rows)


async def test_nothing_to_move_to_escalates_and_pages(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    tenant_id, agent_id = await _agent("none", CLEAR)
    _backups(monkeypatch, [])
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    assert incident.state == "escalated"
    assert voice_fallback.NO_FALLBACK in pages
    assert mover.calls == [] and await _voice(tenant_id, agent_id) == CLEAR


async def test_one_switch_per_agent_per_window(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    tenant_id, agent_id = await _agent("cap", CLEAR)
    _backups(monkeypatch, [STUDIO])
    async with untenanted_session() as session:
        await ledger.record(
            session, playbook="voice_fallback", step="act", outcome="ok", agent_id=agent_id
        )
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    assert incident.state == "escalated" and voice_fallback.REPEAT in pages
    assert mover.calls == []


async def test_the_fleet_breaker_stops_switching_and_pages(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    monkeypatch.setattr(get_settings(), "healer_voice_breaker_agents", 2)
    tenant_id, agent_id = await _agent("breaker", CLEAR)
    _backups(monkeypatch, [STUDIO])
    async with untenanted_session() as session:
        for _ in range(2):
            await ledger.record(
                session, playbook="voice_fallback", step="act", outcome="ok", agent_id=uuid7()
            )
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    assert incident.state == "escalated" and voice_fallback.BREAKER in pages
    assert mover.calls == []


# --- watching, restoring, relapsing ----------------------------------------------------------


async def test_passing_probes_give_a_studio_agent_its_voice_back_then_quiet_closes_it(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    tenant_id, agent_id = await _agent("restore", STUDIO)
    _probe(monkeypatch, ok=False)
    _backups(monkeypatch, [CLEAR])
    await _open(tenant_id, agent_id)
    await _step(agent_id)
    _probe(monkeypatch, ok=True)
    incident = await _step(agent_id)
    assert await _voice(tenant_id, agent_id) == CLEAR  # one passing probe is not enough
    incident = await _step(agent_id)
    assert await _voice(tenant_id, agent_id) == STUDIO
    switch = await _switch(tenant_id, incident.id)
    assert switch is not None and switch.state == "restored"
    assert incident.last_outcome == "voice_probation"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agent_voice_switches SET restored_at = now() - interval '3 hours' "
                "WHERE id = :s"
            ),
            {"s": switch.id},
        )
    incident = await _step(agent_id)
    assert incident.state == "resolved"


async def test_a_relapse_after_restore_holds_the_backup_and_pages(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    monkeypatch.setattr(get_settings(), "healer_voice_restore_probes", 1)
    tenant_id, agent_id = await _agent("relapse", STUDIO)
    _probe(monkeypatch, ok=True)
    _backups(monkeypatch, [CLEAR])
    await _open(tenant_id, agent_id)
    await _step(agent_id)
    await _step(agent_id)
    assert await _voice(tenant_id, agent_id) == STUDIO
    await _signal(tenant_id, agent_id)
    incident = await _step(agent_id)
    assert incident.state == "escalated" and voice_fallback.RELAPSED in pages
    assert await _voice(tenant_id, agent_id) == CLEAR
    switch = await _switch(tenant_id, incident.id)
    assert switch is not None and switch.state == "held"


async def test_a_call_under_way_at_the_switch_is_not_held_against_the_backup(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    # The call that tripped the switch ends after it: its row is written then, stamped with
    # the backup voice, and it carries a second problem raised after the switch.
    tenant_id, agent_id = await _agent("underway", CLEAR)
    _backups(monkeypatch, [STUDIO])
    await _signal(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        tripped = (
            await session.execute(
                text("SELECT engine_call_id FROM call_engine_signals WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar_one()
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    assert await _voice(tenant_id, agent_id) == STUDIO
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO call_engine_signals (id, tenant_id, agent_id, engine_call_id, kind, "
                "occurred_at, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'no_answer_from_model', now(), now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "e": tripped},
        )
    silent = await _call(
        tenant_id, agent_id, quality='{"turns": 0}', voice=STUDIO, ago=timedelta(minutes=3)
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET created_at = now() WHERE id = :c"), {"c": silent}
        )
    pages.clear()
    incident = await _step(agent_id)
    switch = await _switch(tenant_id, incident.id)
    assert switch is not None and switch.state == "switched"
    assert incident.state == "mitigated" and voice_fallback.REPEAT not in pages
    # A call that started on the backup and failed still holds it.
    await _call(tenant_id, agent_id, quality='{"turns": 0}', voice=STUDIO, ago=timedelta(0))
    incident = await _step(agent_id)
    assert incident.state == "escalated" and voice_fallback.REPEAT in pages


async def test_the_owner_choosing_a_voice_stands_the_healer_down(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    tenant_id, agent_id = await _agent("owner", CLEAR)
    _backups(monkeypatch, [STUDIO])
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_voice_id = :v WHERE id = :a"),
            {"v": STUDIO_B, "a": agent_id},
        )
    incident = await _step(agent_id)
    assert incident.state == "resolved" and incident.last_outcome == "stood_down"
    switch = await _switch(tenant_id, incident.id)
    assert switch is not None and switch.state == "stood_down"
    assert await _voice(tenant_id, agent_id) == STUDIO_B


async def test_dry_run_writes_the_switch_it_would_make_and_changes_nothing(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    monkeypatch.setattr(get_settings(), "healer_shadow_playbooks", "voice_fallback")
    tenant_id, agent_id = await _agent("shadow", CLEAR)
    _backups(monkeypatch, [STUDIO])
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    assert mover.calls == [] and await _voice(tenant_id, agent_id) == CLEAR
    assert incident.state == "resolved" and incident.last_outcome == "shadow"
    async with untenanted_session() as session:
        rows = await ledger.list_actions(session, incident_id=incident.id, limit=5)
    assert any(r.outcome == "shadow" and STUDIO in (r.detail or "") for r in rows)


def test_new_playbooks_start_in_dry_run_for_the_configured_days(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    introduced = playbooks.PLAYBOOK_BY_KEY["voice_fallback"].introduced
    assert introduced is not None
    monkeypatch.setattr(get_settings(), "healer_new_playbook_shadow_days", 3)
    assert playbooks.in_shadow("voice_fallback", today=introduced + timedelta(days=2))
    assert not playbooks.in_shadow("voice_fallback", today=introduced + timedelta(days=3))
    # A playbook that enforces a hard rule never runs dry.
    monkeypatch.setattr(get_settings(), "healer_shadow_playbooks", "engine_drift")
    assert not playbooks.in_shadow("engine_drift", today=date(2030, 1, 1))


async def test_the_global_action_breaker_stops_automatic_repairs(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    monkeypatch.setattr(get_settings(), "healer_action_breaker_count", 3)
    tenant_id, agent_id = await _agent("gbreak", CLEAR)
    _backups(monkeypatch, [STUDIO])
    async with untenanted_session() as session:
        for _ in range(4):
            await ledger.record(session, playbook="outbox_replay", step="act", outcome="ok")
    await _open(tenant_id, agent_id)
    incident = await _incident(agent_id)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE heal_incidents SET next_attempt_at = now() - interval '1 minute'"
                " WHERE id = :i"
            ),
            {"i": incident.id},
        )
    from collections import Counter

    await healer_jobs._advance_due(Counter())
    assert "healer_action_breaker" in pages
    assert mover.calls == []


def test_the_limits_are_the_console_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "healer_voice_candidates", 7)
    monkeypatch.setattr(get_settings(), "healer_voice_probe_minutes", 4)
    playbook = playbooks.PLAYBOOK_BY_KEY["voice_fallback"]
    assert playbooks.effective_limits(playbook) == (7, 240)
    monkeypatch.setattr(get_settings(), "healer_voice_probe_max_chars", 12)
    line = voices.probe_line(language="en-IN", direction="inbound", business="Sunrise Homes")
    assert line is None or len(line) <= 12


# --- the record of working voices and the backups ---------------------------------------------


async def test_working_voices_come_from_clean_calls_and_drop_after_a_failure() -> None:
    tenant_id, agent_id = await _agent("history", CLEAR)
    await _call(tenant_id, agent_id, voice=STUDIO, ago=timedelta(minutes=20))
    await _call(tenant_id, agent_id, voice=CLEAR_B, ago=timedelta(minutes=10))
    await _call(
        tenant_id, agent_id, voice=CLEAR_B, quality='{"turns": 0}', ago=timedelta(minutes=5)
    )
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await voices.record_window(
            session, tenant_id=tenant_id, start=now - timedelta(hours=1), end=now
        )
        await voices.record_window(
            session, tenant_id=tenant_id, start=now - timedelta(hours=1), end=now
        )
        worked = await voices.working_voices(session, agent_id=agent_id)
    assert worked == [STUDIO]


def test_a_backup_is_never_in_the_failed_voices_domain() -> None:
    assert voices.failure_domain(STUDIO) == voices.failure_domain(STUDIO_B)
    assert voices.failure_domain(CLEAR) != voices.failure_domain(CLEAR_B)


# --- call checks --------------------------------------------------------------------------------


async def test_silent_calls_count_as_heard_failures_and_dead_air_as_slow() -> None:
    tenant_id, agent_id = await _agent("flags", CLEAR)
    start = datetime.now(UTC) - timedelta(hours=2)
    await _call(tenant_id, agent_id, quality='{"turns": 0}', ago=timedelta(minutes=50))  # (i)
    await _call(  # (ii) no quality block, settled
        tenant_id,
        agent_id,
        quality=None,
        ago=timedelta(minutes=50),
        updated_ago=timedelta(minutes=40),
    )
    await _call(  # (iii) dead air
        tenant_id,
        agent_id,
        quality='{"turns": 5, "longest_silence_s": 12}',
        ago=timedelta(minutes=50),
    )
    await _call(  # (iv) the caller left before the agent spoke
        tenant_id, agent_id, quality='{"turns": 1}', before_agent=True, ago=timedelta(minutes=50)
    )
    await _call(tenant_id, agent_id, ago=timedelta(minutes=50))  # clean
    async with tenant_session(tenant_id) as session:
        counted = await health.count_between(
            session, start=start, end=datetime.now(UTC), agent_id=agent_id
        )
        silent = await healer_watch.silent_agents(
            session, start=start, end=datetime.now(UTC), now=datetime.now(UTC)
        )
    assert counted[0].calls == 5
    assert counted[0].failed_calls == 2
    assert counted[0].slow_starts == 2
    assert [a for a, _ in silent] == [agent_id]


async def test_callers_ringing_back_are_counted_and_no_number_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    tenant_id, agent_id = await _agent("ringback", CLEAR)
    number = "+919812345678"
    await _call(tenant_id, agent_id, party=number, duration=4, ago=timedelta(minutes=20))
    await _call(tenant_id, agent_id, party=number, ago=timedelta(minutes=19))
    await _call(tenant_id, agent_id, party="+919800000001", ago=timedelta(minutes=18))
    caplog.set_level(logging.DEBUG)
    async with tenant_session(tenant_id) as session:
        found = await healer_watch.repeat_callers(session)
    assert found[agent_id].calls == 1
    assert number not in caplog.text


async def test_ring_backs_a_closed_line_check_saw_do_not_open_it_again(
    pages: list[str],
) -> None:
    from collections import Counter

    tenant_id, agent_id = await _agent("ringagain", CLEAR)
    number = "+919812345679"
    await _call(tenant_id, agent_id, party=number, duration=4, ago=timedelta(minutes=20))
    await _call(tenant_id, agent_id, party=number, duration=4, ago=timedelta(minutes=19))
    await _call(tenant_id, agent_id, party=number, ago=timedelta(minutes=18))

    async def score() -> Counter[str]:
        async with tenant_session(tenant_id) as session:
            ring_backs = await healer_watch.repeat_callers(session)
        tally: Counter[str] = Counter()
        scored = healer_jobs._TenantScore(
            verdicts=[],
            silent=[],
            ring_backs=ring_backs,
            failing_in_domain_window={},
            failing_in_page_window={},
            objective=healer_watch.ObjectiveCounts(),
            drops=[],
        )
        await healer_jobs._act_on_calls(tenant_id, scored, tally)
        return tally

    assert (await score())["opened_line_check"] == 1
    key = incidents.dedupe_key("line_protection", agent_id)
    async with untenanted_session() as session:
        opened = await incidents.open_for(session, key)
        assert opened is not None
        assert await incidents.close_by_person(session, opened.id)
    # The next scoring still counts the same calls inside its hour.
    assert (await score())["opened_line_check"] == 0
    # A caller ringing back after the check closed opens it again.
    await _call(tenant_id, agent_id, party=number, duration=4, ago=timedelta(seconds=60))
    await _call(tenant_id, agent_id, party=number, ago=timedelta(0))
    assert (await score())["opened_line_check"] == 1


async def test_failures_on_one_voice_domain_make_one_incident(pages: list[str]) -> None:
    two = [(uuid7(), uuid7()) for _ in range(2)]
    fleet = healer_jobs._FleetFindings(
        domain=dict.fromkeys(two, voices.OWN_VOICE_DOMAIN), spread={}
    )
    from collections import Counter

    tally: Counter[str] = Counter()
    await healer_jobs._detect_voice_domains(fleet, tally)
    await healer_jobs._detect_voice_domains(fleet, tally)
    assert tally["opened_voice_domain"] <= 1
    async with untenanted_session() as session:
        open_one = await incidents.open_for(
            session, incidents.dedupe_key("voice_domain_outage", voices.OWN_VOICE_DOMAIN)
        )
    assert open_one is not None
    await healer_jobs._detect_voice_domains(healer_jobs._FleetFindings(), tally)
    async with untenanted_session() as session:
        assert (
            await incidents.open_for(
                session, incidents.dedupe_key("voice_domain_outage", voices.OWN_VOICE_DOMAIN)
            )
            is None
        )


def test_the_call_objective_pages_on_a_fast_burn_and_tickets_a_slow_one() -> None:
    counts = healer_watch.ObjectiveCounts()
    fast_long, fast_short, slow_long, slow_short = healer_watch.objective_windows()
    for minutes in (fast_long, fast_short, slow_long, slow_short):
        counts.calls[("fleet", minutes)] = 100
        counts.heard[("fleet", minutes)] = 20  # 20% against a 1% budget: 20 times
    burns = healer_watch.burning(counts)
    assert [b.fast for b in burns if b.group == "fleet"] == [True]
    calm = healer_watch.ObjectiveCounts()
    for minutes in (fast_long, fast_short, slow_long, slow_short):
        calm.calls[("fleet", minutes)] = 100
        calm.heard[("fleet", minutes)] = 8  # 8 times: over the slow rate, under the fast
    assert [b.fast for b in healer_watch.burning(calm)] == [False]


# --- billing on the voice that spoke --------------------------------------------------------


def test_the_platforms_billing_names_the_rate_a_call_ran_on() -> None:
    assert rate_key_ran("voice", None) == "byok_voice"
    assert rate_key_ran("llm_voice", None) == "byok_llm_voice"
    assert rate_key_ran("llm", "studio") == "studio"
    assert rate_key_ran("off", "premium") == "premium"
    assert rate_key_ran("all", None) is None


async def test_a_call_that_began_before_a_switch_is_billed_on_the_voice_that_spoke() -> None:
    tenant_id, agent_id = await _agent("bill", STUDIO)
    call_id = await _call(tenant_id, agent_id, ago=timedelta(minutes=30))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, engine_rate_key, created_at, updated_at) VALUES ('thinnest', :r, :t, :a, "
                "true, 'studio', now() - interval '1 day', now())"
            ),
            {"r": f"bill_{agent_id.hex}", "t": tenant_id, "a": agent_id},
        )
        moved = await engine_minute_cost(
            session,
            engine="thinnest",
            tenant_id=tenant_id,
            call_id=call_id,
            seconds=Decimal(60),
            at=datetime.now(UTC),
            ran_keys="llm_voice",
        )
        assert moved.rate_key == "byok_llm_voice" and moved.client_rate_key == "byok_llm_voice"
        await session.execute(
            text(
                "UPDATE engine_agent_routes SET updated_at = now() - interval '1 day' "
                "WHERE agent_id = :a"
            ),
            {"a": agent_id},
        )
        unmoved = await engine_minute_cost(
            session,
            engine="thinnest",
            tenant_id=tenant_id,
            call_id=call_id,
            seconds=Decimal(60),
            at=datetime.now(UTC),
            ran_keys="llm_voice",
        )
    # The route did not move after the call began: its key stands (a key of ours gone at
    # the start still shows as a mismatch in the charge comparison).
    assert unmoved.rate_key == "studio"


# --- the publish watch, summaries, notices ---------------------------------------------------


async def test_a_drop_after_a_script_publish_proposes_going_back() -> None:
    from apps.api.agents import script_builder
    from calevate_shared.call_script import CallScript, ConversationStage

    tenant_id, agent_id = await _agent("publish", CLEAR)

    def script(words: str) -> CallScript:
        return CallScript(
            schema_version=2,
            opening_line="Namaste, this is Asha from Sunrise Homes.",
            stages=[ConversationStage(id="need", name="Their need", instruction=words)],
        )

    async with tenant_session(tenant_id) as session:
        await script_builder.clear_draft(session, agent_id)
        for words in ("Ask what they need.", "Ask what they need today, briefly."):
            await script_builder.save_agent_script(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                script=script(words),
                notes="test",
                created_by=None,
            )
        published = (
            await session.execute(
                text(
                    "SELECT pv.created_at FROM agents a JOIN prompt_versions pv ON pv.id = "
                    "COALESCE(a.live_prompt_id, a.system_prompt_id) WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one()
        for n in range(10):
            await session.execute(
                text(
                    "INSERT INTO agent_health_windows (id, tenant_id, agent_id, window_start, "
                    "calls, short_calls, failed_calls, slow_starts, escalations, "
                    "knowledge_misses, action_failures, language_misses, score, deviating, "
                    "created_at, updated_at) VALUES (:id, :t, :a, :w, 4, 0, 0, 0, 0, 0, 0, 0, "
                    "95, false, now(), now())"
                ),
                {
                    "id": uuid7(),
                    "t": tenant_id,
                    "a": agent_id,
                    "w": published - timedelta(days=1, minutes=15 * n),
                },
            )
    for _ in range(5):
        await _call(tenant_id, agent_id, quality='{"turns": 0}', ago=timedelta(seconds=1))
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET created_at = now() WHERE agent_id = :a"), {"a": agent_id}
        )
        drops = await healer_watch.publish_watch(
            session, tenant_id=tenant_id, now=datetime.now(UTC) + timedelta(minutes=1)
        )
        again = await healer_watch.publish_watch(
            session, tenant_id=tenant_id, now=datetime.now(UTC) + timedelta(minutes=1)
        )
    assert [d.agent_id for d in drops] == [agent_id] and drops[0].proposed
    assert again == []


def test_the_incident_summary_is_written_from_the_ledger() -> None:
    opened = datetime(2026, 11, 12, 17, 30, tzinfo=UTC)
    steps = [
        ledger.ActionRow(
            id=uuid7(),
            at=opened + timedelta(minutes=1),
            incident_id=None,
            playbook="voice_fallback",
            step="act",
            outcome="ok",
            attempt=1,
            tenant_id=None,
            agent_id=None,
            alarm_code=None,
            detail="moved from engine:a (clear) to byok:b",
            actor_type="healer",
        )
    ]
    summary = healer_watch.summary_of(
        trigger_code="agent_voice_failed",
        playbook="voice_fallback",
        automatic=True,
        attempts=1,
        last_outcome="verified",
        escalated=False,
        opened_at=opened,
        resolved_at=opened + timedelta(hours=2),
        steps=steps,
    )
    assert "23:00 IST" in summary and "23:01 IST" in summary
    assert "moved from engine:a" in summary and "2 h 0 min" in summary
    assert summary == healer_watch.summary_of(
        trigger_code="agent_voice_failed",
        playbook="voice_fallback",
        automatic=True,
        attempts=1,
        last_outcome="verified",
        escalated=False,
        opened_at=opened,
        resolved_at=opened + timedelta(hours=2),
        steps=steps,
    )


async def test_a_resolved_incident_gets_its_summary(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    tenant_id, agent_id = await _agent("summary", CLEAR)
    _backups(monkeypatch, [])
    await _open(tenant_id, agent_id)
    incident = await _step(agent_id)
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE heal_incidents SET state = 'resolved', resolved_at = now() WHERE id = :i"),
            {"i": incident.id},
        )
    from collections import Counter

    await healer_jobs._summarize_resolved(Counter())
    async with untenanted_session() as session:
        found = await incidents.read_incident(session, incident.id)
    assert found is not None and found.summary and "Timeline:" in found.summary


def test_the_owners_voice_notices_name_nothing_internal() -> None:
    for state, outcome in (("open", None), ("resolved", None), ("resolved", "stood_down")):
        notice = notices.voice_notice(name="Your agent", state=state, outcome=outcome)
        for words in (notice.headline, notice.what_happened, notice.what_we_did, notice.your_part):
            lowered = words.lower()
            assert words and "_" not in words
            assert not any(
                w in lowered for w in ("cartesia", "thinnest", "healer", "incident", "byok")
            )


def test_the_provider_status_is_read_in_our_words() -> None:
    assert read_summary({"status": {"indicator": "none"}}).operational is True
    assert read_summary({"status": {"indicator": "major"}}).operational is False
    assert read_summary({"status": {"indicator": "weird"}}).operational is None
    assert read_summary(None).reachable is False


# --- tenancy and the migration --------------------------------------------------------------


async def test_a_tenant_reads_only_its_own_voice_rows(
    monkeypatch: pytest.MonkeyPatch, pages: list[str], mover: _Mover
) -> None:
    first, first_agent = await _agent("rls-a", CLEAR)
    second, second_agent = await _agent("rls-b", CLEAR)
    _backups(monkeypatch, [STUDIO])
    for tenant_id, agent_id in ((first, first_agent), (second, second_agent)):
        await _open(tenant_id, agent_id)
        await _step(agent_id)
    for table in ("agent_voice_history", "agent_voice_switches"):
        async with tenant_session(first) as session:
            mine = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            theirs = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"),
                    {"t": second},
                )
            ).scalar()
        assert mine == 1 and theirs == 0, table
        async with untenanted_session() as session:
            unscoped = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = ANY(:t)"),
                    {"t": [first, second]},
                )
            ).scalar()
        assert unscoped == 0, table


STEM = "d7f3a9c1e5b2_voice_fallback"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_goes_down_and_up() -> None:
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    exists = text(
        "SELECT to_regclass('agent_voice_switches') IS NOT NULL AND EXISTS (SELECT 1 FROM "
        "information_schema.columns WHERE table_name = 'calls' AND column_name = "
        "'ended_before_agent')"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    assert connection.execute(exists).scalar() is False
                    revision.upgrade()
                    assert connection.execute(exists).scalar() is True
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
