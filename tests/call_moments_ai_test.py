"""Key moments from the extraction model, on approximate turn times (founder, 11 Oct 2026).

What is pinned here, cheapest first:

1. ThinnestAI turns get a time at all, and it is marked approximate (the vendor says its
   turn time is "when it was written down, not where it falls in the audio").
2. The moments ride in the SAME extraction request: the prompt asks for them only when
   given a brief, numbers the lines it asks about, and never assumes a business type.
3. A suggested moment lands on the turn its line names, with OUR label for a captured
   field and a redacted label for the model's own words (hard rule 5).
4. The pass is metered at our cost with its measured tokens (hard rule 7), the brief comes
   from the account and the running script, a re-run keeps the model's moments, and the
   lead page's read is redacted and tenant-scoped (hard rule 1).

Run: uv run pytest -q tests/call_moments_ai_test.py
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import ai_quota, rates
from apps.api.billing.models import ASSIST_FEATURE_CALL_EXTRACTION
from apps.api.crm.service import _call_moments, get_call
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import parse_transcript
from apps.workers import pipeline
from apps.workers.chat import TokenUsage
from apps.workers.extraction import SarvamExtractor, extract_call
from apps.workers.moments import (
    derive_moments,
    merge_moments,
    model_moments,
    prompt_line_turns,
)
from apps.workers.redaction import redact
from calevate_shared.engine import SARVAM_DEFAULT_LLM
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionOutput,
    ExtractionSchemaSpec,
    MomentCandidate,
    MomentsBrief,
    build_extraction_prompt,
    clean_moment_candidates,
)
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call, _run_pipeline
from tests.pipeline_audit_test import _stub_storage as _stub_storage  # autouse: no bucket
from tests.smoke_pipeline_test import _seed_tenant

SPEC = ExtractionSchemaSpec(
    fields=[
        ExtractionField(key="product", label="Product wanted", type="text"),
        ExtractionField(key="quantity", label="Quantity", type="text"),
    ]
)
BRIEF = MomentsBrief(
    business_type="Shop, food or produce",
    business_line="Chilli and chilli powder, wholesale and retail",
    agent_goal="Take orders and answer stock questions",
    script_steps=["Greet", "Find what they want", "Confirm the order"],
)
TRANSCRIPT = (
    "agent: Namaskaram, Raghava Organics.\n"
    "caller: I want 5 kg Guntur chilli powder.\n"
    "agent: That is 450 rupees a kg.\n"
    "caller: Do you deliver to Vijayawada? My number is 9876543210."
)


@dataclass
class _Turn:
    idx: int
    speaker: str
    text: str
    start_ms: int | None
    start_approximate: bool = True


TURNS = [
    _Turn(0, "agent", "Namaskaram, Raghava Organics.", 1_000),
    _Turn(1, "caller", "", 4_000),  # wordless: not a prompt line
    _Turn(2, "caller", "I want 5 kg Guntur chilli powder.", 6_000),
    _Turn(3, "agent", "That is 450 rupees a kg.\nShall I book it?", 11_000),
    _Turn(4, "caller", "Do you deliver to Vijayawada? My number is 9876543210.", None),
]


# --- 1. the engine's turn times ---------------------------------------------------------


def test_a_thinnest_turn_is_timed_from_the_answer_and_marked_approximate() -> None:
    started = datetime(2026, 10, 6, 4, 30, 2, 118_000, tzinfo=UTC)
    answered = datetime(2026, 10, 6, 4, 30, 9, 540_000, tzinfo=UTC)
    turns, lost = parse_transcript(
        [
            {"speaker": "agent", "text": "Hello", "at": "2026-10-06T04:30:10.204Z"},
            {"speaker": "customer", "text": "Haan", "offset": 15},
            {"speaker": "customer", "text": "No time at all"},
        ],
        "out_x",
        started=started,
        answered=answered,
    )
    assert lost == 0
    assert [t.start_ms for t in turns] == [664, 15_000 - 7_422, None]
    assert [t.start_approximate for t in turns] == [True, True, False]


def test_a_turn_time_never_goes_before_the_start_of_the_recording() -> None:
    answered = datetime(2026, 10, 6, 4, 30, 9, tzinfo=UTC)
    turns, _ = parse_transcript(
        [{"speaker": "agent", "text": "ring", "at": "2026-10-06T04:30:05Z"}],
        "out_y",
        answered=answered,
    )
    assert turns[0].start_ms == 0


def test_a_derived_marker_on_an_approximate_turn_is_kept_and_says_so() -> None:
    """Exact proof of the second is impossible on this engine; the marker is not dropped
    for it, it is anchored to the turn and labelled approximate."""
    moments = derive_moments(
        turns=TURNS, extraction={"product": "Guntur chilli powder"}, field_labels={}
    )
    assert [(m["at_ms"], m["turn_idx"], m["precision"]) for m in moments] == [
        (6_000, 2, "approximate")
    ]


# --- 2. the one request -----------------------------------------------------------------


def test_without_a_brief_the_prompt_is_the_extraction_prompt_alone() -> None:
    """The assist leg and the golden-transcript harness send this; it must not grow."""
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT)
    assert "KEY MOMENTS" not in prompt
    assert '"moments"' not in prompt
    assert TRANSCRIPT in prompt


def test_with_a_brief_the_same_prompt_asks_for_moments_on_numbered_lines() -> None:
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT, moments=BRIEF)
    assert "KEY MOMENTS" in prompt
    assert "[1] agent: Namaskaram, Raghava Organics." in prompt
    assert "[4] caller: Do you deliver to Vijayawada?" in prompt
    assert "product, quantity" in prompt, "a captured-field moment must name a real key"
    assert "Chilli and chilli powder" in prompt
    assert "Confirm the order" in prompt
    for kind in ("booking_agreed", "asked_for_person", "asked_delivery_or_payment"):
        assert kind in prompt
    assert "opt_out" not in prompt, "the opt-out moment is the detector's, not the model's"


def test_a_brief_with_no_business_type_assumes_none() -> None:
    """D-722: no account is a clinic, or anything else, unless somebody chose it."""
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT, moments=MomentsBrief()).lower()
    assert "clinic" not in prompt
    assert "type of business" not in prompt
    assert "not given" in prompt


def test_the_models_moments_are_cleaned_not_trusted() -> None:
    raw = [
        {"line": 2, "kind": "field_captured", "field": "product", "label": "x", "importance": 3},
        {"line": 2, "kind": "field_captured", "field": "symptom"},  # not this business's field
        {"line": 3, "kind": "opt_out"},  # the detector's, never the model's
        {"line": 3, "kind": "ai_disclosure"},  # not a kind at all
        {"line": "4", "kind": "complaint"},  # not a line number
        {"line": True, "kind": "complaint"},
        {"line": 4, "kind": "asked_delivery_or_payment", "label": "a" * 200, "importance": 9},
        "rubbish",
    ]
    cleaned = clean_moment_candidates(raw, SPEC)
    assert [(c.line, c.kind, c.field) for c in cleaned] == [
        (2, "field_captured", "product"),
        (4, "asked_delivery_or_payment", None),
    ]
    assert cleaned[1].importance == 3
    assert len(cleaned[1].label) <= 60
    assert clean_moment_candidates("not a list", SPEC) == []


class _ReadingExtractor:
    """A fake model that reads moments, standing in for Sarvam."""

    model_name = "fake-moments"
    reads_moments = True

    def __init__(self) -> None:
        self.briefs: list[MomentsBrief | None] = []

    async def run(
        self, spec: ExtractionSchemaSpec, transcript: str, *, moments: MomentsBrief | None = None
    ) -> dict[str, Any]:
        self.briefs.append(moments)
        return {
            "product": "Guntur chilli powder",
            "summary": "Asked for chilli powder.",
            "moments": [
                {"line": 4, "kind": "asked_delivery_or_payment", "label": "Asked about delivery"}
            ],
        }


class _PlainExtractor:
    """A runner with no model behind it (the offline baseline's shape)."""

    model_name = "plain"

    async def run(self, spec: ExtractionSchemaSpec, transcript: str) -> dict[str, Any]:
        return {"product": "Guntur chilli powder"}


async def test_the_moments_come_back_from_the_same_extraction_call() -> None:
    runner = _ReadingExtractor()
    out = await extract_call(SPEC, TRANSCRIPT, extractor=runner, moments=BRIEF)
    assert runner.briefs == [BRIEF], "one request, carrying the brief"
    assert out.data == {"product": "Guntur chilli powder"}
    assert [(m.line, m.kind) for m in out.moments] == [(4, "asked_delivery_or_payment")]


async def test_a_runner_that_cannot_read_moments_is_never_handed_the_brief() -> None:
    out = await extract_call(SPEC, TRANSCRIPT, extractor=_PlainExtractor(), moments=BRIEF)
    assert out.moments == []
    assert (await extract_call(SPEC, TRANSCRIPT, extractor=_ReadingExtractor())).moments == []


def test_sarvam_sends_the_brief_inside_the_shared_prompt() -> None:
    import inspect

    source = " ".join(inspect.getsource(SarvamExtractor).split())
    assert (
        "build_extraction_prompt( spec, transcript, moments=moments, languages=languages, "
        "outcomes=outcomes )" in source
    )
    assert SarvamExtractor.reads_moments is True


# --- 3. placing a suggestion ------------------------------------------------------------


def test_prompt_lines_map_back_to_the_turn_that_owns_them() -> None:
    lines = prompt_line_turns(TURNS)
    assert [t.idx for t in lines] == [0, 2, 3, 3, 4], (
        "a wordless turn is not a line, and a two-line turn owns both of its lines"
    )


def _place(candidates: list[MomentCandidate]) -> list[dict[str, Any]]:
    return model_moments(
        candidates,
        line_turns=prompt_line_turns(TURNS),
        field_labels={"product": "Product wanted"},
        redact=lambda label: redact(label).text,
    )


def test_a_suggestion_lands_on_its_turn_with_our_label_for_a_captured_field() -> None:
    placed = _place(
        [
            MomentCandidate(line=2, kind="field_captured", field="product", label="Guntur 5kg"),
            MomentCandidate(line=4, kind="price_quoted", label="Quoted the price per kg"),
        ]
    )
    assert [(m["turn_idx"], m["at_ms"], m["source"], m["precision"]) for m in placed] == [
        (2, 6_000, "model", "approximate"),
        (3, 11_000, "model", "approximate"),
    ]
    assert placed[0]["label"] == placed[0]["label_redacted"] == "Product wanted captured", (
        "a captured-field label is ours, so no value the model wrote can reach it"
    )
    assert placed[1]["category"] == "details"


def test_a_model_label_is_stored_redacted_as_well_as_raw() -> None:
    placed = _place([MomentCandidate(line=3, kind="complaint", label="Gave 9876543210 angrily")])
    assert placed[0]["label"] == "Gave 9876543210 angrily"
    assert "9876543210" not in placed[0]["label_redacted"]


def test_a_suggestion_with_no_line_or_no_time_is_dropped() -> None:
    assert _place([MomentCandidate(line=99, kind="complaint")]) == []
    assert _place([MomentCandidate(line=5, kind="complaint")]) == [], "turn 4 has no time"


def test_an_empty_model_label_falls_back_to_the_plain_one() -> None:
    placed = _place([MomentCandidate(line=1, kind="strong_interest")])
    assert placed[0]["label"] == "Strong interest"


def test_merged_moments_are_capped_at_eight() -> None:
    placed = _place([MomentCandidate(line=1, kind="strong_interest") for _ in range(12)])
    distinct = [{**m, "turn_idx": i, "at_ms": i * 1_000} for i, m in enumerate(placed)]
    assert len(merge_moments([], distinct)) == 8


# --- 4. metering, the brief, re-runs, the lead page -------------------------------------


@pytest.fixture
def attested() -> Iterator[None]:
    rates.install_inr_llm_price_attestations(
        lambda: {
            SARVAM_DEFAULT_LLM: rates.InrLlmPriceAttestation(
                model=SARVAM_DEFAULT_LLM,
                in_inr_per_mtok=Decimal("29.28"),
                cached_in_inr_per_mtok=Decimal("10.98"),
                out_inr_per_mtok=Decimal("73.20"),
                attested_by="founder",
                source="sarvam.ai/api-pricing, read 10 Oct 2026",
            )
        }
    )
    yield
    rates.install_inr_llm_price_attestations(None)


@pytest.fixture(autouse=True)
def _brake_not_tripped(monkeypatch: pytest.MonkeyPatch) -> None:
    async def not_tripped(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


async def test_the_pass_is_metered_at_our_cost_with_its_measured_tokens(attested: None) -> None:
    tenant_id, _agent_id = await _seed_tenant(f"mom_{uuid.uuid4().hex[:8]}")
    extractor = SarvamExtractor("key")
    extractor.last_usage = TokenUsage(prompt_tokens=2_400, output_tokens=620)
    call_id = uuid.uuid4()

    await pipeline._meter_extraction(tenant_id, call_id, extractor, moments_returned=3)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, unit_cost_paid, meta FROM usage_events "
                    "WHERE tenant_id = :t ORDER BY unit_type"
                ),
                {"t": tenant_id},
            )
        ).all()
    assert [r[0] for r in rows] == ["ai_assist_ktok_in", "ai_assist_ktok_out"]
    meta = [r[2] if isinstance(r[2], dict) else json.loads(r[2]) for r in rows]
    for m in meta:
        assert m["feature"] == ASSIST_FEATURE_CALL_EXTRACTION, "our cost, not the allowance"
        assert (m["prompt_tokens"], m["output_tokens"]) == ("2400", "620")
        assert m["moments_returned"] == "3"
    assert all(Decimal(str(r[1])) > 0 for r in rows)


