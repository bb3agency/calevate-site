"""D-820: Pip's script suggestion, held to `docs/COPILOT-CONTRACT.md` §5.

The planner's canonical arguments and refusals, the confirm that records the request and
queues the writer with its audit row, the job that writes, meters and stores the proposal
once, the Script page's read and clear, and the neighbour's agent refused at every door.
The model is replaced at `script_proposal.draft_script`; no credential, no network.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from calevate_shared.call_script import CallScript, ConversationStage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.agents import script_builder, script_proposals, test_conversations
from apps.api.copilot import script_actions, write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.schemas import CopilotProposalEvent
from apps.api.copilot.write_tools_test import _audit, _confirm, _outbox_jobs, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.workers import script_proposal as worker
from apps.workers.extraction import AssistCapability
from apps.workers.script_assist import CONVERT_INSTRUCTION, OWNER_QUESTIONS, ScriptDraft

TOOL = "agent_script_suggest"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _agent_of(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).first()
    assert row is not None
    return UUID(str(row[0]))


async def _set_draft(tenant_id: UUID, agent_id: UUID, script: CallScript) -> None:
    async with tenant_session(tenant_id) as session:
        await script_builder.save_draft(session, agent_id, script)


def _stepped(opening: str = "Namaste, Sunrise here.") -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=opening,
        stages=[ConversationStage(id="greet", name="Greet", instruction="Greet the caller.")],
    )


def _args(agent_id: UUID, **overrides: Any) -> dict[str, Any]:
    return {
        "agent_id": str(agent_id),
        "mode": "change",
        "change": "Make the opening line warmer and shorter",
        "answers": None,
    } | overrides


async def _propose(
    tenant_id: UUID, token: str, args: dict[str, Any], *, role: str = "owner"
) -> CopilotProposalEvent:
    return await write_tools.plan_write(
        TOOL,
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token), role=role)),
    )


@pytest.fixture(autouse=True)
def _allowance_open(monkeypatch: pytest.MonkeyPatch) -> None:
    """The allowance gate is `billing/ai_quota`'s own suite; here it answers "open"."""

    async def _open(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(script_actions, "require_ai_assist", _open)


# --- the registry ----------------------------------------------------------------------


def test_it_is_a_confirm_action_on_the_script_pages_permission() -> None:
    tool = write_tools.tool_named(TOOL)
    assert tool is not None
    assert tool.tier == "confirm"
    assert tool.permission == "org:manage"
    names = [t.name for t in write_tools.WRITE_TOOLS]
    at = names.index("agent_script_suggest")
    assert write_tools.WRITE_TOOLS[at : at + 2] == script_actions.SCRIPT_ACTIONS


def test_the_answers_are_the_five_owner_questions() -> None:
    assert list(script_actions._Answers.model_fields) == list(OWNER_QUESTIONS)
    schema = script_actions.AGENT_SCRIPT_SUGGEST.schema["function"]["parameters"]
    answers = schema["properties"]["answers"]["anyOf"][0]
    assert answers["required"] == list(OWNER_QUESTIONS)


# --- the planner -----------------------------------------------------------------------


async def test_a_change_is_planned_with_canonical_arguments_and_its_cost() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _set_draft(tenant_id, agent_id, _stepped())
    proposal = await _propose(
        tenant_id,
        token,
        _args(agent_id, change="  Handle callers who say the price is too high  "),
    )
    assert proposal.tool == TOOL
    assert proposal.proposed == "Handle callers who say the price is too high"
    assert proposal.cost is not None and "AI help allowance" in proposal.cost
    assert "Nothing in the script changes" in proposal.reversal


async def test_whole_keeps_only_the_answers_given() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    answers = dict.fromkeys(OWNER_QUESTIONS) | {
        "what_you_offer": "Home-cooked tiffin delivered daily",
        "customers": "  ",
    }
    proposal = await _propose(
        tenant_id, token, _args(agent_id, mode="whole", change="ignored", answers=answers)
    )
    assert "Home-cooked tiffin delivered daily" in proposal.proposed
    assert OWNER_QUESTIONS["customers"] not in proposal.proposed


@pytest.mark.parametrize(
    ("mode", "change", "answers", "hand_written", "reason"),
    [
        ("change", "short", None, False, "too short"),
        ("whole", None, None, False, "six questions"),
        ("steps", None, None, False, "already in steps"),
        ("change", "Make the greeting warmer please", None, True, "written by hand"),
    ],
)
async def test_the_refusals_the_model_can_act_on(
    mode: str, change: str | None, answers: Any, hand_written: bool, reason: str
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    if hand_written:
        await _set_draft(tenant_id, agent_id, CallScript(raw_override="Greet them warmly."))
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(tenant_id, token, _args(agent_id, mode=mode, change=change, answers=answers))
    assert reason in refused.value.reason


async def test_a_role_without_the_script_permission_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant(role="staff")
    agent_id = await _agent_of(tenant_id)
    with pytest.raises(WriteRefusedError):
        await _propose(tenant_id, token, _args(agent_id), role="staff")


async def test_a_neighbours_agent_is_not_found() -> None:
    tenant_id, _slug, token = await _make_tenant()
    neighbour, _, _ = await _make_tenant()
    with pytest.raises(ProblemError) as missing:
        await _propose(tenant_id, token, _args(await _agent_of(neighbour)))
    assert missing.value.status == 404


async def test_the_allowance_refusal_reaches_the_person_before_the_card(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _used_up(*_: Any, **__: Any) -> None:
        raise ProblemError.business_rule("ai_quota_exceeded", "This month's AI help is used up.")

    monkeypatch.setattr(script_actions, "require_ai_assist", _used_up)
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(ProblemError) as refused:
        await _propose(tenant_id, token, _args(await _agent_of(tenant_id)))
    assert refused.value.code == "ai_quota_exceeded"


# --- a whole script rests on the owner's own answers (D-833) ----------------------------

#: The production eval's case `c-script-whole-asks-first`: nothing answered yet.
ASKED_ONLY = ("Draft the whole script for this agent",)
ANSWERED = (
    "Draft the whole script for this agent. Ask me the six questions first.",
    "Organic groceries. Home cooks call to order. Never promise same-day delivery.",
)


async def _propose_in_conversation(
    tenant_id: UUID, token: str, args: dict[str, Any], said: tuple[str, ...]
) -> CopilotProposalEvent:
    return await write_tools.plan_write(
        TOOL,
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token))),
        said=said,
    )


