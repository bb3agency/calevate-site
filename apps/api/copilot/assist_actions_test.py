"""D-821: the teach box, the lead-details draft and a call's second reading, asked of Pip.

Held to `docs/COPILOT-CONTRACT.md` §5: the planner's canonical arguments and refusals, the
confirm through the old button's own service function with its audit row, and where the
result lands for review. The second reading's model path is `tests/call_assist_test.py`.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.agents import lead_fields
from apps.api.copilot import assist_actions, write_tools
from apps.api.copilot.actions import WriteRefusedError
from apps.api.copilot.schemas import CopilotProposalEvent
from apps.api.copilot.write_tools_test import _audit, _confirm, _outbox_jobs, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.api.teach import teaching


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _propose(
    tenant_id: UUID, token: str, name: str, args: dict[str, Any], *, role: str = "owner"
) -> CopilotProposalEvent:
    return await write_tools.plan_write(
        name,
        json.dumps(args),
        actor=write_tools.actor_for(_principal(tenant_id, _user_of(token), role=role)),
    )


def test_all_three_are_confirm_actions_on_their_buttons_permissions() -> None:
    expected = {
        "knowledge_teach": "kb:write",
        "lead_fields_draft": "org:manage",
        "call_summarise_again": "org:manage",
    }
    for name, permission in expected.items():
        tool = write_tools.tool_named(name)
        assert tool is not None, name
        assert tool.tier == "confirm" and tool.permission == permission, name
    assert [t.name for t in assist_actions.ASSIST_ACTIONS] == list(expected)
    assert write_tools.WRITE_TOOLS[-3:] == assist_actions.ASSIST_ACTIONS


# --- knowledge_teach ----------------------------------------------------------------------


async def test_teaching_is_planned_with_the_words_shown_for_checking() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(
        tenant_id,
        token,
        "knowledge_teach",
        {"words": "  Red chilli powder is 120 rupees for 250 g.  ", "gap_id": None},
    )
    assert proposal.proposed == "Red chilli powder is 120 rupees for 250 g."
    assert proposal.cost is not None and "AI help allowance" in proposal.cost


@pytest.mark.parametrize(
    ("args", "reason"),
    [
        ({"words": "  ", "gap_id": None}, "empty"),
        ({"words": "We open at ten.", "gap_id": str(uuid.uuid4())}, "not a caller question"),
    ],
)
async def test_the_teach_refusals_the_model_can_act_on(args: dict[str, Any], reason: str) -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(tenant_id, token, "knowledge_teach", args)
    assert reason in refused.value.reason


async def test_staff_may_teach_only_when_the_owner_lets_them() -> None:
    tenant_id, _slug, token = await _make_tenant(role="staff")
    with pytest.raises(WriteRefusedError):
        await _propose(
            tenant_id,
            token,
            "knowledge_teach",
            {"words": "We open at ten.", "gap_id": None},
            role="staff",
        )


async def test_confirming_starts_the_sort_and_it_waits_in_the_teach_box() -> None:
    tenant_id, slug, token = await _make_tenant()
    words = "Red chilli powder is 120 rupees for 250 g. Never promise same-day delivery."
    proposal = await _propose(tenant_id, token, "knowledge_teach", {"words": words, "gap_id": None})
    outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert outcome.applied and "teach box" in outcome.detail
    assert teaching.TEACH_JOB in await _outbox_jobs(tenant_id)
    assert any(action == "kb_teaching.start" for action, _, _ in await _audit(tenant_id))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        mine = (await http.get("/v1/kb/teach/open", headers=_headers(token, slug))).json()
        other_tenant, other_slug, other_token = await _make_tenant()
        theirs = (
            await http.get("/v1/kb/teach/open", headers=_headers(other_token, other_slug))
        ).json()
    assert mine["teaching"]["status"] == "queued"
    assert mine["teaching"]["words"] == words
    assert theirs == {"teaching": None}
    async with tenant_session(other_tenant) as session:
        assert await teaching.open_teaching(session, requested_by=_user_of(token)) is None


# --- lead_fields_draft --------------------------------------------------------------------


async def test_the_draft_is_planned_at_no_cost_to_the_allowance() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(tenant_id, token, "lead_fields_draft", {})
    assert proposal.cost is None
    assert "drafted once" in proposal.reversal


async def test_confirming_queues_the_one_draft_and_a_second_ask_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    proposal = await _propose(tenant_id, token, "lead_fields_draft", {})
    await _confirm(tenant_id, _user_of(token), proposal.token)
    assert lead_fields.DRAFT_JOB in await _outbox_jobs(tenant_id)
    assert any(action == "lead_fields.draft_requested" for action, _, _ in await _audit(tenant_id))
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(tenant_id, token, "lead_fields_draft", {})
    assert "already being drafted" in refused.value.reason


async def test_a_business_with_standard_details_is_not_drafted() -> None:
    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET vertical_template = 'retail' WHERE id = :t"),
            {"t": tenant_id},
        )
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(tenant_id, token, "lead_fields_draft", {})
    assert "standard lead details" in refused.value.reason


async def test_a_reviewed_draft_is_never_asked_for_again() -> None:
    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO lead_field_drafts (id, tenant_id, status, fields, requested_at, "
                "completed_at, reviewed_at, created_at, updated_at) VALUES (:id, :t, 'done', "
                "'[]'::jsonb, now(), now(), now(), now(), now())"
            ),
            {"id": uuid.uuid4(), "t": tenant_id},
        )
    with pytest.raises(WriteRefusedError) as refused:
        await _propose(tenant_id, token, "lead_fields_draft", {})
    assert "never drafted again" in refused.value.reason


# --- call_summarise_again -----------------------------------------------------------------


async def test_a_second_reading_of_a_missing_call_is_refused_before_any_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(ProblemError) as missing:
        await _propose(tenant_id, token, "call_summarise_again", {"call_id": str(uuid.uuid4())})
    assert missing.value.status == 404


async def test_a_second_reading_is_never_left_for_a_background_task() -> None:
    """A paid model call cannot ride an approval decided in the same transaction as it
    (`write_tools.stage_for_approval`): it is asked in conversation, where the card's
    token keeps it from being paid twice."""
    tenant_id, _slug, token = await _make_tenant()
    with pytest.raises(WriteRefusedError) as refused:
        await write_tools.stage_for_approval(
            "call_summarise_again",
            json.dumps({"call_id": str(uuid.uuid4())}),
            principal=_principal(tenant_id, _user_of(token)),
            job_id=uuid.uuid4(),
        )
    assert "asked in conversation" in refused.value.reason


async def test_the_activity_log_keeps_a_sentence_not_the_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The summary is derived from a caller's words and is shown once (`Executed.recorded`)."""
    from apps.api.crm import resummarise

    tenant_id, _slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        call_id = (await session.execute(text("SELECT gen_random_uuid()"))).scalar_one()
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', "
                "'completed', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"sr_{uuid.uuid4().hex[:10]}"},
        )

    async def readable(*_: Any, **__: Any) -> None:
        return None

    async def reading(*_: Any, **__: Any) -> resummarise.SecondReading:
        return resummarise.SecondReading(
            summary="Ravi wants a Tuesday slot.",
            disclosure=None,
            metered=True,
            provider="azure",
            fallback_reason=None,
            ref="assist:x",
        )

    async def open_allowance(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(resummarise, "check_readable", readable)
    monkeypatch.setattr(resummarise, "second_reading", reading)
    monkeypatch.setattr(assist_actions, "require_ai_assist", open_allowance)
    proposal = await _propose(tenant_id, token, "call_summarise_again", {"call_id": str(call_id)})
    outcome = await _confirm(tenant_id, _user_of(token), proposal.token)
    assert "Ravi wants a Tuesday slot." in outcome.detail
    async with tenant_session(tenant_id) as session:
        logged = (
            await session.execute(
                text("SELECT summary FROM copilot_actions WHERE tool = 'call_summarise_again'")
            )
        ).scalar_one()
    assert logged == "Summarised a call again."
