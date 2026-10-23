"""After the first payment (D-859): the agents move into the client's own workspace, the owner
is guided through going live, and test calls go on from the client's own number.

* Activation owes one move; the move republishes live and ready agents with their state kept,
  moves running arms, leaves drafts alone, and a second run moves nothing.
* One agent's refusal never stops the others; a plan or voice refusal is held, alarmed once
  and retried by the hourly sweep; an unexpected error is retried, then failed and alarmed.
* `POST /agents` answering 409 without `phone_number_required` is the plan's agent allowance
  (`snapshots/2026-10-19/pages/api-reference/agents/create-agent.md:654-668`).
* A paid test call comes only from a moved agent that holds its own number, is marked and
  capped per day; the dashboard panel says so without trial copy.
* A refund or dispute on a paid account alarms and reverses nothing.
* The guide's read, its marker and its rows are the tenant's own (RLS).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.agents import lifecycle, prompts
from apps.api.agents import trial_calls as trial_calls_module
from apps.api.agents import trial_panel as trial_panel_module
from apps.api.agents.trial_calls import place_trial_call
from apps.api.agents.trial_panel import read_trial_panel
from apps.api.billing import first_payment
from apps.api.compliance import service as compliance_service
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.thinnest import AGENT_ALLOWANCE_USED
from apps.api.go_live import moves
from apps.api.main import app
from apps.workers import agent_moves
from apps.workers import engine_workspaces as workspace_jobs
from arq import Retry
from calevate_shared.engine import AgentConfig
from calevate_shared.engine_scope import scope_of
from sqlalchemy import text
from tests.conftest import fund_wallet
from tests.hosted_voice_fakes import CatalogueRows, HostingEngine, selected
from tests.thinnest_engine_seams_test import (  # noqa: F401 - pytest fixtures
    _agent,
    _set_columns,
    attested,
    no_webhook,
)
from tests.thinnest_engine_test import _cfg, _engine, _recorder
from tests.workspace_support import give_own_workspace, workspace_of

pytestmark = [pytest.mark.rls]


# --- helpers -----------------------------------------------------------------------------


@pytest.fixture
def alarms(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, dict[str, str]]]:
    raised: list[tuple[str, dict[str, str]]] = []

    def _alert(stage: str, code: str, *, detail: str | None = None, **ids: str) -> None:
        raised.append((code, ids))

    monkeypatch.setattr(moves, "alert", _alert)
    monkeypatch.setattr(first_payment, "alert", _alert)
    return raised


@pytest.fixture
def workspaces_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """The settings name the fake engine; the move's own guard asks for workspaces."""
    monkeypatch.setattr(agent_moves, "engine_has_workspaces", lambda *a: True)


async def _new_agent(tenant_id: UUID, name: str, voice: str) -> UUID:
    async with tenant_session(tenant_id) as session:
        agent_id = await lifecycle.create_agent(
            session, tenant_id=tenant_id, name=name, direction="inbound", language_primary="te-IN"
        )
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet in Telugu, then book.",
            notes=None,
            created_by=None,
        )
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    return UUID(str(agent_id))


async def _in_developer_workspace(
    engine: HostingEngine, tenant_id: UUID, agent_id: UUID, *, status: str
) -> str:
    """The agent as a trial left it: published in our developer workspace (unscoped)."""
    legacy = f"fakeagent_dev_{uuid.uuid4().hex[:8]}"
    engine._agents[legacy] = AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        name="old",
        direction="outbound",
        system_prompt="x",
        opening_line="Hello",
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET engine_agent_ref = :r, engine = 'thinnest', status = :s "
                "WHERE id = :a"
            ),
            {"r": legacy, "s": status, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('thinnest', :r, :t, :a, true, now(), "
                "now())"
            ),
            {"r": legacy, "t": tenant_id, "a": agent_id},
        )
    return legacy


async def _agent_row(tenant_id: UUID, agent_id: UUID) -> tuple[str, str | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).one()
    return str(row[0]), row[1]


