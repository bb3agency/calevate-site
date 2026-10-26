"""A site-visit call read after 26 Oct 2026 lost its whole reading to the D-889 ask.

From the founder's report of 27 Oct 2026: every Telugu real-estate test call from 26 Oct
12:05 pm that booked a site visit showed "Answered" with no "Needs you", "We could not tell
how this call ended." and "The caller did not give any details on this call.", while the
engine's summary named the area, the bedrooms, the budget and the visit. The release before
those calls changed one thing in what the post-call reading sends the model: D-889's
`unlisted` object in the prompt and the strict schema, whose prompt asked for `{}` "when
there is none" while the schema requires every choice key. A reading that fails on that ask,
or comes back as an object that is not an answer, used to be filed as a call where the
caller said nothing.

The transcript here is synthetic, in the calls' shape: Telugu in Latin letters with English
and spoken numbers mixed in.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.engine import fake as fake_engine
from apps.workers import chat, pipeline
from apps.workers import extraction as extraction_module
from apps.workers.chat import ChatOutcome, TokenUsage
from apps.workers.extraction import (
    MODEL_FAILURE,
    ExtractionUnusableError,
    SarvamExtractor,
    _first_json_object,
    build_response_schema,
    extract_call,
)
from calevate_shared.extraction import (
    ExtractionField,
    ExtractionOutput,
    ExtractionSchemaSpec,
    build_extraction_prompt,
)
from scripts.seed import VERTICAL_TEMPLATES
from tests.call_moments_ai_test import attested as attested
from tests.pipeline_audit_test import _completed_call, _run_pipeline, _scalar
from tests.pipeline_audit_test import _stub_storage as _stub_storage

SPEC = ExtractionSchemaSpec(
    fields=[ExtractionField.model_validate(f) for f in VERTICAL_TEMPLATES["real_estate"]]
)

TURNS: tuple[tuple[str, str], ...] = (
    ("agent", "Namaskaram andi, Sri Estates nunchi matladutunnanu. Mee peru cheppandi?"),
    ("caller", "Naa peru Ravi andi. Guntur lo oka flat kosam chustunnanu."),
    ("agent", "Entha bedrooms kavali andi?"),
    ("caller", "4 bedrooms kavali, four BHK."),
    ("agent", "Budget entha anukuntunnaru?"),
    ("caller", "Rendu crores varaku, two crore budget."),
    ("agent", "Eppudu konalanukuntunnaru?"),
    ("caller", "Next month lo konali andi."),
    ("agent", "Site visit ki Saturday saayantram 6 ki ravacha?"),
    ("caller", "Saturday 6 pm ok andi, vastanu."),
)
TRANSCRIPT = "\n".join(f"{speaker}: {text}" for speaker, text in TURNS)

#: What the model answers when it can answer: the visit is agreed and someone must confirm it.
ANSWER: dict[str, Any] = {
    "budget_lakhs": 200,
    "preferred_location": "Guntur",
    "bhk_size": "4BHK",
    "timeline": "Next month",
    "site_visit_interest": True,
    "summary": (
        "Ravi wants a 4 bedroom flat in Guntur for up to 2 crore and agreed a Saturday 6 pm "
        "site visit."
    ),
    "headline": "4BHK in Guntur, 2 crore; site visit Saturday 6 pm",
    "next_step": "Confirm the Saturday 6 pm site visit with Ravi.",
    "sentiment": "positive",
    "outcome_tag": "answered",
    "out_of_scope": False,
    "callback_requested": False,
    "moments": [],
}

USAGE = TokenUsage(prompt_tokens=1_000, output_tokens=4_096)
SMALL = TokenUsage(prompt_tokens=900, output_tokens=300)


class _Model:
    """`chat.complete` replaced: a model that cannot finish an answer carrying `unlisted`
    (it runs to the token cap, with reasoning on and off) and answers the request without it."""

    def __init__(self) -> None:
        self.asked_unlisted: list[bool] = []

    async def complete(self, leg: chat.ChatLeg, messages: Any, **kw: Any) -> ChatOutcome:
        schema = (kw.get("response_format") or {}).get("json_schema", {}).get("schema", {})
        with_unlisted = "unlisted" in schema.get("properties", {})
        self.asked_unlisted.append(with_unlisted)
        if with_unlisted:
            return ChatOutcome(
                content='{"budget_lakhs": 200, "unlisted": {', finish_reason="length", usage=USAGE
            )
        return ChatOutcome(content=json.dumps(ANSWER), finish_reason="stop", usage=SMALL)


def _wire(monkeypatch: pytest.MonkeyPatch, complete: Any) -> None:
    monkeypatch.setattr(chat, "complete", complete)


# --- the prompt and the schema agree --------------------------------------------------


def test_the_prompt_asks_for_the_unlisted_answer_the_strict_schema_accepts() -> None:
    unlisted = build_response_schema(SPEC)["properties"]["unlisted"]
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT)
    section = prompt[prompt.index('- "unlisted"') : prompt.index("WHO SPOKE")]

    assert unlisted["required"] == ["bhk_size"]
    assert "{}" not in section, "an empty object is an answer the strict schema refuses"
    assert "every choice field above as a key (bhk_size)" in section
    assert "null" in section


def test_without_the_ask_the_request_is_the_one_before_d889() -> None:
    prompt = build_extraction_prompt(SPEC, TRANSCRIPT, unlisted=False)
    assert '"unlisted"' not in prompt
    assert '"baad mein call").\n\nWHO SPOKE' in prompt
    assert "unlisted" not in build_response_schema(SPEC, unlisted=False)["properties"]


# --- one call -------------------------------------------------------------------------


async def test_a_reading_that_fails_on_the_unlisted_ask_is_asked_without_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = _Model()
    _wire(monkeypatch, model.complete)
    extractor = SarvamExtractor("key")

    out = await extract_call(SPEC, TRANSCRIPT, extractor=extractor, retry_without_unlisted=True)

    # Reasoning low, then off (the truncation retry), then the request without the ask.
    assert model.asked_unlisted == [True, True, False]
    assert out.valid and MODEL_FAILURE not in out.errors
    assert out.data == {
        "budget_lakhs": 200,
        "preferred_location": "Guntur",
        "bhk_size": "4BHK",
        "timeline": "Next month",
        "site_visit_interest": True,
    }
    assert (out.outcome_tag, out.next_step) == ("answered", ANSWER["next_step"])
    assert out.unlisted == {}
    # Every ask was paid for, so every ask is in what the pipeline meters.
    assert extractor.last_usage == TokenUsage(prompt_tokens=2_900, output_tokens=8_492)


async def test_an_answer_that_is_not_an_extraction_is_a_model_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty(leg: chat.ChatLeg, messages: Any, **kw: Any) -> ChatOutcome:
        return ChatOutcome(content="{}", finish_reason="stop", usage=SMALL)

    _wire(monkeypatch, empty)

    out = await extract_call(SPEC, TRANSCRIPT, extractor=SarvamExtractor("key"))

    # A `_model` failure is what the re-read sweep reads again; `{}` read as an answer was
    # a call filed as "the caller gave nothing", for good.
    assert out.errors == {MODEL_FAILURE: ExtractionUnusableError.__name__}
    assert out.outcome_tag is None and out.data == {}


async def test_the_answer_object_is_found_past_an_empty_one_in_prose(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def chatty(leg: chat.ChatLeg, messages: Any, **kw: Any) -> ChatOutcome:
        return ChatOutcome(
            content="unlisted is {} here.\n```json\n" + json.dumps(ANSWER) + "\n```",
            finish_reason="stop",
            usage=SMALL,
        )

    _wire(monkeypatch, chatty)

    out = await extract_call(SPEC, TRANSCRIPT, extractor=SarvamExtractor("key"))

    assert out.valid and out.data["preferred_location"] == "Guntur"


def test_a_brace_inside_a_string_does_not_cut_the_answer() -> None:
    answer = {**ANSWER, "summary": "Caller said {Saturday} works."}
    assert _first_json_object(json.dumps(answer)) == answer
    assert _first_json_object("noise " + json.dumps(answer)) != {}


def test_a_truncated_object_is_never_read_from_its_inner_object() -> None:
    assert _first_json_object('{"budget_lakhs": 200, "unlisted": {"bhk_size": null}') == {}


# --- the call, end to end -------------------------------------------------------------


async def test_the_site_visit_call_reads_needs_you_with_its_details(
    monkeypatch: pytest.MonkeyPatch, attested: None, _stub_storage: None
) -> None:
    monkeypatch.setattr(fake_engine, "SAMPLE_TURNS", TURNS)
    model = _Model()
    _wire(monkeypatch, model.complete)
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: SarvamExtractor("key"))
    tenant_id, execution_id, call_id = await _completed_call("site_visit")
    await _scalar(
        tenant_id,
        "UPDATE extraction_schemas SET fields = CAST(:f AS jsonb) WHERE tenant_id = :t "
        "RETURNING id",
        f=json.dumps(VERTICAL_TEMPLATES["real_estate"]),
        t=tenant_id,
    )

    await _run_pipeline(tenant_id, call_id, execution_id)

    row = await _scalar(
        tenant_id,
        "SELECT json_build_object('outcome', c.outcome_tag, 'valid', ce.valid, "
        "'errors', ce.errors, 'data', ce.data) FROM calls c "
        "JOIN call_extractions ce ON ce.call_id = c.id WHERE c.id = :c",
        c=call_id,
    )
    # D-887: answered with a next step is a call that needs a person.
    assert row["outcome"] == "needs_you"
    assert row["valid"] is True and not row["errors"]
    assert row["data"]["preferred_location"] == "Guntur"
    assert row["data"]["budget_lakhs"] == 200
    assert row["data"]["bhk_size"] == "4BHK"


# --- repairing the calls already filed as empty ---------------------------------------


async def _filed_empty(
    monkeypatch: pytest.MonkeyPatch, label: str, stored: ExtractionOutput
) -> tuple[UUID, UUID]:
    """A site-visit call whose reading was stored as `stored`, ended 30 minutes ago."""
    monkeypatch.setattr(fake_engine, "SAMPLE_TURNS", TURNS)
    tenant_id, execution_id, call_id = await _completed_call(label)
    await _scalar(
        tenant_id,
        "UPDATE extraction_schemas SET fields = CAST(:f AS jsonb) WHERE tenant_id = :t "
        "RETURNING id",
        f=json.dumps(VERTICAL_TEMPLATES["real_estate"]),
        t=tenant_id,
    )

    async def stored_reading(*_args: Any, **_kw: Any) -> ExtractionOutput:
        return stored

    monkeypatch.setattr(pipeline, "extract_call", stored_reading)
    await _run_pipeline(tenant_id, call_id, execution_id)
    monkeypatch.setattr(pipeline, "extract_call", extract_call)
    await _scalar(
        tenant_id,
        "UPDATE calls SET ended_at = now() - interval '30 minutes' WHERE id = :c RETURNING id",
        c=call_id,
    )
    return tenant_id, call_id


async def test_the_reread_script_repairs_calls_filed_as_empty_and_only_once(
    monkeypatch: pytest.MonkeyPatch, attested: None, _stub_storage: None
) -> None:
    from scripts import reread_extractions

    # How the 26 Oct calls were stored: no outcome, nothing captured, required fields missing.
    legacy = ExtractionOutput(
        valid=False,
        errors={
            "budget_lakhs": "Budget (lakhs) is required but was not captured",
            "preferred_location": "Location is required but was not captured",
        },
    )
    tenant_id, call_id = await _filed_empty(monkeypatch, "filed_empty", legacy)
    assert (
        await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id) is None
    )
    window = timedelta(hours=2)

    found = await reread_extractions.candidates(window=window, cap=10, only_tenant=tenant_id)
    assert [c.call_id for c in found] == [call_id]
    dry = await reread_extractions.run(window=window, cap=10, apply=False, only_tenant=tenant_id)
    assert dry == {"candidate": 1}
    assert (
        await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id) is None
    )

    model = _Model()
    _wire(monkeypatch, model.complete)
    monkeypatch.setattr(extraction_module, "get_extractor", lambda: SarvamExtractor("key"))
    applied = await reread_extractions.run(window=window, cap=10, apply=True, only_tenant=tenant_id)

    assert applied == {"reread": 1}
    assert (
        await _scalar(tenant_id, "SELECT outcome_tag FROM calls WHERE id = :c", c=call_id)
        == "needs_you"
    )
    assert (
        await _scalar(
            tenant_id,
            "SELECT data ->> 'preferred_location' FROM call_extractions WHERE call_id = :c",
            c=call_id,
        )
        == "Guntur"
    )
    # Repaired calls are not candidates, so a second run reads (and pays for) nothing.
    asks = len(model.asked_unlisted)
    assert (
        await reread_extractions.run(window=window, cap=10, apply=True, only_tenant=tenant_id) == {}
    )
    assert len(model.asked_unlisted) == asks


async def test_the_reread_script_also_takes_a_provider_failure_and_skips_a_claimed_call(
    monkeypatch: pytest.MonkeyPatch, attested: None, _stub_storage: None
) -> None:
    from scripts import reread_extractions

    failed = ExtractionOutput(valid=False, errors={MODEL_FAILURE: "ExtractionTruncatedError"})
    tenant_id, call_id = await _filed_empty(monkeypatch, "filed_failed", failed)
    window = timedelta(hours=2)
    await _scalar(
        tenant_id,
        "UPDATE call_extractions SET reread_at = now() WHERE call_id = :c RETURNING call_id",
        c=call_id,
    )

    claimed = await reread_extractions.run(window=window, cap=10, apply=True, only_tenant=tenant_id)

    assert claimed == {"claimed_elsewhere": 1}, "a call another run is reading is not paid twice"
