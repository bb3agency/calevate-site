"""An operator's path names one client and a child object of ANOTHER client.

`tests/adversarial_pass_test.py` drives every client-space `{id}` route with a neighbour's
real ids; `tests/absent_tenant_answer_test.py` drives every `/v1/admin/tenants/{tenant_id}/…`
route with a tenant that does not exist. Neither covers the admin shape in between: a REAL
tenant B in the path and a REAL child id that belongs to tenant A
(`/v1/admin/tenants/{B}/agents/{A's agent}/publish`). An operator copies both ids off
console URLs, so the mismatch is one paste away, and a handler that looked the child up
outside `tenant_session(tenant_id)` would act on A's object while the audit row, the step-up
string and the engine workspace all name B.

Every such route must answer 404 `not_found` and write nothing. Derived from the live route
table, so a route added later is in the sweep on the day it lands.
"""

from __future__ import annotations

import re
import uuid
from typing import Any

import pytest
from apps.api.core.rbac import iter_api_routes
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.absent_tenant_answer_test import BODIES, _make_admin
from tests.adversarial_pass_test import _make_member, _make_org, _seed_one_of_everything

pytestmark = [pytest.mark.rls]

#: Path parameters that name no row a tenant owns: a registry key, not an object id.
_NOT_AN_OBJECT: frozenset[str] = frozenset({"tenant_id", "flag", "capability"})

#: Bodies for the admin routes outside `absent_tenant_answer_test`'s prefix, which this sweep
#: also drives because they name a tenant and a number in one path.
_EXTRA_BODIES: dict[str, dict[str, Any] | None] = {
    "POST /v1/admin/engine-workspaces/tenants/{tenant_id}/numbers/{number_id}/forget": {
        "confirm": True
    },
    "POST /v1/admin/engine-workspaces/tenants/{tenant_id}/numbers/{number_id}/move": None,
    "POST /v1/admin/engine-workspaces/tenants/{tenant_id}/numbers/{number_id}/release": {
        "confirm": True
    },
    "POST /v1/admin/numbers/tenants/{tenant_id}/{number_id}/engine-ref": {
        "engine_number_ref": "census-ref"
    },
    "POST /v1/admin/numbers/tenants/{tenant_id}/{number_id}/release": None,
    # Takes no body; `absent_tenant_answer_test` lists it under NOT_A_404 because its
    # step-up answers first, which this sweep echoes past.
    "DELETE /v1/admin/tenants/{tenant_id}/members/{user_id}": None,
}

_CONFIRM = re.compile(r"X-Confirm-Action: (\S+)")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _census() -> list[tuple[str, str, list[str]]]:
    found: list[tuple[str, str, list[str]]] = []
    for route in iter_api_routes(app):
        if not route.path.startswith("/v1/admin/"):
            continue
        params = [p.alias for p in route.dependant.path_params]
        if "tenant_id" not in params or not set(params) - _NOT_AN_OBJECT:
            continue
        for method in sorted((route.methods or set()) - {"HEAD", "OPTIONS"}):
            found.append((method, route.path, params))
    return sorted(found)


def _body(key: str) -> dict[str, Any] | None:
    if key in _EXTRA_BODIES:
        return _EXTRA_BODIES[key]
    return BODIES.get(key)


async def _seed_admin_kinds(tenant_id: uuid.UUID, ids: dict[str, str]) -> None:
    """The child kinds only the operator console addresses."""
    lot_id, template_id, entry_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_id) as s:
        await s.execute(
            text(
                "INSERT INTO credit_ledger "
                "(id, tenant_id, delta, reason, ref, balance_after, occurred_at, created_at) "
                "VALUES (:i, :t, 10, 'topup', :ref, 10, now(), now())"
            ),
            {"i": entry_id, "t": tenant_id, "ref": f"LOT-{entry_id.hex[:12]}"},
        )
        await s.execute(
            text(
                "INSERT INTO credit_lots (id, tenant_id, source, credits_total, "
                "credits_remaining, clear_inr_per_min, studio_inr_per_min, ledger_entry_id) "
                "VALUES (:i, :t, 'grant', 10, 10, 5, 7, :e)"
            ),
            {"i": lot_id, "t": tenant_id, "e": entry_id},
        )
        await s.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:i, :t, 'voice', 'service', "
                "'Hello from {#var#}, this is an AI assistant calling.', 'submitted', "
                "now(), now())"
            ),
            {"i": template_id, "t": tenant_id},
        )
    ids["lot_id"] = str(lot_id)
    ids["template_id"] = str(template_id)


