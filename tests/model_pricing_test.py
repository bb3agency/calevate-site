"""Operator-attested model prices: storage, effective dating, the seam, the surface (§5).

Ranked by what each failure costs, worst first:

1. **The append-only boundary is real.** A price reaches `unit_cost_paid`; if a row could
   be edited, "what did this model cost in the month we billed it" would be rewritable,
   which is the property the whole ledger family exists for.
2. **The billing seam reads what the operator attested.** The catalogue lane's rate card
   bills an OpenAI/Google leg only off an attested price (hard rule 7 has no REPORTED
   tier); if the installed reader did not surface an attestation, that leg could never be
   billed and never be offered.
3. **Effective dating resolves the price live at an instant**, so a re-rendered invoice is
   re-derivable rather than re-priced by whatever changed since.
4. **The write is stepped-up, audited, and refuses what it cannot store** — an unknown
   model, a non-positive price, a duplicate instant.

`platform_model_prices` is a SHARED, GLOBAL, append-only table. Every test uses catalogue
models that are NOT selectable (`gpt-5.6-luna`, `gemini-2.5-flash-lite`) so it never
collides with Azure billing, and the `_clean` fixture removes its rows as the table owner —
the only role that can, because the table is append-only ON PURPOSE.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import get_args

import pytest
from apps.api.billing.rates import attested_llm_prices, llm_price_is_billable
from apps.api.core.errors import ProblemError
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.model_price_routes import attest_confirmation
from apps.api.ops.model_pricing import (
    PROVIDER_CREDENTIAL,
    attest_price,
    attested_model_prices,
    installed_llm_legs,
    model_offerability,
    offerable_models,
)
from apps.api.ops.pricing_snapshot import (
    install_pricing_readers,
    refresh_pricing_snapshot,
    uninstall_pricing_readers,
)
from apps.api.ops.secret_service import set_secret
from calevate_shared.config import Settings
from calevate_shared.engine import LLM_MODELS, LlmProvider
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

# Catalogue models that are NOT selectable, so attesting them touches no live billing.
GOOGLE_MODEL = "gemini-2.5-flash-lite"
OPENAI_MODEL = "gpt-5.6-luna"
# Every model any test here writes a row for; removed as owner in `_clean`.
_WRITTEN_MODELS = (GOOGLE_MODEL, OPENAI_MODEL)
# Every credential any test installs; removed in `_clean` for the same shared-table reason.
_WRITTEN_SECRETS = ("gemini_api_key", "openai_api_key")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _auth(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


async def _make_admin(role: str = "superadmin") -> tuple[str, uuid.UUID]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Prices', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}", admin_id


async def _purge_table(conn: object, table: str, column: str, values: list[str]) -> None:
    """DELETE from ONE append-only table as the owner, disabling and then restoring its
    triggers verbatim. `ENABLE TRIGGER` is not the inverse of `DISABLE` — plain ENABLE
    demotes an `ENABLE ALWAYS` trigger to ORIGIN — so each trigger's prior mode is read
    first and put back exactly (the trap platform_secrets_test documents)."""
    modes = (
        await conn.execute(  # type: ignore[attr-defined]
            text(
                "SELECT t.tgname, t.tgenabled FROM pg_trigger t "
                f"WHERE t.tgrelid = '{table}'::regclass AND NOT t.tgisinternal"
            )
        )
    ).all()
    await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))  # type: ignore[attr-defined]
    await conn.execute(  # type: ignore[attr-defined]
        text(f"DELETE FROM {table} WHERE {column} = ANY(:v)"), {"v": values}
    )
    for name, mode in modes:
        verb = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA", "D": "DISABLE"}.get(
            str(mode), "ENABLE"
        )
        await conn.execute(text(f'ALTER TABLE {table} {verb} TRIGGER "{name}"'))  # type: ignore[attr-defined]


async def _purge() -> None:
    """Remove this suite's rows from both append-only tables it writes, as the OWNER — the
    only role that can, because both are append-only ON PURPOSE."""
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: platform_model_prices is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            await _purge_table(conn, "platform_model_prices", "model", list(_WRITTEN_MODELS))
            await _purge_table(conn, "platform_secrets", "key", list(_WRITTEN_SECRETS))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    await _purge()
    # The seam is process-wide state; a test that installed a reader must not leak it.
    uninstall_pricing_readers()


# --- storage: append-only + effective dating ------------------------------------


async def test_the_provider_credential_map_is_exhaustive_and_names_real_secrets() -> None:
    """Every declared leg maps to a real manageable credential — the offerability gate's
    other half. A leg with no entry would `KeyError` rather than read as un-credentialed."""
    assert set(PROVIDER_CREDENTIAL) == set(get_args(LlmProvider))
    for cred in PROVIDER_CREDENTIAL.values():
        assert cred in Settings.model_fields, cred


async def test_a_price_row_cannot_be_edited_or_deleted() -> None:
    """The append-only boundary, at the database — the two mutations that would make a
    billed price rewritable."""
    _, admin = await _make_admin()
    async with untenanted_session() as session:
        await attest_price(
            session,
            model=OPENAI_MODEL,
            input_usd_per_mtok=Decimal("0.20"),
            output_usd_per_mtok=Decimal("1.20"),
            effective_from=datetime.now(UTC),
            source_note="test invoice",
            actor_id=admin,
        )
    for statement in (
        "UPDATE platform_model_prices SET input_usd_per_mtok = 9 WHERE model = :m",
        "UPDATE platform_model_prices SET source_note = 'x' WHERE model = :m",
        "DELETE FROM platform_model_prices WHERE model = :m",
    ):
        with pytest.raises(Exception) as raised:
            async with untenanted_session() as session:
                await session.execute(text(statement), {"m": OPENAI_MODEL})
        assert "append-only" in str(raised.value), statement


async def test_effective_dating_resolves_the_price_live_at_the_instant() -> None:
    """A re-render of a past month must resolve the price that was live THEN, not today's."""
    _, admin = await _make_admin()
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)
    async with untenanted_session() as session:
        await attest_price(
            session,
            model=OPENAI_MODEL,
            input_usd_per_mtok=Decimal("0.20"),
            output_usd_per_mtok=Decimal("1.20"),
            effective_from=old,
            source_note="jan invoice",
            actor_id=admin,
        )
        await attest_price(
            session,
            model=OPENAI_MODEL,
            input_usd_per_mtok=Decimal("0.50"),
            output_usd_per_mtok=Decimal("3.00"),
            effective_from=new,
            source_note="jun invoice",
            actor_id=admin,
        )
    async with untenanted_session() as session:
        before = await attested_model_prices(session, at=old - timedelta(days=1))
        between = await attested_model_prices(session, at=datetime(2026, 3, 1, tzinfo=UTC))
        after = await attested_model_prices(session, at=new + timedelta(days=1))
    assert OPENAI_MODEL not in before  # nothing attested yet at that instant
    assert between[OPENAI_MODEL].input_usd_per_mtok == Decimal("0.20")
    assert after[OPENAI_MODEL].input_usd_per_mtok == Decimal("0.50")


