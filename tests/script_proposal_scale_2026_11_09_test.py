"""A large Pip script change keeps what it got right and says exactly what it could not do.

Production, 9 Nov 2026: the founder asked Pip for a large restructuring of Varsha's script and
read "Could not write the suggestion: AI help could not make that change cleanly this time".
The edit returned the WHOLE script on a route-sized budget (15 s, 4,096 tokens); its one repair
asked for the whole script again; and a repair that did not come back, or still broke a rule
anywhere, threw the whole answer away. Now each repair asks only for the parts still broken and
lays them back by step id, the job gives a long script a job-sized budget, a repair that never
comes back still leaves the first answer's good parts, and what is left out is named.

The model is replaced at its one seam (`chat.complete`); the lines are English. A line that
names a technology company breaks a rule (`business_copy.provider_problem`), which is the
broken part in every case here.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx
import pytest
from apps.api.agents import script_proposals
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_JOB_TIMEOUT_S
from apps.api.core.settings import get_settings
from apps.workers import chat
from apps.workers import script_proposal as worker
from apps.workers.extraction import (
    ASSIST_LADDER_LEGS,
    ASSIST_TIMEOUT_S,
    PROVIDER_UNAVAILABLE_REASON,
)
from apps.workers.script_assist import (
    ANSWER_UNUSABLE_CODE,
    TARGETED_REPAIR_NOTE,
    AskTrace,
    LeftOut,
    ScriptBrief,
    UnusableAnswerError,
    draft_script,
    merged_repair,
    salvaged_edit,
)
from calevate_shared.call_script import CallScript, ConversationStage

BROKEN = "We book it on Google for you."
#: What each step is about: words rather than numbers, since a figure the owner's facts do
#: not give is itself a broken rule.
TOPICS = (
    "",
    "seeds",
    "soil",
    "water",
    "season",
    "delivery",
    "payment",
    "storage",
    "pests",
    "harvest",
    "market",
)


#: A warmer line per step, each opening differently and sharing few words with the others, so
#: the same-opening and repeated-line checks have nothing to say about the lines a test keeps.
WARM = (
    "",
    "Which seeds are you planning to sow this season?",
    "How is your soil holding up after the rains?",
    "Do your fields get enough water right now?",
    "When does your next crop season start?",
    "Where should we deliver your order?",
    "Would you like to pay at delivery or online?",
    "Is there a dry place to keep the bags?",
    "Have pests troubled your crop lately?",
    "Any idea yet when the harvest will be ready?",
    "Tell me, where do you usually sell your produce?",
)


def _warm(i: int) -> str:
    return WARM[i]


def _stage(i: int, line: str | None = None) -> ConversationStage:
    return ConversationStage(
        id=f"s{i}",
        name=f"Step {i}",
        instruction=f"Cover the {TOPICS[i]} part of the call.",
        sounds_like=line or f"Now the {TOPICS[i]}, is that fine?",
    )


#: A long script: ten steps, then the close (the most a script holds is twelve).
CURRENT = CallScript(
    schema_version=2,
    opening_line="Hello, this is Asha from Acme Seeds. Can we talk now?",
    goal="Help buyers with their seed orders.",
    stages=[
        *[_stage(i) for i in range(1, 11)],
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
CHANGE = "Rewrite every step's line so it sounds warmer, and set the main task to orders."


def _rewritten(i: int, *, broken: set[int]) -> dict[str, Any]:
    line = BROKEN if i in broken else _warm(i)
    return _stage(i, line).model_dump(mode="json")


def _answer(*, broken: set[int]) -> dict[str, Any]:
    """The whole edited script, as the edit writer returns it, with `broken` steps' lines
    naming a technology company."""
    body = CURRENT.model_dump(mode="json", exclude={"raw_override"})
    body["goal"] = "Help buyers place and track their seed orders."
    body["stages"] = [
        *[_rewritten(i, broken=broken) for i in range(1, 11)],
        CURRENT.stages[-1].model_dump(mode="json"),
    ]
    return body


class Model:
    """`chat.complete` answering the paid leg with each of `answers` in turn (a dict is the
    JSON content, the string "cut" a reply stopped at `max_tokens`), and the Sarvam standby
    unreachable, so only the paid leg's answers decide the outcome."""

    def __init__(self, *answers: dict[str, Any] | str) -> None:
        self.answers = list(answers)
        self.asked: list[list[Any]] = []
        self.max_tokens: list[int | None] = []

    async def __call__(
        self, leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any
    ) -> chat.ChatOutcome:
        if leg.dialect == "sarvam":
            raise httpx.ConnectError("standby down")
        self.asked.append(list(messages))
        self.max_tokens.append(kw.get("max_tokens"))
        answer = self.answers[min(len(self.asked) - 1, len(self.answers) - 1)]
        usage = chat.TokenUsage(prompt_tokens=9_000, output_tokens=3_000)
        if answer == "cut":
            return chat.ChatOutcome(content='{"stages": [', finish_reason="length", usage=usage)
        return chat.ChatOutcome(content=json.dumps(answer), finish_reason="stop", usage=usage)

    def note(self, n: int) -> str:
        """The repair note of the `n`th ask (1-based), as the model read it."""
        return str(self.asked[n - 1][-1]["content"])


@pytest.fixture(autouse=True)
def model_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)


async def _edit(model: Model, trace: AskTrace) -> Any:
    return await draft_script(BRIEF, edit_of=CURRENT, change=CHANGE, trace=trace)


