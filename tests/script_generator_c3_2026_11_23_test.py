"""The script generator's fixes from the founder's test call of 23 Nov 2026 (23:19), held for
any business and language:

1. a step's line asked again whether now is a good time, in the opening's own words but a
   different word form, and the check let it through;
2. the job's own details (the name, a call-back time, another number) were never asked,
   while statuses the call only shows were listed to be asked;
3. the agent called the app's Dashboard the "home screen";
4. nearly every line opened with the same acknowledgement and ended with the same "tell me".

Pure: no database and no model. Lines in the call language are romanised placeholders in the
shape of the call's lines, never product wording.
"""

from __future__ import annotations

from apps.api.agents.call_rules import (
    SCRIPT_FLOW_RULE,
    opening_redone_line_problems,
    reacted_line_problems,
    restated_clause,
)
from apps.api.agents.mistake_lints import mistake_findings
from apps.api.agents.script_lint import (
    LintContext,
    same_ending_problems,
    same_opener_problems,
)
from apps.api.agents.script_structure import time_taken
from calevate_shared.call_script import (
    CALL_BACK,
    CallScript,
    ConversationStage,
    ProcedureStep,
    StageBranch,
)
from calevate_shared.lead_fields import core_fields

TE = "te-IN"
#: The call's opening in its shape: a greeting, who is calling, then "can you talk now?".
OPENING = (
    "Namaskaram, nenu Acme Farms nunchi matladutunnanu, ippudu matladataniki meeku "
    "veeluga unda andi?"
)
#: The first step's line in the call's shape: the reason, then the opening's question again,
#: its last word joined to the one before it.
ASKS_AGAIN = (
    "Meeru ma Acme Farms app lo register chesukunnaru kada, danni mee phone lo pettadaniki "
    "sayam cheddamani phone chesanu, ippudu matladataniki meeku veelunda andi?"
)
#: The same line going on from the person's yes.
GOES_ON = (
    "Meeru ma Acme Farms app lo register chesukunnaru kada, danni mee phone lo pettadaniki "
    "sayam cheddamani phone chesanu."
)


def _stage(
    sid: str, name: str, instruction: str = "Ask one thing.", **kw: object
) -> ConversationStage:
    return ConversationStage(id=sid, name=name, instruction=instruction, **kw)  # type: ignore[arg-type]


def _script(*stages: ConversationStage, opening: str = OPENING) -> CallScript:
    return CallScript(schema_version=2, opening_line=opening, stages=list(stages))


# --- 1. the opening asked again -----------------------------------------------------------


def test_a_steps_line_asking_the_openings_question_in_another_word_form_is_found() -> None:
    """FAILS IF: a step's line in the call language, or its "sounds like" line, may ask the
    opening's "can you talk now?" again when one word of it is written another way."""
    script = _script(
        _stage("s1", "Purpose", sounds_like=ASKS_AGAIN[:200], scripts={TE: ASKS_AGAIN}),
        _stage("s2", "Close"),
    )
    paths = {p.partition(":")[0] for p in opening_redone_line_problems(script)}
    assert paths == {"stages.0.sounds_like", f"stages.0.scripts.{TE}"}


def test_saying_again_who_is_calling_is_found_and_going_on_is_kept() -> None:
    """FAILS IF: a step that says again who is calling passes, or a step that only gives the
    reason the opening did not give is sent back."""
    again = _script(
        _stage(
            "s1", "Purpose", scripts={TE: "Nenu Acme Farms nunchi matladutunnanu, app gurinchi."}
        ),
        _stage("s2", "Close"),
    )
    assert [p.partition(":")[0] for p in opening_redone_line_problems(again)] == [
        f"stages.0.scripts.{TE}"
    ]
    kept = _script(
        _stage("s1", "Purpose", sounds_like=GOES_ON[:200], scripts={TE: GOES_ON}),
        _stage("s2", "Close"),
    )
    assert opening_redone_line_problems(kept) == []


