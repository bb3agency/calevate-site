"""Knowledge search on calls, the opening wait as Get Agent reports it, and the pause under
each turn mode (D-903, from ThinnestAI's email of 27 Oct 2026).

`knowledgeOnCalls` is stated on every publish of the built-in tools, read back by the publish
and compared and repaired by the settings sweep. Get Agent reports `voice.openingWaitSeconds`
as the number a call uses, so an unstated wait reads 4 and is in step. Under `ear` the pause is
not read, and the screens say so; an agent an operator puts on the timer starts from the
console's `thinnest_timer_turn_silence_ms`.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from apps.api.agents import prompts
from apps.api.agents.call_handling import (
    TURN_SILENCE_DEFAULT_MS,
    CallSettings,
    platform_turn_silence_ms,
    resolve_settings,
    resolve_turn_silence,
)
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.agents.service import _call_settings_fields, _load_agent, _to_config
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest
from apps.api.engine.hosted_platform import THINNEST_LIMITS
from apps.api.engine.thinnest import BASE_URL, ThinnestEngine
from apps.api.ops.config_service import validated_value
from sqlalchemy import text
from tests.call_handling_test import _client, _make_live, _operator, _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import WS, _cfg, tools_state

pytestmark = [pytest.mark.rls]

AGENT = f"ag_1@{WS}"


def _engine(
    handler: Any,
) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


# --- knowledge search on calls --------------------------------------------------------------


def test_every_publish_states_knowledge_search_from_where_the_facts_live() -> None:
    held_as_knowledge = _cfg(
        facts_in_knowledge=THINNEST_LIMITS.facts_in_knowledge,
        knowledge_tool=THINNEST_LIMITS.knowledge_tool,
    )
    assert ThinnestEngine.built_in_tools_body(held_as_knowledge)["knowledgeOnCalls"] is True
    in_prompt = _cfg(facts_in_knowledge=False, knowledge_tool=None)
    assert ThinnestEngine.built_in_tools_body(in_prompt)["knowledgeOnCalls"] is False


async def test_a_publish_the_vendor_saved_without_the_switch_is_refused() -> None:
    cfg = _cfg(facts_in_knowledge=True, knowledge_tool="search_knowledge")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state({"knowledgeOnCalls": False}))
        return httpx.Response(200, json={"id": "ag_1"})

    with pytest.raises(ProblemError) as refused:
        await _engine(handler).update_agent(AGENT, cfg)
    assert refused.value.code == "engine_tools_not_pinned"


async def test_a_switch_turned_off_in_the_console_is_drift_and_repaired() -> None:
    cfg = _cfg(facts_in_knowledge=True, knowledge_tool="search_knowledge")
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    sent: list[tuple[str, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/tools"):
            if request.method == "PATCH":
                sent.append((request.url.path, body))
                return httpx.Response(200, json=tools_state(body))
            held = {"knowledgeOnCalls": False, "recall": "verified"}
            return httpx.Response(200, json=tools_state(held))
        if request.method == "GET":
            return httpx.Response(200, json=wanted)
        sent.append((request.url.path, body))
        return httpx.Response(200, json={})

    engine = _engine(handler)
    drifted = await engine.settings_drift(AGENT, cfg)
    assert drifted == ["knowledge_on_calls"]
    assert set(drifted) <= AGENT_SETTING_LABELS
    await engine.repair_settings(AGENT, cfg, drifted)
    # Only the tools route is written; the agent body is left alone.
    assert [path for path, _ in sent] == ["/api/v1/agents/ag_1/tools"]
    assert sent[0][1]["knowledgeOnCalls"] is True


def test_an_answer_without_the_field_is_drift() -> None:
    wanted = ThinnestEngine.built_in_tools_body(_cfg(facts_in_knowledge=True))
    held = tools_state(wanted)
    del held["knowledgeOnCalls"]
    assert thinnest._tools_drift(wanted, held) == ["knowledgeOnCalls"]


# --- the opening wait as Get Agent reports it -----------------------------------------------


def _with_wait(body: dict[str, Any], seconds: object) -> dict[str, Any]:
    return {**body, "voice": {**body["voice"], "openingWaitSeconds": seconds}}


def test_an_unstated_wait_reads_back_as_four_and_is_in_step() -> None:
    wanted = ThinnestEngine(api_key="x")._agent_body(_cfg(opening_waits_for_caller=True))
    assert "openingWaitSeconds" not in wanted["voice"]
    assert thinnest._settings_drift(wanted, _with_wait(wanted, 4)) == []
    assert thinnest._settings_drift(wanted, _with_wait(wanted, 4.0)) == []
    assert thinnest._settings_drift(wanted, wanted) == []
    # A wait somebody set that no publish asks for.
    assert thinnest._settings_drift(wanted, _with_wait(wanted, 2.5)) == ["opening_wait"]


def test_a_stated_wait_is_compared_to_a_tenth_and_ignored_with_the_switch_off() -> None:
    engine = ThinnestEngine(api_key="x")
    wanted = engine._agent_body(_cfg(opening_waits_for_caller=True, opening_wait_ms=1500))
    assert thinnest._settings_drift(wanted, _with_wait(wanted, 1.5)) == []
    assert thinnest._settings_drift(wanted, _with_wait(wanted, 1.50)) == []
    assert thinnest._settings_drift(wanted, _with_wait(wanted, 4)) == ["opening_wait"]
    assert thinnest._settings_drift(wanted, _with_wait(wanted, None)) == ["opening_wait"]
    off = engine._agent_body(_cfg(opening_wait_ms=1500))
    assert thinnest._settings_drift(off, _with_wait(off, 7)) == []


async def test_a_repair_of_an_unstated_wait_sends_the_vendor_default() -> None:
    cfg = _cfg(opening_waits_for_caller=True)
    wanted = ThinnestEngine(api_key="x")._agent_body(cfg)
    sent: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state(engine.built_in_tools_body(cfg)))
        if request.method == "GET":
            return httpx.Response(200, json=_with_wait(wanted, 3))
        sent.append(json.loads(request.content or b"{}"))
        return httpx.Response(200, json={})

    engine = _engine(handler)
    drifted = await engine.settings_drift(AGENT, cfg)
    assert drifted == ["opening_wait"]
    await engine.repair_settings(AGENT, cfg, drifted)
    assert sent == [{"voice": {"openingWaitSeconds": None}}]


# --- the pause under each turn mode ---------------------------------------------------------


def test_the_timer_trial_pause_is_a_console_value_that_republishes() -> None:
    assert get_settings().thinnest_timer_turn_silence_ms == 400
    assert validated_value("thinnest_timer_turn_silence_ms", 350) == 350
    for bad in (150, 3500):
        with pytest.raises(ProblemError):
            validated_value("thinnest_timer_turn_silence_ms", bad)
    assert applies_rule("thinnest_timer_turn_silence_ms").applies == LIVE_AGENTS


def test_only_an_agent_put_on_the_timer_on_its_own_starts_from_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_turn_detection", "timer")
    assert platform_turn_silence_ms(None) == TURN_SILENCE_DEFAULT_MS
    assert platform_turn_silence_ms("ear") == TURN_SILENCE_DEFAULT_MS
    assert platform_turn_silence_ms("timer") == 400
    trial = resolve_turn_silence(None, None, own_turn_detection="timer")
    assert (trial.ms, trial.source) == (400, "platform")
    # The agent's or the account's own pause still wins.
    assert resolve_turn_silence(None, 600, own_turn_detection="timer").ms == 600
    assert resolve_turn_silence(300, 600, own_turn_detection="timer").ms == 300
    resolved = resolve_settings(CallSettings(), CallSettings(), own_turn_detection="timer")
    assert resolved.values.turn_silence_ms == 400
    row: Any = {"turn_detection": "timer"}
    assert _call_settings_fields(row, languages=("te-IN",))["turn_silence_ms"] == 400
    empty: Any = {}
    assert _call_settings_fields(empty, languages=("te-IN",))["turn_silence_ms"] == 250


async def test_publish_sends_the_trial_pause_and_still_sends_the_pause_under_ear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _headers = await _tenant()
    monkeypatch.setattr(get_settings(), "thinnest_turn_detection", "ear")
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet the caller and take their order.",
            notes=None,
            created_by=None,
        )
        on_ear = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
        await session.execute(
            text("UPDATE agents SET turn_detection = 'timer' WHERE id = :id"), {"id": agent_id}
        )
        on_timer = _to_config(
            tenant_id, await _load_agent(session, tenant_id, agent_id), engine=HostingEngine()
        )
    assert (on_ear.turn_detection, on_ear.turn_silence_ms) == ("ear", 250)
    assert (on_timer.turn_detection, on_timer.turn_silence_ms) == ("timer", 400)
    voice = ThinnestEngine(api_key="x")._agent_body(on_ear)["voice"]
    assert voice["turnSilenceSeconds"] == 0.25


async def test_the_screens_say_whether_the_pause_is_used_and_which_one_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_turn_detection", "ear")
    tenant_id, agent_id, owner = await _tenant()
    await _make_live(tenant_id, agent_id)
    operator = await _operator()
    turn = f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/turn-detection"
    handling = f"/v1/agents/{agent_id}/call-handling"
    async with _client() as client:
        on_ear = (await client.get(handling, headers=owner)).json()
        ear_turn = (await client.get(turn, headers=operator)).json()
        put = await client.put(turn, headers=operator, json={"turn_detection": "timer"})
        on_timer = (await client.get(handling, headers=owner)).json()
    assert on_ear["turn_silence_applies"] is False
    assert on_ear["turn_silence_ms_effective"] == 250
    assert on_ear["bounds"]["platform_turn_silence_ms"] == 250
    assert (ear_turn["turn_detection_effective"], ear_turn["turn_silence_applies"]) == (
        "ear",
        False,
    )
    assert put.status_code == 200, put.text
    assert (put.json()["turn_silence_ms_effective"], put.json()["turn_silence_source"]) == (
        400,
        "platform",
    )
    assert put.json()["turn_silence_applies"] is True
    assert on_timer["turn_silence_applies"] is True
    assert on_timer["turn_silence_ms_effective"] == 400
    assert on_timer["bounds"]["platform_turn_silence_ms"] == 400
