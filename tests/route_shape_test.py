"""Route SHAPE, and the one error path that renders a bound parameter.

Three findings from the authz audit are fixed here, and each one is a case where the
code's shape — not its logic — was the defect:

1. `POST /v1/agents/{agent_id}/publish` inferred its tenant from the principal, which
   for an admin-realm mutation is a tenant that can never exist (D-22). The route was
   un-callable in every configuration. It now names its tenant in the path, like every
   other admin mutation, at
   `POST /v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish`.
2. `GET /v1/me` declared `org:read` in `openapi_extra` and enforced nothing.
3. The SQLAlchemy engine rendered bound parameters into `str(exc)`, so a DB error on
   the transcript insert produced a string quoting the raw turn — hard rule 6, on the
   path least likely to be exercised before production.

The structural test at the bottom is the one that generalises: it fails for ANY future
admin-realm mutation that tries to infer its tenant the way publish did, rather than
waiting for someone to notice the endpoint has never returned anything but 401.

Concurrency note: this repo's tests share one Postgres. Every case below is scoped to
a run-unique tenant; nothing asserts a global row count.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.auth import tenant_of
from apps.api.core.rbac import (
    MUTATING_PERMISSIONS,
    PUBLIC_PREFIXES,
    ROLE_PERMISSIONS,
    iter_api_routes,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIRoute
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

# A realistic Telugu turn with an E.164 number inside it — the exact pair hard rule 6
# names (transcript text AND a phone number), so a leak of either fails the assertion.
TELUGU_TURN = "నా నంబర్ +919876543210 కి రేపు కాల్ చేయండి, నేను అపాయింట్‌మెంట్ కావాలి"
PHONE = "+919876543210"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """Same idiom as `authz_audit_test._make_admin`."""
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id, "role": role},
        )
    return f"dev:admin:{clerk_id}"


async def _make_org() -> dict[str, object]:
    return await admin_service.create_organization(
        name="Route Shape Clinic",
        slug=f"rs-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{clerk_id}"


async def _failing_transcript_insert(tenant_id: uuid.UUID) -> IntegrityError:
    """A REAL database error on the real transcript statement, with the real payload
    bound to it.

    The provocation is the `speaker` check constraint (`speaker IN ('agent','caller')`,
    migration 05bba2f3c19c) because it fails in Postgres AFTER the parameters are bound
    and sent — which is the situation that renders them. A client-side validation error
    would never reach the DBAPI and would prove nothing about the engine's rendering.
    """
    with pytest.raises(IntegrityError) as caught:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, "
                    "text, text_redacted, lang, start_ms, end_ms, created_at, updated_at) "
                    "VALUES (:id, :tid, :cid, :idx, :speaker, :text, :redacted, :lang, "
                    "0, 1, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "cid": uuid.uuid4(),
                    "idx": 0,
                    "speaker": "not-a-speaker",
                    "text": TELUGU_TURN,
                    "redacted": "[redacted]",
                    "lang": "te",
                },
            )
    return caught.value


# ------------------------------------------------- hard rule 6 on the error path


async def test_a_failed_transcript_insert_does_not_quote_the_transcript() -> None:
    """The engine must not render bound parameters into a DBAPI error string.

    Before `hide_parameters=True`, `str(exc)` on this insert was 738 characters ending
    in `[parameters: {... 'text': '<the whole Telugu turn, phone number included>'}]`.
    Whether that reached a log depended on where the 200-char cap in
    `redact_text()` happened to fall relative to the length of the SQL statement — a
    coincidence, not a control, and hard rule 6 does not have a length exemption.

    Asserted on the EXCEPTION rather than on captured log output on purpose: the log
    formatter has its own redaction, so a log-based assertion would pass for the wrong
    reason and keep passing if the engine flag were ever reverted.
    """
    org = await _make_org()
    exc = await _failing_transcript_insert(uuid.UUID(str(org["id"])))

    rendered = str(exc)
    assert TELUGU_TURN not in rendered, "raw transcript text rendered into a DB error"
    assert PHONE not in rendered, "a phone number rendered into a DB error"
    # Not just the phone-shaped run: no fragment of the turn may survive either.
    assert "అపాయింట్‌మెంట్" not in rendered
    assert "[redacted]" not in rendered, "the whole parameter dict must be withheld"


async def test_the_hidden_parameters_are_replaced_by_a_still_debuggable_error() -> None:
    """The other half of the trade: what a responder LOSES must stay small.

    Hiding the values must not hide the statement or the constraint — those are what
    actually name the bug, and a future change that swaps `hide_parameters` for
    something blunter (swallowing the error, logging only a type name) should fail
    here rather than quietly cost the on-call engineer their first clue.
    """
    org = await _make_org()
    exc = await _failing_transcript_insert(uuid.UUID(str(org["id"])))

    rendered = str(exc)
    assert "transcript_turns" in rendered, "the failing relation is still named"
    assert "speaker_enum" in rendered, "the violated constraint is still named"
    assert "INSERT INTO transcript_turns" in rendered, "the statement is still shown"
    assert "hide_parameters" in rendered, "SQLAlchemy says WHY the values are absent"
    # The values are gone from the rendering, but not from the exception object: a
    # debugger (or an explicit, redacted handler) can still reach them.
    assert exc.params is not None, "hide_parameters must not destroy the evidence"


async def test_the_error_string_a_worker_persists_carries_no_transcript() -> None:
    """`dispatch_outbox` builds `f"{type(exc).__name__}: {exc}"` and hands it to
    `mark_outbox_failed`, which writes it to `outbox_messages.last_error` — a DATABASE
    column, past every log redaction hook, and kept for as long as the row is.

    Asserted on the string that path BUILDS, before `reliability/service.py` clips it
    to 500 characters, and that is the point rather than an oversight: for this
    statement the clip happens to land just short of the parameters, so a test written
    against the truncated value passes with the leak fully present. The margin is the
    length of the SQL text — a statement a few columns shorter, or a `[:2000]` on some
    future error column, moves the transcript back inside the cut. Length is not a
    control, so the test does not treat it as one.
    """
    org = await _make_org()
    exc = await _failing_transcript_insert(uuid.UUID(str(org["id"])))

    last_error = f"{type(exc).__name__}: {exc}"
    assert TELUGU_TURN not in last_error
    assert PHONE not in last_error
    assert last_error.startswith("IntegrityError:")


# ------------------------------------------------------------- publish is callable


async def test_an_admin_publishes_an_agent_on_the_tenant_path() -> None:
    """The fix for finding 1, from the outside: a plain admin token, no impersonation
    header, and the tenant named in the URL.

    This is the request that was previously impossible — 401 without the header, 403
    with it — so a 200 here is the whole point of moving the route.
    """
    token = await _make_admin()
    org = await _make_org()
    tenant_id, agent_id = org["id"], org["agent_id"]

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_id"] == str(agent_id)
    assert body["status"] == "live"
    assert body["engine_agent_ref"], "publishing must record the engine's ref"


async def test_publishing_is_still_refused_while_impersonating() -> None:
    """D-22 is NOT what was relaxed to make the endpoint work.

    An admin who sends `X-Impersonate-Org` is still refused every mutation, this one
    included. The route became reachable by removing the need to impersonate, not by
    permitting a write inside a "view as client" session — if this ever returns 200,
    the fix was made the wrong way.
    """
    token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{org['id']}/agents/{org['agent_id']}/publish",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Impersonate-Org": str(org["slug"]),
            },
        )

    assert response.status_code == 403, response.text
    assert response.json()["kind"] == "permission"
    assert "read-only" in response.json()["detail"].lower()


async def test_a_client_token_cannot_reach_the_publish_endpoint() -> None:
    """`realm="admin"` still means admin: an owner — who holds no `agents:write` —
    cannot publish their own agent by discovering the new path. D-21's control
    boundary survived the move."""
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))
    token = await _make_member(tenant_id, role="owner")

    async with _client() as http:
        response = await http.post(
            f"/v1/admin/tenants/{tenant_id}/agents/{org['agent_id']}/publish",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])},
        )

    assert response.status_code == 401, response.text


async def test_the_old_publish_path_no_longer_exists() -> None:
    """The move is a breaking path change, stated as a test so nobody has to diff the
    OpenAPI snapshot to discover it. `/v1/agents/{agent_id}` still resolves for GET,
    so a POST to the old publish URL is a routing miss, not a permission answer."""
    paths = {route.path for route in iter_api_routes(app)}
    assert "/v1/agents/{agent_id}/publish" not in paths
    assert "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/publish" in paths
    # The reads that share this router kept their paths.
    assert {"/v1/agents", "/v1/agents/{agent_id}"} <= paths


# -------------------------------------------------------- /v1/me enforces its label


async def test_me_refuses_a_role_that_lacks_the_permission_it_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Finding 2, asserted behaviourally rather than by reading the dependency list.

    `GET /v1/me` declared `org:read` and checked nothing. Every shipped role holds
    `org:read`, so the only way to see the difference is to take it away from one —
    the same technique `authz_audit_test` uses for `admin:impersonate`. Before the
    fix this returned 200 with a full identity document; now it is a 403.
    """
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))
    token = await _make_member(tenant_id, role="owner")

    async with _client() as http:
        allowed = await http.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])},
        )

        monkeypatch.setitem(
            ROLE_PERMISSIONS, "owner", frozenset(ROLE_PERMISSIONS["owner"] - {"org:read"})
        )
        refused = await http.get(
            "/v1/me",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])},
        )

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["realm"] == "client"
    assert refused.status_code == 403, refused.text
    assert refused.json()["kind"] == "permission"


