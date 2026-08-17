"""Authorization audit: realm separation, tenancy context, permission enforcement.

Companion to `api_security_test.py` (client realm) and `admin_security_test.py` (admin
realm). Those two prove the happy paths of the auth core; this file exists for the
edges an audit found — the ones where a token, a header or a route declaration does
something other than what the docstring above it claims.

Every test here was written FIRST, run against the then-current code, and confirmed to
fail before the fix landed. Where a defect could not be fixed inside the auth core
(`core/auth.py`, `core/rbac.py`, `core/deps.py`, `core/middleware.py`,
`db/session.py`), the test is marked `xfail` with a pointer to the file that owns it —
a red suite nobody can fix is worse than a documented one.

Concurrency note: this repo's tests share one Postgres. Nothing here asserts a global
row count; everything is scoped to a run-unique tenant or user.
"""

from __future__ import annotations

import uuid
from typing import Annotated

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.core import auth as auth_module
from apps.api.core.auth import current_any, requires
from apps.api.core.context import Principal, principal_var
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import (
    MUTATING_PERMISSIONS,
    PUBLIC_PREFIXES,
    ROLE_PERMISSIONS,
    MissingPolicyError,
    assert_policy_registry_complete,
    iter_api_routes,
    permission_meta,
)
from apps.api.core.settings import runtime_config_missing_keys
from apps.api.db.session import tenant_session, untenanted_session, user_session
from apps.api.main import app
from fastapi import Depends, FastAPI
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from tests.impersonation_grant_test import view_as_headers

