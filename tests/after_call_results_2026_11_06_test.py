"""What the call page said after the founder's 6 Nov 2026 test call (Rytu Khata, Varsha).

Four things read wrong: a summary that called the caller "him", details filed from the
agent's own explanation and from a question the caller pushed back on, a next step written
as "The business needs to ...", and key moments drawn as empty numbered rows.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from apps.api.crm.service import _moments_out
from apps.workers.call_language import _prompt as language_pass_prompt
from apps.workers.moments import model_moments, prompt_line_turns
from apps.workers.pipeline import _settle_summaries
from apps.workers.redaction import redact
from calevate_shared.extraction import (
    MOMENT_KINDS,
    PHONE_NEEDS_REVIEW,
    ExtractionField,
    ExtractionSchemaSpec,
    MomentCandidate,
    build_extraction_prompt,
    genders_a_person,
    owner_step,
    validate_extraction,
)
from calevate_shared.lead_fields import with_core

FIXTURES = Path(__file__).parent / "fixtures" / "golden_transcripts.json"


def _prompt() -> str:
    return build_extraction_prompt(
        ExtractionSchemaSpec(fields=with_core([])), "caller: hello", languages=("te-IN",)
    )


# --- 1. the summary names no gender the caller did not state ----------------------------


def test_the_prompt_keeps_the_caller_neutral() -> None:
    prompt = _prompt()
    assert 'call the person "the caller" or\n  "they", never "he", "she"' in prompt
    assert "only when the caller\n  said it of themselves" in prompt


def test_the_language_pass_keeps_the_english_summary_neutral() -> None:
    prompt = language_pass_prompt(
        language="Telugu",
        tag="te-IN",
        turns=[(0, "నమస్కారం")],
        summary_en="",
        summary_local="అయిపోయింది, స్టార్ట్ చేశాను చెప్పండి.",
        want_summaries=True,
    )
    assert 'Call the person "the caller" or "they", never "he" or "she"' in prompt


def test_a_pronoun_is_recognised_as_a_word_not_a_letter_run() -> None:
    assert genders_a_person("After the agent guided him through it.")
    assert genders_a_person("She installed the app.")
    assert not genders_a_person("They installed the app; the caller heard the help line.")
    assert not genders_a_person("")


def test_our_neutral_summary_replaces_an_engine_summary_that_genders_the_caller() -> None:
    english, _, source, _ = _settle_summaries(
        engine_summary="The agent guided him through installing it on his Android phone.",
        model_summary="The caller installed the app with the agent's help.",
        stored_local="",
        language="te-IN",
    )
    assert (english, source) == (
        "The caller installed the app with the agent's help.",
        "extraction",
    )


def test_the_engine_summary_still_stands_when_ours_is_missing_or_gendered_too() -> None:
    gendered = "The agent guided him through installing it."
    for model_summary in ("", "He installed it."):
        english, _, source, _ = _settle_summaries(
            engine_summary=gendered, model_summary=model_summary, stored_local="", language="te-IN"
        )
        assert (english, source) == (gendered, "engine")
    # A neutral engine summary keeps its precedence (founder decision 12).
    english, _, source, _ = _settle_summaries(
        engine_summary="The caller installed the app.",
        model_summary="Model words.",
        stored_local="",
        language="te-IN",
    )
    assert (english, source) == ("The caller installed the app.", "engine")


# --- 2. only the caller's own words are details ----------------------------------------


def test_the_agents_explanation_is_never_the_callers_purpose() -> None:
    prompt = _prompt()
    assert "BUSINESS's description, never the caller's reason, need, purpose or use" in prompt
    assert 'answers it with "yes", "okay" or "understood" heard it; they did not say it' in prompt


def test_a_pushed_back_question_is_not_a_yes() -> None:
    prompt = _prompt()
    assert "A question the caller pushed back on, or answered with a question of their own" in (
        prompt
    )
    assert "was not answered yes" in prompt
    assert "The agent's question taking it for granted is not evidence." in prompt


def test_the_golden_set_carries_both_shapes_as_restraint_cases() -> None:
    payload = json.loads(FIXTURES.read_text(encoding="utf-8"))
    cases = {case["id"]: case for case in payload["cases"]}
    keys = {field["key"] for field in payload["schema"]}
    for case_id in (
        "en_agent_explanation_is_not_the_callers_need",
        "en_pushed_back_question_is_not_a_yes",
    ):
        case = cases[case_id]
        # Every field must stay empty: the values on the call are all the agent's.
        assert set(case["expect_absent"]) == keys
        caller_lines = [t for t in case["transcript"] if t.startswith("caller:")]
        agent_lines = [t for t in case["transcript"] if t.startswith("agent:")]
        assert any("BHK" in t for t in agent_lines)
        assert not any("BHK" in t for t in caller_lines)


# --- 3. the next step is the owner's own instruction ----------------------------------


def test_the_prompt_asks_for_the_step_as_the_owners_instruction() -> None:
    prompt = _prompt()
    assert "write it as an instruction to the owner that\n  starts with the verb" in prompt
    assert 'never "The business needs to ..."' in prompt
    assert 'next_step is "Call them back"' in prompt
    assert "next_step says the business calls them back" not in prompt


def test_a_step_about_the_business_reads_as_a_step_for_the_owner() -> None:
    assert owner_step(
        "The business needs to guide the caller on how to start tracking their farming "
        "details in the app."
    ) == ("Guide the caller on how to start tracking their farming details in the app.")
    assert owner_step("Business should call them back tomorrow.") == "Call them back tomorrow."
    assert owner_step("The business team must send the price list.") == "Send the price list."
    assert owner_step("The owner has to confirm the visit.") == "Confirm the visit."
    # Anything else is the reading's own sentence and stays as written.
    for kept in (
        "Call them back.",
        "They will message if they get stuck.",
        "The business is closed",
    ):
        assert owner_step(kept) == kept


# --- 4. a key moment always has words ---------------------------------------------------


def _stored(label: Any, *, source: str = "model") -> dict[str, Any]:
    return {
        "at_ms": 4_000,
        "turn_idx": 1,
        "kind": "complaint",
        "category": "attention",
        "label": label,
        "label_redacted": label,
        "source": source,
        "precision": "approximate",
        "importance": 2,
    }


def test_a_stored_moment_with_no_words_is_not_sent() -> None:
    stored = [_stored(""), _stored("  "), _stored("Asked how to use the app")]
    for raw in (False, True):
        assert [m.label for m in _moments_out(stored, raw=raw)] == ["Asked how to use the app"]


def test_a_new_moment_never_stores_blank_words() -> None:
    turns = [
        SimpleNamespace(idx=0, speaker="agent", text="Hello.", start_ms=0, start_approximate=False),
        SimpleNamespace(
            idx=1,
            speaker="caller",
            text="How do I use it?",
            start_ms=4_000,
            start_approximate=False,
        ),
    ]
    placed = model_moments(
        [
            MomentCandidate(line=2, kind="complaint", label="   "),
            MomentCandidate(line=2, kind="field_captured", field="need", label="x"),
        ],
        line_turns=prompt_line_turns(turns),
        field_labels={"need": "  "},
        redact=lambda label: redact(label).text,
        captured={"need"},
    )
    assert placed, "both suggestions sit on a caller line with a time"
    for marker in placed:
        assert marker["label"].strip() and marker["label_redacted"].strip()
    by_kind = {m["kind"]: m for m in placed}
    assert by_kind["complaint"]["label"] == MOMENT_KINDS["complaint"][1]
    assert by_kind["field_captured"]["label"] == "Need captured"


def test_a_label_redaction_empties_falls_back_to_the_kinds_words() -> None:
    turns = [
        SimpleNamespace(
            idx=0, speaker="caller", text="Hello", start_ms=1_000, start_approximate=False
        )
    ]
    placed = model_moments(
        [MomentCandidate(line=1, kind="complaint", label="Upset")],
        line_turns=prompt_line_turns(turns),
        field_labels={},
        redact=lambda _label: "",
        captured=set(),
    )
    assert [m["label_redacted"] for m in placed] == [MOMENT_KINDS["complaint"][1]]


# --- 6. the other sentences the reading writes for the call page -------------------------


def test_a_doubtful_number_says_so_without_naming_the_field_twice() -> None:
    field = ExtractionField(key="callback_number", label="Callback number", type="text")
    outcome = validate_extraction(
        ExtractionSchemaSpec(fields=[field]), {"callback_number": "1234567890"}
    )
    note = outcome.needs_review["callback_number"]
    assert note == PHONE_NEEDS_REVIEW
    assert "Callback number" not in note and "1234567890" not in note
    assert note.endswith("Check it before you call.")
