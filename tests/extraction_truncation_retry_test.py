"""A Sarvam reading cut off at `EXTRACTION_MAX_TOKENS` is asked once more with reasoning off.

Sarvam counts its reasoning inside `max_tokens`, so the 23 Oct 2026 Telugu call truncated at
`low` on its first pass and on three identical re-reads. The retry gives the whole budget to
the JSON; a re-read of a truncated call starts with reasoning off and stops if it truncates.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import tenant_session
from apps.workers import chat, extraction_reread, pipeline
from apps.workers import extraction as extraction_module
from apps.workers.chat import ChatOutcome, TokenUsage
from apps.workers.extraction import (
    MODEL_FAILURE,
    ExtractionTruncatedError,
    SarvamExtractor,
    extract_call,
)
from calevate_shared.extraction import ExtractionField, ExtractionOutput, ExtractionSchemaSpec
from sqlalchemy import text
from tests.call_moments_ai_test import _brake_not_tripped as _brake_not_tripped
from tests.call_moments_ai_test import attested as attested
from tests.pipeline_audit_test import _completed_call, _run_pipeline
from tests.pipeline_audit_test import _stub_storage as _stub_storage
from tests.smoke_pipeline_test import _seed_tenant

SPEC = ExtractionSchemaSpec(
    fields=[ExtractionField(key="area", label="Area", type="text")],
)
TRANSCRIPT = "agent: Which area?\ncaller: Guntur."

FIRST = TokenUsage(prompt_tokens=1_000, output_tokens=4_096)
SECOND = TokenUsage(prompt_tokens=1_000, output_tokens=300)
TRUNCATED = ChatOutcome(content='{"area": "Gun', finish_reason="length", usage=FIRST)
ANSWER = ChatOutcome(
    content='{"area": "Guntur", "summary": "s"}', finish_reason="stop", usage=SECOND
)


class _Wire:
    """`chat.complete` replaced: records each request and answers from a script."""

    def __init__(self, *answers: ChatOutcome) -> None:
        self._answers = list(answers)
        self.requests: list[dict[str, Any]] = []

    async def complete(self, leg: chat.ChatLeg, messages: Any, **kwargs: Any) -> ChatOutcome:
        self.requests.append(kwargs)
        return self._answers.pop(0)

    @property
    def efforts(self) -> list[Any]:
        return [r["reasoning_effort"] for r in self.requests]


def _wire(monkeypatch: pytest.MonkeyPatch, *answers: ChatOutcome) -> _Wire:
    wire = _Wire(*answers)
    monkeypatch.setattr(extraction_module.chat, "complete", wire.complete)
    return wire


async def test_a_truncated_answer_is_asked_again_with_reasoning_off_and_that_answer_used(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    wire = _wire(monkeypatch, TRUNCATED, ANSWER)
    caplog.set_level(logging.WARNING)
    extractor = SarvamExtractor("key")

    out = await extract_call(SPEC, TRANSCRIPT, extractor=extractor)

    assert wire.efforts == ["low", "off"]
    assert out.valid and out.data["area"] == "Guntur"
    assert extractor.last_reasoning_effort == "off"
    # Both asks were paid for, so both are in what the pipeline meters.
    assert extractor.last_usage == TokenUsage(prompt_tokens=2_000, output_tokens=4_396)
    (record,) = [r for r in caplog.records if r.getMessage() == "extraction_truncated_retry"]
    assert (record.model, record.reasoning_effort, record.retry_reasoning_effort) == (
        "sarvam-105b",
        "low",
        "off",
    )
    assert "Guntur" not in json.dumps({k: str(v) for k, v in vars(record).items()})


async def test_a_retry_that_truncates_too_is_a_visible_model_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    wire = _wire(monkeypatch, TRUNCATED, TRUNCATED)
    extractor = SarvamExtractor("key")

    out = await extract_call(SPEC, TRANSCRIPT, extractor=extractor)

    assert wire.efforts == ["low", "off"]
    assert out.valid is False
    assert out.errors == {MODEL_FAILURE: ExtractionTruncatedError.__name__}
    assert out.data == {}
    assert extractor.last_usage == TokenUsage(prompt_tokens=2_000, output_tokens=8_192)


async def test_reasoning_already_off_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    wire = _wire(monkeypatch, TRUNCATED)

    out = await extract_call(SPEC, TRANSCRIPT, extractor=SarvamExtractor("key").without_reasoning())

    assert wire.efforts == ["off"]
    assert out.errors == {MODEL_FAILURE: ExtractionTruncatedError.__name__}


async def test_an_untruncated_answer_is_asked_once(monkeypatch: pytest.MonkeyPatch) -> None:
    wire = _wire(monkeypatch, ANSWER)
    extractor = SarvamExtractor("key")

    await extract_call(SPEC, TRANSCRIPT, extractor=extractor)

    assert wire.efforts == ["low"]
    assert extractor.last_reasoning_effort == "low"


async def test_both_asks_are_metered_as_the_one_pass(
    monkeypatch: pytest.MonkeyPatch, attested: None
) -> None:
    _wire(monkeypatch, TRUNCATED, ANSWER)
    tenant_id, _agent_id = await _seed_tenant(f"trunc_{uuid.uuid4().hex[:8]}")
    extractor = SarvamExtractor("key")
    await extract_call(SPEC, TRANSCRIPT, extractor=extractor)

    await pipeline._meter_extraction(tenant_id, uuid.uuid4(), extractor)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT meta FROM usage_events WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).all()
    metas = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]
    assert len(metas) == 2
    for meta in metas:
        assert (meta["prompt_tokens"], meta["output_tokens"]) == ("2000", "4396")
        assert meta["reasoning_effort"] == "off"


# --- the re-read ------------------------------------------------------------------------


async def _stored_failure(
    label: str, monkeypatch: pytest.MonkeyPatch, error: str
) -> tuple[UUID, UUID]:
    """A completed call whose reading failed with `error`, ended 20 min ago."""
    tenant_id, execution_id, call_id = await _completed_call(label)

    async def fails(*_args: Any, **_kw: Any) -> ExtractionOutput:
        return ExtractionOutput(valid=False, errors={MODEL_FAILURE: error})

    monkeypatch.setattr(pipeline, "extract_call", fails)
    await _run_pipeline(tenant_id, call_id, execution_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET ended_at = now() - interval '20 minutes' WHERE id = :c"),
            {"c": call_id},
        )
    return tenant_id, call_id


def _reread_with(monkeypatch: pytest.MonkeyPatch, result: ExtractionOutput) -> list[Any]:
    """The re-read's model pass replaced; returns the reasoning effort each pass was given."""
    efforts: list[Any] = []

    async def read(*_args: Any, extractor: Any, **_kw: Any) -> ExtractionOutput:
        efforts.append(extractor._reasoning_effort)
        return result

    monkeypatch.setattr(extraction_module, "get_extractor", lambda: SarvamExtractor("key"))
    monkeypatch.setattr(pipeline, "extract_call", read)
    return efforts