# Dependency aliases for the throwaway apps the registry tests build below. At module
# level because both alternatives inside a function body are lint errors (B008 on the
# `Depends()` default, N806 on a CapWords local) — and this is the repo's own idiom
# for any module that is not a `routes.py`.
OpsManager = Annotated[Principal, Depends(requires("ops:manage"))]
AgentReader = Annotated[Principal, Depends(requires("agents:read"))]
# An IDENTITY with no permission behind it — the `GET /v1/me` shape. MODULE LEVEL is
# load-bearing beyond lint: this file has `from __future__ import annotations`, so a
# route handler's annotation is a STRING that FastAPI resolves against the module
# globals. An alias defined inside a test function does not resolve, the parameter is
# dropped, and the route ends up with NO dependency at all — which the registry catches
# for a different reason ("authenticates nobody"), turning the test below green while
# testing nothing.
AnyIdentity = Annotated[Principal, Depends(current_any)]


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> str:
    """Same idiom as `admin_security_test._make_admin`."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _make_org() -> dict[str, object]:
    return await admin_service.create_organization(
        name="Authz Audit Clinic",
        slug=f"az-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> tuple[uuid.UUID, str]:
    """A user with a membership in `tenant_id`. Returns (user_id, dev bearer token)."""
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return user_id, f"dev:client:{user_id}"


def _assert_deliberate(response: Response) -> None:
    """Not a 500, and not the generic unhandled-exception body behind one.

    The property under test is that SOME code path chose the answer, rather than a
    handler being reached and raising.
    """
    body = response.json()
    assert response.status_code != 500, body
    assert response.headers["content-type"].startswith("application/problem+json")
    assert not str(body["type"]).endswith("/internal_error"), body


# --------------------------------------------------------------------------- realms
#
# SIX TESTS STOOD HERE AND ARE GONE WITH THEIR SUBJECT (D-177). They pinned the Clerk-era
# realm separation and the JWKS failure ladder: that the two realms resolved to two
# publishable keys and therefore two JWKS hosts, that a prod deployment which collapsed
# them onto one host failed `/healthz/ready`, that a `CLERK_FRONTEND_API` fallback
# resolved both, that an unknown `kid` was 401 rather than 500, and that an unreachable
# JWKS host was a 502 dependency failure rather than a bad session.
#
# NOT ONE OF THOSE PROPERTIES IS EXPRESSIBLE NOW, and that is the point rather than a gap:
# there is no signing key, no host to fetch it from, no configuration to collapse and no
# provider to be unreachable. What replaced them is `authn.sessions.token_fingerprint`
# putting the realm INSIDE the hash domain — arithmetic rather than configuration — with
# the `realm` predicate beside it as the belt to that brace. Both directions are driven in
# `tests/authn_session_test.py::test_the_realm_is_inside_the_fingerprint` and, over HTTP
# with real rows behind both credentials, in `tests/realm_boundary_test.py`.
#
# The one below is what survives of `test_local_is_untouched_by_the_realm_separation_check`
# and it survives because it still has a subject: a local box must not be told to install
# authentication keys that no longer exist.


async def test_local_readiness_asks_for_no_authentication_key_at_all() -> None:
    """Authentication configures nothing, so `/healthz/ready` may demand nothing for it.

    This used to guard `missing_realm_separation_keys` against turning every developer's
    probe red. Its subject now is the absence: a deployment cannot be misconfigured into a
    collapsed realm pair, so a readiness list naming an auth key would be naming a key
    nobody can set.
    """
    settings = auth_module.get_settings().model_copy(update={"app_env": "local", "engine": "fake"})
    missing = runtime_config_missing_keys(settings)  # type: ignore[arg-type]
    assert missing == [], missing


# ------------------------------------------------------------------- impersonation


async def test_entering_a_tenant_requires_the_impersonate_permission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The permission is checked where the ACT happens, not only where it is announced.

    It used to be checked only on the start endpoint, which minted nothing and which
    nothing forced a caller through — so the permission named after the act did not gate
    the act, and any `admin_users` row could view any tenant. It is now checked in
    `_load_admin_principal`, FIRST: before the slug lookup (so 404-vs-403 cannot be used
    to probe which client slugs exist) and before the grant (so an operator whose role
    has just lost the permission is refused even while holding a grant that has not yet
    expired — which is this design's whole revocation story).

    No grant is sent here, deliberately: the refusal must be the PERMISSION one, and the
    assertion below pins which of the two 403s this is.
    """
    token = await _make_admin(role="operator")
    org = await _make_org()

    without = frozenset(ROLE_PERMISSIONS["operator"] - {"admin:impersonate"})
    monkeypatch.setitem(ROLE_PERMISSIONS, "operator", without)

    async with _client() as http:
        response = await http.get(
            "/v1/agents",
            headers={
                "Authorization": f"Bearer {token}",
                "X-Impersonate-Org": str(org["slug"]),
            },
        )
    assert response.status_code == 403, response.text
    assert response.json()["kind"] == "permission"
    assert response.json()["type"].endswith("/forbidden"), (
        "the permission refusal must run before the grant check, or a revoked operator "
        "would be told to start a new session instead of being refused"
    )


async def test_impersonation_still_works_for_a_role_that_holds_the_permission() -> None:
    """The other half of the check above: the shipped roles are unaffected (D-22).

    With a grant, because the header alone no longer opens a tenant — see
    `tests/impersonation_grant_test.py` for that refusal and its siblings.
    """
    token = await _make_admin(role="operator")
    org = await _make_org()

    async with _client() as http:
        response = await http.get(
            "/v1/agents", headers=await view_as_headers(http, token, str(org["slug"]))
        )
    assert response.status_code == 200, response.text


# ------------------------------------------------------------- request-scoped state


async def test_the_principal_does_not_survive_the_request_that_set_it() -> None:
    """`principal_var` is request state. Auth sets it and nothing reset it, so in any
    context where requests share a task (an ASGI transport, a test client, a future
    in-process caller) the NEXT request begins holding the LAST one's identity —
    the same class of bug the transaction-local GUCs are written to avoid.
    """
    org = await _make_org()
    _user_id, token = await _make_member(uuid.UUID(str(org["id"])))

    async with _client() as http:
        response = await http.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org["slug"])},
        )
    assert response.status_code == 200, response.text
    assert principal_var.get() is None, "a resolved principal outlived its request"


# ------------------------------------------------------------ the policy registry


