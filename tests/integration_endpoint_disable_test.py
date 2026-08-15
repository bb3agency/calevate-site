"""`DELETE /v1/integrations/endpoints/{id}` is idempotent, and still tells nobody
whether a neighbour's id exists.

The route's CAS predicate (`active = true`) and its existence check used to be one
statement, so `rowcount == 0` conflated "no such endpoint of yours" with "already
disabled" and answered both with 404. That is a false statement about a row the client
can see in their own list, and it breaks the DELETE contract: RFC 9110 §9.2.2 requires
the side effects of N > 1 identical requests to be the same as for one, which makes a
retry after a lost response — or a second click — a success and not an error.

The fix is the shape the INBOUND twin already uses (`ingest.service.set_active`): CAS
first and unconditionally, then a single read to name which of the two zero-row facts it
was. These tests hold the four properties that shape has to keep:

1. the second disable is 204 and the endpoint stays disabled;
2. an id that never existed is still 404;
3. another tenant's id is 404 with the SAME body — no existence leak — and their
   endpoint is untouched;
4. a no-op writes no audit row, so the ledger records changes and not button presses.

CONCURRENCY: every test mints its own tenant, so this file runs beside the other suites
on the shared Postgres.
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations.routes import ENDPOINT_CREATED, ENDPOINT_DISABLED
from apps.api.main import app
from sqlalchemy import text
from tests.api_security_test import _make_tenant

# Imported from the route rather than retyped here. The disable action used to be a bare
# literal in both places, and a ledger whose writer and whose only reader spell the
# action separately is one typo away from an audit trail nobody queries.
CREATED, DISABLED = ENDPOINT_CREATED, ENDPOINT_DISABLED


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _create_endpoint(http: httpx.AsyncClient, slug: str, token: str) -> str:
    created = await http.post(
        "/v1/integrations/endpoints",
        json={"url": "https://crm.example.com/hooks/calevate", "events": ["lead.created"]},
        headers=_headers(slug, token),
    )
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


async def _active(tenant_id: uuid.UUID, endpoint_id: str) -> bool | None:
    """The stored flag, read through the tenant's OWN RLS context — so a test that
    thinks it read a neighbour's row reads nothing instead of lying."""
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT active FROM outbound_webhooks WHERE id = :id"), {"id": endpoint_id}
            )
        ).first()
    return None if row is None else bool(row[0])