# --------------------------------------------------------- the shape, generalised


def _depends_on(route: APIRoute, target: object) -> bool:
    """Is `target` anywhere in this route's dependency tree?"""

    def _walk(dependant: Dependant) -> bool:
        if dependant.call is target:
            return True
        return any(_walk(sub) for sub in dependant.dependencies)

    return _walk(route.dependant)


def _enforced(route: APIRoute) -> list[tuple[str, str]]:
    """Every (permission, realm) pair this route actually verifies, read off the
    attributes `requires()` stamps on the dependency it returns."""
    found: list[tuple[str, str]] = []

    def _walk(dependant: Dependant) -> None:
        call = dependant.call
        permission = getattr(call, "calevate_permission", None)
        realm = getattr(call, "calevate_realm", None)
        if isinstance(permission, str) and isinstance(realm, str):
            found.append((permission, realm))
        for sub in dependant.dependencies:
            _walk(sub)

    _walk(route.dependant)
    return found


async def test_no_admin_realm_mutation_infers_its_tenant_from_the_session() -> None:
    """The general form of finding 1 — the check that would have caught it at boot.

    `tenant_of` reads `Principal.tenant_id`, and for an admin-realm mutation that
    value is unreachable by construction: without `X-Impersonate-Org` an admin
    principal has no tenant, and with it every `MUTATING_PERMISSIONS` entry is refused
    by D-22. So a route that is BOTH `realm="admin"` + mutating AND depends on
    `tenant_of` is not a route with a bug in it — it is a route that cannot be called
    at all, which is why the defect survived review and a green test suite.

    The remedy is always the same and is already the house pattern: name the tenant in
    the path and enter its scope with `tenant_session(tenant_id)`.
    """
    offenders = []
    for route in iter_api_routes(app):
        if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            continue
        if not _depends_on(route, tenant_of):
            continue
        for permission, realm in _enforced(route):
            if realm == "admin" and permission in MUTATING_PERMISSIONS:
                offenders.append(f"{sorted(route.methods or [])} {route.path} -> {permission}")
    assert not offenders, (
        "admin-realm mutations that resolve their tenant through tenant_of are "
        f"un-callable (D-22): {offenders}. Name the tenant in the path instead."
    )


async def test_the_publish_route_names_its_tenant_where_the_house_pattern_does() -> None:
    """The positive half: publish sits in the same path space as the KB approvals and
    the prompt versioning endpoints, so one admin console prefix covers all of them and
    every mutation is self-documenting in the audit log."""
    publish = next(
        route for route in iter_api_routes(app) if route.path.endswith("/agents/{agent_id}/publish")
    )
    assert publish.path.startswith("/v1/admin/tenants/{tenant_id}/")
    assert "tenant_id" in {param.name for param in publish.dependant.path_params}
    assert not _depends_on(publish, tenant_of)
    assert ("agents:write", "admin") in _enforced(publish)
