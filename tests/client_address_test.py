"""One client IP, and a limiter identity that survives a restart (plan Part 2).

Two defects that compounded, both now closed by ONE definition —
`calevate_shared.client_address.client_ip`, which used to live only in the engine
receiver:

**The API read the socket peer.** Behind Cloudflare + nginx that is the PROXY, so every
`audit_log.ip` recorded our own edge (SEC-COMP §5 wants the caller) and the signup
quota's per-IP window — 30/hour — was spent against one shared value, i.e. it capped the
whole platform at 30 signups an hour and let one abuser deny self-serve to everyone.

**The limiter keyed identity on `hash(auth)`.** `str.__hash__` is salted per PROCESS
(PEP 456), and the deployment runs two uvicorn workers, so one token occupied N buckets:
the effective limit was N times the declared one and changed on every restart.

The subprocess test at the bottom is the one that could have caught that second defect
before it shipped, and it is written the way it is on purpose: it runs the fingerprint in
two FRESH interpreters with different `PYTHONHASHSEED` values, because a same-process
assertion passes on the broken code.
"""

from __future__ import annotations

import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from apps.api.core.auth import client_request_ip
from apps.api.core.ratelimit import fingerprint
from apps.api.core.settings import get_settings
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.tenancy import signup as signup_service
from calevate_shared.client_address import client_ip, is_trusted_peer
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from starlette.datastructures import Headers
from starlette.requests import Request

# RFC 5737 documentation ranges: unroutable, so a copy-paste into a real config is inert.
CALLER_IP = "203.0.113.44"  # the browser
OTHER_CALLER_IP = "203.0.113.45"  # a different browser, same edge
EDGE_PEER = "127.0.0.1"  # our nginx, inside TRUSTED_PROXY_CIDRS
OUTSIDE_PEER = "198.51.100.9"  # something talking to the container directly


# --- 1. the shared definition -------------------------------------------------------


@pytest.mark.parametrize(
    ("peer", "headers", "expected"),
    [
        # The ordinary production shape: nginx is the peer and it set the header.
        (EDGE_PEER, {"cf-connecting-ip": CALLER_IP}, CALLER_IP),
        # A stranger reaching the container directly, claiming to be someone else.
        (OUTSIDE_PEER, {"cf-connecting-ip": CALLER_IP}, None),
        # A trusted hop, but the edge stopped setting the header.
        (EDGE_PEER, {}, None),
        # TWO HOPS in one header — the shape a forger appends. Not a single literal
        # address, so it fails closed rather than yielding either half.
        (EDGE_PEER, {"cf-connecting-ip": f"{CALLER_IP}, {OTHER_CALLER_IP}"}, None),
        # `X-Forwarded-For` is not consulted at all: its leftmost entry is attacker input
        # by construction (MDN; RFC 7239 §8.1).
        (EDGE_PEER, {"x-forwarded-for": CALLER_IP}, None),
        # No peer at all (a unix-socket upstream reports none).
        (None, {"cf-connecting-ip": CALLER_IP}, None),
    ],
)
def test_outside_local_only_a_trusted_hops_header_is_believed(
    peer: str | None, headers: dict[str, str], expected: str | None
) -> None:
    assert client_ip(peer, headers, app_env="prod") == expected


def test_local_falls_back_to_the_socket_peer_because_there_is_no_edge() -> None:
    """`local` is the one environment with nothing in front, so the peer IS the caller —
    which is what keeps the whole test suite and a dev proxy working."""
    assert client_ip(OUTSIDE_PEER, {}, app_env="local") == OUTSIDE_PEER
    assert client_ip(EDGE_PEER, {"cf-connecting-ip": CALLER_IP}, app_env="local") == CALLER_IP


def test_an_unparseable_peer_is_not_a_trusted_proxy() -> None:
    assert is_trusted_peer("") is False
    assert is_trusted_peer("not-an-ip") is False
    assert is_trusted_peer(EDGE_PEER) is True


def test_there_is_exactly_one_definition_of_the_client_address() -> None:
    """`apps/api` and `apps/voice-runtime` must not answer "who is calling" twice.

    The receiver's `client_ip` was the correct implementation and the API had a second,
    wrong one; the fix is that both import this. Asserted by identity, so re-adding a
    local copy in either service fails here rather than at the next incident.
    """
    import engine_intake
    import tool_routes
    import webhook_routes
    from apps.api.core import auth as api_auth

    assert webhook_routes.client_ip is client_ip
    assert tool_routes.client_ip is client_ip
    assert api_auth.client_ip is client_ip
    assert not hasattr(engine_intake, "client_ip"), (
        "engine_intake defines a second client_ip again — one way per problem"
    )


def _request(peer: str | None, headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/v1/agents",
            "headers": Headers(headers).raw,
            "client": (peer, 41000) if peer else None,
        }
    )


def test_the_api_dependency_reads_the_caller_not_the_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`client_request_ip` is what stamps `audit_log.ip`. Pinned in a NON-local
    environment, because local's peer fallback would hide the defect being fixed."""
    monkeypatch.setattr(get_settings(), "app_env", "staging")
    assert client_request_ip(_request(EDGE_PEER, {"CF-Connecting-IP": CALLER_IP})) == CALLER_IP
    assert client_request_ip(_request(EDGE_PEER, {})) is None
    assert client_request_ip(_request(OUTSIDE_PEER, {"CF-Connecting-IP": CALLER_IP})) is None


