"""Each voice-platform workspace keeps calls no longer than the client's own policy (D-798).

`callRetentionDays` is set to the shorter of the tenant's recording and transcript periods,
capped at the plan's `planRetentionDays` read from `GET /workspace`, never null; pushed at
provisioning and read back and repaired hourly (`thinnest-findings/mirror/snapshots/
2026-10-15/pages/api-reference/workspace/update-workspace.md:528-599`).
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_customer_data import (
    ThinnestCustomerData,
    set_thinnest_customer_data,
)
from apps.api.tenancy.engine_retention import (
    RETENTION_SYNC_JOB,
    call_content_days,
    queue_retention_sync,
    retention_to_send,
)
from apps.api.tenancy.engine_workspace import read_retention_record
from apps.workers import engine_retention
from apps.workers.settings import WorkerSettings
from arq import Retry
from sqlalchemy import text
from tests.engine_customer_data_test import _outbox, _tenant
from tests.workspace_support import give_own_workspace

DEVELOPER = "developer"


class RetentionVendor:
    """`GET`/`PATCH /workspace` per workspace (`developer` without the header)."""

    def __init__(self, plan: int = 30) -> None:
        self.plan = plan
        self.held: dict[str, int | None] = {}
        self.patches: list[tuple[str, int]] = []
        self.fail: set[str] = set()
        self.ignore_patch = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        workspace = request.headers.get("Thinnest-Workspace") or DEVELOPER
        if workspace in self.fail:
            return httpx.Response(503, json={"error": "down", "code": "unavailable"})
        if request.method == "PATCH":
            days = json.loads(request.content)["callRetentionDays"]
            if days > self.plan:
                return httpx.Response(400, json={"error": "too long", "code": "invalid"})
            self.patches.append((workspace, days))
            if not self.ignore_patch:
                self.held[workspace] = days
        return httpx.Response(
            200,
            json={
                "id": "org_x",
                "callRetentionDays": self.held.get(workspace),
                "planRetentionDays": self.plan,
            },
        )


@pytest.fixture
def vendor(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    fake = RetentionVendor()
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
    monkeypatch.setattr(engine_retention, "alert", lambda _stage, code, **_kw: raised.append(code))
    return raised


async def _developer_record() -> tuple[int | None, int | None, bool]:
    """What `platform_state` holds for the developer workspace: days, plan, whether read."""
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT developer_retention_days, developer_retention_plan_days, "
                    "developer_retention_checked_at IS NOT NULL FROM platform_state WHERE id = 1"
                )
            )
        ).one()
    return row[0], row[1], bool(row[2])


@pytest.fixture(autouse=True)
async def _developer_record_unread() -> Any:
    """`platform_state` is one row for every test: each starts and ends "never read"."""

    async def _clear() -> None:
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "UPDATE platform_state SET developer_retention_days = NULL, "
                    "developer_retention_plan_days = NULL, "
                    "developer_retention_checked_at = NULL WHERE id = 1"
                )
            )

    await _clear()
    yield
    await _clear()


async def _client_workspace() -> tuple[UUID, str]:
    tenant_id = await _tenant()
    workspace = await give_own_workspace(tenant_id, workspace=f"org_{uuid.uuid4().hex}")
    return tenant_id, workspace


def test_the_period_is_the_shorter_of_recording_and_transcript_capped_by_the_plan() -> None:
    assert call_content_days([("recording", 90), ("transcript", 365), ("lead", 10)]) == 90
    assert call_content_days([("transcript", 20)]) == 20
    assert call_content_days([("lead", 10)]) is None
    assert retention_to_send(90, 30) == 30
    assert retention_to_send(20, 30) == 20
    # No policy: the plan's window, never null (null keeps transcripts with no end).
    assert retention_to_send(None, 49) == 49
    assert engine_retention.DEVELOPER_RETENTION_DAYS == 90


def test_the_jobs_are_registered() -> None:
    functions = {getattr(fn, "__qualname__", "") for fn in WorkerSettings.functions}
    crons = {job.name for job in WorkerSettings.cron_jobs}
    assert RETENTION_SYNC_JOB in functions
    assert any("sweep_engine_retention" in name for name in crons)


async def test_a_provisioned_workspace_gets_the_clients_period_capped_and_recorded(
    vendor: RetentionVendor,
) -> None:
    tenant_id, workspace = await _client_workspace()
    async with tenant_session(tenant_id) as session:
        assert await queue_retention_sync(session, tenant_id=tenant_id)
    [payload] = await _outbox(RETENTION_SYNC_JOB, tenant_id)

    assert await engine_retention.sync_engine_retention({}, payload) == "set"

    # Recording 90 and transcript 365 by default: 90, capped at the plan's 30.
    assert vendor.patches == [(workspace, 30)]
    async with tenant_session(tenant_id) as session:
        record = await read_retention_record(session, tenant_id)
    assert (record.days, record.plan_days, record.error_code) == (30, 30, None)
    assert record.checked_at is not None
    # A second push finds it in step and writes nothing.
    assert await engine_retention.sync_engine_retention({}, payload) == "in_step"
    assert len(vendor.patches) == 1


async def test_a_shorter_client_period_is_sent_as_is(vendor: RetentionVendor) -> None:
    tenant_id, workspace = await _client_workspace()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE retention_policies SET ttl_days = 14 WHERE data_category = 'transcript'")
        )
    await engine_retention.sync_engine_retention({}, {"tenant_id": str(tenant_id)})
    assert vendor.patches == [(workspace, 14)]


async def test_a_client_without_a_workspace_of_its_own_is_not_pushed(
    vendor: RetentionVendor, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _tenant()
    payload = {"tenant_id": str(tenant_id)}
    assert await engine_retention.sync_engine_retention({}, payload) == "no_workspace"
    monkeypatch.setattr(get_settings(), "engine", "fake")
    assert await engine_retention.sync_engine_retention({}, payload) == "not_applicable"
    async with tenant_session(tenant_id) as session:
        assert not await queue_retention_sync(session, tenant_id=tenant_id)
    assert vendor.patches == []


async def test_a_failed_push_is_retried_recorded_then_alarmed(
    vendor: RetentionVendor, alarms: list[str]
) -> None:
    tenant_id, workspace = await _client_workspace()
    vendor.fail.add(workspace)
    payload = {"tenant_id": str(tenant_id)}
    with pytest.raises(Retry):
        await engine_retention.sync_engine_retention({"job_try": 1}, payload)
    with pytest.raises(ProblemError):
        await engine_retention.sync_engine_retention({"job_try": 3}, payload)
    assert alarms == ["engine_workspace_retention_drift"]
    async with tenant_session(tenant_id) as session:
        assert (await read_retention_record(session, tenant_id)).error_code == "engine_rejected"


async def test_an_answer_naming_another_period_is_not_taken_as_set(
    vendor: RetentionVendor, alarms: list[str]
) -> None:
    tenant_id, _workspace = await _client_workspace()
    vendor.ignore_patch = True
    with pytest.raises(ProblemError) as refused:
        await engine_retention.sync_engine_retention({"job_try": 3}, {"tenant_id": str(tenant_id)})
    assert refused.value.code == "engine_bad_response"


async def test_the_hourly_check_repairs_drift_everywhere_and_alarms(
    vendor: RetentionVendor, alarms: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.workers import workspace_walk
    from apps.workers.workspace_walk import WorkspaceVisit

    tenant_id, workspace = await _client_workspace()
    broken_tenant, broken = await _client_workspace()
    vendor.held[workspace] = None  # someone cleared it in the console
    vendor.held[DEVELOPER] = 30
    vendor.fail.add(broken)

    async def _walk(_sweep: str, **_kw: Any) -> Any:
        yield workspace_walk.DEVELOPER
        yield WorkspaceVisit(tenant_id=tenant_id, workspace=workspace)
        yield WorkspaceVisit(tenant_id=broken_tenant, workspace=broken)

    monkeypatch.setattr(engine_retention, "walk_workspaces", _walk)

    result = await engine_retention.sweep_engine_retention({})

    assert result.endswith("in_step=1 repaired=1 failed=1")
    assert vendor.patches == [(workspace, 30)]
    assert alarms == ["engine_workspace_retention_repaired", "engine_workspace_retention_drift"]


async def test_the_developer_workspaces_answer_is_kept_until_the_next_good_read(
    vendor: RetentionVendor, alarms: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """D-809: what the developer workspace confirmed is recorded on an in-step read too, and
    a failed read leaves the last answer for `recording_watch` rather than clearing it."""
    from apps.workers import workspace_walk

    vendor.plan = 49
    vendor.held[DEVELOPER] = 49

    async def _walk(_sweep: str, **_kw: Any) -> Any:
        yield workspace_walk.DEVELOPER

    monkeypatch.setattr(engine_retention, "walk_workspaces", _walk)
    assert (await engine_retention.sweep_engine_retention({})).endswith(
        "in_step=1 repaired=0 failed=0"
    )
    assert await _developer_record() == (49, 49, True)

    vendor.fail.add(DEVELOPER)
    assert (await engine_retention.sweep_engine_retention({})).endswith("failed=1")
    assert await _developer_record() == (49, 49, True)
    assert alarms == ["engine_workspace_retention_drift"]


async def test_the_developer_workspace_is_held_at_the_new_tenant_defaults(
    vendor: RetentionVendor, alarms: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.workers import workspace_walk

    vendor.plan = 365

    async def _walk(_sweep: str, **_kw: Any) -> Any:
        yield workspace_walk.DEVELOPER

    monkeypatch.setattr(engine_retention, "walk_workspaces", _walk)
    assert (await engine_retention.sweep_engine_retention({})).endswith("repaired=1 failed=0")
    assert vendor.patches == [(DEVELOPER, 90)]
    assert await _developer_record() == (90, 365, True)
    monkeypatch.setattr(get_settings(), "engine", "fake")
    assert await engine_retention.sweep_engine_retention({}) == "not_applicable"


async def test_provisioning_owes_the_retention_push(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.workers import engine_workspaces

    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id = await _tenant()
    await give_own_workspace(tenant_id, status="pending")
    await engine_workspaces._activate(tenant_id, f"org_{uuid.uuid4().hex}")
    assert await _outbox(RETENTION_SYNC_JOB, tenant_id) == [{"tenant_id": str(tenant_id)}]


async def test_the_admin_panel_reads_the_record(vendor: RetentionVendor) -> None:
    from apps.api.admin.engine_workspace_routes import _tenant_out

    tenant_id, _workspace = await _client_workspace()
    await engine_retention.sync_engine_retention({}, {"tenant_id": str(tenant_id)})
    async with tenant_session(tenant_id) as session:
        out = await _tenant_out(session, tenant_id)
    assert out.call_retention is not None
    assert (out.call_retention.days, out.call_retention.plan_days) == (30, 30)


# --- the per-workspace own-key checks the byok.changed event runs ----------------------------


async def test_an_own_model_check_that_cannot_read_the_workspace_alarms(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.workers import own_model_key

    raised: list[str] = []
    monkeypatch.setattr(own_model_key, "alert", lambda _s, code, **_kw: raised.append(code))

    class Unreachable:
        name = "thinnest"

        async def own_key_state(self) -> Any:
            raise ProblemError(
                kind="dependency", code="engine_unreachable", title="down", detail="down"
            )

    outcome = await own_model_key.check_own_model_workspace(
        Unreachable(),  # type: ignore[arg-type]
        uuid.uuid4(),
        f"org_{uuid.uuid4().hex}",
    )
    assert outcome == "failed"
    assert raised == ["own_model_workspace_drift"]
