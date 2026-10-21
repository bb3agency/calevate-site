"""How agents know the caller has finished: a console setting for ThinnestAI's `turnDetection`
(D-849), `timer` by default, with Ear's spoken acknowledgements sent only under `ear`."""

from __future__ import annotations

import pytest
from apps.api.agents import prompts
from apps.api.agents.service import _load_agent, _to_config
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.ops.config_service import validated_value
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
