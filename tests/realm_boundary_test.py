"""The boundary between the two realms, driven with VALID credentials of the wrong kind.

`tests/authz_audit_test.py` and `tests/impersonation_grant_test.py` already own the
absent credential and the malformed grant. This file exists for the case those cannot
reach: a token that verifies perfectly, a grant signed with the real key and in date,
presented at a door they were not minted for. A 401 for a caller who sent nothing proves
only that SOMETHING is there; the property D-22 and TRD §11 actually claim is that a
real client session cannot become an admin one, that a real operator session cannot
become a client one, and that a real view-as session cannot write.

What is asserted here, in the order a reviewer should read it:

  1. TOKEN CONFUSION over HTTP, both directions, with real rows behind both tokens —
     including a client token accompanied by a genuine grant somebody else minted.
  2. THE BLANK HEADER. `X-Impersonate-Org: ` used to be neither absent nor present: it
     produced `impersonating=True` with no permission check, no grant and no audit row,
     and answered a plain admin console request with "Impersonation is read-only".
  3. THE MUTATION SWEEP. Every route in the live table that declares a mutating
     permission, DRIVEN under a real grant, and required to refuse. Reading the
     decorator is what `tests/authz_audit_test.py::
     test_every_mutating_route_is_gated_by_a_mutating_permission` does; this drives them.
  4. THE DEV TOKEN's second condition. `authz_audit_test` pins the `app_env` half of the
     AND; the Clerk-secret half had nothing behind it.
  5. THE LIFECYCLE ASYMMETRY. A churned tenant locks its own members out and stays open
     to an audited operator — a deliberate difference, pinned so it stays one.

Concurrency: this repo's tests share one Postgres. Everything below is scoped to a
run-unique tenant or user, and nothing asserts a global row count.
"""

from __future__ import annotations

import re
import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.core import auth as auth_module
from apps.api.core.rbac import MUTATING_PERMISSIONS, PUBLIC_PREFIXES, iter_api_routes
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.impersonation_grant_test import view_as_headers

#: Every `{param}` in a route template. Substituted with a uuid so the sweep below can
#: address a route it has no real object for — the point is which dependency answers
#: first, and an id that resolves to nothing is enough to find out.
_PATH_PARAM = re.compile(r"\{[^}]+\}")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> tuple[uuid.UUID, str]:
    """(admin_users.id, dev bearer token). Same idiom as the other admin suites."""
    admin_id = uuid.uuid4()
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "cid": clerk_id, "role": role},
        )
    return admin_id, f"dev:admin:{clerk_id}"


