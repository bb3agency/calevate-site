"""The dashboard data-use attestation: storage, the seam, the surface (D-477, §5).

Ranked by what each failure costs, worst first:

1. **It never defaults to permitted, and an absent row is not a "no".** The whole point of
   the gate is that a client's screen content does not reach a vendor whose terms for OUR
   account nobody has checked. A default of true would make the mechanism ceremonial; an
   absent attestation rendered as a refusal would put a claim in somebody's mouth.
2. **The row is append-only and carries the account it is about.** "What did we believe, on
   whose word, and when, at the time a client's content reached this vendor" is the audit
   question, and a mutable row answers it with today's belief. The project id is what makes
   the claim re-checkable later rather than only re-makeable.
3. **Attesting clears the compliance ground and does NOT invent a leg.** Both halves are
   asserted, because reporting only one of them is a defect in each direction — see
   `agents/llm_models.dashboard_leg_reason`.
4. **The write is stepped-up, audited, and refuses what it cannot store.**

⚠ **NOTHING HERE ASSERTS WHAT GOOGLE'S TERMS SAY.** Every Google-owned host is
egress-blocked from this environment; what is tested is the MECHANISM. Whether the terms
permit anything is the operator's reading and OPERATIONS §2 gate 41's question.

`platform_dashboard_data_use` is a SHARED, GLOBAL, append-only table, so `_clean` removes
this suite's rows as the table OWNER — the only role that can, because the table is
append-only ON PURPOSE. `tests/model_pricing_test.py`'s `_purge_table` is reused verbatim
rather than re-derived: `ENABLE TRIGGER` is not the inverse of `DISABLE` (it demotes an
`ENABLE ALWAYS` trigger to ORIGIN), and one copy of that trap is enough.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.agents.llm_models import (
    NO_DATA_USE_ATTESTATION_REASON,
    dashboard_leg_reason,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.dashboard_data_use_routes import ATTESTATION_STATEMENT, attest_confirmation
from apps.api.ops.model_pricing import (
    attest_dashboard_data_use,
    dashboard_data_use_attestations,
    dashboard_permitted_providers,
)
from apps.api.ops.pricing_snapshot import (
    install_pricing_readers,
    refresh_pricing_snapshot,
    uninstall_pricing_readers,
)
from calevate_shared.config import Settings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.model_pricing_test import _purge_table

#: The only leg this suite writes rows for. `google` because it is the one the mechanism was
#: built for and the one a live tenant is on. Since D-478 the dashboard leg for it IS built
#: (`DASHBOARD_ADDRESSABLE_PROVIDERS`), so attesting it here is the LAST ground and makes it
#: eligible — the mechanism's payoff, and what these tests now assert.
PROVIDER = "google"


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
                "VALUES (:id, 'DataUse', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}", admin_id


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: the table is append-only"
    engine = create_async_engine(owner_url)
    try:
        async with engine.begin() as conn:
            await _purge_table(conn, "platform_dashboard_data_use", "provider", [PROVIDER])
    finally:
        await engine.dispose()
    # The seam is process-wide state; a test that installed a reader must not leak it.
    uninstall_pricing_readers()


async def _attest(**overrides: object) -> None:
    _, admin_id = await _make_admin()
    kwargs: dict[str, object] = {
        "provider": PROVIDER,
        "vendor_account_ref": "calevate-prod-000",
        "paid_tier_confirmed": True,
        "no_training_opt_in_confirmed": True,
        "attested_at": datetime.now(UTC),
        "source_note": "AI Studio Projects page, Billing Tier column, 27 Aug 2026",
        "actor_id": admin_id,
    }
    kwargs.update(overrides)
    async with untenanted_session() as session:
        await attest_dashboard_data_use(session, **kwargs)  # type: ignore[arg-type]


# --- 1. the default, which is the whole safety argument -------------------------


async def test_with_nothing_attested_nothing_is_permitted() -> None:
    """A gate that defaults to permitted is not a gate. Asserted over the STORE rather than
    over the installed reader, so an empty database and an empty snapshot both say no."""
    async with untenanted_session() as session:
        assert await dashboard_permitted_providers(session) == frozenset()


async def test_a_recorded_no_is_stored_and_is_not_the_same_state_as_silence() -> None:
    """**A NEGATIVE ATTESTATION IS WORTH RECORDING AND IS NOT REFUSED.** "Somebody looked
    and it is on the unpaid tier" is a different and more useful fact than "nobody has
    looked", and only the first can be acted on. The write accepts it; only the AND of the
    two answers decides eligibility."""
    await _attest(paid_tier_confirmed=False)

    async with untenanted_session() as session:
        stored = await dashboard_data_use_attestations(session)
        assert stored[PROVIDER].paid_tier_confirmed is False
        assert stored[PROVIDER].permits_dashboard is False
        assert await dashboard_permitted_providers(session) == frozenset()


async def test_billing_on_with_a_training_opt_in_is_still_not_permitted() -> None:
    """THE SECOND QUESTION EARNS ITS COLUMN. A form that asked only about the paid tier
    would pass a project whose logs had been opted back into the vendor's free-tier terms,
    which is a false negative on exactly the path that defeats paying."""
    await _attest(paid_tier_confirmed=True, no_training_opt_in_confirmed=False)

    async with untenanted_session() as session:
        assert await dashboard_permitted_providers(session) == frozenset()


# --- 2. append-only, latest-row-wins, and the account it is about ---------------


async def test_an_attestation_cannot_be_edited_or_deleted() -> None:
    """Hard rule 4. The record of what was believed, and when, is the entire value of the
    table; a row somebody could rewrite answers the audit question with today's belief."""
    await _attest()
    async with untenanted_session() as session:
        with pytest.raises(Exception):  # noqa: B017 - the trigger's own error
            await session.execute(
                text(
                    "UPDATE platform_dashboard_data_use SET paid_tier_confirmed = true "
                    "WHERE provider = :p"
                ),
                {"p": PROVIDER},
            )
    async with untenanted_session() as session:
        with pytest.raises(Exception):  # noqa: B017
            await session.execute(
                text("DELETE FROM platform_dashboard_data_use WHERE provider = :p"),
                {"p": PROVIDER},
            )


