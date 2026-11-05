"""Every edit an owner can make by hand on the Script tab also works by asking Pip.

The hand edits are read from the Script tab (`ScriptBuilder.tsx`: add, delete and move a step;
`SectionEditor.tsx`: name, guided or exact words, instruction, line, ways out, where it goes
next, details, small steps; `ScriptParts`/`OpeningEditor`: the opening lines, why it calls,
the ending and the rest). Each goes through Pip's edit path, `draft_script(edit_of=...,
change=...)`, with the model replaced at its one seam (`chat.complete`): the edit writer, the
merge, the checks and the repair must keep the change rather than undo it. Lines are English.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any

import pytest
from apps.api.agents.script_lint import CapabilityManifest
from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers.script_assist import EDIT_INSTRUCTION, ScriptBrief, draft_script
from calevate_shared.call_script import (
    CallScript,
    ConversationStage,
    ProcedureStep,
    StageBranch,
)

CURRENT = CallScript(
    schema_version=2,
    opening_line="Hello, this is Asha from Acme Seeds. Can we talk now?",
    outbound_purpose="Calling to check the seed order reached them.",
    ending="Thank them and say goodbye.",
    stages=[
        ConversationStage(
            id="ask",
            name="Ask",
            instruction="Ask if the order arrived.",
            sounds_like="Did the seeds arrive?",
        ),
        ConversationStage(
            id="help",
            name="Help",
            instruction="Answer their questions about sowing.",
            sounds_like="Sow them two inches deep.",
        ),
        ConversationStage(
            id="tips",
            name="Tips",
            instruction="Give one watering tip.",
            sounds_like="Water them every morning.",
        ),
        ConversationStage(
            id="close",
            name="Close",
            instruction="Thank them and say goodbye.",
            sounds_like="Thank you, goodbye.",
        ),
    ],
)
BRIEF = ScriptBrief(
    description="A seed shop that calls its buyers.",
    business_name="Acme Seeds",
    agent_name="Asha",
    business_type="retail",
    direction="outbound",
    language="en-IN",
    capabilities=CapabilityManifest(direction="outbound"),
)


@pytest.fixture(autouse=True)
def model_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)


def _model_answers(monkeypatch: pytest.MonkeyPatch, script: CallScript) -> list[str]:
    seen: list[str] = []

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **_: Any) -> chat.ChatOutcome:
        seen.extend(str(m.get("content", "")) if isinstance(m, dict) else str(m) for m in messages)
        body = script.model_dump(mode="json", exclude={"raw_override"})
        return chat.ChatOutcome(content=json.dumps(body), finish_reason="stop")

    monkeypatch.setattr(chat, "complete", _complete)
    return seen


def _stage(script: CallScript, sid: str) -> ConversationStage:
    return next(s for s in script.stages if s.id == sid)


def _with_stage(sid: str, **update: Any) -> CallScript:
    return CURRENT.model_copy(
        update={
            "stages": [s.model_copy(update=update) if s.id == sid else s for s in CURRENT.stages]
        }
    )


OPENING = "Hello {{lead_name}}, Asha from Acme Seeds here, is now a good time?"
NEW = ConversationStage(
    id="area",
    name="Area",
    instruction="Ask which village they farm in.",
    sounds_like="Which village is your farm in?",
)

#: (change the owner asks for, the script the model returns, what must hold after the edit)
CAPABILITIES: dict[str, tuple[str, CallScript, Callable[[CallScript], bool]]] = {
    "add a step": (
        "Add a step after Ask that asks their village.",
        CURRENT.model_copy(update={"stages": [CURRENT.stages[0], NEW, *CURRENT.stages[1:]]}),
        lambda s: [x.id for x in s.stages] == ["ask", "area", "help", "tips", "close"],
    ),
    "delete a step": (
        "Delete the Tips step.",
        CURRENT.model_copy(update={"stages": [s for s in CURRENT.stages if s.id != "tips"]}),
        lambda s: [x.id for x in s.stages] == ["ask", "help", "close"],
    ),
    "rename a step": (
        "Call the Help step Sowing help.",
        _with_stage("help", name="Sowing help"),
        lambda s: _stage(s, "help").name == "Sowing help",
    ),
    "move a step": (
        "Give the tip before answering questions.",
        CURRENT.model_copy(
            update={
                "stages": [
                    CURRENT.stages[0],
                    CURRENT.stages[2],
                    CURRENT.stages[1],
                    CURRENT.stages[3],
                ]
            }
        ),
        lambda s: [x.id for x in s.stages] == ["ask", "tips", "help", "close"],
    ),
    "exact words": (
        "Make the Ask step say exactly: Did the seeds reach you?",
        _with_stage("ask", mode="say", instruction="Did the seeds reach you?"),
        lambda s: (
            _stage(s, "ask").mode == "say"
            and _stage(s, "ask").instruction == "Did the seeds reach you?"
        ),
    ),
    "instruction": (
        "In Help, answer questions about sowing and watering.",
        _with_stage("help", instruction="Answer their questions about sowing and watering."),
        lambda s: "watering" in _stage(s, "help").instruction,
    ),
    "example line": (
        "Change the Tips line.",
        _with_stage("tips", sounds_like="Water them early every morning."),
        lambda s: _stage(s, "tips").sounds_like == "Water them early every morning.",
    ),
    "where it goes next": (
        "After Ask, go straight to the close.",
        _with_stage("ask", otherwise="close"),
        lambda s: _stage(s, "ask").otherwise == "close",
    ),
    "a way out": (
        "If the order has not arrived, go to the close.",
        _with_stage(
            "ask", branches=[StageBranch(when="the order has not arrived", target="close")]
        ),
        lambda s: (
            _stage(s, "ask").branches
            == [StageBranch(when="the order has not arrived", target="close")]
        ),
    ),
    "what it collects": (
        "Collect the delivery date in Ask.",
        _with_stage("ask", collect=["Delivery date"]),
        lambda s: _stage(s, "ask").collect == ["Delivery date"],
    ),
    "small steps": (
        "Walk them through opening the order message.",
        _with_stage(
            "help",
            procedure=[ProcedureStep(action="Open your messages.", wait_for="they say it is open")],
        ),
        lambda s: [p.action for p in _stage(s, "help").procedure] == ["Open your messages."],
    ),
    "opening line": (
        "Open with the name, then: Asha from Acme Seeds here, is now a good time?",
        CURRENT.model_copy(update={"opening_line": OPENING}),
        lambda s: s.opening_line == OPENING,
    ),
    "why calling": (
        "Say we call to check the order and help with sowing.",
        CURRENT.model_copy(
            update={"outbound_purpose": "Calling to check the order and help with sowing."}
        ),
        lambda s: s.outbound_purpose == "Calling to check the order and help with sowing.",
    ),
    "the close": (
        "End by wishing them a good harvest.",
        _with_stage("close", sounds_like="Thank you, have a good harvest."),
        lambda s: _stage(s, "close").sounds_like == "Thank you, have a good harvest.",
    ),
}


@pytest.mark.parametrize("capability", list(CAPABILITIES))
async def test_pip_makes_each_hand_edit(monkeypatch: pytest.MonkeyPatch, capability: str) -> None:
    change, answer, holds = CAPABILITIES[capability]
    _model_answers(monkeypatch, answer)
    draft = await draft_script(BRIEF, edit_of=CURRENT, change=change)
    assert draft.script is not None
    assert holds(draft.script), capability


def test_the_edit_writer_is_told_each_hand_edit_and_only_when_asked() -> None:
    for words in (
        "add a step, delete one, rename one",
        "move one (change its place in the list, keep its id)",
        'exact words\n(mode "say")'.replace("\n", " "),
        "Do each only when the change asks for it",
        "leave it out of `stages` entirely",
        'never keep a step the change removes with an instruction like "Not needed"',
        "reached through a way out whose `when` says which callers",
    ):
        assert words in EDIT_INSTRUCTION, words
