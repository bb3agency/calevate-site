"""The ops route that attests what a client pays for a number-month (gate 26, D-681).

₹499/month is the founder's figure, and it is an ATTESTATION an operator records with its
source — never a constant in code. Like the engine-minute price, the write is step-up
confirmed and audited.
"""

from __future__ import annotations

import uuid

from apps.api.campaigns.number_pricing_routes import ATTEST_NUMBER_PRICE_CONFIRMATION
from apps.api.db.session import untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin

PATH = "/v1/admin/number-pricing"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _rows(source: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM number_price_attestations WHERE source = :s"),
                    {"s": source},
                )
            ).scalar_one()
        )


async def _audits(source: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log a JOIN number_price_attestations n "
                        "ON a.object_id = n.id::text WHERE a.action = 'number_price.attested' "
                        "AND n.source = :s"
                    ),
                    {"s": source},
                )
            ).scalar_one()
        )


def test_the_confirmation_string_is_the_one_the_console_sends() -> None:
    assert ATTEST_NUMBER_PRICE_CONFIRMATION == "attest_number_price"


async def test_an_attestation_without_step_up_is_refused_and_writes_nothing() -> None:
    token = await _make_admin()
    source = f"Founder decision D-681, 7 Oct 2026 ({uuid.uuid4().hex[:8]})"
    async with _client() as http:
        response = await http.post(
            PATH,
            headers={"Authorization": f"Bearer {token}"},
            json={"inr_per_month": "499.00", "source": source},
        )
    assert response.status_code == 403, response.text
    assert response.json()["type"].endswith("/step_up_required")
    assert await _rows(source) == 0


async def test_a_confirmed_attestation_is_recorded_audited_and_read_back() -> None:
    token = await _make_admin()
    source = f"Founder decision D-681, 7 Oct 2026 ({uuid.uuid4().hex[:8]})"
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Confirm-Action": ATTEST_NUMBER_PRICE_CONFIRMATION,
    }
    async with _client() as http:
        created = await http.post(
            PATH, headers=headers, json={"inr_per_month": "499.00", "source": source}
        )
        assert created.status_code == 201, created.text
        assert created.json()["inr_per_month"] == "499.00"
        read = await http.get(PATH, headers={"Authorization": f"Bearer {token}"})
    assert read.status_code == 200
    assert read.json()["attested"] is True
    assert await _rows(source) == 1
    assert await _audits(source) == 1
