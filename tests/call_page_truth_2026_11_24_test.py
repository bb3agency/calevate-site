"""What a finished call left behind after the founder's 24 Nov 2026 12:15 test call.

An outbound call walking an existing customer through installing an app, which ended on the
app's first screen after login. Key moments pinned "Installation Status captured" on the
caller's "Android" and "Setup Progress captured" on "yes, it opened"; and "Setup Progress"
read "Fully operational" for steps the call never reached. The 23 Nov fix asked the model
for the line that settled a status, which the 24 Nov call showed it does not do. Here a
status, progress or outcome of the whole call gets no pin at all, decided in code, and the
extraction prompt says such a value is the furthest step confirmed. The transcripts are
English stand-ins; nothing here names any one business.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest
from apps.api.agents.script_builder import job_details
from apps.api.crm.service import _call_moments, get_call
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers.extraction import ExtractionOutput
from apps.workers.moments import (
    derive_moments,
    field_backed,
    model_moments,
    prompt_line_turns,
)
from apps.workers.pipeline import _persist_extraction
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionSchemaSpec,
    MomentCandidate,
    MomentsBrief,
    build_extraction_prompt,
    whole_call_detail,
)
from calevate_shared.lead_fields import core_fields, with_core
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call


@dataclass(frozen=True)
class _Turn:
    idx: int
    speaker: str
    text: str
    start_ms: int | None
    start_approximate: bool = True


CALL = [
    _Turn(0, "caller", "Hello.", 1_000),
    _Turn(1, "agent", "Is your phone Android or iPhone?", 20_000),
    _Turn(2, "caller", "Android.", 25_000),
    _Turn(3, "agent", "Tap the icon to open the app. Has it opened?", 95_000),
    _Turn(4, "caller", "Yes, it opened.", 102_000),
    _Turn(5, "agent", "Now press the My Farms button. Has that screen come?", 140_000),
]

LABELS = {
    "phone_type": "Phone Type",
    "installation_status": "Installation Status",
    "setup_progress": "Setup Progress",
    "q7": "Call Outcome",
}

READING: dict[str, Any] = {
    "phone_type": "Android",
    "installation_status": "Successfully installed",
    "setup_progress": "Fully operational",
    "q7": "Installation complete",
}


def _stored(turn_idx: int, field: str, label: str) -> dict[str, Any]:
    return {
        "at_ms": 25_000,
        "turn_idx": turn_idx,
        "kind": "field_captured",
        "category": "details",
        "label": label,
        "label_redacted": label,
        "source": "model",
        "precision": "approximate",
        "importance": 2,
        "field": field,
    }


# --- A. the one classifier --------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "label"),
    [
        ("installation_status", "Installation Status"),
        ("setup_progress", "Setup Progress"),
        ("interaction_outcome", "Interaction Outcome"),
        ("q7", "Call Outcome"),
        ("result", ""),
        ("disposition", "Disposition"),
        ("sentiment", "Customer Sentiment"),
    ],
)
def test_a_status_progress_or_outcome_is_read_from_the_whole_call(key: str, label: str) -> None:
    assert whole_call_detail(key, label)


@pytest.mark.parametrize(
    ("key", "label"),
    [("phone_type", "Phone Type"), ("preferred_time", "Call Back Time"), ("statue", "Statue")],
)
def test_a_detail_said_in_one_line_is_not(key: str, label: str) -> None:
    assert not whole_call_detail(key, label)


def test_the_script_builder_asks_by_the_same_classifier() -> None:
    """FAILS IF: the details a script asks and the details that get no pin drift apart."""
    stored = [{"key": k, "label": v} for k, v in LABELS.items()]
    asked = job_details(stored, core_fields({})).labels()
    assert "Phone Type" in asked
    assert not any(whole_call_detail("", label) for label in asked)


# --- A. no pin for a whole-call field, on write ------------------------------------------


def test_the_model_pins_on_android_and_opened_are_dropped() -> None:
    """FAILS IF: "Installation Status captured" stays on "Android." or "Setup Progress
    captured" on "Yes, it opened." (lines 3 and 5 are those caller turns)."""
    placed = model_moments(
        [
            MomentCandidate(line=3, kind="field_captured", field="installation_status"),
            MomentCandidate(line=5, kind="field_captured", field="setup_progress"),
            MomentCandidate(line=5, kind="field_captured", field="q7"),
            MomentCandidate(line=3, kind="field_captured", field="phone_type"),
        ],
        line_turns=prompt_line_turns(CALL),
        field_labels=LABELS,
        redact=str,
        captured=READING.keys(),
        values=READING,
    )
    assert [(m["turn_idx"], m["field"]) for m in placed] == [(2, "phone_type")]