async def _live_script(tenant_id: UUID, agent_id: UUID, script: dict[str, Any]) -> None:
    prompt_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO prompt_versions (id, tenant_id, agent_id, version, body, "
                "structured_script, created_at, updated_at) VALUES (:id, :t, :a, 1, 'x', "
                "CAST(:s AS jsonb), now(), now())"
            ),
            {"id": prompt_id, "t": tenant_id, "a": agent_id, "s": json.dumps(script)},
        )
        await session.execute(
            text("UPDATE agents SET live_prompt_id = :p WHERE id = :a"),
            {"p": prompt_id, "a": agent_id},
        )


async def test_the_brief_comes_from_the_confirmed_type_and_the_running_script() -> None:
    tenant_id, agent_id = await _seed_tenant(f"mom_{uuid.uuid4().hex[:8]}")
    assert await pipeline.load_moments_brief(tenant_id, agent_id) == MomentsBrief(), (
        "an account with no confirmed type and no script gets an empty brief"
    )

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET vertical_template = 'retail' WHERE id = :t"),
            {"t": tenant_id},
        )
    await _live_script(
        tenant_id,
        agent_id,
        {
            "schema_version": 2,
            "business_line": "Chilli powder shop",
            "goal": "Take orders",
            "stages": [{"name": "Greet"}, {"name": "Take the order"}, {"bad": 1}],
        },
    )
    brief = await pipeline.load_moments_brief(tenant_id, agent_id)
    assert brief.business_type == "Shop, food or produce"
    assert (brief.business_line, brief.agent_goal) == ("Chilli powder shop", "Take orders")
    assert brief.script_steps == ["Greet", "Take the order"]


