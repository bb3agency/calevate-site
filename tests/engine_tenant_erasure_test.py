"""An erased account's data at ThinnestAI is deleted by code (D-922).

The tenant erasure reads the numbers its calls in our developer workspace reached BEFORE it
clears them, opens the `voice_engine` task and queues `erase_tenant_at_engine`; the job
deletes the account's agents, the developer-workspace contacts only its own calls created,
and its own customer workspace, then confirms the task. The vendor is
`tests/thinnest_fake_account.py`; shapes from `thinnest-findings/mirror/snapshots/
2026-10-28/pages/api-reference/` (`agents/delete-agent.md`, `contacts/delete-contact.md`,
`customers/delete-customer.md`).
"""

from __future__ import annotations

import json
import secrets
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.compliance import engine_tenant_erasure as owed
from apps.api.compliance.engine_tenant_erasure import (
    ENGINE_ERASURE_OWED,
    VOICE_PLATFORM_ACCOUNT_DELETION,
    VOICE_PLATFORM_ACCOUNT_SENTENCE,
)
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_customers import thinnest_customers
from apps.api.engine.thinnest_workspace import (
    WorkspaceScopeError,
    tenant_erasure_in_developer_workspace,
    workspace_headers,
)
from apps.workers import engine_tenant_erasure as jobs
from apps.workers import retention
from apps.workers.settings import WorkerSettings
from sqlalchemy import text
from tests import tenant_erasure_test as te
from tests.conftest import create_org_with_receptionist
from tests.thinnest_fake_account import DEVELOPER, FakeAccount
from tests.workspace_support import give_own_workspace


@pytest.fixture(autouse=True)
def _developer_known(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_developer_workspace_id", DEVELOPER)


#: Route refs are unique across the whole table, and a lane database outlives one run.
RUN = uuid.uuid4().hex[:8]
MINE, OTHER, WAITS = f"agt_mine_{RUN}", f"agt_other_{RUN}", f"agt_waits_{RUN}"


def _number() -> str:
    return f"+9198{secrets.randbelow(10**8):08d}"


async def _tenant(name: str) -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name=name,
        slug=f"ete-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"]))


async def _route(tenant_id: UUID, agent_id: UUID, ref: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :r, :t, :a, true, now(), "
                "now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )


async def _call(
    tenant_id: UUID, agent_id: UUID, *, to: str, handle: str, copied: bool = True
) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, recording_url, "
                "created_at, updated_at) VALUES (:id, :t, :a, :e, 'outbound', 'completed', "
                "'+911140000000', :to, now(), now(), 61, :rec, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": handle,
                "to": to,
                "rec": f"recordings/{tenant_id}/{call_id}.wav" if copied else None,
            },
        )
    return call_id


async def _erase(tenant_id: UUID) -> UUID:
    await te._churn(tenant_id)
    token = await te._admin()
    filed = await te._post(token, tenant_id, confirm=te._confirm(tenant_id))
    assert filed.status_code == 201, filed.text
    request_id = filed.json()["request_id"]
    await te._run_worker(tenant_id, request_id)
    return UUID(str(request_id))


async def _task(tenant_id: UUID, request_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    "SELECT status, vendor_refs, vendor_reference, note FROM "
                    "processor_erasure_tasks WHERE request_ref = :r AND processor = 'voice_engine'"
                ),
                {"r": request_id},
            )
        ).one()


async def _payloads(tenant_id: UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = 'erase_tenant_at_engine' "
                    "AND payload->>'tenant_id' = :t ORDER BY created_at"
                ),
                {"t": str(tenant_id)},
            )
        ).scalars()
        return [dict(row) for row in rows]


def _sent(account: FakeAccount, method: str, prefix: str) -> list[tuple[str, str | None]]:
    return [
        (s.path, s.workspace)
        for s in account.sent
        if s.method == method and s.path.startswith(prefix)
    ]


# --- a free trial: everything is in our developer workspace ------------------------------