def test_a_status_said_word_for_word_gets_no_derived_pin() -> None:
    turns = [*CALL, _Turn(6, "caller", "Successfully installed, yes.", 150_000)]
    moments = derive_moments(turns=turns, extraction=READING, field_labels=LABELS)
    assert [(m["turn_idx"], m["field"]) for m in moments] == [(2, "phone_type")]


# --- A. calls stored before the rule, on read --------------------------------------------


def test_stored_whole_call_pins_are_dropped_by_key_or_by_label() -> None:
    """A stored marker carries its label, so a key that names nothing still classifies."""
    stored = [
        _stored(2, "installation_status", "Installation Status captured"),
        _stored(4, "q7", "Call Outcome captured"),
        _stored(2, "phone_type", "Phone Type captured"),
    ]
    kept = field_backed(stored, captured=READING.keys(), caller_turns={0, 2, 4})
    assert [m["field"] for m in kept] == ["phone_type"]


async def test_a_call_stored_with_the_wrong_pins_no_longer_shows_them() -> None:
    """FAILS IF: the call page or the lead page still shows a stored status pin."""
    tenant_id, _execution_id, call_id = await _completed_call("wholecall")
    async with tenant_session(tenant_id) as session:
        for turn in CALL:
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, start_ms, created_at, updated_at) VALUES "
                    "(:i, :t, :c, :idx, :s, :x, :x, :ms, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "idx": turn.idx,
                    "s": turn.speaker,
                    "x": turn.text,
                    "ms": turn.start_ms,
                },
            )
    await _persist_extraction(
        tenant_id,
        call_id,
        ExtractionOutput(data=dict(READING), valid=True, errors={}),
        schema_version=1,
        moments=[
            _stored(2, "installation_status", "Installation Status captured"),
            _stored(4, "setup_progress", "Setup Progress captured"),
            _stored(2, "phone_type", "Phone Type captured"),
        ],
    )
    async with tenant_session(tenant_id) as session:
        detail = await get_call(session, call_id, raw=False)
        lead_page = await _call_moments(session, {call_id})
    assert [m.label for m in detail.moments] == ["Phone Type captured"]
    assert lead_page[call_id] == detail.moments


# --- A. the prompt no longer asks for a status pin ---------------------------------------


def _spec() -> ExtractionSchemaSpec:
    return ExtractionSchemaSpec(
        fields=with_core([ExtractionField(key=k, label=v, type="text") for k, v in LABELS.items()])
    )


def test_the_moments_ask_offers_no_whole_call_field() -> None:
    prompt = build_extraction_prompt(_spec(), "caller: hello", moments=MomentsBrief())
    keys_line = next(line for line in prompt.splitlines() if '"field":' in line)
    assert "phone_type" in keys_line
    for key in ("installation_status", "setup_progress", "q7"):
        assert key not in keys_line
    assert "gets no field_captured moment" in prompt
    assert "confirmed that final state" not in prompt


# --- B. a status names the furthest step confirmed ----------------------------------------


@pytest.mark.parametrize("direction", [None, "inbound", "outbound"])
@pytest.mark.parametrize("moments", [None, MomentsBrief()])
def test_a_status_value_is_the_furthest_step_confirmed(
    direction: str | None, moments: MomentsBrief | None
) -> None:
    """FAILS IF: any prompt the extraction sends lets a status claim a state the call did
    not reach ("Fully operational" for a call that stopped at the first screen)."""
    prompt = build_extraction_prompt(_spec(), "caller: hello", moments=moments, direction=direction)
    assert "names the furthest step the caller CONFIRMED on the\n  call" in prompt
    assert "never a later or complete state the call did not reach" in prompt
    assert "When unsure, give the lower\n  state." in prompt
