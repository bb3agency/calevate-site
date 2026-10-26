"""Plans (D-893 F3): one card, one click, exact execution.

The plan freezes its targets and binds its hash; the confirm token approves exactly that
plan; the worker runs each frozen target once, re-checked against the world at that
moment, resumable and cancellable; the result reaches the bell; the tables are FORCE-RLS
tenant tables. Every test mints its own tenant.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

from apps.api.copilot import plans, set_actions, write_tools
from apps.api.copilot.write_tools_test import _actor, _confirm, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.notifications import service as notifications
from apps.workers import copilot_plans as worker


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _agent(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        return UUID(str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()))


async def _leads(tenant_id: UUID, n: int, *, status: str = "new") -> list[UUID]:
    agent_id = await _agent(tenant_id)
    ids = [uuid.uuid4() for _ in range(n)]
    async with tenant_session(tenant_id) as session:
        for index, lead_id in enumerate(ids):
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, created_at, updated_at) VALUES (:i, :t, :a, :p, :n, 'manual', :s, "
                    "now() - make_interval(secs => :age), now())"
                ),
                {
                    "i": lead_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "p": f"+9197{uuid.uuid4().int % 100000000:08d}",
                    "n": f"Lead {index}",
                    "s": status,
                    "age": n - index,
                },
            )
    return ids


async def _statuses(tenant_id: UUID, ids: list[UUID]) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id, status FROM leads WHERE id = ANY(:ids)"), {"ids": ids}
            )
        ).all()
    by_id = {UUID(str(r[0])): str(r[1]) for r in rows}
    return [by_id[i] for i in ids]


async def _build(tenant_id: UUID, user_id: UUID, args: dict[str, Any]) -> plans.PlanRow:
    async with tenant_session(tenant_id) as session:
        return await plans.build_plan(
            session,
            _actor(tenant_id, user_id),
            tool="leads_bulk_update",
            action=set_actions.BULK_UPDATE,
            args=args,
            origin="pip",
        )


async def _run(tenant_id: UUID, plan_id: UUID) -> str:
    return await worker.run_copilot_plan({}, {"tenant_id": str(tenant_id), "plan_id": str(plan_id)})


async def _plan(tenant_id: UUID, plan_id: UUID) -> plans.PlanRow:
    async with tenant_session(tenant_id) as session:
        row = await plans.read_plan(session, plan_id)
    assert row is not None
    return row


async def _queued_runs(tenant_id: UUID, plan_id: UUID) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload ->> 'plan_id' = :pid"
                    ),
                    {"job": plans.RUN_PLAN_JOB, "pid": str(plan_id)},
                )
            ).scalar()
            or 0
        )


# --- building --------------------------------------------------------------------------


async def test_a_plan_freezes_its_targets_and_says_who_is_left_out_and_why() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    fresh = await _leads(tenant_id, 3)
    hot = await _leads(tenant_id, 1, status="hot")
    plan = await _build(
        tenant_id,
        user_id,
        {"lead_ids": [str(i) for i in [*fresh, *hot]], "action": "status", "status": "hot"},
    )
    assert plan.status == "proposed"
    assert plan.target_count == 4 and plan.excluded_count == 1
    assert plan.exclusions == {"Already hot.": 1}
    assert plan.estimate_inr == 0 and plan.estimate_note == plans.NO_COST.note
    assert plan.lens_text == "the 4 leads you chose"
    assert len(plan.plan_hash) == 64
    async with tenant_session(tenant_id) as session:
        rows, total = await plans.targets_page(session, plan, limit=10, offset=0)
    assert total == 4
    assert [r.target_id for r in rows] == [*fresh, *hot]
    assert [r.status for r in rows] == ["pending", "pending", "pending", "skipped"]
    assert rows[0].label == "Lead 0"


async def test_a_lens_chooses_the_set_and_an_empty_set_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    hot = await _leads(tenant_id, 2, status="hot")
    plan = await _build(
        tenant_id,
        _user_of(token),
        {"lens": {"status": "hot"}, "action": "status", "status": "won"},
    )
    assert plan.target_count == 2
    assert plan.lens_text == "leads stage hot"
    async with tenant_session(tenant_id) as session:
        rows, _ = await plans.targets_page(session, plan, limit=10, offset=0)
    assert {r.target_id for r in rows} == set(hot)
    with pytest.raises(write_tools.WriteRefusedError, match="nothing matches"):
        await _build(
            tenant_id,
            _user_of(token),
            {"lens": {"status": "lost"}, "action": "status", "status": "won"},
        )
    with pytest.raises(write_tools.WriteRefusedError, match="not both"):
        await _build(
            tenant_id,
            _user_of(token),
            {
                "lens": {"status": "hot"},
                "lead_ids": [str(hot[0])],
                "action": "status",
                "status": "won",
            },
        )


def test_the_hash_covers_targets_exclusions_change_and_estimate() -> None:
    a, b = uuid.uuid4(), uuid.uuid4()
    base = {
        "tool": "leads_bulk_update",
        "change": {"action": "status", "status": "hot"},
        "targets": [a, b],
        "excluded": {},
        "estimate": plans.NO_COST,
        "run_at": None,
    }
    same = plans.plan_hash(**base)  # type: ignore[arg-type]
    assert plans.plan_hash(**base) == same  # type: ignore[arg-type]
    for change in (
        {"targets": [b, a]},
        {"excluded": {a: "x"}},
        {"change": {"action": "status", "status": "won"}},
        {"estimate": plans.Estimate(inr=None, note="")},
    ):
        assert plans.plan_hash(**{**base, **change}) != same  # type: ignore[arg-type]


# --- approving, through the confirm token ---------------------------------------------------


async def test_confirm_approves_exactly_the_plan_and_queues_its_run_once() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 2)
    proposal = await write_tools.plan_write(
        "leads_bulk_update",
        json.dumps({"lead_ids": [str(i) for i in ids], "action": "status", "status": "hot"}),
        actor=_actor(tenant_id, user_id),
    )
    assert proposal.plan_id is not None
    assert proposal.proposed == "2 lead(s)"
    plan_id = UUID(proposal.plan_id)
    assert await _statuses(tenant_id, ids) == ["new", "new"], "a proposal changes nothing"
    done = await _confirm(tenant_id, user_id, proposal.token)
    assert done.plan_id == proposal.plan_id
    assert (await _plan(tenant_id, plan_id)).status == "approved"
    assert await _queued_runs(tenant_id, plan_id) == 1
    with pytest.raises(ProblemError):
        await _confirm(tenant_id, user_id, proposal.token)
    assert await _queued_runs(tenant_id, plan_id) == 1


async def test_a_changed_hash_an_expired_plan_and_another_person_are_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 1)
    plan = await _build(
        tenant_id, user_id, {"lead_ids": [str(ids[0])], "action": "status", "status": "hot"}
    )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as changed:
            await plans.approve(
                session, _actor(tenant_id, user_id), plan_id=plan.id, expected_hash="0" * 64
            )
        assert changed.value.code == "copilot_plan_changed"
        with pytest.raises(ProblemError) as stranger:
            await plans.approve(
                session,
                _actor(tenant_id, uuid.uuid4()),
                plan_id=plan.id,
                expected_hash=plan.plan_hash,
            )
        assert stranger.value.status == 404
        await session.execute(
            text("UPDATE copilot_plans SET expires_at = now() - interval '1 minute' WHERE id = :i"),
            {"i": plan.id},
        )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as expired:
            await plans.approve(
                session, _actor(tenant_id, user_id), plan_id=plan.id, expected_hash=plan.plan_hash
            )
        assert expired.value.code == "copilot_plan_expired"


# --- running ---------------------------------------------------------------------------


async def _approved(tenant_id: UUID, user_id: UUID, args: dict[str, Any]) -> plans.PlanRow:
    plan = await _build(tenant_id, user_id, args)
    async with tenant_session(tenant_id) as session:
        return await plans.approve(
            session, _actor(tenant_id, user_id), plan_id=plan.id, expected_hash=plan.plan_hash
        )


async def test_the_run_changes_exactly_the_frozen_leads_once_and_records_each() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    frozen = await _leads(tenant_id, 3)
    plan = await _approved(
        tenant_id, user_id, {"lens": {"status": "new"}, "action": "status", "status": "contacted"}
    )
    late = await _leads(tenant_id, 1)  # matches the lens now, but was not in the plan
    assert await _run(tenant_id, plan.id) == "done"
    assert await _statuses(tenant_id, frozen) == ["contacted"] * 3
    assert await _statuses(tenant_id, late) == ["new"], "a target is never swapped in"
    finished = await _plan(tenant_id, plan.id)
    assert finished.status == "done"
    assert finished.done_count >= 3
    assert finished.result is not None and finished.result.startswith("Finished.")
    assert await _run(tenant_id, plan.id) == "not_runnable", "a second delivery does nothing"


async def test_each_target_is_rechecked_when_it_runs() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 2)
    plan = await _approved(
        tenant_id, user_id, {"lead_ids": [str(i) for i in ids], "action": "status", "status": "hot"}
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET deleted_at = now() WHERE id = :i"), {"i": ids[0]}
        )
    await _run(tenant_id, plan.id)
    async with tenant_session(tenant_id) as session:
        rows, _ = await plans.targets_page(
            session, await _plan(tenant_id, plan.id), limit=5, offset=0
        )
    outcome = {r.target_id: (r.status, r.reason) for r in rows}
    assert outcome[ids[1]] == ("done", None)
    assert outcome[ids[0]][0] == "failed"
    assert (await _plan(tenant_id, plan.id)).failed_count == 1


async def test_a_resumed_run_settles_only_what_is_still_pending() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 3)
    plan = await _approved(
        tenant_id, user_id, {"lead_ids": [str(i) for i in ids], "action": "status", "status": "hot"}
    )
    async with tenant_session(tenant_id) as session:
        await plans.claim_run(session, plan.id)
        await plans.record_outcome(session, plan.id, ids[0], plans.TargetOutcome("done"))
    # The worker that settled the first one died; a resumed run finishes the rest.
    await _run(tenant_id, plan.id)
    assert await _statuses(tenant_id, ids) == ["new", "hot", "hot"]
    assert (await _plan(tenant_id, plan.id)).status == "done"


async def test_cancel_stops_the_rest_and_says_so() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 2)
    plan = await _approved(
        tenant_id, user_id, {"lead_ids": [str(i) for i in ids], "action": "status", "status": "hot"}
    )
    async with tenant_session(tenant_id) as session:
        cancelled = await plans.cancel(session, plan_id=plan.id, user_id=user_id)
    assert cancelled.status == "cancelled"
    assert cancelled.skipped_count == 2
    assert cancelled.result == "Stopped. 0 done, 2 skipped."
    assert await _run(tenant_id, plan.id) == "not_runnable"
    assert await _statuses(tenant_id, ids) == ["new", "new"]
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as again:
            await plans.cancel(session, plan_id=plan.id, user_id=user_id)
    assert again.value.code == "copilot_plan_not_cancellable"


async def test_a_member_who_left_runs_nothing() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 1)
    plan = await _approved(
        tenant_id, user_id, {"lead_ids": [str(ids[0])], "action": "status", "status": "hot"}
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(text("DELETE FROM memberships WHERE user_id = :u"), {"u": user_id})
    assert await _run(tenant_id, plan.id) == "member_gone"
    finished = await _plan(tenant_id, plan.id)
    assert finished.status == "done" and finished.skipped_count == 1
    assert await _statuses(tenant_id, ids) == ["new"]


async def test_a_finished_plan_reaches_the_bell() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 1)
    plan = await _approved(
        tenant_id, user_id, {"lead_ids": [str(ids[0])], "action": "status", "status": "hot"}
    )
    await _run(tenant_id, plan.id)
    async with tenant_session(tenant_id) as session:
        bell = await notifications.feed(session, tenant_id=tenant_id, user_id=user_id, limit=20)
    item = next(n for n in bell.items if n.id == f"plan:{plan.id}")
    assert item.source == "plan" and item.tone == "success"
    assert item.title == "Change 1 leads: finished"
    assert item.unread


async def test_the_resume_sweep_requeues_a_stalled_plan() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 1)
    plan = await _approved(
        tenant_id, user_id, {"lead_ids": [str(ids[0])], "action": "status", "status": "hot"}
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE copilot_plans SET updated_at = now() - interval '1 hour' WHERE id = :i"),
            {"i": plan.id},
        )
    assert (await worker.resume_copilot_plans({})).startswith("resumed=")
    assert await _queued_runs(tenant_id, plan.id) == 2


# --- the other set actions ------------------------------------------------------------------


async def test_callbacks_book_bulk_books_one_per_lead_inside_the_window() -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 2)
    at = (
        (datetime.now(UTC) + timedelta(days=2))
        .astimezone(plans_ist())
        .replace(hour=11, minute=0, second=0, microsecond=0)
    )
    async with tenant_session(tenant_id) as session:
        plan = await plans.build_plan(
            session,
            _actor(tenant_id, user_id),
            tool="callbacks_book_bulk",
            action=set_actions.BOOK_CALLBACKS,
            args={"lead_ids": [str(i) for i in ids], "at": at.strftime("%Y-%m-%dT%H:%M")},
            origin="pip",
        )
        assert plan.run_at == at.astimezone(UTC)
        await plans.approve(
            session, _actor(tenant_id, user_id), plan_id=plan.id, expected_hash=plan.plan_hash
        )
    await _run(tenant_id, plan.id)
    async with tenant_session(tenant_id) as session:
        booked = (
            await session.execute(
                text(
                    "SELECT count(*) FROM scheduled_callbacks WHERE lead_id = ANY(:ids) "
                    "AND status = 'scheduled'"
                ),
                {"ids": ids},
            )
        ).scalar_one()
    finished = await _plan(tenant_id, plan.id)
    assert int(booked) + finished.skipped_count == 2  # a standing refusal is skipped, never booked
    night = at.replace(hour=22)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(write_tools.WriteRefusedError, match="9am and 9pm"):
            await plans.build_plan(
                session,
                _actor(tenant_id, user_id),
                tool="callbacks_book_bulk",
                action=set_actions.BOOK_CALLBACKS,
                args={"lead_ids": [str(ids[0])], "at": night.strftime("%Y-%m-%dT%H:%M")},
                origin="pip",
            )


def plans_ist() -> Any:
    from apps.api.billing.plans import IST

    return IST


async def test_a_dial_plan_refused_by_the_account_gate_is_refused_before_a_card() -> None:
    tenant_id, _slug, token = await _make_tenant()
    ids = await _leads(tenant_id, 1)
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE agents SET direction = 'outbound'"))
        with pytest.raises(write_tools.WriteRefusedError, match="cannot place calls yet"):
            await plans.build_plan(
                session,
                _actor(tenant_id, _user_of(token)),
                tool="calls_place_bulk",
                action=set_actions.DIAL_LEADS,
                args={
                    "lead_ids": [str(ids[0])],
                    "agent_id": str(await _agent(tenant_id)),
                    "classification": "service",
                    "consent_source": "inbound_enquiry",
                },
                origin="pip",
            )


async def test_a_dial_plan_whose_launch_is_refused_places_no_call_and_says_why(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The plan worker does not dial: it makes a `pip` campaign and launches it, and a launch
    the gate refuses rolls the campaign back and closes the plan with the gate's reason."""
    tenant_id, _slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 1)

    async def no_blockers(*_: Any, **__: Any) -> list[tuple[str, str]]:
        return []

    monkeypatch.setattr("apps.api.compliance.service.account_dial_blockers", no_blockers)
    async with tenant_session(tenant_id) as session:
        await session.execute(text("UPDATE agents SET direction = 'outbound'"))
        plan = await plans.build_plan(
            session,
            _actor(tenant_id, user_id),
            tool="calls_place_bulk",
            action=set_actions.DIAL_LEADS,
            args={
                "lead_ids": [str(ids[0])],
                "agent_id": str(await _agent(tenant_id)),
                "classification": "service",
                "consent_source": "inbound_enquiry",
            },
            origin="pip",
        )
        await plans.approve(
            session, _actor(tenant_id, user_id), plan_id=plan.id, expected_hash=plan.plan_hash
        )
    assert await _run(tenant_id, plan.id) == "refused"
    finished = await _plan(tenant_id, plan.id)
    assert finished.status == "done" and finished.campaign_id is None
    assert finished.result is not None and finished.result.endswith("No calls were placed.")
    async with tenant_session(tenant_id) as session:
        pip = (
            await session.execute(text("SELECT count(*) FROM campaigns WHERE kind = 'pip'"))
        ).scalar()
    assert pip == 0