async def test_the_pipeline_hands_the_brief_to_the_one_extraction_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, execution_id, call_id = await _completed_call("mombrief")
    seen: list[Any] = []

    async def _capture(*args: Any, **kwargs: Any) -> ExtractionOutput:
        seen.append(kwargs.get("moments"))
        return ExtractionOutput(data={})

    monkeypatch.setattr(pipeline, "extract_call", _capture)
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert len(seen) == 1, "one model request per call, moments included"
    assert isinstance(seen[0], MomentsBrief)


async def test_the_pipeline_tells_the_extraction_the_agents_languages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, execution_id, call_id = await _completed_call("momlang")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET language_primary = 'hi-IN', languages_extra = :x"),
            {"x": ["en-IN"]},
        )
    seen: list[Any] = []

    async def _capture(*args: Any, **kwargs: Any) -> ExtractionOutput:
        seen.append(kwargs.get("languages"))
        return ExtractionOutput(data={})

    monkeypatch.setattr(pipeline, "extract_call", _capture)
    await _run_pipeline(tenant_id, call_id, execution_id)
    assert seen == [("hi-IN", "en-IN")]


def _stored_model_moment(label: str, label_redacted: str) -> dict[str, Any]:
    return {
        "at_ms": 12_000,
        "turn_idx": 3,
        "kind": "complaint",
        "category": "attention",
        "label": label,
        "label_redacted": label_redacted,
        "source": "model",
        "precision": "approximate",
        "importance": 3,
        "field": None,
    }