async def test_attest_refuses_unknown_model_nonpositive_and_duplicate_instant() -> None:
    _, admin = await _make_admin()
    now = datetime.now(UTC)
    with pytest.raises(ProblemError) as unknown:
        async with untenanted_session() as session:
            await attest_price(
                session,
                model="not-a-model",
                input_usd_per_mtok=Decimal("1"),
                output_usd_per_mtok=Decimal("1"),
                effective_from=now,
                source_note="x",
                actor_id=admin,
            )
    assert unknown.value.code == "model_price_unknown_model"

    with pytest.raises(ProblemError) as zero:
        async with untenanted_session() as session:
            await attest_price(
                session,
                model=OPENAI_MODEL,
                input_usd_per_mtok=Decimal("0"),
                output_usd_per_mtok=Decimal("1"),
                effective_from=now,
                source_note="x",
                actor_id=admin,
            )
    assert zero.value.code == "model_price_not_positive"

    async with untenanted_session() as session:
        await attest_price(
            session,
            model=OPENAI_MODEL,
            input_usd_per_mtok=Decimal("0.20"),
            output_usd_per_mtok=Decimal("1.20"),
            effective_from=now,
            source_note="first",
            actor_id=admin,
        )
    with pytest.raises(ProblemError) as dup:
        async with untenanted_session() as session:
            await attest_price(
                session,
                model=OPENAI_MODEL,
                input_usd_per_mtok=Decimal("0.30"),
                output_usd_per_mtok=Decimal("1.30"),
                effective_from=now,
                source_note="second at same instant",
                actor_id=admin,
            )
    assert dup.value.code == "model_price_duplicate_instant"


