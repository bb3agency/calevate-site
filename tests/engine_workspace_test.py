"""One ThinnestAI customer workspace per client (D-693): the table, the resolver, provisioning,
the backfill, offboarding, and the walk every sweep uses.

The vendor is `tests/thinnest_fake_account.py`, built from `thinnest-findings/mirror/
snapshots/2026-10-08/pages/api-reference/customers.md` and `customers/*.md`.
"""

from __future__ import annotations

import secrets
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest_workspace import (
    WorkspaceScopeError,
    in_workspace,
    remember_developer_workspace,
    workspace_headers,
    workspace_of,
)
from apps.api.tenancy import closure
from apps.api.tenancy import engine_workspace as resolver
from apps.workers import engine_workspaces as jobs
from apps.workers import workspace_walk
from calevate_shared.engine_scope import scoped_handle
from sqlalchemy import text
from tests.thinnest_fake_account import DEVELOPER, FakeAccount
from tests.workspace_support import give_own_workspace

pytestmark = [pytest.mark.rls]


async def _tenant(name: str = "Workspace Clinic") -> UUID:
    created = await admin_service.create_organization(
        name=name,
        slug=f"ws-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


async def _owed_tenant() -> UUID:
    """An account that is owed its workspace: what owes one is decided outside creation
    (D-695), so the test queues it the way the operator's Create workspace now does."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        # Paid, as an account owed a workspace is (D-697): restoring it re-provisions.
        await session.execute(
            text(
                "UPDATE organizations SET first_paid_at = now(), first_paid_via = 'wallet_topup' "
                "WHERE id = :t"
            ),
            {"t": tenant_id},
        )
        await resolver.queue_workspace_provisioning(session, tenant_id=tenant_id)
    return tenant_id


async def _outbox(job: str, tenant_id: UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :tid ORDER BY created_at"
                ),
                {"job": job, "tid": str(tenant_id)},
            )
        ).scalars()
        return [dict(r) for r in rows]


async def _state(tenant_id: UUID) -> resolver.WorkspaceState:
    async with tenant_session(tenant_id) as session:
        return await resolver.read_workspace_state(session, tenant_id)


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    raised: list[str] = []
    monkeypatch.setattr(jobs, "alert", lambda _k, code, **_kw: raised.append(code))
    return raised


# --- the table (hard rule 1) ------------------------------------------------------------


async def test_every_new_table_shows_another_tenant_zero_rows() -> None:
    a, b = await _tenant("A"), await _tenant("B")
    await give_own_workspace(a)
    async with tenant_session(a) as session:
        await session.execute(
            text(
                "INSERT INTO engine_voice_clone_copies (id, tenant_id, voice_id, workspace_id, "
                "vendor_voice_id, vendor_clone_id, created_at, updated_at) VALUES (:id, :tid, "
                "'engine:v1', :ws, 'vv', 'vc', now(), now())"
            ),
            {"id": uuid7(), "tid": a, "ws": f"org_test-{a}"},
        )
        await session.execute(
            text(
                "INSERT INTO engine_number_purchases (id, tenant_id, idempotency_key, "
                "vendor_number, workspace_id, direction, status, requested_by, created_at, "
                "updated_at) VALUES (:id, :tid, 'key-12345678', '918012345678', :ws, 'both', "
                "'renting', 'client', now(), now())"
            ),
            {"id": uuid7(), "tid": a, "ws": f"org_test-{a}"},
        )
    for table in (
        "tenant_engine_workspaces",
        "engine_voice_clone_copies",
        "engine_number_purchases",
    ):
        async with tenant_session(b) as session:
            seen = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"), {"a": a}
                )
            ).scalar_one()
        assert seen == 0, table
        async with tenant_session(a) as session:
            own = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :a"), {"a": a}
                )
            ).scalar_one()
        assert own == 1, table


async def test_a_tenant_session_cannot_write_another_tenants_workspace_row() -> None:
    a, b = await _tenant("A"), await _tenant("B")
    await give_own_workspace(a)
    async with tenant_session(b) as session:
        result = await session.execute(
            text("UPDATE tenant_engine_workspaces SET status = 'failed' WHERE tenant_id = :a"),
            {"a": a},
        )
    assert result.rowcount == 0  # type: ignore[attr-defined]
    assert (await _state(a)).status == "active"


# --- the resolver -----------------------------------------------------------------------


async def test_the_resolver_answers_only_an_active_workspace() -> None:
    tenant_id = await _tenant()
    assert await resolver.workspace_for_tenant(tenant_id) is None
    await give_own_workspace(tenant_id, status="plan_limit")
    assert await resolver.workspace_for_tenant(tenant_id) is None
    workspace = await give_own_workspace(tenant_id)
    assert await resolver.workspace_for_tenant(tenant_id) == workspace
    assert await resolver.own_workspace(tenant_id) == workspace


async def test_our_developer_workspace_is_never_a_clients_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit fix 8: the developer workspace's id is `org_…` too, so the prefix is not enough."""
    dev = f"org_dev-{uuid.uuid4().hex}"
    assert resolver.is_own_workspace(dev) is True
    monkeypatch.setattr(get_settings(), "thinnest_developer_workspace_id", dev)
    assert resolver.is_own_workspace(dev) is False
    with pytest.raises(WorkspaceScopeError):
        workspace_headers("GET", "/agents", dev)
    with pytest.raises(Exception) as refused:
        workspace_headers("POST", "/do-not-call", dev)
    assert getattr(refused.value, "code", None) == "engine_workspace_not_provisioned"
    monkeypatch.setattr(get_settings(), "thinnest_developer_workspace_id", None)
    remember_developer_workspace(dev)
    try:
        assert resolver.is_own_workspace(dev) is False
        tenant_id = await _tenant()
        await give_own_workspace(tenant_id, workspace=dev)
        assert await resolver.workspace_for_tenant(tenant_id) is None
    finally:
        remember_developer_workspace(None)


def test_a_handle_of_one_workspace_cannot_be_used_inside_another() -> None:
    handle = scoped_handle("ag_1", "org_a")
    assert workspace_of(handle) == "org_a"
    with in_workspace("org_b"), pytest.raises(WorkspaceScopeError):
        workspace_of(handle)
    with in_workspace("org_a"):
        assert workspace_of(None) == "org_a"
    assert workspace_of(None) is None


async def test_an_account_an_operator_creates_takes_no_workspace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-695: no workspace slot is taken when an operator creates an account."""
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id = await _tenant()
    assert (await _state(tenant_id)).status == "not_provisioned"
    assert await _outbox(resolver.PROVISION_JOB, tenant_id) == []


async def test_create_workspace_now_leaves_an_active_workspace_untouched(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id = await _tenant()
    workspace = await give_own_workspace(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert not await resolver.queue_workspace_provisioning(session, tenant_id=tenant_id)
    state = await _state(tenant_id)
    assert (state.status, state.workspace_id) == ("active", workspace)
    assert await _outbox(resolver.PROVISION_JOB, tenant_id) == []


async def test_create_workspace_now_queues_one_for_a_new_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The operator's button (`POST /v1/admin/engine-workspaces/tenants/{id}/provision`)
    calls exactly this."""
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await resolver.queue_workspace_provisioning(session, tenant_id=tenant_id)
    assert (await _state(tenant_id)).status == "pending"


async def test_no_workspace_is_owed_on_an_engine_without_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "engine", "pipecat")
    tenant_id = await _tenant()
    assert (await _state(tenant_id)).status == "not_provisioned"
    assert await _outbox(resolver.PROVISION_JOB, tenant_id) == []


