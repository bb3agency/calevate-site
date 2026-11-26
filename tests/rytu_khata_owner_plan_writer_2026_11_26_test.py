"""The Rytu Khata owner plan of 25 Nov 2026 through the one writer (`write_script`), against
the defects production wrote from it on 26 Nov 2026 (22:53 IST). Code decides the structure
and keeps the owner's words; the model is a fake, in English placeholders."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
from apps.api.agents.owner_plan import owner_plan
from apps.api.agents.script_builder import JobDetails
from apps.api.agents.script_plan import plan_from_owner
from apps.api.agents.script_shape import echo_branches
from apps.workers import script_writer, step_writer
from apps.workers.script_writer import WriteRequest, write_script
from calevate_shared.call_script import CALL_BACK, CollectField
from tests.script_writer_rebuild_2026_11_26_test import LANG, FakeModel, _context, _good
from tests.script_writer_rebuild_2026_11_26_test import fake as fake

PLAN = (Path(__file__).parent / "fixtures" / "owner_plans" / "rytu_khata_2026_11_25.txt").read_text(
    encoding="utf-8"
)
_STEP = re.compile(r'THIS STEP: "([^"]+)"')


def _owner_words(name: str) -> str:
    plan = owner_plan(PLAN)
    assert plan is not None
    step = plan.named(name)
    assert step is not None
    return " ".join(step.instruction.split())


def test_the_plan_carries_each_owner_step_word_for_word() -> None:
    plan = owner_plan(PLAN)
    assert plan is not None
    built = plan_from_owner(plan, placed=True)
    by_name = {s.name: s for s in built.steps}
    assert "On Android, guide them to open Chrome, type rytukhata.com, and tap Install app" in (
        by_name["App on the home screen"].intent
    )
    assert "tap the Share button, then Add to Home Screen" in (
        by_name["App on the home screen"].intent
    )
    assert "because they registered on the Rytu Khata website" in by_name["Introduction"].intent
    for name in ("My Farms", "First expense", "First sale"):
        assert "one field at a time" in by_name[name].intent


async def test_the_written_script_keeps_the_owners_words_and_invents_nothing(
    fake: FakeModel,
) -> None:
    asked: dict[str, int] = {}

    def answer(name: str, request: str) -> dict[str, Any]:
        asked[name] = asked.get(name, 0) + 1
        raw = _good(name)
        # The model paraphrases the owner, as production's did; code keeps the owner's.
        raw["instruction"] = "Guide the farmer to open the website and add the app."
        if name == "Close" and asked[name] == 1:
            raw["examples"][LANG]["turns"] = ["Thank you, message us any time, goodbye"]
        return raw

    fake.answer = answer
    details = JobDetails(asked=(CollectField(label="Village"),))
    context = _context(
        instruction=PLAN,
        details=details,
        main_task="Help farmers who registered start using the Rytu Khata app.",
    )
    result = await write_script(WriteRequest("whole", context))
    stages = {s.name: s for s in result.script.stages}

    # 1. Each owner step's text is its instruction, verbatim up to the step detail's room.
    for name in ("App on the home screen", "My Farms", "First sale", "Close", "Not registered"):
        owners = _owner_words(name)
        assert stages[name].instruction == owners[: len(stages[name].instruction)]
        assert len(stages[name].instruction) >= min(len(owners), 200)
    assert "rytukhata.com" in stages["App on the home screen"].instruction
    # 8. The first step keeps who is calling and why; only the repeated question goes.
    intro = stages["Introduction"].instruction
    assert "say who is calling and from Rytu Khata" in intro
    assert "because they registered on the Rytu Khata website" in intro
    assert "good time" not in intro
    # 10. The owner's own rules reach every step's request, the steps themselves do not.
    step_requests = [r for r in fake.requests if "THIS STEP" in r]
    assert all("Never offer a call back while you can still help" in r for r in step_requests)
    assert all("2. App on the home screen" not in r for r in step_requests)
    # 9. Nothing beyond what the step says: the rule reaches the writer of every step.
    assert "do not say" in step_writer.STEP_INSTRUCTION
    assert "one field at a time" in stages["First expense"].instruction

    # 2. No collect the job does not ask.
    for stage in result.script.stages:
        assert set(stage.collect) <= {"Village"}, (stage.name, stage.collect)

    # 3. A call back is a way out, never also said in the instruction.
    for stage in result.script.stages:
        if any(b.target == CALL_BACK for b in stage.branches):
            assert "call back" not in stage.instruction.casefold()

    # 4. The close names only the owner's way to reach them: rewritten once, and the
    #    rewrite was told why.
    assert asked["Close"] == 2
    close_requests = [r for r in fake.requests if 'THIS STEP: "Close"' in r]
    assert "names a way to reach the business (message)" in close_requests[-1]
    assert not any("message" in t.casefold() for t in stages["Close"].examples[LANG].turns)

    # 6. No echo way out (0.5.79): a scenario's way to the step its Otherwise reaches.
    assert echo_branches(result.script) == []


@pytest.mark.parametrize("line", ["Message us any time", "Send us a WhatsApp", "Email us"])
def test_a_close_naming_another_channel_than_its_step_is_found(line: str) -> None:
    from calevate_shared.call_script import StepExamples
    from tests.script_writer_rebuild_2026_11_26_test import _script

    script = _script()
    close = script.stages[2].model_copy(
        update={
            "instruction": "Thank them, say they can call us with any doubt.",
            "examples": {LANG: StepExamples(turns=[line])},
        }
    )
    script = script.model_copy(update={"stages": [*script.stages[:2], close]})
    assert any("way to reach" in p for p in script_writer._channel_problems(script))


#: Letters of an Indian script with no meaning, standing for a line in that script.
_INDIC = "".join(chr(0x0C15 + i) for i in range(6))


def test_an_opening_never_changes_its_script_or_gains_an_english_sentence() -> None:
    """7. The 26 Nov 2026 (23:20) opening came back romanised with an English sentence."""
    assert not script_writer.keeps_language(
        f"{_INDIC} {{{{lead_name}}}}", "{{lead_name}} garu, nenu Varsha ni.", "te-IN"
    )
    assert not script_writer.keeps_language(
        f"{_INDIC}?", f"{_INDIC}. We are calling to help you install the app.", "te-IN"
    )
    assert script_writer.keeps_language(f"{_INDIC}?", f"{_INDIC} app?", "te-IN")
    assert script_writer.keeps_language("Hello?", "Hello there, can we talk now?", "en-IN")


async def test_the_writer_keeps_the_opening_when_its_rewrite_changes_the_language(
    fake: FakeModel,
) -> None:
    from dataclasses import replace

    from tests.script_writer_rebuild_2026_11_26_test import _script

    base = _script().model_copy(update={"opening_line": f"{_INDIC} {{{{lead_name}}}}?"})
    context = _context()
    context = replace(context, brief=replace(context.brief, language="te-IN"))
    result = await write_script(WriteRequest("opening", context, base=base))
    assert result.script.opening_line == base.opening_line


def test_only_the_repeated_permission_question_is_dropped_from_the_first_step() -> None:
    """8. The first step keeps who is calling and why when the opening already asks."""
    from apps.api.agents.script_plan import without_permission_ask

    said = without_permission_ask(_owner_words("Introduction"))
    assert "say who is calling and from Rytu Khata" in said
    assert "we want to help them start using the app" in said
    assert "good time" not in said
