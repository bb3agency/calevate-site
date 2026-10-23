"""Our call rules in place of ThinnestAI's default call rules (D-850).

`voice.callInstructions` REPLACES the engine's default call rules, about 1,675 characters read
on every turn (ThinnestAI's email of 21 Oct 2026, `docs/vendor/thinnest-replies-2026-10-12.md`
§23.0 item 3, and the live openapi.json of the same day). With the switch on, a default
sentence that our text does not carry is lost, so every one of them is mapped here to where it
now lives: the speaking rules the engine always adds (only those ThinnestAI named), one of our
composed prompt layers, or `CALL_INSTRUCTIONS`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from apps.api.agents import live_apply, prompts
from apps.api.agents.engine_settings import AGENT_SETTING_LABELS
from apps.api.agents.service import _load_agent, _to_config
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import LIVE_AGENTS, applies_rule
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine import thinnest
from apps.api.engine.thinnest import (
    BASE_URL,
    CALL_INSTRUCTIONS_FIELD,
    CALL_INSTRUCTIONS_MAX_CHARS,
    ThinnestEngine,
)
from calevate_shared import engine as shared_engine
from calevate_shared.engine import (
    CALL_INSTRUCTIONS,
    CONFIDENTIALITY_MARKER,
    TRUTHFUL_ANSWER_MARKER,
    compose_engine_prompt,
)
from tests.call_handling_test import _tenant
from tests.hosted_voice_fakes import HostingEngine
from tests.thinnest_engine_test import WS, _cfg, tools_state

AGENT = f"ag_1@{WS}"
REPLIES = Path(__file__).resolve().parents[1] / "docs" / "vendor" / "thinnest-replies-2026-10-12.md"

#: ThinnestAI's default call rules, sentence by sentence, verbatim (§23.0 item 3).
DEFAULT_CALL_RULES: tuple[str, ...] = (
    "You are speaking with this person on a phone call, out loud.",
    "Keep replies to one or two sentences.",
    "They cannot see anything you write, so never refer to lists, links, buttons or images.",
    "Write titles and abbreviations in full — say Doctor rather than Dr., Street rather than St.",
    "Never use brackets, bullet points or symbols: everything you write is read aloud exactly "
    "as written.",
    "If you need a moment to look something up, say so rather than going quiet.",
    "If you do not know, say so.",
    "Never state an address, a price, a duration, a reference number or a policy unless a tool "
    "has just told you it or it is in the information you were given.",
    "If you were not told, say you do not have it.",
    "Do not answer from general knowledge about how businesses like this usually work.",
    "How long something takes, what to bring, whether reminders are sent - these are facts "
    "about THIS business, and if you were not told them you do not have them.",
    "Only say something is booked, cancelled or confirmed if a tool has just told you it "
    "succeeded.",
    "If a tool failed or you did not call one, say you could not complete it.",
    "When a tool gives you a figure, say that figure and no other.",
    "Open differently each time.",
    "Never begin two turns in a row the same way, and never repeat a sentence you have already "
    "said.",
    "Acknowledge what they just said before you answer it.",
    "Ask ONE question per turn, never two.",
    "If you have two, ask the more useful one and keep the other for later.",
    "Never reply with only an acknowledgement and a question.",
    "Say one thing that shows you understood what they told you in between.",
    "Do not recite things they already know.",
    "If the booking is made, do not read it back again unless they ask.",
)

SPEAKING = "the speaking rules ThinnestAI always adds"
OURS = "our composed prompt"
LEAN = "CALL_INSTRUCTIONS"

#: Where each default sentence lives once ours replace them: (place, the words that say it).
#: Since D-856 every rule but the call frame is in our composed prompt, which the practice
#: chat reads too; two are turned round on purpose and say so.
COVERAGE: dict[str, tuple[tuple[str, str], ...]] = {
    DEFAULT_CALL_RULES[0]: ((LEAN, "You are on a phone call, speaking out loud"),),
    DEFAULT_CALL_RULES[1]: ((OURS, "One or two short sentences, then wait"),),
    DEFAULT_CALL_RULES[2]: ((LEAN, "never mention lists, links, buttons or images"),),
    DEFAULT_CALL_RULES[3]: ((SPEAKING, "titles and abbreviations in full"),),
    DEFAULT_CALL_RULES[4]: ((OURS, "No markdown, emoji, brackets"),),
    # Turned round: "say so rather than going quiet" put a "one second" filler before answers;
    # the engine speaks its own filler after two seconds of silence.
    DEFAULT_CALL_RULES[5]: ((OURS, "Never announce a search or a wait"),),
    DEFAULT_CALL_RULES[6]: (
        (OURS, "No answer after searching, or still unclear after two tries: say so"),
    ),
    DEFAULT_CALL_RULES[7]: (
        (OURS, "Never guess or add to a fact: a price, an offer, stock, an address"),
    ),
    DEFAULT_CALL_RULES[8]: (
        (OURS, "No answer after searching, or still unclear after two tries: say so"),
    ),
    DEFAULT_CALL_RULES[9]: ((OURS, "or how such businesses usually work"),),
    DEFAULT_CALL_RULES[10]: ((OURS, "how long something takes"),),
    DEFAULT_CALL_RULES[11]: ((OURS, "Never say anything is booked or done"),),
    DEFAULT_CALL_RULES[12]: ((OURS, "a failed one plainly"),),
    DEFAULT_CALL_RULES[13]: ((OURS, "Say a tool's figure exactly"),),
    DEFAULT_CALL_RULES[14]: ((OURS, "each turn begun differently"),),
    DEFAULT_CALL_RULES[15]: (
        (OURS, "each turn begun differently"),
        (OURS, "Never re-ask what they said or repeat a sentence."),
    ),
    # Replaced, not carried: an acknowledgement before the answer became "two kg noted" with
    # nothing noted on the calls of 21 Oct 2026 (D-849).
    DEFAULT_CALL_RULES[16]: ((OURS, "Lead with the answer"),),
    DEFAULT_CALL_RULES[17]: ((OURS, "One question a turn"),),
    DEFAULT_CALL_RULES[18]: ((OURS, "One question a turn"),),
    # Turned round: the agent read it as "skip the reaction" and asked "do you want to know the
    # price?" instead of reacting and saying it (calls of 20-22 Oct 2026).
    DEFAULT_CALL_RULES[19]: ((OURS, "React in a few words, then ask the next thing."),),
    DEFAULT_CALL_RULES[20]: ((OURS, "Read back what you heard and wait for a yes"),),
    DEFAULT_CALL_RULES[21]: ((OURS, "Never re-ask what they said or repeat a sentence."),),
    DEFAULT_CALL_RULES[22]: ((OURS, "Never re-ask what they said or repeat a sentence."),),
}


def _reply_23() -> str:
    text = REPLIES.read_text(encoding="utf-8")
    return text[text.index("## 23. ") : text.index("### 23.1 ")]


def test_the_default_rules_here_are_thinnestais_text_word_for_word() -> None:
    section = _reply_23()
    start = section.index('"You are speaking with this person')
    quoted = section[
        start + 1 : section.index('unless they ask."', start) + len("unless they ask.")
    ]
    assert " ".join(DEFAULT_CALL_RULES) == quoted


def _our_prompts() -> list[str]:
    """Our composed prompt in the shapes that change the lines relied on: facts in the
    engine's knowledge or in the prompt, a paying or a trial account, one or two languages."""
    return [
        compose_engine_prompt(
            _cfg(
                facts_in_knowledge=facts,
                knowledge_tool="search_knowledge" if facts else None,
                callbacks_offered=callbacks,
                languages_extra=extra,
            )
        )
        for facts in (True, False)
        for callbacks in (True, False)
        for extra in ([], ["en-IN"])
    ]


