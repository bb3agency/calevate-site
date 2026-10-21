"""Early answers: a console switch for ThinnestAI's `voice.earlyAnswers` (D-852), on by
default like the vendor's, stated on every agent write and repaired when it drifts."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from apps.api.agents import prompts
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.agents.service import _load_agent, _to_config
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.ops.config_catalog import meta_for
from tests.call_handling_test import _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import WS, _cfg, tools_state

AGENT = f"ag_1@{WS}"


@pytest.mark.parametrize("early", [True, False])
def test_every_write_states_the_switch_under_every_turn_mode(early: bool) -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    for mode in ("timer", "ear", "smart"):
        voice = engine._agent_body(_cfg(early_answers=early, turn_detection=mode))["voice"]
        assert voice["earlyAnswers"] is early


async def test_the_drift_sweep_reports_and_repairs_the_switch() -> None:
    assert "early_answers" in AGENT_SETTING_LABELS
    cfg = _cfg(early_answers=False)
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    held = {**wanted, "voice": {**wanted["voice"], "earlyAnswers": True}}
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state(engine.built_in_tools_body(cfg)))
        if request.method == "GET":
            return httpx.Response(200, json=held)
        sent.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={})

    engine = ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )
    drifted = await engine.settings_drift(AGENT, cfg)
    assert drifted == ["early_answers"]
    await engine.repair_settings(AGENT, cfg, drifted)
    assert sent == [{"voice": {"earlyAnswers": False}}]
    assert thinnest._settings_drift(wanted, wanted) == []


def test_the_console_defaults_to_the_vendor_default_and_republishes_live_agents() -> None:
    assert get_settings().thinnest_early_answers is True
    assert applies_rule("thinnest_early_answers").applies == LIVE_AGENTS
    assert "billed" in meta_for("thinnest_early_answers").description


async def test_publish_reads_the_console(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id, _headers = await _tenant()
    monkeypatch.setattr(get_settings(), "thinnest_early_answers", False)
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
    assert cfg.early_answers is False
    assert "early_answers" not in cfg.model_dump()