def test_a_question_that_only_shares_two_words_with_the_opening_is_not_the_opening() -> None:
    assert restated_clause("What time is good for the delivery?", ["is now a good time"]) is None
    assert restated_clause("Can we talk now for a minute?", ["can we talk now"]) is None


# --- 2. the job's own details are asked ---------------------------------------------------

CORE = core_fields(
    {
        "name": "Caller Name",
        "preferred_time": "Call Back Time",
        "other_number": "Alternative Number",
    }
)
STORED = [
    {"key": "installation_status", "label": "Installation Status", "type": "enum",
     "enum_values": ["Installed", "Not installed"]},
    {"key": "setup_progress", "label": "Setup Progress", "type": "text"},
    {"key": "satisfaction", "label": "Satisfaction level", "type": "text",
     "reason": "how happy they are with the app"},
    {"key": "call_outcome", "label": "Call Outcome", "type": "text"},
]  # fmt: skip


# --- 3. the product's own names -------------------------------------------------------------


# --- 4. varied lines ------------------------------------------------------------------------


def test_lines_of_one_language_that_open_alike_are_found() -> None:
    """FAILS IF: the call language's lines may all open with one acknowledgement."""
    script = _script(
        _stage("s1", "Phone", scripts={TE: "Sare andi, mee phone Android aa iPhone aa?"}),
        _stage("s2", "Browser", scripts={TE: "Sare andi, Chrome open cheyandi."}),
        _stage("s3", "Close"),
    )
    assert [p.partition(":")[0] for p in same_opener_problems(script)] == [f"stages.1.scripts.{TE}"]


def test_lines_that_all_end_with_one_tag_are_found() -> None:
    """FAILS IF: every small step may end with the same "tell me when done" tag."""
    steps = [
        ProcedureStep(action=f"Ask them to tap {name} and tell me when done.")
        for name in ("Chrome", "the menu", "Add to Home screen")
    ]
    script = _script(_stage("s1", "Install", procedure=steps), _stage("s2", "Close"))
    assert [p.partition(":")[0] for p in same_ending_problems(script)] == [
        "stages.0.procedure.1.action",
        "stages.0.procedure.2.action",
    ]
    varied = _script(
        _stage(
            "s1",
            "Install",
            procedure=[
                ProcedureStep(action="Ask them to open Chrome."),
                ProcedureStep(action="Ask them to tap the three dots at the top."),
                ProcedureStep(action="Ask them to tap Add to Home screen."),
            ],
        ),
        _stage("s2", "Close"),
    )
    assert same_ending_problems(varied) == []


def test_a_language_line_or_small_step_opening_with_a_reaction_is_sent_back() -> None:
    """FAILS IF: a step's line in the call language or a small step may open with a reaction,
    which the agent then copies into every reply; the close keeps its thanks."""
    script = _script(
        _stage(
            "s1",
            "Install",
            scripts={"en-IN": "Very good, now open the app."},
            procedure=[ProcedureStep(action="Great, now ask them to open Chrome.")],
        ),
        _stage("s2", "Close", scripts={"en-IN": "Thank you, have a good day."}),
    )
    assert [p.partition(":")[0] for p in reacted_line_problems(script)] == [
        "stages.0.scripts.en-IN",
        "stages.0.procedure.0.action",
    ]
    assert mistake_findings(script, LintContext(), "same_opening")


def test_the_writer_is_told_to_vary_how_lines_end() -> None:
    assert "end with the same tag" in SCRIPT_FLOW_RULE


def test_a_branch_to_the_call_back_is_kept_by_the_mend() -> None:
    busy = _script(
        _stage(
            "b",
            "Busy",
            "Ask for a better time.",
            branches=[StageBranch(when="They give a time", target=CALL_BACK)],
        )
    )
    mended = time_taken(busy, {"b"}, ("Call Back Time",))
    assert mended.stages[0].collect == ["Call Back Time"]
    assert len(mended.stages[0].branches) == 1
