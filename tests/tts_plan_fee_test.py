"""The voice vendor's INVOICE, beside what our own meter attributed (D-547 Phase D.3).

Two independent measurements of one month, and every case here is about keeping them
apart:

- **PLAN SPEND** is what the vendor billed — a committed monthly fee for a character
  allotment, paid whether or not the allotment is spoken. Nothing in this tree can fetch
  it (`cartesia.ai` is egress-blocked here), so it is an OPERATOR ATTESTATION, append-only
  and dated, and hard rule 7 gives the catalogue figure no path to it.
- **ATTRIBUTED** is what our meter charged to calls: the attested per-character rate times
  the characters our own transcripts say the agents spoke, summed off `usage_events`.

Their difference is the allotment nobody spoke into. The properties pinned below are the
ones that make that difference trustworthy rather than merely present:

1. **A month nobody attested has NO ROW, never a ₹0 one.** ₹0 reads as "the vendor billed
   us nothing", which is the one misreading of a missing invoice that flatters us.
2. **Sarvam never appears and cannot be attested.** The engine buys that synthesis and
   reports what it charged on every call, so there is no invoice of ours and no
   `tts_kchars` character count of ours to compare one against.
3. **A correction is a later attestation, never an edit.** The trigger proves it at the
   database; the reader proves the newest belief wins and the older one survives.
4. **Every figure is the SERVER's** — the subtraction included (D-458).

⚠ **TWO UNKNOWNS ARE CARRIED, NOT CLOSED.** Cartesia's OVERAGE rate past the allotment is
UNKNOWN (plan ADDENDUM 1, unknown #3): the attested per-character price prices characters
INSIDE the allotment only. And whether the vendor's own character count agrees with ours is
UNKNOWN (OPERATIONS §2 gate 51): `usage_events.qty` is counted from OUR transcript and from
nothing the vendor says. Nothing here reconciles either, and no test below pretends to.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing import spend_routes
from apps.api.billing.plans import ist_month_window
from apps.api.billing.rates import CARTESIA_STARTUP_PLAN_FEE_INR, VOICE_TIERS
from apps.api.billing.spend_routes import (
    _NO_TTS_ATTRIBUTION,
    _tts_plan_rows,
    _TtsAttribution,
)
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.registry import APPEND_ONLY_TABLES, RLS_EXEMPT_TENANT_COLUMNS, Base
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.ops.model_price_routes import tts_plan_fee_confirmation
from apps.api.ops.model_pricing import (
    PLAN_BILLED_TTS_PROVIDERS,
    TTS_PROVIDERS,
    TtsPlanFeeAttestation,
    TtsPriceAttestation,
    attest_tts_plan_fee,
    attested_tts_plan_fees,
    reference_tts_plan_fee,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

MONTH = "2026-01"
NOW = datetime(2026, 2, 3, 9, 0, tzinfo=UTC)


def _unique_month() -> str:
    """A billing month of this case's own, from a range no real row can be in.

    EVERY DB CASE HERE NEEDS ONE, and the reason is that this table is APPEND-ONLY: the
    rows a case writes survive the run, so a second run against the same development
    database re-attests the same `(provider, month, effective_from)` and is refused —
    correctly, and looking exactly like a bug in the code under test. The range is
    deliberately absurd (six thousand years wide, starting a millennium out) so that two
    cases in one run, two runs, or two lanes against one database cannot collide. A
    narrower one collides at the birthday rate, which is a flake that reads as a metering
    defect.
    """
    return f"{3000 + uuid.uuid4().int % 6000}-{1 + uuid.uuid4().int % 12:02d}"


# ------------------------------------------------------------------ the vocabulary


def test_the_plan_billed_set_is_inside_the_voice_vocabulary() -> None:
    """A fee can only be attested for a vendor the rest of the product knows about."""
    assert set(TTS_PROVIDERS) >= PLAN_BILLED_TTS_PROVIDERS
    assert set(VOICE_TIERS) >= PLAN_BILLED_TTS_PROVIDERS


def test_sarvam_is_not_plan_billed() -> None:
    """THE SARVAM DECISION, pinned rather than described. The engine buys that synthesizer
    leg and reports what it charged on every call, so there is no monthly invoice of ours
    to attest — and its cost lands on `tts_chars` at `qty = 1` (a whole-leg charge with no
    character count), never on the `tts_kchars` rows this board sums."""
    assert "sarvam" not in PLAN_BILLED_TTS_PROVIDERS


def test_only_one_vendor_is_plan_billed_because_the_ledger_cannot_tell_two_apart() -> None:
    """`_TTS_ATTRIBUTED_SQL` discriminates by UNIT TYPE and by nothing else, because a
    `usage_events` row carries no vendor. A second plan-billed vendor would therefore have
    both vendors' characters summed into each of its rows — so admitting one is a
    MIGRATION (a discriminator on the ledger row) and not an edit to a frozenset, and this
    is the assertion that says so before the money is wrong."""
    assert len(PLAN_BILLED_TTS_PROVIDERS) == 1
    assert "tts_kchars" in spend_routes._TTS_ATTRIBUTED_SQL
    assert "provider" not in spend_routes._TTS_ATTRIBUTED_SQL


def test_the_table_is_registered_as_append_only_and_platform_scoped() -> None:
    """The two registries a new ledger has to be in, and the ORM model `restore_drill`
    needs. Read off the registries themselves, never restated."""
    assert "platform_tts_plan_fees" in APPEND_ONLY_TABLES
    assert "platform_tts_plan_fees" in RLS_EXEMPT_TENANT_COLUMNS
    assert RLS_EXEMPT_TENANT_COLUMNS["platform_tts_plan_fees"].strip()
    assert Base.metadata.tables.get("platform_tts_plan_fees") is not None


def test_the_reference_fee_is_the_form_prefill_and_nothing_else() -> None:
    """`rates.CARTESIA_STARTUP_PLAN_FEE_INR` is REPORTED — $49 at a relayed conversion, for
    a plan nobody has bought — so it pre-fills the form and never reaches a stored figure.
    Pinned as an equality so a future edit that made the reference authoritative shows up
    here rather than on an invoice."""
    assert reference_tts_plan_fee("cartesia") == CARTESIA_STARTUP_PLAN_FEE_INR


def test_a_reference_fee_is_refused_for_a_vendor_with_no_plan() -> None:
    with pytest.raises(ProblemError) as raised:
        reference_tts_plan_fee("sarvam")
    assert raised.value.code == "tts_plan_fee_provider_not_plan_billed"


def test_the_step_up_string_names_the_vendor_and_the_month() -> None:
    """Bound to BOTH: a header captured while attesting September must not be replayable to
    restate October, which is the correction this table exists to keep honest."""
    assert (
        tts_plan_fee_confirmation("cartesia", "2026-01") == "attest_tts_plan_fee:cartesia:2026-01"
    )


# ------------------------------------------------------- the row renderer, every branch


def _fee(plan_inr: str = "4312.00") -> TtsPlanFeeAttestation:
    return TtsPlanFeeAttestation(
        provider="cartesia",
        month=MONTH,
        plan_inr=Decimal(plan_inr),
        effective_from=NOW,
        attested_at=NOW,
        attested_by="ops",
        source_note="Cartesia Startup plan, invoice INV-2026-01-014",
    )


def _price(rate: str = "3.4496") -> TtsPriceAttestation:
    return TtsPriceAttestation(
        provider="cartesia",
        inr_per_1k_chars=Decimal(rate),
        effective_from=NOW,
        attested_at=NOW,
        attested_by="ops",
        source_note="the same invoice, divided by its allotment",
    )


def test_a_month_with_no_attestation_renders_no_row_at_all() -> None:
    """THE PROPERTY THIS CARD EXISTS FOR. Not a row of zeroes, not a row with a null fee:
    no row. A ₹0 plan spend would say the vendor billed us nothing, and a fleet margin
    computed against it would be a margin we do not have."""
    assert (
        _tts_plan_rows(
            month=MONTH,
            fees={},
            prices={"cartesia": _price()},
            attributed=_TtsAttribution(
                inr=Decimal("100.00"), chars=Decimal(29000), unpriced_rows=0
            ),
        )
        == []
    )


def test_an_attested_month_publishes_the_plan_the_attribution_and_the_difference() -> None:
    rows = _tts_plan_rows(
        month=MONTH,
        fees={"cartesia": _fee()},
        prices={"cartesia": _price()},
        attributed=_TtsAttribution(
            inr=Decimal("1234.5678"), chars=Decimal("358000"), unpriced_rows=0
        ),
    )
    assert len(rows) == 1
    row = rows[0]
    assert row.provider == "cartesia"
    # The vendor is named here and the CLIENT's name for the tier travels beside it, served
    # rather than spelled in a browser.
    assert row.tier_label == "Studio"
    assert row.month == MONTH
    assert row.plan_inr == "4312.00"
    assert row.attributed_inr == "1234.57"
    # THE SERVER'S SUBTRACTION (D-458), against the same rounded figure it published.
    assert row.unused_inr == "3077.43"
    assert Decimal(row.plan_inr) - Decimal(row.attributed_inr) == Decimal(row.unused_inr)
    assert row.chars == "358000"
    assert row.inr_per_1k_chars == "3.4496"


def test_a_month_that_outran_its_plan_reports_a_negative_difference() -> None:
    """NOT CLAMPED AT ZERO. Attributing more than the plan charged is what running into an
    overage looks like from our side of the meter — and the vendor's overage RATE is
    UNKNOWN, so the signed difference is the only honest report. A floor at zero would hide
    the state the card matters most in."""
    rows = _tts_plan_rows(
        month=MONTH,
        fees={"cartesia": _fee()},
        prices={"cartesia": _price()},
        attributed=_TtsAttribution(
            inr=Decimal("5000.00"), chars=Decimal(1_449_400), unpriced_rows=0
        ),
    )
    assert rows[0].unused_inr == "-688.00"


def test_an_incomplete_attribution_withholds_the_difference_rather_than_flattering_it() -> None:
    """`unit_cost_paid` is NULLable and `SUM` skips a NULL silently, so a month holding an
    unpriced row would report a smaller attributed total and therefore a LARGER unused
    allotment. The difference is withheld; `attributed_inr` still reports what WAS
    attributed, which stays true of the rows it summed."""
    rows = _tts_plan_rows(
        month=MONTH,
        fees={"cartesia": _fee()},
        prices={"cartesia": _price()},
        attributed=_TtsAttribution(inr=Decimal("100.00"), chars=Decimal(29000), unpriced_rows=1),
    )
    assert rows[0].unused_inr is None
    assert rows[0].attributed_inr == "100.00"
    assert rows[0].chars == "29000"


def test_an_unpriced_vendor_reports_no_rate_rather_than_a_zero_one() -> None:
    """A fee can be attested before anybody attests the per-character price — the invoice
    arrives whether or not the division has been done. `null` is the honest answer and is a
    different state from ₹0.0000 per 1,000 characters."""
    rows = _tts_plan_rows(
        month=MONTH, fees={"cartesia": _fee()}, prices={}, attributed=_NO_TTS_ATTRIBUTION
    )
    assert rows[0].inr_per_1k_chars is None
    assert rows[0].attributed_inr == "0.00"


def test_the_walk_accumulates_across_tenants() -> None:
    """Cross-tenant totals are unaskable under FORCEd RLS, so the board sums what each
    client's own scope reported. `plus` is that addition, in one place."""
    total = _NO_TTS_ATTRIBUTION.plus(Decimal("10.00"), Decimal(3000), 0).plus(
        Decimal("2.50"), Decimal(700), 2
    )
    assert total == _TtsAttribution(inr=Decimal("12.50"), chars=Decimal(3700), unpriced_rows=2)


