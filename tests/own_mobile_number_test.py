"""`POST /v1/auth/client/mobile-number` — a signed-in person's own mobile number (D-976).

Driven over ASGI against the real app with a real client session cookie, because the parts
most likely to be wrong are which credential admits the request and what the row holds
afterwards. The two refusals this unblocks are driven through their own production paths:
the WhatsApp alert read (`GET /v1/compliance/whatsapp-alerts`) and the start of an
automatic-payment approval (`auto_recharge.begin_mandate`, provider faked).

CONCURRENCY: every case mints its own tenant, users and sessions, and asserts only on rows
it created, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest
from apps.api.authn import mobile_number
from apps.api.authn.cookies import cookie_name
from apps.api.authn.sessions import issue_session
from apps.api.billing import auto_recharge, payments
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.core.settings import get_settings
from apps.api.db.session import credential_session, tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements, create_org_with_receptionist
from tests.impersonation_grant_test import view_as_headers

PATH = "/v1/auth/client/mobile-number"
ALERTS = "/v1/compliance/whatsapp-alerts"

TYPED = "98765 43210"
E164 = "+919876543210"
OTHER_E164 = "+919876500011"


def _client(cookies: dict[str, str] | None = None) -> AsyncClient:
    """A run-unique documentation address (RFC 3849), so the `/v1/auth/**` rate limit is
    never shared with another test."""
    peer = f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)),
        base_url="https://api.calevate.tech",
        cookies=cookies,
    )


@dataclass(frozen=True, slots=True)
class Member:
    tenant_id: UUID
    slug: str
    user_id: UUID

    @property
    def bearer(self) -> dict[str, str]:
        return {"Authorization": f"Bearer dev:client:{self.user_id}", "X-Org-Slug": self.slug}


async def _tenant() -> tuple[UUID, str]:
    created = await create_org_with_receptionist(
        name="Mobile Number Traders",
        slug=f"mob-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email="owner@example.com",
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), str(created["slug"])


async def _member(tenant: tuple[UUID, str] | None = None, *, phone: str | None = None) -> Member:
    tenant_id, slug = tenant or await _tenant()
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, phone, created_at, updated_at) "
                "VALUES (:id, :email, :phone, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com", "phone": phone},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return Member(tenant_id=tenant_id, slug=slug, user_id=user_id)


async def _cookie(user_id: UUID) -> dict[str, str]:
    """A live client session, as the browser presents it."""
    async with credential_session() as session:
        issued = await issue_session(session, realm="client", subject_id=user_id)
    return {cookie_name("client", secure=True): issued.token}


async def _put(user_id: UUID, body: dict[str, Any]) -> Any:
    async with _client(await _cookie(user_id)) as http:
        return await http.post(PATH, json=body)


async def _row(user_id: UUID) -> tuple[str | None, datetime | None]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT phone, phone_verified_at FROM users WHERE id = :id"), {"id": user_id}
            )
        ).one()
    return row[0], row[1]


async def _mark_verified(user_id: UUID) -> None:
    """What the future WhatsApp code step will do; nothing in the product does it today."""
    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE users SET phone_verified_at = now() WHERE id = :id"), {"id": user_id}
        )


async def _audit_rows(user_id: UUID) -> list[tuple[Any, ...]]:
    async with untenanted_session() as session:
        return [
            tuple(row)
            for row in (
                await session.execute(
                    text(
                        "SELECT action, actor_type, actor_id, tenant_id, object_type, "
                        "object_id, ip FROM audit_log WHERE object_id = :id "
                        "AND action = :action ORDER BY at"
                    ),
                    {"id": str(user_id), "action": mobile_number.AUDIT_ACTION},
                )
            ).all()
        ]


def _code(response: Any) -> str:
    return str(response.json()["type"]).rsplit("/", 1)[-1]


# --- set, change, clear ----------------------------------------------------------------


async def test_a_typed_ten_digit_mobile_is_stored_as_e164_and_unconfirmed() -> None:
    member = await _member()

    response = await _put(member.user_id, {"phone": TYPED})

    assert response.status_code == 200, response.text
    assert response.json() == {"change": "added"}
    assert E164 not in response.text, "a public-prefix route echoes no contact field"
    assert await _row(member.user_id) == (E164, None)
    async with _client() as http:
        me = await http.get("/v1/me", headers=member.bearer)
    assert me.status_code == 200, me.text
    assert me.json()["phone"] == E164


@pytest.mark.parametrize("typed", ["09876543210", "+91 98765-43210", "  9876543210 "])
async def test_every_common_way_of_writing_the_number_lands_on_one_value(typed: str) -> None:
    member = await _member()
    response = await _put(member.user_id, {"phone": typed})
    assert response.status_code == 200, response.text
    assert (await _row(member.user_id))[0] == E164


async def test_changing_the_number_clears_its_confirmation_and_repeating_it_does_not() -> None:
    member = await _member(phone=E164)
    await _mark_verified(member.user_id)

    same = await _put(member.user_id, {"phone": TYPED})
    assert same.json() == {"change": "unchanged"}
    phone, verified_at = await _row(member.user_id)
    assert phone == E164 and verified_at is not None, "saving the same number keeps its proof"

    changed = await _put(member.user_id, {"phone": OTHER_E164})
    assert changed.status_code == 200, changed.text
    assert changed.json() == {"change": "changed"}
    assert await _row(member.user_id) == (OTHER_E164, None)


@pytest.mark.parametrize("cleared", [None, "", "   "])
async def test_null_or_blank_removes_the_number(cleared: str | None) -> None:
    member = await _member(phone=E164)
    await _mark_verified(member.user_id)

    response = await _put(member.user_id, {"phone": cleared})

    assert response.status_code == 200, response.text
    assert response.json() == {"change": "removed"}
    assert await _row(member.user_id) == (None, None)


async def test_a_number_that_cannot_be_read_is_refused_in_plain_words() -> None:
    member = await _member(phone=E164)

    response = await _put(member.user_id, {"phone": "12345"})

    assert response.status_code == 422, response.text
    assert _code(response) == "mobile_number_invalid"
    assert response.json()["detail"] == (
        "Enter a 10-digit mobile number, or the full number starting with +."
    )
    assert "12345" not in response.text, "the refusal does not echo what was typed"
    assert await _row(member.user_id) == (E164, None), "a refused write changes nothing"


# --- who may write ---------------------------------------------------------------------


async def test_no_client_session_is_refused() -> None:
    member = await _member()
    async with _client() as http:
        response = await http.post(PATH, json={"phone": TYPED}, headers=member.bearer)
    assert response.status_code == 401, response.text
    assert await _row(member.user_id) == (None, None)


async def test_an_operator_viewing_as_the_client_cannot_change_the_owners_number() -> None:
    tenant = await _tenant()
    await accept_agreements(tenant[0])
    owner = await _member(tenant, phone=E164)
    operator_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": operator_id},
        )
    async with credential_session() as session:
        admin_session = await issue_session(
            session, realm="admin", subject_id=operator_id, mfa_verified_at=datetime.now(UTC)
        )

    async with _client({cookie_name("admin", secure=True): admin_session.token}) as http:
        headers = await view_as_headers(http, f"dev:admin:{operator_id}", tenant[1])
        response = await http.post(PATH, json={"phone": OTHER_E164}, headers=headers)

    assert response.status_code == 401, response.text
    assert await _row(owner.user_id) == (E164, None)
    assert await _audit_rows(owner.user_id) == []


async def test_the_body_cannot_name_another_person() -> None:
    """The row is the session's subject and nothing else: a body naming a user is refused
    before anything is written, and a colleague's number is untouched."""
    tenant = await _tenant()
    caller = await _member(tenant)
    colleague = await _member(tenant, phone=E164)

    response = await _put(caller.user_id, {"phone": OTHER_E164, "user_id": str(colleague.user_id)})

    assert response.status_code == 422, response.text
    assert await _row(colleague.user_id) == (E164, None)
    assert await _row(caller.user_id) == (None, None)

    own = await _put(caller.user_id, {"phone": OTHER_E164})
    assert own.status_code == 200, own.text
    assert await _row(colleague.user_id) == (E164, None)
    assert await _row(caller.user_id) == (OTHER_E164, None)


