"""Sarvam 105B is priced per token, and the legs that call it record what it cost us.

VENDOR-PUBLISHED, https://www.sarvam.ai/api-pricing, read 10 Oct 2026: ₹29.28 input /
₹10.98 cached input / ₹73.20 output per 1M tokens (superseding D-35(a)/D-36's "free").
The properties, each a way the change could be undone:

1. The figure reaches `unit_cost_paid` ONLY through an operator attestation (hard rule 7).
2. The assistant's standby is recorded at our cost, reported as not metered, and never
   counted against the client's AI allowance (founder, 10 Oct 2026).
3. The post-call extraction pass is recorded at our cost, absorbed the same way.
4. The attestation is stored in rupees, append-only, and read back by the billing door.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import ai_quota, rates
from apps.api.billing.ai_quota import new_assist_ref, read_ai_usage
from apps.api.billing.models import ASSIST_FEATURE_CALL_EXTRACTION, ASSIST_FEATURE_STANDBY
from apps.api.billing.service import current_billing_month
from apps.api.crm import assist
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops import model_pricing
from apps.workers import extraction as extraction_module
from apps.workers import pipeline
from apps.workers.chat import TokenUsage, usage_from_body
from apps.workers.extraction import AssistCapability, AssistResult, SarvamExtractor
from calevate_shared.engine import SARVAM_DEFAULT_LLM
from calevate_shared.extraction import ExtractionOutput
from sqlalchemy import text

ATTESTED = rates.InrLlmPriceAttestation(
    model=SARVAM_DEFAULT_LLM,
    in_inr_per_mtok=Decimal("29.28"),
    cached_in_inr_per_mtok=Decimal("10.98"),
    out_inr_per_mtok=Decimal("73.20"),
    attested_by="founder",
    source="sarvam.ai/api-pricing, read 10 Oct 2026",
)
USAGE = TokenUsage(prompt_tokens=2_000, output_tokens=500, cached_prompt_tokens=300)


@pytest.fixture(autouse=True)
def _brake_not_tripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ai_quota_test`'s reason: the platform brake is a global counter this file must not
    depend on."""

    async def not_tripped(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


@pytest.fixture
def attested() -> Iterator[None]:
    rates.install_inr_llm_price_attestations(lambda: {SARVAM_DEFAULT_LLM: ATTESTED})
    yield
    rates.install_inr_llm_price_attestations(None)


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Sarvam Cost Clinic",
        slug=f"svc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="books@example.com",
        language="te-IN",
        created_by=None,
    )
    tenant_id: UUID = created["id"]
    return tenant_id


class _Row:
    def __init__(self, unit_type: str, unit_cost_paid: Decimal, meta: Any) -> None:
        self.unit_type = unit_type
        self.unit_cost_paid = unit_cost_paid
        self.meta: dict[str, Any] = meta if isinstance(meta, dict) else json.loads(meta)


async def _rows(tenant_id: UUID) -> list[_Row]:
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
    return [_Row(str(r[0]), Decimal(str(r[1])), r[2]) for r in rows]


def _standby(usage: TokenUsage | None) -> AssistResult:
    return AssistResult(
        output=ExtractionOutput(summary="Sarvam answered."),
        capability=AssistCapability(
            available=True,
            provider=extraction_module.SARVAM_PROVIDER,
            fallback_reason=extraction_module.PROVIDER_UNAVAILABLE_REASON,
        ),
        usage=usage,
    )


# --- 1: the reference never bills ------------------------------------------------------


def test_the_reference_card_carries_the_published_figures_and_its_source() -> None:
    assert rates.SARVAM_LLM_INR_PER_MTOK["in"] == Decimal("29.28")
    assert rates.SARVAM_LLM_INR_PER_MTOK["cached_in"] == Decimal("10.98")
    assert rates.SARVAM_LLM_INR_PER_MTOK["out"] == Decimal("73.20")
    assert rates.SARVAM_LLM_PRICE_SOURCE == "https://www.sarvam.ai/api-pricing"
    assert rates.SARVAM_LLM_PRICE_READ_ON.isoformat() == "2026-10-10"


def test_unattested_sarvam_has_no_billing_price() -> None:
    assert rates.inr_llm_inr_per_ktok(SARVAM_DEFAULT_LLM) is None
    assert rates.llm_price_is_billable(SARVAM_DEFAULT_LLM) is False
    with pytest.raises(ValueError, match="no operator has attested"):
        rates.llm_inr_per_ktok(SARVAM_DEFAULT_LLM)


def test_an_attestation_opens_the_door_in_rupees(attested: None) -> None:
    per_ktok = rates.inr_llm_inr_per_ktok(SARVAM_DEFAULT_LLM)
    assert per_ktok is not None
    assert per_ktok["in"] == Decimal("0.0293")
    assert per_ktok["cached_in"] == Decimal("0.0110")
    assert per_ktok["out"] == Decimal("0.0732")
    assert rates.llm_inr_per_ktok(SARVAM_DEFAULT_LLM) == {
        "in": Decimal("0.0293"),
        "out": Decimal("0.0732"),
    }
    assert rates.llm_price_is_billable(SARVAM_DEFAULT_LLM) is True


def test_the_cached_input_count_is_read_as_a_subset_of_the_prompt() -> None:
    usage = usage_from_body(
        {
            "usage": {
                "prompt_tokens": 1_000,
                "completion_tokens": 200,
                "prompt_tokens_details": {"cached_tokens": 400},
            }
        }
    )
    assert usage == TokenUsage(prompt_tokens=1_000, output_tokens=200, cached_prompt_tokens=400)