async def _with_moments(label: str) -> tuple[UUID, UUID]:
    tenant_id, _execution_id, call_id = await _completed_call(f"mom{uuid.uuid4().hex[:6]}")
    derived = {
        "at_ms": 1_000,
        "turn_idx": 0,
        "kind": "opt_out",
        "category": "attention",
        "label": "Asked not to be called again",
        "label_redacted": "Asked not to be called again",
        "source": "derived",
        "precision": "approximate",
        "importance": 3,
        "field": None,
    }
    await pipeline._persist_extraction(
        tenant_id,
        call_id,
        ExtractionOutput(data={}, valid=True, errors={}),
        schema_version=1,
        moments=[derived, _stored_model_moment(label, redact(label).text)],
    )
    return tenant_id, call_id


async def test_a_rerun_that_reuses_the_extraction_keeps_the_models_moments() -> None:
    tenant_id, call_id = await _with_moments("Complained about the wait")
    kept = await pipeline._stored_model_moments(tenant_id, call_id)
    assert [m["label"] for m in kept] == ["Complained about the wait"], (
        "only the model's half is carried; the derived half is recomputed"
    )


async def test_the_call_page_reads_category_precision_and_turn() -> None:
    tenant_id, call_id = await _with_moments("Complained about the wait")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, start_ms, start_approximate, created_at, updated_at) VALUES "
                "(:i, :t, :c, 0, 'caller', 'hello', 'hello', 1000, true, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id},
        )
        detail = await get_call(session, call_id, raw=False)
    assert detail.transcript[0].start_approximate is True
    assert [
        (m.kind, m.category, m.precision, m.turn_idx, m.importance) for m in detail.moments
    ] == [
        ("opt_out", "attention", "approximate", 0, 3),
        ("complaint", "attention", "approximate", 3, 3),
    ]


async def test_the_lead_page_reads_redacted_moments_for_its_own_tenant_only() -> None:
    tenant_id, call_id = await _with_moments("Gave 9876543210 to call back")
    async with tenant_session(tenant_id) as session:
        moments = await _call_moments(session, {call_id})
    labels = [m.label for m in moments[call_id]]
    assert len(labels) == 2
    assert not any("9876543210" in label for label in labels), "the lead page is redacted"

    other_tenant, _ = await _seed_tenant(f"mom_{uuid.uuid4().hex[:8]}")
    async with tenant_session(other_tenant) as session:
        assert await _call_moments(session, {call_id}) == {}, "RLS: zero rows across tenants"