async def _audit_actions(tenant_id: uuid.UUID, object_id: str) -> list[str]:
    """`audit_log` is not tenant-RLS'd (the hash chain is global), so this scopes by the
    tenant column explicitly rather than relying on a policy that does not exist."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :t AND object_id = :o "
                    "ORDER BY at"
                ),
                {"t": tenant_id, "o": object_id},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def test_disabling_twice_is_a_success_and_not_a_lie_about_the_row() -> None:
    """The reported defect: click Disable twice, be told your endpoint does not exist.

    The second response is asserted to be 204 rather than merely "not 404", because the
    contract is that the two requests are indistinguishable to the client — and the row
    is re-read afterwards so a route that "succeeded" by doing nothing at all would not
    pass either.
    """
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _create_endpoint(http, slug, token)
        first = await http.delete(
            f"/v1/integrations/endpoints/{endpoint_id}", headers=_headers(slug, token)
        )
        second = await http.delete(
            f"/v1/integrations/endpoints/{endpoint_id}", headers=_headers(slug, token)
        )

    assert first.status_code == 204, first.text
    assert second.status_code == 204, second.text
    assert await _active(tenant_id, endpoint_id) is False


async def test_an_id_that_never_existed_is_still_a_404() -> None:
    """Idempotency is not permissiveness. A typo'd id has no endpoint behind it and must
    keep saying so, in problem+json — otherwise the fix trades one false answer for
    another."""
    _, slug, token = await _make_tenant()
    stranger = uuid.uuid4()
    async with _client() as http:
        missing = await http.delete(
            f"/v1/integrations/endpoints/{stranger}", headers=_headers(slug, token)
        )

    assert missing.status_code == 404, missing.text
    assert missing.headers["content-type"].startswith("application/problem+json")
    # The identifier is never echoed INTO THE PROBLEM: `ProblemError.not_found`
    # documents that "no such row" and "another tenant's row" are deliberately one
    # answer, and a `detail` that quoted the id would start to differentiate them.
    # `instance` is the request path, so it necessarily carries the id the caller
    # themselves sent — that is an echo of the request, not a fact about our data.
    problem = missing.json()
    assert str(stranger) not in problem["detail"]
    assert str(stranger) not in problem["title"]


async def test_a_neighbours_endpoint_is_404_and_the_404_reveals_nothing() -> None:
    """Hard rule 1 at the point where the fix could have leaked it.

    Distinguishing "already inactive" from "missing" is exactly the distinction RLS
    refuses to make across tenants, so the interesting case is a REAL, ACTIVE endpoint
    belonging to someone else: the answer must be byte-identical to the answer for an id
    nobody owns, and the neighbour's endpoint must still be running afterwards.
    """
    owner_tenant, owner_slug, owner_token = await _make_tenant()
    _, other_slug, other_token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _create_endpoint(http, owner_slug, owner_token)
        trespass = await http.delete(
            f"/v1/integrations/endpoints/{endpoint_id}", headers=_headers(other_slug, other_token)
        )
        phantom = await http.delete(
            f"/v1/integrations/endpoints/{uuid.uuid4()}",
            headers=_headers(other_slug, other_token),
        )

    assert trespass.status_code == 404, trespass.text
    assert phantom.status_code == 404, phantom.text
    # Same status, same body: nothing in the response separates "exists, not yours" from
    # "does not exist". `trace_id` is per-request, so it is not part of the comparison.
    assert _comparable(trespass.json()) == _comparable(phantom.json())
    assert await _active(owner_tenant, endpoint_id) is True, "a neighbour disabled nothing"


def _comparable(problem: dict[str, object]) -> dict[str, object]:
    return {k: v for k, v in problem.items() if k not in ("trace_id", "instance")}


async def test_the_no_op_disable_writes_no_audit_row() -> None:
    """Hard rule 5's shape for the ledger: the security-relevant ACT is recorded once,
    and a click that changed nothing is not an act. An audit trail that records actions
    nobody took is worse than one that records fewer.
    """
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _create_endpoint(http, slug, token)
        path = f"/v1/integrations/endpoints/{endpoint_id}"
        await http.delete(path, headers=_headers(slug, token))
        await http.delete(path, headers=_headers(slug, token))

    # CREATED then DISABLED, and nothing for the second click. Registration is now
    # audited too — it is the act that starts lead PII leaving the tenant — so the
    # ledger holds the whole life of the endpoint rather than only its end.
    assert await _audit_actions(tenant_id, endpoint_id) == [CREATED, DISABLED]


async def test_two_concurrent_disables_both_succeed_and_audit_once() -> None:
    """The CAS the fix must not have degraded into read-then-write.

    Two disables in flight together: exactly one UPDATE matches, and the loser must
    resolve to 204 (the endpoint IS disabled) rather than to a 404 or a 409. One audit
    row, because only one of them changed anything.
    """
    tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        endpoint_id = await _create_endpoint(http, slug, token)
        both = await asyncio.gather(
            http.delete(f"/v1/integrations/endpoints/{endpoint_id}", headers=_headers(slug, token)),
            http.delete(f"/v1/integrations/endpoints/{endpoint_id}", headers=_headers(slug, token)),
        )

    assert [r.status_code for r in both] == [204, 204], [r.text for r in both]
    assert await _active(tenant_id, endpoint_id) is False
    assert await _audit_actions(tenant_id, endpoint_id) == [CREATED, DISABLED]