# --- the record ------------------------------------------------------------------------


async def test_each_change_is_audited_by_id_and_a_repeat_is_not(
    caplog: pytest.LogCaptureFixture,
) -> None:
    member = await _member()

    with caplog.at_level(logging.INFO):
        assert (await _put(member.user_id, {"phone": TYPED})).json()["change"] == "added"
        assert (await _put(member.user_id, {"phone": E164})).json()["change"] == "unchanged"
        assert (await _put(member.user_id, {"phone": OTHER_E164})).json()["change"] == "changed"
        assert (await _put(member.user_id, {"phone": None})).json()["change"] == "removed"

    rows = await _audit_rows(member.user_id)
    assert len(rows) == 3, "added, changed, removed; the repeat writes nothing"
    for action, actor_type, actor_id, tenant_id, object_type, object_id, ip in rows:
        assert action == mobile_number.AUDIT_ACTION
        assert actor_type == "user"
        assert actor_id == member.user_id
        assert tenant_id is None, "a login belongs to a person, not to one account"
        assert object_type == "auth_subject" and object_id == str(member.user_id)
        assert ip is not None
    stored = " ".join(str(value) for row in rows for value in row)
    rendered = "\n".join(JsonFormatter().format(record) for record in caplog.records)
    for number in (E164, OTHER_E164):
        assert number.lstrip("+") not in stored
        assert number.lstrip("+") not in rendered, "hard rule 6: no number in a log line"
    assert "own_mobile_number_set" in rendered


