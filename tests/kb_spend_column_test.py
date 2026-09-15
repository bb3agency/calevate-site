"""The cost of UPLOADING knowledge, as its own column in both consoles (D-608).

The founder's sentence is the specification: *"this cost of uploading knowledge should be
shown as a separate column / I mean the usage of this in the clients portal too"*. Ranked by
what each failure costs, worst first:

1. **The lens matches the meter.** `KB_INGESTION_FEATURES` is a tuple of strings and the
   five modules that WRITE those strings each define their own constant. If a rename moved
   one side and not the other, the column would silently read ₹0.00 for a real cost — which
   is worse than no column, because it answers the question wrongly rather than not at all.
2. **It is a COMPONENT, never a second total.** A screen that added it to `used_inr` would
   double-count a client's month.
3. **The upload is never blocked, and the balance is allowed to go negative.** The founder
   decided this explicitly and deferred what to do about it. A gate that crept back in would
   stop a client's knowledge base being indexed the moment they were busy.
4. **Both realms see it**, because the same figure is the operator's cost question and the
   client's own bill question.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from uuid import UUID

from apps.api.billing.ai_quota import (
    AI_QUOTA_INR,
    new_assist_ref,
    quota_payload,
    read_ai_quota,
    record_ai_assist_usage,
)
from apps.api.billing.models import KB_INGESTION_FEATURES
from apps.api.billing.rates import (
    LlmPriceAttestation,
    install_llm_price_attestations,
    llm_inr_per_ktok,
)
from apps.api.crm.assist import ASSIST_FEATURE_KB_GLOSS, ASSIST_FEATURE_KB_OCR
from apps.api.db.session import tenant_session
from apps.api.kb.pack_vectors import ASSIST_FEATURE_PACK_EMBED
from apps.api.retrieval.embedding import (
    ASSIST_FEATURE_CALL_SEARCH,
    ASSIST_FEATURE_KB_EMBED,
    ASSIST_FEATURE_KB_SEARCH,
    ASSIST_FEATURE_LEAD_SEARCH,
)
from apps.api.retrieval.supermemory_index import ASSIST_FEATURE_SUPERMEMORY_INGEST
from calevate_shared.engine import AZURE_OPENAI_DEFAULT_MODEL
from sqlalchemy import text
from tests.ai_quota_test import _tenant

MODEL = AZURE_OPENAI_DEFAULT_MODEL


async def _meter(tenant_id: UUID, *, feature: str, tokens_in: int) -> Decimal:
    async with tenant_session(tenant_id) as session:
        metered = await record_ai_assist_usage(
            session,
            tenant_id=tenant_id,
            ref=new_assist_ref(),
            tokens_in=tokens_in,
            tokens_out=0,
            model=MODEL,
            feature=feature,
        )
    return metered.cost_inr


def test_the_lens_names_exactly_the_five_features_that_are_bought_by_an_upload() -> None:
    """THE DRIFT GUARD, and the reason the tuple is spelled in a leaf rather than imported.

    `billing/models.py` cannot import the five modules that define these names — they import
    `billing/ai_quota`, which imports this — so the tuple is literals plus this test, the
    same registry-and-check shape hard rule 4 uses. A rename on either side is a red test
    rather than a column that reads zero.
    """
    assert set(KB_INGESTION_FEATURES) == {
        ASSIST_FEATURE_KB_GLOSS,
        ASSIST_FEATURE_KB_OCR,
        ASSIST_FEATURE_KB_EMBED,
        ASSIST_FEATURE_PACK_EMBED,
        ASSIST_FEATURE_SUPERMEMORY_INGEST,
    }
    # The three QUESTION-time features stay OUT. The line is who caused the spend: these are
    # bought because somebody asked something, which is ordinary AI use.
    assert not {
        ASSIST_FEATURE_KB_SEARCH,
        ASSIST_FEATURE_CALL_SEARCH,
        ASSIST_FEATURE_LEAD_SEARCH,
    } & set(KB_INGESTION_FEATURES)


async def test_the_knowledge_column_is_a_component_of_the_month_and_not_a_second_total() -> None:
    """One upload and one question, on one tenant, in one month.

    The upload's rupees appear in BOTH `used_inr` and `kb_used_inr`; the question's appear in
    `used_inr` alone. Adding the two published figures would over-state the month, which is
    exactly why the client screen labels the second "of which".
    """
    tenant_id = await _tenant()
    upload = await _meter(tenant_id, feature=ASSIST_FEATURE_PACK_EMBED, tokens_in=40_000)
    question = await _meter(tenant_id, feature=ASSIST_FEATURE_KB_SEARCH, tokens_in=1_000)
    assert upload > 0 and question > 0

    async with tenant_session(tenant_id) as session:
        quota = await read_ai_quota(session, tenant_id=tenant_id)

    assert quota.kb_used_inr == upload
    assert quota.used_inr == upload + question
    assert quota.kb_requests_used == 1
    assert quota.requests_used == 2


async def test_every_ingestion_feature_lands_in_the_column() -> None:
    """All five, not just the one this lane moved — an operator asking "what did their
    knowledge cost us" must not get an answer that silently omits the OCR pass."""
    tenant_id = await _tenant()
    total = Decimal("0")
    for feature in KB_INGESTION_FEATURES:
        total += await _meter(tenant_id, feature=feature, tokens_in=10_000)

    async with tenant_session(tenant_id) as session:
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    assert quota.kb_used_inr == total
    assert quota.kb_requests_used == len(KB_INGESTION_FEATURES)