def test_every_default_call_rule_is_still_said_when_ours_replace_them() -> None:
    assert set(COVERAGE) == set(DEFAULT_CALL_RULES)
    named_by_thinnestai = _reply_23()
    prompts_ = _our_prompts()
    for sentence, places in COVERAGE.items():
        for place, words in places:
            if place == SPEAKING:
                assert words in named_by_thinnestai, sentence
            elif place == OURS:
                assert all(words in prompt for prompt in prompts_), sentence
            else:
                assert words in CALL_INSTRUCTIONS, sentence


def test_our_call_rules_are_shorter_and_fit_the_field() -> None:
    assert len(CALL_INSTRUCTIONS) < thinnest.ENGINE_DEFAULT_CALL_RULES_CHARS
    assert len(CALL_INSTRUCTIONS) <= CALL_INSTRUCTIONS_MAX_CHARS


def test_only_the_call_frame_is_left_for_calls_alone() -> None:
    """D-856: the practice chat never reads `CALL_INSTRUCTIONS`, so a rule kept there is a
    rule the tests never see; only the call frame stays, and it is never blank (blank puts
    the engine's own rules back)."""
    assert CALL_INSTRUCTIONS.strip()
    lean = [words for places in COVERAGE.values() for place, words in places if place == LEAN]
    assert lean == [
        "You are on a phone call, speaking out loud",
        "never mention lists, links, buttons or images",
    ]


