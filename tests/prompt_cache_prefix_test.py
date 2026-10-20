"""Everything fixed in an agent's prompt comes before its first per-call value (D-835).

ThinnestAI fills a `{{variable}}` per call, and the model-side cache a new call can reuse runs
from the start of the prompt to the first value it filled (ThinnestAI email of 19 Oct 2026,
VENDOR-STATED, `docs/vendor/thinnest-replies-2026-10-12.md` §18.0). D-814 put our own
per-call values in the last layer; these pin the client script's half: a section holding a
variable is compiled after the quick facts and the example call, pinned facts are spliced
before it, and nothing before it depends on the caller or the day.
"""

from __future__ import annotations

from calevate_shared.call_script import (
    QUICK_FACTS_LEAD,
    compile_call_script,
    per_call_sections_last,
    splice_quick_facts,
    substitute_variables,
    without_outline,
)
from calevate_shared.engine import THIS_CALL_HEADER, compose_engine_prompt
from tests.agent_prompt_budget_test import COLLECT, PINNED, _config, _starter


def _outbound_prompt() -> str:
    return compose_engine_prompt(_config(_starter("call_leads"), "call_leads", pinned=True))


def test_the_outbound_starter_keeps_its_facts_and_example_before_the_lead_name() -> None:
    prompt = _outbound_prompt()
    first = prompt.index("{{")
    prefix = prompt[:first]
    assert QUICK_FACTS_LEAD in prefix
    assert "[EXAMPLE CALL]" in prefix
    # What follows the value inside the script is the ending section alone.
    script_tail = prompt[first:].split("--- END CLIENT SCRIPT ---")[0]
    assert "[EXAMPLE CALL]" not in script_tail and QUICK_FACTS_LEAD not in script_tail


def test_the_prefix_is_the_same_for_two_callers() -> None:
    """One agent's prompt is one text, whoever is called; the engine's two fillings differ
    only from the first variable on. The day is the engine's own date line, after all of
    ours (§18.0)."""
    prompt = _outbound_prompt()
    assert prompt == _outbound_prompt()
    first = prompt.index("{{")
    asha = substitute_variables(prompt, {"lead_name": "Asha"})
    ravi = substitute_variables(prompt, {"lead_name": "Ravi Kumar"})
    assert asha[:first] == ravi[:first] == prompt[:first]
    assert asha[first:] != ravi[first:]


def test_an_inbound_starter_carries_no_per_call_value_before_this_call() -> None:
    prompt = compose_engine_prompt(_config(_starter("answer_calls"), "answer_calls", pinned=True))
    head = prompt.split(THIS_CALL_HEADER)[0]
    assert "{{" not in head


def test_sections_with_a_value_move_last_and_the_rest_keep_their_order() -> None:
    sections = ["[A]\na", "[B]\nhi {{lead_name}}", "[C]\nc", "[D]\n{{ x }} d", "[E]\ne"]
    assert per_call_sections_last(sections) == [
        "[A]\na",
        "[C]\nc",
        "[E]\ne",
        "[B]\nhi {{lead_name}}",
        "[D]\n{{ x }} d",
    ]


def test_a_stored_body_gets_its_pinned_facts_back_before_the_value() -> None:
    """A body compiled before this change has its ending, with the value, ahead of the quick
    facts; the next splice (a pinned-facts change, a save) puts the facts before it."""
    body = (
        "[IDENTITY]\nYou call for Raghava Organics.\n\n"
        "[ENDING]\nSay goodbye.\nThe person you are calling: {{lead_name}}\n\n"
        f"{QUICK_FACTS_LEAD}\n- Old fact"
    )
    spliced = splice_quick_facts(body, PINNED)
    assert spliced.index(QUICK_FACTS_LEAD) < spliced.index("{{lead_name}}")
    assert "Old fact" not in spliced
    compiled = without_outline(compile_call_script(_starter("call_leads"), collect=COLLECT))
    assert compiled.index("[EXAMPLE CALL]") < compiled.index("{{lead_name}}")