async def _move_rows(tenant_id: UUID) -> dict[UUID, tuple[str, str | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT agent_id, status, reason_code FROM agent_workspace_moves")
            )
        ).all()
    return {UUID(str(r[0])): (str(r[1]), r[2]) for r in rows}


async def _jobs(job: str, tenant_id: UUID) -> list[dict[str, Any]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :j "
                    "AND payload->>'tenant_id' = :t"
                ),
                {"j": job, "t": str(tenant_id)},
            )
        ).scalars()
        return [dict(r) for r in rows]


async def _run(tenant_id: UUID, *, attempt: int = 1) -> str:
    return await agent_moves.move_agents_to_workspace(
        {"job_try": attempt},
        {"tenant_id": str(tenant_id), "workspace_id": workspace_of(tenant_id)},
    )


async def _paid_client(hosted_rows: CatalogueRows) -> tuple[UUID, UUID, str]:
    """A paying client with its own active workspace, and one hosted voice."""
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    await fund_wallet(UUID(str(tenant_id)))
    return UUID(str(tenant_id)), UUID(str(agent_id)), voice


# --- the trigger --------------------------------------------------------------------------


async def test_activation_owes_one_move_per_workspace(hosted_rows: CatalogueRows) -> None:
    tenant_id, _agent_id, _voice = await _paid_client(hosted_rows)
    await give_own_workspace(tenant_id, status="pending")
    await workspace_jobs._activate(tenant_id, workspace_of(tenant_id))
    await workspace_jobs._activate(tenant_id, workspace_of(tenant_id))
    owed = await _jobs(moves.MOVE_JOB, tenant_id)
    assert owed == [{"tenant_id": str(tenant_id), "workspace_id": workspace_of(tenant_id)}]


