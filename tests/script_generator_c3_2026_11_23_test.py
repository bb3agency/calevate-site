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
from apps.api.agents.script_builder import job_details
from apps.api.agents.script_checks import mistake_findings
from apps.api.agents.script_lint import (
    LintContext,
    same_ending_problems,
    same_opener_problems,
    unasked_details,
    unasked_problems,
)
from apps.api.agents.script_structure import collected, settled, time_taken
from apps.workers import campaign_script
from apps.workers import campaign_script_ask as ask
from apps.workers.script_assist import STEP_RULES, _script_from_model_json
from apps.workers.script_proposal import _Fix
from calevate_shared.call_script import (
    CALL_BACK,
    END_OF_CALL,
    CallScript,
    ConversationStage,
    ProcedureStep,
    StageBranch,
    compile_call_script,
)
from calevate_shared.extraction import whole_call_detail
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


def test_the_job_asks_its_core_details_and_its_own_but_not_what_the_call_shows() -> None:
    """FAILS IF: the name, a call-back time and another number are not asked, a status or
    outcome is listed to be asked, or the call-back details are not known as such."""
    details = job_details(STORED, CORE)
    assert details.labels() == (
        "Caller Name",
        "Satisfaction level",
        "Call Back Time",
        "Alternative Number",
    )
    assert details.call_back == ("Call Back Time", "Alternative Number")
    assert whole_call_detail("call_outcome", "Call Outcome")
    body = compile_call_script(_script(_stage("s1", "Close")), collect=list(details.asked))
    assert "- Caller Name (only if not known)" in body
    assert "- Call Back Time (only if they want a call later)" in body
    assert "Installation Status" not in body and "Setup Progress" not in body
    # The writer reads each with when it is asked.
    assert campaign_script._collect_labels(details.asked)[0] == "Caller Name: only if not known"


def test_a_detail_no_step_asks_is_a_finding_the_repair_answers() -> None:
    """FAILS IF: the check every Pip script goes through does not report a detail of the job
    that no step asks, or counts a step that names it with its hint as not asking it."""
    labels = ("Caller Name", "Satisfaction level")
    script = _script(_stage("s1", "Install"), _stage("s2", "Close"))
    found = _Fix(LintContext(collect=labels), [], frozenset()).problems(script)
    assert [p for p in found if p.startswith("script: no step asks")] == unasked_problems(
        script, labels
    )
    assert len(unasked_problems(script, labels)) == 2
    asked = _script(
        _stage("s1", "Install", collect=["Caller Name: only if not known"]),
        _stage("s2", "Close", collect=["Satisfaction level"]),
    )
    assert unasked_details(asked, labels) == []


def test_the_writers_stage_details_are_read_and_settled_to_the_jobs_labels() -> None:
    """FAILS IF: a drafted stage's details are dropped, a hint stays in the label, a detail
    the job does not note is kept, or a step asking for a later time does not note the job's
    own call-back details."""
    raw = {
        "stages": [
            {
                "name": "Name",
                "instruction": "If the name is not known, ask it.",
                "sounds_like": "Mee peru?",
                "collect": ["Caller Name: only if not known", "Budget"],
            },
            {
                "name": "Busy",
                "instruction": "Ask for a better time to call them.",
                "sounds_like": "Eppudu call cheyali?",
            },
            {"name": "Close", "instruction": "Thank them.", "sounds_like": "Dhanyavadalu."},
        ]
    }
    drafted = _script_from_model_json(raw)
    assert drafted.stages[0].collect == ["Caller Name: only if not known", "Budget"]
    context = LintContext(
        collect=("Caller Name", "Call Back Time", "Alternative Number"),
        call_back=("Call Back Time", "Alternative Number"),
    )
    mended = settled(drafted, context)
    assert mended.stages[0].collect == ["Caller Name"]
    assert mended.stages[1].collect == ["Call Back Time", "Alternative Number"]
    assert any(b.target == CALL_BACK for b in mended.stages[1].branches)
    # An owner's step is left as they wrote it.
    assert collected(drafted, context.collect, set()) == drafted
    # With no job labels the old mend stands.
    busy = _script(_stage("b", "Busy", "Ask for a better time.", otherwise=END_OF_CALL))
    assert time_taken(busy, {"b"}).stages[0].collect == ["When to call back"]


def test_the_writer_is_told_to_list_each_detail_where_it_is_asked() -> None:
    assert "collect list" in SCRIPT_FLOW_RULE and "only on that path" in SCRIPT_FLOW_RULE
    assert "{{lead_name}} empty" in ask.DETAILS_RULE
    assert "call later" in ask.DETAILS_RULE


# --- 3. the product's own names -------------------------------------------------------------


def test_the_writer_and_the_review_hold_the_products_own_names() -> None:
    """FAILS IF: the writer is not told to keep a screen's exact name, the review does not
    count a screen's name as a claim to source, or a renamed screen is not a finding."""
    assert "exact name" in STEP_RULES and "never described" in STEP_RULES
    assert "screen, tab, button, menu or feature" in ask.REVIEW_INSTRUCTION
    review = ask.parsed_review(
        {
            "notes": [{"part": "stages.s1", "why": "Shows the dashboard."}],
            "claims": [],
            "problems": [
                {"part": "stages.s1", "kind": "renamed", "detail": "home screen for Dashboard"}
            ],
        },
        ["stages.s1"],
    )
    assert review is not None
    assert review.problems("stages.s1") == [
        ask.WEAK_PROBLEMS["renamed"].format(detail="home screen for Dashboard")
    ]


def test_the_review_reads_and_repairs_each_language_line_and_small_step() -> None:
    """FAILS IF: the review does not see a step's line in the call language or its small
    steps, where the renamed screen was said, or the repair may not rewrite them."""
    script = _script(
        _stage(
            "s1",
            "Dashboard",
            scripts={TE: "Ippudu home screen chudandi."},
            procedure=[ProcedureStep(action="Ask them to open the home screen.")],
        ),
        _stage("s2", "Close"),
    )
    text = next(p.text for p in ask.reviewed_parts(script, None) if p.key == "stages.s1")
    assert "Ippudu home screen chudandi." in text and "open the home screen" in text
    paths = campaign_script._repair_paths("stages.s1", script)
    assert f"stages.0.scripts.{TE}" in paths and "stages.0.procedure.0.action" in paths


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
    assert "open or end with the same words" in SCRIPT_FLOW_RULE


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