# ------------------------------------------------------------------ the attestation


async def _operator() -> UUID:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id


async def _attest(
    actor: UUID, *, month: str, plan_inr: str, effective_from: datetime, provider: str = "cartesia"
) -> TtsPlanFeeAttestation:
    async with untenanted_session() as session:
        return await attest_tts_plan_fee(
            session,
            provider=provider,
            month=month,
            plan_inr=Decimal(plan_inr),
            effective_from=effective_from,
            source_note="invoice INV-2026-01-014",
            actor_id=actor,
        )


async def _read(month: str, *, at: datetime) -> dict[str, TtsPlanFeeAttestation]:
    async with untenanted_session() as session:
        return await attested_tts_plan_fees(session, month=month, at=at)


async def test_an_attested_fee_reads_back_with_its_provenance() -> None:
    actor = await _operator()
    month = _unique_month()
    written = await _attest(actor, month=month, plan_inr="4312.00", effective_from=NOW)
    assert written.plan_inr == Decimal("4312.00")

    read = await _read(month, at=NOW + timedelta(days=1))
    assert read["cartesia"].plan_inr == Decimal("4312.00")
    # Provenance, not just the number: a figure in a table is indistinguishable from one
    # somebody guessed without it.
    assert read["cartesia"].attested_by == str(actor)
    assert read["cartesia"].source_note == "invoice INV-2026-01-014"


