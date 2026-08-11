"""The model path — the one production actually uses — held to the same rule.

`tests/extraction_offline_test.py` proved the OFFLINE extractor invented three kinds of
fact: the agent's question became the caller's name, a caller saying "ledu" set a
boolean true, and an enum matched inside another word. Those were word-level bugs in a
heuristic CI runs. Production does not run that heuristic. Production sends a PROMPT to
Sarvam (D-36) or Gemini and writes whatever comes back, through one validator, into a
CRM row the SMB acts on instead of listening to the call.

So the same three defects have to be prevented on that path too, and there are exactly
two artefacts standing in the way:

1. `build_extraction_prompt` — the only instruction the model ever gets. If it does not
   say who the speaker labels are, that only `caller:` lines are facts about the
   caller, what a denial means and that an absent value is null, then the model is
   being asked to reproduce those defects and can hardly be blamed for it.
2. `validate_extraction` — the last thing between the model's answer and the CRM.

Neither needs credentials to test, which is the point: this file gates the model path
in CI, where no key is configured. The prompt is tested as an ARTEFACT (delete the
speaker rule and a test goes red), and the validator is driven with hand-written model
responses containing each defect — an invented value, a wrong type, an out-of-enum
value, a phone number where a name belongs.

What this file deliberately does NOT assert: that the validator rejects a well-formed
value the transcript never contained. See
`test_a_plausible_invented_value_is_not_the_validators_job` for why that check would
reject CORRECT answers on this product and where the real gate for it lives.
"""

from __future__ import annotations

import pytest
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionSchemaSpec,
    build_extraction_prompt,
    validate_extraction,
)

# --- The schema the fixtures use, so the assertions are about the real product -----

NAME = ExtractionField(
    key="name", label="Caller name", type="text", description="the caller's own name if they say it"
)
INTENT = ExtractionField(
    key="intent",
    label="Intent",
    type="enum",
    enum_values=["book", "reschedule", "cancel", "enquiry", "complaint"],
    description="what the caller wants to do",
)
PARTY_SIZE = ExtractionField(
    key="party_size", label="People", type="number", description="how many people"
)
WANTS_CALLBACK = ExtractionField(
    key="wants_callback",
    label="Callback requested",
    type="bool",
    description="true only if the caller asked to be called back",
)
CALLBACK_NUMBER = ExtractionField(
    key="callback_number",
    label="Callback number",
    type="text",
    description="the 10-digit number the caller asked to be reached on, digits only",
)
CALLBACK_TIME = ExtractionField(
    key="callback_time",
    label="Callback time",
    type="text",
    description="when the caller asked to be called back, in the caller's own words",
)
WHEN = ExtractionField(key="visit_date", label="Visit date", type="date", description="when")

SPEC = ExtractionSchemaSpec(
    fields=[NAME, INTENT, PARTY_SIZE, WANTS_CALLBACK, CALLBACK_NUMBER, CALLBACK_TIME, WHEN]
)

TRANSCRIPT = (
    "agent: Namaskaram, idi Sunrise Clinic AI assistant. Ee call record avutundi.\n"
    "agent: Mee peru cheppandi.\n"
    "caller: Naa peru Kiran. Appointment book cheyali.\n"
    "agent: Meeku callback avasaram unda?\n"
    "caller: Ledu, avasaram ledu andi."
)


def _prompt() -> str:
    return build_extraction_prompt(SPEC, TRANSCRIPT).lower()


def _requires(*needles: str) -> None:
    """Every needle must appear. Written as substrings of the shipped wording so the
    test fails when the RULE is deleted, not when a comma moves."""
    prompt = _prompt()
    missing = [n for n in needles if n.lower() not in prompt]
    assert not missing, f"the extraction prompt no longer says: {missing}"


# --- 1. The prompt must name the speakers and say whose words are facts -----------