async def test_a_conversion_before_the_workspace_is_active_queues_no_racing_apply(
    hosted_rows: CatalogueRows,
) -> None:
    """The conversion's republish used to race provisioning and fail for good. Until the
    workspace is active nothing is queued; the activation owes the move."""
    tenant_id, _agent_id, _voice = await _paid_client(hosted_rows)
    await give_own_workspace(tenant_id, status="pending")
    async with tenant_session(tenant_id) as session:
        assert (
            await moves.refresh_agents_after_payment(
                session, tenant_id=tenant_id, reason="trial_converted"
            )
            == "on_activation"
        )
        runs = (
            await session.execute(
                text("SELECT count(*) FROM live_apply_runs WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert runs == 0
    assert await _jobs(moves.MOVE_JOB, tenant_id) == []


async def test_a_conversion_with_an_active_workspace_owes_the_apply_and_the_move(
    hosted_rows: CatalogueRows,
) -> None:
    tenant_id, _agent_id, _voice = await _paid_client(hosted_rows)
    async with tenant_session(tenant_id) as session:
        assert (
            await moves.refresh_agents_after_payment(
                session, tenant_id=tenant_id, reason="trial_converted"
            )
            == "queued"
        )
    assert len(await _jobs(moves.MOVE_JOB, tenant_id)) == 1


# --- the move ---------------------------------------------------------------------------


async def test_live_and_ready_agents_move_with_their_state_and_drafts_stay(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
    workspaces_on: None,
) -> None:
    tenant_id, live_id, voice = await _paid_client(hosted_rows)
    ready_id = await _new_agent(tenant_id, "Ready one", voice)
    draft_id = await _new_agent(tenant_id, "Draft one", voice)
    engine = HostingEngine()
    old_live = await _in_developer_workspace(engine, tenant_id, live_id, status="live")
    old_ready = await _in_developer_workspace(engine, tenant_id, ready_id, status="paused")
    workspace = workspace_of(tenant_id)

    with selected(engine):
        summary = await _run(tenant_id)

    assert summary == "moved=2", summary
    live_status, live_ref = await _agent_row(tenant_id, live_id)
    ready_status, ready_ref = await _agent_row(tenant_id, ready_id)
    assert (live_status, scope_of(live_ref or "")) == ("live", workspace)
    assert (ready_status, scope_of(ready_ref or "")) == ("paused", workspace), (
        "a ready agent stays ready: the move never switches it on"
    )
    assert await _agent_row(tenant_id, draft_id) == ("draft", None)
    rows = await _move_rows(tenant_id)
    assert rows == {live_id: ("moved", None), ready_id: ("moved", None)}
    retired = {job["old_ref"] for job in await _jobs("retire_moved_engine_agent", tenant_id)}
    assert retired == {old_live, old_ready}

    # Idempotent: a second run finds nothing left behind and owes no second retirement.
    with selected(engine):
        assert await _run(tenant_id) == "nothing_to_move"
    assert len(await _jobs("retire_moved_engine_agent", tenant_id)) == 2


async def test_a_running_arm_moves_with_its_agent(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
    workspaces_on: None,
) -> None:
    tenant_id, agent_id, _voice = await _paid_client(hosted_rows)
    engine = HostingEngine()
    await _in_developer_workspace(engine, tenant_id, agent_id, status="paused")
    arm_ref = f"fakeagent_arm_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        version = (
            await session.execute(
                text("SELECT id FROM prompt_versions WHERE agent_id = :a LIMIT 1"),
                {"a": agent_id},
            )
        ).scalar_one()
        experiment_id, variant_id = uuid.uuid4(), uuid.uuid4()
        await session.execute(
            text(
                "INSERT INTO prompt_experiments (id, tenant_id, agent_id, name, status, "
                "conversion_metric, started_at) VALUES (:i, :t, :a, 'arms', 'running', "
                "'call_outcome_resolved', now())"
            ),
            {"i": experiment_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO prompt_experiment_variants (id, tenant_id, experiment_id, label, "
                "prompt_version_id, disclosure_line, weight_bp, engine_agent_ref) VALUES "
                "(:i, :t, :e, 'B', :pv, 'This is an AI assistant from the clinic.', 5000, :r)"
            ),
            {"i": variant_id, "t": tenant_id, "e": experiment_id, "pv": version, "r": arm_ref},
        )
    engine._agents[arm_ref] = AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(variant_id),
        name="arm",
        direction="outbound",
        system_prompt="x",
        opening_line="Hello",
    )

    with selected(engine):
        await _run(tenant_id)

    async with tenant_session(tenant_id) as session:
        moved_arm = (
            await session.execute(
                text("SELECT engine_agent_ref FROM prompt_experiment_variants WHERE id = :v"),
                {"v": variant_id},
            )
        ).scalar_one()
    assert scope_of(str(moved_arm)) == workspace_of(tenant_id)


class _RefusingEngine(HostingEngine):
    """Refuses to create one agent, with the given error, until told otherwise."""

    def __init__(self, refused: UUID, error: Exception) -> None:
        super().__init__()
        self.refused: UUID | None = refused
        self.error = error

    async def create_agent(self, cfg: AgentConfig) -> str:
        if self.refused is not None and cfg.agent_id == str(self.refused):
            raise self.error
        return await super().create_agent(cfg)


def _allowance() -> ProblemError:
    return ProblemError(
        kind="business_rule", code=AGENT_ALLOWANCE_USED, title="x", detail="x", remediation="x"
    )


async def test_the_plan_allowance_holds_one_agent_and_the_others_still_move(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
    workspaces_on: None,
    alarms: list[tuple[str, dict[str, str]]],
) -> None:
    tenant_id, held_id, voice = await _paid_client(hosted_rows)
    moving_id = await _new_agent(tenant_id, "Second", voice)
    engine = _RefusingEngine(held_id, _allowance())
    old_held = await _in_developer_workspace(engine, tenant_id, held_id, status="paused")
    await _in_developer_workspace(engine, tenant_id, moving_id, status="paused")

    with selected(engine):
        summary = await _run(tenant_id)
    assert summary == "held=1 moved=1", summary
    rows = await _move_rows(tenant_id)
    assert rows[held_id] == ("held", AGENT_ALLOWANCE_USED)
    assert rows[moving_id] == ("moved", None)
    assert await _agent_row(tenant_id, held_id) == ("paused", old_held), (
        "a held agent keeps working where it is"
    )
    assert [code for code, _ in alarms] == ["agent_move_held"]

    # The hourly sweep tries again; the same cause does not page twice.
    with selected(engine):
        await _run(tenant_id)
    assert [code for code, _ in alarms] == ["agent_move_held"]

    # Once a slot is free the sweep queues it and it moves.
    engine.refused = None
    async with tenant_session(tenant_id) as session:
        assert await moves.agents_to_move(
            session, tenant_id=tenant_id, workspace=workspace_of(tenant_id)
        ) == [held_id]
    await agent_moves.sweep_agent_moves({})
    assert len(await _jobs(moves.MOVE_JOB, tenant_id)) == 1
    await agent_moves.sweep_agent_moves({})
    assert len(await _jobs(moves.MOVE_JOB, tenant_id)) == 1, "once per tenant per hour"
    with selected(engine):
        assert await _run(tenant_id) == "moved=1"
    assert (await _move_rows(tenant_id))[held_id] == ("moved", None)


async def test_an_unexpected_error_is_retried_then_failed_and_alarmed(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
    workspaces_on: None,
    alarms: list[tuple[str, dict[str, str]]],
) -> None:
    tenant_id, agent_id, _voice = await _paid_client(hosted_rows)
    engine = _RefusingEngine(agent_id, RuntimeError("boom"))
    await _in_developer_workspace(engine, tenant_id, agent_id, status="paused")

    with selected(engine), pytest.raises(Retry):
        await _run(tenant_id, attempt=1)
    assert (await _move_rows(tenant_id))[agent_id] == ("waiting", "RuntimeError")
    assert alarms == []

    with selected(engine):
        assert await _run(tenant_id, attempt=WORKER_MAX_TRIES) == "failed=1"
    assert (await _move_rows(tenant_id))[agent_id] == ("failed", "RuntimeError")
    assert [code for code, _ in alarms] == ["agent_move_failed"]


async def test_the_move_waits_for_its_own_workspace(
    hosted_rows: CatalogueRows, workspaces_on: None
) -> None:
    tenant_id, _agent_id, _voice = await _paid_client(hosted_rows)
    await give_own_workspace(tenant_id, status="plan_limit")
    assert await _run(tenant_id) == "workspace_not_active"


# --- the vendor's allowance refusal -------------------------------------------------------


async def test_the_agent_allowance_409_is_named_and_plainly_worded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.engine import thinnest

    raised: list[str] = []
    monkeypatch.setattr(thinnest, "alert", lambda stage, code, **_: raised.append(code))
    handler, _seen = _recorder(
        {
            ("GET", "/agents"): httpx.Response(200, json={"items": [], "nextCursor": None}),
            ("POST", "/agents"): httpx.Response(
                409,
                json={
                    "error": "Pay as you go includes 2 agents. Upgrade to add more.",
                    "code": "conflict",
                },
            ),
        }
    )
    with pytest.raises(ProblemError) as refused:
        await _engine(handler).create_agent(_cfg())
    assert refused.value.code == AGENT_ALLOWANCE_USED
    words = f"{refused.value.title} {refused.value.detail} {refused.value.remediation}"
    assert "ThinnestAI" not in words and "Voice engine rejected" not in words
    assert raised == [AGENT_ALLOWANCE_USED]


# --- paid test calls ---------------------------------------------------------------------


@pytest.fixture
def paid_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(compliance_service, "within_calling_hours", lambda *a, **k: True)
    monkeypatch.setattr(trial_calls_module, "TRIAL_CALL_ENGINES", frozenset({"fake"}))
    monkeypatch.setattr(trial_panel_module, "TRIAL_CALL_ENGINES", frozenset({"fake"}))
    # The platform-wide line count is another suite's subject; calls other tests left
    # queued in the shared database must not fill it here.
    from apps.api.agents import service as agents_service

    monkeypatch.setattr(agents_service, "engine_concurrency_cap", lambda *a: None)


def _owner(tenant_id: UUID) -> Principal:
    return Principal(realm="client", user_id=uuid.uuid4(), tenant_id=tenant_id, role="owner")


async def _test_call(tenant_id: UUID, agent_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return await place_trial_call(
            session,
            principal=_owner(tenant_id),
            agent_id=agent_id,
            number="9876543210",
            idempotency_key=str(uuid.uuid4()),
        )


async def _own_number(tenant_id: UUID, agent_id: UUID) -> None:
    digits = f"9180{uuid.uuid4().int % 10**8:08d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, provider, "
                "direction, dlt_status, engine_number_ref, engine_owned, created_at, "
                "updated_at) VALUES (:id, :tid, :aid, :e164, 'standard', 'thinnest', "
                "'both', 'pending', :ref, true, now(), now())"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "aid": agent_id,
                "e164": f"+{digits}",
                "ref": f"{digits}@{workspace_of(tenant_id)}",
            },
        )


@contextmanager
def _dialling(engine: HostingEngine) -> Iterator[None]:
    with selected(engine):
        yield


async def test_a_paid_test_call_waits_for_the_agent_to_move(
    hosted_rows: CatalogueRows, paid_calls: None
) -> None:
    tenant_id, agent_id, _voice = await _paid_client(hosted_rows)
    engine = HostingEngine()
    await _in_developer_workspace(engine, tenant_id, agent_id, status="live")
    with _dialling(engine):
        result = await _test_call(tenant_id, agent_id)
    assert (result.status, result.blocked_rule) == ("blocked", "paid_test_call_agent_moving")


async def test_a_paid_test_call_rings_from_the_clients_own_number_only(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
    paid_calls: None,
) -> None:
    tenant_id, agent_id, _voice = await _paid_client(hosted_rows)
    engine = HostingEngine()
    with _dialling(engine):
        async with tenant_session(tenant_id) as session:
            from apps.api.agents.service import publish_agent

            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        before = await _test_call(tenant_id, agent_id)
        await _own_number(tenant_id, agent_id)
        placed = await _test_call(tenant_id, agent_id)
    assert (before.status, before.blocked_rule) == ("blocked", "paid_test_call_needs_own_number")
    assert placed.status == "queued", placed
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT trial_call, paid_test_call FROM calls WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).one()
    assert tuple(row) == (False, True), "billed like any call, counted as the owner's test"