async def test_a_correction_is_a_later_attestation_and_the_older_belief_survives() -> None:
    """The newest belief at or before the reading instant wins; asked as of the earlier
    instant, the table still says what we believed then. That is the whole reason
    `effective_from` is in the key rather than a column somebody could overwrite."""
    actor = await _operator()
    month = _unique_month()
    await _attest(actor, month=month, plan_inr="4312.00", effective_from=NOW)
    await _attest(actor, month=month, plan_inr="4560.00", effective_from=NOW + timedelta(days=2))

    assert (await _read(month, at=NOW + timedelta(days=5)))["cartesia"].plan_inr == Decimal(
        "4560.00"
    )
    assert (await _read(month, at=NOW + timedelta(days=1)))["cartesia"].plan_inr == Decimal(
        "4312.00"
    )


async def test_a_fee_attested_after_the_month_closed_is_still_visible() -> None:
    """THE REASON `at` IS THE BELIEF INSTANT AND NOT THE MONTH. An invoice arrives weeks
    after its month ends. Resolving the fee at the month's own last instant — the way a
    PRICE is resolved, because a call's cost was struck inside it — would make the
    attestation invisible on the board it exists for."""
    actor = await _operator()
    month = _unique_month()
    _, next_start = ist_month_window(month)
    await _attest(actor, month=month, plan_inr="4312.00", effective_from=next_start)
    assert await _read(month, at=next_start - timedelta(seconds=1)) == {}
    assert (await _read(month, at=next_start + timedelta(days=14)))["cartesia"].plan_inr == Decimal(
        "4312.00"
    )


