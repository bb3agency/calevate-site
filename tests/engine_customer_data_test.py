"""Person-level writes in a client's OWN ThinnestAI workspace only (D-691, revised 8 Oct 2026).

Do-not-call additions are pushed (`POST /do-not-call`) and an erasure erases the contact
(`GET /contacts?phone=`, `DELETE /contacts/{id}`) — but ONLY for a tenant whose workspace
resolves to its own `org_` id, always with `Thinnest-Workspace`, and never to our developer
workspace, which holds every legacy client's data. These tests drive both paths with a fake
resolver; `tests/engine_workspace_data_test.py` drives them through the real one (D-693).
Shapes are the mirror's:
`thinnest-findings/mirror/snapshots/2026-10-08/pages/api-reference/do-not-call/
add-do-not-call-number.md:340-380`, `contacts/list-contacts.md:355-363`,
`contacts/delete-contact.md:365-390`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance import engine_dnc
from apps.api.compliance.processor_erasure import (
    VOICE_PLATFORM_ERASURE_REQUESTED,
    VOICE_PLATFORM_ERASURE_SENTENCE,
)
from apps.api.compliance.service import add_to_dnc
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_customer_data import (
    ThinnestCustomerData,
    set_thinnest_customer_data,
)
from apps.api.tenancy import engine_workspace
from apps.workers import engine_customer_data as jobs
from apps.workers import retention
from apps.workers.settings import WorkerSettings
from arq import Retry
from sqlalchemy import text

WORKSPACE = "org_3fKq9TzQ1mN8vB2xR7cLpA"


class FakeWorkspaceVendor:
    def __init__(self) -> None:
        self.requests: list[tuple[str, str, str | None, Any]] = []
        self.contacts: list[str] = ["cust_1"]
        self.delete_status = 204
        self.fail = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        body = json.loads(request.content) if request.content else None
        self.requests.append(
            (request.method, path, request.headers.get("Thinnest-Workspace"), body)
        )
        if self.fail:
            return httpx.Response(503, json={"error": "down", "code": "unavailable"})
        if path == "/do-not-call":
            return httpx.Response(201, json={"phone": body["phone"]})
        if path == "/contacts":
            return httpx.Response(
                200, json={"items": [{"id": c} for c in self.contacts], "nextCursor": None}
            )
        if path.startswith("/contacts/"):
            if self.delete_status == 204:
                return httpx.Response(204)
            return httpx.Response(200, json={"recordingsPending": 1})
        return httpx.Response(404, json={"error": "no", "code": "not_found"})


@pytest.fixture
def vendor() -> Any:
    fake = FakeWorkspaceVendor()
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


def _provisioned(monkeypatch: pytest.MonkeyPatch, workspace: str | None = WORKSPACE) -> None:
    async def _resolve(_tenant_id: uuid.UUID) -> str | None:
        return workspace

    monkeypatch.setattr(engine_workspace, "workspace_for_tenant", _resolve)


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Own Workspace Clinic",
        slug=f"ow-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


def _phone() -> str:
    return f"+9198{uuid.uuid4().int % 100000000:08d}"


async def _outbox(job: str, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE job = :j"), {"j": job}
            )
        ).scalars()
        return [row for row in rows if row.get("tenant_id") == str(tenant_id)]


# --- the resolver ---------------------------------------------------------------------------


async def test_a_tenant_with_no_workspace_row_has_no_workspace_of_its_own() -> None:
    assert await engine_workspace.workspace_for_tenant(uuid.uuid4()) is None
    assert await engine_workspace.own_workspace(uuid.uuid4()) is None


@pytest.mark.parametrize(
    ("workspace", "own"),
    [(WORKSPACE, True), (None, False), ("", False), ("org_", False), ("ws_dev", False)],
)
def test_only_an_org_id_is_a_workspace_of_the_clients_own(workspace: str | None, own: bool) -> None:
    assert engine_workspace.is_own_workspace(workspace) is own


async def test_the_client_refuses_to_build_a_request_without_a_customer_workspace(
    vendor: FakeWorkspaceVendor,
) -> None:
    from apps.api.engine.thinnest_customer_data import thinnest_customer_data

    for workspace in ("", "ws_developer"):
        with pytest.raises(ProblemError) as refused:
            await thinnest_customer_data().add_do_not_call(workspace, "+919876500001")
        assert refused.value.code == "engine_workspace_not_provisioned"
    assert vendor.requests == []


# --- do-not-call, two-way ------------------------------------------------------------------


async def test_a_suppression_is_not_queued_for_a_tenant_without_its_own_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=_phone(), source="manual")
    assert await _outbox(engine_dnc.ENGINE_DNC_PUSH_JOB, tenant_id) == []


async def test_a_suppression_is_pushed_into_the_clients_own_workspace_only(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    _provisioned(monkeypatch)
    tenant_id = await _tenant()
    phone = _phone()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="manual")

    [payload] = await _outbox(engine_dnc.ENGINE_DNC_PUSH_JOB, tenant_id)
    assert phone not in json.dumps(payload)

    assert await jobs.push_engine_dnc({}, payload) == "pushed=1"
    [(method, path, header, body)] = vendor.requests
    assert (method, path, header) == ("POST", "/do-not-call", WORKSPACE)
    assert body["phone"] == phone


async def test_a_push_whose_tenant_lost_its_workspace_sends_nothing(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    _provisioned(monkeypatch, None)
    payload = {"tenant_id": str(uuid.uuid4()), "dnc_ids": [str(uuid.uuid4())]}
    assert await jobs.push_engine_dnc({}, payload) == "not_provisioned"
    assert vendor.requests == []


async def test_a_refused_push_is_retried_then_alarmed(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    _provisioned(monkeypatch)
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=_phone(), source="manual")
    [payload] = await _outbox(engine_dnc.ENGINE_DNC_PUSH_JOB, tenant_id)
    vendor.fail = True
    raised: list[str] = []
    monkeypatch.setattr(jobs, "alert", lambda _k, code, **_kw: raised.append(code))

    with pytest.raises(Retry):
        await jobs.push_engine_dnc({"job_try": 1}, payload)
    with pytest.raises(ProblemError):
        await jobs.push_engine_dnc({"job_try": 3}, payload)
    assert raised == ["engine_dnc_push_failed"]


def test_both_jobs_are_registered() -> None:
    registered = {getattr(fn, "__qualname__", "") for fn in WorkerSettings.functions}
    assert {jobs.ENGINE_DNC_PUSH_JOB, jobs.ENGINE_CONTACT_ERASURE_JOB} <= registered
    assert jobs.ENGINE_DNC_PUSH_JOB == engine_dnc.ENGINE_DNC_PUSH_JOB


# --- erasure ----------------------------------------------------------------------------------


async def _erased_with_platform_call(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[uuid.UUID, uuid.UUID, str]:
    from tests.thinnest_erasure_test import _request, _tenant_with_a_platform_call

    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, _call_id, phone, _ecid = await _tenant_with_a_platform_call()
    request_id = await _request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    return tenant_id, request_id, phone


async def _task_status(tenant_id: uuid.UUID, request_id: uuid.UUID) -> tuple[str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, vendor_reference FROM processor_erasure_tasks "
                    "WHERE request_ref = :r AND processor = 'voice_engine'"
                ),
                {"r": request_id},
            )
        ).one()
    return str(row[0]), row[1]


async def test_an_erasure_in_the_clients_own_workspace_erases_the_contact_and_records_it(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    _provisioned(monkeypatch)
    tenant_id, request_id, phone = await _erased_with_platform_call(monkeypatch)

    async with tenant_session(tenant_id) as session:
        proof = (
            await session.execute(
                text("SELECT proof FROM deletion_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar_one()
    assert proof["engine_deletion"] == VOICE_PLATFORM_ERASURE_REQUESTED
    assert proof["actions"]["voice_platform"].endswith(VOICE_PLATFORM_ERASURE_SENTENCE)
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)
    assert phone not in json.dumps(payload), "the subject travels sealed"
    assert (await _task_status(tenant_id, request_id))[0] == "open"

    assert await jobs.erase_engine_contact({}, payload) == "contacts=1 recordings_pending=0"

    assert [(m, p, h) for m, p, h, _ in vendor.requests] == [
        ("GET", "/contacts", WORKSPACE),
        ("DELETE", "/contacts/cust_1", WORKSPACE),
    ]
    assert await _task_status(tenant_id, request_id) == ("confirmed", "cust_1=0")


async def test_recordings_still_queued_leave_the_task_awaiting_an_answer(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    _provisioned(monkeypatch)
    vendor.delete_status = 200
    tenant_id, request_id, _phone = await _erased_with_platform_call(monkeypatch)
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)

    assert await jobs.erase_engine_contact({}, payload) == "contacts=1 recordings_pending=1"
    assert await _task_status(tenant_id, request_id) == ("requested", "cust_1=1")


async def test_no_contact_on_the_number_is_confirmed_as_nothing_held(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    _provisioned(monkeypatch)
    vendor.contacts = []
    tenant_id, request_id, _phone = await _erased_with_platform_call(monkeypatch)
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)

    assert await jobs.erase_engine_contact({}, payload) == "contacts=0 recordings_pending=0"
    assert await _task_status(tenant_id, request_id) == ("confirmed", "no-contact")


async def test_an_erasure_job_never_reaches_a_workspace_that_is_not_the_clients(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    _provisioned(monkeypatch)
    tenant_id, _request_id, _phone = await _erased_with_platform_call(monkeypatch)
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)
    _provisioned(monkeypatch, None)

    assert await jobs.erase_engine_contact({}, payload) == "not_provisioned"
    assert vendor.requests == []


async def test_a_failed_erasure_is_retried_then_alarmed(
    monkeypatch: pytest.MonkeyPatch, vendor: FakeWorkspaceVendor
) -> None:
    _provisioned(monkeypatch)
    tenant_id, _request_id, _phone = await _erased_with_platform_call(monkeypatch)
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)
    vendor.fail = True
    raised: list[str] = []
    monkeypatch.setattr(jobs, "alert", lambda _k, code, **_kw: raised.append(code))

    with pytest.raises(Retry):
        await jobs.erase_engine_contact({"job_try": 1}, payload)
    with pytest.raises(ProblemError):
        await jobs.erase_engine_contact({"job_try": 3}, payload)
    assert raised == ["engine_contact_erasure_failed"]

    payload["subject"] = {"ciphertext": "x"}
    with pytest.raises(ProblemError) as unreadable:
        await jobs.erase_engine_contact({"job_try": 1}, payload)
    assert unreadable.value.code == "engine_erasure_subject_unreadable"
