"""The ENCODER price: input-only attestation, and what it switches on (D-608).

Ranked by what each failure costs, worst first:

1. **Nothing is billable until an operator attests.** Both encoder legs carry a catalogue
   figure whose evidence is `verified=False` — Google's page is egress-blocked from this
   deployment and OpenAI's was never read — so hard rule 7 must keep both out of
   `unit_cost_paid`. A regression here spends a vendor credential on every upload and
   records an invented cost against it, on an append-only ledger.
2. **The attestation is INPUT-ONLY at the type level.** An embedding request returns a
   vector and the vendor bills no output tokens. A form that accepted an output price is a
   form somebody eventually types a guess into.
3. **The two catalogues stay disjoint.** Attesting a CHAT model through the encoder route
   would write a row whose NULL output leg reads as "the vendor bills nothing" — and every
   minute on that model would then be under-costed for ever.
4. **The pack encoder is a catalogue key**, so the constant the wire sends, the constant
   the ledger records and the constant the price is attested against cannot drift apart.

`platform_model_prices` is a SHARED, GLOBAL, append-only table; `_clean` removes this
suite's rows as the table OWNER, the only role that can.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from apps.api.billing import rates
from apps.api.billing.rates import (
    LlmPriceAttestation,
    attested_llm_prices,
    install_llm_price_attestations,
    llm_inr_per_ktok,
    llm_price_is_billable,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import untenanted_session
from apps.api.kb import pack_vectors
from apps.api.main import app
from apps.api.ops.model_price_routes import (
    EmbeddingPriceAttestIn,
    embedding_attest_confirmation,
)
from apps.api.ops.model_pricing import (
    attest_embedding_price,
    attest_price,
    attested_model_prices,
    embedding_offerability,
    reference_embedding_price,
)
from apps.api.ops.pricing_snapshot import uninstall_pricing_readers
from apps.api.retrieval import embedding as dashboard_embedding
from calevate_shared.config import Settings
from calevate_shared.engine import (
    EMBEDDING_MODELS,
    LLM_MODELS,
    EmbeddingModelSpec,
    EmbeddingPrice,
    Evidence,
)
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.model_pricing_test import _purge_table

PACK_ENCODER = "models/gemini-embedding-2"
DASHBOARD_ENCODER = "text-embedding-3-small"
_WRITTEN_MODELS = (PACK_ENCODER, DASHBOARD_ENCODER)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _auth(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


async def _make_admin() -> tuple[str, uuid.UUID]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Encoders', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}", admin_id


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: platform_model_prices is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            await _purge_table(conn, "platform_model_prices", "model", list(_WRITTEN_MODELS))
    finally:
        await engine.dispose()
    uninstall_pricing_readers()
    install_llm_price_attestations(None)


# --- the catalogue is the one source of the encoder's name ------------------------


def test_both_encoders_this_tree_buys_vectors_from_are_catalogue_keys() -> None:
    """The constant the WIRE sends is the constant the PRICE is attested against.

    Three modules name an encoder (`kb/pack_vectors`, `retrieval/embedding`, and the voice
    worker, which restates the first deliberately and is pinned by its own test). If any of
    them named a model the catalogue does not carry, `attest_embedding_price` would refuse
    the identifier an operator is looking at, and the leg would be unpriceable while looking
    configured.
    """
    assert pack_vectors.EMBEDDING_MODEL in EMBEDDING_MODELS
    assert dashboard_embedding.EMBEDDING_MODEL in EMBEDDING_MODELS
    assert set(EMBEDDING_MODELS) == {
        pack_vectors.EMBEDDING_MODEL,
        dashboard_embedding.EMBEDDING_MODEL,
    }

    for module in (pack_vectors, dashboard_embedding):
        spec = EMBEDDING_MODELS[module.EMBEDDING_MODEL]
        assert spec.dimensions == module.EMBEDDING_DIMS, (
            f"{module.__name__} sends a width the catalogue does not declare; a vector "
            "written at one width and searched at another is a silently wrong ranking"
        )


def test_no_encoder_is_in_the_conversational_catalogue() -> None:
    """The two catalogues are DISJOINT, which is what keeps the two attestation routes from
    accepting each other's models — and what keeps an encoder off the in-call model picker."""
    assert not set(EMBEDDING_MODELS) & set(LLM_MODELS)