async def test_a_naive_reading_instant_is_refused() -> None:
    """A naive instant has no month, and comparing one against `timestamptz` is how a
    board reads a different month on a UTC server and an IST laptop."""
    async with untenanted_session() as session:
        with pytest.raises(ValueError, match="timezone-aware"):
            await attested_tts_plan_fees(session, month=MONTH, at=datetime(2026, 2, 3))


async def test_re_attesting_the_same_instant_is_refused_with_a_sentence() -> None:
    """The one write an append-only table cannot express, refused as a 409 an operator can
    act on rather than surfacing as a 500 on a primary-key violation."""
    actor = await _operator()
    month = _unique_month()
    await _attest(actor, month=month, plan_inr="4312.00", effective_from=NOW)
    with pytest.raises(ProblemError) as raised:
        await _attest(actor, month=month, plan_inr="4560.00", effective_from=NOW)
    assert raised.value.code == "tts_plan_fee_duplicate_instant"
    assert "later effective date" in (raised.value.remediation or "")


async def test_a_zero_fee_is_refused_because_absence_already_has_a_spelling() -> None:
    actor = await _operator()
    with pytest.raises(ProblemError) as raised:
        await _attest(actor, month=MONTH, plan_inr="0.00", effective_from=NOW)
    assert raised.value.code == "tts_plan_fee_not_positive"


async def test_a_vendor_with_no_monthly_plan_cannot_be_attested() -> None:
    """Refused rather than stored: a Sarvam fee would render a row whose `attributed_inr` is
    structurally ₹0 — no `tts_kchars` row is ever written for that leg — and whose unused
    allotment would therefore be the whole fee. A wrong number in the flattering direction,
    arrived at from a true attestation."""
    actor = await _operator()
    with pytest.raises(ProblemError) as raised:
        await _attest(actor, month=MONTH, plan_inr="4312.00", effective_from=NOW, provider="sarvam")
    assert raised.value.code == "tts_plan_fee_provider_not_plan_billed"
    assert "cartesia" in (raised.value.remediation or "")