def test_an_agent_that_answers_calls_says_who_it_is_when_asked() -> None:
    """An agent that answers calls also rings out (a trial test call, a call back); asked who
    is calling, it says who and why and asks if now is a good time (call of 22 Oct 2026)."""
    for direction in ("inbound", "both"):
        assert shared_engine.WHO_IS_CALLING_RULE in compose_engine_prompt(_cfg(direction=direction))
    assert shared_engine.WHO_IS_CALLING_RULE not in compose_engine_prompt(
        _cfg(direction="outbound")
    )


def test_the_switch_sends_ours_or_puts_the_defaults_back() -> None:
    engine = ThinnestEngine(api_key="ta_live_test")
    on = engine._agent_body(_cfg(engine_call_instructions=True))
    off = engine._agent_body(_cfg())
    assert on["voice"][CALL_INSTRUCTIONS_FIELD] == CALL_INSTRUCTIONS
    assert off["voice"][CALL_INSTRUCTIONS_FIELD] is None
    # The instructions themselves, and hard rule 5 / D-674 in them, do not move.
    assert on["instructions"] == off["instructions"]
    assert TRUTHFUL_ANSWER_MARKER in on["instructions"]
    assert CONFIDENTIALITY_MARKER in on["instructions"]


def _publishing_engine(answers: list[dict[str, Any]]) -> ThinnestEngine:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.url.path.endswith("/tools"):
            return httpx.Response(200, json=tools_state(body))
        return httpx.Response(200, json=answers.pop(0) if answers else {})

    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


async def test_a_publish_whose_answer_holds_other_call_rules_is_refused() -> None:
    held_defaults = {"voice": {CALL_INSTRUCTIONS_FIELD: None}}
    with pytest.raises(ProblemError) as refused:
        await _publishing_engine([held_defaults]).update_agent(
            AGENT, _cfg(engine_call_instructions=True)
        )
    assert refused.value.code == "engine_call_instructions_not_saved"
    held_ours = {"voice": {CALL_INSTRUCTIONS_FIELD: CALL_INSTRUCTIONS}}
    with pytest.raises(ProblemError):
        await _publishing_engine([held_ours]).update_agent(AGENT, _cfg())
    # Blank is the defaults, like null; an answer without the field is not compared.
    await _publishing_engine([{"voice": {CALL_INSTRUCTIONS_FIELD: ""}}]).update_agent(AGENT, _cfg())
    await _publishing_engine([{}]).update_agent(AGENT, _cfg(engine_call_instructions=True))


async def test_the_drift_sweep_reports_and_repairs_the_call_rules() -> None:
    assert "call_instructions" in AGENT_SETTING_LABELS
    cfg = _cfg(engine_call_instructions=True)
    wanted = ThinnestEngine(api_key="ta_live_test")._agent_body(cfg)
    sent: list[dict[str, Any]] = []
    held = {**wanted, "voice": {**wanted["voice"], CALL_INSTRUCTIONS_FIELD: None}}

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
    assert drifted == ["call_instructions"]
    await engine.repair_settings(AGENT, cfg, drifted)
    assert sent == [{"voice": {CALL_INSTRUCTIONS_FIELD: CALL_INSTRUCTIONS}}]
    off = ThinnestEngine(api_key="ta_live_test")._agent_body(_cfg())
    blank = {**off, "voice": {**off["voice"], CALL_INSTRUCTIONS_FIELD: ""}}
    assert thinnest._settings_drift(off, blank) == []


async def test_publish_reads_the_console_and_saving_it_republishes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert get_settings().thinnest_call_instructions is False
    assert applies_rule("thinnest_call_instructions").applies == LIVE_AGENTS
    tenant_id, agent_id, _headers = await _tenant()
    monkeypatch.setattr(get_settings(), "thinnest_call_instructions", True)
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
    assert cfg.engine_call_instructions is True
    assert "engine_call_instructions" not in cfg.model_dump()


def test_a_change_to_our_call_rules_republishes_every_live_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    before = live_apply.platform_prompt_revision()
    monkeypatch.setattr(shared_engine, "CALL_INSTRUCTIONS", f"{CALL_INSTRUCTIONS} Be brief.")
    assert live_apply.platform_prompt_revision() != before
