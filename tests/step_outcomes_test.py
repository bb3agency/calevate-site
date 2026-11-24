"""D-1036: Pip writes the outcome of every step that has none, for any campaign or inbound line.

The model is a stub, so what is asserted is the seam: a save that leaves a step without an
outcome queues one pass per burst, the pass writes only the missing outcomes and never one
that is there, an owner's save made while Pip wrote wins, the sweep finds the holders no save
reached, and the SQL worklist agrees with the Python rule.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.campaigns import service as campaigns
from apps.api.campaigns import step_outcomes as outcomes_api
from apps.api.campaigns import workspace
from apps.api.core.errors import ProblemError
from apps.api.db.session import admin_session, tenant_session
from apps.api.inbound import lines as inbound_lines
from apps.workers import step_outcomes as worker
from apps.workers.extraction import (
    PROVIDER_UNAVAILABLE_REASON,
    AssistCapability,
    assist_unavailable,
)
from apps.workers.script_assist import UnusableAnswerError
from calevate_shared.call_script import (
    SCRIPT_SCHEMA_VERSION,
    CallScript,
    ConversationStage,
    StepOutcome,
)
from sqlalchemy import text
from tests.dispatch_budget_test import _dlt_rows, _tenant

pytestmark = pytest.mark.anyio

OWNER_OUTCOME = "The person says they remember the Rytu Khata app."


def _stage(sid: str, name: str, step: int | None, instruction: str) -> ConversationStage:
    return ConversationStage(id=sid, name=name, instruction=instruction, step=step)


def _script(outcomes: list[StepOutcome] | None = None) -> CallScript:
    """Three steps; step 2 has two scenarios."""
    return CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION,
        goal="Get the app installed.",
        stages=[
            _stage("remember", "Remembers the app", 1, "Ask whether they remember Rytu Khata."),
            _stage("install", "Installs it", 2, "Ask them to install the app from Play Store."),
            _stage("installed", "Already has it", 2, "Ask them to open the installed app."),
            _stage("login", "Logs in", 3, "Ask them to log in with their 10 digit number."),
        ],
        step_outcomes=outcomes or [],
    )


def _missing_cases() -> list[tuple[CallScript, list[int]]]:
    no_steps = CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION,
        stages=[_stage("a", "A", None, "Do a."), _stage("b", "B", None, "Do b.")],
        step_outcomes=[StepOutcome(step=2, outcome="B is done.")],
    )
    return [
        (_script(), [1, 2, 3]),
        (_script([StepOutcome(step=1, outcome=OWNER_OUTCOME)]), [2, 3]),
        (
            _script([StepOutcome(step=n, outcome=f"Step {n} done.") for n in (1, 2, 3)]),
            [],
        ),
        (no_steps, [1]),
        (CallScript(raw_override="Say hello."), []),
        (CallScript(schema_version=SCRIPT_SCHEMA_VERSION, goal="Nothing yet."), []),
    ]


def test_missing_steps_follow_the_steps_scenarios_share() -> None:
    for script, missing in _missing_cases():
        assert outcomes_api.missing_steps(script) == missing


async def test_the_sql_worklist_rule_agrees_with_the_python_rule() -> None:
    async with admin_session() as session:
        for script, missing in _missing_cases():
            lacks = (
                await session.execute(
                    text("SELECT script_lacks_step_outcome(CAST(:s AS jsonb))"),
                    {"s": script.model_dump_json()},
                )
            ).scalar_one()
            assert lacks is bool(missing), script.model_dump_json()
        assert (
            await session.execute(text("SELECT script_lacks_step_outcome(NULL)"))
        ).scalar_one() is not True


def test_only_grounded_outcomes_for_missing_steps_are_kept() -> None:
    material = "Ask them to install the app from Play Store. Ask them to log in with their number."
    raw = {
        "outcomes": [
            {
                "step": 2,
                "outcome": "The person says the app is installed.",
                "quote": "install the app from Play Store",
            },
            # The quote is not in the material: a paraphrase does not count.
            {
                "step": 3,
                "outcome": "The person says they logged in.",
                "quote": "sign in with an OTP",
            },
            # A figure the material never states.
            {
                "step": 3,
                "outcome": "The person says they paid 499 rupees.",
                "quote": "log in with their number",
            },
            # Step 1 is not missing: an outcome there is never written over.
            {"step": 1, "outcome": "Something else.", "quote": "install the app"},
            {"step": 9, "outcome": "No such step.", "quote": "install the app"},
        ]
    }
    request = worker.Request(
        text="", material=material, naming="", cases=(), targets=(2, 3), subject="person"
    )
    written = worker.accepted(raw, request)
    assert written is not None and written.outcomes == {2: "The person says the app is installed."}


def test_writing_outcomes_never_replaces_one_that_is_there() -> None:
    script = _script([StepOutcome(step=1, outcome=OWNER_OUTCOME)])
    written = worker.with_outcomes(
        script, {1: "Pip's other words.", 2: "Installed.", 3: "Logged in."}
    )
    assert {o.step: o.outcome for o in written.step_outcomes} == {
        1: OWNER_OUTCOME,
        2: "Installed.",
        3: "Logged in.",
    }


# --- the database seam ----------------------------------------------------------------------


@pytest.fixture
def pip_on(monkeypatch: pytest.MonkeyPatch) -> None:
    async def yes(_session: Any, *, tenant_id: uuid.UUID) -> bool:
        return True

    monkeypatch.setattr(outcomes_api, "account_content_may_reach_models", yes)
    monkeypatch.setattr(worker, "account_content_may_reach_models", yes)


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        return await campaigns.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Rytu Khata installs",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )


async def _jobs(tenant_id: uuid.UUID, holder_id: uuid.UUID) -> list[dict[str, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE job = :j ORDER BY created_at"),
                {"j": outcomes_api.JOB},
            )
        ).all()
    payloads = [r[0] if isinstance(r[0], dict) else json.loads(r[0]) for r in rows]
    return [p for p in payloads if str(holder_id) in (p.get("campaign_id"), p.get("line_id"))]


async def _state(tenant_id: uuid.UUID, table: str, holder_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    f"SELECT step_outcomes_state, step_outcomes_at, step_outcomes_inputs, script "
                    f"FROM {table} WHERE id = :h"
                ),
                {"h": holder_id},
            )
        ).one()


async def _save_campaign(tenant_id: uuid.UUID, campaign_id: uuid.UUID, script: CallScript) -> None:
    async with tenant_session(tenant_id) as session:
        await workspace.save_script(session, campaign_id, script, author="owner")


async def _past_debounce(tenant_id: uuid.UUID, table: str, holder_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                f"UPDATE {table} SET step_outcomes_at = now() - interval '1 minute' WHERE id = :h"
            ),
            {"h": holder_id},
        )


async def test_a_burst_of_saves_leaving_a_step_without_an_outcome_queues_one_pass(
    pip_on: None,
) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)

    await _save_campaign(tenant_id, campaign_id, _script())
    first = await _state(tenant_id, "campaigns", campaign_id)
    await _save_campaign(
        tenant_id, campaign_id, _script([StepOutcome(step=1, outcome=OWNER_OUTCOME)])
    )
    second = await _state(tenant_id, "campaigns", campaign_id)

    assert len(await _jobs(tenant_id, campaign_id)) == 1
    assert first[0] == second[0] == "queued"
    # The second save pushed the waiting pass back: one pass over the script the owner ended with.
    assert second[1] >= first[1]
    async with tenant_session(tenant_id) as session:
        assert (await workspace.read_workspace(session, campaign_id)).step_outcomes_pending


async def test_a_save_with_every_outcome_written_queues_nothing(pip_on: None) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    full = _script([StepOutcome(step=n, outcome=f"Step {n} done.") for n in (1, 2, 3)])

    await _save_campaign(tenant_id, campaign_id, full)

    assert await _jobs(tenant_id, campaign_id) == []
    assert (await _state(tenant_id, "campaigns", campaign_id))[0] is None


async def test_a_line_save_queues_too_and_waits_while_pip_is_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no(_session: Any, *, tenant_id: uuid.UUID) -> bool:
        return False

    monkeypatch.setattr(outcomes_api, "account_content_may_reach_models", no)
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        line_id = await inbound_lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Help", created_by=None
        )
        await inbound_lines.save_script(session, line_id, _script(), author="owner")

    assert await _jobs(tenant_id, line_id) == []
    assert (await _state(tenant_id, "inbound_lines", line_id))[0] == "skipped"


def _stub_model(
    monkeypatch: pytest.MonkeyPatch,
    raw: Callable[[], dict[str, Any]],
    *,
    during: Callable[[], Any] | None = None,
) -> list[str]:
    asked: list[str] = []

    async def fake_ask_json(request: str, _instruction: str, **kwargs: Any) -> Any:
        asked.append(request)
        if during is not None:
            await during()
        answer = raw()
        try:
            value = kwargs["parse"](answer)
        except UnusableAnswerError:
            value = kwargs["salvage"](answer)
        if value is None:
            raise ProblemError.business_rule("assist_answer_unusable", "Unusable.")
        return SimpleNamespace(value=value, earlier=(), model=None, capability=None)

    async def no_meter(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "ask_json", fake_ask_json)
    monkeypatch.setattr(worker.crm_assist, "meter_assist", no_meter)
    monkeypatch.setattr(worker.crm_assist, "meter_earlier", no_meter)
    return asked


def _answer() -> dict[str, Any]:
    return {
        "outcomes": [
            {"step": 1, "outcome": "Pip would say otherwise.", "quote": "Rytu Khata"},
            {
                "step": 2,
                "outcome": "The person says the app is installed and open.",
                "quote": "install the app",
            },
            {"step": 3, "outcome": "The person says they are logged in.", "quote": "log in"},
        ]
    }


async def test_the_pass_writes_only_the_missing_outcomes(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _save_campaign(
        tenant_id, campaign_id, _script([StepOutcome(step=1, outcome=OWNER_OUTCOME)])
    )
    await _past_debounce(tenant_id, "campaigns", campaign_id)
    asked = _stub_model(monkeypatch, _answer)

    result = await worker.write_step_outcomes(
        {}, {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)}
    )

    assert result == "saved"
    state, _at, inputs, raw = await _state(tenant_id, "campaigns", campaign_id)
    assert state == "done" and inputs
    assert {o.step: o.outcome for o in CallScript.model_validate(raw).step_outcomes} == {
        1: OWNER_OUTCOME,
        2: "The person says the app is installed and open.",
        3: "The person says they are logged in.",
    }
    # The request names only the steps without one, and carries the owner's as context.
    assert "STEP 2" in asked[0] and "STEP 3" in asked[0] and "STEP 1\n" not in asked[0]
    # A complete script: nothing more to queue, and the screen stops showing Pip at work.
    async with tenant_session(tenant_id) as session:
        assert not (await workspace.read_workspace(session, campaign_id)).step_outcomes_pending


async def test_an_owner_save_made_while_pip_writes_wins(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _save_campaign(tenant_id, campaign_id, _script())
    await _past_debounce(tenant_id, "campaigns", campaign_id)
    owners = _script([StepOutcome(step=n, outcome=f"Owner's step {n}.") for n in (1, 2, 3)])

    async def owner_saves() -> None:
        await _save_campaign(tenant_id, campaign_id, owners)

    _stub_model(monkeypatch, _answer, during=owner_saves)

    result = await worker.write_step_outcomes(
        {}, {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)}
    )

    assert result == "stale"
    _state_now, _at, inputs, raw = await _state(tenant_id, "campaigns", campaign_id)
    assert CallScript.model_validate(raw) == owners
    assert inputs is None


async def test_a_line_saved_meanwhile_keeps_its_version_and_script(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        line_id = await inbound_lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Help", created_by=None
        )
        await inbound_lines.save_script(session, line_id, _script(), author="owner")
    await _past_debounce(tenant_id, "inbound_lines", line_id)
    edited = _script().model_copy(update={"goal": "The owner changed the goal."})

    async def owner_saves() -> None:
        async with tenant_session(tenant_id) as session:
            await inbound_lines.save_script(session, line_id, edited, author="owner")

    _stub_model(monkeypatch, _answer, during=owner_saves)

    result = await worker.write_step_outcomes(
        {}, {"tenant_id": str(tenant_id), "line_id": str(line_id)}
    )

    assert result == "stale"
    state, _at, _inputs, raw = await _state(tenant_id, "inbound_lines", line_id)
    assert CallScript.model_validate(raw) == edited
    # The owner's save left steps without outcomes, so its own pass waits.
    assert state == "queued"


async def test_a_pass_asked_for_moments_ago_waits_out_the_burst(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _save_campaign(tenant_id, campaign_id, _script())
    deferred: list[dict[str, Any]] = []

    async def fake_enqueue(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        deferred.append({"job": job, **kwargs})
        return "id"

    monkeypatch.setattr(worker, "enqueue", fake_enqueue)

    result = await worker.write_step_outcomes(
        {}, {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)}
    )

    assert result == "deferred"
    assert deferred[0]["job"] == outcomes_api.JOB and deferred[0]["_defer_until"] > datetime.now(
        UTC
    )
    assert (await _state(tenant_id, "campaigns", campaign_id))[0] == "queued"


async def test_the_same_script_is_not_asked_about_twice(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _save_campaign(tenant_id, campaign_id, _script())
    await _past_debounce(tenant_id, "campaigns", campaign_id)
    # An answer the code cannot stand behind: nothing grounded, so nothing is saved.
    asked = _stub_model(monkeypatch, lambda: {"outcomes": []})

    async def unusable(request: str, _instruction: str, **kwargs: Any) -> Any:
        asked.append(request)
        from apps.api.core.errors import ProblemError

        raise ProblemError.business_rule("assist_answer_unusable", "Unusable.")

    monkeypatch.setattr(worker, "ask_json", unusable)
    payload = {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)}
    assert await worker.write_step_outcomes({}, payload) == "assist_answer_unusable"
    async with tenant_session(tenant_id) as session:
        await outcomes_api.queue_after_save(session, "campaign", campaign_id, _script())
    await _past_debounce(tenant_id, "campaigns", campaign_id)

    assert await worker.write_step_outcomes({}, payload) == "unchanged"
    assert len(asked) == 1


async def test_a_ladder_no_model_answered_is_asked_again_on_the_same_script(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _save_campaign(tenant_id, campaign_id, _script())
    await _past_debounce(tenant_id, "campaigns", campaign_id)
    asked = _stub_model(monkeypatch, _answer)
    answering = worker.ask_json

    async def outage(request: str, _instruction: str, **kwargs: Any) -> Any:
        asked.append(request)
        raise assist_unavailable(
            AssistCapability(available=False, reason=PROVIDER_UNAVAILABLE_REASON)
        )

    monkeypatch.setattr(worker, "ask_json", outage)
    payload = {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)}
    assert await worker.write_step_outcomes({}, payload) == f"assist_{PROVIDER_UNAVAILABLE_REASON}"
    state, _at, inputs, _raw = await _state(tenant_id, "campaigns", campaign_id)
    assert state == "failed" and inputs is None, "an outage is not a reading of the script"

    monkeypatch.setattr(worker, "ask_json", answering)
    async with tenant_session(tenant_id) as session:
        await outcomes_api.queue_after_save(session, "campaign", campaign_id, _script())
    await _past_debounce(tenant_id, "campaigns", campaign_id)
    assert await worker.write_step_outcomes({}, payload) == "saved"
    assert len(asked) == 2


async def test_a_used_up_allowance_waits_and_writes_once_it_renews(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _save_campaign(tenant_id, campaign_id, _script())
    await _past_debounce(tenant_id, "campaigns", campaign_id)
    asked = _stub_model(monkeypatch, _answer)
    real_quota = worker.read_ai_quota

    async def used_up(_session: Any, *, tenant_id: uuid.UUID) -> Any:
        return SimpleNamespace(at_ceiling=True, platform_paused=False)

    monkeypatch.setattr(worker, "read_ai_quota", used_up)
    payload = {"tenant_id": str(tenant_id), "campaign_id": str(campaign_id)}
    assert await worker.write_step_outcomes({}, payload) == "skipped"
    state, _at, inputs, _raw = await _state(tenant_id, "campaigns", campaign_id)
    assert asked == [] and state == "skipped" and inputs is None

    monkeypatch.setattr(worker, "read_ai_quota", real_quota)
    monkeypatch.setattr(worker, "HOLDERS_PER_TICK", 100_000)
    await worker.sweep_step_outcomes({})
    await _past_debounce(tenant_id, "campaigns", campaign_id)
    assert await worker.write_step_outcomes({}, payload) == "saved"
    assert len(asked) == 1


async def test_the_sweep_queues_only_holders_lacking_an_outcome_no_pass_covered(
    pip_on: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(worker, "HOLDERS_PER_TICK", 100_000)
    tenant_id, agent_id = await _tenant()
    lacking = await _campaign(tenant_id, agent_id)
    complete = await _campaign(tenant_id, agent_id)
    covered = await _campaign(tenant_id, agent_id)
    full = _script([StepOutcome(step=n, outcome=f"Step {n} done.") for n in (1, 2, 3)])
    async with tenant_session(tenant_id) as session:
        for cid, script, state in (
            (lacking, _script(), None),
            (complete, full, None),
            (covered, _script(), "done"),
        ):
            await session.execute(
                text(
                    "UPDATE campaigns SET script = CAST(:s AS jsonb), step_outcomes_state = :st "
                    "WHERE id = :c"
                ),
                {"s": script.model_dump_json(), "st": state, "c": cid},
            )

    await worker.sweep_step_outcomes({})

    assert len(await _jobs(tenant_id, lacking)) == 1
    assert await _jobs(tenant_id, complete) == []
    assert await _jobs(tenant_id, covered) == []
    assert (await _state(tenant_id, "campaigns", lacking))[0] == "queued"


async def _yes(_session: Any, *, tenant_id: uuid.UUID) -> bool:
    return True


async def test_another_accounts_holder_is_invisible_to_the_pass_seam(pip_on: None) -> None:
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    campaign_id = await _campaign(tenant_a, agent_a)
    await _save_campaign(tenant_a, campaign_id, _script())

    async with tenant_session(tenant_b) as session:
        assert not await outcomes_api.pending(session, "campaign", campaign_id)
        assert not await outcomes_api.queue_after_save(session, "campaign", campaign_id, _script())
        rows = (
            await session.execute(
                text("SELECT count(*) FROM campaigns WHERE step_outcomes_state IS NOT NULL")
            )
        ).scalar_one()
    assert rows == 0
    assert len(await _jobs(tenant_a, campaign_id)) == 1