async def test_an_unknown_vendor_is_refused_by_name() -> None:
    actor = await _operator()
    with pytest.raises(ProblemError) as raised:
        await _attest(
            actor, month=MONTH, plan_inr="4312.00", effective_from=NOW, provider="elevenlabs"
        )
    assert raised.value.code == "tts_price_unknown_provider"


async def test_the_database_refuses_an_update_and_a_delete() -> None:
    """Hard rule 4 at the database, not only in the writer. A fee somebody could edit would
    silently restate what a closed month cost us, on the one board that compares it against
    what our own meter attributed."""
    actor = await _operator()
    month = _unique_month()
    await _attest(actor, month=month, plan_inr="4312.00", effective_from=NOW)
    for statement in (
        "UPDATE platform_tts_plan_fees SET source_note = source_note || 'x' WHERE month = :m",
        "DELETE FROM platform_tts_plan_fees WHERE month = :m",
    ):
        async with untenanted_session() as session:
            with pytest.raises(Exception, match=r"append-only|immutable|forbid|not allowed"):
                await session.execute(text(statement), {"m": month})


# ---------------------------------------------------------------------- the ops route


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _admin_token() -> tuple[UUID, str]:
    admin_id = await _operator()
    return admin_id, f"dev:admin:{admin_id}"


def _headers(token: str, month: str, *, confirm: bool = True) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm:
        headers["X-Confirm-Action"] = tts_plan_fee_confirmation("cartesia", month)
    return headers


async def test_the_route_records_the_fee_and_writes_an_audit_row() -> None:
    _, token = await _admin_token()
    month = _unique_month()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/tts-prices/cartesia/plan-fee",
            headers=_headers(token, month),
            json={
                "month": month,
                "plan_inr": "4312.00",
                "source_note": "Cartesia Startup plan, invoice INV-2026-02-014",
            },
        )
    assert response.status_code == 200, response.text
    body = response.json()["plan_fee"]
    assert body["plan_inr"] == "4312.00"
    assert body["tier_label"] == "Studio"
    assert body["month"] == month
    # The pre-fill travels back so the console can render it greyed beside the form; it is
    # never the stored value (hard rule 7).
    assert body["reference_plan_inr"] == str(CARTESIA_STARTUP_PLAN_FEE_INR)

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT object_type, actor_type FROM audit_log "
                    "WHERE action = 'platform.tts_plan_fee_attested' AND object_id = :oid"
                ),
                # The vendor AND the month: an audit row naming only the vendor could not
                # tell two months' attestations apart, which is this table's whole subject.
                {"oid": f"cartesia:{month}"},
            )
        ).first()
    assert row is not None, "an attestation with no audit row is an unattributable figure"
    assert row[0] == "platform_tts_plan_fees"
    assert row[1] == "admin"


async def test_the_route_refuses_without_the_step_up_header() -> None:
    _, token = await _admin_token()
    month = _unique_month()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/tts-prices/cartesia/plan-fee",
            headers=_headers(token, month, confirm=False),
            json={"month": month, "plan_inr": "4312.00", "source_note": "an invoice"},
        )
    assert response.status_code in (401, 403, 428), response.text
    async with untenanted_session() as session:
        stored = (
            await session.execute(
                text("SELECT count(*) FROM platform_tts_plan_fees WHERE month = :m"), {"m": month}
            )
        ).scalar()
    assert stored == 0, "an unconfirmed attestation reached the ledger"


async def test_a_header_for_another_month_cannot_restate_this_one() -> None:
    _, token = await _admin_token()
    month = _unique_month()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/tts-prices/cartesia/plan-fee",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": tts_plan_fee_confirmation("cartesia", "2026-12"),
            },
            json={"month": month, "plan_inr": "4312.00", "source_note": "an invoice"},
        )
    assert response.status_code in (401, 403, 428), response.text