async def test_paid_test_calls_stop_at_the_daily_cap(
    attested: set[str],  # noqa: F811
    no_webhook: None,  # noqa: F811
    hosted_rows: CatalogueRows,
    paid_calls: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _voice = await _paid_client(hosted_rows)
    monkeypatch.setattr(get_settings(), "trial_daily_call_cap", 1)
    engine = HostingEngine()
    with _dialling(engine):
        async with tenant_session(tenant_id) as session:
            from apps.api.agents.service import publish_agent

            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        await _own_number(tenant_id, agent_id)
        first = await _test_call(tenant_id, agent_id)
        second = await _test_call(tenant_id, agent_id)
    assert first.status == "queued"
    assert (second.status, second.blocked_rule) == ("blocked", "paid_test_daily_cap")


async def test_the_dashboard_panel_shows_paid_test_calls_without_trial_copy(
    hosted_rows: CatalogueRows, paid_calls: None
) -> None:
    tenant_id, _agent_id, _voice = await _paid_client(hosted_rows)
    async with tenant_session(tenant_id) as session:
        panel = await read_trial_panel(session, tenant_id=tenant_id)
    assert panel.on_trial is False and panel.paid_test_calls is True
    assert panel.can_call is False and panel.blocked_reason is not None
    assert "trial" not in panel.blocked_reason.lower()
    assert panel.answering_locked_reason is None


# --- money taken back ---------------------------------------------------------------------


async def test_a_refund_on_a_paid_account_alarms_and_reverses_nothing(
    hosted_rows: CatalogueRows, alarms: list[tuple[str, dict[str, str]]]
) -> None:
    from apps.api.billing.payments import RefundEvent, credit_refund

    tenant_id, _agent_id, _voice = await _paid_client(hosted_rows)
    from decimal import Decimal

    async with tenant_session(tenant_id) as session:
        await credit_refund(
            session,
            refund=RefundEvent(
                refund_id="rfnd_d859",
                payment_id="pay_d859",
                tenant_id=tenant_id,
                amount_inr=Decimal("100.00"),
                currency="INR",
            ),
        )
        paid = await first_payment.has_paid(session, tenant_id=tenant_id)
    assert paid, "a refund does not unpay an account"
    [(code, ids)] = alarms
    assert code == "paid_account_payment_reversed"
    assert ids == {
        "tenant_id": str(tenant_id),
        "payment_ref": "pay_d859",
        "reversal_ref": "rfnd_d859",
    }


async def test_a_reversal_on_an_unpaid_account_is_not_an_alarm(
    alarms: list[tuple[str, dict[str, str]]],
) -> None:
    tenant_id, _agent_id = await _agent()
    async with tenant_session(tenant_id) as session:
        assert not await first_payment.alert_payment_reversed(
            session,
            tenant_id=UUID(str(tenant_id)),
            kind="dispute",
            payment_ref="p",
            reversal_ref="d",
        )
    assert alarms == []


# --- the guide ----------------------------------------------------------------------------


async def _owner_headers(tenant_id: UUID) -> dict[str, str]:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:i, :e, now(), now())"
            ),
            {"i": user_id, "e": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:i, :t, :u, 'owner', now(), now())"
            ),
            {"i": uuid.uuid4(), "t": tenant_id, "u": user_id},
        )
    return {"Authorization": f"Bearer dev:client:{user_id}"}