def test_the_prompt_names_the_speaker_labels_the_transcript_actually_uses() -> None:
    """`_persist_transcript` writes `f"{turn.speaker}: {turn.text}"` and `Speaker` is
    `Literal["agent", "caller"]`. A model told nothing about that formatting reads the
    whole thing as one voice — which is precisely how the offline extractor filed the
    agent's question as the caller's name."""
    _requires("agent:", "caller:")


def test_the_prompt_says_only_the_callers_words_are_facts_about_the_caller() -> None:
    _requires("only", "caller")
    prompt = _prompt()
    assert "only `caller:` lines are evidence" in prompt or "only caller: lines" in prompt, (
        "nothing in the prompt restricts evidence to the caller's turns"
    )


def test_the_prompt_forbids_taking_a_value_from_the_agents_question() -> None:
    """Defect 1, in the model's words: "Mee peru cheppandi?" is a request for a name.
    A model that treats it as an answer files a person who does not exist."""
    _requires("mee peru cheppandi", "is a question", "not an answer")


def test_the_prompt_forbids_taking_a_value_from_the_agents_menu_of_options() -> None:
    """The generalisation: the agent offering "book cheyala leda cancel cheyala?" is not
    the caller choosing one."""
    _requires("menu of options", "read-back")


def test_the_prompt_says_a_denial_is_not_a_confirmation() -> None:
    """Defect 2: the caller answering "Ledu" set `wants_callback = true`, and the client
    then rings someone who said no — the harm the do-not-call machinery exists to
    prevent."""
    _requires("ledu", "vaddu", "denial", "false", "never true")


def test_the_prompt_says_an_absent_value_is_null_and_must_not_be_guessed() -> None:
    _requires("null", "never guess")


def test_the_prompt_says_the_empty_calls_are_correctly_empty() -> None:
    """A model asked for eight fields will fill eight fields unless told that a
    wrong-number, hostile or silent call is SUPPOSED to come back almost all null —
    three of the golden fixtures are exactly that."""
    _requires("wrong-number", "silent")


def test_the_prompt_forbids_placeholder_strings_standing_in_for_null() -> None:
    """ "N/A" in a CRM column is a fabricated value with extra steps."""
    _requires("n/a", "unknown", "not provided")


def test_the_prompt_says_an_enum_takes_exactly_one_listed_value() -> None:
    """Defect 3 on the model path: `other` matched inside "brother"."""
    _requires("exactly one", "verbatim", "brother")


def test_the_prompt_protects_the_field_the_smb_actually_acts_on() -> None:
    """A number read aloud as digit words is how Indian callers give a number, and one
    digit wrong is the single worst output this system produces — so the prompt has to
    say both how to assemble it and to return null when unsure."""
    _requires("read aloud", "digits", "one digit")


def test_the_prompt_says_whose_number_it_is_must_have_been_stated() -> None:
    """The relative-number fixture: filing the son's mobile as the patient's own is the
    right value in the wrong column, and the client rings the wrong person."""
    _requires("relative", "not the caller")


def test_the_prompt_keeps_a_relative_time_in_the_callers_own_words() -> None:
    """ "kal subah" resolved to a confident timestamp is off by a day, every day."""
    _requires("kal subah", "own words")


def test_the_prompt_still_carries_the_schema_and_the_transcript() -> None:
    """The regression the rules above could cause: a beautifully principled prompt that
    forgot to ask for the fields."""
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT)
    for field in SPEC.fields:
        assert f'"{field.key}"' in prompt
    assert "book, reschedule, cancel, enquiry, complaint" in prompt
    assert TRANSCRIPT in prompt, "the transcript is not in the prompt at all"
    assert "YYYY-MM-DD" in prompt


def test_both_shipped_model_paths_send_this_exact_prompt() -> None:
    """The rules are worthless if a provider adapter builds its own instruction. Both
    adapters must render the shared prompt, or Gemini and Sarvam disagree about what a
    denial means."""
    import inspect

    import apps.workers.extraction as extraction_module

    for cls in (extraction_module.SarvamExtractor, extraction_module.GeminiExtractor):
        source = inspect.getsource(cls.run)
        assert "build_extraction_prompt(spec, transcript)" in source, (
            f"{cls.__name__} does not send the shared extraction prompt"
        )


