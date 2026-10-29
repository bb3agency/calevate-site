"""A saved setting reaches every live agent at once (D-720): the seam, the walk, the sources.

`agents/live_apply.queue_live_apply` records a run and an outbox message in the saving
transaction; `apps/workers/live_apply` converges each live agent through `publish_agent`.
These cases run the worker's own jobs directly (the dispatcher is not running in tests).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest
from apps.api.agents import live_apply, prompts
from apps.api.agents.live_apply import AGENT_JOB, APPLY_JOB, queue_live_apply, read_run
from apps.api.core.errors import ProblemError
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.ingest.policy_routes import router as lead_calling_router
from apps.workers import live_apply as worker
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.live_apply_support import drain_live_apply
from tests.llm_model_selection_test import _published, _second_agent, _tenant


@pytest.fixture(autouse=True)
async def _no_open_platform_run() -> None:
    """A pending platform run absorbs every later tenant request, and nothing walks one in
    this suite, so each case starts with none open (another case may have left one)."""
    async with untenanted_session() as session:
        await session.execute(
            text(
                "UPDATE live_apply_runs SET status = 'superseded', lease_until = NULL "
                "WHERE scope = 'platform' AND status IN ('pending', 'running')"
            )
        )


async def _queue(tenant_id: uuid.UUID, reason: str = "test") -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await queue_live_apply(session, scope="tenant", tenant_id=tenant_id, reason=reason)


async def _run(run_id: uuid.UUID) -> live_apply.LiveApplyRunView:
    async with untenanted_session() as session:
        run = await read_run(session, run_id)
    assert run is not None
    return run


async def _outbox(job: str, run_id: uuid.UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'run_id' = :run"
                    ),
                    {"job": job, "run": str(run_id)},
                )
            ).scalar()
            or 0
        )


def _counting(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    seen: list[str] = []
    original = engine.update_agent

    async def counting(ref: str, config: Any) -> None:
        seen.append(str(ref))
        await original(ref, config)

    monkeypatch.setattr(engine, "update_agent", counting)
    return seen


# ------------------------------------------------------------------ the seam


async def test_a_queue_writes_a_run_and_its_outbox_message_in_the_same_transaction() -> None:
    tenant_id, _agent, _bearer = await _tenant()
    run_id = await _queue(tenant_id, "lead_calling.detect_machines")
    run = await _run(run_id)
    assert (run.scope, run.tenant_id, run.status) == ("tenant", tenant_id, "pending")
    assert run.reasons == ["lead_calling.detect_machines"]
    assert await _outbox(APPLY_JOB, run_id) == 1


async def test_a_pending_run_absorbs_a_later_save_and_a_newer_run_supersedes_a_running_one() -> (
    None
):
    tenant_id, _agent, _bearer = await _tenant()
    first = await _queue(tenant_id, "business_profile")
    again = await _queue(tenant_id, "default_llm_model")
    assert again == first
    assert (await _run(first)).reasons == ["business_profile", "default_llm_model"]

    async with untenanted_session() as session:
        await session.execute(
            text("UPDATE live_apply_runs SET status = 'running' WHERE id = :id"), {"id": first}
        )
    newer = await _queue(tenant_id, "trial_converted")
    assert newer != first
    assert (await _run(first)).status == "superseded"


async def test_the_scope_must_name_its_target() -> None:
    async with untenanted_session() as session:
        with pytest.raises(ValueError):
            await queue_live_apply(session, scope="tenant", reason="x")


# ------------------------------------------------------------------ the walk


async def test_every_live_agent_is_republished_and_a_draft_is_not() -> None:
    tenant_id, agent_id, _bearer = await _tenant()
    ref = await _published(tenant_id, agent_id)
    draft_id = await _second_agent(tenant_id)
    # A script edit waiting behind "Put it live": staged on the live agent, not applied.
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="UNPUBLISHED DRAFT: greet the caller and sell them a car.",
            notes=None,
            created_by=None,
        )
    run_id = await _queue(tenant_id)
    outcomes = await drain_live_apply(tenant_id)
    assert outcomes == ["walked applied=1"]

    run = await _run(run_id)
    assert (run.status, run.total, run.applied, run.failed) == ("done", 1, 1, 0)
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    held = await engine.get_agent(ref)
    assert "UNPUBLISHED DRAFT" not in (held.system_prompt or "")
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(text("SELECT status FROM agents WHERE id = :a"), {"a": draft_id})
        ).scalar()
    assert status == "draft"


async def test_a_live_agent_takes_an_update_while_its_account_owes_an_agreement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-926: two live agents kept old text on 28 Oct because their accounts had a document
    to re-accept. The agent is already on the phone; only going live waits on agreements."""
    from apps.api.legal import service as legal

    tenant_id, agent_id, _bearer = await _tenant()
    await _published(tenant_id, agent_id)
    draft_id = await _second_agent(tenant_id)

    async def owed(_session: Any, *, tenant_id: uuid.UUID) -> tuple[str, str]:
        return (legal.AGREEMENTS_RULE, legal.AGREEMENTS_REASON)

    monkeypatch.setattr(legal, "agreements_blocker", owed)
    run_id = await _queue(tenant_id)
    assert await drain_live_apply(tenant_id) == ["walked applied=1"]
    assert (await _run(run_id)).failed == 0

    from apps.api.agents.service import publish_agent

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as refused:
            await publish_agent(session, tenant_id=tenant_id, agent_id=draft_id)
    assert refused.value.code == legal.AGREEMENTS_RULE