@pytest.mark.parametrize(
    ("answers", "reason"),
    [
        (None, "six questions first"),
        ({"what_you_offer": "Organic groceries", "customers": "Home cooks"}, "`what_you_offer`"),
    ],
    ids=["no-answers", "invented-answers"],
)
async def test_a_whole_script_before_the_owner_answered_is_refused(
    answers: dict[str, str] | None, reason: str
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    with pytest.raises(WriteRefusedError) as refused:
        await _propose_in_conversation(
            tenant_id, token, _args(agent_id, mode="whole", answers=answers), ASKED_ONLY
        )
    assert reason in refused.value.reason


async def test_a_whole_script_from_answers_the_owner_typed_is_proposed() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    answers = dict.fromkeys(OWNER_QUESTIONS) | {
        "what_you_offer": "Organic groceries.",
        "customers": "home cooks call to order",
        "never_say": "Never promise same-day delivery",
    }
    proposal = await _propose_in_conversation(
        tenant_id, token, _args(agent_id, mode="whole", answers=answers), ANSWERED
    )
    assert "Organic groceries" in proposal.proposed


async def test_a_change_is_not_held_to_the_owners_exact_words() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _set_draft(tenant_id, agent_id, _stepped())
    proposal = await _propose_in_conversation(
        tenant_id, token, _args(agent_id, change="Make the greeting friendlier"), ("be nicer",)
    )
    assert proposal.proposed == "Make the greeting friendlier"


# --- confirm, the job, the Script page --------------------------------------------------


async def _requested(tenant_id: UUID, token: str, args: dict[str, Any]) -> UUID:
    proposal = await _propose(tenant_id, token, args)
    outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert outcome.applied
    async with tenant_session(tenant_id) as session:
        pending = await script_proposals.read_proposal(session, UUID(args["agent_id"]))
    assert pending is not None
    return pending.id


def _drafting_with(
    monkeypatch: pytest.MonkeyPatch, result: CallScript | ProblemError
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def _draft(brief: Any, **kwargs: Any) -> ScriptDraft:
        calls.append({"brief": brief, **kwargs})
        if isinstance(result, ProblemError):
            raise result
        return ScriptDraft(script=result, capability=AssistCapability(available=True))

    monkeypatch.setattr(worker, "draft_script", _draft)
    return calls


def _metering(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    features: list[str] = []

    async def _meter(*_: Any, feature: str, **__: Any) -> Any:
        features.append(feature)
        return type("Metered", (), {"metered": False})()

    async def _earlier(*_: Any, feature: str, **__: Any) -> bool:
        return False

    monkeypatch.setattr(crm_assist, "meter_assist", _meter)
    monkeypatch.setattr(crm_assist, "meter_earlier", _earlier)
    return features


def _payload(tenant_id: UUID, agent_id: UUID, proposal_id: UUID) -> dict[str, str]:
    return {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal_id),
    }


async def test_confirm_records_the_request_queues_the_writer_and_audits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _set_draft(tenant_id, agent_id, _stepped())
    proposal_id = await _requested(tenant_id, token, _args(agent_id))

    assert script_proposals.PROPOSAL_JOB in await _outbox_jobs(tenant_id)
    assert ("agent.script_assist", "agent", str(agent_id)) in await _audit(tenant_id)
    async with _client() as client:
        shown = (
            await client.get(
                f"/v1/agents/{agent_id}/script/proposal", headers=_headers(token, slug)
            )
        ).json()["proposal"]
    assert shown["id"] == str(proposal_id)
    assert shown["status"] == "drafting"
    assert shown["request"] == "Make the opening line warmer and shorter"
    assert shown["base_script"]["opening_line"] == "Namaste, Sunrise here."

    # A second request while this one is written is refused, so two cannot race.
    with pytest.raises(WriteRefusedError):
        await _propose(tenant_id, token, _args(agent_id))


async def test_the_job_writes_meters_and_stores_the_proposal_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _set_draft(tenant_id, agent_id, _stepped())
    proposal_id = await _requested(tenant_id, token, _args(agent_id))
    calls = _drafting_with(monkeypatch, _stepped("Namaste! Sunrise here, how can I help?"))
    features = _metering(monkeypatch)

    payload = _payload(tenant_id, agent_id, proposal_id)
    assert await worker.draft_script_proposal({}, payload) == "ready"
    assert await worker.draft_script_proposal({}, payload) == "not_pending"

    assert len(calls) == 1
    assert calls[0]["change"] == "Make the opening line warmer and shorter"
    assert calls[0]["edit_of"].opening_line == "Namaste, Sunrise here."
    assert features == ["script_draft"]
    async with _client() as client:
        shown = (
            await client.get(
                f"/v1/agents/{agent_id}/script/proposal", headers=_headers(token, slug)
            )
        ).json()["proposal"]
        assert shown["status"] == "ready"
        assert shown["script"]["opening_line"] == "Namaste! Sunrise here, how can I help?"
        cleared = await client.delete(
            f"/v1/agents/{agent_id}/script/proposal/{proposal_id}", headers=_headers(token, slug)
        )
        assert cleared.status_code == 204
        after = await client.get(
            f"/v1/agents/{agent_id}/script/proposal", headers=_headers(token, slug)
        )
    assert after.json() == {"proposal": None}
    # The draft itself was never touched.
    async with tenant_session(tenant_id) as session:
        draft = await script_builder.read_draft(session, agent_id)
    assert draft is not None and draft.script.opening_line == "Namaste, Sunrise here."


async def test_a_discarded_request_is_not_resurrected_by_its_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    proposal_id = await _requested(
        tenant_id,
        token,
        _args(agent_id, mode="whole", answers={"what_you_offer": "Tiffins every day"}),
    )
    async with tenant_session(tenant_id) as session:
        assert await script_proposals.discard(session, agent_id=agent_id, proposal_id=proposal_id)
    _drafting_with(monkeypatch, _stepped())
    assert (
        await worker.draft_script_proposal({}, _payload(tenant_id, agent_id, proposal_id))
        == "not_pending"
    )


async def test_a_refusal_is_stored_in_the_owners_words_and_its_spend_metered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    proposal_id = await _requested(
        tenant_id, token, _args(agent_id, mode="whole", answers={"what_you_offer": "Tiffins daily"})
    )
    refusal = ProblemError.business_rule(
        "assist_answer_unusable",
        "The AI answered in a form we could not use.",
        remediation="Ask again.",
    )
    calls = _drafting_with(monkeypatch, refusal)
    refused: list[str] = []

    async def _meter_refusal(*_: Any, feature: str, **__: Any) -> None:
        refused.append(feature)

    monkeypatch.setattr(crm_assist, "meter_refusal", _meter_refusal)
    assert (
        await worker.draft_script_proposal({}, _payload(tenant_id, agent_id, proposal_id))
        == "refused"
    )
    assert calls[0]["brief"].answers == (("what_you_offer", "Tiffins daily"),)
    assert refused == ["script_draft"]
    async with tenant_session(tenant_id) as session:
        failed = await script_proposals.read_proposal(session, agent_id)
    assert failed is not None and failed.status == "failed"
    assert failed.note == "The AI answered in a form we could not use. Ask again."


async def test_steps_converts_the_hand_written_script_and_lists_what_did_not_fit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    raw = "Greet the caller warmly.\nNever promise a delivery time over the phone."
    await _set_draft(tenant_id, agent_id, CallScript(raw_override=raw))
    proposal_id = await _requested(
        tenant_id, token, _args(agent_id, mode="steps", change=None, answers=None)
    )
    calls = _drafting_with(
        monkeypatch,
        CallScript(
            schema_version=2,
            stages=[
                ConversationStage(id="greet", name="Greet", instruction="Greet the caller warmly.")
            ],
        ),
    )
    _metering(monkeypatch)
    await worker.draft_script_proposal({}, _payload(tenant_id, agent_id, proposal_id))
    assert calls[0]["instruction"] == CONVERT_INSTRUCTION
    assert raw in calls[0]["brief"].description
    async with tenant_session(tenant_id) as session:
        ready = await script_proposals.read_proposal(session, agent_id)
    assert ready is not None and ready.status == "ready"
    assert ready.unplaced == ["Never promise a delivery time over the phone."]


async def test_a_request_the_job_never_finished_reads_as_failed() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _requested(
        tenant_id,
        token,
        _args(agent_id, mode="whole", answers={"customers": "Families in the colony"}),
    )
    long_ago = datetime.now(UTC) - script_proposals.DRAFTING_STALE_AFTER - timedelta(minutes=1)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET script_proposal = jsonb_set(script_proposal, "
                "'{requested_at}', to_jsonb(CAST(:at AS text))) WHERE id = :aid"
            ),
            {"aid": agent_id, "at": long_ago.isoformat()},
        )
        stale = await script_proposals.read_proposal(session, agent_id)
    assert stale is not None and stale.status == "failed"
    assert stale.note == script_proposals.STALE_NOTE


async def test_a_neighbour_cannot_read_or_clear_the_proposal() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    proposal_id = await _requested(
        tenant_id, token, _args(agent_id, mode="whole", answers={"customers": "Families nearby"})
    )
    _other, other_slug, other_token = await _make_tenant()
    async with _client() as client:
        read = await client.get(
            f"/v1/agents/{agent_id}/script/proposal", headers=_headers(other_token, other_slug)
        )
        cleared = await client.delete(
            f"/v1/agents/{agent_id}/script/proposal/{proposal_id}",
            headers=_headers(other_token, other_slug),
        )
    assert read.status_code == 404
    assert cleared.status_code == 404
    async with tenant_session(tenant_id) as session:
        assert await script_proposals.read_proposal(session, agent_id) is not None


async def test_an_unknown_proposal_id_clears_nothing() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _requested(
        tenant_id,
        token,
        _args(agent_id, mode="whole", answers={"customers": "Families in the colony"}),
    )
    async with tenant_session(tenant_id) as session:
        assert not await script_proposals.discard(
            session, agent_id=agent_id, proposal_id=uuid.uuid4()
        )
        assert await script_proposals.read_proposal(session, agent_id) is not None


# --- agent_tests_fix: the Test section's "Improve my agent", asked of Pip ---------------


async def _failed_run(tenant_id: UUID, agent_id: UUID, *, verdicts: tuple[str, ...]) -> UUID:
    run_id = uuid.uuid4()
    results = [
        {"key": f"k{i}", "title": f"Test {i}", "verdict": verdict, "reason": "x"}
        for i, verdict in enumerate(verdicts, start=1)
    ]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_test_runs (id, tenant_id, agent_id, status, results, "
                "created_at, updated_at) VALUES (:id, :t, :a, 'done', CAST(:r AS jsonb), "
                "now(), now())"
            ),
            {"id": run_id, "t": tenant_id, "a": agent_id, "r": json.dumps(results)},
        )
    return run_id


