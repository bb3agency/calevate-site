"""D-658: what the account's own people add reaches the agent with no human step.

The founder: "I want it to be reaching the agent as soon as it is added without waiting for
anyone's approval at all." Driven through the route, the outbox promise, the publish job and
the sweep, because each half passes on its own and the feature is the seam between them.
What must NOT change is asserted beside it: an operator's flow still waits for an admin, and
an older version never overwrites a newer one because a queue ran them out of order.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.kb import service, uploads
from apps.api.main import app
from apps.workers import kb_gloss, kb_ingest
from calevate_shared.document_ingest import ExtractedText
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_workflow_test import _tenant_with_published_agent

BODY = "Consultation is 500 rupees. Follow-up visits within a week are free."


async def _member(tenant_id: uuid.UUID, role: str = "owner") -> uuid.UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id.hex[:12]}@example.test"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return user_id


async def _slug(tenant_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str((await session.execute(text("SELECT slug FROM organizations"))).scalar())


async def _source(tenant_id: uuid.UUID, source_id: object) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT status, is_active, published_at, approved_by, submitted_by "
                    "FROM kb_sources WHERE id = :s"
                ),
                {"s": source_id},
            )
        ).one()


async def _publish_jobs(source_id: object) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'source_id' = :sid"
                    ),
                    {"job": service.PUBLISH_KB_SOURCE_JOB, "sid": str(source_id)},
                )
            ).scalar()
        )


async def _publish(tenant_id: uuid.UUID, source_id: object) -> str:
    return await kb_ingest.publish_kb_source(
        {"job_try": 1}, {"tenant_id": str(tenant_id), "source_id": str(source_id)}
    )


async def _member_submission(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, user_id: uuid.UUID, *, body: str = BODY
) -> dict[str, Any]:
    async with tenant_session(tenant_id) as session:
        return await service.submit_source(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Fees",
            body=body,
            submitted_by=user_id,
            auto_approve=True,
        )


async def test_an_owners_typed_knowledge_goes_live_with_nobody_approving_it() -> None:
    """THE FEATURE, end to end: route -> approved + promised publish -> job -> live."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    owner = await _member(tenant_id, "owner")
    headers = {"Authorization": f"Bearer dev:client:{owner}", "X-Org-Slug": await _slug(tenant_id)}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as http:
        created = await http.post(
            "/v1/kb/sources",
            headers=headers,
            json={"agent_id": str(agent_id), "name": "Fees", "body": BODY, "kind": "text"},
        )
    assert created.status_code == 201, created.text
    assert created.json()["status"] == "approved"
    source_id = created.json()["id"]

    row = await _source(tenant_id, source_id)
    assert row.approved_by == owner == row.submitted_by, "an auto-approval names who cleared it"
    assert row.is_active is False, "nothing is live until the publish job has run"
    assert await _publish_jobs(source_id) == 1, "the publish must be promised in the same commit"

    assert (await _publish(tenant_id, source_id)).startswith("published")
    live = await _source(tenant_id, source_id)
    assert live.is_active is True
    assert live.published_at is not None


async def test_an_older_version_never_overwrites_a_newer_one_out_of_queue_order() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    owner = await _member(tenant_id)
    v1 = await _member_submission(tenant_id, agent_id, owner)
    v2 = await _member_submission(tenant_id, agent_id, owner, body=BODY + " Card accepted.")

    assert (await _publish(tenant_id, v2["id"])).startswith("published")
    assert await _publish(tenant_id, v1["id"]) == "superseded"

    assert (await _source(tenant_id, v2["id"])).is_active is True
    assert (await _source(tenant_id, v1["id"])).is_active is False


async def test_knowledge_added_before_the_agent_is_published_goes_live_on_the_next_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The ordinary case the sweep exists for: a client fills in their knowledge before
    their agent's first publish. The job's refusal is recorded, not retried for ever, and
    the sweep publishes it once there is an agent to publish it to."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    owner = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = NULL WHERE id = :a"), {"a": agent_id}
        )
    created = await _member_submission(tenant_id, agent_id, owner)
    assert await _publish(tenant_id, created["id"]) == "failed:agent_not_published"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = :r WHERE id = :a"),
            {"r": ref, "a": agent_id},
        )
        # Past `RETRY_STALLED_AFTER`, so the sweep considers it.
        await session.execute(
            text("UPDATE kb_sources SET updated_at = now() - interval '2 hours' WHERE id = :s"),
            {"s": created["id"]},
        )

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(kb_gloss, "tenants_holding_knowledge", _only_this_tenant)
    # The re-drive and link arms read fleet-wide, so on a shared database they would act on
    # other tests' uploads; this test is about the typed arm only.
    _quiet_fleet_wide_arms(monkeypatch)
    assert await kb_ingest._unpublished_typed_sources(datetime.now(UTC)) == [
        (tenant_id, uuid.UUID(str(created["id"])))
    ]
    outcome = await kb_ingest.sweep_kb_uploads({})
    assert "typed=1" in outcome
    assert (await _source(tenant_id, created["id"])).is_active is True


