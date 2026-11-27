"""What the founder's 28 Nov 2026 00:48 test call left on its call page, and why none of it
stands.

An outbound set-up call on an eleven-step script whose third step is a side step, taken only
by a way out of the second. The caller went through steps 1-8; the sale (9) was not clear and
the last two were never reached. The page showed:

* a summary saying the caller "confirmed completion of all steps";
* "Not mentioned" for a status detail about step 4, which the caller had confirmed;
* "Language captured · Suggested" on the caller's "Hello.", a line that names no language;
* "Done" for the side step the call never went into.

Nothing here names any one business.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from apps.api.crm.step_progress import (
    StepProgress,
    StepReading,
    progress_json,
    read_progress,
    side_steps,
    with_sides,
)
from apps.workers import step_progress as judge
from apps.workers import step_truth
from apps.workers.moments import (
    field_backed,
    languages_named,
    model_moments,
    needs_its_line,
    prompt_line_turns,
    stated_on,
)
from calevate_shared.call_script import (
    END_OF_CALL,
    SCRIPT_SCHEMA_VERSION,
    CallScript,
    ConversationStage,
    StageBranch,
)
from calevate_shared.events import TranscriptTurn
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionOutput,
    ExtractionSchemaSpec,
    MomentCandidate,
)

MAIN = [
    "Introduction",
    "Why we called",
    "App on the home screen",
    "Login",
    "Language",
    "Add a branch",
    "First entry",
    "First sale",
    "Dashboard",
    "Close",
]
#: A side step named for nothing being absent, so only the script's shape makes it one.
SIDE = "Signs up first"


def _stage(sid: str, step: int, name: str, **extra: Any) -> ConversationStage:
    return ConversationStage(id=sid, step=step, name=name, instruction=f"Guide: {name}.", **extra)


def _script(*, otherwise_from_two: str = "s3") -> CallScript:
    stages = [
        _stage("s1", 1, MAIN[0]),
        _stage(
            "s2",
            2,
            MAIN[1],
            branches=[StageBranch(when="They say they never signed up", target="side")],
            otherwise=otherwise_from_two,
        ),
        _stage("side", 3, SIDE, otherwise="s3"),
    ]
    stages += [_stage(f"s{n}", n + 1, name) for n, name in enumerate(MAIN[2:], 3)]
    stages[-1] = stages[-1].model_copy(update={"otherwise": END_OF_CALL})
    return CallScript(schema_version=SCRIPT_SCHEMA_VERSION, stages=stages)


SCRIPT = _script()
NAMES = judge.step_names(SCRIPT)
HOME = 4  # "App on the home screen"


def _reading(states: dict[int, str], turns: dict[int, int] | None = None) -> StepProgress:
    turns = turns or {}
    return StepProgress(
        steps=tuple(
            StepReading(
                n,
                NAMES[n],
                states.get(n, "unclear"),  # type: ignore[arg-type]
                turn_idx=turns.get(n, n * 2) if states.get(n) == "reached" else None,
            )
            for n in NAMES
        )
    )


#: The founder's call: 1-8 reached, the side step read reached on step 4's own line, the sale
#: not clear, the last two never reached.
CALL = _reading(
    {**dict.fromkeys(range(1, 9), "reached"), 10: "not_reached", 11: "not_reached"},
    turns={3: HOME * 2},
)


# --- 4. a side step the call did not go into ---------------------------------------------


def test_a_step_reached_only_by_a_way_out_is_a_side_step() -> None:
    assert side_steps(SCRIPT) == frozenset({3})
    # Falling into it from the step before puts it on the call's way through.
    assert side_steps(_script(otherwise_from_two="")) == frozenset()


def test_a_side_step_read_on_another_steps_line_is_not_needed() -> None:
    """FAILS IF: a side step the call never took reads Done because the line that showed the
    step it leads back to was read as showing it too."""
    settled = with_sides(CALL, side_steps(SCRIPT))
    assert settled.state_of(3) == "not_needed"
    assert not settled.shows_reached(3)
    assert settled.state_of(HOME) == "reached"
    assert settled.furthest == 8


def test_a_side_step_the_call_did_go_into_keeps_its_reading() -> None:
    went_in = _reading(dict.fromkeys(range(1, 9), "reached"), turns={3: 5})
    assert with_sides(went_in, side_steps(SCRIPT)).state_of(3) == "reached"
    # Not reached or unclear before the furthest step: the call went past without it.
    for state in ("unclear", "not_reached"):
        past = _reading({**dict.fromkeys(range(1, 9), "reached"), 3: state})
        assert with_sides(past, side_steps(SCRIPT)).state_of(3) == "not_needed"
    # Beyond the furthest step the call did not get that far.
    early = _reading({1: "reached", 2: "reached", 3: "not_reached"})
    assert with_sides(early, side_steps(SCRIPT)).state_of(3) == "not_reached"


def _turns() -> list[TranscriptTurn]:
    lines = [("caller", "Hello.")]
    for n in range(1, 12):
        lines += [("agent", f"Now step {n}."), ("caller", f"Yes, step {n} is there.")]
    return [
        TranscriptTurn(call_id="c", idx=i, speaker=s, text=t)  # type: ignore[arg-type]
        for i, (s, t) in enumerate(lines)
    ]


def _row(step: int, state: str, turn: int = -1, quote: str = "") -> dict[str, Any]:
    return {
        "step": step,
        "state": state,
        "caller_turn": turn,
        "quote": quote,
        "scenario": "",
        "moved_on_turn": -1,
    }


SPEC = ExtractionSchemaSpec(
    fields=[
        ExtractionField(key="installation_status", label="Installation Status", type="text"),
        ExtractionField(key="dashboard_status", label="Dashboard Status", type="text"),
        ExtractionField(
            key="interaction_outcome",
            label="Interaction Outcome",
            type="enum",
            enum_values=["Setup successful", "Help given"],
        ),
        ExtractionField(key="crop", label="Crop", type="text"),
        ExtractionField(key="dashboard_seen", label="Dashboard status", type="bool"),
    ]
)


def _judged(rows: list[dict[str, Any]], **extra: Any) -> StepProgress:
    raw = {"steps": rows, "fields": [], "goal_step": -1, "outcomes": [], **extra}
    raw.setdefault("claimed_done_turn", -1)
    return judge.checked(
        raw,
        names=NAMES,
        lines=judge.redacted_lines(_turns()),
        spec=SPEC,
        scenarios=judge.step_scenarios(SCRIPT),
        sides=side_steps(SCRIPT),
    )


def _line(step: int) -> int:
    return step * 2


def test_the_judge_cannot_mark_the_side_step_done_on_the_line_of_the_step_it_leads_to() -> None:
    rows = [_row(n, "reached", _line(n), f"step {n} is there") for n in range(1, 9) if n != 3]
    rows.append(_row(3, "reached", _line(HOME), f"step {HOME} is there"))
    progress = _judged(rows)
    assert progress.state_of(3) == "not_needed"
    assert progress.state_of(HOME) == "reached"


def test_not_needed_is_a_side_steps_word_only() -> None:
    progress = _judged([_row(3, "not_needed"), _row(5, "not_needed")])
    assert progress.state_of(3) == "not_needed"
    assert progress.state_of(5) == "unclear"


def test_the_judge_is_told_which_step_is_a_side_step() -> None:
    asked = judge.request_text(SCRIPT, judge.redacted_lines(_turns()), SPEC)
    assert f"Step 3 ({SIDE}; a side step, gone through only by a way out into it)" in asked
    assert f"Step {HOME} (App on the home screen):" in asked
    assert "installation_status (Installation Status): free text" in asked
    assert "crop (Crop)" not in asked
    assert "not_needed" in judge.ASK


def test_a_reading_with_its_details_and_side_steps_survives_storage() -> None:
    progress = _judged(
        [_row(n, "reached", _line(n), f"step {n} is there") for n in range(1, 5) if n != 3],
        details=[
            {"key": "installation_status", "step": HOME},
            {"key": "crop", "step": 2},
            {"key": "dashboard_status", "step": 99},
            "not a row",
        ],
    )
    # Only a status detail, onto a real step.
    assert progress.details == {"installation_status": HOME}
    assert read_progress(json.loads(progress_json(progress))) == progress


# --- 1 and 2. what the notes and the summary keep ------------------------------------------


def _facts(progress: StepProgress) -> step_truth.StepFacts:
    return step_truth.facts_of(SCRIPT, with_sides(progress, side_steps(SCRIPT)), [])


def test_the_side_step_is_never_where_a_call_stops_short_or_what_it_reached() -> None:
    facts = _facts(CALL)
    assert 3 in facts.branches
    assert 3 not in facts.reached
    assert facts.incomplete
    assert SIDE not in (step_truth.prompt_note(facts) or "")


TOLD = (
    "The caller agreed to install the app on their phone, including adding a branch, "
    "recording an entry and saving a sale. They confirmed completion of all steps and the "
    "app is now installed."
)


def test_a_summary_saying_every_step_was_done_loses_that_clause_only() -> None:
    """FAILS IF: "confirmed completion of all steps" survives on a call that stopped short."""
    facts = _facts(CALL)
    assert step_truth.claims_unreached("They confirmed completion of all steps.", facts)
    assert step_truth.without_unreached(TOLD, facts) == (
        "The caller agreed to install the app on their phone, including adding a branch, "
        "recording an entry and saving a sale. The app is now installed."
    )
    for whole in ("Every step was completed.", "Everything is done now."):
        assert step_truth.without_unreached(whole, facts) == ""


def test_a_detail_about_a_reached_step_stands_on_a_call_that_stopped_later() -> None:
    """FAILS IF: "Installation Status" is dropped because a later step was not reached."""
    progress = StepProgress(
        steps=CALL.steps,
        details={"installation_status": HOME, "dashboard_status": 10, "dashboard_seen": 10},
    )
    facts = _facts(progress)
    out, changed = step_truth.settle(
        ExtractionOutput(
            data={
                "installation_status": "Successfully installed",
                "dashboard_status": "Dashboard viewed",
                "dashboard_seen": True,
                "interaction_outcome": "Setup successful",
            },
            summary=TOLD,
        ),
        facts,
        SPEC,
        goal=None,
        outcomes=(),
    )
    # About step 4, reached: kept. About step 10, not reached: a claim it happened goes.
    # About the whole task, on a call that stopped short: goes.
    assert out.data == {"installation_status": "Successfully installed"}
    assert {"dashboard_status", "dashboard_seen", "interaction_outcome", "summary"} <= set(changed)
    assert out.summary.endswith("The app is now installed.")


def test_a_detail_about_an_unreached_step_saying_it_is_not_done_stays() -> None:
    progress = StepProgress(steps=CALL.steps, details={"dashboard_status": 10})
    out, _ = step_truth.settle(
        ExtractionOutput(data={"dashboard_status": "Not opened yet"}),
        _facts(progress),
        SPEC,
        goal=None,
        outcomes=(),
    )
    assert out.data == {"dashboard_status": "Not opened yet"}


# --- 3. a language is not said on a line that names none -----------------------------------


@dataclass(frozen=True)
class _Turn:
    idx: int
    speaker: str
    text: str
    start_ms: int | None
    start_approximate: bool = True


TURNS = [
    _Turn(0, "caller", "Hello.", 1_000),
    _Turn(1, "agent", "ఇప్పుడు మాట్లాడటానికి వీలుగా ఉందా?", 2_000),
    _Turn(2, "caller", "Em cheyamannaru meeru, marchipoyanu.", 9_000),
    _Turn(3, "agent", "సరే అండి.", 10_000),
]


def _suggested(turns: list[_Turn], line: int, value: str) -> list[dict[str, Any]]:
    return model_moments(
        [MomentCandidate(line=line, kind="field_captured", field="language")],
        line_turns=prompt_line_turns(turns),
        field_labels={"language": "Language"},
        redact=str,
        captured={"language"},
        values={"language": value},
    )


def test_a_language_gets_no_marker_on_a_line_that_names_none() -> None:
    """FAILS IF: "Language captured" sits on "Hello." or on a line that is about something
    else."""
    assert _suggested(TURNS, 1, "Telugu") == []
    assert _suggested(TURNS, 3, "Telugu") == []


def test_a_language_the_caller_names_keeps_its_marker_on_that_line() -> None:
    for said in ("Telugu lo cheppandi.", "Telugulo matladandi.", "తెలుగులో చెప్పండి."):
        turns = [*TURNS, _Turn(4, "caller", said, 12_000)]
        assert [m["turn_idx"] for m in _suggested(turns, 1, "Telugu")] == [4]


def test_a_stored_language_marker_on_a_line_that_names_none_is_not_shown() -> None:
    stored = [
        {"kind": "field_captured", "turn_idx": 0, "field": "language", "source": "model"},
        {"kind": "field_captured", "turn_idx": 2, "field": "preferred", "source": "model"},
        {"kind": "field_captured", "turn_idx": 2, "field": "need", "source": "model"},
    ]
    values = {"language": "Telugu", "preferred": "Telugu", "need": "Help with the app"}
    kept = field_backed(
        stored,
        captured=set(values),
        caller_turns={0, 2},
        values=values,
        turn_texts={t.idx: t.text for t in TURNS},
    )
    assert [m["field"] for m in kept] == ["need"]


def test_what_counts_as_a_language_value() -> None:
    assert languages_named("Telugu") == {"telugu"}
    assert languages_named("Telugu and English") == {"telugu", "english_india"}
    assert languages_named("తెలుగు") == {"telugu"}
    # A sentence that mentions a language is a reading of what was said, not a language.
    assert languages_named("Wants to hear about the app in Telugu") == frozenset()
    assert needs_its_line("Telugu")
    assert not needs_its_line("Expense tracking")
    assert languages_named(None) == frozenset()
    assert stated_on("Hindi", "Hindi mein boliye")
    assert not stated_on("Hindi", "Hello.")
    # Anything else is said as before (`said_on`).
    assert stated_on("గుర్తులేదండి", "నాకు గుర్తులేదండి.")