async def test_the_latest_row_wins_and_a_correction_is_a_new_instant() -> None:
    """A correction supersedes rather than replaces, so the history stays readable."""
    earlier = datetime.now(UTC) - timedelta(days=30)
    await _attest(attested_at=earlier, paid_tier_confirmed=True)
    await _attest(attested_at=datetime.now(UTC), paid_tier_confirmed=False)

    async with untenanted_session() as session:
        stored = await dashboard_data_use_attestations(session)
        assert stored[PROVIDER].paid_tier_confirmed is False
        assert await dashboard_permitted_providers(session) == frozenset()


async def test_a_re_attestation_at_the_same_instant_is_refused_by_name() -> None:
    """The one write an append-only table cannot express, refused with a sentence rather
    than surfacing as a primary-key 500."""
    now = datetime.now(UTC)
    await _attest(attested_at=now)
    with pytest.raises(ProblemError) as raised:
        await _attest(attested_at=now)
    assert raised.value.code == "dashboard_data_use_duplicate_instant"


async def test_an_attestation_with_no_account_reference_is_refused() -> None:
    """Without the project id the claim can never be VERIFIED, only re-made — which is the
    difference between this table and a signature. Refused with the sentence rather than
    left to the database CHECK."""
    with pytest.raises(ProblemError) as raised:
        await _attest(vendor_account_ref="   ")
    assert raised.value.code == "dashboard_data_use_evidence_missing"
    assert "re-check" in (raised.value.remediation or "")


async def test_an_undeclared_provider_is_refused() -> None:
    with pytest.raises(ProblemError) as raised:
        await _attest(provider="anthropic")
    assert raised.value.code == "dashboard_data_use_unknown_provider"


# --- 3. the seam the eligibility gate reads -------------------------------------


async def test_the_gate_reads_the_attestation_through_the_installed_reader() -> None:
    """END TO END, and BOTH halves of the answer.

    Before attesting, the reported ground is "nobody has attested" — which is what makes this
    a field something READS rather than a column nothing consults. Since D-478 the Gemini
    dashboard leg IS built, so the attestation clears the LAST ground and the leg becomes
    eligible; before D-478 it would have moved to "we have not built the leg" instead.
    """
    install_pricing_readers()
    await refresh_pricing_snapshot()
    assert dashboard_leg_reason(PROVIDER) == NO_DATA_USE_ATTESTATION_REASON

    await _attest()
    await refresh_pricing_snapshot()

    assert dashboard_leg_reason(PROVIDER) is None