async def _make_org(status: str = "active") -> dict[str, object]:
    org = await admin_service.create_organization(
        name="Realm Boundary Clinic",
        slug=f"rb-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    if status != "active":
        # Straight to the column: `admin/routes.py`'s lifecycle endpoint is a different
        # module's surface with its own transition rules, and this file is about who may
        # READ a tenant in that state, not about how it got there.
        # The tenant's OWN session: `organizations` is RLS'd, and neither the
        # untenanted session nor `app.admin` (USING only — `tests/admin_security_test.py
        # ::test_admin_guc_grants_no_writes`) can update a row of it. An UPDATE that
        # silently matched zero rows would have made every assertion below describe an
        # `active` tenant while claiming to describe a churned one.
        async with tenant_session(uuid.UUID(str(org["id"]))) as session:
            updated = await session.execute(
                text("UPDATE organizations SET status = :s WHERE id = :i"),
                {"s": status, "i": org["id"]},
            )
            assert updated.rowcount == 1, "the lifecycle change did not land"
    return org


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> tuple[uuid.UUID, str]:
    """A real `users` row with a real membership. Returns (user_id, dev bearer token)."""
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
    return user_id, f"dev:client:{clerk_id}"


# ------------------------------------------------------------------ token confusion


async def test_a_working_client_session_is_still_nobody_on_the_admin_console() -> None:
    """A VALID client token — real user, real membership, reads its own tenant fine —
    presented at the operator console.

    The interesting half is the control: the same token succeeds on its own realm in the
    same test. Without it a 401 here would be satisfied by a token that was simply
    broken, which is the shape of assertion this file exists to avoid.

    The refusal is 401 and not 403 on purpose. 403 would say "you are authenticated
    here, you just lack the role", and a support person reading that would go looking
    for an `admin_users` row to add. The truth is that this credential is not an admin
    credential at all: the two realms are two Clerk applications with two JWKS hosts
    (TRD §11, D-37), so the token never gets as far as a role.
    """
    org = await _make_org()
    _user_id, token = await _make_member(uuid.UUID(str(org["id"])))
    auth = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        own_realm = await http.get("/v1/agents", headers={**auth, "X-Org-Slug": str(org["slug"])})
        directory = await http.get("/v1/admin/tenants", headers=auth)
        switches = await http.get("/v1/ops/platform", headers=auth)

    assert own_realm.status_code == 200, "the control: this token works on its own realm"
    for name, response in (("directory", directory), ("switches", switches)):
        assert response.status_code == 401, f"{name}: {response.text}"
        assert response.json()["kind"] == "auth", (
            f"{name} answered as an AUTHORIZATION failure, which tells a support person "
            "to grant this account a role rather than to use the other console"
        )


async def test_a_working_operator_session_is_still_nobody_on_a_client_surface() -> None:
    """The mirror, and the direction that matters more: an admin token is the one with
    a role table behind it, so a client route that accepted it would be reading
    `ROLE_PERMISSIONS['superadmin']` for a tenant nobody granted.

    Again with a control — the same token opens the admin console in the same test.
    """
    _admin_id, token = await _make_admin()
    auth = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        own_realm = await http.get("/v1/admin/tenants", headers=auth)
        leads = await http.get("/v1/leads", headers=auth)
        me = await http.get("/v1/me", headers=auth)

    assert own_realm.status_code == 200, "the control: this token works on its own realm"
    for name, response in (("leads", leads), ("me", me)):
        assert response.status_code == 401, f"{name}: {response.text}"
        assert response.json()["kind"] == "auth", name


async def test_a_genuine_grant_does_not_travel_on_somebody_elses_token() -> None:
    """A grant minted through the real route, for the real tenant, in date and signed
    with the real key — carried by a CLIENT token.

    This is the "valid grant, wrong credential" case, and it is the one the module
    docstring's revocation argument rests on: the grant is not a credential, so pairing
    it with a session that never passed the admin verifier must buy nothing. It is
    refused by AUTHENTICATION (401), before `verify_grant` is ever consulted — which is
    the right order, because a client token has no `admin_users.id` for the actor
    binding to be compared against in the first place.
    """
    org = await _make_org()
    _admin_id, admin_token = await _make_admin()
    _user_id, client_token = await _make_member(uuid.UUID(str(org["id"])))

    async with _client() as http:
        stolen = await view_as_headers(http, admin_token, str(org["slug"]))
        assert (await http.get("/v1/agents", headers=stolen)).status_code == 200, (
            "the control: the grant genuinely opens this tenant for the operator it names"
        )
        borrowed = await http.get(
            "/v1/agents", headers={**stolen, "Authorization": f"Bearer {client_token}"}
        )

    assert borrowed.status_code == 401, borrowed.text
    assert borrowed.json()["kind"] == "auth", borrowed.text


# ------------------------------------------------------------------- the blank header


async def test_a_blank_impersonate_header_is_a_request_defect_not_a_view_as_session() -> None:
    """`X-Impersonate-Org: ` used to be a third state nobody designed.

    It was not "absent" — `impersonating` was set from `header is not None`, so the
    principal claimed to be inside a tenant. And it was not "present" — the slug was
    falsy, so `admin:impersonate` was never checked, no grant was demanded and no
    `admin.impersonation_read` row was written. What came out was an operator on the
    ADMIN CONSOLE being told "Impersonation is read-only. Perform this action from the
    admin console", and a `Principal.impersonating` that no longer meant "a grant was
    verified and this read was audited" — the one thing every mutating dependency in
    the app reads it for.

    All three header shapes are driven here, so the test pins a DISTINCTION rather than
    a status code: absent works, blank is a 422 about the header, and a real view-as
    session is the read-only 403.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()
    auth = {"Authorization": f"Bearer {token}"}
    body = {
        "name": "Blank Header Clinic",
        "slug": f"bh-{uuid.uuid4().hex[:8]}",
        "vertical_template": "clinic",
        "language": "te-IN",
    }

    async with _client() as http:
        absent = await http.post("/v1/admin/tenants", headers=auth, json=body)
        blank = await http.post(
            "/v1/admin/tenants", headers={**auth, "X-Impersonate-Org": ""}, json=body
        )
        viewing = await http.post(
            "/v1/admin/tenants",
            headers=await view_as_headers(http, token, str(org["slug"])),
            json=body,
        )

    assert absent.status_code == 201, absent.text

    assert blank.status_code == 422, blank.text
    assert blank.json()["type"].endswith("/impersonate_org_blank"), blank.text
    assert "X-Impersonate-Org" in blank.json()["remediation"], (
        "the operator must be told which header to fix, not that they may not act"
    )

    assert viewing.status_code == 403, viewing.text
    assert "read-only" in viewing.json()["detail"].lower(), viewing.text


async def test_a_whitespace_slug_is_not_a_deleted_client() -> None:
    """` ` reached the directory lookup and answered "Organization not found".

    That is a 404 about a CLIENT for a defect in a HEADER, and it is the answer most
    likely to be believed: an operator told a client's account does not exist opens an
    incident about a deleted tenant. Stripped and refused as blank instead.
    """
    _admin_id, token = await _make_admin()

    async with _client() as http:
        response = await http.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}", "X-Impersonate-Org": "   \t "},
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/impersonate_org_blank"), response.text


async def test_the_impersonating_flag_is_never_true_without_a_resolved_tenant() -> None:
    """The invariant the blank header broke, asserted on the function that decides it.

    `Principal.impersonating` is read by `requires()` to refuse every mutation, by
    `Principal.can_mutate`, and by the console to grey out controls. All of that assumes
    the flag means "this principal entered a tenant through the audited path". It is now
    derived from `tenant_id`, which is assigned on exactly one branch — the one that has
    already checked `admin:impersonate`, resolved the slug and verified the grant — so
    the two cannot disagree.

    DRIVEN AT THE FUNCTION, not through a request, and deliberately including the empty
    slug that `_impersonation_slug` now refuses at the edge. The two guards are
    independent: the header normalisation stops the blank value arriving, and this makes
    `_load_admin_principal` self-consistent for any slug it is handed, so neither one is
    load-bearing alone. A test that only went through HTTP would be satisfied by the
    edge guard and would say nothing about the flag's own definition.
    """
    _admin_id, token = await _make_admin()
    clerk_id = token.removeprefix("dev:admin:")
    verified = auth_module.VerifiedToken(clerk_user_id=clerk_id, email=None, realm="admin")

    for slug in (None, ""):
        principal = await auth_module._load_admin_principal(verified, slug)
        assert principal.tenant_id is None, slug
        assert principal.impersonating is False, (
            f"a slug of {slug!r} resolved no tenant, so nothing was checked, granted or "
            "audited — a principal claiming impersonation here means the flag no longer "
            "implies the audited entry every mutating dependency trusts it for"
        )
        assert principal.can_mutate is True, "an operator who entered no tenant is themselves"


# --------------------------------------------------------- the read-only rule, DRIVEN


def _mutating_routes() -> list[tuple[str, str, str]]:
    """(method, template, declared permission) for every mutating-permission route."""
    found: list[tuple[str, str, str]] = []
    for route in iter_api_routes(app):
        if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            continue
        declared = (route.openapi_extra or {}).get("x-calevate-permission")
        if declared not in MUTATING_PERMISSIONS:
            continue
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            found.append((method, route.path, str(declared)))
    return found


async def test_no_route_declaring_a_mutating_permission_is_reachable_while_impersonating() -> None:
    """D-22's read-only rule, driven over every route the registry knows about.

    THE STATIC TEST IS NOT THIS TEST. `authz_audit_test` reads each route's declaration
    and requires it to be a mutating permission; that assumes `requires()` is the only
    thing between a declaration and a handler, and assumes it is wired on every one of
    them. This sends the request. Any route whose dependency graph lets a body, a path
    parameter or a router-level dependency answer before the read-only check shows up
    here as a status that is not a refusal.

    TWO REFUSALS ARE ACCEPTED, and the difference is recorded rather than smoothed over:

      - `impersonation_read_only` (the D-22 rule itself) for every route an operator's
        token can reach at all;
      - `impersonation_not_available_here` for the handful declared `realm="client"`.
        Those verify against the CLIENT application's JWKS, which an operator's token
        will never satisfy, so the rule that refuses them is realm separation and not
        D-22. They are refused either way; saying which is what keeps a support person
        off the wrong desk.

    Nothing else passes — in particular a 2xx, a 404 (the handler ran and looked for the
    object) or a 422 (the body was validated first) is a failure, because each of them
    means the request got past the guard before being stopped by something incidental.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()
    routes = _mutating_routes()
    # Non-vacuity: if route discovery breaks, this file must go red rather than green.
    assert len(routes) >= 40, f"only {len(routes)} mutating routes found — discovery is broken"

    offenders: list[str] = []
    read_only: list[str] = []
    wrong_realm: list[str] = []
    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        for method, template, _permission in routes:
            path = _PATH_PARAM.sub(lambda _: str(uuid.uuid4()), template)
            response = await http.request(method, path, headers=headers, json={})
            # A SUCCESSFUL response is not problem+json and need not be an object at
            # all — `POST /v1/leads/bulk` answers a list. Reading `type` off it blindly
            # turned the one outcome this test exists to report into an AttributeError
            # inside the loop, which names no route.
            body = response.json()
            code = (
                str(body.get("type", "")).rsplit("/", 1)[-1] if isinstance(body, dict) else "<ok>"
            )
            if response.status_code == 403 and code == "forbidden":
                read_only.append(f"{method} {template}")
            elif response.status_code == 403 and code == "impersonation_not_available_here":
                wrong_realm.append(f"{method} {template}")
            else:
                offenders.append(f"{method} {template} -> {response.status_code} {code}")

    assert not offenders, (
        "a view-as session reached these routes without meeting D-22's read-only rule "
        f"or the realm boundary: {offenders}"
    )
    assert len(read_only) >= 40, (
        f"only {len(read_only)} routes were refused by the read-only rule itself; the "
        f"rest answered the realm boundary ({wrong_realm}) — if that set has grown, D-22 "
        "is being enforced by an accident of which realm a route declares"
    )


async def test_a_client_realm_route_says_view_as_rather_than_bad_token() -> None:
    """The three routes the sweep classifies as `wrong_realm`, named.

    Each is a client-realm mutation an operator can reach from a client's screen and
    each used to answer "This token is not valid for this realm" — a sentence about the
    CREDENTIAL, handed to somebody whose credential is fine and whose session is simply
    the wrong kind for this surface. It reads as a broken sign-in, and a broken sign-in
    is escalated to whoever owns Clerk rather than to whoever owns the console.

    Asserted with a real grant so the answer cannot be coming from the grant check.
    """
    _admin_id, token = await _make_admin()
    org = await _make_org()

    async with _client() as http:
        headers = await view_as_headers(http, token, str(org["slug"]))
        responses = {
            "caps": await http.put("/v1/billing/caps", headers=headers, json={}),
            "topup": await http.post("/v1/billing/topups/intent", headers=headers, json={}),
            "alerts": await http.post("/v1/compliance/whatsapp-alerts", headers=headers, json={}),
        }

    for name, response in responses.items():
        assert response.status_code == 403, f"{name}: {response.text}"
        body = response.json()
        assert body["type"].endswith("/impersonation_not_available_here"), f"{name}: {body}"
        assert body["kind"] == "permission", f"{name}: {body}"
        assert body["remediation"], f"{name}: a refusal an operator meets must say what to do"


# ------------------------------------------------------- the dev token's OTHER half


async def test_a_deployment_with_a_clerk_secret_refuses_dev_tokens_even_in_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_verify_dev_token` requires `app_env == "local"` AND no Clerk secret for the
    realm. `tests/app_env_required_test.py` owns the first condition end to end; the
    second had nothing behind it.

    It is the condition that protects a developer who has pointed their local machine at
    a real Clerk application — the moment they do, `dev:admin:<anyone>` must stop being
    a way to become any operator whose Clerk id they can guess, because now there are
    real operators to name. Asserted per realm, because the secrets are per realm and
    configuring one must not disarm the other's gate.
    """
    for realm, configured, other in (
        ("admin", "clerk_admin_secret_key", "clerk_client_secret_key"),
        ("client", "clerk_client_secret_key", "clerk_admin_secret_key"),
    ):
        settings = auth_module.get_settings().model_copy(
            update={"app_env": "local", configured: "sk_test_configured", other: None}
        )
        monkeypatch.setattr(auth_module, "get_settings", lambda s=settings: s)

        assert auth_module._verify_dev_token(f"dev:{realm}:anyone", realm) is None, (  # type: ignore[arg-type]
            f"a configured {configured} must disarm the dev path on the {realm} realm"
        )
        # And the OTHER realm, whose secret is still absent, keeps working — so this
        # pins a per-realm condition rather than a global kill switch.
        sibling = "client" if realm == "admin" else "admin"
        assert auth_module._verify_dev_token(f"dev:{sibling}:anyone", sibling) is not None  # type: ignore[arg-type]


# ------------------------------------------------------------ the lifecycle asymmetry


async def test_a_churned_tenant_locks_out_its_members_and_stays_open_to_an_operator() -> None:
    """A DELIBERATE asymmetry, pinned so nobody has to guess whether it is one.

    `_load_client_principal` filters `o.status <> 'churned'`: the client has left, and
    their people no longer have an account to sign in to. `_load_admin_principal` does
    NOT filter on status — it filters `deleted_at IS NULL` only — so an operator can
    still enter. That is the correct direction and the reason is regulatory rather than
    commercial: the questions that arrive AFTER a client leaves are a DPDP erasure
    request to verify, a final invoice to explain and a complaint to answer, and none of
    them is answerable from outside the tenant.

    What makes it safe is that nothing about the entry is quieter than usual: the
    operator still needs `admin:impersonate`, still needs a grant bound to this tenant,
    still writes `admin.impersonation_started` and `admin.impersonation_read`, and still
    cannot write. A soft-DELETED tenant is the different case and is refused by the slug
    lookup — `tests/impersonation_grant_test.py` covers that door.
    """
    org = await _make_org(status="churned")
    tenant_id = uuid.UUID(str(org["id"]))
    _user_id, client_token = await _make_member(tenant_id)
    _admin_id, admin_token = await _make_admin()

    async with _client() as http:
        member = await http.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {client_token}", "X-Org-Slug": str(org["slug"])},
        )
        operator = await http.get(
            "/v1/agents", headers=await view_as_headers(http, admin_token, str(org["slug"]))
        )

    assert member.status_code == 403, member.text
    assert member.json()["kind"] == "permission", member.text
    assert operator.status_code == 200, operator.text

    async with untenanted_session() as session:
        started = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE tenant_id = :t AND action = 'admin.impersonation_started'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
        read = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log "
                    "WHERE tenant_id = :t AND action = 'admin.impersonation_read'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert started == 1, "entering a departed client is exactly as recorded as any other"
    assert read == 1


async def test_a_suspended_tenant_is_reachable_by_an_operator_and_by_its_own_owner() -> None:
    """`suspended` is NOT `churned`, and the difference is asserted rather than assumed.

    Suspension is a state a client comes back from — a payment problem, a compliance
    hold — so their own people keep their sign-in and see the account explaining itself.
    Only `churned` (terminal) and `deleted_at` remove that. This test exists because the
    two statuses sit side by side in one CHECK constraint and a future `IN (...)` that
    lumped them together would silently lock out every suspended client's owner.
    """
    org = await _make_org(status="suspended")
    _user_id, client_token = await _make_member(uuid.UUID(str(org["id"])))
    _admin_id, admin_token = await _make_admin()

    async with _client() as http:
        member = await http.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {client_token}", "X-Org-Slug": str(org["slug"])},
        )
        operator = await http.get(
            "/v1/agents", headers=await view_as_headers(http, admin_token, str(org["slug"]))
        )

    assert member.status_code == 200, member.text
    assert operator.status_code == 200, operator.text


# --------------------------------------------------------------- the refusal's shape


async def test_every_refusal_on_this_boundary_is_problem_json_with_a_stable_code() -> None:
    """Errors are part of the interface (BACKEND-PATTERNS §3), and this boundary's
    refusals are what a console switches on.

    Four different wrong things, four different machine codes, all `application/
    problem+json` and none of them a 500. The codes are pinned because the console
    branches on them: `impersonation_grant_expired` is re-minted silently, and
    `impersonate_org_blank` is a bug in the caller that must be shown.
    """
    org = await _make_org()
    _admin_id, admin_token = await _make_admin()
    _user_id, client_token = await _make_member(uuid.UUID(str(org["id"])))

    async with _client() as http:
        cases = {
            "unauthorized": await http.get(
                "/v1/admin/tenants", headers={"Authorization": f"Bearer {client_token}"}
            ),
            "impersonate_org_blank": await http.get(
                "/v1/agents",
                headers={"Authorization": f"Bearer {admin_token}", "X-Impersonate-Org": ""},
            ),
            "impersonation_grant_required": await http.get(
                "/v1/agents",
                headers={
                    "Authorization": f"Bearer {admin_token}",
                    "X-Impersonate-Org": str(org["slug"]),
                },
            ),
            "impersonation_not_available_here": await http.put(
                "/v1/billing/caps",
                headers=await view_as_headers(http, admin_token, str(org["slug"])),
                json={},
            ),
        }

    for expected, response in cases.items():
        assert response.status_code < 500, f"{expected}: {response.text}"
        assert response.headers["content-type"].startswith("application/problem+json"), expected
        body = response.json()
        assert body["type"].endswith(f"/{expected}"), f"expected {expected}, got {body['type']}"
        assert body["detail"], expected
        assert "Traceback" not in body["detail"] and "sqlalchemy" not in body["detail"].lower()
