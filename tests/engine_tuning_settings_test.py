"""The adapter's wording temperature and filler timing are console settings, bounded by the
vendor's documented ranges (`update-agent.md:751-755`, `:1424-1444` of the 12 Nov 2026
snapshot), stated on every agent write, repaired when they drift, and republished when saved
or when a deploy moves their default."""

from __future__ import annotations

import pytest
from apps.api.agents import live_apply, prompts
from apps.api.agents.service import _load_agent, _to_config
from apps.api.agents.voice_stamp import stamp_of
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest
from apps.api.engine.hosted_platform import PLATFORM_AGENT_VALUES
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.ops.config_service import validated_value
from calevate_shared.config import Settings
from tests.call_handling_test import _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import _cfg

KEYS = (
    "thinnest_agent_temperature_tenths",
    "thinnest_thinking_delay_ms",
    "thinnest_thinking_repeat_ms",
)


def _body(**update: object) -> dict[str, object]:
    return ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg(**update))


def test_the_defaults_are_the_values_agents_were_published_with() -> None:
    settings = get_settings()
    assert settings.thinnest_agent_temperature_tenths == 3
    assert settings.thinnest_thinking_delay_ms == 2000
    assert settings.thinnest_thinking_repeat_ms == 2500
    body = _body()
    assert body["temperature"] == 0.3
    voice = body["voice"]
    assert isinstance(voice, dict)
    assert (voice["thinkingDelayMs"], voice["thinkingRepeatMs"]) == (2000, 2500)


@pytest.mark.parametrize(
    ("key", "inside", "outside"),
    [
        ("thinnest_agent_temperature_tenths", (0, 20), (-1, 21)),
        ("thinnest_thinking_delay_ms", (200, 5000), (199, 5001)),
        ("thinnest_thinking_repeat_ms", (1000, 10_000), (999, 10_001)),
    ],
)
def test_each_takes_the_vendors_range_and_republishes_live_agents(
    key: str, inside: tuple[int, int], outside: tuple[int, int]
) -> None:
    for good in inside:
        assert validated_value(key, good) == good
    for bad in outside:
        with pytest.raises(Exception):  # noqa: B017 - the range refusal, whatever its class
            validated_value(key, bad)
    assert applies_rule(key).applies == LIVE_AGENTS


def test_every_write_states_the_console_values() -> None:
    body = _body(temperature=1.2, thinking_delay_ms=400, thinking_repeat_ms=6000)
    voice = body["voice"]
    assert isinstance(voice, dict)
    assert body["temperature"] == 1.2
    assert (voice["thinkingDelayMs"], voice["thinkingRepeatMs"]) == (400, 6000)
    assert not {"thinkingDelayMs", "thinkingRepeatMs"} & set(thinnest.PLATFORM_VOICE_VALUES)
    assert "temperature" not in thinnest.PLATFORM_AGENT_FIELDS


def test_a_different_value_on_the_platform_is_drift() -> None:
    wanted = _body(thinking_delay_ms=2000)
    voice = wanted["voice"]
    assert isinstance(voice, dict)
    held = {**wanted, "voice": {**voice, "thinkingRepeatMs": 3000}}
    assert thinnest._settings_drift(wanted, held) == ["filler_timing"]
    assert thinnest._settings_drift(wanted, {**wanted, "temperature": 0.9}) == ["temperature"]


def test_the_fixed_values_stay_in_code() -> None:
    values = PLATFORM_AGENT_VALUES["thinnest"]
    assert values["greetingUninterruptible"] is True
    assert values["endPhrases"] == []
    assert values["recall"] == "verified"
    assert values["vocabulary"] == "none"


def test_a_deploy_that_moves_a_default_moves_the_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    before = live_apply.platform_prompt_revision()
    field = Settings.model_fields["thinnest_thinking_delay_ms"]
    monkeypatch.setattr(field, "default", 2100)
    assert live_apply.platform_prompt_revision() != before
    assert set(KEYS) <= set(live_apply.ENGINE_CONSOLE_DEFAULT_KEYS)


def test_the_voice_stamp_records_the_published_filler_delay() -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    assert stamp_of(_cfg(thinking_delay_ms=3000), engine)["filler_delay_ms"] == 3000


async def test_publish_reads_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, _headers = await _tenant()
    monkeypatch.setattr(get_settings(), "thinnest_agent_temperature_tenths", 5)
    monkeypatch.setattr(get_settings(), "thinnest_thinking_delay_ms", 1500)
    monkeypatch.setattr(get_settings(), "thinnest_thinking_repeat_ms", 4000)
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
    assert (cfg.temperature, cfg.thinking_delay_ms, cfg.thinking_repeat_ms) == (0.5, 1500, 4000)
    assert not {"temperature", "thinking_delay_ms", "thinking_repeat_ms"} & set(cfg.model_dump())