async def test_a_trial_erasure_deletes_its_agent_and_only_its_own_contacts(
    account: FakeAccount,
) -> None:
    tenant_id, agent_id = await _tenant("Trial to erase")
    other_id, other_agent = await _tenant("Another trial")
    mine, shared, stranger = _number(), _number(), _number()
    await _route(tenant_id, agent_id, MINE)
    await _route(other_id, other_agent, OTHER)
    call_id = await _call(tenant_id, agent_id, to=mine, handle=f"out_{uuid.uuid4()}")
    await _call(tenant_id, agent_id, to=shared, handle=f"out_{uuid.uuid4()}")
    await _call(other_id, other_agent, to=shared, handle=f"out_{uuid.uuid4()}")
    dev = account.ws(None)
    dev.agents |= {MINE, OTHER}
    dev.contacts.update(
        {"cust_mine": mine[1:], "cust_shared": shared[1:], "cust_stranger": stranger[1:]}
    )

    request_id = await _erase(tenant_id)

    # The erasure cleared our copy of the numbers; the job can only have found the contact
    # because they were read before that.
    async with tenant_session(tenant_id) as session:
        cleared = (
            await session.execute(text("SELECT to_e164 FROM calls WHERE id = :c"), {"c": call_id})
        ).scalar_one()
        proof = (
            await session.execute(
                text("SELECT proof FROM tenant_erasure_requests WHERE id = :r"), {"r": request_id}
            )
        ).scalar_one()
    assert cleared is None
    assert proof["engine_deletion"] == VOICE_PLATFORM_ACCOUNT_DELETION
    assert proof["actions"]["voice_platform_account"] == VOICE_PLATFORM_ACCOUNT_SENTENCE
    task = await _task(tenant_id, request_id)
    assert (task.status, task.vendor_refs, task.vendor_reference) == (
        "open",
        [MINE],
        ENGINE_ERASURE_OWED,
    )
    [payload] = await _payloads(tenant_id)
    assert len(payload["subjects"]) == 2
    flat = json.dumps(payload)
    assert mine[1:] not in flat and shared[1:] not in flat  # hard rule 6: sealed, never clear

    result = await jobs.erase_tenant_at_engine({}, payload)

    assert result == "agents=1 contacts=1 workspace=none confirmed=True"
    assert dev.agents == {OTHER}
    assert set(dev.contacts) == {"cust_shared", "cust_stranger"}
    assert _sent(account, "DELETE", "/agents/") == [(f"/agents/{MINE}", None)]
    assert _sent(account, "DELETE", "/contacts/") == [("/contacts/cust_mine", None)]
    assert not _sent(account, "DELETE", "/customers")
    assert (await _task(tenant_id, request_id)).status == "confirmed"
    # Idempotent: a settled task is not acted on again.
    assert await jobs.erase_tenant_at_engine({}, payload) == "already_settled"


