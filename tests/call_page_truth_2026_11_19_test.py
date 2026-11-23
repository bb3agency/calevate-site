"""What a call page says about a call must be what the call said (19 Nov 2026 call review).

An outbound five-minute call showed four "Key moments", three of them on the wrong line: a
final "using it: yes" on the line where the person said they were not using it, a note on
an unrelated line, and a purpose on a later step-by-step request. Its summary said the call
"ended with the customer satisfied" (never said; the call was cut off), spelt the business's
own name with scholarly marks, and its details listed the person's name as "Not mentioned"
beside a contact list that held it. The transcripts here are English stand-ins; the code
they exercise has no wording for any one business.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from apps.api.crm import service as crm
from apps.api.crm.captured import with_list_columns
from apps.api.crm.schemas import CapturedFieldOut
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.extraction import OfflineExtractor
from apps.workers.moments import derive_moments, model_moments, prompt_line_turns
from apps.workers.pipeline import _settle_summaries
from apps.workers.redaction import redact
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionSchemaSpec,
    MomentCandidate,
    MomentsBrief,
    asserts_feeling,
    build_extraction_prompt,
    spell_business_name,
    without_feelings,
)
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call


@dataclass
class _Turn:
    idx: int
    speaker: str
    text: str
    start_ms: int | None
    start_approximate: bool = True


CALL = [
    _Turn(0, "caller", "Hello.", 3_000),
    _Turn(1, "agent", "Hello, I am calling about the app you registered on.", 3_000),
    _Turn(2, "caller", "Go ahead.", 12_000),
    _Turn(3, "agent", "Are you using it through a web browser or as an app?", 12_000),
    _Turn(4, "caller", "Actually I am not using it, I don't remember registering.", 37_000),
    _Turn(5, "agent", "No problem. What would you like it for?", 60_000),
    _Turn(6, "caller", "I want to keep a record of my daily expenses.", 65_000),
    _Turn(7, "agent", "Is your phone Android or iPhone?", 94_000),
    _Turn(8, "caller", "Android.", 104_000),
    _Turn(9, "agent", "Enter your mobile number and password.", 145_000),
    _Turn(10, "caller", "No password, so I used forgot password and logged in.", 168_000),
    _Turn(11, "agent", "Open settings, pick your language and add your first entry.", 168_000),
    _Turn(12, "caller", "Tell me one step at a time, slowly.", 200_000),
    _Turn(13, "agent", "Sure. Tap the plus button.", 200_000),
    _Turn(14, "caller", "Done, I am using it now.", 230_000),
]

LABELS = {
    "currently_using": "Is currently using the app?",
    "notes": "Notes",
    "purpose": "Purpose of usage",
}
VALUES: dict[str, Any] = {
    "currently_using": True,
    "notes": "Forgot the password and logged in with forgot password.",
    "purpose": "Keep a record of daily expenses",
}


def _line_of(idx: int) -> int:
    lines = prompt_line_turns(CALL)
    return next(n for n, turn in enumerate(lines, 1) if turn.idx == idx)


def _placed(*candidates: MomentCandidate) -> dict[str, int]:
    placed = model_moments(
        list(candidates),
        line_turns=prompt_line_turns(CALL),
        field_labels=LABELS,
        redact=lambda label: redact(label).text,
        captured=VALUES.keys(),
        values=VALUES,
        denies=OfflineExtractor.denies,
    )
    return {str(m["field"]): int(m["turn_idx"]) for m in placed}


def _field_moment(field: str, turn_idx: int) -> MomentCandidate:
    return MomentCandidate(line=_line_of(turn_idx), kind="field_captured", field=field)


# --- 1. a key moment sits on the line that supports the final value -----------------------


def test_a_yes_is_never_pinned_on_the_line_that_said_no() -> None:
    """The 0:37 marker: "using it: yes" on "I am not using it". Which later line settled it a
    word match cannot tell, so the marker goes rather than pointing at the opposite."""
    assert _placed(_field_moment("currently_using", 4)) == {}
    assert _placed(_field_moment("currently_using", 14)) == {"currently_using": 14}


def test_a_note_moves_to_the_line_it_is_about() -> None:
    """The 1:44 marker: a password note on the caller's "Android."."""
    assert _placed(_field_moment("notes", 8)) == {"notes": 10}