async def _attempts(tenant_id: UUID, call_id: UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT reread_attempts FROM call_extractions WHERE call_id = :c"),
                    {"c": call_id},
                )
            ).scalar_one()
        )


def _payload(tenant_id: UUID, call_id: UUID) -> dict[str, str]:
    return {"tenant_id": str(tenant_id), "call_id": str(call_id)}


async def test_a_truncated_call_is_reread_with_reasoning_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id = await _stored_failure(
        "trunc_ok", monkeypatch, ExtractionTruncatedError.__name__
    )
    efforts = _reread_with(monkeypatch, ExtractionOutput(data={"area": "Guntur"}, valid=True))

    outcome = await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id))

    assert (outcome, efforts) == ("reread", ["off"])


async def test_a_reread_that_still_truncates_stops_the_rereads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    truncated = ExtractionOutput(
        valid=False, errors={MODEL_FAILURE: ExtractionTruncatedError.__name__}
    )
    tenant_id, call_id = await _stored_failure(
        "trunc_stop", monkeypatch, ExtractionTruncatedError.__name__
    )
    efforts = _reread_with(monkeypatch, truncated)

    outcome = await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id))

    assert (outcome, efforts) == ("still_truncated", ["off"])
    assert await _attempts(tenant_id, call_id) == extraction_reread.REREAD_MAX_ATTEMPTS
    async with tenant_session(tenant_id) as session:
        exhausted = await extraction_reread.exhausted_rereads(session, now=datetime.now(UTC))
    assert call_id in exhausted, "the exhausted alarm names it for a person"


async def test_any_other_failure_is_reread_with_the_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, call_id = await _stored_failure("trunc_other", monkeypatch, "ReadTimeout")
    efforts = _reread_with(monkeypatch, ExtractionOutput(valid=False, errors={MODEL_FAILURE: "x"}))

    outcome = await extraction_reread.reread_call_extraction({}, _payload(tenant_id, call_id))

    assert (outcome, efforts) == ("still_failed", ["low"])
    assert await _attempts(tenant_id, call_id) == 1