# --- the routes ------------------------------------------------------------------------


async def test_the_routes_read_approve_and_cancel_a_plan_for_its_owner_only() -> None:
    tenant_id, slug, token = await _make_tenant()
    user_id = _user_of(token)
    ids = await _leads(tenant_id, 2)
    plan = await _build(
        tenant_id, user_id, {"lead_ids": [str(i) for i in ids], "action": "status", "status": "hot"}
    )
    async with _client() as http:
        read = await http.get(f"/v1/copilot/plans/{plan.id}", headers=_headers(token, slug))
        assert read.status_code == 200, read.text
        body = read.json()
        assert body["status"] == "proposed" and body["can_approve"] is True
        assert body["who"] == "the 2 leads you chose"
        page = await http.get(
            f"/v1/copilot/plans/{plan.id}/targets",
            params={"limit": 1},
            headers=_headers(token, slug),
        )
        assert page.json()["total"] == 2 and len(page.json()["targets"]) == 1
        listed = await http.get("/v1/copilot/plans", headers=_headers(token, slug))
        assert [p["id"] for p in listed.json()["plans"]] == [str(plan.id)]
        wrong = await http.post(
            f"/v1/copilot/plans/{plan.id}/approve",
            json={"plan_hash": "f" * 64},
            headers=_headers(token, slug),
        )
        assert wrong.status_code == 409
        approved = await http.post(
            f"/v1/copilot/plans/{plan.id}/approve",
            json={"plan_hash": plan.plan_hash},
            headers=_headers(token, slug),
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["status"] == "approved"
        stopped = await http.post(
            f"/v1/copilot/plans/{plan.id}/cancel", headers=_headers(token, slug)
        )
        assert stopped.json()["status"] == "cancelled"
        _other, other_slug, other_token = await _make_tenant()
        hidden = await http.get(
            f"/v1/copilot/plans/{plan.id}", headers=_headers(other_token, other_slug)
        )
        assert hidden.status_code == 404


async def test_the_bulk_route_runs_a_set_beyond_one_request_as_a_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.crm import routes as crm_routes

    monkeypatch.setattr(crm_routes, "MAX_BULK_LEADS", 2)
    tenant_id, slug, token = await _make_tenant()
    ids = await _leads(tenant_id, 3, status="interested")
    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            json={
                "scope": "filter",
                "action": "status",
                "status": "won",
                "lens": {"status": "interested"},
                "expected_count": 3,
            },
            headers=_headers(token, slug),
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["plan_id"] is not None and body["requested"] == 3
    plan_id = UUID(body["plan_id"])
    plan = await _plan(tenant_id, plan_id)
    assert plan.origin == "console" and plan.status == "approved"
    await _run(tenant_id, plan_id)
    assert await _statuses(tenant_id, ids) == ["won"] * 3


# --- tenancy ---------------------------------------------------------------------------


async def test_another_tenant_reads_zero_plan_and_target_rows() -> None:
    tenant_id, _slug, token = await _make_tenant()
    ids = await _leads(tenant_id, 1)
    await _build(
        tenant_id, _user_of(token), {"lead_ids": [str(ids[0])], "action": "status", "status": "hot"}
    )
    other, _s, _t = await _make_tenant()
    async with tenant_session(other) as session:
        for table in ("copilot_plans", "copilot_plan_targets"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            assert count == 0, table
    async with tenant_session(tenant_id) as session:
        assert (await session.execute(text("SELECT count(*) FROM copilot_plans"))).scalar() == 1


def test_every_plan_backed_tool_is_confirm_tier_and_registered() -> None:
    for name in (
        "leads_bulk_update",
        "campaign_add_leads",
        "callbacks_book_bulk",
        "calls_place_bulk",
    ):
        assert write_tools.tier_of(name) == "confirm", name
        assert plans.set_action_of(name) is not None, name
