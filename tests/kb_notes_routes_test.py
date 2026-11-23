"""The knowledge page's typed notes: list, rename, remove and put back (D-893 L7).

The buttons call the same `kb/store` functions Pip's `knowledge_rename` and
`knowledge_remove` call; these tests drive them through the routes, within role.
"""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.db.session import tenant_session
from apps.api.kb import service as kb_service
from apps.api.kb import store
from apps.api.kb.picks import LINE_PICKS, read_picks
from apps.workers import kb_ingest
from sqlalchemy import text
from tests.conftest import FakeS3
from tests.kb_read_copy_test import _slug
from tests.kb_staff_curation_test import _client, _h, _member
from tests.kb_workflow_test import _tenant_with_published_agent


async def _note(tenant_id: uuid.UUID, name: str = "Parking") -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        created = await kb_service.submit_source(
            session,
            tenant_id=tenant_id,
            name=name,
            body="Parking is free behind the shop.",
            auto_approve=True,
        )
    source_id = uuid.UUID(str(created["id"]))
    await kb_ingest.publish_kb_source(
        {}, {"tenant_id": str(tenant_id), "source_id": str(source_id)}
    )
    return source_id


async def test_a_note_is_listed_renamed_removed_and_put_back(s3: FakeS3) -> None:
    del s3
    tenant_id, _agent = await _tenant_with_published_agent()
    note_id = await _note(tenant_id)
    slug = await _slug(tenant_id)
    _owner, owner = await _member(tenant_id, "owner")
    async with _client() as http:
        listed = await http.get("/v1/kb/notes", headers=_h(owner, slug))
        assert listed.status_code == 200, listed.text
        [row] = [n for n in listed.json()["notes"] if n["id"] == str(note_id)]
        assert row["state"] == "in_use" and row["name"] == "Parking"

        renamed = await http.patch(
            f"/v1/kb/notes/{note_id}", json={"name": "Car park"}, headers=_h(owner, slug)
        )
        assert renamed.status_code == 200 and renamed.json()["name"] == "Car park"

        removed = await http.post(f"/v1/kb/notes/{note_id}/remove", headers=_h(owner, slug))
        assert removed.status_code == 200, removed.text
        assert removed.json()["state"] == "removed" and removed.json()["restorable"] is True

        relisted = await http.get("/v1/kb/notes", headers=_h(owner, slug))
        assert [n["state"] for n in relisted.json()["notes"] if n["id"] == str(note_id)] == [
            "removed"
        ]

        back = await http.post(f"/v1/kb/notes/{note_id}/restore", headers=_h(owner, slug))
        assert back.status_code == 200, back.text
        assert back.json()["state"] == "in_use"

    async with tenant_session(tenant_id) as session:
        actions = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE object_id = :id AND action LIKE 'kb.%' "
                    "ORDER BY at"
                ),
                {"id": str(note_id)},
            )
        ).scalars()
        items, _total = await store.find_items(session, tenant_id=tenant_id, kinds=["note"])
    assert list(actions) == ["kb.renamed", "kb.removed", "kb.restored"]
    assert any(item.name == "Car park" and item.state == "in_use" for item in items)


async def test_pip_never_removes_a_removed_note_or_puts_back_one_in_use(s3: FakeS3) -> None:
    """FAILS IF Pip's `knowledge_remove` proposes, or confirms as done, a removal of a note
    already removed or a put-back of one still in use: a removed note keeps its ref, and
    `restore_note` on a note in use would republish its newest approved version."""
    import json

    import pytest
    from apps.api.copilot import write_tools
    from apps.api.copilot.write_tools_test import _confirm, _principal

    del s3
    tenant_id, _agent = await _tenant_with_published_agent()
    note_id = await _note(tenant_id)
    user_id, _token = await _member(tenant_id, "owner")
    actor = write_tools.actor_for(_principal(tenant_id, user_id))
    item = f"note:{note_id}"

    async def propose(put_back: bool | None) -> Any:
        return await write_tools.plan_write(
            "knowledge_remove", json.dumps({"item": item, "put_back": put_back}), actor=actor
        )

    with pytest.raises(write_tools.WriteRefusedError):
        await propose(True)
    removal = await propose(None)
    second = await propose(None)
    assert (await _confirm(tenant_id, user_id, removal.token)).applied is True
    # The second card, shown before the first was confirmed, changes nothing and says so.
    again = await _confirm(tenant_id, user_id, second.token)
    assert again.applied is False and "already removed" in again.detail
    with pytest.raises(write_tools.WriteRefusedError):
        await propose(None)
    back = await propose(True)
    assert (await _confirm(tenant_id, user_id, back.token)).applied is True


