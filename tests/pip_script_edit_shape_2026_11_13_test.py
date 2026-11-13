"""Pip's script change survives an answer in the wrong shape, and an edit is never handed to
the standby after the account's model answered.

Production, 13 Nov 2026 (23:16): the founder asked Pip for six changes to Varsha's script,
one of them "skip three steps and go to Purpose of usage". The paid leg answered (1,570
tokens) and our own reading of the answer raised TypeError. That counted as no answer: no
repair was asked, the Sarvam standby rewrote the whole Telugu script under its 4,096-token
ceiling and was cut off, and the owner read "This change was too big for Pip to write in one
go". Now a value of the wrong type is left for validation to name, a reading that still
trips is sent back for repair like a broken rule, an edit the paid leg answered is never
rewritten by the standby, and "too big" is said only when no leg could finish.

The model is replaced at its one seam (`chat.complete`); the lines are English.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from apps.api.agents import script_proposals
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers import script_proposal as worker
from apps.workers.script_assist import (
    ANSWER_UNUSABLE_CODE,
    REPAIR_NOTE,
    SHAPE_PROBLEM,
    AskTrace,
    ScriptBrief,
    ask_json,
    draft_script,
    ways_to_kept_steps,
)
from calevate_shared.call_script import CallScript, ConversationStage

CURRENT = CallScript(
    schema_version=2,
    opening_line="Hello, this is Asha from Acme Seeds. Can we talk now?",
    goal="Help buyers with their seed orders.",
    stages=[
        ConversationStage(
            id="icon",
            name="Icon check",
            instruction="Ask if the app icon is on their phone.",
            sounds_like="Can you see our app on your phone?",
        ),
        ConversationStage(
            id="device",
            name="Device check",
            instruction="Ask which phone they have.",
            sounds_like="Which phone do you have?",
        ),
        ConversationStage(
            id="use",
            name="Purpose of usage",
            instruction="Ask what they use the app for.",
            sounds_like="What do you mostly use the app for?",
        ),
        ConversationStage(
            id="close", name="Close", instruction="Thank them.", sounds_like="Thank you, bye."
        ),
    ],
)
BRIEF = ScriptBrief(
    description="A seed shop.",
    business_name="Acme Seeds",
    agent_name="Asha",
    business_type="retail",
    direction="inbound",
    language="en-IN",
)
CHANGE = "If they can see the icon, skip the device question and go to how they use it."
WHEN = "They say the app is already on their phone"


def _answer(target: object) -> dict[str, Any]:
    body = CURRENT.model_dump(mode="json", exclude={"raw_override"})
    body["stages"][0]["branches"] = [{"when": WHEN, "target": target}]
    return body


class Model:
    """The paid leg answering each of `answers` in turn; `sarvam` counts the standby's asks,
    which answer a reply cut off at its ceiling (production's outcome)."""

    def __init__(self, *answers: dict[str, Any]) -> None:
        self.answers = list(answers)
        self.asked: list[list[Any]] = []
        self.sarvam = 0

    async def __call__(
        self, leg: chat.ChatLeg, messages: Sequence[Any], **_kw: Any
    ) -> chat.ChatOutcome:
        usage = chat.TokenUsage(prompt_tokens=6_000, output_tokens=1_500)
        if leg.dialect == "sarvam":
            self.sarvam += 1
            return chat.ChatOutcome(content='{"stages": [', finish_reason="length", usage=usage)
        self.asked.append(list(messages))
        answer = self.answers[min(len(self.asked) - 1, len(self.answers) - 1)]
        return chat.ChatOutcome(content=json.dumps(answer), finish_reason="stop", usage=usage)

    def note(self, n: int) -> str:
        return str(self.asked[n - 1][-1]["content"])


@pytest.fixture(autouse=True)
def model_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)