async def test_a_month_that_is_not_a_billing_month_is_refused_before_the_step_up() -> None:
    """`2026-9` is not the spelling every billing surface groups by, and a header confirming
    it must not be accepted for a month that spelling could never name. Refused by the one
    parser this product has, so the panel and the spend board cannot disagree."""
    _, token = await _admin_token()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/tts-prices/cartesia/plan-fee",
            headers=_headers(token, "2026-9"),
            json={"month": "2026-9", "plan_inr": "4312.00", "source_note": "an invoice"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/invalid_billing_month")


async def test_a_third_decimal_is_refused_rather_than_silently_rounded() -> None:
    """The column is `NUMERIC(12,2)` — an invoice is quoted to the paisa — so a figure it
    cannot hold exactly is a refusal that names the field, never a value Postgres rounds
    under an operator who typed it off a bill."""
    _, token = await _admin_token()
    month = _unique_month()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/tts-prices/cartesia/plan-fee",
            headers=_headers(token, month),
            json={"month": month, "plan_inr": "4312.005", "source_note": "an invoice"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/tts_plan_fee_invalid")
    assert "decimal places" in response.json()["detail"]


async def test_an_implausible_fee_is_refused_by_the_columns_own_width() -> None:
    _, token = await _admin_token()
    month = _unique_month()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/tts-prices/cartesia/plan-fee",
            headers=_headers(token, month),
            json={"month": month, "plan_inr": "99999999999.00", "source_note": "an invoice"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/tts_plan_fee_invalid")


async def test_the_route_refuses_a_vendor_with_no_monthly_plan() -> None:
    _, token = await _admin_token()
    month = _unique_month()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/tts-prices/sarvam/plan-fee",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Confirm-Action": tts_plan_fee_confirmation("sarvam", month),
            },
            json={"month": month, "plan_inr": "4312.00", "source_note": "an invoice"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/tts_plan_fee_provider_not_plan_billed")


# ------------------------------------------------------------------- the spend board


async def _tenant_with_cartesia_call(
    *, chars: int, rate: str, at: datetime, unpriced: bool = False
) -> UUID:
    """One live client with one Cartesia call metered exactly as the pipeline meters it —
    a `tts_kchars` row whose `qty` is the agent's character count in THOUSANDS.

    `at` stamps `occurred_at`, the column the month window is cut on, so a case can place
    its call in a month of its own and assert exact figures rather than relations against
    whatever else a shared development database holds.
    """
    created = await admin_service.create_organization(
        name="Voice Clinic",
        slug=f"voice-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
        plan_tier="prepaid",
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    assert isinstance(tenant_id, UUID) and isinstance(agent_id, UUID)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, started_at, duration_s, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                "'outbound', '+919876500001', 'completed', :at, 60, now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "at": at,
            },
        )
        await session.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, meta, created_at) VALUES (:i, :t, :c, "
                "'tts_kchars', :qty, :cost, :at, CAST(:m AS jsonb), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "c": call_id,
                "qty": Decimal(chars) / Decimal(1000),
                "cost": None if unpriced else Decimal(rate),
                "at": at,
                "m": json.dumps({"engine": "fake"}),
            },
        )
    return tenant_id


def _quiet_month() -> tuple[str, datetime]:
    """A billing month of this test's own, and an instant inside it.

    A month picked at random from a range no real row can be in, because the fleet board
    walks EVERY live client and this development database is shared with other lanes:
    asserting an exact rupee figure for the CURRENT month would be asserting something
    about somebody else's rows. A month nobody else is metering into is the only window in
    which the arithmetic can be pinned exactly, which is what these cases are for.

    `_unique_month` is the draw, for the reason its own docstring gives.
    """
    month = _unique_month()
    start, _ = ist_month_window(month)
    return month, start + timedelta(days=9)


async def _board(token: str, month: str) -> dict[str, object]:
    with pytest.MonkeyPatch.context() as patch:
        # The walk's cost is a property of how many live accounts this database happens to
        # hold, so the budget is lifted here rather than left to the clock — the trade
        # `spend_attribution_test` already makes on this board.
        patch.setattr(spend_routes, "FLEET_BUDGET_S", 3600.0)
        async with _client() as http:
            response = await http.get(
                f"/v1/admin/spend?month={month}", headers={"Authorization": f"Bearer {token}"}
            )
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


async def test_the_board_renders_no_plan_row_when_nobody_has_attested_this_month() -> None:
    """THE PROPERTY THIS SLICE WAS ASKED FOR, end to end. Characters were spoken and cost
    was attributed, and no invoice has been attested — so the card carries NO ROW and
    renders its stated absence. A ₹0 plan spend here would report a fleet margin that does
    not exist."""
    _, token = await _admin_token()
    month, moment = _quiet_month()
    await _tenant_with_cartesia_call(chars=29_000, rate="3.4496", at=moment)
    assert (await _board(token, month))["tts_plan"] == []