async def test_nothing_is_deleted_while_a_recording_copy_of_ours_is_missing(
    account: FakeAccount,
) -> None:
    tenant_id, agent_id = await _tenant("Trial waiting for a copy")
    mine = _number()
    await _route(tenant_id, agent_id, WAITS)
    await _call(tenant_id, agent_id, to=mine, handle=f"out_{uuid.uuid4()}", copied=False)
    account.ws(None).agents.add(WAITS)
    account.ws(None).contacts["cust_waits"] = mine[1:]
    request_id = await _erase(tenant_id)
    [payload] = await _payloads(tenant_id)

    assert await jobs.erase_tenant_at_engine({}, payload) == "held calls_waiting=1"

    assert WAITS in account.ws(None).agents
    assert "cust_waits" in account.ws(None).contacts
    task = await _task(tenant_id, request_id)
    assert task.vendor_reference == "cust_waits=held"
    # The nightly sweep asks again, with no numbers; the recorded contact is enough.
    assert (await retention.sweep_tenant(tenant_id))["engine_tenant_erasures_requeued"] == 1
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET ended_at = now() - interval '400 days', "
                "created_at = now() - interval '400 days'"
            )
        )
    again = {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    assert await jobs.erase_tenant_at_engine({}, again) == (
        "agents=1 contacts=1 workspace=none confirmed=True"
    )
    assert "cust_waits" not in account.ws(None).contacts


# --- a paying client: its own workspace -------------------------------------------------


async def _paying(account: FakeAccount, name: str) -> tuple[UUID, str, str]:
    """(tenant, its agent's raw vendor id, its own workspace), the workspace offboarding."""
    tenant_id, agent_id = await _tenant(name)
    paid = f"agt_paid_{uuid.uuid4().hex[:12]}"
    workspace = account.add_customer(f"calevate-{tenant_id}")
    await give_own_workspace(tenant_id, workspace=workspace)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE tenant_engine_workspaces SET status = 'offboarding' WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    await _route(tenant_id, agent_id, f"{paid}@{workspace}")
    account.ws(workspace).agents.add(paid)
    return tenant_id, paid, workspace


async def test_a_paying_erasure_deletes_its_agents_and_its_own_workspace(
    account: FakeAccount,
) -> None:
    tenant_id, paid, workspace = await _paying(account, "Paying to erase")
    request_id = await _erase(tenant_id)
    task = await _task(tenant_id, request_id)
    assert task.vendor_refs == [paid]  # the raw id: `vendor_refs` takes no `@`
    [payload] = await _payloads(tenant_id)
    assert payload["subjects"] == []

    result = await jobs.erase_tenant_at_engine({}, payload)

    assert result == "agents=1 contacts=0 workspace=deleted confirmed=True"
    assert _sent(account, "DELETE", "/agents/") == [(f"/agents/{paid}", workspace)]
    assert _sent(account, "DELETE", "/customers/") == [(f"/customers/{workspace}", None)]
    assert account.customers[workspace]["archivedAt"] is not None
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM tenant_engine_workspaces WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
        assert await owed.owed_tenant_engine_erasures(session) == []
    assert status == "deleted"
    assert (await _task(tenant_id, request_id)).status == "confirmed"


async def test_a_workspace_still_renting_a_number_stays_owed_and_is_asked_again(
    account: FakeAccount,
) -> None:
    tenant_id, _paid, workspace = await _paying(account, "Still renting")
    number = f"9180{secrets.randbelow(10**8):08d}"
    account.hold(workspace, number)
    request_id = await _erase(tenant_id)
    [payload] = await _payloads(tenant_id)

    result = await jobs.erase_tenant_at_engine({}, payload)

    assert result == "agents=1 contacts=0 workspace=holds_numbers confirmed=False"
    assert account.customers[workspace]["archivedAt"] is None
    assert (await _task(tenant_id, request_id)).status in ("open", "requested")
    assert (await retention.sweep_tenant(tenant_id))["engine_tenant_erasures_requeued"] == 1

    del account.ws(workspace).numbers[number]  # the offboarding released it
    again = {"tenant_id": str(tenant_id), "request_id": str(request_id)}
    assert await jobs.erase_tenant_at_engine({}, again) == (
        "agents=1 contacts=0 workspace=deleted confirmed=True"
    )


# --- never the developer workspace ------------------------------------------------------


async def test_the_developer_workspace_is_never_deleted(
    account: FakeAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    with pytest.raises(WorkspaceScopeError):
        await thinnest_customers().delete(DEVELOPER)
    assert not account.sent

    # A workspace row naming our developer workspace, as a provisioning defect would leave.
    developer = f"org_dev-{RUN}"
    monkeypatch.setattr(get_settings(), "thinnest_developer_workspace_id", None)
    tenant_id, agent_id = await _tenant("Mis-filed workspace")
    await give_own_workspace(tenant_id, workspace=developer, status="active")
    monkeypatch.setattr(get_settings(), "thinnest_developer_workspace_id", developer)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE tenant_engine_workspaces SET status = 'offboarding' WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    await _route(tenant_id, agent_id, f"agt_misfiled_{RUN}")
    request_id = await _erase(tenant_id)
    [payload] = await _payloads(tenant_id)

    result = await jobs.erase_tenant_at_engine({}, payload)

    assert result.endswith("workspace=refused confirmed=False")
    assert not _sent(account, "DELETE", "/customers")
    assert (await _task(tenant_id, request_id)).status != "confirmed"


def test_contact_routes_reach_the_developer_workspace_only_inside_an_erasure() -> None:
    for method, route in (("GET", "/contacts"), ("DELETE", "/contacts/{id}")):
        with pytest.raises(ProblemError) as refused:
            workspace_headers(method, route, None)
        assert refused.value.code == "engine_workspace_not_provisioned"
        with tenant_erasure_in_developer_workspace():
            assert workspace_headers(method, route, None) == {}
    with tenant_erasure_in_developer_workspace(), pytest.raises(ProblemError):
        workspace_headers("POST", "/do-not-call", None)


# --- wiring -----------------------------------------------------------------------------


def test_the_job_is_registered_under_the_name_the_erasure_queues() -> None:
    assert owed.TENANT_ENGINE_ERASURE_JOB == jobs.TENANT_ENGINE_ERASURE_JOB
    names = {getattr(f, "__name__", None) for f in WorkerSettings.functions}
    assert jobs.TENANT_ENGINE_ERASURE_JOB in names