def test_a_purpose_moves_off_a_later_unrelated_line() -> None:
    """The 3:20 marker: the purpose on "Tell me one step at a time"."""
    assert _placed(_field_moment("purpose", 12)) == {"purpose": 6}


def test_a_detail_pinned_on_the_agents_explanation_moves_to_the_callers_words() -> None:
    assert _placed(_field_moment("purpose", 5)) == {"purpose": 6}


def test_a_line_that_supports_the_value_is_kept_as_the_model_chose_it() -> None:
    assert _placed(_field_moment("notes", 10), _field_moment("purpose", 6)) == {
        "notes": 10,
        "purpose": 6,
    }


def test_a_value_in_words_no_line_shares_keeps_the_models_line() -> None:
    """A value written in other words (a translation) proves nothing either way."""
    placed = model_moments(
        [_field_moment("purpose", 12)],
        line_turns=prompt_line_turns(CALL),
        field_labels=LABELS,
        redact=lambda label: redact(label).text,
        captured={"purpose"},
        values={"purpose": "Bookkeeping"},
    )
    assert [m["turn_idx"] for m in placed] == [12]


def test_a_derived_marker_anchors_the_final_mention_and_never_a_bare_yes() -> None:
    turns = [
        _Turn(0, "agent", "Kondapur or Gachibowli?", 1_000),
        _Turn(1, "caller", "Not Gachibowli, Kondapur. Yes.", 6_000),
        _Turn(2, "caller", "Actually Gachibowli is better. Yes.", 12_000),
    ]
    moments = derive_moments(
        turns=turns,
        extraction={"area": "Gachibowli", "agreed": "Yes"},
        field_labels={"area": "Area", "agreed": "Agreed"},
    )
    assert [(m["field"], m["turn_idx"]) for m in moments] == [("area", 2)]


def test_the_prompt_asks_for_the_line_that_settled_the_value() -> None:
    spec = ExtractionSchemaSpec(fields=[ExtractionField(key="notes", label="Notes", type="text")])
    prompt = build_extraction_prompt(spec, "caller: hi", moments=MomentsBrief())
    assert "on the\n  caller's line that settled THAT value" in prompt
    assert "never on an\n  earlier line that began the subject" in prompt


# --- 2. the summary says what was said, and no feeling nobody stated -----------------------

ENGINE = (
    "The customer did not know the app and was helped to install it. "
    "The call ended with the customer satisfied."
)


def test_a_feeling_or_a_good_ending_is_recognised() -> None:
    assert asserts_feeling("The call ended with the customer satisfied.")
    assert asserts_feeling("They were happy with the help.")
    assert asserts_feeling("The call ended on a positive note.")
    assert not asserts_feeling("The caller installed the app and asked how to add an entry.")


def test_our_summary_replaces_an_engine_summary_that_states_a_feeling() -> None:
    ours = "The caller had not used the app and was walked through installing it."
    english, _, source, _ = _settle_summaries(
        engine_summary=ENGINE, model_summary=ours, stored_local="", language="te-IN"
    )
    assert (english, source) == (ours, "extraction")


def test_without_ours_the_engine_summary_stands_without_the_feeling() -> None:
    english, _, source, _ = _settle_summaries(
        engine_summary=ENGINE, model_summary="", stored_local="", language="te-IN"
    )
    assert (english, source) == (
        "The customer did not know the app and was helped to install it.",
        "engine",
    )
    assert without_feelings("They were happy.") == "They were happy.", "never emptied"


