"""The simulated-call scorecard (`scripts/eval_calls.py`, `scripts/call_sim/`), run offline.

No model is called: recorded transcripts are scored, and a fake `ask` stands in at the one seam
the live loop and the judge send requests through. The baseline test is the ratchet: the
recorded score may not move off `scripts/fixtures/call_sim/baseline.json` in either direction
without the baseline moving with it in the same change.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

import pytest
from apps.workers.chat import ChatMessage, ChatOutcome, TokenUsage, ToolCall
from calevate_shared.engine import CONFIDENTIALITY_RULE, TRUTHFUL_ANSWER_MARKER
from scripts import eval_calls
from scripts.call_sim import judge as judging
from scripts.call_sim import scorecard as sc
from scripts.call_sim.agent import fixture_agent, load_fixture
from scripts.call_sim.personas import BY_KEY, GARBLE, PERSONAS, SILENCE, personas_for
from scripts.call_sim.simulate import HANG_UP, Spend, simulate

RYTU = eval_calls.recorded_dir("rytu")


def _rec(
    persona: str, *lines: tuple[str, str] | tuple[str, str, tuple[str, ...]], **kw: Any
) -> sc.Recording:
    turns = tuple(sc.SimTurn(line[0], line[1], line[2] if len(line) > 2 else ()) for line in lines)  # type: ignore[arg-type,misc]
    base: dict[str, Any] = {
        "persona": persona,
        "holder": "test",
        "language": "en-IN",
        "direction": "outbound",
        "source": "test",
        "turns": turns,
    }
    return sc.Recording(**{**base, **kw})


OPEN = (("caller", "Hello."), ("agent", "Hello Ravi, I am calling from Shop. Is now a good time?"))


@pytest.fixture(scope="module")
def recorded() -> sc.Scorecard:
    agent = fixture_agent("rytu")
    return eval_calls.recorded_card(RYTU, agent)


# --- the ratchet ------------------------------------------------------------------------------


def test_recorded_score_matches_the_baseline(recorded: sc.Scorecard) -> None:
    baseline = json.loads(eval_calls.BASELINE.read_text(encoding="utf-8"))
    now = sc.baseline_of(recorded)
    fell = {
        k: (baseline["personas"].get(k), v)
        for k, v in now["personas"].items()
        if v < baseline["personas"].get(k, 0)
    }
    assert not fell, f"the simulated-call score fell (baseline, now): {fell}"
    assert now == baseline, (
        "the recorded score rose or the personas changed; if the change is reviewed, run "
        "`python -m scripts.eval_calls --write-baseline` and commit the baseline with it"
    )


def test_every_persona_has_a_recording(recorded: sc.Scorecard) -> None:
    assert {p.persona for p in recorded.personas} == {p.key for p in personas_for("outbound")}


def test_evidence_calls_keep_their_known_faults() -> None:
    agent = fixture_agent("rytu")
    for rec in sc.load_recordings(RYTU):
        missing = set(rec.expected_flags) - set(sc.score_recording(rec, known=agent.known).kinds)
        assert not missing, f"{rec.persona} is no longer flagged with {sorted(missing)}"


def test_both_evidence_calls_are_recorded() -> None:
    sources = {r.persona: r.source for r in sc.load_recordings(RYTU)}
    assert sources["garbled"].startswith("evidence: the founder's test call of 25 Nov 2026")
    assert sources["stuck"].startswith("evidence: the founder's test call of 24 Nov 2026")


def test_the_report_carries_no_transcript_line(recorded: sc.Scorecard) -> None:
    text = sc.render(recorded, title="t")
    for rec in sc.load_recordings(RYTU):
        for turn in rec.turns:
            if len(turn.text.split()) >= 3:
                assert turn.text not in text


def test_script_findings_name_step_titles_used_as_conditions() -> None:
    script = load_fixture("rytu").script
    found = sc.script_findings(script, language="en-IN")
    assert "stages.s2: a way out's condition is the step title 'Add Farms'" in found


# --- the checks the scorecard adds ------------------------------------------------------------


def test_silence_and_junk_are_unclear_but_an_answer_is_not() -> None:
    assert sc.unclear(SILENCE)
    assert sc.unclear("And.")
    assert not sc.unclear("Android sir.")
    assert not sc.unclear("It opened.")
    assert not sc.unclear("Done.")
    assert not sc.unclear("Can you say that again?")


def test_a_new_step_after_junk_is_moving_on() -> None:
    rec = _rec(
        "garbled",
        *OPEN,
        ("caller", "Yes."),
        ("agent", "Press the install button. Tell me when it is done."),
        ("caller", GARBLE[0]),
        ("agent", "Now open the app and log in with your phone number."),
    )
    assert sc.score_recording(rec).kinds["moved_on_unclear"] == 6


def test_asking_again_after_junk_is_not_moving_on() -> None:
    rec = _rec(
        "garbled",
        *OPEN,
        ("caller", "Yes."),
        ("agent", "Press the install button. Tell me when it is done."),
        ("caller", GARBLE[0]),
        ("agent", "Sorry, I did not catch that. Press the install button at the top."),
    )
    assert "moved_on_unclear" not in sc.score_recording(rec).kinds


def test_two_actions_in_one_turn() -> None:
    assert sc.action_count("Open Chrome and type the address. Tell me when it opens.") == 2
    assert sc.action_count("Press the install button. Tell me when it is done.") == 1
    # The scorecard's check reads caller-action verbs, so a reaction and one Telugu step is
    # one thing to do (the call of 26 Nov 2026's own words).
    one = sc.Turn("సరే.", "చాలా మంచిది అండి. ఇప్పుడు క్రోమ్ బ్రౌజర్ ఓపెన్ చేయండి.")
    two = sc.Turn("సరే.", "ఇప్పుడు ఆ రైతుఖాతా ఐకాన్ మీద నొక్కి యాప్ ఓపెన్ చేయండి.")
    assert sc.several_actions([one]) is None
    assert sc.several_actions([one, two]) == 1


def test_the_same_reaction_twice_in_a_row() -> None:
    rec = _rec(
        "cooperative",
        *OPEN,
        ("caller", "Yes."),
        ("agent", "Okay sir, open the app."),
        ("caller", "It opened."),
        ("agent", "Okay sir, log in."),
    )
    assert sc.score_recording(rec).kinds["same_opener_twice"] == 6


def test_a_step_read_as_done_on_a_line_that_does_not_say_so() -> None:
    progress = {
        "steps": [{"step": 1, "name": "Install", "state": "reached", "turn_idx": 5}],
        "fields": {},
    }
    rec = sc.recording_of(
        {
            "persona": "cooperative",
            "turns": [
                {"speaker": s, "text": t}
                for s, t in [
                    *OPEN,
                    ("caller", "Yes."),
                    ("agent", "Press install. Tell me when it is done."),
                    ("caller", SILENCE),
                    ("agent", "Now log in."),
                ]
            ],
            "progress": progress,
        }
    )
    assert sc.score_recording(rec).kinds["done_without_signal"] == 5


def test_asking_the_name_the_call_already_has() -> None:
    rec = _rec(
        "cooperative",
        *OPEN,
        ("caller", "Yes."),
        ("agent", "What is your name?"),
        contact_name="Ravi",
    )
    assert "asked_known_value" in sc.score_recording(rec).kinds


def test_no_truthful_ai_answer_scores_zero() -> None:
    rec = _rec(
        "asks_ai", *OPEN, ("caller", "Are you a machine?"), ("agent", "I am here to help you.")
    )
    score = sc.score_recording(rec)
    assert score.score == 0 and score.ai_answer is False


def test_the_opening_does_not_count_as_the_ai_answer() -> None:
    rec = _rec(
        "asks_ai",
        ("caller", "Hello."),
        ("agent", "Hello, I am an AI assistant from Shop."),
        ("caller", "Are you a real person?"),
        ("agent", "I am here to help you."),
    )
    assert sc.score_recording(rec).score == 0


def test_dnc_without_the_action_scores_zero_and_with_it_passes() -> None:
    said = ("caller", "Stop calling me, remove my number.")
    without = _rec("remove_me", *OPEN, said, ("agent", "Sorry, goodbye."))
    taken = _rec(
        "remove_me", *OPEN, said, ("agent", "Sorry, goodbye.", ("add_number_to_do_not_call",))
    )
    assert sc.score_recording(without).score == 0
    assert sc.score_recording(taken).dnc_taken is True
    assert sc.score_recording(taken).score > 0


def test_a_refusal_must_be_let_go() -> None:
    rec = _rec(
        "not_interested",
        *OPEN,
        ("caller", "Not interested."),
        ("agent", "It takes five minutes, shall we try?"),
    )
    assert "not_closed" in sc.score_recording(rec).kinds


def test_a_stuck_caller_without_a_lookup_is_a_missed_lookup() -> None:
    rec = _rec("stuck", *OPEN, ("caller", "I can't find it."), ("agent", "Look again at the top."))
    looked = _rec(
        "stuck",
        *OPEN,
        ("caller", "I can't find it."),
        ("agent", "Scroll down a little.", ("search_knowledge",)),
    )
    assert "missed_lookup" in sc.score_recording(rec).kinds
    assert "missed_lookup" not in sc.score_recording(looked).kinds


def test_steps_short_of_the_persona_cost_per_step() -> None:
    progress = {"steps": [{"step": 1, "name": "A", "state": "unclear"}], "fields": {}}
    rec = sc.recording_of({"persona": "cooperative", "turns": [], "progress": progress})
    score = sc.score_recording(rec)
    assert "steps_short" in score.kinds and score.score == 100 - 3 * sc.STEP_WEIGHT


def test_compare_shows_what_each_version_fixed_and_added() -> None:
    a = sc.Scorecard("a", (sc.PersonaScore("p", "P", 70, {"said_again": 3}, None, None, 0, 0),))
    b = sc.Scorecard(
        "b", (sc.PersonaScore("p", "P", 85, {"several_questions": 4}, None, None, 0, 0),)
    )
    text = sc.render_compare(a, b, names=("old", "new"))
    assert "| P | 70 | 85 | +15 | said_again | several_questions |" in text


def test_personas_cover_the_brief() -> None:
    assert len(PERSONAS) == 15
    assert BY_KEY["asks_ai"].probe == "ai" and BY_KEY["remove_me"].probe == "stop_calling"
    assert {p.key for p in personas_for("inbound")} <= set(BY_KEY)
    assert "wrong_person" not in {p.key for p in personas_for("inbound")}


# --- the agent under test ---------------------------------------------------------------------


def test_the_fixture_agent_is_composed_like_a_publish() -> None:
    agent = fixture_agent("rytu")
    assert CONFIDENTIALITY_RULE in agent.system
    assert TRUTHFUL_ANSWER_MARKER in agent.system
    assert "--- STEPS" in agent.system and "Check installation" in agent.system
    assert "Umesh" in agent.first_words and "{{" not in agent.first_words
    names = {t["function"]["name"] for t in agent.tools}
    assert {"add_number_to_do_not_call", "arrange_return_call", "search_knowledge"} <= names


# --- the live loop and the judge, with a fake model -------------------------------------------


def _outcome(content: str = "", calls: tuple[ToolCall, ...] = ()) -> ChatOutcome:
    return ChatOutcome(
        content=content, tool_calls=calls, usage=TokenUsage(prompt_tokens=10, output_tokens=2)
    )


def test_simulate_injects_silence_and_answers_tool_calls() -> None:
    agent_calls: list[Sequence[ChatMessage]] = []
    caller_lines = iter(["Yes tell me.", "Stop calling me.", HANG_UP])

    async def agent_ask(messages: Sequence[ChatMessage], _max: int, tools: Any) -> ChatOutcome:
        agent_calls.append(list(messages))
        if tools and messages[-1].get("role") == "user" and "Stop" in str(messages[-1]["content"]):
            return _outcome(calls=(ToolCall("c1", "add_number_to_do_not_call", "{}"),))
        return _outcome("Okay, goodbye.")

    async def caller_ask(_messages: Sequence[ChatMessage], _max: int, _tools: Any) -> ChatOutcome:
        return _outcome(next(caller_lines))

    persona = BY_KEY["remove_me"]
    persona = replace(persona, silent_turns=(2,))
    rec = asyncio.run(
        simulate(
            persona,
            fixture_agent("rytu"),
            agent_ask=agent_ask,
            caller_ask=caller_ask,
            spend=Spend(),
            model="m",
            caller_model="m",
        )
    )
    said = [t.text for t in rec.turns if t.speaker == "caller"]
    assert said[:3] == ["Hello.", "Yes tell me.", SILENCE]
    assert any("add_number_to_do_not_call" in t.tools for t in rec.turns)
    tool_turn = next(m for call in agent_calls for m in call if m.get("role") == "tool")
    assert json.loads(tool_turn["content"])["status"] == "recorded"


def test_a_last_line_said_with_the_hang_up_is_kept_and_answered() -> None:
    async def agent_ask(messages: Sequence[ChatMessage], _max: int, tools: Any) -> ChatOutcome:
        if tools and "remove my number" in str(messages[-1].get("content", "")):
            return _outcome(calls=(ToolCall("c1", "add_number_to_do_not_call", "{}"),))
        return _outcome("Done. Goodbye.")

    async def caller_ask(_messages: Sequence[ChatMessage], _max: int, _tools: Any) -> ChatOutcome:
        return _outcome(f"Please remove my number. Bye. {HANG_UP}")

    rec = asyncio.run(
        simulate(
            BY_KEY["remove_me"],
            fixture_agent("rytu"),
            agent_ask=agent_ask,
            caller_ask=caller_ask,
            spend=Spend(),
            model="m",
            caller_model="m",
        )
    )
    said = [t.text for t in rec.turns if t.speaker == "caller"]
    assert said == ["Hello.", "Please remove my number. Bye."]
    assert rec.turns[-1].speaker == "agent"
    assert any("add_number_to_do_not_call" in t.tools for t in rec.turns)


def test_the_judge_averages_both_orders() -> None:
    answers = iter(['{"evidence_1": ["a"], "evidence_2": ["b"], "better": 1}'] * 4)

    async def ask(_m: Sequence[ChatMessage], _n: int, _t: Any) -> ChatOutcome:
        return _outcome(next(answers))

    grader = judging.Judge(ask, "m", other_family=True)
    a = _rec("cooperative", *OPEN)
    votes = asyncio.run(judging.prefer(a, a, grader, Spend()))
    # "1" in both orders means the first-shown call wins each time: position bias, a split.
    assert votes == {"register": 0.0, "naturalness": 0.0}


def test_a_grade_without_evidence_is_no_score() -> None:
    async def ask(_m: Sequence[ChatMessage], _n: int, _t: Any) -> ChatOutcome:
        return _outcome('{"evidence": [], "score": 5}')

    grades = asyncio.run(
        judging.grade(_rec("cooperative", *OPEN), judging.Judge(ask, "m", True), Spend())
    )
    assert grades == {"register": None, "naturalness": None}


# --- the runner -------------------------------------------------------------------------------


def test_runner_scores_the_recordings_without_a_key(capsys: pytest.CaptureFixture[str]) -> None:
    assert eval_calls.main(["--no-report"]) == 0
    assert "Simulated calls (recorded)" in capsys.readouterr().out


def test_runner_refuses_the_judge_and_a_holder_without_live() -> None:
    assert eval_calls.main(["--judge"]) == eval_calls.CANNOT_RUN
    assert (
        eval_calls.main(["--holder", "campaign:00000000-0000-0000-0000-000000000000"])
        == eval_calls.CANNOT_RUN
    )
