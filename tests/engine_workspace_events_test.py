"""`contact.erased` and `byok.changed`: signed, deduped on the event id, attributed to one
client by its workspace, and acted on (D-798).

Payloads as `thinnest-findings/mirror/snapshots/2026-10-15/pages/api-reference/webhooks.md:
536-597` documents them; delivery and signing as every other event (`:36-41`, `:210-226`).
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
import signed_intake
import webhook_routes
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest import ThinnestEngine
from apps.api.engine.thinnest_webhooks import SUBSCRIBED_EVENTS
from apps.api.reliability.engine_intake_keys import seal_delivery
from apps.api.reliability.service import body_hash, claim_inbox_event
from apps.workers import engine_workspace_events as events
from apps.workers.settings import WorkerSettings
from arq import Retry
from calevate_shared.engine_scope import scoped_handle
from signed_intake import SIGNED_INTAKES, keyed_event
from sqlalchemy import text
from tests.smoke_pipeline_test import _seed_tenant
from tests.thinnest_intake_security_test import (  # noqa: F401 - `captured` is a fixture
    _agent_with_secret,
    _post,
    _signed,
    captured,
)
from tests.workspace_support import give_own_workspace

ENGINE = "thinnest"


@pytest.fixture(autouse=True)
def adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(events, "get_engine", lambda: ThinnestEngine(api_key="ta_x"))


def _erased(contact: str = "cust_1", **data: Any) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex[:10]}",
        "event": "contact.erased",
        "sentAt": "2026-10-15T02:30:11Z",
        "data": {"contactId": contact, "erasedAt": "2026-10-14T11:42:05Z", **data},
    }


def _byok(change: str = "key_removed", **data: Any) -> dict[str, Any]:
    return {
        "id": f"evt_{uuid.uuid4().hex[:10]}",
        "event": "byok.changed",
        "data": {
            "change": change,
            "kind": "tts",
            "provider": "cartesia",
            "byokEnabled": False,
            "scope": None,
            **data,
        },
    }


async def _route(workspace: str | None) -> tuple[UUID, str]:
    tenant_id, agent_id = await _seed_tenant(f"fakeagent_{uuid.uuid4().hex[:10]}")
    ref = scoped_handle(f"ag_{uuid.uuid4()}", workspace)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :ref, :tid, :aid, true, "
                "now(), now())"
            ),
            {"ref": ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id, ref


def _job(ref: str, body: dict[str, Any]) -> dict[str, Any]:
    unit = str(body["id"])
    return {
        "engine": ENGINE,
        "execution_id": unit,
        "raw_status": body["event"],
        "engine_agent_ref": ref,
        "delivery": seal_delivery(
            json.dumps(body), engine=ENGINE, execution_id=unit, event_name=f"{body['event']}:{unit}"
        ),
    }


async def _inbox_row() -> UUID:
    key = f"evt_{uuid.uuid4().hex}:contact.erased"
    async with untenanted_session() as session:
        claim = await claim_inbox_event(
            session, provider=ENGINE, event_key=key, payload_hash=body_hash({"k": key})
        )
    return claim.row_id


async def _inbox_status(row_id: UUID) -> str:
    async with untenanted_session() as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM webhook_inbox_events WHERE id = :id"), {"id": row_id}
                )
            ).scalar_one()
        )


async def _waiting_task(tenant_id: UUID, reference: str) -> UUID:
    task_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO processor_erasure_tasks (id, tenant_id, request_ref, request_kind, "
                "processor, status, requested_at, subject_ref, vendor_refs, vendor_reference) "
                "VALUES (:id, :t, :r, 'subject', 'voice_engine', 'requested', now(), 'h', "
                "'[]'::jsonb, :v)"
            ),
            {"id": task_id, "t": tenant_id, "r": uuid.uuid4(), "v": reference},
        )
    return task_id


async def _task(tenant_id: UUID, task_id: UUID) -> tuple[str, str]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, vendor_reference FROM processor_erasure_tasks WHERE id = :i"),
                {"i": task_id},
            )
        ).one()
    return str(row[0]), str(row[1])


# --- subscription and intake ---------------------------------------------------------------


def test_both_events_are_subscribed_and_routed_to_one_registered_job() -> None:
    assert {"contact.erased", "byok.changed"} <= set(SUBSCRIBED_EVENTS)
    routes = SIGNED_INTAKES[ENGINE].events
    for event in ("contact.erased", "byok.changed"):
        assert routes[event].call_fields == ()
        assert routes[event].job == signed_intake.ENGINE_WORKSPACE_EVENT_JOB
    assert events.ENGINE_WORKSPACE_EVENT_JOB == signed_intake.ENGINE_WORKSPACE_EVENT_JOB
    assert webhook_routes.ENGINE_WORKSPACE_EVENT_JOB == signed_intake.ENGINE_WORKSPACE_EVENT_JOB
    registered = {getattr(fn, "__qualname__", "") for fn in WorkerSettings.functions}
    assert events.ENGINE_WORKSPACE_EVENT_JOB in registered


def test_a_workspace_event_is_keyed_on_its_event_id_in_the_endpoints_workspace() -> None:
    intake = SIGNED_INTAKES[ENGINE]
    body = _erased()
    keyed = keyed_event(intake, body, engine_agent_ref="ag_1@org_a")
    assert not isinstance(keyed, str)
    assert keyed.execution_id == body["id"]
    assert keyed.event_name == f"contact.erased:{body['id']}"
    # A delivery about another client's workspace, signed by this client's endpoint.
    assert (
        keyed_event(intake, _erased(workspaceId="org_b"), engine_agent_ref="ag_1@org_a")
        == "workspace mismatch"
    )
    same = keyed_event(intake, _erased(workspaceId="org_a"), engine_agent_ref="ag_1@org_a")
    assert not isinstance(same, str)
    developer = keyed_event(intake, _byok(workspaceId="org_b"), engine_agent_ref="ag_1")
    assert not isinstance(developer, str)


async def test_a_signed_delivery_is_acked_queued_once_and_deduped(
    captured: list[dict[str, Any]],  # noqa: F811
) -> None:
    secret = f"s3cr3t-{uuid.uuid4().hex}"
    ref = await _agent_with_secret(secret)
    body = json.dumps(_byok()).encode()

    first = await _post(body, ref=ref, signed=_signed(body, secret))
    again = await _post(body, ref=ref, signed=_signed(body, secret, attempt=2))
    forged = await _post(body, ref=ref, signed=_signed(body, "not-the-secret"))

    assert first.status_code == 202 and first.json()["status"] == "accepted"
    assert again.json()["status"] == "duplicate"
    assert forged.status_code == 401
    [job] = captured
    event_id = json.loads(body)["id"]
    assert job["job"] == signed_intake.ENGINE_WORKSPACE_EVENT_JOB
    assert job["job_id"] == (
        f"{signed_intake.ENGINE_WORKSPACE_EVENT_JOB}:{ENGINE}:{event_id}:byok.changed:{event_id}"
    )
    assert job["payload"]["engine_agent_ref"] == ref


# --- contact.erased -------------------------------------------------------------------------


async def test_contact_erased_closes_only_its_own_clients_task() -> None:
    workspace = f"org_{uuid.uuid4().hex}"
    tenant_id, ref = await _route(workspace)
    await give_own_workspace(tenant_id, workspace=workspace)
    other_tenant, _other_ref = await _route(None)
    mine = await _waiting_task(tenant_id, "cust_1=1,cust_2=0")
    theirs = await _waiting_task(other_tenant, "cust_1=1")
    payload = {**_job(ref, _erased("cust_1")), "inbox_row_id": str(await _inbox_row())}

    assert await events.ingest_engine_workspace_event({}, payload) == "tasks=1"

    assert await _task(tenant_id, mine) == ("confirmed", "cust_1=0,cust_2=0")
    # The same contact id in another client's task is not touched: their workspace's is not
    # the one that said so.
    assert await _task(other_tenant, theirs) == ("requested", "cust_1=1")
    assert await _inbox_status(UUID(payload["inbox_row_id"])) == "processed"


async def test_contact_erased_from_a_developer_wide_endpoint_finds_the_client() -> None:
    workspace = f"org_{uuid.uuid4().hex}"
    tenant_id, _ref = await _route(None)
    await give_own_workspace(tenant_id, workspace=workspace)
    _developer_tenant, developer_ref = await _route(None)
    task_id = await _waiting_task(tenant_id, "cust_9=1")
    payload = _job(developer_ref, _erased("cust_9", workspaceId=workspace))
    assert await events.ingest_engine_workspace_event({}, payload) == "tasks=1"
    assert (await _task(tenant_id, task_id))[1] == "cust_9=0"


async def test_contact_erased_that_no_client_owns_changes_nothing() -> None:
    _tenant, developer_ref = await _route(None)
    assert (
        await events.ingest_engine_workspace_event({}, _job(developer_ref, _erased()))
        == "developer_workspace"
    )
    stranger = _job(developer_ref, _erased(workspaceId=f"org_{uuid.uuid4().hex}"))
    assert await events.ingest_engine_workspace_event({}, stranger) == "unattributable"


async def test_an_endpoint_naming_another_clients_workspace_is_refused() -> None:
    mine = f"org_{uuid.uuid4().hex}"
    tenant_id, ref = await _route(mine)
    await give_own_workspace(tenant_id, workspace=mine)
    other_ws = f"org_{uuid.uuid4().hex}"
    other_tenant, _ = await _route(None)
    await give_own_workspace(other_tenant, workspace=other_ws)
    task_id = await _waiting_task(other_tenant, "cust_1=1")

    body = _job(ref, _erased("cust_1", workspaceId=other_ws))
    assert await events.ingest_engine_workspace_event({}, body) == "workspace_mismatch"
    assert await _task(other_tenant, task_id) == ("requested", "cust_1=1")

    # An endpoint whose route belongs to one tenant, scoped to another tenant's workspace.
    stray_tenant, stray_ref = await _route(other_ws)
    assert stray_tenant != other_tenant
    assert (
        await events.ingest_engine_workspace_event({}, _job(stray_ref, _erased("cust_1")))
        == "workspace_mismatch"
    )
    assert await _task(other_tenant, task_id) == ("requested", "cust_1=1")


async def test_an_unreadable_delivery_is_failed_and_not_retried() -> None:
    _tenant, ref = await _route(None)
    row = await _inbox_row()
    for broken in (
        {**_job(ref, _erased()), "delivery": None},
        _job(ref, {"id": "evt_x", "event": "contact.erased", "data": {}}),
    ):
        broken["inbox_row_id"] = str(row)
        with pytest.raises(ProblemError):
            await events.ingest_engine_workspace_event({"job_try": 1}, broken)
    assert await _inbox_status(row) == "failed"


async def test_a_failing_attribution_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    _tenant, ref = await _route(None)

    async def _down(_workspace: str) -> UUID | None:
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(events, "tenant_for_workspace", _down)
    payload = _job(ref, _erased(workspaceId=f"org_{uuid.uuid4().hex}"))
    with pytest.raises(Retry):
        await events.ingest_engine_workspace_event({"job_try": 1}, payload)
    with pytest.raises(RuntimeError):
        await events.ingest_engine_workspace_event({"job_try": 3}, payload)


# --- byok.changed ---------------------------------------------------------------------------


class Checks:
    def __init__(self) -> None:
        self.ran: list[tuple[str, Any]] = []

    async def studio(self, _engine: Any, tenant_id: UUID, workspace: str) -> str:
        self.ran.append(("studio", workspace))
        return "repaired"

    async def own_model(self, _engine: Any, tenant_id: UUID, workspace: str) -> str:
        self.ran.append(("own_model", workspace))
        return "ok"

    async def developer(self, _engine: Any) -> str:
        self.ran.append(("developer", None))
        return "ok"

    async def developer_own_model(self, _engine: Any) -> str:
        self.ran.append(("developer_own_model", None))
        return "ok"


def _keys_engine() -> Any:
    """A voice-hosting engine that also runs our own model (`RunsOwnModel`)."""
    from tests.hosted_voice_fakes import HostingEngine

    class KeysEngine(HostingEngine):
        async def install_own_model_key(self, *, provider: str, api_key: str, model: str) -> None:
            return None

        async def enable_own_model_key(self) -> Any:
            return self.key_state

        async def set_agent_own_keys(
            self, ref: str, *, own_voice: bool, own_model: str | None
        ) -> None:
            return None

    return KeysEngine()


@pytest.fixture
def checks(monkeypatch: pytest.MonkeyPatch) -> Checks:
    recorder = Checks()
    engine = _keys_engine()
    monkeypatch.setattr(events, "hosting_engine", lambda: engine)
    monkeypatch.setattr(events, "check_studio_workspace", recorder.studio)
    monkeypatch.setattr(events, "check_own_model_workspace", recorder.own_model)
    monkeypatch.setattr(events, "check_developer_studio", recorder.developer)
    monkeypatch.setattr(events, "check_developer_own_model", recorder.developer_own_model)
    return recorder


async def _keys_of_ours(tenant_id: UUID, *, studio: bool, own_model: bool) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE tenant_engine_workspaces SET "
                "studio_enabled_at = CASE WHEN :s THEN now() END, "
                "own_model_enabled_at = CASE WHEN :m THEN now() END WHERE tenant_id = :t"
            ),
            {"s": studio, "m": own_model, "t": tenant_id},
        )


async def test_byok_changed_runs_that_workspaces_checks_at_once(checks: Checks) -> None:
    workspace = f"org_{uuid.uuid4().hex}"
    tenant_id, ref = await _route(workspace)
    await give_own_workspace(tenant_id, workspace=workspace)
    await _keys_of_ours(tenant_id, studio=True, own_model=True)

    result = await events.ingest_engine_workspace_event({}, _job(ref, _byok()))

    assert result == "studio=repaired own_model=ok"
    assert checks.ran == [("studio", workspace), ("own_model", workspace)]
    # The lease is given back.
    assert await get_redis().get(f"calevate:byok-check:{workspace}") is None


async def test_byok_changed_in_a_workspace_holding_none_of_our_keys_writes_nothing(
    checks: Checks,
) -> None:
    workspace = f"org_{uuid.uuid4().hex}"
    tenant_id, ref = await _route(workspace)
    await give_own_workspace(tenant_id, workspace=workspace)
    assert (
        await events.ingest_engine_workspace_event({}, _job(ref, _byok("key_added")))
        == "no_keys_of_ours"
    )
    assert checks.ran == []


async def test_byok_changed_in_our_developer_workspace_checks_both_our_keys(
    checks: Checks,
) -> None:
    """Our Cartesia key (D-727) and our Google key (D-834) both live there."""
    _tenant, ref = await _route(None)
    assert (
        await events.ingest_engine_workspace_event({}, _job(ref, _byok()))
        == "developer=ok own_model=ok"
    )
    assert checks.ran == [("developer", None), ("developer_own_model", None)]


async def test_a_workspace_no_longer_active_or_not_ours_is_left_alone(checks: Checks) -> None:
    workspace = f"org_{uuid.uuid4().hex}"
    tenant_id, ref = await _route(workspace)
    await give_own_workspace(tenant_id, workspace=workspace)
    await _keys_of_ours(tenant_id, studio=True, own_model=False)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE tenant_engine_workspaces SET status = 'offboarding' WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    assert await events.ingest_engine_workspace_event({}, _job(ref, _byok())) == "not_active"
    _developer, developer_ref = await _route(None)
    stranger = _job(developer_ref, _byok(workspaceId=f"org_{uuid.uuid4().hex}"))
    assert await events.ingest_engine_workspace_event({}, stranger) == "unattributable"
    assert checks.ran == []


async def test_a_check_already_running_holds_the_next_event_back(checks: Checks) -> None:
    workspace = f"org_{uuid.uuid4().hex}"
    tenant_id, ref = await _route(workspace)
    await give_own_workspace(tenant_id, workspace=workspace)
    await _keys_of_ours(tenant_id, studio=True, own_model=False)
    lease = f"calevate:byok-check:{workspace}"
    await get_redis().set(lease, "1", ex=60)
    try:
        with pytest.raises(Retry):
            await events.ingest_engine_workspace_event({"job_try": 1}, _job(ref, _byok()))
        assert (
            await events.ingest_engine_workspace_event({"job_try": 3}, _job(ref, _byok()))
            == "coalesced"
        )
        assert checks.ran == []
    finally:
        await get_redis().delete(lease)


def test_the_lease_outlives_the_longest_a_check_can_run() -> None:
    assert WorkerSettings.job_timeout < events.BYOK_LEASE_S


async def test_a_check_that_outlived_its_lease_leaves_the_next_holders_alone(
    checks: Checks, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace = f"org_{uuid.uuid4().hex}"
    tenant_id, ref = await _route(workspace)
    await give_own_workspace(tenant_id, workspace=workspace)
    await _keys_of_ours(tenant_id, studio=True, own_model=False)
    lease = f"calevate:byok-check:{workspace}"

    async def slow_check(_engine: Any, _tenant: UUID, _workspace: str) -> str:
        # The lease expires mid-check and the next event's check takes it.
        await get_redis().set(lease, "next-holder", ex=60)
        return "ok"

    monkeypatch.setattr(events, "check_studio_workspace", slow_check)
    try:
        assert await events.ingest_engine_workspace_event({}, _job(ref, _byok())) == "studio=ok"
        assert await get_redis().get(lease) == "next-holder"
    finally:
        await get_redis().delete(lease)


async def test_nothing_is_checked_on_an_engine_hosting_no_voices(
    checks: Checks, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(events, "hosting_engine", lambda: None)
    _tenant, ref = await _route(None)
    assert await events.ingest_engine_workspace_event({}, _job(ref, _byok())) == "not_hosted"
    assert checks.ran == []


async def test_our_own_write_echoes_back_as_ok_and_writes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The real Studio check on the echo of our own install: the workspace already reads as
    we want it, so it is recorded `ok`, nothing is installed and nothing alarms."""
    from apps.workers import studio_voice_key
    from tests.hosted_voice_fakes import READY_KEY, HostingEngine

    raised: list[str] = []
    monkeypatch.setattr(studio_voice_key, "alert", lambda _s, code, **_kw: raised.append(code))
    engine = HostingEngine(key_state=READY_KEY)
    monkeypatch.setattr(events, "hosting_engine", lambda: engine)
    workspace = f"org_{uuid.uuid4().hex}"
    tenant_id, ref = await _route(workspace)
    await give_own_workspace(tenant_id, workspace=workspace)
    await _keys_of_ours(tenant_id, studio=True, own_model=False)

    result = await events.ingest_engine_workspace_event(
        {}, _job(ref, _byok("key_replaced", byokEnabled=True, scope="voice"))
    )

    assert result == "studio=ok"
    assert engine.installed == [] and engine.enabled == 0
    assert raised == []
