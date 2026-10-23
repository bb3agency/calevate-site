"""The billing screen's two new reads (D-869): Clear against Studio, and credit used this
month against all time.

The tier comparison must quote only rates the card and the wallet already price (hard rule
7): its range is checked against `rate_card_out`, the one function every other rate surface
reads, rather than against numbers typed here. Credit usage is owner-only (`billing:read`)
and per account.
"""

from __future__ import annotations

from decimal import Decimal

import httpx
from apps.api.billing.payment_routes import rate_card_out
from apps.api.billing.service import record_entry
from apps.api.billing.tier_routes import recommend
from apps.api.db.session import tenant_session
from apps.api.main import app
from tests.api_security_test import _make_tenant
from tests.conftest import fund_wallet


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def test_the_comparison_quotes_the_card_and_the_wallet() -> None:
    tenant_id, slug, token = await _make_tenant()
    await fund_wallet(tenant_id, "1000.00")
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        response = await http.get("/v1/billing/voice-tiers", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    async with tenant_session(tenant_id) as session:
        card = await rate_card_out(session)

    tiers = {t["tier"]: t for t in body["tiers"]}
    assert list(tiers) == ["clear", "studio"]
    assert tiers["clear"]["label"] == card.clear_tier_label
    assert Decimal(tiers["clear"]["from_inr_per_min"]) == min(
        p.clear_inr_per_min for p in card.packs
    )
    assert Decimal(tiers["studio"]["to_inr_per_min"]) == max(
        p.studio_inr_per_min for p in card.packs
    )
    # A ledger top-up opens no credit lot (lots open on a paid pack), so there is no rate
    # to quote: null, never a card figure standing in for one.
    assert tiers["clear"]["your_inr_per_min"] is None
    assert tiers["clear"]["minutes_left"] is None
    assert body["recommended"] in ("clear", "studio")
    assert all(t["includes"] for t in body["tiers"])


def test_the_recommendation_follows_use_and_availability() -> None:
    assert (
        recommend(studio_offered=False, clear_minutes=Decimal(0), studio_minutes=Decimal(9))[0]
        == "clear"
    )
    assert (
        recommend(studio_offered=True, clear_minutes=Decimal(2), studio_minutes=Decimal(9))[0]
        == "studio"
    )
    assert (
        recommend(studio_offered=True, clear_minutes=Decimal(0), studio_minutes=Decimal(0))[0]
        == "clear"
    )


async def test_credit_usage_this_month_and_all_time_is_the_accounts_own() -> None:
    tenant_id, slug, token = await _make_tenant()
    other_id, other_slug, other_token = await _make_tenant()
    _staff_id, staff_slug, staff_token = await _make_tenant(role="staff")
    await fund_wallet(tenant_id, "1000.00")
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-100.00"),
            reason="adjustment",
            ref="test-adjust",
        )

    async with _client() as http:
        mine = await http.get(
            "/v1/billing/credit-usage",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
        )
        theirs = await http.get(
            "/v1/billing/credit-usage",
            headers={"Authorization": f"Bearer {other_token}", "X-Org-Slug": other_slug},
        )
        staff = await http.get(
            "/v1/billing/credit-usage",
            headers={"Authorization": f"Bearer {staff_token}", "X-Org-Slug": staff_slug},
        )

    assert mine.status_code == 200, mine.text
    body = mine.json()
    for period in ("this_month", "all_time"):
        assert body[period]["added_inr"] == "1000.00"
        assert body[period]["spent_inr"] == "100.00"
        assert body[period]["adjustments_inr"] == "100.00"
    assert theirs.json()["all_time"]["added_inr"] == "0.00"
    assert staff.status_code == 403
    assert other_id != tenant_id
