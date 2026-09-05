"""Cross-tenant isolation of `idempotency_records` (hard rule 1), which is NOT a policy.

Every other tenant-scoped table in this schema answers hard rule 1 the same way: a
`tenant_id` column and a FORCEd `tenant_isolation` policy, swept behaviourally by
`tests/rls_sweep_test.py`. `idempotency_records` cannot — the replay happens BEFORE any
tenant-scoped query runs, and the row is claimed by a request that has not yet reached a
`tenant_session`. So its isolation lives somewhere else entirely: inside the LOOKUP KEY.

`reliability.scope_key(tenant_id=..., user_id=...)` is an HMAC fingerprint of the
principal, and it is the first column of the UNIQUE key every claim matches on
(`scope_key, route, method, idempotency_key`). Two tenants replaying the same
`Idempotency-Key` therefore address two different rows and never meet.

WHY THIS FILE EXISTS. That property had no behavioural test. `scripts/check_idempotency_
scope.py` is excellent and proves something adjacent but different: that `scope_key` keeps
its typed signature and stays the only producer of a scope, so no call site can compute a
scope from a header or a client address (D-175 — the reference platform whose scope fell
back to `request.ip` behind a CDN). That is a check on the INPUTS. Nothing asserted the
OUTCOME: that tenant B, replaying tenant A's key, is handed `fresh` and not A's stored
`response_payload`. The consequence if it ever regressed is not a subtle one — it is
caller B receiving caller A's lead, through a mechanism nobody thinks of as a read path
and that no RLS policy is in a position to stop.

`apps/api/db/registry.RLS_EXEMPT_TENANT_COLUMNS["idempotency_records"]` now states this
isolation-by-lookup-key in words, because a reviewer reading that dict is entitled to
learn how a table holding a replayed response body is scoped. This file is the assertion
under it: the registry entry makes the claim, and a claim with no test is the shape hard
rule 1 exists to refuse.

Run: uv run pytest tests/idempotency_cross_tenant_test.py -q
Requires the local Postgres (docker compose up -d) with migrations applied.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.session import untenanted_session
from apps.api.reliability import service as rel
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

#: One run's namespace, so a parallel suite's rows are never this suite's rows.
RUN = uuid.uuid4().hex[:8]
ROUTE = f"/v1/leads/cross-tenant-{RUN}"

TENANT_A = UUID("aaaaaaaa-0000-4000-8000-00000000000a")
TENANT_B = UUID("bbbbbbbb-0000-4000-8000-00000000000b")
USER_A = UUID("aaaaaaaa-1111-4000-8000-00000000000a")


def _scopes() -> tuple[str, str]:
    return (
        rel.scope_key(tenant_id=TENANT_A, user_id=USER_A),
        rel.scope_key(tenant_id=TENANT_B, user_id=USER_A),
    )


@pytest.fixture(autouse=True)
async def _clean_up_after_ourselves() -> Any:
    yield
    scope_a, scope_b = _scopes()
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM idempotency_records WHERE route = :r AND scope_key = ANY(:s)"),
            {"r": ROUTE, "s": [scope_a, scope_b]},
        )


async def test_two_tenants_sharing_one_idempotency_key_never_share_a_response() -> None:
    """THE ONE THAT MATTERS. Same key, same route, same body, different tenant.

    Tenant A completes the request and its response is stored. Tenant B then sends the
    identical `Idempotency-Key`. B must be told to do the work itself — a `replay` here
    would hand B the lead A just created, and `response_payload` is the evidence: the
    assertion checks the BODY and not only the state, because a `fresh` claim carrying a
    populated payload would be the same leak wearing the right label.
    """
    scope_a, scope_b = _scopes()
    shared_key = f"shared-{RUN}"
    # Identical bodies on purpose: a differing hash would raise `idempotency_key_reused`
    # and the test would pass for the wrong reason, proving only that the bodies differ.
    body = rel.body_hash({"phone": "+919000000000"})

    async with untenanted_session() as session:
        first = await rel.claim_idempotency(
            session, scope=scope_a, route=ROUTE, method="POST", key=shared_key, request_hash=body
        )
        assert first.state == "fresh"
        await rel.complete_idempotency(
            session,
            record_id=first.record_id,
            response_status=201,
            response_payload={"lead_id": "tenant-a-secret"},
        )

    async with untenanted_session() as session:
        second = await rel.claim_idempotency(
            session, scope=scope_b, route=ROUTE, method="POST", key=shared_key, request_hash=body
        )

    assert second.state == "fresh", "tenant B was served tenant A's idempotency record"
    assert second.record_id != first.record_id
    assert second.response_payload is None, (
        "tenant B's claim carries tenant A's stored response body — this is a "
        "cross-tenant read through the replay path, which no RLS policy can stop"
    )


async def test_the_same_tenant_still_replays() -> None:
    """The control, and it is not optional: a scope that isolated by being BROKEN — a
    fingerprint that never collided because it was random per call — would pass the test
    above and silently retire idempotency itself, re-executing every retry. On
    `POST /v1/leads/{id}/call` that is a second real phone call to a real person.
    """
    scope_a, _ = _scopes()
    same_key = f"same-tenant-{RUN}"
    body = rel.body_hash({"phone": "+919000000001"})

    async with untenanted_session() as session:
        first = await rel.claim_idempotency(
            session, scope=scope_a, route=ROUTE, method="POST", key=same_key, request_hash=body
        )
        await rel.complete_idempotency(
            session, record_id=first.record_id, response_status=201, response_payload={"n": 1}
        )

    async with untenanted_session() as session:
        second = await rel.claim_idempotency(
            session, scope=scope_a, route=ROUTE, method="POST", key=same_key, request_hash=body
        )

    assert second.state == "replay"
    assert second.response_payload == {"n": 1}


async def test_two_tenants_get_two_rows_not_one() -> None:
    """The storage-level statement of the same fact, asserted against the table rather
    than through the API — so a future `claim_idempotency` that started collapsing the
    two rows (an `ON CONFLICT` widened to ignore `scope_key`, say) fails here even if it
    kept returning the right states.
    """
    scope_a, scope_b = _scopes()
    shared_key = f"rows-{RUN}"
    body = rel.body_hash({"phone": "+919000000002"})

    async with untenanted_session() as session:
        for scope in (scope_a, scope_b):
            await rel.claim_idempotency(
                session, scope=scope, route=ROUTE, method="POST", key=shared_key, request_hash=body
            )

    async with untenanted_session() as session:
        scopes = (
            (
                await session.execute(
                    text(
                        "SELECT scope_key FROM idempotency_records "
                        "WHERE route = :r AND idempotency_key = :k ORDER BY scope_key"
                    ),
                    {"r": ROUTE, "k": shared_key},
                )
            )
            .scalars()
            .all()
        )

    assert sorted(scopes) == sorted({scope_a, scope_b}), (
        "one Idempotency-Key from two tenants must occupy two rows; collapsing them is "
        "how one tenant's stored response becomes reachable by the other"
    )


async def test_a_scope_does_not_leak_the_raw_tenant_id() -> None:
    """BACKEND-PATTERNS §4 forbids storing the raw ids, which is why the scope is an
    HMAC rather than `f"{tenant_id}:{user_id}"`. Pinned behaviourally because the
    pseudonymity is the reason the column is safe to hold at all, and a well-meaning
    refactor toward a readable key would be invisible in a diff review.
    """
    scope_a, scope_b = _scopes()

    assert str(TENANT_A) not in scope_a
    assert TENANT_A.hex not in scope_a
    assert str(USER_A) not in scope_a
    assert scope_a != scope_b
