"""KB ingestion → approval → publish (FLOWS §7).

The gate is the product: a client cannot change what their agent says to callers
without a human reading it first, because the agent speaks under the client's own PE
registration. These tests pin down the gate, the versioning, and the publish ordering.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb import service
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


async def _tenant_with_published_agent() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="KB Clinic",
        slug=f"kb-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_kb_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r, status = 'live' WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id


def test_chunking_respects_paragraphs_and_the_cap() -> None:
    """A chunk cut mid-sentence becomes a sentence the agent reads aloud badly."""
    body = "\n\n".join(["Clinic hours are 9am to 8pm, Monday to Saturday."] * 30)
    chunks = service.chunk_text(body)
    assert chunks
    assert all(len(c) <= service.MAX_CHUNK_CHARS for c in chunks)
    assert all(c.strip().endswith(".") for c in chunks), "chunks end on a sentence"


def test_a_long_paragraph_is_split_on_sentence_ends() -> None:
    body = " ".join([f"Sentence number {i} explains a clinic policy." for i in range(60)])
    chunks = service.chunk_text(body)
    assert len(chunks) > 1
    assert all(len(c) <= service.MAX_CHUNK_CHARS for c in chunks)


def test_empty_content_produces_no_chunks() -> None:
    assert service.chunk_text("   \n\n  ") == []


async def test_submitted_knowledge_is_not_live_until_approved_and_published() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        result = await service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Clinic hours",
            body="We are open 9am to 8pm.\n\nSunday is closed.",
        )
    assert result["status"] == "pending_approval"

    # Publishing before approval must be refused — that IS the gate.
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as exc:
            await service.publish_source(session, tenant_id=tenant_id, source_id=result["id"])
    assert exc.value.code == "kb_not_approved"

    async with tenant_session(tenant_id) as session:
        await service.approve_source(session, source_id=result["id"], approved_by=None)
        version = await service.publish_source(session, tenant_id=tenant_id, source_id=result["id"])
    assert version == 1

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT is_active, published_at FROM kb_sources WHERE id = :i"),
                {"i": result["id"]},
            )
        ).first()
    assert row is not None and row[0] is True and row[1] is not None


async def test_approving_twice_is_a_lost_race_not_an_update() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        result = await service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="FAQ", body="Parking is free."
        )
        await service.approve_source(session, source_id=result["id"], approved_by=None)
        with pytest.raises(ProblemError) as exc:
            await service.approve_source(session, source_id=result["id"], approved_by=None)
    assert exc.value.code == "kb_not_pending"


async def test_publishing_a_new_version_archives_the_previous_one() -> None:
    """Rollback (FLOWS §7) is republishing an archived version, so exactly one version
    of a named source may be active at a time."""
    tenant_id, agent_id = await _tenant_with_published_agent()

    async with tenant_session(tenant_id) as session:
        v1 = await service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Hours", body="Open 9 to 8."
        )
        await service.approve_source(session, source_id=v1["id"], approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=v1["id"])

        v2 = await service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Hours", body="Open 10 to 9."
        )
        assert v2["version"] == 2
        await service.approve_source(session, source_id=v2["id"], approved_by=None)
        await service.publish_source(session, tenant_id=tenant_id, source_id=v2["id"])

        rows = (
            await session.execute(
                text(
                    "SELECT version, is_active, status FROM kb_sources WHERE name = 'Hours' "
                    "ORDER BY version"
                )
            )
        ).all()

    assert [r[1] for r in rows] == [False, True], "only one version may be live"
    assert rows[0][2] == "archived", "the previous version is archived, not deleted"


async def test_an_unpublished_agent_cannot_receive_knowledge() -> None:
    """Pushing a KB to an agent the engine has never seen would silently no-op."""
    created = await admin_service.create_organization(
        name="Draft Clinic",
        slug=f"draft-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    async with tenant_session(created["id"]) as session:
        submitted = await service.submit_source(
            session,
            tenant_id=created["id"],
            agent_id=created["agent_id"],
            name="Anything",
            body="Some knowledge that should not reach a draft agent.",
        )
        await service.approve_source(session, source_id=submitted["id"], approved_by=None)
        with pytest.raises(ProblemError) as exc:
            await service.publish_source(
                session, tenant_id=created["id"], source_id=submitted["id"]
            )
    assert exc.value.code == "agent_not_published"


async def test_approval_lives_on_the_admin_surface_not_behind_impersonation() -> None:
    """The deadlock this layout avoids, asserted so it cannot be reintroduced.

    An admin reaches a tenant through impersonation, and impersonation is READ-ONLY
    (D-22). If approve/publish lived on the client-realm KB router they would be
    reachable only with a tenant context that refuses mutations — permanently
    un-callable. They belong on the admin router with the tenant named in the path.
    """
    from apps.api.core.rbac import iter_api_routes
    from apps.api.main import app

    paths = {r.path for r in iter_api_routes(app)}
    for action in ("approve", "reject", "publish"):
        assert f"/v1/kb/sources/{{source_id}}/{action}" not in paths
        assert f"/v1/admin/tenants/{{tenant_id}}/kb/{{source_id}}/{action}" in paths


async def test_the_approval_queue_is_readable_through_impersonation() -> None:
    """Regression: the admin console's KB queue could never be read.

    Both KB reads were gated on `kb:write`. The queue is read through impersonation
    (D-22), impersonation refuses every MUTATING permission, and `kb:write` is one — so
    the operator's approval screen 403'd on the list it exists to show. Reading what an
    agent knows is an agent read; only submitting changes what it says.
    """
    import uuid as _uuid

    from apps.api.core.rbac import MUTATING_PERMISSIONS, iter_api_routes
    from apps.api.main import app

    assert "kb:write" in MUTATING_PERMISSIONS, "the premise: writing knowledge is a mutation"

    kb_reads = {
        (route.path, tuple(sorted(route.methods)))
        for route in iter_api_routes(app)
        if route.path.startswith("/v1/kb/") and "GET" in route.methods
    }
    assert kb_reads, "the KB read routes must still exist"
    for route in iter_api_routes(app):
        if not route.path.startswith("/v1/kb/") or "GET" not in route.methods:
            continue
        declared = (getattr(route, "openapi_extra", None) or {}).get("x-calevate-permission")
        assert declared not in MUTATING_PERMISSIONS, (
            f"{route.path} is a read gated on the mutating permission {declared!r}; "
            "an impersonating operator can never call it"
        )

    # And end to end: an operator viewing a client can see the queue.
    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        await service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Hours",
            body="The clinic is open 9am to 8pm, Monday to Saturday.",
            kind="text",
            uri=None,
            submitted_by=None,
        )
    slug = await _slug_of(tenant_id)
    admin_token = await _make_admin_token()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        listed = await http.get(
            "/v1/kb/sources?status=pending_approval",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "X-Org-Slug": slug,
                "X-Impersonate-Org": slug,
            },
        )
        submitted = await http.post(
            "/v1/kb/sources",
            headers={
                "Authorization": f"Bearer {admin_token}",
                "X-Org-Slug": slug,
                "X-Impersonate-Org": slug,
            },
            json={"agent_id": str(agent_id), "name": "Sneaky", "body": "x" * 20, "kind": "text"},
        )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 1
    assert submitted.status_code == 403, "reading is allowed; writing through impersonation is not"
    del _uuid


async def _slug_of(tenant_id: uuid.UUID) -> str:
    from apps.api.db.session import admin_session

    async with admin_session() as session:
        return str(
            (
                await session.execute(
                    text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar()
        )


async def _make_admin_token() -> str:
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id},
        )
    return f"dev:admin:{clerk_id}"
