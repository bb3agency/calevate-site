"""How many words a caller must say to stop the agent: a console setting for ThinnestAI's
`voice.interruptWords` (founder, 23 Oct 2026), 2 by default, stated on every agent write and
repaired when it drifts."""

from __future__ import annotations

import pytest
from apps.api.agents import prompts
from apps.api.agents.service import _load_agent, _to_config
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest
from apps.api.engine.thinnest import PLATFORM_VOICE_VALUES, ThinnestEngine
from apps.api.ops.config_service import validated_value
from tests.call_handling_test import _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import _cfg


@pytest.mark.parametrize("words", [1, 2, 6])
def test_every_write_states_the_console_count(words: int) -> None:
    voice = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(interrupt_words=words))["voice"]
    assert voice["interruptWords"] == words
    assert "interruptWords" not in PLATFORM_VOICE_VALUES


def test_a_different_count_on_the_platform_is_drift() -> None:
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(interrupt_words=2))
    held = {**wanted, "voice": {**wanted["voice"], "interruptWords": 3}}
    assert thinnest._settings_drift(wanted, held) == ["interruptions"]


def test_the_console_defaults_to_two_takes_one_to_six_and_republishes_live_agents() -> None:
    assert get_settings().thinnest_interrupt_words == 2
    assert validated_value("thinnest_interrupt_words", 1) == 1
    for bad in (0, 7):
        with pytest.raises(Exception):  # noqa: B017 - the range refusal, whatever its class
            validated_value("thinnest_interrupt_words", bad)
    assert applies_rule("thinnest_interrupt_words").applies == LIVE_AGENTS


async def test_publish_reads_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, _headers = await _tenant()
    monkeypatch.setattr(get_settings(), "thinnest_interrupt_words", 1)
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
    assert cfg.interrupt_words == 1
    assert "interrupt_words" not in cfg.model_dump()