def test_a_list_of_steps_where_one_belongs_is_left_for_validation() -> None:
    """FAILS IF: a `target` or `otherwise` that is a list raises TypeError (it did, from a set
    lookup), or a way out to a step that is gone is no longer removed."""
    stages = [
        {
            "id": "a",
            "otherwise": ["b", "c"],
            "branches": [
                {"when": "x", "target": ["b", "c"]},
                {"when": "y", "target": "gone"},
                {"when": "z", "target": None},
                {"when": "w", "target": "b"},
            ],
        },
        {"id": "b", "otherwise": "gone"},
    ]
    kept = ways_to_kept_steps(stages)
    assert [b["target"] for b in kept[0]["branches"]] == [["b", "c"], "b"]
    assert kept[0]["otherwise"] == ["b", "c"]
    assert kept[1]["otherwise"] == ""


async def test_a_wrong_shaped_branch_is_repaired_not_handed_to_the_standby(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the production answer (a list of steps as one branch's target) skips the
    repair, or the standby is asked to rewrite the script."""
    fixed = _answer("use")
    model = Model(_answer(["device", "use"]), {"stages": [fixed["stages"][0]]})
    monkeypatch.setattr(chat, "complete", model)
    draft = await draft_script(BRIEF, edit_of=CURRENT, change=CHANGE, trace=AskTrace())
    assert len(model.asked) == 2
    assert model.sarvam == 0
    first = draft.script.stages[0]
    assert [(b.when, b.target) for b in first.branches] == [(WHEN, "use")]


async def test_a_reading_that_trips_is_sent_back_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAILS IF: an answer our own reading cannot handle counts as no answer (straight to the
    standby) instead of a repair, or that repair asks for named parts it cannot name."""
    good = {"line": "Thank you."}
    model = Model({"line": ["Thank", "you."]}, good)
    monkeypatch.setattr(chat, "complete", model)

    def parse(data: dict[str, Any]) -> str:
        return "".join(["said: ", data["line"]])

    answer = await ask_json("Say thanks.", "Answer in JSON.", parse=parse, trace=AskTrace())
    assert answer.value == "said: Thank you."
    assert model.sarvam == 0
    assert model.note(2) == REPAIR_NOTE.format(problems=SHAPE_PROBLEM)


async def test_an_edit_the_model_answered_is_not_rewritten_by_the_standby(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an edit still unusable after its repairs goes to the standby, whose cut-off
    then tells the owner the change was too big."""
    monkeypatch.setattr(get_settings(), "script_edit_repair_rounds", 1)
    broken = _answer(["device", "use"])
    model = Model(broken, broken)
    monkeypatch.setattr(chat, "complete", model)
    trace = AskTrace()
    with pytest.raises(ProblemError) as refused:
        await draft_script(BRIEF, edit_of=CURRENT, change=CHANGE, trace=trace)
    assert refused.value.code == ANSWER_UNUSABLE_CODE
    assert model.sarvam == 0
    assert len(model.asked) == 2
    assert not trace.truncated
    assert worker.refusal_note(refused.value, trace) != script_proposals.TOO_BIG_NOTE


async def test_the_repair_rounds_follow_the_console_setting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an edit's repair rounds are a constant rather than the console's number."""
    monkeypatch.setattr(get_settings(), "script_edit_repair_rounds", 3)
    broken = _answer(["device", "use"])
    model = Model(broken, broken, broken, broken)
    monkeypatch.setattr(chat, "complete", model)
    with pytest.raises(ProblemError):
        await draft_script(BRIEF, edit_of=CURRENT, change=CHANGE, trace=AskTrace())
    assert len(model.asked) == 4


async def test_a_new_script_still_falls_back_to_the_standby(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the edit rule stops a whole new script from reaching the standby when the
    paid leg cannot be reached."""

    async def down(leg: chat.ChatLeg, messages: Sequence[Any], **_kw: Any) -> chat.ChatOutcome:
        if leg.dialect == "sarvam":
            down.sarvam += 1  # type: ignore[attr-defined]
            raise httpx.ConnectError("standby down too")
        raise httpx.ConnectError("paid leg down")

    down.sarvam = 0  # type: ignore[attr-defined]
    monkeypatch.setattr(chat, "complete", down)
    with pytest.raises(ProblemError):
        await draft_script(BRIEF, trace=AskTrace())
    assert down.sarvam == 1  # type: ignore[attr-defined]