async def test_an_agent_the_platform_walk_failed_is_tried_once_more_at_the_next_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _bearer = await _tenant()
    await _published(tenant_id, agent_id)
    revision = uuid.uuid4().hex[:16]
    monkeypatch.setattr(live_apply, "platform_prompt_revision", lambda: revision)
    async with untenanted_session() as session:
        run_id = await live_apply.queue_platform_prompt_apply(session)
        failure = {"tenant_id": str(tenant_id), "agent_id": str(agent_id), "code": "x"}
        await session.execute(
            text(
                "UPDATE live_apply_runs SET status = 'done', finished_at = now(), "
                "walked_at = now(), failures = CAST(:f AS jsonb) WHERE id = :id"
            ),
            {"f": json.dumps([failure]), "id": run_id},
        )

    async def agent_runs() -> list[Any]:
        async with untenanted_session() as session:
            return list(
                (
                    await session.execute(
                        text(
                            "SELECT reasons FROM live_apply_runs "
                            "WHERE scope = 'agent' AND agent_id = :a"
                        ),
                        {"a": agent_id},
                    )
                ).scalars()
            )

    for _start in range(2):
        async with untenanted_session() as session:
            assert await live_apply.queue_platform_prompt_apply(session) is None
    assert await agent_runs() == [[f"platform_prompt:{revision}:retry"]]


async def test_a_platform_wide_change_is_walked_in_bounded_batches_from_a_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _bearer = await _tenant()
    await _published(tenant_id, agent_id)
    second = await _second_agent(tenant_id)
    await _published(tenant_id, second)
    seen = _counting(monkeypatch)
    monkeypatch.setattr(worker, "BATCH_SIZE", 1)
    run_id = await _queue(tenant_id)

    first = await worker.apply_live_settings({}, {"run_id": str(run_id)})
    assert first == "continued applied=1"
    middle = await _run(run_id)
    assert middle.status == "running" and middle.applied == 1
    # The continuation is a fresh outbox message, so other queued work takes its turn.
    assert await _outbox(APPLY_JOB, run_id) == 2
    assert await worker.apply_live_settings({}, {"run_id": str(run_id)}) == "continued applied=1"
    assert await worker.apply_live_settings({}, {"run_id": str(run_id)}) == "walked applied=0"
    done = await _run(run_id)
    assert (done.status, done.total, done.applied) == ("done", 2, 2)
    assert len(seen) == 2


async def test_a_refusal_no_retry_can_fix_is_recorded_and_alarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _bearer = await _tenant()
    await _published(tenant_id, agent_id)
    alarms: list[tuple[str, dict[str, str]]] = []
    monkeypatch.setattr(worker, "alert", lambda stage, code, **kw: alarms.append((code, kw)))

    async def refused(**_: Any) -> Any:
        raise ProblemError.business_rule("engine_prompt_too_long", "The script is too long.")

    monkeypatch.setattr(worker, "converge_agent", refused)
    run_id = await _queue(tenant_id)
    await drain_live_apply(tenant_id)

    run = await _run(run_id)
    assert (run.status, run.applied, run.failed, run.retrying) == ("done", 0, 1, 0)
    assert run.failures[0]["code"] == "engine_prompt_too_long"
    assert run.failures[0]["agent_id"] == str(agent_id)
    assert run.failures[0]["agent_name"]
    assert [code for code, _ in alarms] == ["live_apply_agent_failed"]