# --- 4. the surface -------------------------------------------------------------


async def _audit_count() -> int:
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE "
                    "action = 'platform.dashboard_data_use_attested' AND object_id = :p"
                ),
                {"p": PROVIDER},
            )
        ).scalar() or 0


async def test_get_lists_every_declared_leg_with_its_ground_and_the_statement() -> None:
    token, _ = await _make_admin()
    async with _client() as http:
        response = await http.get("/v1/ops/dashboard-data-use", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    rows = {row["provider"]: row for row in body["providers"]}
    assert set(rows) == {"azure_openai", "openai", "google"}
    # Since D-478 the Gemini leg IS built, so `dashboard_leg_built` is True — but it is still
    # NOT eligible here, because this suite has attested nothing. The two facts are reported
    # separately so the panel can say plainly that attesting WILL now switch it on.
    assert rows["google"]["dashboard_leg_built"] is True
    assert rows["google"]["eligible"] is False
    assert rows["google"]["attested_at"] is None
    assert rows["azure_openai"]["eligible"] is True
    # The form renders the server's sentence rather than keeping its own copy that drifts.
    assert body["statement"] == ATTESTATION_STATEMENT


async def test_a_normal_admin_cannot_reach_the_panel() -> None:
    token, _ = await _make_admin("operator")
    async with _client() as http:
        listed = await http.get("/v1/ops/dashboard-data-use", headers=_auth(token))
    assert listed.status_code == 403


async def test_attest_via_the_route_needs_step_up_and_lands_an_audit_row() -> None:
    token, _ = await _make_admin()
    path = f"/v1/ops/dashboard-data-use/{PROVIDER}"
    payload = {
        "vendor_account_ref": "calevate-prod-000",
        "paid_tier_confirmed": True,
        "no_training_opt_in_confirmed": True,
        "source_note": "AI Studio Projects page, Billing Tier column, 27 Aug 2026",
    }
    # audit_log is global and append-only (never purged), so assert the DELTA, not a total.
    before = await _audit_count()
    async with _client() as http:
        no_confirm = await http.post(path, headers=_auth(token), json=payload)
        assert no_confirm.status_code == 403

        ok = await http.post(
            path, headers=_auth(token, attest_confirmation(PROVIDER)), json=payload
        )
    assert ok.status_code == 200, ok.text
    row = ok.json()["provider"]
    assert row["vendor_account_ref"] == "calevate-prod-000"
    assert row["paid_tier_confirmed"] is True
    # NOW ELIGIBLE (D-478): the Gemini dashboard leg is built, so this attestation clears the
    # last ground and the response says the assistant will run on it — rather than leaving an
    # operator to find out by watching it not move.
    assert row["eligible"] is True
    assert row["blocked_reason"] is None

    assert await _audit_count() == before + 1


async def test_the_route_refuses_a_blank_reference_and_an_undeclared_provider() -> None:
    token, _ = await _make_admin()
    async with _client() as http:
        blank = await http.post(
            f"/v1/ops/dashboard-data-use/{PROVIDER}",
            headers=_auth(token, attest_confirmation(PROVIDER)),
            json={
                "vendor_account_ref": "   ",
                "paid_tier_confirmed": True,
                "no_training_opt_in_confirmed": True,
                "source_note": "AI Studio, 27 Aug 2026",
            },
        )
        assert blank.status_code == 422

        unknown = await http.post(
            "/v1/ops/dashboard-data-use/anthropic",
            headers=_auth(token, attest_confirmation("anthropic")),
            json={
                "vendor_account_ref": "acct-1",
                "paid_tier_confirmed": True,
                "no_training_opt_in_confirmed": True,
                "source_note": "vendor console, 27 Aug 2026",
            },
        )
    assert unknown.status_code == 404
    assert unknown.json()["type"].endswith("dashboard_data_use_unknown_provider")