# --- what it unblocks ------------------------------------------------------------------


async def test_whatsapp_alerts_stop_refusing_once_the_number_is_added() -> None:
    member = await _member()

    async with _client() as http:
        before = await http.get(ALERTS, headers=member.bearer)
    assert before.status_code == 422, before.text
    assert _code(before) == "alert_optin_needs_a_number"
    assert "Your account" in before.json()["remediation"]

    assert (await _put(member.user_id, {"phone": TYPED})).status_code == 200

    async with _client() as http:
        after = await http.get(ALERTS, headers=member.bearer)
    assert after.status_code == 200, after.text
    assert after.json()["status"] == "none", "a number is not a consent; the owner still agrees"


@dataclass
class _FakeRazorpay:
    customers: list[dict[str, Any]] = field(default_factory=list)

    async def create_customer(self, **kwargs: Any) -> str:
        self.customers.append(kwargs)
        return f"cust_{uuid.uuid4().hex[:14]}"

    async def create_mandate_order(self, **_: Any) -> str:
        return f"order_{uuid.uuid4().hex[:14]}"


async def test_automatic_top_ups_stop_refusing_once_the_number_is_added(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "payment_provider", payments.PROVIDER)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_mobile")
    monkeypatch.setattr(settings, "razorpay_key_secret", "rzp_secret_mobile")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec_mobile")
    monkeypatch.setattr(settings, "razorpay_mode", None)
    fake = _FakeRazorpay()
    monkeypatch.setattr(auto_recharge, "razorpay_api", lambda: fake)
    member = await _member()

    with pytest.raises(ProblemError) as refused:
        await auto_recharge.begin_mandate(
            tenant_id=member.tenant_id,
            user_id=member.user_id,
            method="upi",
            max_debit_inr=Decimal("2000.00"),
        )
    assert refused.value.code == "auto_recharge_needs_contact"
    assert refused.value.remediation is not None and "Your account" in refused.value.remediation

    assert (await _put(member.user_id, {"phone": TYPED})).status_code == 200

    checkout = await auto_recharge.begin_mandate(
        tenant_id=member.tenant_id,
        user_id=member.user_id,
        method="upi",
        max_debit_inr=Decimal("2000.00"),
    )
    assert checkout.order_id
    assert [customer["contact"] for customer in fake.customers] == [E164]
