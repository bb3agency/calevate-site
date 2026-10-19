"""The voice platform's copy of a call is deleted when its period ends or an erasure reaches it
(D-798), through `delete_engine_call_content`, and an erasure task closes on the platform's
confirmations: every call deleted with nothing queued, and the contact half settled.

The vendor is a mock transport answering as `post-call/delete-call-content.md:443-589` and
`webhooks.md:545-563` document (`thinnest-findings/mirror/snapshots/2026-10-15/pages/
api-reference/`).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.compliance import engine_content
from apps.api.compliance.processor_erasure import (
    record_contact_erased,
    settle_voice_engine_task,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_customer_data import (
    ThinnestCustomerData,
    set_thinnest_customer_data,
)
from apps.workers import engine_customer_data as jobs
from apps.workers import retention
from arq import Retry
from sqlalchemy import text
from tests.engine_customer_data_test import _outbox, _task_status
from tests.thinnest_erasure_test import _request, _tenant_with_a_platform_call
from tests.workspace_support import give_own_workspace


class ContentVendor:
    """`DELETE /calls/{id}/content` per call: a status per raw id (default 200, nothing left
    queued), and `pending` files still queued on a 200."""

    def __init__(self) -> None:
        self.status: dict[str, int] = {}
        self.pending: dict[str, int] = {}
        self.code: dict[str, str] = {}
        self.seen: list[tuple[str, str | None]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        raw = path.split("/")[2]
        self.seen.append((raw, request.headers.get("Thinnest-Workspace")))
        status = self.status.get(raw, 200)
        if status == 200:
            return httpx.Response(
                200,
                json={
                    "contentDeleted": True,
                    "contentDeletedAt": "2026-10-15T10:00:00Z",
                    "recordingsPending": self.pending.get(raw, 0),
                    "call": None,
                },
            )
        codes = {403: "key_scope_build", 404: "not_found", 409: "call_live", 410: "gone"}
        code = self.code.get(raw, codes.get(status, "unavailable"))
        return httpx.Response(status, json={"error": "refused", "code": code})


@pytest.fixture
def vendor() -> Any:
    fake = ContentVendor()
    set_thinnest_customer_data(
        ThinnestCustomerData(
            api_key="ta_live_test",
            client=httpx.AsyncClient(
                transport=httpx.MockTransport(fake.handler),
                base_url="https://app.thinnest.ai/api/v1",
            ),
        )
    )
    yield fake
    set_thinnest_customer_data(None)


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    raised: list[str] = []
    monkeypatch.setattr(jobs, "alert", lambda _stage, code, **_kw: raised.append(code))
    return raised


async def _call_state(tenant_id: UUID, call_id: UUID) -> tuple[Any, Any, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_content_delete_requested_at, engine_content_deleted_at, "
                    "engine_content_recordings_pending FROM calls WHERE id = :c"
                ),
                {"c": call_id},
            )
        ).one()
    return row[0], row[1], row[2]


async def _add_call(tenant_id: UUID, engine_call_id: str, *, age_days: int = 0) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT id FROM agents ORDER BY created_at LIMIT 1"))
        ).scalar_one()
        ended = datetime.now(UTC) - timedelta(days=age_days)
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, ended_at, duration_s, created_at, updated_at) VALUES (:id, :t, :a, "
                ":e, 'inbound', 'completed', :at, :at, 30, :at, now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": engine_call_id, "at": ended},
        )
    return call_id


async def _erasure(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[UUID, UUID, UUID, str, dict[str, Any]]:
    """A ThinnestAI erasure of a call in our developer workspace (no contact asked)."""
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, call_id, phone, engine_call_id = await _tenant_with_a_platform_call()
    request_id = await _request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    [payload] = await _outbox(jobs.ENGINE_CONTENT_DELETE_JOB, tenant_id)
    return tenant_id, request_id, call_id, engine_call_id, payload


def test_the_job_name_is_one_spelling() -> None:
    assert engine_content.ENGINE_CONTENT_DELETE_JOB == jobs.ENGINE_CONTENT_DELETE_JOB


# --- an erasure ---------------------------------------------------------------------------


async def test_an_erasure_deletes_the_calls_content_and_closes_its_task(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor
) -> None:
    tenant_id, request_id, call_id, engine_call_id, payload = await _erasure(monkeypatch)
    assert await _task_status(tenant_id, request_id) == ("open", "contact-not-asked")

    result = await jobs.delete_engine_call_content({}, payload)

    assert result == "deleted=1 gone=0 busy=0 skipped=0 tasks_confirmed=1"
    # A call in our developer workspace is deleted there, with no client header.
    assert vendor.seen == [(engine_call_id, None)]
    _requested, deleted_at, pending = await _call_state(tenant_id, call_id)
    assert deleted_at == datetime(2026, 10, 15, 10, tzinfo=UTC) and pending == 0
    assert await _task_status(tenant_id, request_id) == ("confirmed", "contact-not-asked")

    # A replay finds it done and asks nothing.
    assert (await jobs.delete_engine_call_content({}, payload)).startswith("deleted=0")
    assert len(vendor.seen) == 1


async def test_files_still_queued_hold_the_task_until_the_platform_says_none(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor
) -> None:
    tenant_id, request_id, call_id, engine_call_id, payload = await _erasure(monkeypatch)
    vendor.pending[engine_call_id] = 1
    await jobs.delete_engine_call_content({}, payload)
    assert (await _call_state(tenant_id, call_id))[2] == 1
    assert (await _task_status(tenant_id, request_id))[0] == "requested"

    # The backstop asks again a day later; the platform now holds none.
    vendor.pending[engine_call_id] = 0
    assert (await jobs.delete_engine_call_content({}, payload)).endswith("tasks_confirmed=1")
    assert len(vendor.seen) == 2


async def test_a_call_in_a_clients_workspace_is_deleted_there(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, _call_id, _phone, _ecid = await _tenant_with_a_platform_call()
    workspace = await give_own_workspace(tenant_id)
    call_id = await _add_call(tenant_id, f"out_x@{workspace}")
    assert await jobs.delete_engine_call_content(
        {}, {"tenant_id": str(tenant_id), "call_ids": [str(call_id)]}
    ) == ("deleted=1 gone=0 busy=0 skipped=0 tasks_confirmed=0")
    assert vendor.seen == [("out_x", workspace)]


@pytest.mark.parametrize("status", [404, 410])
async def test_a_call_or_workspace_already_gone_is_recorded_deleted(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor, status: int
) -> None:
    tenant_id, request_id, call_id, engine_call_id, payload = await _erasure(monkeypatch)
    vendor.status[engine_call_id] = status
    assert (await jobs.delete_engine_call_content({}, payload)).startswith("deleted=0 gone=1")
    _requested, deleted_at, pending = await _call_state(tenant_id, call_id)
    assert deleted_at is not None and pending == 0
    assert (await _task_status(tenant_id, request_id))[0] == "confirmed"


async def test_a_live_or_booked_call_is_asked_again_later(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor, alarms: list[str]
) -> None:
    tenant_id, request_id, call_id, engine_call_id, payload = await _erasure(monkeypatch)
    vendor.status[engine_call_id] = 409
    with pytest.raises(Retry):
        await jobs.delete_engine_call_content({"job_try": 1}, payload)
    # The last try leaves it to the backstop, quietly: a live call is not a fault.
    assert (await jobs.delete_engine_call_content({"job_try": 3}, payload)).startswith(
        "deleted=0 gone=0 busy=1"
    )
    assert (await _call_state(tenant_id, call_id))[1] is None
    assert (await _task_status(tenant_id, request_id))[0] == "requested"
    assert alarms == []


async def test_a_transient_failure_retries_then_alarms(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor, alarms: list[str]
) -> None:
    _tenant_id, _request_id, _call_id, engine_call_id, payload = await _erasure(monkeypatch)
    vendor.status[engine_call_id] = 503
    with pytest.raises(Retry):
        await jobs.delete_engine_call_content({"job_try": 1}, payload)
    with pytest.raises(ProblemError):
        await jobs.delete_engine_call_content({"job_try": 3}, payload)
    assert alarms == ["engine_call_content_delete_failed"]


async def test_a_key_that_cannot_delete_alarms_at_once(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor, alarms: list[str]
) -> None:
    _tenant_id, _request_id, _call_id, engine_call_id, payload = await _erasure(monkeypatch)
    vendor.status[engine_call_id] = 403
    with pytest.raises(ProblemError) as refused:
        await jobs.delete_engine_call_content({"job_try": 1}, payload)
    assert refused.value.code == "engine_key_not_full"
    assert alarms == ["engine_call_content_delete_failed"]


async def test_a_403_about_anything_but_the_key_is_not_called_a_key_problem(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor, alarms: list[str]
) -> None:
    # A key that belongs to one customer workspace is refused acting as another with a 403
    # too (delete-call-content.md:556-557); errors.md:20-37 says to branch on `code`.
    _tenant_id, _request_id, _call_id, engine_call_id, payload = await _erasure(monkeypatch)
    vendor.status[engine_call_id] = 403
    vendor.code[engine_call_id] = "workspace_header_forbidden"
    with pytest.raises(Retry):
        await jobs.delete_engine_call_content({"job_try": 1}, payload)
    with pytest.raises(ProblemError) as refused:
        await jobs.delete_engine_call_content({"job_try": 3}, payload)
    assert refused.value.code != "engine_key_not_full"
    assert alarms == ["engine_call_content_delete_failed"]


async def test_our_own_runtimes_calls_and_another_tenants_calls_are_never_sent(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, _call_id, _phone, _ecid = await _tenant_with_a_platform_call()
    ours = await _add_call(tenant_id, f"pipecat:{tenant_id}:abc")
    other_tenant, other_call, _p, _e = await _tenant_with_a_platform_call()

    # Tenant X's job naming tenant Y's call: RLS hides the row, so nothing is sent.
    result = await jobs.delete_engine_call_content(
        {}, {"tenant_id": str(tenant_id), "call_ids": [str(ours), str(other_call)]}
    )
    assert result == "deleted=0 gone=0 busy=0 skipped=1 tasks_confirmed=0"
    assert vendor.seen == []
    assert (await _call_state(other_tenant, other_call))[1] is None
    # And the queue never marks our own runtime's call as owed.
    async with tenant_session(tenant_id) as session:
        assert (
            await engine_content.queue_engine_content_deletion(
                session, tenant_id=tenant_id, call_ids=[ours]
            )
            == 0
        )
        assert (
            await engine_content.queue_engine_content_deletion(
                session, tenant_id=tenant_id, call_ids=[]
            )
            == 0
        )


async def test_another_engine_queues_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "engine", "fake")
    tenant_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        assert (
            await engine_content.queue_engine_content_deletion(
                session, tenant_id=tenant_id, call_ids=None
            )
            == 0
        )


# --- contact.erased closes the contact half --------------------------------------------------


async def test_contact_erased_closes_the_task_waiting_on_that_contact(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, request_id, _call_id, _ecid, payload = await _erasure(monkeypatch)
    await jobs.delete_engine_call_content({}, payload)
    async with tenant_session(tenant_id) as session:
        task_id = (
            await session.execute(
                text(
                    "UPDATE processor_erasure_tasks SET status = 'requested', "
                    "vendor_reference = 'cust_a=0,cust_b=2' WHERE request_ref = :r "
                    "RETURNING id"
                ),
                {"r": request_id},
            )
        ).scalar_one()
        # Someone else's contact: nothing of ours waits on it.
        assert await record_contact_erased(session, contact_id="cust_other") == []
        assert await record_contact_erased(session, contact_id="cust_b") == [task_id]
    assert await _task_status(tenant_id, request_id) == ("confirmed", "cust_a=0,cust_b=0")
    async with tenant_session(tenant_id) as session:
        # Already answered: a repeat changes nothing.
        assert await record_contact_erased(session, contact_id="cust_b") == []
        assert not await settle_voice_engine_task(session, task_id=task_id)


async def test_an_unsettled_contact_or_call_keeps_the_task_open(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor
) -> None:
    tenant_id, request_id, _call_id, _ecid, _payload = await _erasure(monkeypatch)
    async with tenant_session(tenant_id) as session:
        task_id = (
            await session.execute(
                text(
                    "UPDATE processor_erasure_tasks SET status = 'requested', "
                    "vendor_reference = 'cust_a=0' WHERE request_ref = :r RETURNING id"
                ),
                {"r": request_id},
            )
        ).scalar_one()
        # The contact half is done; the call's content is not.
        assert not await settle_voice_engine_task(session, task_id=task_id)
        await session.execute(
            text("UPDATE processor_erasure_tasks SET vendor_reference = NULL WHERE id = :t"),
            {"t": task_id},
        )
        # No contact answer at all yet.
        assert not await settle_voice_engine_task(session, task_id=task_id)


async def test_a_contact_still_held_back_keeps_the_task_open_until_it_is_erased(
    monkeypatch: pytest.MonkeyPatch, vendor: ContentVendor
) -> None:
    """A contact whose DELETE waits for our copy of its recordings (D-810) has erased
    nothing yet, so the task stays open even with every call's content gone and every other
    contact settled; once that contact reports its last recording gone, the task closes."""
    tenant_id, request_id, _call_id, _ecid, payload = await _erasure(monkeypatch)
    await jobs.delete_engine_call_content({}, payload)
    async with tenant_session(tenant_id) as session:
        task_id = (
            await session.execute(
                text(
                    "UPDATE processor_erasure_tasks SET status = 'requested', "
                    "vendor_reference = 'cust_a=0,cust_h=held' WHERE request_ref = :r "
                    "RETURNING id"
                ),
                {"r": request_id},
            )
        ).scalar_one()
        assert not await settle_voice_engine_task(session, task_id=task_id)
    assert await _task_status(tenant_id, request_id) == ("requested", "cust_a=0,cust_h=held")
    async with tenant_session(tenant_id) as session:
        assert await record_contact_erased(session, contact_id="cust_h") == [task_id]
    assert (await _task_status(tenant_id, request_id))[0] == "confirmed"


async def test_a_task_naming_no_platform_call_has_none_awaiting_our_copy() -> None:
    """A contact erasure whose task names no call of the platform's has nothing it must wait
    for, and asks the database nothing to say so."""

    class _NoReads:
        async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("an empty list of calls needs no read")

    assert (
        await engine_content.calls_awaiting_our_copy(
            _NoReads(),  # type: ignore[arg-type]
            raw_call_ids=[],
            workspace="org_any",
        )
        == 0
    )


# --- the retention sweep -------------------------------------------------------------------


async def test_the_sweep_queues_calls_past_the_shorter_period_and_the_unsettled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, fresh_call, _phone, _ecid = await _tenant_with_a_platform_call()
    old = await _add_call(tenant_id, f"out_{uuid.uuid4()}", age_days=100)
    stale = await _add_call(tenant_id, f"out_{uuid.uuid4()}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET engine_content_delete_requested_at = now() - interval '2 days', "
                "recording_url = 'recordings/stale.wav' WHERE id = :c"
            ),
            {"c": stale},
        )

    totals = await retention.sweep_tenant(tenant_id)

    # Recording 90, transcript 365: the platform's copy goes at 90.
    assert totals["engine_content_queued"] == 2
    queued = {
        c for p in await _outbox(jobs.ENGINE_CONTENT_DELETE_JOB, tenant_id) for c in p["call_ids"]
    }
    assert queued == {str(old), str(stale)}
    assert (await _call_state(tenant_id, fresh_call))[0] is None
    # Marked, so tomorrow's tick does not queue the same call again.
    assert (await retention.sweep_tenant(tenant_id))["engine_content_queued"] == 0


async def test_our_own_runtimes_old_calls_do_not_fill_the_sweeps_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A call our former runtime ran is never queued (no vendor holds it), so it is never
    # marked either; if the due query selected it, it would head every night's batch.
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    monkeypatch.setattr(retention, "ENGINE_CONTENT_BATCH", 2)
    tenant_id, _call, _phone, _ecid = await _tenant_with_a_platform_call()
    for n in range(2):
        await _add_call(tenant_id, f"pipecat:{tenant_id}:old{n}", age_days=200 + n)
    platform_call = await _add_call(tenant_id, f"out_{uuid.uuid4()}", age_days=100)

    assert (await retention.sweep_tenant(tenant_id))["engine_content_queued"] == 1
    queued = {
        c for p in await _outbox(jobs.ENGINE_CONTENT_DELETE_JOB, tenant_id) for c in p["call_ids"]
    }
    assert queued == {str(platform_call)}


async def test_a_tenant_with_no_call_content_policy_still_gets_the_backstop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, _call, _phone, _ecid = await _tenant_with_a_platform_call()
    await _add_call(tenant_id, f"out_{uuid.uuid4()}", age_days=400)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "DELETE FROM retention_policies WHERE data_category IN ('recording', 'transcript')"
            )
        )
    assert (await retention.sweep_tenant(tenant_id))["engine_content_queued"] == 0
    monkeypatch.setattr(get_settings(), "engine", "fake")
    assert (await retention.sweep_tenant(tenant_id))["engine_content_queued"] == 0


# --- the retention floor ---------------------------------------------------------------------


async def _sent(tenant_id: UUID) -> set[str]:
    return {
        c for p in await _outbox(jobs.ENGINE_CONTENT_DELETE_JOB, tenant_id) for c in p["call_ids"]
    }


async def test_an_erasure_never_deletes_a_recording_we_do_not_hold_inside_the_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, call_id, phone, _ecid = await _tenant_with_a_platform_call()
    # The call has ended but our copy of its recording has not landed.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET recording_url = NULL WHERE id = :c"), {"c": call_id}
        )
    request_id = await _request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )

    # Owed, but the platform's copy is the only one and is not asked deleted.
    assert (await _call_state(tenant_id, call_id))[0] is not None
    assert await _sent(tenant_id) == set()

    # The backstop a day later: still inside the floor, still held back.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET engine_content_delete_requested_at = now() - interval '2 days' "
                "WHERE id = :c"
            ),
            {"c": call_id},
        )
    await retention.sweep_tenant(tenant_id)
    assert await _sent(tenant_id) == set()

    # Once the floor has passed the backstop sends it.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET engine_content_delete_requested_at = now() - interval '2 days', "
                "ended_at = now() - interval '91 days', created_at = now() - interval '91 days' "
                "WHERE id = :c"
            ),
            {"c": call_id},
        )
    await retention.sweep_tenant(tenant_id)
    assert await _sent(tenant_id) == {str(call_id)}


async def test_a_call_that_never_connected_or_whose_audio_we_hold_goes_at_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, held, _phone, _ecid = await _tenant_with_a_platform_call()
    unanswered = await _add_call(tenant_id, f"out_{uuid.uuid4()}")
    not_copied = await _add_call(tenant_id, f"out_{uuid.uuid4()}")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = 'no_answer' WHERE id = :c"), {"c": unanswered}
        )
        owed = await engine_content.queue_engine_content_deletion(
            session, tenant_id=tenant_id, call_ids=[held, unanswered, not_copied]
        )

    assert owed == 3
    assert await _sent(tenant_id) == {str(held), str(unanswered)}
    assert (await _call_state(tenant_id, not_copied))[0] is not None


async def test_queued_jobs_carry_ids_only(monkeypatch: pytest.MonkeyPatch) -> None:
    _tenant_id, _request_id, _call_id, _ecid, payload = await _erasure(monkeypatch)
    assert set(payload) == {"tenant_id", "call_ids"}
    assert "+91" not in json.dumps(payload)
