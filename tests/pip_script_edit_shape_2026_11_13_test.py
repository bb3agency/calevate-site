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

import pytest
from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers.script_assist import (
    REPAIR_NOTE,
    SHAPE_PROBLEM,
    AskTrace,
    ScriptBrief,
    ask_json,
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
