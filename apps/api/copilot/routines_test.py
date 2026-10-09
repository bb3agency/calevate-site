"""D-694 routines: the schedule, the slot that fires once, the skips, the routes, RLS.

A routine becomes an ordinary background job, so the gates a job meets are tested where the
job is (`jobs_test.py`: a confirm-tier step is staged, never run). What is tested here is
everything a routine adds: when a slot fires, that it fires once, why it is skipped, who can
see it, and the approval preview the inbox reads.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import jobs, routines, write_tools
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.workers.copilot_routines import fire_due_routines


def _user_of(token: str) -> UUID:
    return UUID(token.rsplit(":", 1)[1])


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


_BODY = {
    "name": "Morning call-backs",
    "instruction": "Call back yesterday's missed leads",
    "schedule": {"days": ["mon", "tue", "wed", "thu", "fri"], "time": "09:00"},
}


async def _create(
    token: str, slug: str, body: dict[str, object] | None = None
) -> dict[str, object]:
    async with _client() as http:
        response = await http.post(
            "/v1/copilot/routines", json=body or _BODY, headers=_headers(token, slug)
        )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _make_due(tenant_id: UUID, routine_id: str, slot: datetime) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE copilot_routines SET next_run_at = :slot WHERE id = :id"),
            {"slot": slot, "id": UUID(routine_id)},
        )


async def _runs(tenant_id: UUID, routine_id: str) -> list[tuple[str, str | None, UUID | None]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT status, reason, job_id FROM copilot_routine_runs "
                    "WHERE routine_id = :id ORDER BY created_at"
                ),
                {"id": UUID(routine_id)},
            )
        ).all()
    return [(str(row[0]), row[1], row[2]) for row in rows]


# --- the schedule ---------------------------------------------------------------------------


def _ist(year: int, month: int, day: int, hour: int, minute: int) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=routines.IST)


def test_the_next_run_is_the_next_chosen_day_at_the_chosen_time_in_ist() -> None:
    weekdays = routines.days_mask(["mon", "tue", "wed", "thu", "fri"])
    # Friday 9 Oct 2026, 08:00 IST → 09:00 the same morning.
    assert routines.next_occurrence(weekdays, 9 * 60, after=_ist(2026, 10, 9, 8, 0)) == _ist(
        2026, 10, 9, 9, 0
    ).astimezone(UTC)
    # 09:00 itself is not "after" 09:00, so the slot that just fired is never returned.
    assert routines.next_occurrence(weekdays, 9 * 60, after=_ist(2026, 10, 9, 9, 0)) == _ist(
        2026, 10, 12, 9, 0
    ).astimezone(UTC)
    # Friday evening skips the weekend to Monday.
    assert routines.next_occurrence(weekdays, 9 * 60, after=_ist(2026, 10, 9, 18, 0)) == _ist(
        2026, 10, 12, 9, 0
    ).astimezone(UTC)


def test_a_late_evening_ist_slot_lands_on_the_right_utc_day() -> None:
    every_day = routines.days_mask(routines.WEEKDAYS)
    # 23:30 IST on Friday is 18:00 UTC on Friday, not Saturday.
    due = routines.next_occurrence(every_day, 23 * 60 + 30, after=_ist(2026, 10, 9, 23, 0))
    assert due == datetime(2026, 10, 9, 18, 0, tzinfo=UTC)
    # 00:15 IST on Saturday is 18:45 UTC on Friday.
    due = routines.next_occurrence(every_day, 15, after=_ist(2026, 10, 9, 23, 59))
    assert due == datetime(2026, 10, 9, 18, 45, tzinfo=UTC)


def test_a_weekly_routine_waits_a_week_after_it_fires() -> None:
    sunday = routines.days_mask(["sun"])
    assert routines.next_occurrence(sunday, 10 * 60, after=_ist(2026, 10, 11, 10, 0)) == _ist(
        2026, 10, 18, 10, 0
    ).astimezone(UTC)


def test_the_day_mask_round_trips_and_refuses_what_is_not_a_day() -> None:
    assert routines.days_of(routines.days_mask(["fri", "mon"])) == ["mon", "fri"]
    with pytest.raises(ValueError, match="weekday"):
        routines.days_mask(["someday"])
    with pytest.raises(ValueError, match="at least one day"):
        routines.next_occurrence(0, 0, after=datetime.now(UTC))


# --- the routes -----------------------------------------------------------------------------


async def test_a_routine_is_saved_redacted_and_scheduled() -> None:
    tenant_id, slug, token = await _make_tenant()
    created = await _create(
        token,
        slug,
        {**_BODY, "instruction": "Every morning call 9876543210 back and tell me"},
    )
    assert created["enabled"] is True
    assert created["schedule"] == _BODY["schedule"]
    assert created["next_run_at"] is not None
    assert "9876543210" not in str(created["instruction"]), "a number never reaches the row"
    async with _client() as http:
        listed = await http.get("/v1/copilot/routines", headers=_headers(token, slug))
    assert [row["id"] for row in listed.json()["routines"]] == [created["id"]]
    async with tenant_session(tenant_id) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'copilot.routine_created' "
                    "AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert audited == 1


async def test_a_schedule_that_is_not_a_schedule_is_refused_at_the_door() -> None:
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        for schedule in (
            {"days": [], "time": "09:00"},
            {"days": ["mon", "mon"], "time": "09:00"},
            {"days": ["mon"], "time": "9am"},
            {"days": ["mon"], "time": "24:00"},
        ):
            response = await http.post(
                "/v1/copilot/routines",
                json={**_BODY, "schedule": schedule},
                headers=_headers(token, slug),
            )
            assert response.status_code == 422, schedule


async def test_switching_off_clears_the_next_run_and_switching_on_reschedules_from_now() -> None:
    _tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    async with _client() as http:
        off = await http.patch(
            f"/v1/copilot/routines/{created['id']}",
            json={"enabled": False},
            headers=_headers(token, slug),
        )
        assert off.json()["next_run_at"] is None
        on = await http.patch(
            f"/v1/copilot/routines/{created['id']}",
            json={"enabled": True, "schedule": {"days": ["sat"], "time": "18:30"}},
            headers=_headers(token, slug),
        )
    body = on.json()
    assert body["enabled"] is True
    due = datetime.fromisoformat(body["next_run_at"]).astimezone(routines.IST)
    assert (due.weekday(), due.hour, due.minute) == (5, 18, 30)
    assert due > datetime.now(UTC)


async def test_a_deleted_routine_is_gone() -> None:
    _tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    async with _client() as http:
        deleted = await http.delete(
            f"/v1/copilot/routines/{created['id']}", headers=_headers(token, slug)
        )
        assert deleted.status_code == 204
        again = await http.get(
            f"/v1/copilot/routines/{created['id']}/runs", headers=_headers(token, slug)
        )
    assert again.status_code == 404


async def test_one_person_keeps_a_bounded_number_of_routines() -> None:
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        for index in range(routines.MAX_ROUTINES_PER_USER):
            await routines.create_routine(
                session,
                tenant_id=tenant_id,
                user_id=_user_of(token),
                name=f"r{index}",
                instruction="tidy my leads",
                days=routines.EVERY_DAY,
                at_minute=600,
                enabled=False,
                now=datetime.now(UTC),
            )
    async with _client() as http:
        refused = await http.post("/v1/copilot/routines", json=_BODY, headers=_headers(token, slug))
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/copilot_routine_limit")


# --- RLS and the person -------------------------------------------------------------------


async def test_copilot_routines_rls_returns_zero_rows_across_tenants() -> None:
    _tenant_a, slug_a, token_a = await _make_tenant()
    tenant_b, slug_b, token_b = await _make_tenant()
    created = await _create(token_a, slug_a)
    async with _client() as http:
        run = await http.post(
            f"/v1/copilot/routines/{created['id']}/run", headers=_headers(token_a, slug_a)
        )
        assert run.status_code == 200, run.text
    async with tenant_session(tenant_b) as session:
        for table in ("copilot_routines", "copilot_routine_runs"):
            seen = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            assert seen == 0, table
    async with _client() as http:
        for method, path in (
            ("PATCH", f"/v1/copilot/routines/{created['id']}"),
            ("DELETE", f"/v1/copilot/routines/{created['id']}"),
            ("POST", f"/v1/copilot/routines/{created['id']}/run"),
            ("GET", f"/v1/copilot/routines/{created['id']}/runs"),
        ):
            response = await http.request(
                method,
                path,
                json={"enabled": False} if method == "PATCH" else None,
                headers=_headers(token_b, slug_b),
            )
            assert response.status_code == 404, (method, path)


async def test_a_colleagues_routine_is_not_yours_to_read_or_run() -> None:
    tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    colleague = await _add_member(tenant_id)
    async with tenant_session(tenant_id) as session:
        mine = await routines.list_routines(session, user_id=colleague, limit=20)
        assert mine == []
        with pytest.raises(ProblemError):
            await routines.read_routine(
                session, routine_id=UUID(str(created["id"])), user_id=colleague
            )


async def _add_member(tenant_id: UUID, role: str = "staff") -> UUID:
    user_id = uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :tid, :uid, :role, now(), now())"
            ),
            {"tid": tenant_id, "uid": user_id, "role": role},
        )
    return user_id


async def test_the_tick_reads_across_tenants_and_cannot_write_without_one() -> None:
    """The ops-read policy is a READ: an untenanted session sees due ids and nothing else
    may be written through it."""
    tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    async with untenanted_session() as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM copilot_routines WHERE id = :id"),
                {"id": UUID(str(created["id"]))},
            )
        ).scalar()
    assert seen == 1
    with pytest.raises(Exception, match=r"row-level security|violates"):
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "INSERT INTO copilot_routines (id, tenant_id, user_id, name, instruction, "
                    "days, at_minute, enabled, next_run_at) VALUES (gen_random_uuid(), :tid, "
                    ":uid, 'x', 'y', 1, 0, false, NULL)"
                ),
                {"tid": tenant_id, "uid": _user_of(token)},
            )
    async with untenanted_session() as session:
        updated = await session.execute(
            text("UPDATE copilot_routines SET name = 'hijacked' WHERE id = :id"),
            {"id": UUID(str(created["id"]))},
        )
        assert getattr(updated, "rowcount", 0) == 0


# --- firing ---------------------------------------------------------------------------------


async def test_a_due_slot_queues_one_job_and_fires_once() -> None:
    tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    now = datetime.now(UTC)
    slot = now - timedelta(minutes=2)
    await _make_due(tenant_id, str(created["id"]), slot)

    async with tenant_session(tenant_id) as session:
        assert await routines.fire_due(session, routine_id=UUID(str(created["id"])), now=now) == (
            "queued"
        )
    async with tenant_session(tenant_id) as session:
        again = await routines.fire_due(session, routine_id=UUID(str(created["id"])), now=now)
    assert again == "not_due", "a slot fires once"

    runs = await _runs(tenant_id, str(created["id"]))
    assert [(status, reason) for status, reason, _ in runs] == [("queued", None)]
    job_id = runs[0][2]
    assert job_id is not None
    async with tenant_session(tenant_id) as session:
        job = await jobs.read_job(session, job_id=job_id, user_id=_user_of(token))
        routine = await routines.read_routine(
            session, routine_id=UUID(str(created["id"])), user_id=_user_of(token)
        )
        actions = (await session.execute(text("SELECT count(*) FROM copilot_actions"))).scalar()
    assert job is not None
    assert job.status == "queued"
    assert job.goal.startswith("Morning call-backs:")
    assert job.screen_route == routines.ROUTINE_SCREEN_ROUTE
    assert routine.next_run_at is not None and routine.next_run_at > now
    assert routine.last_run_at is not None
    assert actions == 0, "firing a routine does nothing but queue a job"
    async with untenanted_session() as session:
        queued = (
            await session.execute(
                text("SELECT job FROM outbox_messages WHERE payload->>'job_id' = :j"),
                {"j": str(job_id)},
            )
        ).all()
    assert [row[0] for row in queued] == [jobs.COPILOT_JOB]


async def test_a_slot_reached_late_is_skipped_not_run_late() -> None:
    tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    now = datetime.now(UTC)
    await _make_due(tenant_id, str(created["id"]), now - routines.LATE_LIMIT - timedelta(minutes=5))
    async with tenant_session(tenant_id) as session:
        outcome = await routines.fire_due(session, routine_id=UUID(str(created["id"])), now=now)
    assert outcome == "skipped"
    [(status, reason, job_id)] = await _runs(tenant_id, str(created["id"]))
    assert status == "skipped"
    assert reason is not None and "could not start on time" in reason
    assert job_id is None
    async with tenant_session(tenant_id) as session:
        routine = await routines.read_routine(
            session, routine_id=UUID(str(created["id"])), user_id=_user_of(token)
        )
    assert routine.enabled and routine.next_run_at is not None and routine.next_run_at > now


async def test_a_person_already_running_two_tasks_has_the_run_skipped() -> None:
    tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    async with tenant_session(tenant_id) as session:
        for _ in range(jobs.MAX_ACTIVE_JOBS_PER_USER):
            await jobs.create_job(
                session,
                tenant_id=tenant_id,
                user_id=_user_of(token),
                goal="busy",
                screen_route="/c/{slug}/leads",
            )
    now = datetime.now(UTC)
    await _make_due(tenant_id, str(created["id"]), now - timedelta(minutes=1))
    async with tenant_session(tenant_id) as session:
        assert (
            await routines.fire_due(session, routine_id=UUID(str(created["id"])), now=now)
            == "skipped"
        )
    [(status, reason, _)] = await _runs(tenant_id, str(created["id"]))
    assert status == "skipped" and reason is not None and "tasks running" in reason
    async with _client() as http:
        refused = await http.post(
            f"/v1/copilot/routines/{created['id']}/run", headers=_headers(token, slug)
        )
    assert refused.status_code == 409
    assert refused.json()["type"].endswith("/copilot_routine_not_started")


async def test_a_routine_whose_author_left_is_switched_off() -> None:
    tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM memberships WHERE user_id = :u"), {"u": _user_of(token)}
        )
    now = datetime.now(UTC)
    await _make_due(tenant_id, str(created["id"]), now - timedelta(minutes=1))
    async with tenant_session(tenant_id) as session:
        assert (
            await routines.fire_due(session, routine_id=UUID(str(created["id"])), now=now)
            == "skipped"
        )
        routine = await routines.read_routine(
            session, routine_id=UUID(str(created["id"])), user_id=_user_of(token)
        )
    assert routine.enabled is False and routine.next_run_at is None
    [(status, reason, _)] = await _runs(tenant_id, str(created["id"]))
    assert status == "skipped" and reason is not None and "no longer on the account" in reason


async def test_run_now_queues_a_job_and_leaves_the_schedule_alone() -> None:
    _tenant_id, slug, token = await _make_tenant()
    created = await _create(token, slug)
    async with _client() as http:
        run = await http.post(
            f"/v1/copilot/routines/{created['id']}/run", headers=_headers(token, slug)
        )
        assert run.status_code == 200, run.text
        history = await http.get(
            f"/v1/copilot/routines/{created['id']}/runs", headers=_headers(token, slug)
        )
        listed = await http.get("/v1/copilot/routines", headers=_headers(token, slug))
    body = run.json()
    assert body["trigger"] == "manual" and body["status"] == "queued" and body["job_id"]
    assert [row["id"] for row in history.json()["runs"]] == [body["id"]]
    assert history.json()["runs"][0]["job_status"] == "queued"
    assert listed.json()["routines"][0]["next_run_at"] == created["next_run_at"]


async def test_the_tick_fires_what_is_due_in_any_account() -> None:
    tenant_a, slug_a, token_a = await _make_tenant()
    tenant_b, slug_b, token_b = await _make_tenant()
    due_a = await _create(token_a, slug_a)
    due_b = await _create(token_b, slug_b)
    later = await _create(token_b, slug_b, {**_BODY, "name": "Later"})
    slot = datetime.now(UTC) - timedelta(minutes=1)
    await _make_due(tenant_a, str(due_a["id"]), slot)
    await _make_due(tenant_b, str(due_b["id"]), slot)
    result = await fire_due_routines({"job_try": 1})
    assert "failed=0" in result
    assert [status for status, _, _ in await _runs(tenant_a, str(due_a["id"]))] == ["queued"]
    assert [status for status, _, _ in await _runs(tenant_b, str(due_b["id"]))] == ["queued"]
    assert await _runs(tenant_b, str(later["id"])) == []


# --- the approval preview ---------------------------------------------------------------------


async def _stage_dnc(tenant_id: UUID, token: str) -> write_tools.StagedApproval:
    async with tenant_session(tenant_id) as session:
        job = await jobs.create_job(
            session,
            tenant_id=tenant_id,
            user_id=_user_of(token),
            goal="tidy",
            screen_route="/c/{slug}/leads",
        )
        lead = (await session.execute(text("SELECT id FROM leads LIMIT 1"))).scalar()
    return await write_tools.stage_for_approval(
        "dnc_add",
        json.dumps({"lead_id": str(lead), "reason": "manual"}),
        principal=Principal(
            realm="client", user_id=_user_of(token), tenant_id=tenant_id, role="owner"
        ),
        job_id=job.id,
    )


async def test_the_preview_says_what_approving_would_do_and_changes_nothing() -> None:
    tenant_id, slug, token = await _make_tenant()
    staged = await _stage_dnc(tenant_id, token)
    async with _client() as http:
        preview = await http.get(
            f"/v1/copilot/approvals/{staged.action_id}/preview", headers=_headers(token, slug)
        )
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["still_applies"] is True and body["refusal"] is None
    assert body["title"] and body["proposed"] and body["reversal"]
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM copilot_actions WHERE id = :i"), {"i": staged.action_id}
            )
        ).scalar()
        suppressed = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert status == "pending_approval"
    assert suppressed == 0

    async with _client() as http:
        await http.post(
            f"/v1/copilot/approvals/{staged.action_id}/reject", headers=_headers(token, slug)
        )
        decided = await http.get(
            f"/v1/copilot/approvals/{staged.action_id}/preview", headers=_headers(token, slug)
        )
    assert decided.json()["still_applies"] is False
    assert decided.json()["refusal"]


async def test_another_accounts_approval_cannot_be_previewed() -> None:
    tenant_a, _slug_a, token_a = await _make_tenant()
    _tenant_b, slug_b, token_b = await _make_tenant()
    staged = await _stage_dnc(tenant_a, token_a)
    async with _client() as http:
        response = await http.get(
            f"/v1/copilot/approvals/{staged.action_id}/preview", headers=_headers(token_b, slug_b)
        )
    assert response.status_code == 404