async def test_each_repair_asks_only_for_the_broken_steps_and_keeps_the_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a repair asks for the whole script again, a partial repair answer replaces
    the step list (dropping every step it did not repeat), or one step still broken after the
    repairs throws away the nine good ones."""
    fixed_3 = _stage(3, _warm(3)).model_dump(mode="json")
    fixed_7 = _stage(7, _warm(7)).model_dump(mode="json")
    model = Model(
        _answer(broken={3, 7, 9}),
        {"stages": [fixed_3, fixed_7, _rewritten(9, broken={9})]},
        {"stages": [_rewritten(9, broken={9})]},
    )
    monkeypatch.setattr(chat, "complete", model)
    trace = AskTrace()
    draft = await _edit(model, trace)

    assert len(model.asked) == 3
    first_note, second_note = model.note(2), model.note(3)
    for note in (first_note, second_note):
        assert note.startswith(TARGETED_REPAIR_NOTE.split("{problems}")[0])
        assert "Return the whole JSON again" not in note
    # Each step is named by its id, and the second round names only what is still broken.
    assert all(f'(id "s{i}")' in first_note for i in (3, 7, 9))
    assert '(id "s9")' in second_note and '(id "s3")' not in second_note

    script = draft.script
    assert [s.id for s in script.stages] == [s.id for s in CURRENT.stages]
    assert script.goal == "Help buyers place and track their seed orders."
    by_id = {s.id: s for s in script.stages}
    assert by_id["s3"].sounds_like == _warm(3)
    assert by_id["s5"].sounds_like == _warm(5)
    assert by_id["s9"] == CURRENT.stages[8]
    assert [p.part for p in draft.left_out] == ["stages.s9"]
    assert draft.left_out[0].name == "Step 9" and not draft.left_out[0].added
    assert trace.repairs == 2
    # Every round is one metered request: all three asks' tokens.
    assert draft.usage is not None and draft.usage.output_tokens == 9_000


async def test_a_repair_cut_off_still_keeps_what_the_first_answer_got_right(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a repair that never came back (cut off at its token ceiling) discards the
    first answer, so the owner reads "could not make that change cleanly" for one bad line."""
    model = Model(_answer(broken={4}), "cut")
    monkeypatch.setattr(chat, "complete", model)
    trace = AskTrace()
    draft = await _edit(model, trace)
    assert draft.script.goal == "Help buyers place and track their seed orders."
    assert draft.script.stages[3] == CURRENT.stages[3]
    assert draft.script.stages[0].sounds_like == _warm(1)
    assert [p.part for p in draft.left_out] == ["stages.s4"]
    assert trace.truncated


async def test_nothing_left_names_each_part_and_why(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAILS IF: an edit with nothing usable left says only "try describing the change another
    way" when we know which part broke which rule."""
    only = CURRENT.model_dump(mode="json", exclude={"raw_override"})
    only["stages"][1] = _rewritten(2, broken={2})
    model = Model(only)
    monkeypatch.setattr(chat, "complete", model)
    trace = AskTrace()
    with pytest.raises(ProblemError) as refused:
        await draft_script(BRIEF, edit_of=CURRENT, change="Make step 2 warmer.", trace=trace)
    assert refused.value.code == ANSWER_UNUSABLE_CODE
    assert [p.part for p in trace.unwritten] == ["stages.s2"]
    note = worker.refusal_note(refused.value, trace)
    assert note.startswith("Pip could not write a clean version of Step “Step 2”:")
    assert "Names a technology company" in note
    # The vendor the model named is ours to know, never the client's to read (D-679).
    assert "Google" not in note
    assert "another way" not in note


def test_a_first_answer_cut_off_says_the_change_was_too_big() -> None:
    """FAILS IF: a change too long to write in one answer reads as "no assistant answered"."""
    trace = AskTrace(truncated=True)
    refusal = ProblemError.business_rule(PROVIDER_UNAVAILABLE_REASON, "No assistant answered.")
    assert worker.refusal_note(refusal, trace) == script_proposals.TOO_BIG_NOTE


def test_a_step_that_fails_validation_is_put_back_and_the_rest_kept() -> None:
    """FAILS IF: one step the script's own validation refuses (here a mode that does not
    exist) refuses the whole lenient read."""
    body = _answer(broken=set())
    body["stages"][5]["mode"] = "sing"
    with pytest.raises(UnusableAnswerError):
        salvaged_edit(body, CURRENT)
    script, left_out = salvaged_edit(body, CURRENT, lenient=True)
    assert script.stages[5] == CURRENT.stages[5]
    assert script.goal == "Help buyers place and track their seed orders."
    assert [p.part for p in left_out] == ["stages.s6"]


def test_a_repair_restores_a_dropped_close_but_never_duplicates_a_renamed_step() -> None:
    previous = {"stages": [{"id": "a"}, {"id": "b"}]}
    repaired = {"stages": [{"id": "b", "name": "B2"}, {"id": "close"}, {"id": "b-copy"}]}
    merged = merged_repair(previous, repaired, known_ids=frozenset({"a", "b", "close"}))
    assert merged["stages"] == [{"id": "a"}, {"id": "b", "name": "B2"}, {"id": "close"}]


def test_the_owner_never_reads_a_vendor_name_in_a_left_out_reason() -> None:
    rule = "names a technology company (google)"
    assert script_proposals.owner_rule(rule) == "Names a technology company."
    part = LeftOut("opening_line", "", rule)
    assert script_proposals.part_label(part) == "The opening line"


def test_the_proposal_job_budget_fits_inside_the_worker_job() -> None:
    """FAILS IF: the job's ladder plus its opening repairs can outlast arq's `job_timeout`,
    which would kill the job after the model was paid and before the meter row is written."""
    ladder = ASSIST_LADDER_LEGS * worker.PROPOSAL_REQUEST_TIMEOUT_S
    openings = 2 * ASSIST_LADDER_LEGS * ASSIST_TIMEOUT_S
    assert ladder + openings + 30 < WORKER_JOB_TIMEOUT_S