async def test_the_registry_catches_a_declaration_with_nothing_enforcing_it() -> None:
    """`permission_meta(...)` is a string in `openapi_extra`. Before this check, a
    route that declared one and forgot `Depends(requires(...))` sailed through the boot
    assertion — the registry read the label, not the lock.
    """
    unguarded = FastAPI()

    @unguarded.get("/v1/secrets", openapi_extra=permission_meta("admin:tenants"))
    async def _secrets() -> dict[str, str]:
        return {"nope": "nope"}

    with pytest.raises(MissingPolicyError, match="secrets"):
        assert_policy_registry_complete(unguarded)


async def test_the_registry_catches_a_declaration_that_disagrees_with_the_check() -> None:
    """Declaring `agents:read` while enforcing `ops:manage` (or the reverse, which is
    the dangerous direction) makes the generated client, the docs and the audit story
    all describe a rule the server does not apply."""
    drifted = FastAPI()

    @drifted.get("/v1/drifted", openapi_extra=permission_meta("agents:read"))
    async def _drifted(_: OpsManager) -> dict[str, str]:
        return {"ok": "ok"}

    with pytest.raises(MissingPolicyError, match="drifted"):
        assert_policy_registry_complete(drifted)


async def test_the_registry_catches_a_declaration_with_only_an_identity_behind_it() -> None:
    """The third shape of "a label with no lock", and the one the boot gate used to pass.

    Its two siblings above cover a declaration with NO auth dependency and a declaration
    that names a DIFFERENT permission than the lock. Between them sits the shape this
    repo has actually shipped: `Depends(current_any)` — which resolves an identity and
    checks no permission — beside `permission_meta("ops:manage")`. That is what `GET
    /v1/me` was, and the docstring of `test_a_declared_permission_is_a_permission_the_
    route_checks` below records it.

    `assert_policy_registry_complete` PASSED it. The clause was
    `elif enforced and declared not in enforced`, so an EMPTY enforcement set was
    exempted from the comparison rather than being its worst case — a route whose label
    says `ops:manage` and whose lock is "be signed in".

    MEASURED, not deduced. Driven against a throwaway app on the shipped code, a `staff`
    member of one tenant reached the `ops:manage` route (200, `role=staff`) and an
    `operator` reached the `platform:secrets` route (200, `role=operator`) — the two
    permissions in this table that exist precisely to be held by almost nobody. The boot
    assertion reported both routes as guarded.

    The live app has no such route (`test_a_declared_permission_is_a_permission_the_
    route_checks` sweeps it), which is why this is written against a throwaway one: the
    property under test is what the BOOT GATE refuses, not what today's table happens to
    contain. A test of the table would go green on its own the day the table is right and
    say nothing about the next route.
    """
    labelled = FastAPI()

    @labelled.get("/v1/big-red-switch", openapi_extra=permission_meta("ops:manage"))
    async def _labelled(_: AnyIdentity) -> dict[str, str]:
        return {"ok": "ok"}

    with pytest.raises(MissingPolicyError, match="big-red-switch") as raised:
        assert_policy_registry_complete(labelled)
    assert "ops:manage" in str(raised.value), "the failure must name the permission to lock"


async def test_the_registry_accepts_a_route_that_declares_and_enforces_the_same_thing() -> None:
    """The control: the new checks must not reject the shape every real route uses."""
    proper = FastAPI()

    @proper.get("/v1/proper", openapi_extra=permission_meta("agents:read"))
    async def _proper(_: AgentReader) -> dict[str, str]:
        return {"ok": "ok"}

    assert_policy_registry_complete(proper)


