"""A client's data in its own ThinnestAI workspace (D-693): DNC and erasure light up, the
erasure keeps every contact's pending recordings across retries, a workspace 404 is not an
erased contact, a delivery is keyed in its agent's workspace, and an action from another
workspace is refused."""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.compliance.service import add_to_dnc
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest_customer_data import (
    ThinnestCustomerData,
    set_thinnest_customer_data,
)
from apps.api.worker.engine_actions import workspace_matches
from apps.workers import engine_customer_data as jobs
from apps.workers import retention
from arq import Retry
from calevate_shared.engine_scope import scoped_handle
from signed_intake import SIGNED_INTAKES, keyed_event
from tests.engine_customer_data_test import (
    FakeWorkspaceVendor,
    _outbox,
    _phone,
    _task_status,
    _tenant,
)
from tests.workspace_support import give_own_workspace

pytestmark = [pytest.mark.rls]


class ContactVendor(FakeWorkspaceVendor):
    """Per-contact answers: `None` is a 204, an int is `200 {recordingsPending}`, and a
    contact in `fail` answers 503 (nothing deleted)."""

    def __init__(self) -> None:
        super().__init__()
        self.pending: dict[str, int | None] = {}
        self.failing: set[str] = set()
        self.workspace_gone = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/api/v1")
        if path.startswith("/contacts/") and request.method == "DELETE":
            self.requests.append(
                (request.method, path, request.headers.get("Thinnest-Workspace"), None)
            )
            contact = path.split("/")[2]
            if self.workspace_gone:
                return httpx.Response(
                    404, json={"error": "Workspace not found.", "code": "workspace_not_found"}
                )
            if contact in self.failing:
                return httpx.Response(503, json={"error": "down", "code": "unavailable"})
            self.contacts = [c for c in self.contacts if c != contact]
            n = self.pending.get(contact)
            if n is None:
                return httpx.Response(204)
            return httpx.Response(200, json={"recordingsPending": n})
        return super().handler(request)


@pytest.fixture
def vendor() -> Any:
    fake = ContactVendor()
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


def _ws() -> str:
    return f"org_{uuid.uuid4().hex}"


# --- DNC and erasure light up once the resolver answers the tenant's own workspace ---------


async def test_a_suppression_reaches_the_clients_own_workspace_once_it_has_one(
    monkeypatch: pytest.MonkeyPatch, vendor: ContactVendor
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id = await _tenant()
    phone = _phone()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="manual")
    assert await _outbox(jobs.ENGINE_DNC_PUSH_JOB, tenant_id) == [], "not provisioned: ours only"

    workspace = await give_own_workspace(tenant_id, workspace=_ws())
    second = _phone()
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=second, source="manual")
    [payload] = await _outbox(jobs.ENGINE_DNC_PUSH_JOB, tenant_id)
    assert await jobs.push_engine_dnc({}, payload) == "pushed=1"
    assert [(m, p, h) for m, p, h, _ in vendor.requests] == [("POST", "/do-not-call", workspace)]


async def _erasure(monkeypatch: pytest.MonkeyPatch, *, provisioned: bool) -> tuple[UUID, UUID, str]:
    from tests.thinnest_erasure_test import _request, _tenant_with_a_platform_call

    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id, _call_id, phone, _ecid = await _tenant_with_a_platform_call()
    workspace = await give_own_workspace(tenant_id, workspace=_ws()) if provisioned else ""
    request_id = await _request(tenant_id, phone)
    await retention.execute_deletion_request(
        {}, {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    )
    return tenant_id, request_id, workspace


async def test_an_erasure_reaches_the_clients_own_workspace_once_it_has_one(
    monkeypatch: pytest.MonkeyPatch, vendor: ContactVendor
) -> None:
    tenant_id, request_id, workspace = await _erasure(monkeypatch, provisioned=True)
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)
    assert await jobs.erase_engine_contact({}, payload) == "contacts=1 recordings_pending=0"
    assert {h for _m, _p, h, _b in vendor.requests} == {workspace}
    assert await _task_status(tenant_id, request_id) == ("confirmed", "cust_1=0")