async def test_the_board_publishes_the_plan_the_attribution_and_the_difference() -> None:
    """The whole seam, end to end: an attested invoice, real `tts_kchars` rows read inside
    each client's own RLS scope, and a difference the SERVER computed.

    29,000 characters at ₹3.4496 per 1,000 is ₹100.0384, which is ₹100.04 at the paisa —
    and the unused allotment is the rest of the ₹4,312 fee."""
    actor, token = await _admin_token()
    month, moment = _quiet_month()
    await _tenant_with_cartesia_call(chars=29_000, rate="3.4496", at=moment)
    await _attest(actor, month=month, plan_inr="4312.00", effective_from=datetime.now(UTC))

    rows = (await _board(token, month))["tts_plan"]
    assert isinstance(rows, list) and len(rows) == 1
    row = rows[0]
    assert row["provider"] == "cartesia"
    assert row["tier_label"] == "Studio"
    assert row["month"] == month
    assert row["plan_inr"] == "4312.00"
    assert row["chars"] == "29000"
    assert row["attributed_inr"] == "100.04"
    assert row["unused_inr"] == "4211.96"


async def test_an_unpriced_metered_row_withholds_the_difference_on_the_live_board() -> None:
    """`unit_cost_paid` is NULLable and `SUM` skips a NULL, so a month holding one would
    report a larger unused allotment than it has. The board withholds the difference rather
    than publishing the flattering one — reachable end to end, not only in the renderer."""
    actor, token = await _admin_token()
    month, moment = _quiet_month()
    await _tenant_with_cartesia_call(chars=29_000, rate="3.4496", at=moment)
    await _tenant_with_cartesia_call(chars=5_000, rate="3.4496", at=moment, unpriced=True)
    await _attest(actor, month=month, plan_inr="4312.00", effective_from=datetime.now(UTC))

    rows = (await _board(token, month))["tts_plan"]
    assert isinstance(rows, list)
    assert rows[0]["unused_inr"] is None
    # The characters ARE all counted — `qty` is NOT NULL — so the count stays complete even
    # where the money does not.
    assert rows[0]["chars"] == "34000"
    assert rows[0]["attributed_inr"] == "100.04"


async def test_every_figure_on_the_plan_card_crosses_the_wire_as_a_string() -> None:
    """Hard rule 7 at the boundary: `Number()` on ₹10,159.00 is ₹10,158.999999999998, and a
    character count is the quantity a rate is multiplied by, so it travels the same way."""
    actor, token = await _admin_token()
    month, moment = _quiet_month()
    await _tenant_with_cartesia_call(chars=29_000, rate="3.4496", at=moment)
    await _attest(actor, month=month, plan_inr="4312.00", effective_from=datetime.now(UTC))
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(spend_routes, "FLEET_BUDGET_S", 3600.0)
        async with _client() as http:
            raw = (
                await http.get(
                    f"/v1/admin/spend?month={month}",
                    headers={"Authorization": f"Bearer {token}"},
                )
            ).text
    assert '"tts_plan"' in raw

    def _no_floats(_: str) -> float:
        raise AssertionError("a money field crossed the wire as a JSON number, not a string")

    json.loads(raw, parse_float=_no_floats)


async def test_the_speaking_rate_card_prices_both_vendors_even_unmeasured() -> None:
    """`by_provider` travels on BOTH shapes. Whether a price is attested is not a
    measurement, and the screen renders the vendor rows in the unmeasured branch too — a
    card that hid them below the sample threshold would hide the one row an operator opened
    it for (the tier nobody has priced)."""
    _, token = await _admin_token()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(spend_routes, "FLEET_BUDGET_S", 3600.0)
        async with _client() as http:
            response = await http.get(
                "/v1/admin/spend/tts-speaking-rate", headers={"Authorization": f"Bearer {token}"}
            )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [r["provider"] for r in body["by_provider"]] == list(TTS_PROVIDERS)
    for row in body["by_provider"]:
        assert row["tier_label"]
        if not row["price_attested"]:
            assert row["inr_per_1k_chars"] is None
        if row["inr_per_1k_chars"] is None or body["pooled"] is None:
            assert row["pooled_inr_per_minute"] is None
