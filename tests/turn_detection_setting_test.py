"""How agents know the caller has finished: a console setting for ThinnestAI's `turnDetection`
(D-849), `timer` by default, with Ear's spoken acknowledgements sent only under `ear`."""

from __future__ import annotations

import pytest
from apps.api.agents import prompts
from apps.api.agents.call_handling import turn_detection_of
from apps.api.agents.service import _load_agent, _to_config
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.ops.config_catalog import CONTROL_HINTS
from apps.api.ops.config_service import validated_value
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.call_handling_test import _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import _cfg


def _voice(**update: object) -> dict[str, object]:
    voice: dict[str, object] = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(**update))[
        "voice"
    ]
    return voice


def test_timer_is_the_default_and_sends_no_ear_field() -> None:
    voice = _voice()
    assert voice["turnDetection"] == "timer"
    assert "acknowledgements" not in voice


@pytest.mark.parametrize("spoken", [True, False])
def test_ear_sends_the_acknowledgements_switch(spoken: bool) -> None:
    voice = _voice(turn_detection="ear", acknowledgements=spoken)
    assert (voice["turnDetection"], voice["acknowledgements"]) == ("ear", spoken)


def test_a_mode_or_switch_changed_in_the_vendor_console_is_drift() -> None:
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(
        _cfg(turn_detection="ear", acknowledgements=True)
    )
    for held in ({"turnDetection": "timer"}, {"acknowledgements": False}):
        live = {**body, "voice": {**body["voice"], **held}}
        assert thinnest._settings_drift(body, live) == ["turn_silence"]
    assert thinnest._settings_drift(body, body) == []


def test_the_console_takes_only_the_three_modes_and_republishes_live_agents() -> None:
    assert get_settings().thinnest_turn_detection == "timer"
    assert get_settings().thinnest_acknowledgements is True
    assert validated_value("thinnest_turn_detection", "ear") == "ear"
    with pytest.raises(ProblemError):
        validated_value("thinnest_turn_detection", "fast")
    for key in ("thinnest_turn_detection", "thinnest_acknowledgements"):
        assert applies_rule(key).applies == LIVE_AGENTS


async def test_publish_reads_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, _headers = await _tenant()
    monkeypatch.setattr(get_settings(), "thinnest_turn_detection", "ear")
    monkeypatch.setattr(get_settings(), "thinnest_acknowledgements", False)
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and take their order.",
            notes=None,
            created_by=None,
        )
        cfg = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
    assert (cfg.turn_detection, cfg.acknowledgements) == ("ear", False)
    assert "turn_detection" not in cfg.model_dump()


# --- Timer v2 (D-940) -------------------------------------------------------------------


def test_timer_v2_sends_neither_the_pause_nor_an_ear_field() -> None:
    """`turnSilenceSeconds` is not used by `timer_v2` (snapshots/2026-10-29/pages/
    api-reference/agents/update-agent.md:1470-1476), so it is not sent; Ear's own fields
    stay Ear's."""
    voice = _voice(turn_detection="timer_v2", acknowledgements=True)
    assert voice["turnDetection"] == "timer_v2"
    assert "turnSilenceSeconds" not in voice
    assert "acknowledgements" not in voice
    assert "turnSilenceSeconds" in _voice(turn_detection="timer")


def test_timer_v2_drift_is_the_mode_and_never_the_unused_pause() -> None:
    body = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(turn_detection="timer_v2"))
    held_pause = {**body, "voice": {**body["voice"], "turnSilenceSeconds": 1.7}}
    assert thinnest._settings_drift(body, held_pause) == []
    moved = {**body, "voice": {**body["voice"], "turnDetection": "timer"}}
    assert thinnest._settings_drift(body, moved) == ["turn_silence"]


def test_the_console_and_the_column_reader_take_timer_v2() -> None:
    assert validated_value("thinnest_turn_detection", "timer_v2") == "timer_v2"
    assert turn_detection_of("timer_v2") == "timer_v2"
    offered = {option.value for option in CONTROL_HINTS["thinnest_turn_detection"].options}
    assert offered == {"timer", "ear", "smart", "timer_v2"}
    assert get_settings().thinnest_turn_detection == "timer"


async def test_the_column_holds_timer_v2_and_refuses_an_unknown_mode() -> None:
    tenant_id, agent_id, _headers = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and take their order.",
            notes=None,
            created_by=None,
        )
        await session.execute(
            text("UPDATE agents SET turn_detection = 'timer_v2' WHERE id = :id"), {"id": agent_id}
        )
        cfg = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
        assert cfg.turn_detection == "timer_v2"
        with pytest.raises(IntegrityError, match="turn_detection"):
            await session.execute(
                text("UPDATE agents SET turn_detection = 'timer_v3' WHERE id = :id"),
                {"id": agent_id},
            )