# --- audit fix 7: the pending count survives a retry -----------------------------------------


async def test_a_retried_erasure_keeps_what_earlier_attempts_left_pending(
    monkeypatch: pytest.MonkeyPatch, vendor: ContactVendor
) -> None:
    vendor.contacts = ["ct_a", "ct_b"]
    vendor.pending = {"ct_a": 2}
    vendor.failing = {"ct_b"}
    tenant_id, request_id, _workspace = await _erasure(monkeypatch, provisioned=True)
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)

    with pytest.raises(Retry):
        await jobs.erase_engine_contact({"job_try": 1}, payload)
    assert await _task_status(tenant_id, request_id) == ("requested", "ct_a=2")

    vendor.failing = set()
    assert await jobs.erase_engine_contact({"job_try": 2}, payload) == (
        "contacts=1 recordings_pending=2"
    )
    assert await _task_status(tenant_id, request_id) == ("requested", "ct_a=2,ct_b=0")

    # Nothing left to find: the earlier attempts' pending recording still holds the task.
    assert await jobs.erase_engine_contact({"job_try": 3}, payload) == (
        "contacts=0 recordings_pending=2"
    )
    assert (await _task_status(tenant_id, request_id))[0] == "requested"


async def test_an_empty_retry_after_a_clean_delete_does_not_confirm(
    monkeypatch: pytest.MonkeyPatch, vendor: ContactVendor
) -> None:
    vendor.contacts = ["ct_a", "ct_b"]
    vendor.failing = {"ct_b"}
    tenant_id, request_id, _workspace = await _erasure(monkeypatch, provisioned=True)
    [payload] = await _outbox(jobs.ENGINE_CONTACT_ERASURE_JOB, tenant_id)
    with pytest.raises(Retry):
        await jobs.erase_engine_contact({"job_try": 1}, payload)
    vendor.failing = set()
    vendor.contacts = []
    await jobs.erase_engine_contact({"job_try": 2}, payload)
    assert (await _task_status(tenant_id, request_id))[0] == "requested"


# --- audit fix 8: a missing WORKSPACE is not an erased contact ------------------------------


async def test_a_404_for_the_workspace_is_not_an_erased_contact(vendor: ContactVendor) -> None:
    from apps.api.engine.thinnest_customer_data import thinnest_customer_data

    client = thinnest_customer_data()
    vendor.pending = {"ct_gone": None}
    assert await client.delete_contact("org_ok", "ct_gone") == 0
    vendor.workspace_gone = True
    with pytest.raises(ProblemError):
        await client.delete_contact("org_gone", "ct_1")


# --- deliveries and actions ---------------------------------------------------------------


def test_a_delivery_for_a_client_agent_is_keyed_in_its_workspace() -> None:
    intake = SIGNED_INTAKES["thinnest"]
    agent = scoped_handle("ag_7", "org_client")
    data = {"id": "out_9", "agent": {"id": "ag_7"}, "analysedAt": "T"}
    keyed = keyed_event(
        intake, {"id": "evt_1", "event": "call.analysed", "data": data}, engine_agent_ref=agent
    )
    assert not isinstance(keyed, str)
    assert keyed.execution_id == "out_9@org_client"
    other = keyed_event(
        intake,
        {"id": "evt_2", "event": "call.analysed", "data": {**data, "agent": {"id": "ag_8"}}},
        engine_agent_ref=agent,
    )
    assert other == "agent mismatch"
    legacy = keyed_event(
        intake, {"id": "evt_3", "event": "call.analysed", "data": data}, engine_agent_ref="ag_7"
    )
    assert not isinstance(legacy, str) and legacy.execution_id == "out_9"


@pytest.mark.parametrize(
    ("ref", "header", "ok"),
    [
        ("ag_1@org_a", "org_a", True),
        ("ag_1@org_a", None, True),
        ("ag_1@org_a", "org_b", False),
        ("ag_1", "org_developer", True),
    ],
)
def test_an_action_from_another_workspace_is_refused(
    ref: str, header: str | None, ok: bool
) -> None:
    assert workspace_matches(ref, header) is ok
