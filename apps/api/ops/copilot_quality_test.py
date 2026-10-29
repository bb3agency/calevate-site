"""D-937: Pip's live success scores, computed from seeded answer and action-log rows, read
across tenants through `copilot_quality_scan`, and the alarm on a low area."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin
from tests.api_security_test import _make_tenant

from apps.api.copilot import quality
from apps.api.db.session import admin_session, tenant_session
from apps.api.main import app
from apps.api.ops import copilot_quality as scores
from apps.api.ops.copilot_quality import ActionRow, AnswerRow, build_report
from apps.workers import copilot_quality as alarm_job

NOW = datetime(2026, 10, 29, 10, 0, tzinfo=UTC)


def _a(**fields: Any) -> AnswerRow:
    fields.setdefault("turn_id", uuid.uuid4())
    fields.setdefault("tenant_id", None)
    fields.setdefault("created_at", NOW)
    return AnswerRow(**fields)


def test_answers_are_scored_per_area_and_per_tool() -> None:
    answers = [
        # calls: a read, opened a screen, thumbs up.
        _a(tools=("calls_recent",), navigated=True, vote="up", first_token_ms=400, total_ms=900),
        # leads: an immediate action kept.
        _a(tools=("lead_set_status",), acted=True, kept=True, first_token_ms=600, total_ms=2000),
        # leads: the action failed, thumbs down "not_done".
        _a(
            tools=("lead_set_status",),
            failed_tools=("lead_set_status",),
            vote="down",
            vote_reason="not_done",
            first_token_ms=800,
            total_ms=3000,
        ),
        # campaigns: a confirm card proposed.
        _a(proposed_tool="campaign_pause", fell_back=True, provider="sarvam"),
        # no tool at all, an unfinished answer.
        _a(completed=False, provider="google"),
        # a permission refusal on a read.
        _a(tools=("team_members",), refused_tools=("team_members",)),
        # Gate refusals: counted as questions, never as answers.
        _a(refusal="fair_use"),
        _a(refusal="consent"),
    ]
    actions = [
        ActionRow(tool="lead_set_status", tier="immediate", status="done", source="interactive"),
        ActionRow(tool="lead_set_status", tier="immediate", status="undone", source="interactive"),
        ActionRow(tool="campaign_pause", tier="confirm", status="done", source="interactive"),
    ]
    report = build_report(answers, actions, realm="client", days=7)

    assert report.questions == 8
    assert {(r.reason, r.count) for r in report.refusals} == {("consent", 1), ("fair_use", 1)}
    overall = report.overall
    assert overall.answers == 6
    # Done: the screen opened (and the thumbs up) and the kept action.
    assert overall.done == 2
    assert overall.done_share == round(2 / 6, 3)
    assert (overall.thumbs_up, overall.thumbs_down, overall.thumbs_down_share) == (1, 1, 0.5)
    assert [(r.reason, r.count) for r in overall.reasons] == [("not_done", 1)]
    assert overall.permission_refusals == 1
    assert overall.fell_back == 1
    assert (overall.actions_done, overall.actions_undone, overall.actions_failed) == (2, 1, 1)
    assert overall.action_failure_share == 0.25
    assert (overall.proposals, overall.proposals_accepted, overall.proposals_abandoned) == (1, 1, 0)
    assert overall.first_token_typical_ms == 600
    # Fewer than P90_MIN timed answers: no slow figure.
    assert overall.first_token_slow_ms is None
    assert overall.total_typical_ms == 2000

    areas = {row.area: row.figures for row in report.by_area}
    assert set(areas) == {"calls", "leads", "campaigns", "team", scores.NO_TOOL}
    assert areas["leads"].answers == 2
    assert areas["leads"].thumbs_down == 1
    assert areas["leads"].actions_failed == 1
    assert areas["calls"].done == 1
    assert areas["campaigns"].proposals_accepted == 1

    tools = {row.tool: row for row in report.by_tool}
    assert tools["lead_set_status"].is_action is True
    assert tools["lead_set_status"].figures.tool_failures == 1
    assert tools["calls_recent"].is_action is False
    assert tools["team_members"].figures.permission_refusals == 1
    assert {(p.provider, p.answers) for p in report.by_provider} == {("sarvam", 1), ("google", 1)}

    # Examples: ids only, thumbs down first.
    examples = overall.examples
    assert examples[0].why == "thumbs_down"
    assert [e.why for e in examples] == ["thumbs_down", "unfinished"]
    assert all(UUID(e.turn_id) for e in examples)


def test_an_area_is_low_only_with_enough_votes_or_attempts() -> None:
    downs = [_a(tools=("calls_recent",), vote="down", vote_reason="wrong") for _ in range(3)] + [
        _a(tools=("calls_recent",), vote="up") for _ in range(2)
    ]
    low = build_report(downs, [], realm="client", days=7)
    assert {r.area: r.figures.low for r in low.by_area}["calls"] == ["thumbs_down"]

    few = build_report(downs[:3], [], realm="client", days=7)
    assert {r.area: r.figures.low for r in few.by_area}["calls"] == []

    failing = [_a(tools=("lead_set_status",), failed_tools=("lead_set_status",)) for _ in range(2)]
    kept = [
        ActionRow(tool="lead_set_status", tier="immediate", status="done", source="interactive")
        for _ in range(3)
    ]
    report = build_report(failing, kept, realm="client", days=7)
    leads = {r.area: r.figures for r in report.by_area}["leads"]
    assert leads.action_failure_share == 0.4
    assert leads.low == ["action_failures"]


def test_the_p90_appears_once_enough_answers_are_timed() -> None:
    timed = [_a(first_token_ms=ms, total_ms=ms * 2) for ms in range(100, 1300, 100)]
    figures = build_report(timed, [], realm="client", days=7).overall
    assert figures.first_token_slow_ms == 1100
    assert figures.total_slow_ms == 2200


def test_admin_tools_score_under_platform() -> None:
    report = build_report([_a(tools=("platform_health",)), _a()], [], realm="admin", days=7)
    assert {r.area for r in report.by_area} == {scores.PLATFORM, scores.NO_TOOL}


async def test_the_scan_reads_every_client_and_the_route_serves_it() -> None:
    first, _s1, token1 = await _make_tenant()
    second, _s2, token2 = await _make_tenant()
    turns: list[UUID] = []
    for tenant_id, token, vote in ((first, token1, "up"), (second, token2, "down")):
        turn_id = uuid.uuid4()
        turns.append(turn_id)
        async with tenant_session(tenant_id) as session:
            await quality.record_answer(
                session,
                realm="client",
                turn_id=turn_id,
                owner_id=UUID(token.rsplit(":", 1)[1]),
                tenant_id=tenant_id,
                capture=quality.AnswerCapture(tools=["calls_recent"]),
                completed=True,
            )
            await session.execute(
                text(
                    "UPDATE copilot_answer_outcomes SET vote = :v, voted_at = now() "
                    "WHERE turn_id = :t"
                ),
                {"v": vote, "t": turn_id},
            )
            await session.execute(
                text(
                    "INSERT INTO copilot_actions (id, tenant_id, tool, tier, status, source, "
                    "object_type) VALUES (:id, :tid, 'lead_set_status', 'immediate', 'done', "
                    "'interactive', 'lead')"
                ),
                {"id": uuid.uuid4(), "tid": tenant_id},
            )
    async with admin_session() as session:
        window = await scores.read_window(
            session, realm="client", since=datetime.now(UTC) - timedelta(minutes=5)
        )
    seen = {a.turn_id: a for a in window.answers}
    assert set(turns) <= set(seen)
    assert seen[turns[0]].tenant_id == first and seen[turns[1]].tenant_id == second
    assert seen[turns[1]].vote == "down"
    assert sum(1 for r in window.actions if r.tool == "lead_set_status") >= 2

    admin = await _make_admin()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as client:
        response = await client.get(
            "/v1/ops/copilot-quality?days=7&realm=client",
            headers={"Authorization": f"Bearer {admin}"},
        )
        too_long = await client.get(
            "/v1/ops/copilot-quality?days=31", headers={"Authorization": f"Bearer {admin}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["realm"] == "client" and body["window_days"] == 7
    assert body["overall"]["answers"] >= 2
    assert too_long.status_code == 422


async def test_the_alarm_raises_one_episode_per_low_area(monkeypatch: pytest.MonkeyPatch) -> None:
    raised: list[tuple[str, str, str | None]] = []

    def fake_alert(stage: str, code: str, *, detail: str | None = None, **kw: Any) -> None:
        raised.append((code, kw.get("episode", ""), detail))

    low_calls = scores.Window(
        answers=tuple(
            [_a(tools=("calls_recent",), vote="down", vote_reason="wrong") for _ in range(4)]
            + [_a(tools=("calls_recent",), vote="up")]
            + [_a(tools=("leads_find",), vote="up") for _ in range(5)]
        ),
        actions=(),
        complete=True,
    )
    empty = scores.Window(answers=(), actions=(), complete=True)

    async def fake_read(_session: Any, *, realm: str, since: datetime) -> scores.Window:
        del since
        return low_calls if realm == "client" else empty

    monkeypatch.setattr(alarm_job, "read_window", fake_read)
    monkeypatch.setattr(alarm_job, "alert", fake_alert)
    result = await alarm_job.alarm_copilot_quality({})

    assert [(code, episode) for code, episode, _ in raised] == [
        ("copilot_quality_low", "client:calls")
    ]
    detail = raised[0][2] or ""
    assert "4 of 5 thumbs were down" in detail
    assert result.startswith("areas_low=1")


async def test_the_alarm_prunes_old_admin_rows_only() -> None:
    old, fresh = uuid.uuid4(), uuid.uuid4()
    async with admin_session() as session:
        for turn_id, age in ((old, 120), (fresh, 1)):
            await session.execute(
                text(
                    "INSERT INTO admin_copilot_answer_outcomes (id, turn_id, completed, "
                    "created_at, updated_at) VALUES (:id, :t, true, :at, :at)"
                ),
                {"id": uuid.uuid4(), "t": turn_id, "at": datetime.now(UTC) - timedelta(days=age)},
            )
    await alarm_job.alarm_copilot_quality({})
    async with admin_session() as session:
        left = {
            UUID(str(r[0]))
            for r in (
                await session.execute(
                    text(
                        "SELECT turn_id FROM admin_copilot_answer_outcomes "
                        "WHERE turn_id IN (:a, :b)"
                    ),
                    {"a": old, "b": fresh},
                )
            ).all()
        }
    assert left == {fresh}