# --- provisioning -----------------------------------------------------------------------


async def test_provisioning_creates_one_workspace_and_owes_its_follow_ups(
    account: FakeAccount,
) -> None:
    tenant_id = await _owed_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO dnc_list (id, tenant_id, phone_e164, scope, source, added_at, "
                "created_at) VALUES (:id, :tid, '+919812345678', 'tenant', 'call_optout', "
                "now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id},
        )
    assert await jobs.provision_engine_workspace({}, {"tenant_id": str(tenant_id)}) == "active"
    state = await _state(tenant_id)
    assert state.active and state.workspace_id in account.customers
    create = next(s for s in account.sent if s.method == "POST" and s.path == "/customers")
    assert create.workspace is None
    assert await _outbox("submit_engine_business_details", tenant_id)
    assert await _outbox("push_engine_dnc", tenant_id)
    # Idempotent: a second run finds it and creates nothing.
    assert (
        await jobs.provision_engine_workspace({}, {"tenant_id": str(tenant_id)}) == "already_active"
    )
    assert len([s for s in account.sent if s.path == "/customers" and s.method == "POST"]) == 1


async def test_provisioning_adopts_the_workspace_our_reference_already_names(
    account: FakeAccount,
) -> None:
    tenant_id = await _owed_tenant()
    existing = account.add_customer(resolver.external_ref_for(tenant_id))
    await jobs.provision_engine_workspace({}, {"tenant_id": str(tenant_id)})
    assert (await _state(tenant_id)).workspace_id == existing
    assert not [s for s in account.sent if s.path == "/customers" and s.method == "POST"]


