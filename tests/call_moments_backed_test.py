"""A "<field> captured" marker appears only for a field the reading holds, on the caller's
turn that gave it.

The specimen is the founder's trial call of 30 Oct 2026 (Sri Estates, outbound): the page
showed "Location captured · Suggested" under the agent's question "are you still looking?"
while the details listed Location as "Not mentioned". The model had suggested a
`field_captured` moment for a field its own answer left null, on an agent line.

Run: uv run pytest -q tests/call_moments_backed_test.py
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
from calevate_shared.cut_off import likely_cut_off
from calevate_shared.extraction import MomentCandidate
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call


@dataclass(frozen=True)
class _Turn:
    idx: int
    speaker: str
    text: str
    start_ms: int | None
    start_approximate: bool = True


_REPEAT = "అవునండి, శ్రీ ఎస్టేట్స్ నుంచి కాల్ చేస్తున్నాను. మీరు ఏ ఏరియాలో ప్రాపర్టీ చూస్తున్నారు?"

#: The call as the page showed it, times in ms. Lines 10 onwards carry no shown time in the
#: report; they are spaced as the earlier exchanges were.
SRI_ESTATES = [
    _Turn(0, "caller", "Hello.", 1_000),
    _Turn(1, "agent", "నమస్కారం అండి, Sri-Estates నుంచి call చేస్తున్నాను. ఇప్పుడు మాట్లాడొచ్చా?", 2_000),
    _Turn(2, "caller", "Sri Estates.", 9_000),
    _Turn(3, "agent", "మీరు ఇంతకు ముందు ప్రాపర్టీ గురించి ఎంక్వైరీ చేశారు కదా, ఇంకా చూస్తున్నారా అండి?", 10_000),
    _Turn(4, "caller", "Yes.", 17_000),
    _Turn(5, "agent", "సంతోషం అండి. మీరు ఏ ఏరియాలో ప్రాపర్టీ చూస్తున్నారు?", 18_000),
    _Turn(6, "caller", "Ah.", 25_000),
    _Turn(7, "agent", "పర్లేదు అండి, మీకు ఏ ఏరియాలో అయితే బాగుంటుంది అనిపిస్తుందో చెప్తారా?", 26_000),
    _Turn(8, "caller", "Sri Estates.", 26_000),
    _Turn(9, "agent", _REPEAT, 27_000),
    _Turn(10, "caller", "Sri Estates.", 34_000),
    _Turn(11, "agent", _REPEAT, 35_000),
    _Turn(12, "caller", "Sri Estates.", 42_000),
    _Turn(13, "agent", _REPEAT, 43_000),
    _Turn(14, "caller", "Sri Estates.", 50_000),
    _Turn(15, "agent", _REPEAT, 51_000),
]

#: What the reading held: a language and a note, no location.
READING: dict[str, Any] = {"language": "Telugu", "notes": "Kept repeating the company name"}

LABELS = {"preferred_location": "Location", "notes": "Notes"}


def _suggest(*candidates: MomentCandidate, captured: Any = tuple(READING)) -> list[Any]:
    return model_moments(
        list(candidates),
        line_turns=prompt_line_turns(SRI_ESTATES),
        field_labels=LABELS,
        redact=str,
        captured=captured,
        unheard=likely_cut_off(SRI_ESTATES),
    )


# --- the writer -------------------------------------------------------------------------


def test_the_founders_call_carries_no_location_marker() -> None:
    """Line 4 is the agent asking whether they are still looking; Location was not captured."""
    location = MomentCandidate(line=4, kind="field_captured", field="preferred_location")
    assert _suggest(location) == []


def test_a_field_the_reading_left_empty_has_no_marker_even_on_a_caller_line() -> None:
    on_caller = MomentCandidate(line=5, kind="field_captured", field="preferred_location")
    assert _suggest(on_caller) == []


def test_a_captured_field_suggested_on_an_agent_line_has_no_marker() -> None:
    on_agent = MomentCandidate(line=4, kind="field_captured", field="notes")
    assert _suggest(on_agent) == []


def test_a_captured_field_on_the_callers_line_keeps_its_marker() -> None:
    placed = _suggest(MomentCandidate(line=5, kind="field_captured", field="notes"))
    assert [(m["turn_idx"], m["label"], m["source"]) for m in placed] == [
        (4, "Notes captured", "model")
    ]


def test_other_kinds_are_not_held_to_the_field_rule() -> None:
    """A price is the agent's line by definition; only captured details need the caller."""
    quoted = MomentCandidate(line=4, kind="price_quoted", label="Quoted a price")
    assert [m["turn_idx"] for m in _suggest(quoted, captured=())] == [3]