#: POSTs that READ, each with the reason it is not an instance of the bug the sweep
#: below hunts. The identifier is personal data, so it travels in a body rather than a
#: query string (hard rule 6) — which is a fact about the REQUEST, not about whether the
#: route writes anything. Listed here by path instead of being reclassified as mutations.
#:
#: MODULE LEVEL, and a dict rather than a set, for the same reason as its sibling
#: `impersonation_reads_test.ADMIN_CONSOLE_GETS`: an allowlist that outlives the route it
#: names is how it stops being an allowlist and becomes a hole, so the reason is stored
#: beside the path and `test_every_read_shaped_as_a_post_still_names_a_real_route`
#: requires every entry to still name a live mutating-method route.
READS_SHAPED_AS_POSTS: dict[str, str] = {
    "/v1/dnc/check": (
        "'Is this number suppressed?' — it writes nothing, and the number travels in "
        "the body because a query string lands in access logs, referrers and history"
    ),
    "/v1/compliance/messaging-consent/lookup": (
        "'May we message this number?' — the same shape and the same reason as `/v1/dnc/check`"
    ),
    "/v1/compliance/subject-export": (
        "a DPDP §11 access request: it reads one data principal's record, and the "
        "identifier that selects it is the personal data itself"
    ),
    "/v1/leads/search": (
        "the Leads table, searched. It writes nothing; the term is a POST body because it "
        "is matched against `phone_e164` and a query string is written to nginx access "
        "logs, the edge log, browser history and referrers (D-181)"
    ),
    "/v1/leads/export.csv": (
        "the SAME export as the GET on this path, with the lens in the body for the same "
        "reason as `/v1/leads/search`. It reads; `calls:read_raw` and the audit row are "
        "what gate it, and both shapes share them"
    ),
    "/v1/lead-sources/{webhook_id}/meta/setup": (
        "hands back a verify token. POST because the RESPONSE is credential-shaped, "
        "the mirror of `/v1/dnc/check` being POST because the REQUEST is — and it is "
        "what lets the route keep `org:manage` without a D-22 exemption"
    ),
    "/v1/admin/impersonation-grants": (
        "mints the short-lived, read-only D-22 view-as grant and records that authority "
        "was issued. It creates no tenant data, and `admin:impersonate` must STAY "
        "non-mutating: D-22 forbids gating a read on a mutating permission, and every "
        "read an operator makes inside a client account is gated on this one"
    ),
}


def _mutating_method_routes() -> set[str]:
    """Every non-public route the sweep below examines — the exact population an entry
    in `READS_SHAPED_AS_POSTS` can legitimately name."""
    return {
        route.path
        for route in iter_api_routes(app)
        if not any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES)
        and (route.methods or set()) & {"POST", "PUT", "PATCH", "DELETE"}
    }


async def test_every_mutating_route_is_gated_by_a_mutating_permission() -> None:
    """D-22's read-only guarantee is only as complete as `MUTATING_PERMISSIONS`.

    An impersonating admin is refused permissions in that set and allowed everything
    else, so a POST/PATCH/DELETE declared with a read permission would be a write an
    admin could perform inside a client's session — the one thing D-22 forbids.

    The exceptions are POSTs that read (`READS_SHAPED_AS_POSTS` above).
    """
    offenders = []
    for route in iter_api_routes(app):
        if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            continue
        if route.path in READS_SHAPED_AS_POSTS:
            continue
        methods = route.methods or set()
        if not methods & {"POST", "PUT", "PATCH", "DELETE"}:
            continue
        declared = (route.openapi_extra or {}).get("x-calevate-permission")
        if declared not in MUTATING_PERMISSIONS:
            offenders.append(f"{sorted(methods)} {route.path} -> {declared}")
    assert not offenders, f"mutating routes with a non-mutating permission: {offenders}"


async def test_every_read_shaped_as_a_post_still_names_a_real_route() -> None:
    """The staleness guard the sweep above shipped without, and the reason it matters.

    The exemptions are matched by STRING. Rename a route — or delete it, or drop the
    method that put it in this population — and the entry does not fail; it just stops
    matching anything, which is invisible. It stays that way until some later route
    lands on the freed path, and that route is then skipped by a rule written about a
    different endpoint years earlier: a permanent hole in D-22's read-only guarantee,
    opened by a rename nobody would think to connect to it.

    Its sibling `impersonation_reads_test.py` already carries exactly this assertion
    (`test_every_admin_console_exemption_still_names_a_real_route`) over
    `ADMIN_CONSOLE_GETS`. Two allowlists of the same kind, one guarded — the lesson had
    been learned in one file and not the other, which is the whole finding.
    """
    stale = sorted(set(READS_SHAPED_AS_POSTS) - _mutating_method_routes())
    assert not stale, (
        f"READS_SHAPED_AS_POSTS names routes that no longer exist: {stale}. Delete the "
        "entry or point it at the route's new path — left as-is it is a standing "
        "exemption for whatever lands on that path next."
    )


