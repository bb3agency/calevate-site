"""Why the person said no, as one countable category (founder, 24 Nov 2026): the post-call
reading names one of `REFUSAL_REASONS` or nothing, never words, and the call keeps it for the
Improve tab to count.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest
from apps.api.db.session import tenant_session
from apps.workers.extraction import build_response_schema, extract_call
from apps.workers.pipeline import _persist_extraction
from calevate_shared.business_outcomes import BusinessOutcome
from calevate_shared.extraction import (
    REFUSAL_REASONS,
    ExtractionOutput,
    ExtractionSchemaSpec,
    build_extraction_prompt,
    refusal_reason_of,
)
from calevate_shared.lead_fields import OUTPUT_KEYS
from sqlalchemy import text
from tests.pipeline_audit_test import _completed_call

SPEC = ExtractionSchemaSpec(fields=[])
MIGRATION = (
    Path(__file__).resolve().parent.parent
    / "alembic"
    / "versions"
    / "b7e2c4a91d06_calls_refusal_reason.py"
)


def test_the_prompt_asks_for_one_listed_reason_or_null() -> None:
    prompt = build_extraction_prompt(SPEC, "caller: no thanks")
    assert '"refusal_reason"' in prompt
    for reason in REFUSAL_REASONS:
        assert f"    {reason} " in prompt
    assert 'a plain "no" is not_interested' in prompt


def test_the_schema_admits_only_the_categories_and_null() -> None:
    prop = build_response_schema(SPEC)["properties"]["refusal_reason"]
    assert prop == {"type": ["string", "null"], "enum": [*REFUSAL_REASONS, None]}
    assert "refusal_reason" in build_response_schema(SPEC)["required"]
    # No business detail may take the key the reading answers under.
    assert "refusal_reason" in OUTPUT_KEYS


def test_the_migration_check_names_exactly_the_categories() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    listed = source.split("refusal_reason IN (", 1)[1].split(")", 1)[0]
    assert [w.strip(" '\"\n") for w in listed.replace('"', "").split(",")] == list(REFUSAL_REASONS)


@pytest.mark.parametrize(
    ("raw", "kept"),
    [
        ("price", "price"),
        (" Busy_Now ", "busy_now"),
        ("too costly for me", None),
        ("", None),
        (None, None),
        (3, None),
    ],
)
def test_only_a_listed_category_is_kept(raw: object, kept: str | None) -> None:
    assert refusal_reason_of(raw) == kept


class _Runner:
    model_name = "fake-model"
    reads_goal = True
    reads_outcomes = True
    reads_setting = True

    def __init__(self, answer: dict[str, Any]) -> None:
        self.answer = answer

    async def run(
        self,
        spec: ExtractionSchemaSpec,
        transcript: str,
        *,
        outcomes: Sequence[BusinessOutcome] = (),
        goal: str | None = None,
        setting: Any = None,
    ) -> dict[str, Any]:
        return dict(self.answer)


@pytest.mark.anyio
async def test_the_reading_keeps_the_category_and_drops_words() -> None:
    answer = {"summary": "s", "outcome_tag": "answered", "refusal_reason": "already_has"}
    out = await extract_call(SPEC, "caller: we have one", extractor=_Runner(answer))
    assert out.refusal_reason == "already_has"
    answer["refusal_reason"] = "They said their son already installed it"
    worded = await extract_call(SPEC, "caller: we have one", extractor=_Runner(answer))
    assert worded.refusal_reason is None


@pytest.mark.anyio
async def test_the_call_keeps_the_reason_and_a_failed_reading_none() -> None:
    tenant_id, _execution_id, call_id = await _completed_call("refusal")
    await _persist_extraction(
        tenant_id,
        call_id,
        ExtractionOutput(outcome_tag="answered", refusal_reason="price"),
        schema_version=1,
    )
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT refusal_reason FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar_one()
    assert stored == "price"

    await _persist_extraction(
        tenant_id,
        call_id,
        ExtractionOutput(refusal_reason="price", valid=False, errors={"_model": "TimeoutError"}),
        schema_version=1,
    )
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT refusal_reason FROM calls WHERE id = :c"), {"c": call_id}
            )
        ).scalar_one()
    assert stored is None