def test_a_derived_marker_lands_on_the_callers_answer_not_the_agents_question() -> None:
    """The agent names the area first; the earliest verbatim match used to be its question."""
    turns = [
        _Turn(0, "agent", "Kondapur or Gachibowli, which one?", 1_000, False),
        _Turn(1, "caller", "Kondapur is better for us.", 6_000, False),
    ]
    moments = derive_moments(
        turns=turns, extraction={"preferred_location": "Kondapur"}, field_labels=LABELS
    )
    assert [(m["turn_idx"], m["label"]) for m in moments] == [(1, "Location captured")]


def test_a_value_only_the_agent_said_has_no_derived_marker() -> None:
    turns = [_Turn(0, "agent", "Shall I note Kondapur?", 1_000), _Turn(1, "caller", "Ok.", 4_000)]
    assert (
        derive_moments(turns=turns, extraction={"preferred_location": "Kondapur"}, field_labels={})
        == []
    )


# --- stored rows ------------------------------------------------------------------------


def _stored(kind: str, turn_idx: int | None, field: str | None = None) -> dict[str, Any]:
    return {
        "at_ms": 10_000,
        "turn_idx": turn_idx,
        "kind": kind,
        "category": "details",
        "label": "Location captured",
        "label_redacted": "Location captured",
        "source": "model",
        "precision": "approximate",
        "importance": 2,
        "field": field,
    }


def test_stored_rows_lose_the_unbacked_field_markers_only() -> None:
    stored = [
        _stored("field_captured", 3, "preferred_location"),
        _stored("field_captured", 3, "notes"),
        _stored("field_captured", 4, "notes"),
        _stored("complaint", 3),
    ]
    kept = field_backed(stored, captured={"notes"}, caller_turns={0, 2, 4})
    assert [(m["kind"], m["turn_idx"], m["field"]) for m in kept] == [
        ("field_captured", 4, "notes"),
        ("complaint", 3, None),
    ]


def test_without_turns_only_the_field_is_checked() -> None:
    """The lead page reads markers without the transcript."""
    stored = [_stored("field_captured", 3, "notes"), _stored("field_captured", 3, "location")]
    kept = field_backed(stored, captured={"notes"}, caller_turns=None)
    assert [m["field"] for m in kept] == ["notes"]


def test_anything_that_is_not_a_list_is_left_for_the_reader() -> None:
    assert field_backed(None, captured=(), caller_turns=None) is None
    assert field_backed({"x": 1}, captured=(), caller_turns=()) == {"x": 1}


async def test_a_row_stored_before_the_rule_no_longer_shows_on_either_page() -> None:
    """The founder's call is already stored; the read path drops its marker without a
    backfill, on the call page and on the lead page."""
    tenant_id, _execution_id, call_id = await _completed_call("backed")
    async with tenant_session(tenant_id) as session:
        for turn in SRI_ESTATES[:6]:
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
            _stored("field_captured", 3, "preferred_location"),
            _stored("field_captured", 3, "notes"),
            _stored("field_captured", 4, "notes"),
        ],
    )
    async with tenant_session(tenant_id) as session:
        detail = await get_call(session, call_id, raw=False)
        lead_page = await _call_moments(session, {call_id})
    assert [m.turn_idx for m in detail.moments] == [4]
    assert sorted(m.turn_idx or 0 for m in lead_page[call_id]) == [3, 4], (
        "the lead page has no turns, so it checks the field only"
    )