async def _propose_fix(tenant_id: UUID, token: str, args: dict[str, Any]) -> CopilotProposalEvent:
    return await write_tools.plan_write(
        "agent_tests_fix",
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token))),
    )


async def test_fixes_are_planned_for_the_named_failures_of_the_latest_run() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    await _failed_run(tenant_id, agent_id, verdicts=("failed", "needs_fix", "passed"))
    proposal = await _propose_fix(
        tenant_id, token, {"agent_id": str(agent_id), "test_keys": ["k2"]}
    )
    assert proposal.tool == "agent_tests_fix"
    assert proposal.proposed == "Test 2"
    assert proposal.cost is not None and "AI help allowance" in proposal.cost


@pytest.mark.parametrize(
    ("verdicts", "keys", "reason"),
    [
        ((), None, "no finished test run"),
        (("passed",), None, "nothing to fix"),
        (("failed",), ["k9"], "not a failed test"),
        (("failed", "passed"), ["k2"], "not a failed test"),
    ],
)
async def test_the_fix_refusals_the_model_can_act_on(
    verdicts: tuple[str, ...], keys: list[str] | None, reason: str
) -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    if verdicts:
        await _failed_run(tenant_id, agent_id, verdicts=verdicts)
    with pytest.raises(WriteRefusedError) as refused:
        await _propose_fix(tenant_id, token, {"agent_id": str(agent_id), "test_keys": keys})
    assert reason in refused.value.reason