# --------------------------------------------------------------- tenant selection


async def test_naming_a_third_orgs_slug_is_403_even_for_a_multi_org_member() -> None:
    """`X-Org-Slug` selects among the caller's OWN memberships; it never widens them.

    The interesting case is a member of two orgs, because the resolver's other branch
    (pick the single membership) is not available to short-circuit the check — if the
    slug filter were ever dropped, this caller would silently land in org A while
    asking for org C.
    """
    org_a = await _make_org()
    org_b = await _make_org()
    org_c = await _make_org()
    user_id, token = await _make_member(uuid.UUID(str(org_a["id"])))
    async with tenant_session(uuid.UUID(str(org_b["id"]))) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": org_b["id"], "uid": user_id},
        )

    async with _client() as http:
        foreign = await http.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org_c["slug"])},
        )
        mine = await http.get(
            "/v1/agents",
            headers={"Authorization": f"Bearer {token}", "X-Org-Slug": str(org_b["slug"])},
        )
        unnamed = await http.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})

    assert foreign.status_code == 403, foreign.text
    assert foreign.json()["kind"] == "permission"
    assert mine.status_code == 200, mine.text
    assert {a["id"] for a in mine.json()} == {str(org_b["agent_id"])}
    assert unnamed.status_code == 422, "two memberships and no header must ask, not guess"
    assert unnamed.json()["type"].endswith("/org_required")


# ------------------------------------------------------------------- the dev path