async def test_a_deleted_workspace_is_restored_rather_than_replaced(account: FakeAccount) -> None:
    tenant_id = await _owed_tenant()
    archived = account.add_customer(resolver.external_ref_for(tenant_id), archived=True)
    await jobs.provision_engine_workspace({}, {"tenant_id": str(tenant_id)})
    assert (await _state(tenant_id)).workspace_id == archived
    assert account.customers[archived]["archivedAt"] is None


async def test_the_plan_cap_leaves_the_client_waiting_and_alarms(
    account: FakeAccount, alarms: list[str]
) -> None:
    account.cap = 0
    tenant_id = await _owed_tenant()
    assert await jobs.provision_engine_workspace({}, {"tenant_id": str(tenant_id)}) == "plan_limit"
    state = await _state(tenant_id)
    assert (state.status, state.last_error_code) == ("plan_limit", "plan_limit")
    assert "engine_workspace_plan_limit" in alarms
    assert await resolver.workspace_for_tenant(tenant_id) is None


async def test_the_developer_workspace_is_never_recorded_as_a_clients(
    account: FakeAccount, alarms: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id = await _owed_tenant()
    account.customers[DEVELOPER] = {
        "id": DEVELOPER,
        "externalId": resolver.external_ref_for(tenant_id),
        "archivedAt": None,
        "eraseAfter": None,
    }
    result = await jobs.provision_engine_workspace({}, {"tenant_id": str(tenant_id)})
    assert result == "refused_developer_workspace"
    assert (await _state(tenant_id)).status == "failed"
    assert "engine_workspace_provisioning_failed" in alarms


async def test_the_daily_sweep_backfills_every_paid_tenant_without_a_workspace(
    account: FakeAccount, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A workspace is owed from the first payment (D-697): the sweep backfills a paid
    tenant that has none, and leaves an unpaid one (a free trial) without."""
    monkeypatch.setattr(get_settings(), "engine", "pipecat")
    paid = await _tenant("Paid, no workspace")
    unpaid = await _tenant("Never paid")
    monkeypatch.setattr(get_settings(), "engine", "thinnest")
    async with tenant_session(paid) as session:
        await session.execute(
            text(
                "UPDATE organizations SET first_paid_at = now(), first_paid_via = 'wallet_topup' "
                "WHERE id = :t"
            ),
            {"t": paid},
        )
    assert (await _state(paid)).status == "not_provisioned"
    # The shared test database holds every other test's tenants; the sweep is pointed at
    # these two so its per-tick budget is spent here.
    monkeypatch.setattr(
        jobs,
        "_LIVE_TENANTS",
        "SELECT o.id, o.first_paid_at IS NOT NULL FROM organizations o "
        f"WHERE o.id IN ('{paid}'::uuid, '{unpaid}'::uuid) ORDER BY o.id",
    )
    await jobs.retry_engine_workspaces({})
    assert (await _state(paid)).status == "pending"
    assert await _outbox(resolver.PROVISION_JOB, paid)
    assert (await _state(unpaid)).status == "not_provisioned"
    assert not await _outbox(resolver.PROVISION_JOB, unpaid)


# --- offboarding ------------------------------------------------------------------------


async def test_closing_an_account_offboards_its_workspace(account: FakeAccount) -> None:
    tenant_id = await _owed_tenant()
    await jobs.provision_engine_workspace({}, {"tenant_id": str(tenant_id)})
    workspace = (await _state(tenant_id)).workspace_id
    assert workspace is not None
    number = f"9180{secrets.randbelow(10**8):08d}"
    account.hold(workspace, number)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, provider, "
                "engine_number_ref, engine_owned, direction, created_at, updated_at) VALUES "
                "(:id, :tid, :e164, 'standard', 'thinnest', :ref, true, 'both', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "e164": f"+{number}", "ref": f"{number}@{workspace}"},
        )
        await closure.close_account(session, tenant_id=tenant_id, reason="test", closed_by=None)
    assert (await _state(tenant_id)).status == "offboarding"
    assert await resolver.workspace_for_tenant(tenant_id) is None
    assert await _outbox(resolver.OFFBOARD_JOB, tenant_id)

    result = await jobs.offboard_engine_workspace({}, {"tenant_id": str(tenant_id)})

    assert result == "released=1 agents_deleted=0"
    release = next(s for s in account.sent if s.method == "DELETE" and "/phone-numbers/" in s.path)
    assert (release.workspace, release.query.get("confirm")) == (workspace, "release")
    assert account.customers[workspace]["archivedAt"] is not None
    assert (await _state(tenant_id)).status == "deleted"
    async with tenant_session(tenant_id) as session:
        released = (
            await session.execute(
                text("SELECT released_at IS NOT NULL FROM phone_numbers WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar_one()
        assert released is True
        await closure.restore_account(session, tenant_id=tenant_id)
    assert (await _state(tenant_id)).status == "pending"


# --- the walk -----------------------------------------------------------------------------


def test_the_walk_resumes_after_its_cursor_and_wraps() -> None:
    rows = [
        resolver.WorkspaceRow(tenant_id=UUID(int=i), status="active", workspace_id=f"org_{i}")
        for i in (1, 2, 3)
    ]
    assert [r.workspace_id for r in workspace_walk.rotate(rows, str(UUID(int=2)))] == [
        "org_3",
        "org_1",
        "org_2",
    ]
    assert workspace_walk.rotate(rows, None) == rows


async def test_a_bounded_walk_reports_what_it_left_and_starts_there_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = [
        resolver.WorkspaceRow(tenant_id=UUID(int=i), status="active", workspace_id=f"org_w{i}")
        for i in (1, 2, 3)
    ]

    async def _active(**_kw: Any) -> list[resolver.WorkspaceRow]:
        return rows

    monkeypatch.setattr(workspace_walk, "active_workspaces", _active)
    sweep = f"test-{uuid.uuid4().hex[:6]}"
    report = workspace_walk.WalkReport()
    first = [
        v.workspace async for v in workspace_walk.walk_workspaces(sweep, budget=2, report=report)
    ]
    assert first == [None, "org_w1", "org_w2"] and report.deferred == 1
    second = [
        v.workspace
        async for v in workspace_walk.walk_workspaces(sweep, budget=2, include_developer=False)
    ]
    assert second == ["org_w3", "org_w1"]


async def test_charges_are_read_in_every_workspace(monkeypatch: pytest.MonkeyPatch) -> None:
    """costMicro is reconciled per workspace (D-693): the developer workspace, then each
    client's, each listing read inside its own workspace."""
    from apps.api.engine.charges import EngineChargeListing
    from apps.api.engine.thinnest_workspace import current_workspace
    from apps.workers import engine_charges

    read_in: list[str | None] = []

    class _Engine:
        name = "thinnest"

        def holds_credentials(self) -> bool:
            return True

        async def list_call_charges(self, *, since: Any) -> EngineChargeListing:
            read_in.append(current_workspace())
            return EngineChargeListing(charges=[], complete=True, other_currency=0)

    rows = [resolver.WorkspaceRow(tenant_id=UUID(int=7), status="active", workspace_id="org_c7")]

    async def _active(**_kw: Any) -> list[resolver.WorkspaceRow]:
        return rows

    monkeypatch.setattr(workspace_walk, "active_workspaces", _active)
    monkeypatch.setattr(engine_charges, "get_engine", lambda: _Engine())
    outcome = await engine_charges.reconcile_engine_charges({})
    assert read_in == [None, "org_c7"]
    assert "workspaces=2" in outcome
