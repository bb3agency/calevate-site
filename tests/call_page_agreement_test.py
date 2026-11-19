"""The lead page, the call page, the webhook and the post-call reading say one thing about a
call (19 Nov 2026 audit of the call page).

A key moment on the lead page kept the vendor's written-down time and skipped the caller
line check the call page makes; "Caller spoke over this part" was measured from a different
time than the reading that decided which lines went unheard; a list column the call page
showed was missing on the lead page and filled only text details; and the feeling filter
dropped a complaint whole with the facts inside it. The wording here is English stand-in
text; none of the code under test has words for any one business or language.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
from apps.api.campaigns import notes
from apps.api.crm import service as crm
from apps.api.crm.captured import with_list_columns
from apps.api.crm.routes import get_lead_captured
from apps.api.crm.schemas import CapturedFieldOut
from apps.api.crm.turn_times import TimedLine, line_times
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import parse_timeline, parse_transcript
from apps.workers import call_translation
from apps.workers.call_language import LanguagePass
from apps.workers.extraction import ExtractionOutput
from apps.workers.pipeline import _persist_extraction, _settle_summaries
from calevate_shared.cut_off import likely_cut_off_rows
from calevate_shared.extraction import ExtractionField, without_feelings
from sqlalchemy import text
from tests.agent_lifecycle_test import _tenant
from tests.call_turn_times_test import ANSWERED, VENDOR_TIMELINE, VENDOR_TURNS
from tests.pipeline_audit_test import _completed_call

#: 489 characters, about 24.5 s to say: inside the gap from where it was written down (12.5 s)
#: to the caller's next line (37 s), outside the gap from where the timeline heard it (14.3 s).
LONG_AGENT_LINE = ("word " * 98).strip()


async def _vendor_call(*, agent_line: str = "You registered.") -> tuple[UUID, UUID]:
    """A completed call holding the vendor-shaped transcript and timeline."""
    tenant_id, _execution_id, call_id = await _completed_call("agree")
    shaped = [dict(t) for t in VENDOR_TURNS]
    shaped[3]["text"] = agent_line
    turns, _lost = parse_transcript(shaped, "c1", answered=datetime.fromisoformat(ANSWERED))
    async with tenant_session(tenant_id) as session:
        for turn in turns:
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, start_ms, start_approximate, created_at, updated_at) VALUES "
                    "(:i, :t, :c, :idx, :s, :x, :x, :ms, :approx, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "idx": turn.idx,
                    "s": turn.speaker,
                    "x": turn.text,
                    "ms": turn.start_ms,
                    "approx": turn.start_approximate,
                },
            )
        await session.execute(
            text(
                "UPDATE calls SET status = 'completed', "
                "engine_timeline = CAST(:tl AS jsonb) WHERE id = :c"
            ),
            {"tl": parse_timeline(VENDOR_TIMELINE).model_dump_json(), "c": call_id},
        )
    return tenant_id, call_id


def _marker(turn_idx: int, at_ms: int) -> dict[str, Any]:
    return {
        "at_ms": at_ms,
        "turn_idx": turn_idx,
        "kind": "field_captured",
        "field": "slot",
        "label": "Slot captured",
        "label_redacted": "Slot captured",
        "source": "derived",
        "precision": "approximate",
    }


# --- 1. a moment on the lead page is the moment on the call page -------------------------


async def test_the_lead_page_times_and_filters_a_moment_as_the_call_page_does() -> None:
    tenant_id, call_id = await _vendor_call()
    await _persist_extraction(
        tenant_id,
        call_id,
        ExtractionOutput(data={"slot": "Tuesday"}, valid=True, errors={}),
        schema_version=1,
        # On the caller's "Not using it." (written at 37 s) and on the agent's answer after.
        moments=[_marker(4, 37_000), _marker(5, 37_300)],
    )
    async with tenant_session(tenant_id) as session:
        page = (await crm.get_call(session, call_id)).moments
        lead = (await crm._call_moments(session, {call_id}))[call_id]
    assert lead == page
    # Only the caller line's marker, played from where the transcript plays that line.
    assert [(m.turn_idx, m.at_ms) for m in lead] == [(4, 14_300)]


# --- 6. "Caller spoke over this part" is the reading's own measure -----------------------


async def test_the_page_flags_the_lines_the_reading_treated_as_unheard() -> None:
    tenant_id, call_id = await _vendor_call(agent_line=LONG_AGENT_LINE)
    async with tenant_session(tenant_id) as session:
        detail = await crm.get_call(session, call_id)
    flagged = {t.idx for t in detail.transcript if t.likely_cut_off}
    turns, _lost = parse_transcript(
        [dict(t, text=LONG_AGENT_LINE) if i == 3 else t for i, t in enumerate(VENDOR_TURNS)],
        "c1",
        answered=datetime.fromisoformat(ANSWERED),
    )
    # What the pipeline's `likely_cut_off` reads: the stored written-down times.
    reading = likely_cut_off_rows((t.idx, t.speaker, len(t.text), t.start_ms) for t in turns)
    assert flagged == set(reading) == set()
    placed = line_times(
        [TimedLine(t.idx, t.speaker, t.start_ms, t.start_approximate) for t in turns],
        parse_timeline(VENDOR_TIMELINE),
    )
    from_placed = likely_cut_off_rows(
        (t.idx, t.speaker, len(t.text), (placed[t.idx] if t.speaker == "agent" else t).start_ms)
        for t in turns
    )
    assert from_placed == {3}, "the case where the two measures part, so the test can tell"


# --- 4/5. a feeling nobody said goes; the facts and requests beside it stay -------------


def test_a_complaint_keeps_its_facts_and_its_request() -> None:
    assert (
        without_feelings("Caller is upset that the delivery is a week late and wants a refund.")
        == "Caller said the delivery is a week late and wants a refund."
    )
    assert (
        without_feelings("The caller was frustrated but agreed to a call back tomorrow.")
        == "The caller agreed to a call back tomorrow."
    )
    assert (
        without_feelings("The caller was unhappy about the late delivery and asked for a refund.")
        == "The caller spoke about the late delivery and asked for a refund."
    )


def test_a_satisfied_ending_on_a_cut_off_call_goes() -> None:
    summary = "The customer asked how to add an entry. The customer was satisfied."
    assert without_feelings(summary) == "The customer asked how to add an entry."
    assert (
        without_feelings("They were happy with the price and the delivery time. They paid.")
        == "They paid."
    )


def test_a_feeling_the_caller_named_is_theirs_and_stays() -> None:
    summary = "The caller was upset with the delay."
    assert without_feelings(summary, said="I am really upset with this delay") == summary


def test_our_own_english_gets_the_same_check() -> None:
    english, _local, source, _ = _settle_summaries(
        engine_summary="",
        model_summary="The caller asked for a refund. The caller was satisfied.",
        stored_local="",
        language="te-IN",
    )
    assert (english, source) == ("The caller asked for a refund.", "extraction")


def test_an_engine_call_language_summary_beside_cleaned_english_is_written_again() -> None:
    # Stands for an engine summary in the call's own script: no check reads its words.
    engine_local = "కాల్ బాగుంది"
    english, local, _source, _ = _settle_summaries(
        engine_summary=engine_local,
        model_summary="The caller booked a visit. The call ended on a positive note.",
        stored_local="",
        language="te-IN",
    )
    assert english == "The caller booked a visit."
    assert local == "", "left for the language pass to write from the cleaned English"
    english, local, _source, _ = _settle_summaries(
        engine_summary=engine_local,
        model_summary="The caller booked a visit.",
        stored_local="",
        language="te-IN",
    )
    assert local == engine_local, "nothing was cleaned, so the engine's own stands"


async def test_the_language_pass_cleans_its_english_and_restates_the_call_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id = await _vendor_call()
    engine_local = "కాల్"
    restated = "బుక్"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET summary = NULL, summary_local = :l, "
                "summary_language = 'te-IN', translation_state = 'pending' WHERE id = :c"
            ),
            {"l": engine_local, "c": call_id},
        )
        await session.execute(
            text(
                "UPDATE agents SET language_primary = 'te-IN' WHERE id = "
                "(SELECT agent_id FROM calls WHERE id = :c)"
            ),
            {"c": call_id},
        )
    asked: list[dict[str, Any]] = []

    async def fake_pass(**kwargs: Any) -> LanguagePass:
        asked.append(kwargs)
        if len(asked) == 1:
            return LanguagePass(summary_en="The caller booked a visit. The caller was satisfied.")
        return LanguagePass(summary_local=restated)

    monkeypatch.setattr(call_translation.call_language, "run_language_pass", fake_pass)
    monkeypatch.setattr(
        call_translation, "get_settings", lambda: type("S", (), {"sarvam_api_key": "k"})()
    )
    await call_translation.translate_call(tenant_id, call_id, feature="call_reading", turns=False)
    async with tenant_session(tenant_id) as session:
        summary, local = (
            await session.execute(
                text("SELECT summary, summary_local FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).one()
    assert summary == "The caller booked a visit."
    assert asked[1]["summary_en"] == "The caller booked a visit."
    assert local == restated


# --- 7/8. a list column fills a detail of any type, on both pages ------------------------


def _field(key: str, type_: str, choices: tuple[str, ...] = ()) -> CapturedFieldOut:
    field = CapturedFieldOut(key=key, label=key.title(), type=type_, core=False, current=True)  # type: ignore[arg-type]
    field._choices = choices
    return field


def test_a_list_cell_fills_a_detail_only_when_it_reads_cleanly_as_its_type() -> None:
    fields = [
        _field("plan", "enum", ("Gold", "Silver")),
        _field("visits", "number"),
        _field("insured", "bool"),
        _field("due", "date"),
        _field("renewal", "date"),
        _field("weight", "number"),
    ]
    filled = with_list_columns(
        fields,
        columns={
            "Plan": "gold",
            "Visits": "3",
            "Insured": "YES",
            "Due": "05/11/2026",
            "Renewal": "2026-12-01",
            "Weight": "72.5",
        },
    )
    assert [(f.value, f.source) for f in filled] == [
        ("Gold", "list"),
        (3, "list"),
        (True, "list"),
        ("2026-11-05", "list"),
        ("2026-12-01", "list"),
        (72.5, "list"),
    ]
    unclear = with_list_columns(
        fields,
        columns={
            "Plan": "Platinum",
            "Visits": "about ten",
            "Insured": "maybe",
            "Due": "next week",
            "Renewal": "31/02/2026",
            "Weight": "1,200",
        },
    )
    assert [f.value for f in unclear] == [None] * 6
    assert all(f.source == "call" for f in unclear)


PLAN = ExtractionField(key="plan", label="Plan", type="enum", enum_values=["Gold", "Silver"])
VISITS = ExtractionField(key="visits", label="Visits", type="number")
AREA = ExtractionField(key="area", label="Area", type="text")


async def test_the_lead_page_shows_the_list_columns_the_call_page_shows() -> None:
    tenant_id, agent_id, _token = await _tenant()
    campaign_id, call_id, lead_id = uuid7(), uuid7(), uuid7()
    phone = "+919800000777"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status) "
                "VALUES (:id, :t, :a, 'Renewals', 'service', 'draft')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await notes.save_notes(session, campaign_id, [PLAN, VISITS, AREA], expected_digest=None)
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, campaign_id, engine_call_id, "
                "direction, status, started_at, duration_s, to_e164, created_at, updated_at) "
                "VALUES (:id, :t, :a, :c, :e, 'outbound', 'completed', now(), 60, :p, "
                "now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "c": campaign_id,
                "e": f"r-{call_id}",
                "p": phone,
            },
        )
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, custom, "
                "status, attempts, created_at, updated_at) VALUES (:i, :t, :c, :p, "
                "CAST(:custom AS jsonb), 'completed', 1, now(), now())"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "c": campaign_id,
                "p": phone,
                "custom": json.dumps({"Plan": "silver", "Visits": "4", "Area": "Kondapur"}),
            },
        )
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, data, "
                "first_call_id, last_call_id, call_count, is_repeat_caller, created_at, "
                "updated_at) VALUES (:id, :t, :a, :p, 'campaign', 'new', '{}'::jsonb, :c, :c, "
                "1, false, now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id, "p": phone, "c": call_id},
        )
        await session.execute(
            text("UPDATE calls SET lead_id = :l WHERE id = :c"), {"l": lead_id, "c": call_id}
        )
        call_page = (await crm.get_call(session, call_id)).captured
        lead_page = (await get_lead_captured(lead_id, session)).fields

    def listed(fields: list[CapturedFieldOut]) -> dict[str, Any]:
        wanted = {"plan", "visits", "area"}
        return {f.key: f.value for f in fields if f.source == "list" and f.key in wanted}

    expected = {"plan": "Silver", "visits": 4, "area": "Kondapur"}
    assert listed(call_page) == listed(lead_page) == expected
    assert "_choices" not in lead_page[0].model_dump(), "the choices are never sent"