def test_the_prompt_forbids_a_feeling_or_an_ending_nobody_said() -> None:
    prompt = build_extraction_prompt(ExtractionSchemaSpec(fields=[]), "caller: hi")
    assert "Never say how the caller felt" in prompt
    assert "A call that stops in the middle of a sentence ended there" in prompt
    assert "a detail you\n  left null is not stated in it" in prompt


# --- 3. names are written as the business spells them ------------------------------------


def test_a_name_written_with_marks_is_spelt_the_business_way() -> None:
    marked = f"Rai{chr(0x1E6D)}u Kh{chr(0x101)}t{chr(0x101)}"
    summary = f'The customer did not know about the "{marked}" app.'
    assert spell_business_name(summary, "Rytu Khata") == (
        'The customer did not know about the "Rytu Khata" app.'
    )
    combining = f"Uses Rait{chr(0x323)}u Kha{chr(0x304)}ta{chr(0x304)} daily."
    assert spell_business_name(combining, "Rytu Khata") == "Uses Rytu Khata daily."
    assert spell_business_name("Rytu Khata", "Rytu Khata") == "Rytu Khata"


def test_the_prompt_names_the_business_and_the_agent_and_forbids_marks() -> None:
    prompt = build_extraction_prompt(
        ExtractionSchemaSpec(fields=[]),
        "caller: hi",
        business_name="Acme Ledger",
        agent_name="Asha",
    )
    assert 'The business is called "Acme Ledger".' in prompt
    assert 'Its agent on the call is called "Asha".' in prompt
    assert "never\nwith accents or marks" in prompt
    assert "Its agent" not in build_extraction_prompt(ExtractionSchemaSpec(fields=[]), "caller: hi")


# --- 4. what the contact list already said is shown, not "Not mentioned" -----------------


def _field(key: str, label: str, value: Any = None, type_: str = "text") -> CapturedFieldOut:
    return CapturedFieldOut(
        key=key,
        label=label,
        type=type_,
        core=False,
        current=True,
        value=value,  # type: ignore[arg-type]
    )


def test_an_empty_detail_a_list_column_names_is_filled_from_the_list() -> None:
    fields = [
        _field("village_name", "Village"),
        _field("crop", "Main crop", value="said on the call"),
        _field("visits", "Visits", type_="number"),
        _field("caller_name", "Caller Name"),
    ]
    filled = with_list_columns(
        fields,
        columns={"Village Name": " Kondapur ", "Main crop": "x", "Visits": "3", "Caller name": ""},
    )
    assert (filled[0].value, filled[0].source) == ("Kondapur", "list")
    assert (filled[1].value, filled[1].source) == ("said on the call", "call"), "call wins"
    assert (filled[2].value, filled[2].source) == (3, "list"), "a number cell, as a number"
    assert filled[3].value is None, "a blank cell fills nothing"
    assert with_list_columns(fields, columns=None) == fields


async def test_the_call_page_shows_a_list_column_the_call_did_not_capture() -> None:
    tenant_id, _execution_id, call_id = await _completed_call("listcols")
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        agent_id, phone = (
            await session.execute(
                text("SELECT agent_id, from_e164 FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).one()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, status, classification, "
                "created_at, updated_at) VALUES (:c, :t, :a, 'Onboarding', 'running', 'service', "
                "now(), now())"
            ),
            {"c": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, name, "
                "custom, status, attempts, created_at, updated_at) VALUES (:i, :t, :c, :p, "
                "'Listed Person', CAST(:custom AS jsonb), 'completed', 1, now(), now())"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "c": campaign_id,
                "p": phone,
                "custom": '{"Preferred time": "Evenings"}',
            },
        )
        await session.execute(
            text("UPDATE calls SET campaign_id = :g, status = 'completed' WHERE id = :c"),
            {"g": campaign_id, "c": call_id},
        )
        detail = await crm.get_call(session, call_id)
    by_key = {f.key: f for f in detail.captured}
    assert (by_key["preferred_time"].value, by_key["preferred_time"].source) == (
        "Evenings",
        "list",
    )
    assert (by_key["name"].value, by_key["name"].source) == ("Listed Person", "list")