# --- 2: the standby is ours --------------------------------------------------------------


async def test_the_standby_is_recorded_at_its_cost_and_not_charged_to_the_client(
    attested: None,
) -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        metering = await assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=_standby(USAGE),
            feature=assist.ASSIST_FEATURE_COPILOT,
        )

    assert metering.metered is False, "the client is never told they paid for the standby"
    assert metering.cost_inr == Decimal("2") * Decimal("0.0293") + Decimal("0.5") * Decimal(
        "0.0732"
    )
    rows = await _rows(tenant_id)
    assert [row.unit_type for row in rows] == ["ai_assist_ktok_in", "ai_assist_ktok_out"]
    assert {row.meta["feature"] for row in rows} == {ASSIST_FEATURE_STANDBY}
    assert {row.meta["standby_for"] for row in rows} == {assist.ASSIST_FEATURE_COPILOT}
    assert {row.meta["model"] for row in rows} == {SARVAM_DEFAULT_LLM}

    month = current_billing_month()
    client_view = await _usage(tenant_id, month, include_free=False)
    our_view = await _usage(tenant_id, month, include_free=True)
    assert client_view.used_inr == 0, "the standby must not draw on the client's AI allowance"
    assert client_view.requests == 0
    assert our_view.used_inr == metering.cost_inr, "it is on our ledger at its true cost"


async def _usage(tenant_id: UUID, month: str, *, include_free: bool) -> Any:
    async with tenant_session(tenant_id) as session:
        return await read_ai_usage(
            session, tenant_id=tenant_id, month=month, include_free=include_free
        )


async def test_an_unattested_standby_writes_nothing() -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        metering = await assist.meter_assist(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            result=_standby(USAGE),
        )
    assert metering.metered is False
    assert metering.cost_inr == 0
    assert await _rows(tenant_id) == []


# --- 3: the post-call extraction pass ---------------------------------------------------


async def test_the_extraction_pass_is_recorded_at_its_cost(attested: None) -> None:
    tenant_id = await _tenant()
    call_id = uuid.uuid4()
    extractor = SarvamExtractor("key")
    extractor.last_usage = USAGE

    await pipeline._meter_extraction(tenant_id, call_id, extractor)

    rows = await _rows(tenant_id)
    assert [row.unit_type for row in rows] == ["ai_assist_ktok_in", "ai_assist_ktok_out"]
    assert {row.meta["feature"] for row in rows} == {ASSIST_FEATURE_CALL_EXTRACTION}
    assert {row.meta["call_id"] for row in rows} == {str(call_id)}
    assert {row.unit_cost_paid for row in rows} == {Decimal("0.0293"), Decimal("0.0732")}
    client_view = await _usage(tenant_id, current_billing_month(), include_free=False)
    assert client_view.used_inr == 0, "extraction is part of serving the call"


async def test_an_unpriced_or_unreported_extraction_writes_nothing() -> None:
    tenant_id = await _tenant()
    extractor = SarvamExtractor("key")
    extractor.last_usage = USAGE
    await pipeline._meter_extraction(tenant_id, uuid.uuid4(), extractor)  # unattested
    extractor.last_usage = None
    await pipeline._meter_extraction(tenant_id, uuid.uuid4(), extractor)  # no usage block
    assert await _rows(tenant_id) == []


# --- 4: the attestation store -------------------------------------------------------------


async def test_an_attestation_is_stored_in_rupees_and_read_back() -> None:
    """Rolled back, because the table is append-only and global: a committed row would
    make every later run's Sarvam leg billable."""
    actor = await _admin_id()
    effective = datetime.now(UTC) - timedelta(seconds=1)
    async with untenanted_session() as session:
        try:
            await model_pricing.attest_inr_llm_price(
                session,
                model=SARVAM_DEFAULT_LLM,
                in_inr_per_mtok=Decimal("29.28"),
                cached_in_inr_per_mtok=Decimal("10.98"),
                out_inr_per_mtok=Decimal("73.20"),
                effective_from=effective,
                source_note="sarvam.ai/api-pricing, read 10 Oct 2026",
                actor_id=actor,
            )
            read = await model_pricing.attested_inr_llm_prices(session, at=datetime.now(UTC))
        finally:
            await session.rollback()
    record = read[SARVAM_DEFAULT_LLM]
    assert record.in_inr_per_mtok == Decimal("29.28")
    assert record.cached_in_inr_per_mtok == Decimal("10.98")
    assert record.out_inr_per_mtok == Decimal("73.20")


async def test_only_a_rupee_billed_model_can_be_attested_here() -> None:
    from apps.api.core.errors import ProblemError

    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as refused:
            await model_pricing.attest_inr_llm_price(
                session,
                model="gpt-4o-mini",
                in_inr_per_mtok=Decimal("1"),
                cached_in_inr_per_mtok=None,
                out_inr_per_mtok=Decimal("1"),
                effective_from=datetime.now(UTC),
                source_note="x" * 5,
                actor_id=uuid.uuid4(),
            )
    assert refused.value.code == "inr_llm_price_unknown_model"


async def _admin_id() -> UUID:
    """One operator account (`admin_copilot_billing_test._make_admin`'s idiom)."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id