async def test_dev_tokens_are_refused_in_a_non_local_settings_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole safety of `dev:<realm>:<id>` rests on this branch. Asserted for both
    realms and for every non-local environment the Settings type allows."""
    for env in ("staging", "prod"):
        settings = auth_module.get_settings().model_copy(
            update={
                "app_env": env,
            }
        )
        monkeypatch.setattr(auth_module, "get_settings", lambda s=settings: s)
        for realm in ("admin", "client"):
            with pytest.raises(ProblemError) as exc:
                await auth_module.verify_token(f"dev:{realm}:whoever", realm)  # type: ignore[arg-type]
            assert exc.value.status == 401, f"{env}/{realm} accepted a dev token"


async def test_a_dev_token_for_the_other_realm_is_refused() -> None:
    """Realm separation on the local path too — otherwise the dev harness would prove
    a property the deployed system does not have."""
    for token_realm, verify_realm in (("client", "admin"), ("admin", "client")):
        with pytest.raises(ProblemError) as exc:
            await auth_module.verify_token(f"dev:{token_realm}:whoever", verify_realm)  # type: ignore[arg-type]
        assert exc.value.status == 401


# ---------------------------------------------------------------- the GUC widenings


async def test_the_user_guc_opens_memberships_and_nothing_else() -> None:
    """Migration 8c31d0f4ab27 claims `app.user_id` widens READ by exactly one clause:
    your own membership rows and the organizations they point at. Asserted rather than
    trusted, including the rows of a DIFFERENT member of the same tenant."""
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))
    mine, _token = await _make_member(tenant_id)
    theirs, _other_token = await _make_member(tenant_id)

    async with user_session(mine) as session:
        own = (
            await session.execute(
                text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": mine}
            )
        ).scalar()
        other = (
            await session.execute(
                text("SELECT count(*) FROM memberships WHERE user_id = :u"), {"u": theirs}
            )
        ).scalar()
        orgs = (
            await session.execute(
                text("SELECT count(*) FROM organizations WHERE id = :t"), {"t": tenant_id}
            )
        ).scalar()
        leads = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()

    assert own == 1, "a user must be able to find their own memberships"
    assert other == 0, "app.user_id must not expose a co-member's row"
    assert orgs == 1, "the organizations they belong to resolve"
    assert leads == 0, "app.user_id unlocks no tenant data"


async def test_a_tenant_guc_does_not_survive_into_the_next_session_on_the_pool() -> None:
    """`set_config(..., true)` is transaction-local. If it were ever changed to the
    session-level form, a pooled connection would carry one tenant's scope into the
    next request — asserted here rather than assumed from the third argument."""
    org = await _make_org()
    tenant_id = uuid.UUID(str(org["id"]))
    async with tenant_session(tenant_id) as session:
        visible = (
            await session.execute(
                text("SELECT count(*) FROM agents WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert visible and visible >= 1

    for _ in range(5):  # exhaust the pool's first connection, whichever it is
        async with untenanted_session() as session:
            leaked = (
                await session.execute(
                    text("SELECT count(*) FROM agents WHERE tenant_id = :t"), {"t": tenant_id}
                )
            ).scalar()
            guc = (
                await session.execute(text("SELECT current_setting('app.tenant_id', true)"))
            ).scalar()
        assert leaked == 0, "a tenant's rows outlived the transaction that scoped them"
        assert not guc, "app.tenant_id is still set on a recycled connection"


# ------------------------------------------------- hostile headers reach middleware


async def test_a_non_utf8_header_byte_does_not_500_the_whole_stack() -> None:
    """HTTP header values are ISO-8859-1 on the wire, not UTF-8 (RFC 9110 §5.5), which
    is why Starlette decodes them `latin-1` everywhere. Three middlewares in this file
    decoded them as UTF-8 instead, and a middleware raising is a 500 BEFORE routing —
    on every endpoint at once, including `/healthz` and the never-shed `/hooks` surface
    that an engine calls. One byte from any client, authenticated or not.

    Reported by the CRM/ingest audit, which hit it by accident: a latin-1 byte in
    `X-Ingest-Secret` meant their request never reached the ingest code at all.
    """
    hostile = {b"X-Ingest-Secret": b"caf\xe9", b"X-Correlation-Id": b"caf\xe9"}
    async with _client() as http:
        health = await http.get("/healthz", headers=hostile)
        # No Authorization header at all, so the answer is the auth layer's own 401
        # rather than anything about how this deployment is configured.
        guarded = await http.get("/v1/leads", headers=hostile)
        hook = await http.post(f"/hooks/v1/ingest/{uuid.uuid4()}", headers=hostile, json={})

    assert health.status_code == 200, health.text
    assert guarded.status_code == 401, guarded.text
    _assert_deliberate(hook)


async def test_oversized_duplicated_and_nul_bearing_headers_get_a_deliberate_answer() -> None:
    """The rest of what a hostile client controls about a header. None of these reaches
    a handler, and none of them reaches the 500 path either.

    The token shapes are `dev:client:` ones so the assertions describe the AUTH layer and
    nothing else.

    THE FOUR ANSWER ALIKE NOW, AND THE SPLIT THAT USED TO BE HERE IS WORTH RECORDING. A
    NUL byte was always a malformed CREDENTIAL, refused at the boundary by `bearer_token`.
    The other three carried a well-formed vendor-subject token naming somebody we had no
    mirror row for, and D-124 made that a transient `503 identity_mirror_pending` — the
    token had verified, so calling it an authentication failure was the defect. D-177
    deleted the mirror: a dev token names one of OUR uuids or it does not parse, and a
    subject that parses and resolves to nobody is simply not a credential. So the honest
    answer for all four is 401, and there is no longer a state in which a verified
    credential belongs to a person we have not heard of yet.
    """
    async with _client() as http:
        huge = await http.get(
            "/v1/leads", headers={"Authorization": "Bearer dev:client:" + "a" * 64_000}
        )
        nul = await http.get("/v1/leads", headers={b"Authorization": b"Bearer dev:client:a\x00b"})
        duplicated = await http.get(
            "/v1/leads",
            headers=[
                ("Authorization", "Bearer dev:client:one"),
                ("Authorization", "Bearer dev:client:two"),
            ],
        )
        empty_org = await http.get(
            "/v1/leads", headers={"Authorization": "Bearer dev:client:nobody", "X-Org-Slug": ""}
        )

    for response in (huge, nul, duplicated, empty_org):
        _assert_deliberate(response)
        assert response.status_code == 401, response.text
        assert response.json()["kind"] == "auth", response.text


# ------------------------------------------------------------- reported, then fixed
#
# Both cases below were `xfail`s naming the file that owned the defect. Both are fixed,
# so they are ordinary tests now — the finding text has moved into the routes it
# describes, and `tests/route_shape_test.py` covers each one behaviourally as well.


async def test_a_declared_permission_is_a_permission_the_route_checks() -> None:
    """Every route's `openapi_extra` declaration names a permission the route actually
    verifies.

    This was xfailed on `GET /v1/me`, which declared `org:read` and enforced nothing —
    its only auth dependency was `Depends(current_any)`, which resolves an identity and
    checks no permission. Never exploitable (every role the DB enums allow holds
    `org:read`), but a route whose label and lock disagree is exactly what the
    strengthened registry exists to catch, and the registry could not demand the
    dependency outright while the live app still had one such route.
    """
    from apps.api.core.rbac import route_enforcement

    for route in iter_api_routes(app):
        if any(route.path.startswith(prefix) for prefix in PUBLIC_PREFIXES):
            continue
        declared = (route.openapi_extra or {}).get("x-calevate-permission")
        enforced, _identified = route_enforcement(route)
        assert declared in enforced, (
            f"{route.path} declares {declared}, enforces {sorted(enforced)}"
        )


async def test_an_admin_can_publish_an_agent() -> None:
    """Publishing an agent is a request an admin can actually make.

    This was xfailed on `POST /v1/agents/{agent_id}/publish`, which was `realm="admin"`
    but took its tenant from `Depends(db)` -> `tenant_of` -> `current_any`: without
    `X-Impersonate-Org` that falls through to the CLIENT verifier (401), and with it
    resolves an impersonating principal that D-22 refuses for `agents:write` (403). The
    endpoint was un-callable in both configurations.

    The fix names the tenant in the path, the house pattern every other admin mutation
    already used — so the assertion for the impersonating call FLIPS rather than
    relaxing: a 403 there is now the correct answer, not the defect. D-22 was never the
    thing standing in the way; inferring the tenant was.
    """
    token = await _make_admin()
    org = await _make_org()
    path = f"/v1/admin/tenants/{org['id']}/agents/{org['agent_id']}/publish"
    # The wizard mints this agent at step 1 with no prompt version, and publishing one
    # is refused by name (`agent_has_no_script`) rather than shipping a hardcoded English
    # placeholder. This case is about WHO may call the route, so the agent gets the one
    # precondition the route legitimately has.
    async with tenant_session(uuid.UUID(str(org["id"]))) as scoped:
        await prompts.write_prompt_version(
            scoped,
            tenant_id=uuid.UUID(str(org["id"])),
            agent_id=uuid.UUID(str(org["agent_id"])),
            body="[IDENTITY]\nYou are the receptionist for Authz Audit Clinic.\n",
            notes=None,
            created_by=None,
        )

    async with _client() as http:
        plain = await http.post(path, headers={"Authorization": f"Bearer {token}"})
        # A REAL grant, so the 403 below is D-22's read-only rule rather than the
        # grant check refusing before that rule is reached.
        viewing = await http.post(
            path, headers=await view_as_headers(http, token, str(org["slug"]))
        )
    assert plain.status_code == 200, plain.text
    assert plain.json()["agent_id"] == str(org["agent_id"])
    # Still read-only inside a "view as client" session (D-22) — unchanged, on purpose.
    assert viewing.status_code == 403, viewing.text