async def test_uploading_past_the_allowance_takes_the_balance_negative_and_is_not_blocked() -> None:
    """THE FOUNDER'S DECISION, PINNED (D-608).

    *"Just take the balance into negative for now / We will decide better on what to do with
    it next."* So: the metering succeeds past the ceiling, `balance_inr` goes SIGNED
    negative, and `remaining_inr` stays clamped at zero for the "about N more assists"
    estimate. No KB ingestion path calls `require_ai_assist`, which is what makes the upload
    unblockable rather than merely unblocked today — and this test is what would notice a
    gate creeping back in on the metering side.
    """
    tenant_id = await _tenant()
    included = AI_QUOTA_INR["self_serve"]

    # Enough to clear the tier's whole allowance in one go, then a second upload on top.
    overshoot = await _meter(tenant_id, feature=ASSIST_FEATURE_KB_EMBED, tokens_in=7_000_000)
    assert overshoot > included
    second = await _meter(tenant_id, feature=ASSIST_FEATURE_PACK_EMBED, tokens_in=100_000)
    assert second > 0, "an upload past the ceiling was not metered"

    async with tenant_session(tenant_id) as session:
        quota = await read_ai_quota(session, tenant_id=tenant_id)

    assert quota.balance_inr < 0, "the overdraft was hidden"
    assert quota.balance_inr == quota.allowance_inr - quota.used_inr
    assert quota.remaining_inr == Decimal("0")
    assert quota.kb_used_inr == quota.used_inr


async def test_the_client_payload_publishes_the_column_and_the_signed_balance() -> None:
    """The client realm's own wire shape — the founder asked for this in the clients' portal
    too, and the browser may never divide or subtract a rupee amount to get it."""
    tenant_id = await _tenant()
    await _meter(tenant_id, feature=ASSIST_FEATURE_KB_GLOSS, tokens_in=50_000)

    async with tenant_session(tenant_id) as session:
        payload = quota_payload(await read_ai_quota(session, tenant_id=tenant_id))

    for key in ("kb_used_inr", "kb_requests_used", "balance_inr"):
        assert key in payload
    # Money is an exact digit STRING on the wire (hard rule 7), never a JSON number.
    assert isinstance(payload["kb_used_inr"], str)
    assert isinstance(payload["balance_inr"], str)
    assert Decimal(payload["kb_used_inr"]) > 0


async def test_a_month_with_no_uploads_reports_zero_rather_than_nothing() -> None:
    """Zero is a real answer here and is NOT rendered as absent: "they uploaded nothing" is
    a fact a client reading their bill is owed, and a missing field would read as an error."""
    tenant_id = await _tenant()
    await _meter(tenant_id, feature=ASSIST_FEATURE_KB_SEARCH, tokens_in=1_000)

    async with tenant_session(tenant_id) as session:
        quota = await read_ai_quota(session, tenant_id=tenant_id)
    assert quota.kb_used_inr == Decimal("0")
    assert quota.kb_requests_used == 0
    assert quota.used_inr > 0


async def test_one_tenants_uploads_never_reach_another_tenants_column() -> None:
    """RLS plus the predicate, on the query this column rides. `usage_events` is FORCE-RLS'd
    and `read_ai_quota` also names the tenant, so a cross-tenant read is zero rows twice."""
    uploader = await _tenant()
    bystander = await _tenant()
    await _meter(uploader, feature=ASSIST_FEATURE_PACK_EMBED, tokens_in=50_000)

    async with tenant_session(bystander) as session:
        quota = await read_ai_quota(session, tenant_id=bystander)
    assert quota.kb_used_inr == Decimal("0")
    assert quota.used_inr == Decimal("0")


async def test_the_split_is_one_scan_over_the_rows_the_meter_wrote() -> None:
    """No new unit type, no new ledger, no second ceiling — the column is a FILTER over rows
    that already exist. Asserted at the store so a future "kb_ktok_in" unit type, which would
    need a migration and a second idempotency key, is a deliberate act rather than a drift."""
    tenant_id = await _tenant()
    await _meter(tenant_id, feature=ASSIST_FEATURE_PACK_EMBED, tokens_in=10_000)

    async with tenant_session(tenant_id) as session:
        units = (
            await session.execute(
                text("SELECT DISTINCT unit_type FROM usage_events WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).all()
    assert sorted(u[0] for u in units) == ["ai_assist_ktok_in", "ai_assist_ktok_out"]


def test_an_input_only_attestation_can_price_an_upload() -> None:
    """The seam that connects this column to D-608's other half: once the encoder's price is
    attested INPUT-ONLY, an embedding's rows carry a real `unit_cost_paid` on the input leg
    and an exact zero on the output leg — which is the truth about an embedding rather than
    a default (`kb/pack_vectors._vectors_for` passes `tokens_out=0`)."""
    encoder = "models/gemini-embedding-2"
    try:
        install_llm_price_attestations(
            lambda: {
                encoder: LlmPriceAttestation(
                    model=encoder,
                    input_usd_per_mtok=Decimal("0.20"),
                    output_usd_per_mtok=None,
                    read_on=date(2026, 9, 15),
                    attested_by="founder",
                    source="Google Cloud billing export 2026-09",
                )
            }
        )
        priced = llm_inr_per_ktok(encoder)
        assert priced["in"] > 0
        assert priced["out"] == Decimal("0.0000")
    finally:
        install_llm_price_attestations(None)