# --- hard rule 7: nothing is billable until somebody attests ----------------------


def test_no_encoder_is_billable_from_the_catalogue_alone() -> None:
    """THE DEFAULT STATE OF EVERY DEPLOYMENT, and the one this whole seam is built around.

    Both catalogue figures are `verified=False`: the Gemini one is VENDOR-PUBLISHED and
    founder-relayed (`ai.google.dev` is egress-blocked from this container) and the OpenAI
    one was never read at all. So neither may reach `unit_cost_paid`, both legs are no-ops,
    and every pack is built lexical-only.
    """
    install_llm_price_attestations(None)
    for model in EMBEDDING_MODELS:
        _, verified = reference_embedding_price(model)
        assert verified is False, f"{model} claims a verified catalogue price it does not have"
        assert llm_price_is_billable(model) is False
        with pytest.raises(ValueError) as raised:
            llm_inr_per_ktok(model)
        # The refusal has to be actionable: it names the ops console and what is switched
        # off, because an operator who reads only "no billable price" does not know that
        # their clients' uploads are being indexed by word-matching alone.
        assert "ops console" in str(raised.value)
        assert EMBEDDING_MODELS[model].used_for in str(raised.value)

    assert pack_vectors.pack_embedding_is_billable() is False


def test_an_attested_encoder_prices_input_and_charges_nothing_for_output() -> None:
    """The one door, opened. `out` is an exact ZERO rather than an absent key.

    `record_ai_assist_usage` writes an `ai_assist_ktok_out` row for every assist whatever
    the model — at `qty = 0` for an embedding — so a mapping that dropped the key would be a
    `KeyError` on a metering path rather than a ₹0.0000 line an operator can see.
    """
    attestation = LlmPriceAttestation(
        model=PACK_ENCODER,
        input_usd_per_mtok=Decimal("0.20"),
        output_usd_per_mtok=None,
        read_on=datetime.now(UTC).date(),
        attested_by="founder",
        source="Google Cloud billing export 2026-09",
    )
    install_llm_price_attestations(lambda: {PACK_ENCODER: attestation})
    assert llm_price_is_billable(PACK_ENCODER) is True
    priced = llm_inr_per_ktok(PACK_ENCODER)
    assert priced["in"] > 0
    assert priced["out"] == Decimal("0.0000")
    assert pack_vectors.pack_embedding_is_billable() is True


