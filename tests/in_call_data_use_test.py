"""D-839: the in-call data-use attestation is its own statement, and our own model's readiness
reads it rather than the dashboard one."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
from apps.api.agents.own_model import OWN_MODEL_PROVIDER, own_model_readiness
from apps.api.db.session import untenanted_session
from apps.api.ops.in_call_data_use_routes import IN_CALL_STATEMENT, attest_confirmation
from apps.api.ops.model_pricing import attest_data_use, in_call_permitted_providers
from calevate_shared.config import Settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.dashboard_data_use_test import _auth, _client, _make_admin
from tests.model_pricing_test import _purge_table

PATH = "/v1/ops/in-call-data-use"
PAYLOAD = {
    "vendor_account_ref": "calevate-prod-000",
    "paid_tier_confirmed": True,
    "no_training_opt_in_confirmed": True,
    "source_note": "AI Studio Projects page, Billing Tier column, 20 Oct 2026",
}


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: the tables are append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            for table in ("platform_in_call_data_use", "platform_dashboard_data_use"):
                await _purge_table(conn, table, "provider", [OWN_MODEL_PROVIDER])
    finally:
        await engine.dispose()


async def _attest(leg: str, *, paid: bool = True) -> None:
    _, admin_id = await _make_admin()
    async with untenanted_session() as session:
        await attest_data_use(
            session,
            provider=OWN_MODEL_PROVIDER,
            vendor_account_ref="calevate-prod-000",
            paid_tier_confirmed=paid,
            no_training_opt_in_confirmed=True,
            attested_at=datetime.now(UTC),
            source_note="AI Studio Projects page, 20 Oct 2026",
            actor_id=admin_id,
            leg=leg,  # type: ignore[arg-type]
        )


async def test_readiness_reads_the_in_call_attestation_and_not_the_dashboard_one() -> None:
    """FAILS IF: an attestation about Pip's screen text makes our own model ready for
    callers' speech, or the in-call attestation does not."""
    await _attest("dashboard")
    async with untenanted_session() as session:
        before = await own_model_readiness(session, engine="thinnest")
    assert before.data_use_attested is False
    assert any("caller speech" in step for step in before.missing())

    await _attest("in_call")
    async with untenanted_session() as session:
        after = await own_model_readiness(session, engine="thinnest")
        permitted = await in_call_permitted_providers(session)
    assert after.data_use_attested is True
    assert OWN_MODEL_PROVIDER in permitted


async def test_a_recorded_no_keeps_our_model_off() -> None:
    await _attest("in_call", paid=False)
    async with untenanted_session() as session:
        assert OWN_MODEL_PROVIDER not in await in_call_permitted_providers(session)


async def test_the_route_needs_its_own_step_up_and_audits() -> None:
    """FAILS IF: the dashboard step-up string attests the in-call leg, or the write is not
    audited."""
    token, _ = await _make_admin()
    async with _client() as http:
        listed = await http.get(PATH, headers=_auth(token))
        dashboard_word = await http.post(
            f"{PATH}/{OWN_MODEL_PROVIDER}",
            headers=_auth(token, f"attest_dashboard_data_use:{OWN_MODEL_PROVIDER}"),
            json=PAYLOAD,
        )
        ok = await http.post(
            f"{PATH}/{OWN_MODEL_PROVIDER}",
            headers=_auth(token, attest_confirmation(OWN_MODEL_PROVIDER)),
            json=PAYLOAD,
        )
    assert listed.status_code == 200, listed.text
    assert listed.json()["statement"] == IN_CALL_STATEMENT
    assert [row["provider"] for row in listed.json()["providers"]] == [OWN_MODEL_PROVIDER]
    assert listed.json()["providers"][0]["permits"] is False
    assert dashboard_word.status_code == 403
    assert ok.status_code == 200, ok.text
    assert ok.json()["provider"]["permits"] is True
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = "
                    "'platform.in_call_data_use_attested' AND object_id = :p"
                ),
                {"p": OWN_MODEL_PROVIDER},
            )
        ).scalar_one()
    assert audited >= 1


async def test_a_provider_no_call_answers_on_is_refused() -> None:
    token, _ = await _make_admin()
    async with _client() as http:
        refused = await http.post(
            f"{PATH}/openai", headers=_auth(token, attest_confirmation("openai")), json=PAYLOAD
        )
    assert refused.status_code == 404, refused.text
    assert refused.json()["type"].endswith("/in_call_data_use_unknown_provider")


async def test_an_operator_without_platform_config_cannot_reach_it() -> None:
    token, _ = await _make_admin("operator")
    async with _client() as http:
        refused = await http.get(PATH, headers=_auth(token))
    assert refused.status_code == 403