async def test_a_removed_note_is_not_knowledge_but_stays_listed_to_be_put_back(
    s3: FakeS3,
) -> None:
    del s3
    tenant_id, _agent = await _tenant_with_published_agent()
    note_id = await _note(tenant_id, "Holidays")
    async with tenant_session(tenant_id) as session:
        await store.remove_note(session, tenant_id=tenant_id, source_id=note_id)
        items, _total = await store.find_items(session, tenant_id=tenant_id, kinds=["note"])
        notes = await store.list_notes(session)
    assert [(i.state, i.agents_use) for i in items if i.name == "Holidays"] == [("removed", False)]
    assert [(n.name, n.state) for n in notes if n.name == "Holidays"] == [("Holidays", "removed")]


async def test_past_the_cap_the_most_recently_changed_notes_are_the_ones_listed() -> None:
    tenant_id, _agent = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        # 200 old notes whose names sort first, then one changed now whose name sorts last.
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, kind, name, status, version, is_active, "
                "created_at, updated_at) SELECT gen_random_uuid(), :t, 'text', "
                "'A note ' || lpad(n::text, 3, '0'), 'approved', 1, true, "
                "now() - interval '30 days', now() - interval '30 days' "
                "FROM generate_series(1, 200) AS n"
            ),
            {"t": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, kind, name, status, version, is_active, "
                "created_at, updated_at) VALUES (gen_random_uuid(), :t, 'text', 'Zoo timings', "
                "'approved', 1, true, now(), now())"
            ),
            {"t": tenant_id},
        )
        notes = await store.list_notes(session)
        # Rolled back, not committed: approved, active text sources with no chunks are a
        # state publishing never leaves, and every later knowledge sweep in the suite would
        # try to publish them and fail (`kb_render_refused`).
        await session.rollback()
    assert len(notes) == 200
    assert notes[0].name == "Zoo timings"
    assert [n.changed_at for n in notes] == sorted((n.changed_at for n in notes), reverse=True)


async def test_staff_without_curation_are_refused_and_another_account_sees_404(
    s3: FakeS3,
) -> None:
    del s3
    tenant_id, _agent = await _tenant_with_published_agent()
    other_id, _other_agent = await _tenant_with_published_agent()
    note_id = await _note(tenant_id)
    slug = await _slug(tenant_id)
    other_slug = await _slug(other_id)
    _staff, staff = await _member(tenant_id, "staff")
    _stranger, stranger = await _member(other_id, "owner")
    async with _client() as http:
        seen = await http.get("/v1/kb/notes", headers=_h(staff, slug))
        refused = await http.post(f"/v1/kb/notes/{note_id}/remove", headers=_h(staff, slug))
        foreign = await http.patch(
            f"/v1/kb/notes/{note_id}", json={"name": "Mine now"}, headers=_h(stranger, other_slug)
        )
        not_a_note = await http.post(
            f"/v1/kb/notes/{uuid.uuid4()}/restore", headers=_h(stranger, other_slug)
        )
    assert seen.status_code == 200
    assert refused.status_code == 403
    assert foreign.status_code == 404
    assert not_a_note.status_code == 404


async def test_a_note_put_back_over_an_unapproved_edit_lists_as_in_use_and_keeps_its_pick(
    s3: FakeS3,
) -> None:
    """An edit still waiting for review is archived with the note when it is removed; put
    back, the approved version is live again, and the list and a pick both name that one,
    not the never-approved edit."""
    del s3
    tenant_id, agent_id = await _tenant_with_published_agent()
    live_id = await _note(tenant_id, "Delivery")
    line_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        edit = await kb_service.submit_source(
            session, tenant_id=tenant_id, name="Delivery", body="Delivery is free over 500."
        )
        await store.remove_note(session, tenant_id=tenant_id, source_id=live_id)
        await store.restore_note(session, tenant_id=tenant_id, source_id=live_id)
        await session.execute(
            text(
                "INSERT INTO inbound_lines (id, tenant_id, agent_id, name) "
                "VALUES (:id, :t, :a, 'Front desk')"
            ),
            {"id": line_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO inbound_line_sources (id, tenant_id, inbound_line_id, kb_source_id) "
                "VALUES (:id, :t, :l, :s)"
            ),
            {"id": uuid.uuid4(), "t": tenant_id, "l": line_id, "s": live_id},
        )
        notes = [n for n in await store.list_notes(session) if n.name == "Delivery"]
        picked = (await read_picks(session, LINE_PICKS, [line_id]))[line_id]
    assert edit["status"] == "pending_approval"
    assert [(n.id, n.state) for n in notes] == [(live_id, "in_use")]
    assert picked == [live_id]
