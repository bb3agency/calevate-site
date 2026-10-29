"""D-937: how each Pip answer went, and the asker's thumbs on it.

The capture keeps names, ids and timings from the stream; the row lands under the answer's
turn id; the vote round-trips, is changeable, belongs to the asker only, and stays inside
its tenant.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.api_security_test import _make_tenant

from apps.api.copilot import quality
from apps.api.copilot.schemas import (
    CopilotStepEvent,
    CopilotVoteIn,
)
from apps.api.copilot.service import CopilotEvent, CopilotSpend
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers.extraction import AssistCapability


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if slug is not None:
        headers["X-Org-Slug"] = slug
    return headers


def _user_of(token: str) -> UUID:
    return UUID(token.rsplit(":", 1)[1])


def _step(tool: str, status: str) -> CopilotEvent:
    return CopilotEvent(
        step=CopilotStepEvent(id=f"c-{tool}", tool=tool, status=status, args="")  # type: ignore[arg-type]
    )


def _spend(provider: str, fallback: str | None = None) -> CopilotEvent:
    return CopilotEvent(
        spend=CopilotSpend(
            usage=None,
            capability=AssistCapability(
                available=True, provider=provider, fallback_reason=fallback
            ),
        )
    )


def _action_event(action_id: UUID) -> CopilotEvent:
    return CopilotEvent(
        action=cast(Any, SimpleNamespace(tool="lead_set_status", action_id=str(action_id)))
    )


def _proposal_event(tool: str) -> CopilotEvent:
    return CopilotEvent(proposal=cast(Any, SimpleNamespace(tool=tool)))


def test_the_capture_keeps_tool_outcomes_ids_and_timings_and_never_text() -> None:
    capture = quality.AnswerCapture()
    action_id = uuid.uuid4()
    capture.observe(_step("calls_recent", "running"))
    capture.observe(_step("calls_recent", "done"))
    capture.observe(_step("lead_set_status", "failed"))
    capture.observe(_step("member_invite", "refused"))
    capture.observe(CopilotEvent(text="Here is "))
    capture.observe(CopilotEvent(text="what I found."))
    capture.observe(_action_event(action_id))
    capture.observe(_proposal_event("campaign_pause"))
    capture.observe(_spend("google"))
    capture.observe(_spend("sarvam", fallback="provider_unavailable"))
    capture.finish()

    assert capture.tools == ["calls_recent", "lead_set_status", "member_invite"]
    assert capture.failed_tools == ["lead_set_status"]
    assert capture.refused_tools == ["member_invite"]
    assert capture.action_ids == [action_id]
    assert capture.proposed_tool == "campaign_pause"
    assert capture.first_token_ms is not None and capture.total_ms is not None
    assert capture.first_token_ms <= capture.total_ms
    assert capture.provider == "sarvam"
    assert capture.fell_back is True
    # Nothing of what was said is on the capture.
    assert "found" not in repr(capture)


def test_one_leg_with_no_fallback_is_not_a_fallback() -> None:
    capture = quality.AnswerCapture()
    capture.observe(_spend("google"))
    assert capture.fell_back is False


def test_a_reason_goes_with_a_thumbs_down_and_a_note_with_other() -> None:
    CopilotVoteIn(vote="down", reason="other", note="it missed my calendar")
    CopilotVoteIn(vote=None)
    with pytest.raises(ValidationError):
        CopilotVoteIn(vote="up", reason="wrong")
    with pytest.raises(ValidationError):
        CopilotVoteIn(vote="down", reason="too_slow", note="slow")
    with pytest.raises(ValidationError):
        CopilotVoteIn(vote="down", reason="other", note="x" * 121)


async def _answer(tenant_id: UUID, user_id: UUID, **capture: Any) -> UUID:
    turn_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await quality.record_answer(
            session,
            realm="client",
            turn_id=turn_id,
            owner_id=user_id,
            tenant_id=tenant_id,
            capture=quality.AnswerCapture(**capture),
            completed=True,
        )
    return turn_id


async def test_a_vote_round_trips_changes_and_is_taken_back() -> None:
    tenant_id, slug, token = await _make_tenant()
    user_id = _user_of(token)
    turn_id = await _answer(tenant_id, user_id, tools=["calls_recent"])
    path = f"/v1/copilot/turns/{turn_id}/vote"
    async with _client() as client:
        up = await client.put(path, json={"vote": "up"}, headers=_headers(token, slug))
        assert up.status_code == 200, up.text
        assert up.json() == {"turn_id": str(turn_id), "vote": "up", "vote_reason": None}

        down = await client.put(
            path,
            json={"vote": "down", "reason": "other", "note": "call me on 9876543210"},
            headers=_headers(token, slug),
        )
        assert down.json()["vote"] == "down" and down.json()["vote_reason"] == "other"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT vote, vote_reason, vote_note, voted_at FROM copilot_answer_outcomes "
                    "WHERE turn_id = :t"
                ),
                {"t": turn_id},
            )
        ).one()
        votes = await quality.votes_for(
            session, realm="client", owner_id=user_id, turn_ids=[turn_id]
        )
    assert row[0] == "down" and row[1] == "other" and row[3] is not None
    # The note is redacted on write: the digits never reach the column.
    assert row[2] and "9876543210" not in row[2]
    assert votes[turn_id].vote == "down"

    async with _client() as client:
        cleared = await client.put(path, json={"vote": None}, headers=_headers(token, slug))
    assert cleared.json()["vote"] is None
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT vote, vote_reason, vote_note, voted_at FROM copilot_answer_outcomes "
                    "WHERE turn_id = :t"
                ),
                {"t": turn_id},
            )
        ).one()
    assert tuple(row) == (None, None, None, None)


async def test_only_the_asker_can_rate_and_a_refused_question_cannot_be_rated() -> None:
    tenant_id, slug, token = await _make_tenant()
    other_tenant, other_slug, other_token = await _make_tenant()
    turn_id = await _answer(tenant_id, _user_of(token))
    refused = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await quality.record_refusal(
            session,
            realm="client",
            turn_id=refused,
            owner_id=_user_of(token),
            tenant_id=tenant_id,
            refusal="fair_use",
        )
    async with _client() as client:
        stranger = await client.put(
            f"/v1/copilot/turns/{turn_id}/vote",
            json={"vote": "down"},
            headers=_headers(other_token, other_slug),
        )
        not_answered = await client.put(
            f"/v1/copilot/turns/{refused}/vote", json={"vote": "up"}, headers=_headers(token, slug)
        )
    assert stranger.status_code == 404
    assert stranger.json()["type"].endswith("/copilot_answer_not_found")
    assert not_answered.status_code == 404
    del other_tenant


async def test_outcome_rows_stay_inside_their_tenant() -> None:
    """Hard rule 1: another tenant's session reads zero rows."""
    tenant_id, _slug, token = await _make_tenant()
    other_tenant, _other_slug, _other_token = await _make_tenant()
    turn_id = await _answer(tenant_id, _user_of(token))
    async with tenant_session(other_tenant) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM copilot_answer_outcomes WHERE turn_id = :t"),
                {"t": turn_id},
            )
        ).scalar()
    async with tenant_session(tenant_id) as session:
        own = (
            await session.execute(
                text("SELECT count(*) FROM copilot_answer_outcomes WHERE turn_id = :t"),
                {"t": turn_id},
            )
        ).scalar()
    assert seen == 0
    assert own == 1