# --- offerability: credential installed AND price attested ----------------------


async def test_a_model_is_offerable_only_with_both_a_credential_and_a_price() -> None:
    _, admin = await _make_admin()
    now = datetime.now(UTC)
    # The invariant, over every model: offerable iff credential installed AND the price is
    # BILLABLE, where billable means an operator attested it OR the catalogue figure is a
    # first-hand vendor reading (`reference_verified`). This is the catalogue lane's own
    # `llm_price_is_billable` rule — it is why Azure is offerable with no attestation and the
    # OpenAI/Google legs are not.
    async with untenanted_session() as session:
        offers = await model_offerability(session, at=now)
    for offer in offers.values():
        assert offer.offerable == (
            offer.credential_installed and (offer.price_attested or offer.reference_verified)
        )
    # GOOGLE_MODEL is the google leg (REPORTED price, not verified) with no attestation
    # (the store is purged between tests), so it is not offerable whatever its credential.
    assert offers[GOOGLE_MODEL].reference_verified is False
    assert not offers[GOOGLE_MODEL].price_attested
    assert not offers[GOOGLE_MODEL].offerable

    # Attest a price AND install the credential → billable AND credentialed → offerable.
    async with untenanted_session() as session:
        await attest_price(
            session,
            model=GOOGLE_MODEL,
            input_usd_per_mtok=Decimal("0.10"),
            output_usd_per_mtok=Decimal("0.40"),
            effective_from=now,
            source_note="ai studio console",
            actor_id=admin,
        )
        await set_secret(
            session, key=PROVIDER_CREDENTIAL["google"], value="test-gemini-key", actor_id=admin
        )
    async with untenanted_session() as session:
        assert "google" in await installed_llm_legs(session)
        offers = await model_offerability(session, at=now)
        offerable = await offerable_models(session, at=now)
    assert offers[GOOGLE_MODEL].credential_installed
    assert offers[GOOGLE_MODEL].price_attested
    assert offers[GOOGLE_MODEL].offerable
    assert GOOGLE_MODEL in offerable


# --- the billing seam: the installed reader surfaces the attestation ------------


async def test_the_billing_seam_reads_an_attested_price_after_a_refresh() -> None:
    """With the ops readers installed, an attested OpenAI-leg price makes that model
    billable — the whole point of the seam (hard rule 7 has no REPORTED tier)."""
    _, admin = await _make_admin()
    # Default: nothing installed → the unpriced OpenAI-leg model is not billable.
    uninstall_pricing_readers()
    assert not llm_price_is_billable(OPENAI_MODEL)

    async with untenanted_session() as session:
        await attest_price(
            session,
            model=OPENAI_MODEL,
            input_usd_per_mtok=Decimal("0.20"),
            output_usd_per_mtok=Decimal("1.20"),
            effective_from=datetime.now(UTC),
            source_note="openai invoice",
            actor_id=admin,
        )
    install_pricing_readers()
    await refresh_pricing_snapshot()
    assert OPENAI_MODEL in attested_llm_prices()
    assert llm_price_is_billable(OPENAI_MODEL)


