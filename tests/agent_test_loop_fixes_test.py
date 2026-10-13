"""The test-and-improve loop's defects from the founder's screenshot of 11 Oct 2026 (D-748).

- the agent answered a Telugu caller in English, talking about "the caller": the speech
  checks now fail both, and our opt-out answer no longer hands the model a third-person
  English sentence to read out;
- "the request not to be called again was not recorded" in a test chat, which has no number
  to record: only a missing step fails now;
- "AI help could not write new test callers" said nothing about why;
- the 500 on "Improve my agent": the allowance read took the tenant's credit lock, the route
  then ran the improver inline and its own session waited on that lock until the statement
  timeout. The read no longer locks, the route queues a job, and a cancelled statement is a
  503 "try again", never a 500.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from typing import Any

import pytest
from apps.api.agents import test_conversations
from apps.api.agents.test_conversations import Turn, decide, probe_scenario
from apps.api.agents.turn_checks import PLATFORM_KINDS, turn_problems
from apps.api.billing.ai_quota import read_ai_quota
from apps.api.billing.service import lock_tenant_credits
from apps.api.core.errors import ProblemError, unhandled_problem_response
from apps.api.core.settings import get_settings
from apps.api.db.session import long_running_statements, tenant_session
from apps.api.main import app
from apps.api.reliability.engine_actions import ACTION_NAMES, OPT_OUT
from apps.api.worker.in_call_tools import OPTOUT_DONE_SAY
from apps.workers import agent_test_ai, chat
from apps.workers import agent_test_conversations as worker
from apps.workers.extraction import PROVIDER_UNAVAILABLE_REASON
from apps.workers.script_assist import ask_json
from calevate_shared.call_script import CallScript, ConversationStage
from httpx import ASGITransport, AsyncClient
from psycopg import errors as pg_errors
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from tests.api_security_test import _make_tenant

OPT_OUT_TOOL = ACTION_NAMES[OPT_OUT]

#: The two replies in the founder's screenshot, word for word.
SCREENSHOT_OPT_OUT_REPLY = (
    "The caller's number has been added to the do-not-call list. They will not receive any "
    "further calls."
)
TELUGU_STOP = test_conversations.PROBE_LINES["stop_calling"]["te-IN"]


# --- (a) language and person -------------------------------------------------------------


def test_an_english_third_person_reply_to_a_telugu_caller_fails_on_our_side() -> None:
    kinds = {
        p.kind
        for p in turn_problems(SCREENSHOT_OPT_OUT_REPLY, caller_said=TELUGU_STOP, language="te-IN")
    }
    assert {"wrong_language", "third_person"} <= kinds
    assert {"wrong_language", "third_person"} <= PLATFORM_KINDS


def test_a_code_mixed_telugu_reply_is_not_the_wrong_language() -> None:
    reply = "సరే అండి, మీ number remove చేశాం. మళ్ళీ call రాదు."
    kinds = {p.kind for p in turn_problems(reply, caller_said=TELUGU_STOP, language="te-IN")}
    assert "wrong_language" not in kinds and "third_person" not in kinds


def test_an_english_agent_answering_in_english_is_not_the_wrong_language() -> None:
    # The caller wrote Telugu but the agent's own language is English: it may answer in it.
    kinds = {
        p.kind
        for p in turn_problems(
            "Sure, I have removed your number.", caller_said=TELUGU_STOP, language="en-IN"
        )
    }
    assert "wrong_language" not in kinds


def test_our_opt_out_answer_is_an_instruction_not_a_sentence_about_the_caller() -> None:
    """FAILS IF the action's answer goes back to a third-person statement the model can read
    out as it stands (the screenshot's reply paraphrased the old one)."""
    assert not OPTOUT_DONE_SAY.lower().startswith("the caller")
    assert "language they are speaking" in OPTOUT_DONE_SAY
    assert "Do not read this note out" in OPTOUT_DONE_SAY


# --- (b) what a test chat can prove ---------------------------------------------------------


def test_the_screenshot_opt_out_fails_for_its_words_not_for_an_unprovable_write() -> None:
    result = decide(
        probe_scenario("stop_calling", "te-IN"),
        [
            Turn(
                said=TELUGU_STOP,
                reply=SCREENSHOT_OPT_OUT_REPLY,
                tools=[OPT_OUT_TOOL],
                statuses=["caller_not_matched"],
            )
        ],
        None,
        language="te-IN",
        unjudged_reason="n/a",
    )
    assert result["verdict"] == "failed" and result["fix"] == "platform"
    assert "answered in English" in result["reason"]
    assert "not recorded" not in result["reason"]
    assert result["limit"] == test_conversations.OPT_OUT_TEST_LIMIT


def test_no_opt_out_step_at_all_still_fails() -> None:
    result = decide(
        probe_scenario("stop_calling", "te-IN"),
        [Turn(said=TELUGU_STOP, reply="సరే అండి.")],
        None,
        language="te-IN",
        unjudged_reason="n/a",
    )
    assert result["verdict"] == "failed"
    assert "did not take the step" in result["reason"]


# --- (c) why the standard callers ran ---------------------------------------------------------


def test_the_worker_ai_budget_fits_the_job_timeout() -> None:
    """Two AI steps of two legs each, plus every paced message, inside `job_timeout`."""
    ai = 4 * agent_test_ai.WORKER_AI_TIMEOUT_S
    paced = test_conversations.MAX_MESSAGES * worker.PAUSE_S
    assert ai + paced < 300
    assert 2 * agent_test_ai.IMPROVE_TIMEOUT_S < 300


# --- (d) the 500 -------------------------------------------------------------------------------

CURRENT = CallScript(
    schema_version=2,
    stages=[ConversationStage(id="s1", name="Greet", instruction="Greet them.")],
)


def test_a_change_naming_several_tests_is_kept_not_a_crash() -> None:
    """The improver may answer `because` with a list. `list in set` raised TypeError, which
    reached the route as a 500."""
    proposal = agent_test_ai.proposal_from_model(
        {
            "script": {},
            "changes": [{"target": "objections", "because": ["k2", "k1"], "why": "x"}],
            "facts": [{"action": "add", "question": "Delivery?", "because": {"k": 1}, "why": "y"}],
        },
        current=CURRENT,
        keys={"k1", "k2"},
        fact_ids=set(),
    )
    assert proposal is not None
    assert proposal["changes"][0]["because"] == "k2"
    assert proposal["facts"][0]["because"] is None


async def test_a_parser_that_raises_is_no_answer_not_an_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", "sk-test", raising=False)

    async def _complete(*_: Any, **__: Any) -> Any:
        return chat.ChatOutcome(content=json.dumps({"a": 1}), finish_reason="stop")

    monkeypatch.setattr(chat, "complete", _complete)

    def _boom(_raw: dict[str, Any]) -> str:
        raise TypeError("unhashable type: 'list'")

    with pytest.raises(ProblemError) as refused:
        await ask_json("d", "i", parse=_boom)
    assert refused.value.code == f"assist_{PROVIDER_UNAVAILABLE_REASON}"


def test_a_cancelled_statement_is_a_503_try_again() -> None:
    cancelled = OperationalError(
        "SELECT 1", {}, pg_errors.QueryCanceled("canceling statement due to statement timeout")
    )
    response = unhandled_problem_response("/v1/x", cancelled)
    body = json.loads(response.body)
    assert response.status_code == 503
    assert body["type"].endswith("/database_busy") and body["retryable"] is True
    assert body["remediation"] == "Try again in a moment."
    assert response.headers["Retry-After"] == "5"


async def test_reading_the_allowance_does_not_wait_for_the_credit_lock() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    held = asyncio.Event()
    release = asyncio.Event()

    async def _hold() -> None:
        async with tenant_session(tenant_id) as session:
            await lock_tenant_credits(session, tenant_id)
            held.set()
            await release.wait()

    holder = asyncio.create_task(_hold())
    await held.wait()
    try:
        with long_running_statements(2000):
            async with tenant_session(tenant_id) as session:
                started = time.monotonic()
                await read_ai_quota(session, tenant_id=tenant_id)
        assert time.monotonic() - started < 1.5
    finally:
        release.set()
        await holder


async def _failed_run(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    run_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_test_runs (id, tenant_id, agent_id, status, results, "
                "created_at, updated_at) VALUES (:id, :t, :a, 'done', CAST(:r AS jsonb), "
                "now(), now())"
            ),
            {
                "id": run_id,
                "t": tenant_id,
                "a": agent_id,
                "r": json.dumps(
                    [{"key": "k1", "title": "Price", "verdict": "failed", "reason": "x"}]
                ),
            },
        )
    return run_id


async def test_improve_answers_at_once_while_another_transaction_holds_the_credit_lock() -> None:
    """The production 500: 10 s waiting on the credit lock, then QueryCanceled. Now the
    route queues the proposal and answers 202 with the lock held elsewhere."""
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
    run_id = await _failed_run(tenant_id, agent_id)
    held = asyncio.Event()
    release = asyncio.Event()

    async def _hold() -> None:
        async with tenant_session(tenant_id) as session:
            await lock_tenant_credits(session, tenant_id)
            held.set()
            await release.wait()

    holder = asyncio.create_task(_hold())
    await held.wait()
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
            started = time.monotonic()
            answered = await http.post(
                f"/v1/agents/{agent_id}/script/tests/{run_id}/improve",
                json={"keys": ["k1"]},
                headers={"Authorization": f"Bearer {token}", "X-Org-Slug": slug},
            )
            elapsed = time.monotonic() - started
    finally:
        release.set()
        await holder
    assert answered.status_code == 202, answered.text
    assert elapsed < 5
    latest = answered.json()["latest"]
    assert latest["id"] == str(run_id) and latest["improving"] is True
    async with tenant_session(tenant_id) as session:
        queued = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "ORDER BY created_at DESC LIMIT 1"
                ),
                {"job": test_conversations.IMPROVE_JOB},
            )
        ).scalar_one()
    assert (queued if isinstance(queued, dict) else json.loads(queued))["keys"] == ["k1"]