async def test_a_repeat_record_for_the_same_turn_writes_nothing() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    turn_id = await _answer(tenant_id, user_id, tools=["calls_recent"])
    async with tenant_session(tenant_id) as session:
        await quality.record_answer(
            session,
            realm="client",
            turn_id=turn_id,
            owner_id=user_id,
            tenant_id=tenant_id,
            capture=quality.AnswerCapture(tools=["leads_find"]),
            completed=False,
        )
        rows = (
            await session.execute(
                text("SELECT tools FROM copilot_answer_outcomes WHERE turn_id = :t"),
                {"t": turn_id},
            )
        ).all()
    assert [list(r[0]) for r in rows] == [["calls_recent"]]


async def test_an_operator_rates_their_own_admin_answer_and_it_is_audited() -> None:
    token = await _make_admin(role="operator")
    operator = _user_of(token)
    turn_id = uuid.uuid4()
    async with untenanted_session() as session:
        await quality.record_answer(
            session,
            realm="admin",
            turn_id=turn_id,
            owner_id=operator,
            tenant_id=None,
            capture=quality.AnswerCapture(tools=["platform_health"]),
            completed=True,
        )
    other = await _make_admin(role="operator")
    async with _client() as client:
        own = await client.put(
            f"/v1/admin/copilot/turns/{turn_id}/vote",
            json={"vote": "down", "reason": "wrong"},
            headers=_headers(token),
        )
        theirs = await client.put(
            f"/v1/admin/copilot/turns/{turn_id}/vote",
            json={"vote": "up"},
            headers=_headers(other),
        )
    assert own.status_code == 200, own.text
    assert own.json()["vote_reason"] == "wrong"
    assert theirs.status_code == 404
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'admin_copilot.answer_rated' "
                    "AND object_id = :t"
                ),
                {"t": str(turn_id)},
            )
        ).scalar()
    assert audited == 1


def test_only_the_gate_refusals_pip_owns_are_scored() -> None:
    from apps.api.core.errors import ProblemError

    def problem(code: str) -> ProblemError:
        return ProblemError(kind="business_rule", code=code, title="t", detail="d")

    assert quality.gate_refusal_of(problem("copilot_daily_limit_reached")) == "fair_use"
    assert quality.gate_refusal_of(problem("copilot_consent_required")) == "consent"
    assert quality.gate_refusal_of(problem("admin_ai_paused_platform_wide")) == "paused"
    assert quality.gate_refusal_of(problem("copilot_screen_too_large")) is None
