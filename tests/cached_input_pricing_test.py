"""Input a provider served from its prompt cache is priced at the attested cached rung (D-816).

Every test here fails at bdc20490: there was no cached rung on a USD attestation, no
`ai_assist_10ktok_cached_in` unit, and both AI ledgers priced every input token at the full
rate whatever the provider reported.

Arithmetic, at `PLANNING_USD_INR` = 95 and Gemini 3.1 Flash-Lite's attested $0.25 / $1.50 /
$0.025 per million (input / output / cached; ai.google.dev/gemini-api/docs/pricing, read
18 Oct 2026): input ₹0.0238 per thousand, output ₹0.1425 per thousand, cached ₹0.0238 per TEN
thousand. A question of 16,000 input tokens, 12,000 of them cached, and 100 output tokens is
4 x 0.0238 + 1.2 x 0.0238 + 0.1 x 0.1425 = ₹0.13801, against ₹0.39505 at the full rate.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import platform_ai, rates
from apps.api.billing.ai_quota import (
    assist_ledger_rows,
    new_assist_ref,
    read_ai_quota,
    record_ai_assist_usage,
)
from apps.api.billing.models import AI_ASSIST_UNIT_TYPES, PLATFORM_ABSORBED_UNIT_TYPES
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops import model_pricing, pricing_snapshot
from apps.workers.chat import TokenUsage, usage_from_body
from sqlalchemy import text

MODEL = "gemini-3.1-flash-lite"
CACHED_UNIT = "ai_assist_10ktok_cached_in"


def _attestation(cached: Decimal | None) -> rates.LlmPriceAttestation:
    return rates.LlmPriceAttestation(
        model=MODEL,
        input_usd_per_mtok=Decimal("0.25"),
        output_usd_per_mtok=Decimal("1.50"),
        read_on=date(2026, 10, 18),
        attested_by="founder",
        source="ai.google.dev/gemini-api/docs/pricing, read 18 Oct 2026",
        cached_input_usd_per_mtok=cached,
    )


@pytest.fixture
def cached_rung() -> Iterator[None]:
    rates.install_llm_price_attestations(lambda: {MODEL: _attestation(Decimal("0.025"))})
    yield
    rates.install_llm_price_attestations(None)


@pytest.fixture
def no_cached_rung() -> Iterator[None]:
    rates.install_llm_price_attestations(lambda: {MODEL: _attestation(None)})
    yield
    rates.install_llm_price_attestations(None)


def _cost(rows: tuple[tuple[str, Decimal, Decimal], ...]) -> Decimal:
    return sum((qty * price for _, qty, price in rows), Decimal("0"))


def test_the_cached_unit_is_an_absorbed_ai_assist_unit() -> None:
    assert CACHED_UNIT in AI_ASSIST_UNIT_TYPES
    assert CACHED_UNIT in PLATFORM_ABSORBED_UNIT_TYPES


def test_the_cached_rung_comes_only_from_an_attestation(cached_rung: None) -> None:
    assert rates.cached_input_inr_per_unit(MODEL) == Decimal("0.0238")
    assert rates.cached_input_inr_per_unit("gpt-4o-mini") is None


def test_a_cached_price_above_the_input_price_or_at_zero_is_refused() -> None:
    for bad in (Decimal("0.30"), Decimal("0")):
        with pytest.raises(ValueError, match="cached-input price"):
            _attestation(bad)


def test_a_reported_hit_with_a_rung_is_priced_at_the_rung(cached_rung: None) -> None:
    rows = assist_ledger_rows(
        model=MODEL, tokens_in=16_000, tokens_out=100, cached_tokens_in=12_000
    )
    assert [unit for unit, _, _ in rows] == ["ai_assist_ktok_in", "ai_assist_ktok_out", CACHED_UNIT]
    assert rows[0][1] == Decimal("4") and rows[2][1] == Decimal("1.2")
    assert _cost(rows) == Decimal("0.13801")


def test_no_rung_or_no_report_prices_every_input_token_in_full(no_cached_rung: None) -> None:
    full = Decimal("0.39505")
    for cached in (12_000, None):
        rows = assist_ledger_rows(
            model=MODEL, tokens_in=16_000, tokens_out=100, cached_tokens_in=cached
        )
        assert len(rows) == 2 and _cost(rows) == full
    rates.install_llm_price_attestations(lambda: {MODEL: _attestation(Decimal("0.025"))})
    rows = assist_ledger_rows(model=MODEL, tokens_in=16_000, tokens_out=100, cached_tokens_in=None)
    assert len(rows) == 2 and _cost(rows) == full


def test_a_rupee_billed_models_cached_rung_comes_from_its_rupee_attestation() -> None:
    """A vendor that invoices in rupees is attested in rupees and never crosses the exchange
    rate; with no cached rung on file its input is priced in full. Test figures only."""

    def _inr(cached: Decimal | None) -> rates.InrLlmPriceAttestation:
        return rates.InrLlmPriceAttestation(
            model="inr-test-model",
            in_inr_per_mtok=Decimal("30"),
            cached_in_inr_per_mtok=cached,
            out_inr_per_mtok=Decimal("90"),
            attested_by="founder",
            source="test figures",
        )

    held = rates._inr_attestation_reader
    try:
        rates.install_inr_llm_price_attestations(lambda: {"inr-test-model": _inr(Decimal("15"))})
        # ₹15 per million is ₹0.15 per ten thousand.
        assert rates.cached_input_rate_exact("inr-test-model") == Decimal("0.15")
        assert rates.cached_input_inr_per_unit("inr-test-model") == Decimal("0.1500")
        rates.install_inr_llm_price_attestations(lambda: {"inr-test-model": _inr(None)})
        assert rates.cached_input_rate_exact("inr-test-model") is None
    finally:
        rates.install_inr_llm_price_attestations(held)


def test_a_reported_count_is_told_apart_from_a_missing_one() -> None:
    body = {"usage": {"prompt_tokens": 100, "completion_tokens": 5}}
    assert usage_from_body(body) == TokenUsage(prompt_tokens=100, output_tokens=5)
    body["usage"]["prompt_tokens_details"] = {"cached_tokens": 0}  # type: ignore[index]
    reported = usage_from_body(body)
    assert reported is not None and reported.cached_tokens_in == 0
    silent = TokenUsage(prompt_tokens=100, output_tokens=5, cached_prompt_tokens=40)
    assert reported.plus(silent).cached_tokens_in is None


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Cache Clinic",
        slug=f"cache-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id: uuid.UUID = created["id"]
    return tenant_id


async def test_the_tenant_ledger_writes_the_cached_row_and_the_quota_counts_it(
    cached_rung: None,
) -> None:
    tenant_id = await _tenant()
    ref = new_assist_ref()
    async with tenant_session(tenant_id) as session:
        before = await read_ai_quota(session, tenant_id=tenant_id, include_free=True)
        metered = await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=ref,
            tokens_in=16_000,
            tokens_out=100,
            model=MODEL,
            feature="copilot",
            cached_tokens_in=12_000,
        )
        replay = await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=ref,
            tokens_in=16_000,
            tokens_out=100,
            model=MODEL,
            feature="copilot",
            cached_tokens_in=12_000,
        )
        rows = (
            await session.execute(
                text(
                    "SELECT unit_type, qty, unit_cost_paid, meta->>'cached_prompt_tokens' "
                    "FROM usage_events WHERE tenant_id = :t AND ref = :r ORDER BY unit_type"
                ),
                {"t": tenant_id, "r": ref},
            )
        ).all()
        after = await read_ai_quota(session, tenant_id=tenant_id, include_free=True)
    assert metered.cost_inr == Decimal("0.13801") and not replay.recorded
    assert {row[0] for row in rows} == {"ai_assist_ktok_in", "ai_assist_ktok_out", CACHED_UNIT}
    assert {row[3] for row in rows} == {"12000"}
    assert after.used_inr - before.used_inr == sum(row[1] * row[2] for row in rows)
    assert after.requests_used - before.requests_used == 1


async def test_the_platform_ledger_writes_the_cached_row(cached_rung: None) -> None:
    admin_id = uuid.uuid4()
    ref = new_assist_ref()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
        metered = await platform_ai.record_platform_ai_usage(
            session,
            admin_user_id=admin_id,
            ref=ref,
            tokens_in=16_000,
            tokens_out=100,
            model=MODEL,
            feature="admin_copilot",
            cached_tokens_in=12_000,
        )
        units = (
            await session.execute(
                text("SELECT unit_type FROM platform_ai_usage WHERE ref = :r"), {"r": ref}
            )
        ).scalars()
        assert set(units) == {"ai_assist_ktok_in", "ai_assist_ktok_out", CACHED_UNIT}
    assert metered.cost_inr == Decimal("0.13801")


async def test_an_operator_attests_a_cached_rung_and_billing_reads_it() -> None:

    admin_id = uuid.uuid4()
    # Far in the future, so no other test pricing this model "now" sees the row.
    at = datetime(2100, 1, 1, tzinfo=UTC) + timedelta(seconds=uuid.uuid4().int % 10**8)
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
        with pytest.raises(ProblemError) as refused:
            await model_pricing.attest_price(
                session,
                model=MODEL,
                input_usd_per_mtok=Decimal("0.25"),
                output_usd_per_mtok=Decimal("1.50"),
                cached_input_usd_per_mtok=Decimal("0.30"),
                effective_from=at,
                source_note="invoice",
                actor_id=admin_id,
            )
        assert refused.value.code == "model_price_cached_out_of_range"
        await model_pricing.attest_price(
            session,
            model=MODEL,
            input_usd_per_mtok=Decimal("0.25"),
            output_usd_per_mtok=Decimal("1.50"),
            cached_input_usd_per_mtok=Decimal("0.025"),
            effective_from=at,
            source_note="invoice",
            actor_id=admin_id,
        )
        stored = (await model_pricing.attested_model_prices(session, at=at))[MODEL]
    assert stored.cached_input_usd_per_mtok == Decimal("0.025")
    attestation = pricing_snapshot._to_attestation(stored)
    assert attestation is not None and attestation.cached_input_usd_per_mtok == Decimal("0.025")


def test_the_cache_counts_survive_the_log_redactor() -> None:
    """An operator reads the hit rate from these fields; a redacted count reads as nothing."""
    from apps.api.billing.ai_quota import cache_log_fields
    from apps.api.core.logging import redact_mapping

    fields = cache_log_fields(tokens_in=6000, cached_tokens_in=4096)
    assert redact_mapping(dict(fields)) == {"input_count": 6000, "cached_input_count": 4096}