def _quiet_fleet_wide_arms(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Replace the sweep's re-drive and link-recheck arms with recorders."""
    seen: list[str] = []

    async def _redrive(_ctx: dict[str, Any], payload: dict[str, Any]) -> str:
        seen.append(str(payload["source_id"]))
        return "skipped"

    async def _recheck(**_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(kb_ingest, "ingest_kb_source", _redrive)
    monkeypatch.setattr(kb_ingest, "_recheck_link", _recheck)
    return seen


async def test_one_item_that_raises_does_not_stop_the_rest_of_the_sweep(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stalled upload whose object cannot be read used to raise out of the sweep before the
    typed-knowledge arm ran, and on every later tick too, since its row led the queue again.
    Now every other item runs, and the tick still fails so its retry and alarm apply."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    owner = await _member(tenant_id)
    created = await _member_submission(tenant_id, agent_id, owner)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE kb_sources SET updated_at = now() - interval '2 hours' WHERE id = :s"),
            {"s": created["id"]},
        )

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(kb_gloss, "tenants_holding_knowledge", _only_this_tenant)
    _quiet_fleet_wide_arms(monkeypatch)
    # One stalled upload, the oldest in the fleet so the sweep's capped read always reaches it.
    async with tenant_session(tenant_id) as session:
        stalled = await uploads.create_link(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Price list",
            url="https://example.com/prices",
            submitted_by=owner,
            auto_approve=True,
        )
        await session.execute(
            text(
                "UPDATE kb_uploads SET ingest_status = 'received', "
                "updated_at = timestamptz '2000-01-01 00:00:00+00' WHERE id = :u"
            ),
            {"u": stalled["id"]},
        )
    broken = stalled["source_id"]

    async def _redrive_fails(_ctx: dict[str, Any], _payload: dict[str, Any]) -> str:
        raise ConnectionError("object storage unreachable")

    monkeypatch.setattr(kb_ingest, "ingest_kb_source", _redrive_fails)

    try:
        with pytest.raises(
            kb_ingest.KbSweepIncompleteError, match=f"redrive:{broken}:ConnectionError"
        ):
            await kb_ingest.sweep_kb_uploads({})
        assert (await _source(tenant_id, created["id"])).is_active is True
    finally:
        # Out of the retryable set, so the next sweep on this database never sees it: an
        # oldest-in-the-fleet stalled row left behind would fill every later test's capped read.
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE kb_uploads SET ingest_status = 'error' WHERE id = :u"),
                {"u": stalled["id"]},
            )


async def test_the_sweep_leaves_an_admins_approve_then_publish_flow_alone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admin-approved source waits for the admin's own Publish, exactly as before D-658:
    the approver is not a member of the account, so the sweep's arm does not name it."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    async with tenant_session(tenant_id) as session:
        seeded = await service.submit_source(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Seeded", body=BODY
        )
        assert seeded["status"] == "pending_approval"
        assert await service.approve_source(
            session, source_id=seeded["id"], approved_by=uuid.uuid4()
        )
        await session.execute(
            text("UPDATE kb_sources SET updated_at = now() - interval '2 hours' WHERE id = :s"),
            {"s": seeded["id"]},
        )
    assert await _publish_jobs(seeded["id"]) == 0, "an operator's submission promised a publish"

    async def _only_this_tenant() -> list[uuid.UUID]:
        return [tenant_id]

    monkeypatch.setattr(kb_gloss, "tenants_holding_knowledge", _only_this_tenant)
    assert await kb_ingest._unpublished_typed_sources(datetime.now(UTC)) == []


async def test_an_account_members_photo_goes_live_without_a_confirmation(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-658 removed the owner-confirmation step for text a model read off a photograph.
    The reading is still labelled (`text_provenance = 'ocr'`) on the client's screen."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    owner = await _member(tenant_id)

    async def _read_by_a_model(*_: Any, **__: Any) -> ExtractedText:
        return ExtractedText(
            text=BODY,
            kind="image",
            provenance="ocr",
            unit_count=1,
            unit_name="images",
            needs_confirmation=True,
            model="test-ocr",
        )

    monkeypatch.setattr(kb_ingest, "_extract", _read_by_a_model)
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_upload(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Menu photo",
            filename="menu.jpg",
            content_type="image/jpeg",
            data=b"\xff\xd8\xff\xe0 a photographed menu",
            submitted_by=owner,
            auto_approve=True,
        )
    assert row["review_state"] == "pending_approval", "nothing is approved before it is read"

    outcome = await kb_ingest.ingest_kb_source(
        {"job_try": 1},
        {"tenant_id": str(tenant_id), "source_id": str(row["source_id"]), "may_self_approve": True},
    )
    assert outcome.startswith("published"), outcome
    async with tenant_session(tenant_id) as session:
        shown = await uploads.get_upload(session, uuid.UUID(str(row["id"])))
    assert shown["is_live"] is True
    assert shown["text_provenance"] == "ocr"
    assert (await _source(tenant_id, row["source_id"])).approved_by == owner


async def _linked_page(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, linker: uuid.UUID
) -> dict[str, Any]:
    """A link added and live, then re-read after the page changed. Returns the upload row."""
    async with tenant_session(tenant_id) as session:
        row = await uploads.create_link(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Opening hours",
            url="https://example.com/hours",
            submitted_by=linker,
            auto_approve=True,
        )
        await service.publish_source(
            session, tenant_id=tenant_id, source_id=uuid.UUID(str(row["source_id"]))
        )
    return row


async def _versions(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> list[tuple[Any, ...]]:
    async with tenant_session(tenant_id) as session:
        return [
            tuple(r)
            for r in (
                await session.execute(
                    text(
                        "SELECT version, status, is_active, approved_by FROM kb_sources "
                        "WHERE agent_id = :a AND name = 'Opening hours' ORDER BY version"
                    ),
                    {"a": agent_id},
                )
            ).all()
        ]


async def _recheck(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, row: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _page(_url: str) -> bytes:
        return b"<html><body>Open 9 to 9 now</body></html>"

    monkeypatch.setattr(kb_ingest, "_fetch_page", _page)
    assert await kb_ingest._recheck_link(
        upload_id=uuid.UUID(str(row["id"])),
        tenant_id=tenant_id,
        agent_id=agent_id,
        url="https://example.com/hours",
        known_digest="a-digest-from-the-last-reading",
        name="Opening hours",
    )


async def test_a_changed_page_a_member_linked_goes_live_in_the_linkers_name(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The founder: "the client linked the page, so its updates are theirs"."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    owner = await _member(tenant_id)
    row = await _linked_page(tenant_id, agent_id, owner)
    await _recheck(tenant_id, agent_id, row, monkeypatch)

    v2 = await _versions(tenant_id, agent_id)
    assert v2[1][1:] == ("approved", False, owner), "the change was not approved for the linker"
    async with tenant_session(tenant_id) as session:
        new_source = (
            await session.execute(
                text(
                    "SELECT id FROM kb_sources WHERE agent_id = :a AND name = 'Opening hours' "
                    "AND version = 2"
                ),
                {"a": agent_id},
            )
        ).scalar()
    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :job "
                    "AND payload->>'source_id' = :sid"
                ),
                {"job": uploads.INGEST_KB_SOURCE_JOB, "sid": str(new_source)},
            )
        ).scalar()
    assert queued == 1, "the publish of the change must be promised in the same commit"

    outcome = await kb_ingest.ingest_kb_source(
        {"job_try": 1},
        {"tenant_id": str(tenant_id), "source_id": str(new_source), "may_self_approve": False},
    )
    assert outcome.startswith("published"), outcome
    assert [(v[0], v[1], v[2]) for v in await _versions(tenant_id, agent_id)] == [
        (1, "archived", False),
        (2, "approved", True),
    ]


async def test_a_changed_page_an_operator_linked_still_waits_for_review(
    s3: FakeS3, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An operator's id is never a membership, so their link keeps the review it had."""
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    row = await _linked_page(tenant_id, agent_id, uuid.uuid4())
    await _recheck(tenant_id, agent_id, row, monkeypatch)
    assert [(v[0], v[1], v[2]) for v in await _versions(tenant_id, agent_id)] == [
        (1, "approved", True),
        (2, "pending_approval", False),
    ]


async def test_an_older_upload_finishing_late_is_archived_not_published_over_a_newer_one(
    s3: FakeS3,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    tenant_id, agent_id = uuid.UUID(str(tenant_id)), uuid.UUID(str(agent_id))
    owner = await _member(tenant_id)
    async with tenant_session(tenant_id) as session:
        old = await uploads.create_link(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Opening hours",
            url="https://example.com/hours",
            submitted_by=owner,
            auto_approve=True,
        )
        new = await uploads.create_link(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Opening hours",
            url="https://example.com/hours-v2",
            submitted_by=owner,
            auto_approve=True,
        )
    for row in (new, old):
        await kb_ingest.ingest_kb_source(
            {"job_try": 1},
            {
                "tenant_id": str(tenant_id),
                "source_id": str(row["source_id"]),
                "may_self_approve": False,
            },
        )
    assert [(v[0], v[1], v[2]) for v in await _versions(tenant_id, agent_id)] == [
        (1, "archived", False),
        (2, "approved", True),
    ]