def test_a_verified_catalogue_figure_would_bill_without_an_attestation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GROUND 2, EXERCISED — the arm no shipped entry reaches today.

    `llm_price_is_billable` has exactly two grounds and the encoder catalogue is held to
    both, not to a looser one. Neither entry is `verified=True` today (Google's page is
    egress-blocked here, OpenAI's was never read), so this substitutes a catalogue whose
    evidence IS a first-hand vendor reading and checks that the arm behaves like its
    conversational twin: billable with nothing attested, priced on input, zero on output.

    It is asserted rather than left unreachable because the day somebody CAN read a vendor
    page from a deployment, this is the path an upload's money takes, and a branch nobody
    has ever run is not a branch anybody should discover through an invoice.
    """
    verified = EmbeddingModelSpec(
        model=PACK_ENCODER,
        provider="google",
        price=EmbeddingPrice(
            input_usd_per_mtok=Decimal("0.20"),
            evidence=Evidence(
                source="a vendor page somebody actually read",
                read_on=datetime.now(UTC).date(),
                verified=True,
            ),
        ),
        dimensions=3072,
        used_for="the knowledge pack's dense arm",
    )
    monkeypatch.setattr(rates, "EMBEDDING_MODELS", {PACK_ENCODER: verified})
    install_llm_price_attestations(None)
    assert llm_price_is_billable(PACK_ENCODER) is True
    priced = llm_inr_per_ktok(PACK_ENCODER)
    assert priced["in"] > 0
    assert priced["out"] == Decimal("0.0000")


def test_an_encoder_price_of_zero_is_refused_at_the_service() -> None:
    """The DB CHECK is the backstop; this is the message an operator can act on. A zero
    embeds every upload at nothing while looking like a working leg."""
    now = datetime.now(UTC)

    async def _attempt() -> ProblemError:
        async with untenanted_session() as session:
            with pytest.raises(ProblemError) as raised:
                await attest_embedding_price(
                    session,
                    model=PACK_ENCODER,
                    input_usd_per_mtok=Decimal("0"),
                    effective_from=now,
                    source_note="a typo",
                    actor_id=uuid.uuid4(),
                )
        return raised.value

    error = asyncio.run(_attempt())
    assert error.code == "embedding_price_not_positive"


def test_a_zero_output_price_is_still_refused() -> None:
    """ABSENT and ZERO stay different facts. `None` is what the vendor bills; a typed zero
    is the metering failure nobody investigates, and the guard that catches it is unchanged."""
    with pytest.raises(ValueError):
        LlmPriceAttestation(
            model=PACK_ENCODER,
            input_usd_per_mtok=Decimal("0.20"),
            output_usd_per_mtok=Decimal("0"),
            read_on=datetime.now(UTC).date(),
            attested_by="founder",
            source="a typo",
        )


# --- the store -------------------------------------------------------------------


async def test_the_store_holds_an_input_only_row_and_the_reader_returns_none_output() -> None:
    """NULL survives the round trip. A reader that coerced it to a zero would trip the
    billing seam's own guard and blank every other model's price (`_to_attestation`)."""
    _, admin_id = await _make_admin()
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        written = await attest_embedding_price(
            session,
            model=PACK_ENCODER,
            input_usd_per_mtok=Decimal("0.20"),
            effective_from=now,
            source_note="Google Cloud billing export 2026-09, line 4",
            actor_id=admin_id,
        )
        assert written.output_usd_per_mtok is None
        back = await attested_model_prices(session, at=now)
    assert back[PACK_ENCODER].input_usd_per_mtok == Decimal("0.200000")
    assert back[PACK_ENCODER].output_usd_per_mtok is None


async def test_the_encoder_route_refuses_a_chat_model_and_the_chat_route_refuses_an_encoder() -> (
    None
):
    """THE DISJOINTNESS, ENFORCED AT BOTH WRITERS rather than assumed from the catalogues.

    An encoder attested through the chat route would be given an output price nobody
    published; a chat model attested through the encoder route would have its output leg
    stored NULL and every minute on it under-costed for ever. Both are refused by name.
    """
    _, admin_id = await _make_admin()
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as encoder_route:
            await attest_embedding_price(
                session,
                model="gpt-4o-mini",
                input_usd_per_mtok=Decimal("0.15"),
                effective_from=now,
                source_note="wrong route",
                actor_id=admin_id,
            )
        assert encoder_route.value.code == "embedding_price_unknown_model"

        with pytest.raises(ProblemError) as chat_route:
            await attest_price(
                session,
                model=PACK_ENCODER,
                input_usd_per_mtok=Decimal("0.20"),
                output_usd_per_mtok=Decimal("0.20"),
                effective_from=now,
                source_note="wrong route",
                actor_id=admin_id,
            )
        assert chat_route.value.code == "model_price_unknown_model"


async def test_a_second_attestation_at_the_same_instant_is_refused() -> None:
    """A correction is a NEW effective instant, never an edit — the append-only rule stated
    as a sentence rather than surfaced as an IntegrityError rendered as a 500."""
    _, admin_id = await _make_admin()
    now = datetime.now(UTC)
    async with untenanted_session() as session:
        await attest_embedding_price(
            session,
            model=PACK_ENCODER,
            input_usd_per_mtok=Decimal("0.20"),
            effective_from=now,
            source_note="first reading",
            actor_id=admin_id,
        )
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await attest_embedding_price(
                session,
                model=PACK_ENCODER,
                input_usd_per_mtok=Decimal("0.25"),
                effective_from=now,
                source_note="second reading",
                actor_id=admin_id,
            )
    assert raised.value.code == "embedding_price_duplicate_instant"


# --- the surface -----------------------------------------------------------------


async def test_the_panel_lists_every_encoder_with_its_ground_before_anybody_attests() -> None:
    """The row that needs an operator must be VISIBLE, with the sentence saying what is
    switched off — a panel that hid the unpriced encoders would hide the only work there is.
    """
    token, _ = await _make_admin()
    async with _client() as client:
        response = await client.get("/v1/ops/model-prices", headers=_auth(token))
    assert response.status_code == 200
    rows = {row["model"]: row for row in response.json()["embedding_prices"]}
    assert set(rows) == set(EMBEDDING_MODELS)
    for model, row in rows.items():
        assert row["price_attested"] is False
        assert row["input_usd_per_mtok"] is None
        assert row["usable"] is False
        assert row["reference_verified"] is False
        assert row["used_for"] == EMBEDDING_MODELS[model].used_for
        assert row["dimensions"] == EMBEDDING_MODELS[model].dimensions
        assert "output" not in "".join(row), "an output leg leaked onto an encoder row"


async def test_the_form_has_no_output_field_at_all() -> None:
    """INPUT-ONLY AS A TYPE, NOT A CONVENTION. `extra="forbid"` refuses the field outright,
    so the shape of the request is what stops a guess rather than a reviewer's attention."""
    token, _ = await _make_admin()
    async with _client() as client:
        response = await client.post(
            f"/v1/ops/embedding-prices/{PACK_ENCODER}",
            headers=_auth(token, embedding_attest_confirmation(PACK_ENCODER)),
            json={
                "input_usd_per_mtok": "0.20",
                "output_usd_per_mtok": "0.40",
                "source_note": "Google Cloud billing export 2026-09",
            },
        )
    assert response.status_code == 422


async def test_attesting_through_the_route_makes_the_leg_usable_and_writes_an_audit_row() -> None:
    """The whole seam end to end, with the identifier carrying its SLASH VERBATIM — no
    percent-encoding anywhere, which is the reason this route has its own prefix."""
    token, _ = await _make_admin()
    # `audit_log` is append-only and shared, so this test can only speak for rows written
    # after it started — the same scoping every other audit assertion in this tree uses.
    started = datetime.now(UTC)
    async with _client() as client:
        response = await client.post(
            f"/v1/ops/embedding-prices/{PACK_ENCODER}",
            headers=_auth(token, embedding_attest_confirmation(PACK_ENCODER)),
            json={
                "input_usd_per_mtok": "0.20",
                "source_note": "Google Cloud billing export 2026-09, gemini-embedding-2 input",
            },
        )
    assert response.status_code == 200, response.text
    price = response.json()["price"]
    assert price["model"] == PACK_ENCODER
    assert price["input_usd_per_mtok"] == "0.200000"
    assert price["price_attested"] is True

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT object_type FROM audit_log WHERE action = "
                    "'platform.embedding_price_attested' AND object_id = :m AND at >= :t"
                ),
                {"m": PACK_ENCODER, "t": started},
            )
        ).all()
        offers = await embedding_offerability(session, at=datetime.now(UTC))
    assert [r[0] for r in rows] == ["platform_model_prices"], (
        "the encoder attestation is not one audited act against the price store"
    )
    assert offers[PACK_ENCODER].price_attested is True
    # No output leg anywhere on the write path: the request model has no field for one, so
    # neither the audit summary nor the store can carry a figure nobody published.
    assert "output_usd_per_mtok" not in EmbeddingPriceAttestIn.model_fields


async def test_the_write_refuses_without_the_step_up_header_bound_to_this_model() -> None:
    """A header captured while pricing one encoder cannot be replayed against the other —
    and the chat route's header cannot be replayed here at all."""
    token, _ = await _make_admin()
    body = {"input_usd_per_mtok": "0.20", "source_note": "an invoice"}
    async with _client() as client:
        bare = await client.post(
            f"/v1/ops/embedding-prices/{PACK_ENCODER}", headers=_auth(token), json=body
        )
        wrong_model = await client.post(
            f"/v1/ops/embedding-prices/{PACK_ENCODER}",
            headers=_auth(token, embedding_attest_confirmation(DASHBOARD_ENCODER)),
            json=body,
        )
        chat_header = await client.post(
            f"/v1/ops/embedding-prices/{PACK_ENCODER}",
            headers=_auth(token, f"attest_model_price:{PACK_ENCODER}"),
            json=body,
        )
    assert bare.status_code >= 400
    assert wrong_model.status_code >= 400
    assert chat_header.status_code >= 400

    async with untenanted_session() as session:
        assert PACK_ENCODER not in await attested_model_prices(session, at=datetime.now(UTC))
    assert PACK_ENCODER not in attested_llm_prices()