# --- 2. The validator, driven with the answers a model actually returns ------------


def test_an_out_of_enum_value_never_reaches_the_crm() -> None:
    """A model inventing a sixth intent must not create a column value no filter,
    export or hot-lead rule knows about."""
    outcome = validate_extraction(SPEC, {"intent": "urgent_booking"})

    assert "intent" not in outcome.data
    assert "intent" in outcome.errors
    assert not outcome.valid


def test_an_enum_returned_as_a_list_is_rejected_not_stringified() -> None:
    """A model asked for one value returns `["book"]` often enough. `str()` turned that
    into the literal text `['book']`."""
    outcome = validate_extraction(SPEC, {"intent": ["book"]})

    assert "intent" not in outcome.data
    assert "intent" in outcome.errors


def test_a_wrong_typed_number_is_rejected_rather_than_coerced_to_nonsense() -> None:
    outcome = validate_extraction(SPEC, {"party_size": "chala mandi"})

    assert "party_size" not in outcome.data
    assert "party_size" in outcome.errors


def test_a_number_field_given_an_object_does_not_become_a_stringified_dict() -> None:
    outcome = validate_extraction(SPEC, {"party_size": {"adults": 2, "children": 1}})

    assert "party_size" not in outcome.data
    assert "party_size" in outcome.errors


def test_a_text_field_given_an_object_does_not_become_a_stringified_dict() -> None:
    """The defect this caught: `str({'first': 'Ravi'})` is `"{'first': 'Ravi'}"` — a
    text column holding Python source, which every export and every screen then shows
    to the client."""
    outcome = validate_extraction(SPEC, {"name": {"first": "Ravi", "last": "Kumar"}})

    assert "name" not in outcome.data
    assert "name" in outcome.errors


def test_a_phone_number_in_a_name_field_never_lands_in_the_crm() -> None:
    """Right value, catastrophically wrong column: the name column now holds a phone
    number, which is PII in a field nobody redacts and a name nobody has."""
    outcome = validate_extraction(SPEC, {"name": "9999999999"})

    assert "name" not in outcome.data, "filed a phone number as the caller's name"
    assert "name" in outcome.errors


def test_a_phone_number_smuggled_into_the_callback_time_is_rejected() -> None:
    """Same defect one field over, and with punctuation, which is how a model writes a
    number it is proud of."""
    outcome = validate_extraction(SPEC, {"callback_time": "+91 99999-99999"})

    assert "callback_time" not in outcome.data
    assert "callback_time" in outcome.errors


def test_the_field_that_asks_for_a_phone_number_still_gets_one() -> None:
    """The other direction, so the fix is not "reject all digits"."""
    outcome = validate_extraction(SPEC, {"callback_number": "9999999999"})

    assert outcome.data["callback_number"] == "9999999999"
    assert outcome.valid


def test_a_speaker_label_is_never_a_value() -> None:
    """The sharpest form of the attribution defect, and one a model does commit: it
    copies the transcript's own label into the field."""
    outcome = validate_extraction(SPEC, {"name": "caller"})

    assert "name" not in outcome.data
    assert "name" in outcome.errors


def test_a_value_that_kept_its_speaker_prefix_is_cleaned_not_filed_raw() -> None:
    """`"caller: Kiran"` is the right answer with the transcript's formatting stuck to
    it. Filing it raw puts `caller: Kiran` on the client's screen."""
    outcome = validate_extraction(SPEC, {"name": "caller: Kiran"})

    assert outcome.data["name"] == "Kiran"


@pytest.mark.parametrize(
    "placeholder", ["N/A", "unknown", "not provided", "-", "null", "None", "teliyadu"]
)
def test_a_placeholder_string_is_read_as_null_not_as_a_name(placeholder: str) -> None:
    """A model that will not say null says "N/A". Stored literally, the client's CRM
    fills up with callers named `Unknown` — a fabricated row that looks captured."""
    outcome = validate_extraction(SPEC, {"name": placeholder})

    assert "name" not in outcome.data, f"filed a caller named {placeholder!r}"
    assert not outcome.errors, "an absent value is null, not a validation failure"


