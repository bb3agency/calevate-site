"""Targeted edits (W3.7): an owner's free-form change rewrites only the places it names.

1. A free-form ask on a saved script is an `edit`; a request that lays out steps, a rewrite
   and a blank Generate are not.
2. The map is held to the script: unknown places dropped, a rule for every step fanned out
   to each step's lines only, a map that names nothing unusable.
3. Only the mapped steps and parts change; every other one is the saved one, byte for byte,
   whatever the writer answered elsewhere; each change is said for its review row.
4. A change that reshapes the call is written whole.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest
from apps.workers import campaign_script, script_writer, step_writer
from apps.workers.script_assist import JsonAnswer, UnusableAnswerError
from apps.workers.script_writer import EditMap, WriteRequest, write_script
from calevate_shared.call_script import CallScript, FaqEntry
from tests.script_writer_rebuild_2026_11_26_test import (
    CAP,
    LANG,
    OWNER_STEPS,
    FakeModel,
    _context,
    _good,
    _script,
)

#: The four Swara instructions of 27 Nov 2026 (ai-tests.md §2), as one request.
SWARA = (
    "One action per turn in every step; never ask the farmer to tell you when done, ask what "
    "they see instead; on an early stop say which steps are left and ask when to call back; "
    "remove WhatsApp and support timings."
)


def _saved() -> CallScript:
    script = _script()
    return script.model_copy(
        update={
            "goal": "The farmer installs the app.",
            "faqs": [FaqEntry(question="Is it free?", answer="Yes, free for farmers.")],
        }
    )


def test_a_free_form_ask_on_a_saved_script_is_an_edit() -> None:
    base = _saved()
    asked = _context(asked_from=base, saved=base, instruction="Make the close shorter.")
    assert campaign_script.write_request(asked, 0.0).mode == "edit"
    assert campaign_script.write_request(replace(asked, instruction=""), 0.0).mode == "whole"
    assert (
        campaign_script.write_request(replace(asked, instruction=OWNER_STEPS), 0.0).mode == "whole"
    )
    assert campaign_script.write_request(replace(asked, rewrite=True), 0.0).mode == "whole"


def test_the_map_is_held_to_the_script() -> None:
    script = _saved()
    mapped = script_writer.parsed_edit_map(
        {
            "whole": False,
            "changes": [
                {"where": "stages.close", "change": "Drop the WhatsApp line."},
                {"where": "stages.nowhere", "change": "Ignored."},
                {"where": "faqs.0.answer", "change": "Say it is free for every farmer."},
            ],
            "every_step": {"change": "Give one action a turn.", "lines_only": True},
        },
        script,
    )
    assert set(mapped.steps) == {"install", "login", "close"}
    assert mapped.steps["close"] == "Drop the WhatsApp line. Give one action a turn."
    assert mapped.parts == {"faqs.0.answer": "Say it is free for every farmer."}
    assert mapped.lines_only == {"install", "login", "close"}
    assert script_writer.parsed_edit_map({"whole": True}, script) == EditMap(whole=True)
    with pytest.raises(UnusableAnswerError):
        script_writer.parsed_edit_map(
            {"whole": False, "changes": [], "every_step": {"change": "", "lines_only": False}},
            script,
        )


class _EditModel(FakeModel):
    def __init__(self, mapped: dict[str, Any]) -> None:
        super().__init__()
        self.mapped = mapped

    async def __call__(self, description: str, instruction: str, **kw: Any) -> JsonAnswer[Any]:
        if instruction == script_writer.EDIT_MAP_INSTRUCTION:
            self.requests.append(description)
            return JsonAnswer(value=kw["parse"](self.mapped), capability=CAP, model="fake")
        if instruction == step_writer.PARTS_INSTRUCTION:
            self.requests.append(description)
            value = {"parts": [{"path": "faqs.0.answer", "text": "Yes, it is free for all."}]}
            return JsonAnswer(value=kw["parse"](value), capability=CAP, model="fake")
        return await super().__call__(description, instruction, **kw)


def _install(monkeypatch: pytest.MonkeyPatch, model: FakeModel) -> None:
    monkeypatch.setattr(step_writer, "ask_json", model)
    monkeypatch.setattr(script_writer, "ask_json", model)


async def test_only_the_mapped_places_change_and_the_rest_is_the_saved_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _saved()
    model = _EditModel(
        {
            "whole": False,
            "changes": [
                {"where": "stages.login", "change": "Ask what they see, never if it is done."},
                {"where": "faqs.0.answer", "change": "Say it is free for all."},
            ],
            "every_step": {"change": "", "lines_only": False},
        }
    )
    _install(monkeypatch, model)
    context = _context(asked_from=base, saved=base, instruction=SWARA)

    result = await write_script(WriteRequest("edit", context, base=base))

    out = result.script
    assert out.stages[1] != base.stages[1]
    assert out.stages[1].instruction == "Guide the person through Login."
    for kept in (0, 2):
        assert out.stages[kept].model_dump_json() == base.stages[kept].model_dump_json()
    assert out.faqs[0].answer == "Yes, it is free for all."
    assert out.opening_line == base.opening_line and out.goal == base.goal
    assert result.changed == {
        "stages.login": "Ask what they see, never if it is done.",
        "faqs": "Say it is free for all.",
    }
    # One map, one step, one part: never a whole script.
    step_asks = [r for r in model.requests if 'THIS STEP: "' in r]
    assert len(step_asks) == 1 and 'THIS STEP: "Login"' in step_asks[0]


def test_whatever_the_writer_did_elsewhere_is_put_back() -> None:
    base = _saved()
    touched = base.model_copy(
        update={
            "goal": "Changed by a repair round.",
            "stages": [s.model_copy(update={"instruction": "Changed."}) for s in base.stages],
        }
    )
    mapped = EditMap(steps={"login": "x"})
    kept = script_writer._only_where_mapped(base, touched, mapped)
    assert kept.goal == base.goal
    assert kept.stages[0] == base.stages[0] and kept.stages[2] == base.stages[2]
    assert kept.stages[1].instruction == "Changed."


async def test_a_change_that_reshapes_the_call_is_written_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _saved()
    model = _EditModel(
        {"whole": True, "changes": [], "every_step": {"change": "", "lines_only": False}}
    )
    _install(monkeypatch, model)

    async def opening(*_a: Any, **_k: Any) -> Any:
        from apps.workers.opening_line import WrittenOpening
        from calevate_shared.opening_notices import SaidNotices

        return JsonAnswer(
            value=WrittenOpening(line=base.opening_line, said=SaidNotices()),
            capability=CAP,
            model="fake",
        )

    monkeypatch.setattr(script_writer, "write_opening", opening)
    context = _context(asked_from=base, saved=base, instruction="Add a step to ask their village.")
    result = await write_script(WriteRequest("edit", context, base=base))
    step_asks = [r for r in model.requests if 'THIS STEP: "' in r]
    assert len(step_asks) >= len(base.stages), "every step written again"
    assert result.changed == {}


def test_a_global_rule_writes_only_each_steps_lines() -> None:
    words = step_writer.parsed_step(_good("Login"), languages=(LANG,), first=False, close=False)
    stage = _saved().stages[1]
    laid = script_writer.stage_with(stage, words, only=script_writer._LINES_ONLY)
    assert laid.instruction == stage.instruction
    assert laid.procedure == stage.procedure