async def test_a_transient_failure_retries_that_agent_and_settles_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _bearer = await _tenant()
    await _published(tenant_id, agent_id)
    real = worker.converge_agent

    async def flaky(**_: Any) -> Any:
        raise ProblemError(
            kind="dependency", code="engine_unreachable", title="x", detail="vendor down"
        )

    monkeypatch.setattr(worker, "converge_agent", flaky)
    run_id = await _queue(tenant_id)
    await drain_live_apply(tenant_id)
    waiting = await _run(run_id)
    assert (waiting.status, waiting.retrying, waiting.applied) == ("running", 1, 0)
    assert await _outbox(AGENT_JOB, run_id) == 1

    payload = {"run_id": str(run_id), "tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    with pytest.raises(Exception) as retried:
        await worker.apply_live_agent({"job_try": 1}, payload)
    assert type(retried.value).__name__ == "Retry"

    monkeypatch.setattr(worker, "converge_agent", real)
    assert await worker.apply_live_agent({"job_try": 2}, payload) == "applied"
    settled = await _run(run_id)
    assert (settled.status, settled.retrying, settled.applied, settled.failed) == (
        "done",
        0,
        1,
        0,
    )


async def test_a_retry_is_queued_in_the_transaction_that_moves_the_cursor_past_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committed apart, a worker dying between the two re-walked the agent on resume and
    queued a second retry that `retrying` counted once, so the run never finished."""
    tenant_id, agent_id, _bearer = await _tenant()
    await _published(tenant_id, agent_id)

    async def flaky(**_: Any) -> Any:
        raise ProblemError(kind="dependency", code="engine_unreachable", title="x", detail="y")

    real_queue = worker.queue_agent_retry
    cursor_at_queue: list[Any] = []

    async def spy(session: Any, run: uuid.UUID, **kwargs: Any) -> Any:
        cursor_at_queue.append(
            (
                await session.execute(
                    text("SELECT cursor_agent_id, retrying FROM live_apply_runs WHERE id = :id"),
                    {"id": run},
                )
            ).one()
        )
        return await real_queue(session, run, **kwargs)

    monkeypatch.setattr(worker, "converge_agent", flaky)
    monkeypatch.setattr(worker, "queue_agent_retry", spy)
    run_id = await _queue(tenant_id)
    await drain_live_apply(tenant_id)
    assert [(str(c), r) for c, r in cursor_at_queue] == [(str(agent_id), 1)]
    assert await _outbox(AGENT_JOB, run_id) == 1


async def test_an_agent_that_never_recovers_is_given_up_and_alarmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, _bearer = await _tenant()
    await _published(tenant_id, agent_id)
    alarms: list[str] = []
    monkeypatch.setattr(worker, "alert", lambda stage, code, **kw: alarms.append(code))

    async def down(**_: Any) -> Any:
        raise ProblemError(kind="dependency", code="engine_unreachable", title="x", detail="y")

    monkeypatch.setattr(worker, "converge_agent", down)
    run_id = await _queue(tenant_id)
    await drain_live_apply(tenant_id)
    payload = {"run_id": str(run_id), "tenant_id": str(tenant_id), "agent_id": str(agent_id)}
    assert await worker.apply_live_agent({"job_try": WORKER_MAX_TRIES}, payload) == "failed"
    run = await _run(run_id)
    assert (run.status, run.failed, run.retrying) == ("done", 1, 0)
    assert alarms == ["live_apply_agent_failed"]


# ------------------------------------------------------------------ the sources


async def test_a_platform_setting_live_agents_carry_queues_the_platform_run() -> None:
    from apps.api.core.settings import get_settings
    from apps.api.ops import config_service
    from tests.platform_config_hardening_test import _admin_id

    admin_id = await _admin_id()
    async with untenanted_session() as session:
        before = (await config_service.read_rows(session)).get("thinnest_byok_enabled")
        written = await config_service.set_value(
            session,
            key="thinnest_byok_enabled",
            value=not get_settings().thinnest_byok_enabled,
            note="live apply test",
            actor_id=admin_id,
            expected_revision=before.revision if before else 0,
        )
    try:
        assert written.live_apply_run_id is not None
        run = await _run(written.live_apply_run_id)
        assert run.scope == "platform"
        assert "thinnest_byok_enabled" in run.reasons
        assert await _outbox(APPLY_JOB, written.live_apply_run_id) == 1
    finally:
        async with untenanted_session() as session:
            await config_service.clear_value(
                session,
                key="thinnest_byok_enabled",
                actor_id=admin_id,
                expected_revision=written.revision,
            )
            # A pending platform run absorbs every later tenant request (it walks them
            # anyway). Nothing walks it in this suite, so it is closed here rather than
            # left to absorb the next test's tenant run.
            await session.execute(
                text(
                    "UPDATE live_apply_runs SET status = 'superseded', lease_until = NULL "
                    "WHERE scope = 'platform' AND status IN ('pending', 'running')"
                )
            )


def test_a_live_setting_is_not_a_live_agents_setting() -> None:
    from apps.api.core.platform_config import LIVE, applies_rule

    assert applies_rule("trial_daily_call_cap").applies == LIVE


def _lead_calling_app() -> FastAPI:
    from apps.api.core.errors import install_error_handlers

    application = FastAPI()
    install_error_handlers(application)
    application.include_router(lead_calling_router)
    return application


async def test_the_answering_machine_switch_queues_the_clients_live_apply() -> None:
    tenant_id, agent_id, bearer = await _tenant()
    await _published(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {bearer}"}
    async with AsyncClient(
        transport=ASGITransport(app=_lead_calling_app()), base_url="http://api"
    ) as client:
        current = (await client.get("/v1/lead-calling", headers=headers)).json()
        body = {
            key: current[key]
            for key in (
                "calling_agent_id",
                "wait_seconds",
                "hours_start",
                "hours_end",
                "days",
                "holidays",
                "after_hours",
                "retry_attempts",
                "retry_interval_minutes",
            )
        }
        body["detect_machines"] = not current["detect_machines"]
        saved = await client.put("/v1/lead-calling", headers=headers, json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json()["agents_updated"] == 1
    async with untenanted_session() as session:
        reasons = (
            await session.execute(
                text("SELECT reasons FROM live_apply_runs WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert reasons == ["lead_calling.detect_machines"]
    assert await drain_live_apply(tenant_id) == ["walked applied=1"]


# ------------------------------------------------------------------ notices never greet


def test_no_notice_template_greets() -> None:
    from apps.api.compliance.disclosure import (
        AI_DISCLOSURE_TEMPLATES,
        RECORDING_NOTICE_TEMPLATES,
    )

    greetings = ("namaskaram", "namaskar", "namaste", "hello", "hi ", "vanakkam")
    for template in [*AI_DISCLOSURE_TEMPLATES.values(), *RECORDING_NOTICE_TEMPLATES.values()]:
        assert template.strip(), "a notice may never be blank"
        assert not template.lower().startswith(greetings), template
    # The truthful content stays: who is calling, and that the call is recorded.
    assert all(
        any(ai in t for ai in ("AI assistant", "ఏఐ అసిస్టెంట్", "एआई असिस्टेंट"))
        for t in AI_DISCLOSURE_TEMPLATES.values()
    )
    assert all(
        any(word in t for word in ("record", "రికార్డ్", "रिकॉर्ड"))
        for t in RECORDING_NOTICE_TEMPLATES.values()
    )


async def test_the_migration_rewrites_only_exact_old_outputs_and_queues_the_client() -> None:
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from apps.api.core.settings import get_settings
    from sqlalchemy import create_engine as create_sync_engine
    from tests.disclosure_toggle_test import _load_revision

    tenant_id, agent_id, _bearer = await _tenant()
    await _published(tenant_id, agent_id)
    edited = await _second_agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        name = (await session.execute(text("SELECT name FROM organizations"))).scalar()
        await session.execute(
            text(
                "UPDATE agents SET ai_disclosure_line = :ai, disclosure_line = :bundle "
                "WHERE id = :a"
            ),
            {
                "ai": f"Namaskaram, idi {name} AI assistant.",
                "bundle": f"Namaskaram, idi {name} AI assistant. Ee call record avutundi.",
                "a": agent_id,
            },
        )
        await session.execute(
            text("UPDATE agents SET ai_disclosure_line = :ai WHERE id = :a"),
            {"ai": "Namaskaram! Our own words, edited by a person.", "a": edited},
        )

    revision = _load_revision("a2d8e6c4f1b7_notices_carry_no_greeting")
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    sync = create_sync_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    revision.upgrade()
                    lines = dict(
                        connection.execute(
                            text(
                                "SELECT id, ai_disclosure_line || ' | ' || disclosure_line "
                                "FROM agents WHERE id IN (:a, :b)"
                            ),
                            {"a": agent_id, "b": edited},
                        )
                        .tuples()
                        .all()
                    )
                    assert lines[agent_id] == (
                        f"Idi {name} AI assistant. | Idi {name} AI assistant. "
                        "Ee call record avutundi."
                    )
                    assert lines[edited].startswith("Namaskaram! Our own words")
                    queued = connection.execute(
                        text(
                            "SELECT count(*) FROM live_apply_runs r JOIN outbox_messages m "
                            "ON m.payload->>'run_id' = r.id::text WHERE r.tenant_id = :t "
                            "AND r.reasons ? 'notice_greeting_removed'"
                        ),
                        {"t": tenant_id},
                    ).scalar_one()
                    assert queued == 1
                    revision.downgrade()
                    restored = connection.execute(
                        text("SELECT ai_disclosure_line FROM agents WHERE id = :a"),
                        {"a": agent_id},
                    ).scalar_one()
                    # Created after the template changed, so a downgrade leaves it alone.
                    assert restored == f"Idi {name} AI assistant."
            finally:
                transaction.rollback()
    finally:
        sync.dispose()


async def test_a_pending_platform_run_covers_a_clients_later_change() -> None:
    tenant_id, _agent, _bearer = await _tenant()
    async with untenanted_session() as session:
        platform = await queue_live_apply(session, scope="platform", reason="webhook_base_url")
    try:
        assert await _queue(tenant_id, "business_profile") == platform
        assert (await _run(platform)).reasons == ["webhook_base_url", "business_profile"]
    finally:
        async with untenanted_session() as session:
            await session.execute(
                text("UPDATE live_apply_runs SET status = 'superseded' WHERE id = :id"),
                {"id": platform},
            )


def test_the_sarvam_key_and_the_sarvam_105b_price_are_both_on_the_ops_console() -> None:
    """The founder could not find either; both are served (checked 10 Oct 2026)."""
    from apps.api.billing import rates
    from apps.api.ops.config_catalog import PANEL_MODEL_PRICING, SECTIONS
    from apps.api.ops.secret_service import manageable_secret_keys

    assert "sarvam_api_key" in manageable_secret_keys()
    assert "sarvam-105b" in rates.INR_PRICED_LLMS
    # The rupee prices render inside the Model prices panel, which a served section mounts.
    assert [s.id for s in SECTIONS if PANEL_MODEL_PRICING in s.panels_after] == ["language-models"]


# ------------------------------------------------------------------ a deploy's prompt text


async def test_a_new_platform_prompt_revision_queues_one_platform_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-739: a worker starting on a build whose platform text changed walks the fleet once;
    the next start, and a second worker starting beside it, queue nothing."""
    revision = uuid.uuid4().hex[:16]
    monkeypatch.setattr(live_apply, "platform_prompt_revision", lambda: revision)
    async with untenanted_session() as session:
        run_id = await live_apply.queue_platform_prompt_apply(session)
    assert run_id is not None
    run = await _run(run_id)
    assert (run.scope, run.reasons) == ("platform", [f"platform_prompt:{revision}"])
    assert await _outbox(APPLY_JOB, run_id) == 1
    async with untenanted_session() as session:
        assert await live_apply.queue_platform_prompt_apply(session) is None


def test_the_platform_prompt_revision_is_stable_and_short() -> None:
    first = live_apply.platform_prompt_revision()
    assert first == live_apply.platform_prompt_revision()
    assert len(first) == 16


def test_a_new_call_behaviour_value_moves_the_platform_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The filler delay, re-ask wait and greeting rule ship by deploy (D-835); the worker-start
    republish keys on this revision, so changing one must move it."""
    from apps.api.engine import hosted_platform

    before = live_apply.platform_prompt_revision()
    changed = {**hosted_platform.PLATFORM_AGENT_VALUES["thinnest"], "reaskAfterSeconds": 6}
    monkeypatch.setitem(hosted_platform.PLATFORM_AGENT_VALUES, "thinnest", changed)
    assert live_apply.platform_prompt_revision() != before