async def test_confirming_fixes_queues_the_improver_once_and_audits() -> None:
    tenant_id, _slug, token = await _make_tenant()
    agent_id = await _agent_of(tenant_id)
    run_id = await _failed_run(tenant_id, agent_id, verdicts=("failed",))
    proposal = await _propose_fix(tenant_id, token, {"agent_id": str(agent_id), "test_keys": None})
    outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert outcome.applied
    assert (await _outbox_jobs(tenant_id)).count(test_conversations.IMPROVE_JOB) == 1
    assert ("agent.tests_improvement", "agent", str(agent_id)) in await _audit(tenant_id)
    async with tenant_session(tenant_id) as session:
        assert (await test_conversations.get_run(session, agent_id, run_id)).improving
    with pytest.raises(WriteRefusedError) as again:
        await _propose_fix(tenant_id, token, {"agent_id": str(agent_id), "test_keys": None})
    assert "already being worked out" in again.value.reason


async def test_fixes_for_a_neighbours_agent_are_not_found() -> None:
    tenant_id, _slug, token = await _make_tenant()
    neighbour, _, _ = await _make_tenant()
    neighbour_agent = await _agent_of(neighbour)
    await _failed_run(neighbour, neighbour_agent, verdicts=("failed",))
    with pytest.raises(ProblemError) as missing:
        await _propose_fix(tenant_id, token, {"agent_id": str(neighbour_agent), "test_keys": None})
    assert missing.value.status == 404