def test_a_placeholder_in_a_required_field_is_still_a_miss() -> None:
    """Reading "N/A" as null must not become a way to satisfy a required field."""
    required = ExtractionField(key="name", label="Caller name", type="text", required=True)
    outcome = validate_extraction(ExtractionSchemaSpec(fields=[required]), {"name": "unknown"})

    assert "name" in outcome.errors
    assert not outcome.valid


def test_a_transcript_pasted_into_a_text_field_is_rejected() -> None:
    """A model that loses the thread returns the whole call in one field. That is not a
    value; it is unredacted transcript text in a CRM column."""
    outcome = validate_extraction(SPEC, {"callback_time": TRANSCRIPT * 40})

    assert "callback_time" not in outcome.data
    assert "callback_time" in outcome.errors


def test_a_denial_word_in_a_boolean_reads_as_false_not_as_truthy_text() -> None:
    """The model path's version of defect 2: the model answers the Telugu word rather
    than a JSON boolean."""
    assert validate_extraction(SPEC, {"wants_callback": "ledu"}).data["wants_callback"] is False
    assert validate_extraction(SPEC, {"wants_callback": "avunu"}).data["wants_callback"] is True


def test_an_unreadable_boolean_is_an_error_not_a_silent_true() -> None:
    outcome = validate_extraction(SPEC, {"wants_callback": "maybe later"})

    assert "wants_callback" not in outcome.data
    assert "wants_callback" in outcome.errors


def test_a_relative_time_is_not_accepted_as_a_date() -> None:
    """ "repu" is not a date, and a date column filled with a guess is a booking on the
    wrong day."""
    outcome = validate_extraction(SPEC, {"visit_date": "repu"})

    assert "visit_date" not in outcome.data
    assert "visit_date" in outcome.errors


def test_a_good_answer_passes_through_unharmed() -> None:
    """The control. Every rejection above is worthless if the validator also rejects
    the extraction we want."""
    outcome = validate_extraction(
        SPEC,
        {
            "name": "Kiran",
            "intent": "book",
            "party_size": "2",
            "wants_callback": True,
            "callback_number": "9999999999",
            "callback_time": "repu udayam pathi gantalaku",
            "visit_date": "2026-08-12",
        },
    )

    assert outcome.valid, outcome.errors
    assert outcome.data == {
        "name": "Kiran",
        "intent": "book",
        "party_size": 2,
        "wants_callback": True,
        "callback_number": "9999999999",
        "callback_time": "repu udayam pathi gantalaku",
        "visit_date": "2026-08-12",
    }


def test_a_native_telugu_script_answer_survives_validation() -> None:
    """Telugu-first is the product. A validator that quietly drops the script form
    would fail the market it was built for."""
    outcome = validate_extraction(SPEC, {"name": "స్వాతి"})

    assert outcome.data["name"] == "స్వాతి"


def test_a_plausible_invented_value_is_not_the_validators_job() -> None:
    """The deliberate boundary, recorded so nobody "fixes" it by accident.

    A validator cannot check that a value was said, because on THIS product the correct
    answer is usually not in the transcript verbatim: `party_size` 3 comes from
    "muggurum", and `callback_number` 9999999999 comes from "tommidi tommidi ...".
    A presence check would reject those CORRECT answers and downgrade them to a missing
    field — which the eval baseline is allowed to waive, so the gate would get WEAKER.

    Fabrication is gated where it can be gated honestly: by the prompt rules above, and
    by `scripts/eval.py`, which scores a fabricated field as `restraint` and a wrong one
    as `capture_wrong` — neither of them waivable on any model.
    """
    outcome = validate_extraction(SPEC, {"name": "Ramesh"})

    assert outcome.data["name"] == "Ramesh"
    assert outcome.valid
