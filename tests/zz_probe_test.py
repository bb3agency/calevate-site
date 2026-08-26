from __future__ import annotations
import uuid
from tests.self_serve_test import _client, _headers, _signed_up_user, _signup_body  # type: ignore
import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from sqlalchemy import text


@pytest.fixture(autouse=True)
def _on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "self_serve_signup_enabled", True)


async def test_probe_nul_byte_name() -> None:
    token, _ = await _signed_up_user()
    async with _client() as c:
        r = await c.post("/v1/auth/signup", json=_signup_body(business_name="Ab\x00cd"), headers=_headers(token))
    print("NUL name ->", r.status_code, r.text[:400])


async def test_probe_whitespace_name() -> None:
    token, _ = await _signed_up_user()
    async with _client() as c:
        r = await c.post("/v1/auth/signup", json=_signup_body(business_name="   "), headers=_headers(token))
    print("WS name ->", r.status_code, r.text[:400])


async def test_probe_control_name() -> None:
    token, _ = await _signed_up_user()
    async with _client() as c:
        r = await c.post("/v1/auth/signup", json=_signup_body(business_name="Acme‮\ninjected\r\nX"), headers=_headers(token))
    print("CTRL name ->", r.status_code, r.text[:600])


async def test_probe_two_orgs_one_user() -> None:
    token, uid = await _signed_up_user()
    async with _client() as c:
        r1 = await c.post("/v1/auth/signup", json=_signup_body(), headers=_headers(token))
        r2 = await c.post("/v1/auth/signup", json=_signup_body(), headers=_headers(token))
    print("two orgs ->", r1.status_code, r2.status_code)
    async with untenanted_session() as s:
        n = (await s.execute(text("SELECT count(*) FROM memberships WHERE user_id=:u"), {"u": uid})).scalar()
    print("memberships:", n)


async def test_probe_unverified_email() -> None:
    token, uid = await _signed_up_user()
    async with untenanted_session() as s:
        v = (await s.execute(text("SELECT email_verified_at FROM users WHERE id=:u"), {"u": uid})).scalar()
    async with _client() as c:
        r = await c.post("/v1/auth/signup", json=_signup_body(), headers=_headers(token))
    print("email_verified_at:", v, "-> signup", r.status_code)