async def test_a_second_improve_while_one_is_working_queues_nothing_more() -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
    run_id = await _failed_run(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        first = await test_conversations.request_improvement(
            session, tenant_id=tenant_id, agent_id=agent_id, run_id=run_id, keys=None
        )
        again = await test_conversations.request_improvement(
            session, tenant_id=tenant_id, agent_id=agent_id, run_id=run_id, keys=None
        )
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages "
                    "WHERE job = :job AND payload->>'run_id' = :r"
                ),
                {"job": test_conversations.IMPROVE_JOB, "r": str(run_id)},
            )
        ).scalar_one()
    assert first.improving and again.improving
    assert queued == 1


async def test_an_improve_job_that_is_refused_tells_the_owner_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
    run_id = await _failed_run(tenant_id, agent_id)

    async def _refused(*_: Any, **__: Any) -> Any:
        raise ProblemError(kind="dependency", code="assist_quota_exhausted", title="t", detail="d")

    monkeypatch.setattr(worker, "improve_run", _refused)
    async with tenant_session(tenant_id) as session:
        await test_conversations.queue_improvement(session, tenant_id=tenant_id, run_id=run_id)
    outcome = await worker.improve_agent_test_run(
        {}, {"tenant_id": str(tenant_id), "run_id": str(run_id)}
    )
    async with tenant_session(tenant_id) as session:
        run = await test_conversations.get_run(session, agent_id, run_id)
    assert outcome == "skipped"
    assert not run.improving
    assert run.improve_note is not None and "allowance is used up" in run.improve_note

    async def _crash(*_: Any, **__: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "improve_run", _crash)
    assert (
        await worker.improve_agent_test_run(
            {}, {"tenant_id": str(tenant_id), "run_id": str(run_id)}
        )
        == "failed"
    )
    async with tenant_session(tenant_id) as session:
        run = await test_conversations.get_run(session, agent_id, run_id)
    assert run.improve_note == worker.IMPROVE_FAILED_NOTE


# --- (e) the agent is behind while the agreements wait -------------------------------------


async def test_a_live_agent_with_agreements_waiting_says_its_tests_are_on_older_instructions() -> (
    None
):
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_t' WHERE id = :id"), {"id": agent_id}
        )
        note = await test_conversations.waiting_update(session, tenant_id, agent_id)
    assert note == test_conversations.WAITING_FOR_AGREEMENTS
