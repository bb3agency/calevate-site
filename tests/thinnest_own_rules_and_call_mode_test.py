"""ThinnestAI's answer of 21 Oct 2026, built (D-847; `docs/vendor/thinnest-replies-2026-10-12.md`
§21). Every new request field is VENDOR-STATED and not in the 19 Oct docs, so each is sent only
behind a console switch that is off by default.

1. `ownRules`: sent only with `thinnest_own_rules` on; our prompt then carries the hand-over
   rule the vendor stops adding; read back when an answer states it, and switched off again
   only on a server whose answer showed the field.
2. Test Chat's call mode: `mode: "call"` only with `thinnest_test_chat_call_mode` on, the mode
   read back, a refusal for an agent not set up for calls in our words, and results of the two
   modes never compared.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from apps.api.agents import test_conversations, trial_results
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.agents.test_window import send_test_message
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.engine.test_chat import TEST_CALL_NOT_SET_UP, TEST_CHAT_UNAVAILABLE, TestChatTurn
from apps.api.engine.thinnest import BASE_URL, OWN_RULES_FIELD, ThinnestEngine
from apps.workers import agent_test_conversations as worker
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    OWN_RULES_HANDOVER_RULE,
    TRUTHFUL_ANSWER_MARKER,
    compose_engine_prompt,
)
from tests.thinnest_engine_test import WS, _cfg, tools_state

AGENT = f"ag_1@{WS}"


# --- 1. ownRules ---------------------------------------------------------------------------


def test_own_rules_is_sent_only_while_the_switch_is_on() -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    assert engine._agent_body(_cfg(engine_own_rules=True))[OWN_RULES_FIELD] is True
    assert OWN_RULES_FIELD not in engine._agent_body(_cfg())


def test_with_own_rules_our_prompt_states_when_to_hand_over_and_keeps_the_floor() -> None:
    """The vendor stops adding its hand-over rule, so ours says it: only on request, through
    the tool that is attached only while someone is on duty, never guessing instead; with no
    tool, nobody is free and the account's call-back rule applies. Hard rule 5 and D-674 stay
    whole."""
    off = compose_engine_prompt(_cfg())
    on = compose_engine_prompt(_cfg(engine_own_rules=True))
    assert OWN_RULES_HANDOVER_RULE in on and OWN_RULES_HANDOVER_RULE not in off
    assert on.replace(f"{OWN_RULES_HANDOVER_RULE}\n", "") == off
    assert "Asked for a person with no hand-over tool" in on
    assert "offer a call back" in on
    trial = compose_engine_prompt(_cfg(engine_own_rules=True, callbacks_offered=False))
    assert "Never offer or book a call back" in trial
    for prompt in (on, trial):
        assert TRUTHFUL_ANSWER_MARKER in prompt and CONFIDENTIALITY_MARKER in prompt
        assert prompt.index(OWN_RULES_HANDOVER_RULE) < prompt.index(CONFIDENTIALITY_MARKER)


def _publishing_engine(answers: list[dict[str, Any]], sent: list[dict[str, Any]]) -> ThinnestEngine:
    """Answers each agent PATCH with the next of `answers`, the tools route as saved."""

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state(body))
        sent.append(body)
        return httpx.Response(200, json=answers.pop(0) if answers else {})

    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


async def test_an_answer_not_holding_own_rules_refuses_the_publish() -> None:
    sent: list[dict[str, Any]] = []
    engine = _publishing_engine([{OWN_RULES_FIELD: False}], sent)
    with pytest.raises(ProblemError) as refused:
        await engine.update_agent(AGENT, _cfg(engine_own_rules=True))
    assert refused.value.code == "engine_own_rules_not_saved"


async def test_an_answer_that_does_not_state_own_rules_is_not_compared() -> None:
    sent: list[dict[str, Any]] = []
    await _publishing_engine([{}], sent).update_agent(AGENT, _cfg(engine_own_rules=True))
    assert [OWN_RULES_FIELD in body for body in sent] == [True]


async def test_switching_off_clears_own_rules_on_a_server_that_showed_the_field() -> None:
    """Off omits the field, which leaves what an earlier publish set; an answer still
    stating `true` proves the server knows the field, so `false` is sent and read back."""
    sent: list[dict[str, Any]] = []
    engine = _publishing_engine([{OWN_RULES_FIELD: True}, {OWN_RULES_FIELD: False}], sent)
    await engine.update_agent(AGENT, _cfg())
    assert OWN_RULES_FIELD not in sent[0]
    assert sent[1] == {OWN_RULES_FIELD: False}
    stuck = _publishing_engine([{OWN_RULES_FIELD: True}, {OWN_RULES_FIELD: True}], [])
    with pytest.raises(ProblemError) as refused:
        await stuck.update_agent(AGENT, _cfg())
    assert refused.value.code == "engine_own_rules_not_saved"


async def test_the_drift_sweep_reports_and_repairs_own_rules_only_from_a_stated_answer() -> None:
    assert "own_rules" in AGENT_SETTING_LABELS
    cfg = _cfg(engine_own_rules=True)
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    sent: list[dict[str, Any]] = []

    def engine_holding(agent: dict[str, Any]) -> ThinnestEngine:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/tools"):
                return httpx.Response(200, json=tools_state(engine.built_in_tools_body(cfg)))
            if request.method == "GET":
                return httpx.Response(200, json=agent)
            sent.append(json.loads(request.content or b"{}"))
            return httpx.Response(200, json={})

        engine = ThinnestEngine(
            api_key="ta_live_test",
            client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
        )
        return engine

    unstated = {k: v for k, v in wanted.items() if k != OWN_RULES_FIELD}
    assert "own_rules" not in await engine_holding(unstated).settings_drift(AGENT, cfg)
    switched_off = engine_holding({**wanted, OWN_RULES_FIELD: False})
    drifted = await switched_off.settings_drift(AGENT, cfg)
    assert drifted == ["own_rules"]
    await switched_off.repair_settings(AGENT, cfg, drifted)
    assert sent == [{OWN_RULES_FIELD: True}]


# --- 2. Test Chat's call mode ---------------------------------------------------------------


def _chat_engine(handler: Any) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


async def test_call_mode_is_asked_only_when_wanted_and_its_answer_is_read() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        answer = {"session": "vr_1", "reply": "ok", "tools": []}
        return httpx.Response(200, json={**answer, **({"mode": "call"} if "mode" in body else {})})

    engine = _chat_engine(handler)
    chat = await engine.test_chat("ag_9", "hello")
    call = await engine.test_chat("ag_9", "hello", call_mode=True)
    assert "mode" not in bodies[0] and bodies[1]["mode"] == "call"
    assert (chat.mode, call.mode) == ("chat", "call")


async def test_call_mode_not_confirmed_by_the_answer_is_unknown() -> None:
    engine = _chat_engine(
        lambda request: httpx.Response(200, json={"session": "vr_1", "reply": "ok", "tools": []})
    )
    assert (await engine.test_chat("ag_9", "hi", call_mode=True)).mode is None


@pytest.mark.parametrize(
    ("status", "code"), [(409, "calling_not_set_up"), (400, "calling_not_set_up"), (409, None)]
)
async def test_an_agent_not_set_up_for_calls_is_refused_in_our_words(
    status: int, code: str | None
) -> None:
    payload = {"error": "Set up calling on this agent first.", **({"code": code} if code else {})}
    engine = _chat_engine(lambda request: httpx.Response(status, json=payload))
    with pytest.raises(ProblemError) as refused:
        await engine.test_chat("ag_9", "hi", call_mode=True)
    assert refused.value.code == TEST_CALL_NOT_SET_UP
    words = f"{refused.value.title} {refused.value.detail} {refused.value.remediation}"
    assert "ThinnestAI" not in words and "Thinnest" not in words


async def test_a_409_in_chat_mode_keeps_its_meaning() -> None:
    engine = _chat_engine(lambda request: httpx.Response(409, json={"error": "off"}))
    with pytest.raises(ProblemError) as refused:
        await engine.test_chat("ag_9", "hi")
    assert refused.value.code == TEST_CHAT_UNAVAILABLE


class _ModeChat:
    def __init__(self, mode: str | None) -> None:
        self.asked: list[bool] = []
        self.mode = mode

    async def test_chat(
        self, ref: str, message: str, *, session: str | None = None, call_mode: bool = False
    ) -> TestChatTurn:
        self.asked.append(call_mode)
        return TestChatTurn(session="vr_1", reply="ok", tools=(), mode=self.mode)  # type: ignore[arg-type]


@pytest.mark.parametrize("on", [False, True])
async def test_every_test_message_asks_the_mode_the_console_switch_names(
    on: bool, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_test_chat_call_mode", on)
    fake = _ModeChat("call" if on else "chat")
    await send_test_message(fake, agent_id=uuid.uuid4(), engine_agent_ref="ag_9", message="hi")
    assert fake.asked == [on]


async def test_a_run_files_its_results_under_the_mode_its_turns_ran_in() -> None:
    async def _no_pause() -> None:
        return None

    scenario = test_conversations.Scenario(
        key="k", title="T", category="business", turns=("hi",), expect="E"
    )
    run_id = uuid.uuid4()
    for mode, channel in (
        ("call", "test_chat_call"),
        ("chat", "test_chat"),
        (None, "test_chat_call"),
    ):
        modes: set[Any] = set()
        await worker.talk(
            _ModeChat(mode),
            agent_id=uuid.uuid4(),
            engine_agent_ref="ag_9",
            scenarios=[scenario],
            pause=_no_pause,
            modes=modes,
        )
        assert worker.run_channel(modes, run_id=run_id) == channel


def test_results_of_the_two_modes_are_never_compared() -> None:
    def result(channel: str | None, verdict: str) -> dict[str, Any]:
        row: dict[str, Any] = {
            "key": "k",
            "verdict": verdict,
            "owner": "script" if verdict == "failed" else None,
            "fix": "script_step" if verdict == "failed" else None,
            "passes": 1 if verdict == "passed" else 0,
            "judged_tries": 1,
        }
        return row if channel is None else {**row, "channel": channel}

    before = [result(None, "passed")]
    assert trial_results.compare(before, [result("test_chat", "failed")]).changes == {"k": "broken"}
    assert trial_results.compare(before, [result("test_chat_call", "failed")]).changes == {
        "k": "new"
    }
    assert test_conversations.result_channel({"channel": "test_chat_call"}) == "test_chat_call"
    assert test_conversations.result_channel({}) == "test_chat"