# --- 2. the signup quota's IP dimension ---------------------------------------------


def _client(peer: str) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=app, client=(peer, 12345)), base_url="http://api"
    )


async def _signed_up_user() -> str:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    return f"dev:client:{user_id}"


def _signup_body() -> dict[str, str]:
    return {
        "business_name": "Sunrise Dental",
        "slug": f"ip-{uuid.uuid4().hex[:8]}",
        "vertical_template": "clinic",
        "language": "te-IN",
    }


def _headers(token: str, caller_ip: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "CF-Connecting-IP": caller_ip}


def _caller_address() -> str:
    """A CALL-unique documentation address (RFC 3849's `2001:db8::/32`).

    The signup quota's window is an HOUR and this suite runs many times an hour, so an
    address drawn from RFC 5737's 254-address /24 would eventually inherit an earlier
    run's count and refuse the first signup — a test failing for a reason that is not the
    code. IPv6 documentation space is the same idea with enough room to never collide.
    """
    return f"2001:db8:{uuid.uuid4().hex[:4]}:{uuid.uuid4().hex[:4]}::1"


async def test_two_callers_behind_one_proxy_do_not_share_the_signup_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE PLATFORM CAP. Both requests arrive from the same socket peer — our own edge,
    which is what every real request looks like — and differ only in the address the edge
    vouched for. With the quota spent against the peer, the second was a 429 and thirty
    signups an hour was the ceiling for the entire internet.

    Run-unique addresses because the suite shares one Redis with other work: a hardcoded
    documentation IP would inherit whatever a previous run left in the hourly bucket.
    """
    monkeypatch.setattr(signup_service, "SIGNUPS_PER_IP_PER_HOUR", 1)
    monkeypatch.setattr(get_settings(), "self_serve_signup_enabled", True)
    first_ip, second_ip = _caller_address(), _caller_address()

    async with _client(EDGE_PEER) as http:
        first = await http.post(
            "/v1/auth/signup",
            headers=_headers(await _signed_up_user(), first_ip),
            json=_signup_body(),
        )
        second = await http.post(
            "/v1/auth/signup",
            headers=_headers(await _signed_up_user(), second_ip),
            json=_signup_body(),
        )
        # ...and the same caller a second time still IS refused, so the limit is real.
        third = await http.post(
            "/v1/auth/signup",
            headers=_headers(await _signed_up_user(), first_ip),
            json=_signup_body(),
        )

    assert first.status_code == 201, first.text
    assert second.status_code == 201, second.text
    assert third.status_code == 429, third.text


async def test_the_audit_row_records_the_caller_behind_the_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SEC-COMP §5's "actor, tenant, at, ip" — the `ip` half, end to end through the
    route, rather than as a unit call."""
    monkeypatch.setattr(get_settings(), "self_serve_signup_enabled", True)
    caller = _caller_address()
    async with _client(EDGE_PEER) as http:
        created = await http.post(
            "/v1/auth/signup",
            headers=_headers(await _signed_up_user(), caller),
            json=_signup_body(),
        )
    assert created.status_code == 201, created.text

    tenant_id = uuid.UUID(created.json()["tenant_id"])
    async with untenanted_session() as session:
        recorded = (
            await session.execute(
                text(
                    "SELECT ip FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'organization.self_serve_created'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert str(recorded) == caller, "the ledger recorded the proxy, not the caller"


# --- 3. the limiter identity ---------------------------------------------------------

_TOKEN = "Bearer eyJhbGciOi.stable.token"
_FINGERPRINT_PROBE = (
    "from apps.api.core.ratelimit import fingerprint;"
    f"print(fingerprint({_TOKEN!r}), hash({_TOKEN!r}))"
)
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _probe(seed: str) -> tuple[str, str]:
    result = subprocess.run(
        [sys.executable, "-c", _FINGERPRINT_PROBE],
        capture_output=True,
        text=True,
        check=True,
        cwd=_REPO_ROOT,
        env={"PYTHONHASHSEED": seed, "PATH": "/usr/bin:/bin"},
    )
    digest, builtin = result.stdout.split()
    return digest, builtin


def test_the_identity_bucket_is_stable_across_processes() -> None:
    """THE DEFECT, REPRODUCED AND CLOSED IN ONE TEST.

    Two fresh interpreters with different hash seeds — which is what two uvicorn workers
    are, and what the same worker is after a restart. `fingerprint` must agree; the
    builtin `hash` the limiter used to key on must NOT, or this test would be asserting
    nothing about the thing that was wrong.

    """
    ours_a, builtin_a = _probe("1")
    ours_b, builtin_b = _probe("2")
    assert ours_a == ours_b, "the limiter's identity moved between processes"
    assert builtin_a != builtin_b, (
        "PYTHONHASHSEED is not varying, so this test cannot see the defect it exists for"
    )


def test_the_fingerprint_is_wide_enough_to_not_collide_tenants() -> None:
    """The old key truncated to 32 bits — ~77k live tokens to a 50% collision by the
    birthday bound, i.e. one tenant spending another tenant's limiter budget."""
    assert len(fingerprint("Bearer a")) == 32  # 16 bytes of blake2s, hex
    assert fingerprint("Bearer a") != fingerprint("Bearer b")