async def test_the_first_payment_owes_the_guide_until_it_is_put_aside(
    hosted_rows: CatalogueRows,
) -> None:
    tenant_id, agent_id = await _agent()
    tenant = UUID(str(tenant_id))
    engine = HostingEngine()
    await _in_developer_workspace(engine, tenant, UUID(str(agent_id)), status="paused")
    from decimal import Decimal

    from apps.api.billing.service import record_entry

    async with tenant_session(tenant) as session:
        await record_entry(
            session, tenant_id=tenant, delta=Decimal("500.00"), reason="topup", ref="pay_guide"
        )
        assert await first_payment.on_payment_credited(
            session, tenant_id=tenant, amount_inr=Decimal("500.00"), via="wallet_topup"
        )
    headers = await _owner_headers(tenant)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")
    async with client as http:
        read = await http.get("/v1/go-live", headers=headers)
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["due"] is True and body["current"] == "move"
        assert body["move"]["state"] == "moving"
        assert [a["state"] for a in body["move"]["agents"]] == ["moving"]
        assert "ThinnestAI" not in read.text
        aside = await http.post("/v1/go-live/dismiss", headers=headers)
    assert aside.status_code == 200
    assert aside.json()["due"] is False and aside.json()["dismissed_at"] is not None


async def test_another_tenant_reads_zero_rows() -> None:
    mine, mine_agent = await _agent()
    theirs, _ = await _agent()
    async with tenant_session(mine) as session:
        await session.execute(
            text(
                "INSERT INTO agent_workspace_moves (id, tenant_id, agent_id, workspace_id) "
                "VALUES (:i, :t, :a, 'org_x')"
            ),
            {"i": uuid7(), "t": mine, "a": mine_agent},
        )
        await session.execute(
            text("INSERT INTO go_live_guides (id, tenant_id, owed_at) VALUES (:i, :t, now())"),
            {"i": uuid7(), "t": mine},
        )
    async with tenant_session(theirs) as session:
        for table in ("agent_workspace_moves", "go_live_guides"):
            assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar() == 0
    with pytest.raises(Exception, match="row-level security"):
        async with tenant_session(theirs) as session:
            await session.execute(
                text("INSERT INTO go_live_guides (id, tenant_id, owed_at) VALUES (:i, :t, now())"),
                {"i": uuid7(), "t": mine},
            )
