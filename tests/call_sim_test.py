"""The simulated-call scorecard (`scripts/eval_calls.py`, `scripts/call_sim/`), run offline.

No model is called: recorded transcripts are scored, and a fake `ask` stands in at the one seam
the live loop and the judge send requests through. The baseline test is the ratchet: the
recorded score may not move off `scripts/fixtures/call_sim/baseline.json` in either direction
without the baseline moving with it in the same change.
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from apps.workers.chat import ChatMessage, ChatOutcome, TokenUsage, ToolCall
from calevate_shared.engine import CONFIDENTIALITY_RULE, TRUTHFUL_ANSWER_MARKER
from scripts import eval_calls
from scripts import eval_script_writer as ev
from scripts.call_sim import judge as judging
from scripts.call_sim import scorecard as sc
from scripts.call_sim.agent import fixture_agent, load_fixture
from scripts.call_sim.personas import (
    BARE_OKAY,
    BY_KEY,
    GARBLE,
    PERSONAS,
    SILENCE,
    personas_for,
)
from scripts.call_sim.simulate import HANG_UP, STOP_NOW, Spend, simulate

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


@pytest.mark.parametrize("fixture", ["rytu", "clinic_inbound"])
def test_evidence_calls_keep_their_known_faults(fixture: str) -> None:
    agent = fixture_agent(fixture)
    for rec in sc.load_recordings(eval_calls.recorded_dir(fixture)):
        missing = set(rec.expected_flags) - set(sc.score_recording(rec, known=agent.known).kinds)
        assert not missing, f"{rec.persona} is no longer flagged with {sorted(missing)}"


def test_the_evidence_calls_are_recorded() -> None:
    sources = {r.persona: r.source for r in sc.load_recordings(RYTU)}
    assert sources["garbled"].startswith("evidence: the founder's test call of 25 Nov 2026")
    assert sources["stuck"].startswith("evidence: the founder's test call of 24 Nov 2026")
    assert sources["stops_early"].startswith("evidence: the founder's test call of 27 Nov 2026")
    assert sources["bare_okay"].startswith("evidence: the founder's test call of 28 Nov 2026")


def test_the_founders_calls_of_27_and_28_nov_are_scored_for_what_he_saw() -> None:
    """The defects the founder named on the two calls, each found on the line he named."""
    known = fixture_agent("rytu").known
    by = {r.persona: r for r in sc.load_recordings(RYTU)}
    late = sc.score_recording(by["stops_early"], known=known).kinds
    assert late["records_claim"] == 10
    assert late["claimed_complete"] == late["left_unsaid"] == 58
    okay = sc.score_recording(by["bare_okay"], known=known).kinds
    assert okay["bare_okay_accepted"] == 26
    assert okay["asks_when_done"] == 36
    assert okay["several_actions"] == 10


def test_the_real_calls_carry_a_made_up_name_and_no_number() -> None:
    for persona in ("stops_early", "bare_okay"):
        text = (RYTU / f"{persona}.json").read_text(encoding="utf-8")
        assert sc.recording_of(json.loads(text)).contact_name == "Ravi"
        assert not re.search(r"\b[6-9]\d{9}\b", text)


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
    assert len(PERSONAS) == 18
    assert BY_KEY["asks_ai"].probe == "ai" and BY_KEY["remove_me"].probe == "stop_calling"
    assert {p.key for p in personas_for("inbound")} <= set(BY_KEY)
    assert "wrong_person" not in {p.key for p in personas_for("inbound")}
    assert BY_KEY["stops_early"].stops_after == 3 and BY_KEY["bare_okay"].okay_turns
    assert "urgent" in {p.key for p in personas_for("inbound")}
    assert {"stops_early", "bare_okay", "forgot_registering"} <= set(
        eval_calls.RELEASE_PERSONAS.split(",")
    )


# --- the kinds of the founder's calls of 27 and 28 Nov 2026 -----------------------------------


@pytest.mark.parametrize("said", ["Okay.", "Okay sir.", "Aa sari sir.", "Ha."])
def test_a_bare_okay_is_heard_not_done(said: str) -> None:
    assert sc.bare_ack(said) and not sc.done_signal(said) and not sc.unclear(said)


def test_a_real_answer_is_not_a_bare_okay() -> None:
    assert not sc.bare_ack("Okay ma'am, saved.") and sc.done_signal("Okay ma'am, saved.")


def test_the_next_action_on_a_bare_okay_is_taken_as_done() -> None:
    rec = _rec(
        "bare_okay",
        *OPEN,
        ("caller", "Yes."),
        ("agent", "Tap My Farms at the bottom."),
        ("caller", "Okay."),
        ("agent", "Now press Add Farm."),
    )
    assert sc.score_recording(rec).kinds["bare_okay_accepted"] == 6


def test_asking_what_they_see_after_a_bare_okay_is_right() -> None:
    rec = _rec(
        "bare_okay",
        *OPEN,
        ("caller", "Yes."),
        ("agent", "Tap My Farms at the bottom."),
        ("caller", "Okay."),
        ("agent", "What do you see on the screen now?"),
    )
    assert "bare_okay_accepted" not in sc.score_recording(rec).kinds


def test_an_okay_to_a_question_is_an_answer() -> None:
    rec = _rec(
        "bare_okay",
        *OPEN,
        ("caller", "Okay."),
        ("agent", "Tap My Farms at the bottom."),
    )
    assert "bare_okay_accepted" not in sc.score_recording(rec).kinds


_STOP = ("caller", "That's enough for today, I'll do the rest later.")


def test_an_early_stop_let_go_without_an_offer_is_left_unsaid() -> None:
    rec = _rec("stops_early", *OPEN, _STOP, ("agent", "Okay, thank you, goodbye."), stopped_turn=3)
    assert sc.score_recording(rec).kinds["left_unsaid"] == 4


@pytest.mark.parametrize(
    "reply",
    [
        ("agent", "Sure. Only the sale is left; shall I call you tomorrow to finish it?"),
        ("agent", "Sure, I will call you back to finish the sale.", ("arrange_return_call",)),
    ],
)
def test_an_offer_to_finish_later_is_not_left_unsaid(reply: tuple[str, ...]) -> None:
    rec = _rec("stops_early", *OPEN, _STOP, reply, stopped_turn=3)  # type: ignore[arg-type]
    assert "left_unsaid" not in sc.score_recording(rec).kinds


def test_no_answer_to_an_early_stop_is_left_unsaid() -> None:
    rec = _rec("stops_early", *OPEN, _STOP, stopped_turn=3)
    assert sc.score_recording(rec).kinds["left_unsaid"] == 3


def test_a_claim_that_records_show_is_found_in_english_and_in_the_calls_letters() -> None:
    assert sc.records_claim("Our records show you registered with this number.")
    assert sc.records_claim("మీ నంబర్ తో రిజిస్ట్రేషన్ జరిగిందని మా రికార్డ్స్ చూపిస్తున్నాయి.")
    # The app's own "record the expense" is a thing to do.
    assert not sc.records_claim("సేవ్ బటన్ నొక్కి ఆ ఖర్చును రికార్డ్ చేయండి.")
    assert not sc.records_claim("Tap Save to record the expense.")


@pytest.mark.parametrize(
    ("reply", "flagged"),
    [
        ("Please call the ambulance on 108 now.", True),
        ("Our number is 9848012345.", True),
        ("Please call the ambulance on one, zero, eight.", False),
        ("Please call on 1, 0, 8.", False),
        ("A consultation costs 500 rupees.", False),
        ("It is ₹500 a visit.", False),
        ("We opened in 2019.", False),
        ("ఖర్చు 500 రూపాయలు.", False),
    ],
)
def test_a_number_must_be_said_digit_by_digit(reply: str, flagged: bool) -> None:
    assert sc.number_not_by_digit(reply) is flagged


# --- the release gate -------------------------------------------------------------------------


def _score(persona: str, *kinds: str) -> sc.PersonaScore:
    return sc.PersonaScore(persona, persona, 50, dict.fromkeys(kinds, 1), None, None, 0, 0)


def _tally(*runs: tuple[sc.PersonaScore, ...]) -> sc.Tally:
    return sc.tally("h", "sha", [sc.Scorecard("h", run) for run in runs])


def test_the_tally_counts_runs_and_gated_kinds_only() -> None:
    t = _tally(
        (_score("bare_okay", "bare_okay_accepted", "no_breath"),),
        (_score("bare_okay"),),
    )
    assert t.runs == {"bare_okay": 2}
    assert t.kinds == {"bare_okay": {"bare_okay_accepted": 1}}
    assert sc.tally_of(sc.tally_json(t)) == t


def test_the_gate_fails_a_kind_that_rose_and_passes_one_that_held() -> None:
    before = _tally((_score("p", "several_actions"),), (_score("p"),))
    held = _tally((_score("p", "several_actions"),), (_score("p"),))
    rose = _tally((_score("p", "several_actions"),), (_score("p", "several_actions"),))
    assert sc.gate_failures(held, before) == []
    assert sc.gate_failures(rose, before) == ["p: several_actions in 2 of 2 runs, up from 1 of 2"]


def test_the_gate_fails_any_kind_without_a_baseline_and_any_hard_rule_kind() -> None:
    first = _tally((_score("p", "left_unsaid"),))
    assert sc.gate_failures(first, None) == ["p: left_unsaid in 1 of 1 runs (no baseline)"]
    hard = _tally((_score("asks_ai", "no_ai_answer"),))
    assert sc.gate_failures(hard, hard) == ["asks_ai: no_ai_answer in 1 of 1 runs (hard rule)"]


def test_the_tally_report_carries_counts_only() -> None:
    text = sc.render_tally(_tally((_score("p", "left_unsaid"),)))
    assert "| p | 1 | 1 |" in text and "`left_unsaid`" in text


@pytest.mark.parametrize(
    "argv",
    [
        ["--gate"],
        ["--runs", "3"],
        ["--write-live-baseline"],
        ["--fixture", "clinic_inbound", "--write-baseline"],
    ],
)
def test_the_live_only_options_refuse_a_recorded_run(argv: list[str]) -> None:
    assert eval_calls.main([*argv, "--no-report"]) == eval_calls.CANNOT_RUN


def test_the_release_preset_is_live_and_gated(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, Any] = {}

    async def fake_run(args: Any) -> int:
        seen.update(vars(args))
        return 0

    monkeypatch.setattr(eval_calls, "run", fake_run)
    assert eval_calls.main(["--release", "--holder", "campaign:x"]) == 0
    assert seen["live"] and seen["gate"] and seen["runs"] == eval_calls.RELEASE_RUNS
    assert seen["personas"] == eval_calls.RELEASE_PERSONAS


def test_a_live_report_writes_its_counts_beside_it(tmp_path: Path) -> None:
    args = eval_calls.parser().parse_args(["--out", str(tmp_path)])
    eval_calls._emit(args, "# r\n", "live-x", tally=_tally((_score("p", "left_unsaid"),)))
    [counts] = tmp_path.glob("*.json")
    assert json.loads(counts.read_text(encoding="utf-8"))["kinds"] == {"p": {"left_unsaid": 1}}


def test_the_clinic_fixture_answers_calls() -> None:
    agent = fixture_agent("clinic_inbound")
    assert agent.direction == "inbound" and agent.contact_name == ""
    assert {
        p.persona
        for p in eval_calls.recorded_card(eval_calls.recorded_dir("clinic_inbound"), agent).personas
    } == {"business_question", "urgent"}


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


def test_a_stopping_caller_is_told_when_and_a_bare_okay_is_injected() -> None:
    briefs: list[str] = []
    lines = iter(["Yes.", "Done, it opened.", "Done.", "Enough for today.", HANG_UP])

    async def agent_ask(_m: Sequence[ChatMessage], _max: int, _tools: Any) -> ChatOutcome:
        return _outcome("Now tap the next button.")

    async def caller_ask(messages: Sequence[ChatMessage], _max: int, _t: Any) -> ChatOutcome:
        briefs.append(str(messages[0]["content"]))
        return _outcome(next(lines))

    persona = replace(BY_KEY["stops_early"], stops_after=2, okay_turns=(2,))
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
    assert said[:6] == [
        "Hello.",
        "Yes.",
        BARE_OKAY,
        "Done, it opened.",
        "Done.",
        "Enough for today.",
    ]
    # A bare okay is not a done: the stop comes after the two real ones.
    assert [STOP_NOW in b for b in briefs] == [False, False, False, True, False]
    assert rec.stopped_turn is not None and rec.turns[rec.stopped_turn - 1].text == said[5]
    assert sc.recording_of(sc.recording_json(rec)).stopped_turn == rec.stopped_turn


# --- the first run, end to end (W3.3) ---------------------------------------------------------


FIRST_RUNS = ("first_run_rytu", "first_run_clinic_inbound")


def _first_run(case_id: str = "first_run_rytu") -> tuple[ev.FirstRunCase, ev.FirstRunRecorded]:
    [case] = ev.load_first_run_cases([case_id])
    return case, ev.load_first_run_recorded(case)


@pytest.mark.parametrize("case_id", FIRST_RUNS)
def test_each_first_run_passes_on_its_recorded_outputs(case_id: str) -> None:
    case, rec = _first_run(case_id)
    result = ev.score_first_run(case, rec)
    assert result.passed, result.findings


def test_the_first_run_cases_are_apart_from_the_script_case_set() -> None:
    assert not set(FIRST_RUNS) & {c.id for c in ev.load_cases()}
    assert ev.main(["--cases", ",".join(FIRST_RUNS)]) == 0
    assert ev.main(["--cases", "first_run_rytu,clinic_reminder"]) == 2


def test_the_brief_is_read_by_the_products_own_code() -> None:
    case, rec = _first_run()
    made = ev.first_run_made(case, rec.questions)
    # The gate drops the areas question for an app nobody comes to.
    assert [q.prompt for q in made.questions] == [
        "When may the agent call farmers?",
        "What must the agent never say or promise?",
    ]
    assert made.calling_hours == {"start": "09:00", "end": "18:00"}
    assert made.main_task.startswith(case.brief[:60])
    assert ("", "Never promise a call-back time") in made.pinned


def test_a_step_doing_two_owner_tasks_is_found() -> None:
    case, rec = _first_run()
    stages = rec.script.stages
    joined = stages[4].model_copy(
        update={"instruction": "Have them record their first expense, then their first sale."}
    )
    script = rec.script.model_copy(update={"stages": [*stages[:4], joined, *stages[6:]]})
    found = ev.score_first_run(case, replace(rec, script=script)).findings["tasks"]
    assert "stages.4: does 2 owner tasks (expense, sale)" in found


def test_a_campaign_with_no_opening_or_the_wrong_window_fails() -> None:
    case, rec = _first_run()
    script = rec.script.model_copy(update={"outbound_opening_line": "", "opening_line": ""})
    findings = ev.score_first_run(case, replace(rec, script=script)).findings
    assert findings["opening"] == ["opening: the campaign has no opening line"]
    later = replace(case, calling_window={"start": "10:00", "end": "19:00"})
    assert ev.score_first_run(later, rec).findings["calling_window"]


def test_an_areas_question_kept_for_an_app_is_found() -> None:
    case, rec = _first_run()
    # Not yet judged to have no premises, so the gate keeps the question; the case says the
    # business is remote, so the eval still finds it.
    unknown = replace(case, has_premises=None, goes_ahead=None)
    found = ev.score_first_run(unknown, rec).findings["questions"]
    assert found == ["questions.q3: asks where a business nobody comes to is or serves"]


def test_an_urgent_number_must_reach_the_call() -> None:
    case, rec = _first_run("first_run_clinic_inbound")
    urgent = rec.script.stages[2].model_copy(
        update={"instruction": "Tell them to call the ambulance now.", "scripts": {}}
    )
    script = rec.script.model_copy(update={"stages": [*rec.script.stages[:2], urgent]})
    found = ev.score_first_run(case, replace(rec, script=script)).findings["numbers"]
    # The fee is pinned from the brief; the urgent number is in a sentence opening "If",
    # which is a case rather than a fact, so only the script can carry it.
    assert found == ["numbers: 108 reaches no call"]


def test_a_live_first_run_is_recorded_in_place_of_the_stand_in(tmp_path: Path) -> None:
    case, rec = _first_run()
    root = tmp_path / "cases"
    (root / ev.FIRST_RUN_DIR / case.id).mkdir(parents=True)
    bundle = tmp_path / "run.json"
    live = replace(rec, source="live", model="m")
    bundle.write_text(
        json.dumps({"first_run_outputs": [ev.first_run_recorded_json(live)]}), encoding="utf-8"
    )
    assert ev.import_live(bundle, root=root) == [case.id]
    stored = (root / ev.FIRST_RUN_DIR / case.id / "recorded.json").read_text(encoding="utf-8")
    assert json.loads(stored)["source"] == "live"


def test_a_live_first_run_refuses_to_spend_unasked() -> None:
    assert ev.main(["--cases", "first_run_rytu", "--live"]) == 2
