"""What the founder's 27 Nov 2026 test call left on its call page, and why none of it stands.

An outbound set-up call on a ten-step script. The caller followed the agent through most
steps, then stopped ("I'll see the rest later") before the last ones; the agent closed with
"you have finished the setup". The page showed:

* "This doesn't look like an Indian mobile number" under a "Phone Type" detail of "Android":
  a field that mentions a phone was read as one that asks for a phone number;
* "Fully operational" and "Setup successful" as the progress and the outcome, and a summary
  repeating the agent's closing claim, on a reading of reached 1-2, unclear 3-8, not reached
  9 and unclear 10;
* an "Extra Details captured · Suggested" marker on a caller line that does not say the
  details' words.

Nothing here names any one business.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from apps.api.crm.step_progress import StepProgress, StepReading
from apps.workers import step_truth
from apps.workers.moments import field_backed, model_moments, prompt_line_turns, said_on
from calevate_shared.call_script import SCRIPT_SCHEMA_VERSION, CallScript, ConversationStage
from calevate_shared.extraction import (
    PHONE_NEEDS_REVIEW,
    ExtractionField,
    ExtractionOutput,
    ExtractionSchemaSpec,
    MomentCandidate,
    build_extraction_prompt,
    is_phone_field,
    validate_extraction,
)

# --- 1. a field that mentions a phone is not a phone number ------------------------------


def _f(key: str, label: str, type_: str = "text", reason: str = "", **kw: Any) -> ExtractionField:
    return ExtractionField(key=key, label=label, type=type_, reason=reason, **kw)  # type: ignore[arg-type]


NOT_PHONE_NUMBERS = [
    _f("phone_type", "Phone Type"),
    _f("phone_type", "Phone Type", "enum", enum_values=["Android", "iPhone"]),
    _f("phone_model", "Phone model"),
    _f("phone_brand", "Phone brand", reason="Which company made the phone they use."),
    _f("handset", "Which phone do you use?"),
    _f("handset", "Handset", reason="Which phone the caller has, Android or iPhone."),
    _f("contact_person", "Contact person"),
    _f("prefers_whatsapp", "Prefers WhatsApp", "bool"),
]
PHONE_NUMBERS = [
    _f("phone", "Phone"),
    _f("mobile", "Mobile", "number"),
    _f("phone_number", "Phone number"),
    _f("whatsapp", "WhatsApp"),
    _f("contact", "Best contact"),
    _f("alt", "Alt", reason="their whatsapp number for follow-up"),
    _f("alt_mobile", "Alternate mobile"),
    _f("mobile_no", "Mobile No."),
    _f("callback_number", "Callback number"),
    _f("other_number", "Other number", reason="A different phone number to reach them on."),
]


@pytest.mark.parametrize("field", NOT_PHONE_NUMBERS, ids=lambda f: f"{f.label}-{f.type}")
def test_a_field_about_the_phone_is_not_a_phone_number(field: ExtractionField) -> None:
    assert not is_phone_field(field)


@pytest.mark.parametrize("field", PHONE_NUMBERS, ids=lambda f: f.label)
def test_a_field_asking_for_the_number_still_is_one(field: ExtractionField) -> None:
    assert is_phone_field(field)


def test_android_under_phone_type_is_kept_and_not_flagged() -> None:
    """FAILS IF: "Android" under "Phone Type" is read as a phone number."""
    for field in NOT_PHONE_NUMBERS[:2]:
        out = validate_extraction(ExtractionSchemaSpec(fields=[field]), {field.key: "Android"})
        assert out.data == {field.key: "Android"}
        assert out.needs_review == {}
    phone = PHONE_NUMBERS[0]
    flagged = validate_extraction(ExtractionSchemaSpec(fields=[phone]), {"phone": "1234567890"})
    assert flagged.needs_review == {"phone": PHONE_NEEDS_REVIEW}


# --- 2. the agent's own claim of completion ---------------------------------------------

STEPS = [
    "Introduction",
    "Why we called",
    "Install the app",
    "Login",
    "Language",
    "Add a branch",
    "First entry",
    "First sale",
    "Dashboard",
    "Close",
]
SCRIPT = CallScript(
    schema_version=SCRIPT_SCHEMA_VERSION,
    stages=[
        ConversationStage(id=f"s{n}", name=name, instruction=f"Guide them: {name}.", step=n)
        for n, name in enumerate(STEPS, 1)
    ],
)
SPEC = ExtractionSchemaSpec(
    fields=[
        _f(
            "setup_progress",
            "Setup Progress",
            "enum",
            enum_values=["Installed", "Logged in", "Fully operational"],
        ),
        _f(
            "interaction_outcome",
            "Interaction Outcome",
            "enum",
            enum_values=["Setup successful", "Help given", "Not interested"],
        ),
    ]
)


def _reading(states: dict[int, str]) -> StepProgress:
    return StepProgress(
        steps=tuple(
            StepReading(n, STEPS[n - 1], states.get(n, "unclear"), turn_idx=1)  # type: ignore[arg-type]
            for n in range(1, len(STEPS) + 1)
        )
    )


#: The reading the founder's call got: reached to 2, unclear to 8, not reached 9.
STOPPED = _reading({1: "reached", 2: "reached", 9: "not_reached"})


def test_a_call_not_reached_before_its_last_step_stopped_short() -> None:
    assert step_truth.facts_of(SCRIPT, STOPPED, []).incomplete
    finished = _reading(dict.fromkeys(range(1, 10), "reached"))
    assert not step_truth.facts_of(SCRIPT, finished, []).incomplete


def test_the_agents_claim_of_completion_is_not_the_outcome_or_the_summary() -> None:
    """FAILS IF: "Fully operational", "Setup successful" or the agent's closing claim stays
    on a call that stopped before its last steps."""
    facts = step_truth.facts_of(SCRIPT, STOPPED, [])
    told = ExtractionOutput(
        data={"setup_progress": "Fully operational", "interaction_outcome": "Setup successful"},
        summary=(
            "The caller installed the app and logged in with the agent's help. The call "
            "ended with the agent saying the setup was complete."
        ),
    )
    out, changed = step_truth.settle(told, facts, SPEC, goal=None, outcomes=())
    assert out.data == {}
    assert out.summary == "The caller installed the app and logged in with the agent's help."
    assert {"setup_progress", "interaction_outcome", "summary"} <= set(changed)


def test_the_prompt_judges_completion_from_the_caller() -> None:
    prompt = build_extraction_prompt(SPEC, "caller: Hello.")
    assert "is the agent's claim, not evidence" in prompt
    assert "only from what\n  the caller said and did" in prompt
    assert "say they stopped and what was left undone" in prompt


# --- 3. a quoted value sits only on a line that says it ---------------------------------


@dataclass(frozen=True)
class _Turn:
    idx: int
    speaker: str
    text: str
    start_ms: int | None
    start_approximate: bool = True


SAID = "అసలు అది ఏంటండి? నాకు గుర్తులేదండి."
TURNS = [
    _Turn(0, "caller", "Hello.", 1_000),
    _Turn(1, "agent", "ఇప్పుడు మాట్లాడటానికి వీలుగా ఉందా?", 2_000),
    _Turn(2, "caller", SAID, 9_000),
    _Turn(3, "agent", "సరే అండి.", 10_000),
]
#: A sentence in the call's script that no turn holds.
UNSAID = "ప్రైస్ పాత గురించి ఆ రోజు గుట్టలేదు."


def _suggested(notes: str) -> list[dict[str, Any]]:
    return model_moments(
        [MomentCandidate(line=3, kind="field_captured", field="notes")],
        line_turns=prompt_line_turns(TURNS),
        field_labels={"notes": "Extra Details"},
        redact=str,
        captured={"notes"},
        values={"notes": notes},
    )


def test_a_quote_no_line_says_gets_no_marker() -> None:
    """FAILS IF: "Extra Details captured" is pinned on a caller line that does not hold the
    details' words."""
    assert _suggested(UNSAID) == []
    assert [m["turn_idx"] for m in _suggested("నాకు గుర్తులేదండి")] == [2]
    # An English reading of the line shares no word with it and is still the model's line.
    assert [m["turn_idx"] for m in _suggested("Did not remember signing up")] == [2]


def test_a_stored_marker_on_a_line_that_does_not_say_it_is_not_shown() -> None:
    stored = [
        {"kind": "field_captured", "turn_idx": 2, "field": "notes", "source": "model"},
        {"kind": "field_captured", "turn_idx": 2, "field": "need", "source": "model"},
        {"kind": "field_captured", "turn_idx": 2, "field": "name", "source": "derived"},
    ]
    texts = {t.idx: t.text for t in TURNS}
    values = {"notes": UNSAID, "need": "Help with the app", "name": UNSAID}
    kept = field_backed(
        stored, captured=set(values), caller_turns={0, 2}, values=values, turn_texts=texts
    )
    assert [m["field"] for m in kept] == ["need", "name"]
    # Without the words the check is skipped, as the turn check is without turns.
    assert len(field_backed(stored, captured=set(values), caller_turns={0, 2})) == 3


def test_the_comparison_keeps_telugu_words_whole() -> None:
    assert said_on("గుర్తులేదండి", SAID)
    assert not said_on("గుర్తు", "గుర్తులేదండి")
    assert said_on("ఏంటండి", SAID)