# --- the surface: step-up, audit, refusals, money as strings --------------------


async def test_get_lists_every_catalogue_model_with_reference_and_offerability() -> None:
    token, _ = await _make_admin()
    async with _client() as http:
        response = await http.get("/v1/ops/model-prices", headers=_auth(token))
    assert response.status_code == 200
    body = response.json()
    rows = {r["model"]: r for r in body["prices"]}
    assert set(rows) == set(LLM_MODELS)
    # Money is a STRING end to end (hard rule 7).
    azure = rows["gpt-4o-mini"]
    assert isinstance(azure["reference_input_usd_per_mtok"], str)
    assert azure["reference_verified"] is True  # D-410 read Azure first-hand
    assert rows[OPENAI_MODEL]["reference_verified"] is False  # REPORTED
    assert azure["input_usd_per_mtok"] is None  # nothing attested


async def test_a_normal_admin_cannot_reach_the_panel() -> None:
    token, _ = await _make_admin("operator")
    async with _client() as http:
        assert (await http.get("/v1/ops/model-prices", headers=_auth(token))).status_code == 403


async def _audit_count(model: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE "
                        "action = 'platform.model_price_attested' AND object_id = :m"
                    ),
                    {"m": model},
                )
            ).scalar()
            or 0
        )


async def test_attest_via_the_route_needs_step_up_and_lands_an_audit_row() -> None:
    token, _ = await _make_admin()
    path = f"/v1/ops/model-prices/{OPENAI_MODEL}"
    payload = {
        "input_usd_per_mtok": "0.20",
        "output_usd_per_mtok": "1.20",
        "source_note": "openai.com/api/pricing 23 Aug 2026",
    }
    # audit_log is global and append-only (never purged), so assert the DELTA, not a total.
    before = await _audit_count(OPENAI_MODEL)
    async with _client() as http:
        # No step-up header → refused.
        no_confirm = await http.post(path, headers=_auth(token), json=payload)
        assert no_confirm.status_code == 403

        ok = await http.post(
            path,
            headers=_auth(token, attest_confirmation(OPENAI_MODEL)),
            json=payload,
        )
    assert ok.status_code == 200, ok.text
    price = ok.json()["price"]
    # A STRING on the wire (hard rule 7), and exact — the NUMERIC(12,6) round-trip pads it
    # to "0.200000", which is the same number. Compared as Decimal, never as a float.
    assert isinstance(price["input_usd_per_mtok"], str)
    assert Decimal(price["input_usd_per_mtok"]) == Decimal("0.20")
    assert price["price_attested"] is True

    assert await _audit_count(OPENAI_MODEL) == before + 1


async def test_the_route_refuses_a_nonpositive_and_an_unknown_model() -> None:
    token, _ = await _make_admin()
    # A valid `source_note` (>= 3 chars) so the request passes pydantic and reaches the
    # money check — the boundary refusal this test is actually about.
    async with _client() as http:
        zero = await http.post(
            f"/v1/ops/model-prices/{OPENAI_MODEL}",
            headers=_auth(token, attest_confirmation(OPENAI_MODEL)),
            json={
                "input_usd_per_mtok": "0",
                "output_usd_per_mtok": "1",
                "source_note": "vendor page",
            },
        )
        assert zero.status_code == 422
        assert zero.json()["type"].endswith("model_price_invalid")

        unknown_model = "gpt-4o-mini-nope"
        unknown = await http.post(
            f"/v1/ops/model-prices/{unknown_model}",
            headers=_auth(token, attest_confirmation(unknown_model)),
            json={
                "input_usd_per_mtok": "1",
                "output_usd_per_mtok": "1",
                "source_note": "vendor page",
            },
        )
    assert unknown.status_code == 404
    assert unknown.json()["type"].endswith("model_price_unknown_model")
