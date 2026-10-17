"""An erasure's contact DELETE waits for our own copy of the person's recordings (D-810).

Erasing a contact in a client's workspace deletes that person's recordings at ThinnestAI at
once (`thinnest-findings/mirror/snapshots/2026-10-15/pages/workspace/data-and-erasure.md:21`).
So the DELETE is held while any of the erasure's calls in that workspace connected, is
inside the 90-day floor and has no recording copy of ours — D-803's rule for a per-call
deletion (`engine_content._READY_SQL`). The nightly sweep queues a held erasure again and
the job deletes the contacts the task recorded once the copy lands, the floor passes, or
the call never connected.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers import engine_customer_data as jobs
from apps.workers import retention
from sqlalchemy import text
from tests.engine_customer_data_test import (
    WORKSPACE,
    FakeWorkspaceVendor,
    _outbox,
    _provisioned,
    _task_status,
    vendor,
)
from tests.thinnest_erasure_test import _request, _tenant_with_a_platform_call

# Re-exported so pytest finds the fixture here.
__all__ = ["vendor"]


async def _erased(
    monkeypatch: pytest.MonkeyPatch,
    *,
    status: str = "completed",
    scope: str | None = WORKSPACE,
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """A ThinnestAI erasure of one call whose recording we never copied."""
    _provisioned(monkeypatch)
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, call_id, phone, raw = await _tenant_with_a_platform_call()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET recording_url = NULL, status = :s, engine_call_id = :e "
                "WHERE id = :c"
            ),
            {"c": call_id, "s": status, "e": f"{raw}@{scope}" if scope else raw},
        )
    request_id = await _request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    return tenant_id, request_id, call_id


async def _first_run(tenant_id: uuid.UUID) -> str:
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)
    return await jobs.erase_engine_contact({}, payload)


async def _released(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """The re-queued runs, which carry no subject."""
    return [
        p for p in await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id) if "subject" not in p
    ]


def _deletes(vendor: FakeWorkspaceVendor) -> list[str]:
    return [path for method, path, _h, _b in vendor.requests if method == "DELETE"]


async def test_the_contact_is_held_while_a_connected_calls_recording_is_only_at_the_platform(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    tenant_id, request_id, _call = await _erased(monkeypatch)

    assert await _first_run(tenant_id) == "held contacts=1 calls_waiting=1"
    assert [(m, p, h) for m, p, h, _ in vendor.requests] == [("GET", "/contacts", WORKSPACE)]
    # Nothing was asked of the platform, so the task is still open, naming what it holds.
    assert await _task_status(tenant_id, request_id) == ("open", "cust_1=held")


async def test_a_held_erasure_is_retried_and_completes_once_our_copy_lands(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    tenant_id, request_id, call_id = await _erased(monkeypatch)
    await _first_run(tenant_id)

    # The nightly sweep queues it again; still too early, so nothing is deleted.
    assert (await retention.sweep_tenant(tenant_id))["engine_contact_erasures_requeued"] == 1
    [early] = await _released(tenant_id)
    assert await jobs.erase_engine_contact({}, early) == "held contacts=1 calls_waiting=1"
    assert _deletes(vendor) == []

    # Our copy lands (a late recording re-files the erasure, which holds it).
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO recording_erasure_holds (id, tenant_id, call_id, request_id, "
                "object_key, erase_after, created_at) VALUES (:id, :t, :c, :r, :k, :at, now())"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "c": call_id,
                "r": request_id,
                "k": f"recordings/{call_id}.wav",
                "at": datetime.now(UTC) + timedelta(days=90),
            },
        )
        # A day after the content deletion was first owed, so the sweep re-asks it too.
        await session.execute(
            text(
                "UPDATE calls SET engine_content_delete_requested_at = now() - interval '2 days' "
                "WHERE id = :c"
            ),
            {"c": call_id},
        )
    totals = await retention.sweep_tenant(tenant_id)
    assert totals["engine_contact_erasures_requeued"] == 1
    assert totals["engine_content_queued"] == 1
    released = (await _released(tenant_id))[-1]

    assert await jobs.erase_engine_contact({}, released) == "contacts=1 recordings_pending=0"
    assert _deletes(vendor) == ["/contacts/cust_1"]
    assert await _task_status(tenant_id, request_id) == ("requested", "cust_1=0")

    [content] = await _outbox(jobs.ENGINE_CONTENT_DELETE_JOB, tenant_id)
    assert (await jobs.delete_engine_call_content({}, content)).endswith("tasks_confirmed=1")
    assert await _task_status(tenant_id, request_id) == ("confirmed", "cust_1=0")
    # Released, so the next night queues nothing.
    assert (await retention.sweep_tenant(tenant_id))["engine_contact_erasures_requeued"] == 0


async def test_a_held_erasure_goes_ahead_once_the_floor_has_passed(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    tenant_id, request_id, call_id = await _erased(monkeypatch)
    await _first_run(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET ended_at = now() - interval '91 days', "
                "created_at = now() - interval '91 days' WHERE id = :c"
            ),
            {"c": call_id},
        )

    await retention.sweep_tenant(tenant_id)
    [released] = await _released(tenant_id)
    assert await jobs.erase_engine_contact({}, released) == "contacts=1 recordings_pending=0"
    assert _deletes(vendor) == ["/contacts/cust_1"]
    assert await _task_status(tenant_id, request_id) == ("requested", "cust_1=0")


async def test_a_held_erasure_goes_ahead_once_the_call_ends_without_connecting(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    """A dial still booked when the erasure ran holds the contact: it may yet connect. Once
    it ends unanswered nothing was recorded, so the DELETE goes on the next night."""
    tenant_id, request_id, call_id = await _erased(monkeypatch, status="queued")
    assert await _first_run(tenant_id) == "held contacts=1 calls_waiting=1"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = 'no_answer' WHERE id = :c"), {"c": call_id}
        )

    await retention.sweep_tenant(tenant_id)
    [released] = await _released(tenant_id)
    assert await jobs.erase_engine_contact({}, released) == "contacts=1 recordings_pending=0"
    assert _deletes(vendor) == ["/contacts/cust_1"]
    assert await _task_status(tenant_id, request_id) == ("requested", "cust_1=0")


async def test_a_call_in_another_workspace_does_not_hold_the_contact(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    """The contact DELETE acts on the client's workspace only; a call filed in our developer
    workspace keeps its recording there whatever this DELETE does."""
    tenant_id, _request_id, _call = await _erased(monkeypatch, scope=None)

    assert await _first_run(tenant_id) == "contacts=1 recordings_pending=0"
    assert _deletes(vendor) == ["/contacts/cust_1"]