async def _audit_rows(tenant_id: uuid.UUID) -> int:
    async with untenanted_session() as s:
        return int(
            (
                await s.execute(
                    text("SELECT count(*) FROM audit_log WHERE tenant_id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
        )


def test_the_sweep_has_routes_to_drive() -> None:
    """Non-vacuity: route discovery broken would pass the sweep over nothing."""
    assert len(_census()) >= 30, f"only {len(_census())} admin child-id routes found"


def test_every_swept_route_has_a_body() -> None:
    """A route with no entry would be driven with no body and refused 422 by validation,
    which proves nothing; the absent-tenant census already requires an entry for every
    `/v1/admin/tenants/{tenant_id}` route, so only the two other prefixes are kept here."""
    missing = [
        f"{m} {p}"
        for m, p, _ in _census()
        if f"{m} {p}" not in BODIES and f"{m} {p}" not in _EXTRA_BODIES
    ]
    assert not missing, f"add a body for: {missing}"


async def test_a_neighbours_child_id_under_another_clients_path_is_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant B in the path, tenant A's real child ids after it: 404 everywhere, and no
    audit row lands on A (B legitimately records the operator's read of its own pages)."""
    from apps.api.admin import engine_workspace_routes

    # Otherwise the engine-workspace routes refuse with `engine_workspaces_not_used`
    # before they read anything, and their entries would pass on the wrong refusal.
    monkeypatch.setattr(engine_workspace_routes, "engine_has_workspaces", lambda: True)
    # The test engine records numbers under no provider, and the number moves refuse that
    # before they read the number.
    from apps.api.campaigns import engine_numbers

    monkeypatch.setattr(engine_numbers, "engine_number_provider", lambda: "thinnest")

    org_a, org_b = await _make_org(), await _make_org()
    tenant_a, tenant_b = uuid.UUID(str(org_a["id"])), uuid.UUID(str(org_b["id"]))
    user_a, _ = await _make_member(tenant_a)
    await _make_member(tenant_b)
    ids = await _seed_one_of_everything(tenant_a, user_a)
    await _seed_admin_kinds(tenant_a, ids)
    ids["suggestion_id"] = ids.get("suggestion_id", "0123456789abcdef")
    token = await _make_admin()
    audit_a = await _audit_rows(tenant_a)

    wrong: list[str] = []
    vacuous: list[str] = []
    async with _client() as http:
        for method, template, params in _census():
            key = f"{method} {template}"
            url = template.replace("{tenant_id}", str(tenant_b))
            for name in params:
                if name == "tenant_id":
                    continue
                value = (
                    "call_timing_breakdown"
                    if name == "flag"
                    else "transfer"
                    if name == "capability"
                    else ids.get(name)
                )
                if value is None:
                    vacuous.append(f"{key}: no seeded {name}")
                    value = str(uuid.uuid4())
                url = url.replace("{" + name + "}", value)
            body = _body(key)
            headers = {"Authorization": f"Bearer {token}"}
            response = await http.request(method, url, headers=headers, json=body)
            if response.status_code == 403 and "step_up_required" in response.text:
                # The confirmation names the ids the route binds; echo it back so the route
                # is reached rather than passing on the step-up refusal.
                match = _CONFIRM.search(response.json().get("remediation", ""))
                if match is not None:
                    headers["X-Confirm-Action"] = match.group(1)
                    response = await http.request(method, url, headers=headers, json=body)
            payload = response.json() if response.content else {}
            kind = payload.get("kind") if isinstance(payload, dict) else None
            if response.status_code != 404 or kind != "not_found":
                wrong.append(f"{key} -> {response.status_code} {response.text[:200]}")

    assert not wrong, (
        "an operator naming client B in the path reached client A's object, or was refused "
        f"for something other than the object not being there: {wrong}"
    )
    assert await _audit_rows(tenant_a) == audit_a, "an act on A's object was recorded"
    assert not vacuous, f"the sweep has no real id for: {vacuous}"
