"""Founder decisions of 18 Oct 2026 on the D-818 audit (D-819).

1. A paid turn that answered but whose answer the client did not get is OUR cost: on the
   ledger at its own model, never in the client's monthly AI allowance or the assistant's
   fair-use cap.
2. A multi-piece job (call-language chunks, OCR images, assistant turns, a repaired answer)
   some piece of which answered without a usage block records the reported part and raises
   `ai_usage_incomplete`; it is never left looking like the whole cost and never dropped.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.billing import ai_quota
from apps.api.billing import models as billing_models
from apps.api.billing.ai_quota import new_assist_ref, read_ai_usage
from apps.api.billing.service import current_billing_month
from apps.api.core import provider_health
from apps.api.core.settings import get_settings
from apps.api.crm import assist
from apps.api.db.session import tenant_session
from apps.workers import call_language, chat, document_ocr, script_assist
from apps.workers.extraction import AssistCapability, PaidTurn, TenantModelLeg
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

GEMINI = "gemini-3.1-flash-lite"
GOOGLE_LEG = TenantModelLeg(model=GEMINI, provider="google", serves_dashboard=True)
AZURE = AssistCapability(available=True, provider="azure")


def _usage(tokens: int) -> chat.TokenUsage:
    return chat.TokenUsage(prompt_tokens=tokens, output_tokens=tokens // 10)


@pytest.fixture(autouse=True)
def _quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _nothing(*args: Any, **kwargs: Any) -> None:
        return None

    async def _not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(provider_health, "note_failure", _nothing)
    monkeypatch.setattr(provider_health, "note_success", _nothing)
    monkeypatch.setattr(ai_quota, "platform_brake_tripped", _not_tripped)


# --- the shared rule ----------------------------------------------------------------------


def test_a_piece_without_usage_leaves_the_reported_part_marked_incomplete() -> None:
    """FAILS IF: an unreported piece drops the whole sum to unknown, or vanishes from it."""
    total = chat.sum_usage([_usage(100), None, _usage(50)])
    assert total is not None
    assert (total.prompt_tokens, total.incomplete) == (150, True)
    assert chat.sum_usage([_usage(100), _usage(50)]) == _usage(100).plus(_usage(50))
    assert chat.sum_usage([None, None]) is None


async def test_call_language_chunks_record_the_reported_part_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a chunk that answered without usage silently drops out of the total."""
    calls = 0

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        nonlocal calls
        calls += 1
        return chat.ChatOutcome(
            content=json.dumps({"turns": []}),
            finish_reason="stop",
            usage=_usage(100) if calls == 1 else None,
        )

    monkeypatch.setattr(chat, "complete", _complete)
    turns = [(i, f"line {i}") for i in range(call_language.TURNS_PER_REQUEST + 1)]
    result = await call_language.run_language_pass(
        api_key="k", language="en-IN", turns=turns, summary_en="x", summary_local="x"
    )
    assert calls == 2
    assert result.usage is not None
    assert (result.usage.prompt_tokens, result.usage.incomplete) == (100, True)


async def test_ocr_images_record_the_reported_part_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an image read without usage drops out of the recorded total unflagged."""
    leg = chat.ChatLeg(url="https://p.test/v1", api_key="k", wire_model=GEMINI, dialect="google")
    reads = iter([_usage(1000), None])

    async def _read(leg: chat.ChatLeg, image: Any, http: Any) -> tuple[str, None, Any]:
        return "We open at nine every day of the week.", None, next(reads)

    monkeypatch.setattr(document_ocr, "ocr_leg", lambda: leg)
    monkeypatch.setattr(document_ocr, "_transcribe", _read)
    images = [
        document_ocr.OcrImage(data=b"\xff\xd8\xff", mime_type="image/jpeg", position=n)
        for n in (1, 2)
    ]
    extracted = await document_ocr.ocr_images(images)
    assert extracted.prompt_tokens == 1000
    assert extracted.usage_incomplete is True


async def test_a_repair_answered_without_usage_keeps_the_first_attempt_as_incomplete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: one attempt without a usage block turns the known attempt into unknown."""
    settings = get_settings()
    monkeypatch.setattr(settings, "gemini_api_key", "g-test", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    calls = 0

    async def _complete(leg: chat.ChatLeg, messages: Sequence[Any], **kw: Any) -> Any:
        nonlocal calls
        calls += 1
        return chat.ChatOutcome(
            content=json.dumps({"ok": calls > 1}),
            finish_reason="stop",
            usage=_usage(100) if calls == 1 else None,
        )

    def _parse(raw: dict[str, Any]) -> bool:
        if not raw.get("ok"):
            raise script_assist.UnusableAnswerError("ok: must be true")
        return True

    monkeypatch.setattr(chat, "complete", _complete)
    answer = await script_assist.ask_json("d", "i", parse=_parse, tenant_leg=GOOGLE_LEG)
    assert answer.usage is not None
    assert (answer.usage.prompt_tokens, answer.usage.incomplete) == (100, True)


# --- on the ledger --------------------------------------------------------------------------


async def _tenant() -> UUID:
    created = await create_org_with_receptionist(
        name="Unused Turn Store",
        slug=f"unused-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email="books@example.com",
        language="te-IN",
        created_by=None,
    )
    tenant_id: UUID = created["id"]
    return tenant_id


async def _metas(tenant_id: UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT meta FROM usage_events WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).all()
    return [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]


@pytest.mark.rls
async def test_an_unused_paid_turn_is_our_cost_and_not_the_clients_allowance() -> None:
    """FAILS IF: a paid turn whose answer the client never got is recorded under the
    surface's own feature, where the monthly allowance counts it."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        charged = await assist.meter_earlier(
            session,
            tenant_id=tenant_id,
            earlier=[PaidTurn(_usage(2000), AZURE, None)],
            feature=assist.ASSIST_FEATURE_SCRIPT_DRAFT,
        )
    assert charged is False
    metas = await _metas(tenant_id)
    assert metas and {m["feature"] for m in metas} == {billing_models.ASSIST_FEATURE_UNUSED}
    assert {m["unused_for"] for m in metas} == {assist.ASSIST_FEATURE_SCRIPT_DRAFT}

    month = current_billing_month()
    async with tenant_session(tenant_id) as session:
        client = await read_ai_usage(session, tenant_id=tenant_id, month=month, include_free=False)
        ours = await read_ai_usage(session, tenant_id=tenant_id, month=month, include_free=True)
    assert client.used_inr == 0 and client.requests == 0
    assert ours.used_inr > Decimal("0")


@pytest.mark.rls
async def test_an_incomplete_total_is_recorded_flagged_and_alarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a partial total reaches the ledger with nothing saying it is partial."""
    fired: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(ai_quota, "alert", lambda stage, code, **kw: fired.append((code, kw)))
    tenant_id = await _tenant()
    partial = chat.sum_usage([_usage(1000), None])
    assert partial is not None
    async with tenant_session(tenant_id) as session:
        await assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=PaidTurn(partial, AZURE, None),
            feature=assist.ASSIST_FEATURE_RESUMMARISE,
        )
    metas = await _metas(tenant_id)
    assert metas and {m.get("usage_incomplete") for m in metas} == {"true"}
    assert [code for code, _ in fired] == [ai_quota.USAGE_INCOMPLETE_ALARM]
