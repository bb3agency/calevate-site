"""Suggested fixes are grounded in the test's good answer and never take away what the agent
can do (founder, 27 Oct 2026, Sri Estates "Anjali").

The founder's practice test "Gives part of another number" failed every try; the improver
answered with a replacement for the step "Find out what they need" that told the agent to
refuse numbers, dropped the step's price and site-visit rules, and said "I have restricted
the agent". These tests hold the server-side checks that refuse that suggestion, accept the
minimal edit the good answer asks for, and keep the honest "not tested yet".
"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import fix_guard, test_conversations, trial_results
from apps.api.agents.script_edits import ScriptEdit, added_text, kept_problem, language_problem
from apps.api.agents.specimen_scenarios import CLASSES
from apps.api.agents.test_conversations import Judged, Scenario, Turn, decide
from apps.workers import agent_test_ai
from apps.workers.script_assist import UnusableAnswerError
from calevate_shared.call_script import CallScript, ConversationStage

STEP = (
    "Ask which area and what size home they want. Never quote a final price or promise "
    "availability; say the team will confirm. Offer a site visit."
)

SCRIPT = CallScript(
    schema_version=2,
    stages=[ConversationStage(id="s2", name="Find out what they need", instruction=STEP)],
)

GOOD_ANSWER = next(c.expect for c in CLASSES if c.key == "specimen_partial_number")

BRIEF = test_conversations.AgentBrief(
    business_name="Sri Estates",
    business_type="real_estate",
    direction="outbound",
    language="te-IN",
    register="",
    word_swaps=(),
    steps=(("s2", "Find out what they need", STEP),),
    opening_line="",
    ending="",
    objections=(),
    pinned_facts=(),
    knowledge_titles=(),
    lead_fields=("Name",),
    hand_over="off",
    call_backs=True,
    call_is_recorded=True,
    actions=(("whatsapp", "Send the project brochure on WhatsApp"),),
)

#: The founder's suggestion, as the improver returned it.
FOUNDERS_BAD_EDIT: dict[str, Any] = {
    "op": "set_step",
    "step_id": "s2",
    "part": "",
    "name": "",
    "objection": "",
    "text": (
        "Only handle property enquiries. If they ask to send information to a phone number, "
        "tell them you cannot do that. Never accept or confirm partial or full phone numbers."
    ),
    "because": "specimen_partial_number",
    "why": (
        "The agent was incorrectly accepting phone numbers; I have restricted the agent to "
        "only handling property enquiries."
    ),
}


#: A test the script owns, for the checks that read the edit's words: the founder's own key
#: is a platform-rule test, which `fix_guard.stored_problem` refuses before anything else.
SCRIPT_TEST = "g1"


def _propose(edit: dict[str, Any], *, send_back: bool = False) -> dict[str, Any] | None:
    return agent_test_ai.proposal_from_model(
        {"edits": [edit], "facts": []},
        current=SCRIPT,
        keys={"specimen_partial_number", SCRIPT_TEST},
        fact_ids=set(),
        language="en-IN",
        send_back_language=send_back,
        brief=BRIEF,
        good_answers={"specimen_partial_number": GOOD_ANSWER, SCRIPT_TEST: GOOD_ANSWER},
    )


def test_the_founders_suggestion_is_sent_back_then_withheld_not_unusable() -> None:
    """FAILS IF the improver can again offer a step that refuses numbers on an agent that
    sends WhatsApp follow-ups, drops the step's own rules or claims a restriction; or if a
    model that insists on it reads as "answered in a form we could not use" (D-909)."""
    with pytest.raises(UnusableAnswerError) as sent_back:
        _propose(FOUNDERS_BAD_EDIT, send_back=True)
    assert "our platform rules decide" in sent_back.value.problems
    # The repaired answer brings the same edit: withheld, and an honest empty proposal.
    proposal = _propose(FOUNDERS_BAD_EDIT)
    assert proposal is not None
    assert (proposal["edits"], proposal["dropped"], proposal["withheld"]) == ([], 1, 1)
    # For a test the script owns, the same words are still refused for what they say.
    with pytest.raises(UnusableAnswerError) as for_the_script:
        _propose({**FOUNDERS_BAD_EDIT, "because": SCRIPT_TEST}, send_back=True)
    assert "never says it restricted" in for_the_script.value.problems


@pytest.mark.parametrize(
    ("text", "why", "problem"),
    [
        # Keeps the step but refuses numbers outright: the capability check.
        (
            STEP + " Never accept or confirm partial or full phone numbers.",
            "Stops the agent taking a wrong number.",
            "refuses taking a caller's number",
        ),
        # Keeps the step but refuses to send: the WhatsApp action.
        (
            STEP + " If they ask you to send details, tell them you cannot do that.",
            "Keeps the call on property.",
            "refuses its whatsapp action",
        ),
        # A good edit with a why that claims an effect nobody tested.
        (
            STEP + " Take a number a few digits at a time and read all ten back.",
            "I have restricted the agent to full numbers.",
            "never says it restricted",
        ),
    ],
)
def test_each_check_names_what_is_wrong(text: str, why: str, problem: str) -> None:
    edit = {**FOUNDERS_BAD_EDIT, "text": text, "why": why, "because": SCRIPT_TEST}
    with pytest.raises(UnusableAnswerError) as sent_back:
        _propose(edit, send_back=True)
    assert problem in sent_back.value.problems


def test_a_refusal_of_the_good_answer_is_caught_without_a_capability() -> None:
    """An agent with no WhatsApp action still may not be told to refuse what the good
    answer has it do."""
    edit = ScriptEdit(
        id="e1",
        op="set_step",
        step_id="s2",
        text=STEP + " Do not take the caller's other details at all.",
        because="k",
        why="Asks less.",
    )
    problem = fix_guard.grounding_problem(
        edit,
        SCRIPT,
        brief=replace(BRIEF, actions=()),
        good_answer="Takes the caller's details and reads them back.",
        where="edits.0",
    )
    assert problem is not None and "good answer" in problem


def test_the_minimal_edit_for_the_number_test_is_offered() -> None:
    """The step keeps every sentence and gains the one the good answer asks for."""
    text = (
        STEP + " For another number, take it a few digits at a time until all ten are read "
        "back, and never send or say thanks on part of it."
    )
    proposal = _propose(
        {
            **FOUNDERS_BAD_EDIT,
            "text": text,
            "why": "Asks for all ten digits and reads them back.",
            "because": SCRIPT_TEST,
        }
    )
    assert proposal is not None
    assert [e["after"] for e in proposal["edits"]] == [text]
    assert proposal["dropped"] == 0


def test_only_the_added_words_are_judged_and_a_telugu_step_keeps_telugu() -> None:
    """An owner's step in Telugu can take a minimal edit in Telugu: the English-only rule
    for AI-written instructions applies to a step written in English."""
    telugu = CallScript(
        schema_version=2,
        stages=[
            ConversationStage(id="s2", name="Need", instruction="ఏ ఏరియా కావాలో అడగండి. సైట్ విజిట్ ఆఫర్ చేయండి.")
        ],
    )
    edit = ScriptEdit(
        id="e1",
        op="set_step",
        step_id="s2",
        text="ఏ ఏరియా కావాలో అడగండి. సైట్ విజిట్ ఆఫర్ చేయండి. నంబర్ పది అంకెలు చదివి వినిపించండి.",
    )
    assert added_text(edit, telugu) == "నంబర్ పది అంకెలు చదివి వినిపించండి."
    assert language_problem(edit, telugu, "te-IN", where="e") is None
    # The same Telugu words added to an English step are refused, as before.
    english = ScriptEdit(id="e2", op="set_step", step_id="s2", text=STEP + " నంబర్ అడగండి.")
    assert language_problem(english, SCRIPT, "te-IN", where="e") is not None


def test_a_step_rewritten_from_scratch_is_not_a_minimal_edit() -> None:
    edit = ScriptEdit(id="e1", op="set_step", step_id="s2", text="Ask what they need.")
    assert kept_problem(edit, SCRIPT, where="e") is not None
    one_changed = ScriptEdit(
        id="e2",
        op="set_step",
        step_id="s2",
        text=STEP.replace("Offer a site visit.", "Offer a site visit this week."),
    )
    assert kept_problem(one_changed, SCRIPT, where="e") is None


def test_the_improver_reads_the_good_answer_and_the_agents_actions() -> None:
    failure = {
        "key": "specimen_partial_number",
        "title": "Gives part of another number",
        "verdict": "needs_fix",
        "expect": GOOD_ANSWER,
        "reason": "It took four digits as the whole number.",
        "conversation": [],
    }
    request = agent_test_ai.improve_request(BRIEF, SCRIPT, [failure])
    assert f"A good answer: {GOOD_ANSWER}" in request
    assert "whatsapp: Send the project brochure on WhatsApp" in request
    assert "never remove, forbid or refuse" in agent_test_ai.IMPROVE_INSTRUCTION.lower()


def test_a_stored_proposal_says_it_is_not_tested() -> None:
    answer = SimpleNamespace(
        value={"edits": [], "facts": [], "dropped": 0},
        capability=SimpleNamespace(disclosure=None),
    )
    record = agent_test_ai.improvement_record(
        answer,  # type: ignore[arg-type]
        base=SCRIPT,
        base_kind="draft",
        base_saved_at=None,
        base_version=None,
        for_keys=[],
        request_hash="h",
    )
    assert record["tested"] is False


# --- platform rules never reach the improver -----------------------------------------


def test_a_judged_fail_of_a_platform_rule_caller_is_ours() -> None:
    """The founder's failure was judged "needs a fix" with the script to blame, so the
    improver was asked to edit the client's script for a platform rule."""
    scenario = Scenario(
        key="specimen_partial_number",
        title="Gives part of another number",
        category="edge",
        turns=("x",),
        expect=GOOD_ANSWER,
        source="standard",
    )
    judged = Judged(verdict="needs_fix", reason="It took part of a number.", fix="script_step")
    result = decide(
        scenario, [Turn(said="x", reply="Sure.")], judged, language="en-IN", unjudged_reason=""
    )
    assert result["owner"] == "platform"
    assert set(test_conversations.PLATFORM_RULE_TESTS) <= {c.key for c in CLASSES}


def test_one_platform_try_makes_the_whole_test_ours() -> None:
    """Three tries: one put down to the script by the judge, one failed by a platform rule
    check. The test is ours, so the improver never chases it."""
    tries = [
        {"key": "k", "verdict": "needs_fix", "fix": "script_step", "owner": "script"},
        {"key": "k", "verdict": "failed", "fix": "platform", "owner": "platform"},
        {"key": "k", "verdict": "passed", "fix": None, "owner": None},
    ]
    assert trial_results.result_owner(trial_results.aggregate(tries)) == "platform"
