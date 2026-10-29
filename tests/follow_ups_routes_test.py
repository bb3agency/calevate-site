"""`/v1/follow-ups` (D-940): the HTTP contract of docs/FOLLOW-UPS.md, its errors, its
permissions, and that one account never reaches another's Follow-ups."""

from __future__ import annotations

import uuid
from typing import Any

from apps.api.db.session import tenant_session
from httpx import AsyncClient
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _client, _lead, _tenant

STEPS: list[dict[str, Any]] = [
    {"id": "s1", "kind": "wait", "hours": 2, "next": "s2"},
    {"id": "s2", "kind": "set_status", "status": "hot", "next": "s3"},
    {"id": "s3", "kind": "end", "goal": True},
]


async def _create(http: AsyncClient, t: Tenant, **body: Any) -> dict[str, Any]:
    payload = {"name": "Warm up", "trigger": {"kind": "manual"}, "steps": STEPS, **body}
    response = await http.post("/v1/follow-ups", json=payload, headers=t.headers)
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _publish(http: AsyncClient, t: Tenant, made: dict[str, Any]) -> Any:
    return await http.post(
        f"/v1/follow-ups/{made['id']}/publish",
        json={"expected_updated_at": made["updated_at"]},
        headers=t.headers,
    )


async def test_create_edit_publish_and_the_lifecycle() -> None:
    t = await _tenant()
    async with _client() as http:
        made = await _create(http, t)
        assert made["status"] == "draft" and made["has_unpublished_changes"] is True
        assert made["live_version"] is None and made["problems"] == []
        assert [s["summary"] for s in made["steps"]] == [
            "Wait 2 hours",
            "Mark the lead hot",
            "Finish (goal reached)",
        ]
        assert made["counts"] == {"running": 0, "waiting": 0, "done_30d": 0, "goal_30d": 0}

        published = await _publish(http, t, made)
        assert published.status_code == 200, published.text
        live = published.json()
        assert live["status"] == "live" and live["live_version"]["number"] == 1
        assert live["has_unpublished_changes"] is False

        same = await _publish(http, t, live)
        assert same.json()["live_version"]["number"] == 1, "nothing to publish is a no-op"

        edited = await http.patch(
            f"/v1/follow-ups/{made['id']}",
            json={
                "name": "Warm up v2",
                "step_edits": [{"step_id": "s1", "wait": {"minutes": 30}}],
                "settings": {"max_days": 5},
            },
            headers=t.headers,
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["name"] == "Warm up v2" and body["has_unpublished_changes"] is True
        assert body["steps"][0]["summary"] == "Wait 30 minutes"

        changed = await http.post(
            f"/v1/follow-ups/{made['id']}/publish",
            json={"expected_updated_at": made["updated_at"]},
            headers=t.headers,
        )
        assert changed.status_code == 409
        assert changed.json()["type"].endswith("/follow_up_changed")
        assert changed.json()["expected_updated_at"]

        v2 = await http.post(
            f"/v1/follow-ups/{made['id']}/publish",
            json={"expected_updated_at": body["updated_at"]},
            headers=t.headers,
        )
        assert v2.json()["live_version"]["number"] == 2

        for leaf, status in (("pause", "paused"), ("resume", "live"), ("turn-off", "off")):
            moved = await http.post(f"/v1/follow-ups/{made['id']}/{leaf}", headers=t.headers)
            assert (moved.status_code, moved.json()["status"]) == (200, status), moved.text
        again = await http.post(f"/v1/follow-ups/{made['id']}/pause", headers=t.headers)
        assert again.status_code == 409 and again.json()["type"].endswith("/follow_up_not_live")
        back = await http.post(f"/v1/follow-ups/{made['id']}/resume", headers=t.headers)
        assert back.json()["status"] == "live"

        listed = await http.get("/v1/follow-ups", headers=t.headers)
        assert listed.status_code == 200
        [row] = [i for i in listed.json()["items"] if i["id"] == made["id"]]
        assert row["starts_when"] == "You start it for chosen leads"


async def test_a_draft_with_problems_lists_them_and_will_not_publish() -> None:
    t = await _tenant()
    async with _client() as http:
        made = await _create(
            http,
            t,
            steps=[
                {"id": "s1", "kind": "assign", "user_id": str(uuid.uuid4()), "next": "s2"},
                {"id": "s2", "kind": "call", "agent_id": str(t.agent_id)},
            ],
        )
        codes = {(p["step_id"], p["code"]) for p in made["problems"]}
        assert codes == {("s1", "teammate_unknown"), ("s2", "agent_cannot_call")}
        refused = await _publish(http, t, made)
        assert refused.status_code == 422
        body = refused.json()
        assert body["type"].endswith("/follow_up_invalid")
        assert {(p["step_id"], p["code"]) for p in body["problems"]} == codes

        rewritten = await http.put(
            f"/v1/follow-ups/{made['id']}/draft",
            json={"trigger": {"kind": "manual"}, "steps": STEPS, "settings": {}},
            headers=t.headers,
        )
        assert rewritten.status_code == 200 and rewritten.json()["problems"] == []
        assert (await _publish(http, t, rewritten.json())).status_code == 200


async def test_small_edits_that_do_not_fit_are_refused() -> None:
    t = await _tenant()
    async with _client() as http:
        made = await _create(http, t)
        for edit in (
            {"step_id": "zz", "remove": True},
            {"step_id": "s2", "wait": {"minutes": 5}},
            {"step_id": "s2", "agent_id": str(t.agent_id)},
            {"step_id": "s2", "template_id": str(uuid.uuid4())},
        ):
            refused = await http.patch(
                f"/v1/follow-ups/{made['id']}", json={"step_edits": [edit]}, headers=t.headers
            )
            assert refused.status_code == 422, (edit, refused.text)
        removed = await http.patch(
            f"/v1/follow-ups/{made['id']}",
            json={"step_edits": [{"step_id": "s2", "remove": True}]},
            headers=t.headers,
        )
        steps = removed.json()["steps"]
        assert [s["id"] for s in steps] == ["s1", "s3"]
        assert steps[0]["next"] == "s3", "what led to a removed step leads where it led"


async def test_two_follow_ups_for_every_new_lead_cannot_both_be_on() -> None:
    t = await _tenant()
    new_lead = {"kind": "new_lead"}
    async with _client() as http:
        first = await _create(http, t, trigger=new_lead)
        assert (await _publish(http, t, first)).status_code == 200
        second = await _create(http, t, trigger=new_lead, name="Second")
        overlap = await _publish(http, t, second)
        assert overlap.status_code == 409
        assert overlap.json()["type"].endswith("/follow_up_trigger_overlap")
        await http.post(f"/v1/follow-ups/{first['id']}/turn-off", headers=t.headers)
        assert (await _publish(http, t, second)).status_code == 200
        blocked = await http.post(f"/v1/follow-ups/{first['id']}/resume", headers=t.headers)
        assert blocked.status_code == 409


async def test_start_runs_results_and_stopping_one_run() -> None:
    t = await _tenant()
    lead_a, lead_b = await _lead(t), await _lead(t)
    async with _client() as http:
        made = await _create(http, t)
        not_live = await http.post(
            f"/v1/follow-ups/{made['id']}/start",
            json={"lead_ids": [str(lead_a)]},
            headers=t.headers,
        )
        assert not_live.status_code == 409
        await _publish(http, t, made)
        unclear = await http.post(f"/v1/follow-ups/{made['id']}/start", json={}, headers=t.headers)
        assert unclear.status_code == 422
        moved = await http.post(
            f"/v1/follow-ups/{made['id']}/start",
            json={"lens": {"status": "new"}, "expected_count": 99},
            headers=t.headers,
        )
        assert moved.status_code == 409
        started = await http.post(
            f"/v1/follow-ups/{made['id']}/start",
            json={"lead_ids": [str(lead_a), str(lead_b), str(lead_a)]},
            headers=t.headers,
        )
        assert started.json() == {"started": 2, "skipped": 0, "plan_id": None}
        by_lens = await http.post(
            f"/v1/follow-ups/{made['id']}/start",
            json={"lens": {"status": "new"}},
            headers=t.headers,
        )
        assert by_lens.json()["started"] == 0, "both are already in it"

        runs = await http.get(
            f"/v1/follow-ups/{made['id']}/runs", params={"limit": 1}, headers=t.headers
        )
        page = runs.json()
        assert len(page["items"]) == 1 and page["next_cursor"]
        assert page["items"][0]["step_summary"] == "Wait 2 hours"
        rest = await http.get(
            f"/v1/follow-ups/{made['id']}/runs",
            params={"cursor": page["next_cursor"], "status": "waiting"},
            headers=t.headers,
        )
        assert len(rest.json()["items"]) == 1 and rest.json()["next_cursor"] is None
        bad = await http.get(
            f"/v1/follow-ups/{made['id']}/runs", params={"cursor": "nope"}, headers=t.headers
        )
        assert bad.status_code == 422

        run_id = page["items"][0]["id"]
        detail = await http.get(f"/v1/follow-ups/{made['id']}/runs/{run_id}", headers=t.headers)
        assert detail.json()["events"][0]["kind"] == "start"
        stopped = await http.post(
            f"/v1/follow-ups/{made['id']}/runs/{run_id}/stop", headers=t.headers
        )
        assert (stopped.json()["status"], stopped.json()["end_reason"]) == (
            "stopped",
            "stopped_by_client",
        )
        again = await http.post(
            f"/v1/follow-ups/{made['id']}/runs/{run_id}/stop", headers=t.headers
        )
        assert again.json()["type"].endswith("/follow_up_run_not_running")

        results = (await http.get(f"/v1/follow-ups/{made['id']}/results", headers=t.headers)).json()
        assert (results["days"], results["started"]) == (30, 2)
        assert [s["step_id"] for s in results["steps"]] == ["s1", "s2", "s3"]

        one = await http.get(f"/v1/follow-ups/{made['id']}", headers=t.headers)
        assert one.json()["counts"]["waiting"] == 1


async def test_the_starters_are_filled_in_for_the_account() -> None:
    t = await _tenant()
    async with _client() as http:
        found = (await http.get("/v1/follow-ups/starters", headers=t.headers)).json()["items"]
        keys = [s["key"] for s in found]
        assert keys == [
            "call_new_leads",
            "qualify_new_leads",
            "missed_call_callback",
            "appointment_reminder",
            "payment_reminder",
            "win_back",
        ]
        qualify = found[1]
        assert set(qualify["needs"]) == {"outbound_agent", "whatsapp_template", "team_address"}
        made = await _create(
            http,
            t,
            name=qualify["name"],
            trigger=qualify["trigger"],
            steps=[{k: v for k, v in s.items() if k != "summary"} for s in qualify["steps"]],
            settings=qualify["settings"],
            starter="qualify_new_leads",
        )
        assert {p["code"] for p in made["problems"]} >= {"agent_unknown", "template_unknown"}
        first = await _create(http, t, starter="call_new_leads", trigger={"kind": "new_lead"})
        assert first["starter"] == "call_new_leads"
        twice = await http.post(
            "/v1/follow-ups",
            json={
                "name": "x",
                "trigger": {"kind": "manual"},
                "steps": STEPS,
                "starter": "call_new_leads",
            },
            headers=t.headers,
        )
        assert twice.status_code == 409
        after = (await http.get("/v1/follow-ups/starters", headers=t.headers)).json()["items"]
        assert after[0]["available"] is False


async def test_another_account_never_sees_or_moves_a_follow_up() -> None:
    a, b = await _tenant(), await _tenant()
    async with _client() as http:
        made = await _create(http, a)
        for method, path in (
            ("GET", f"/v1/follow-ups/{made['id']}"),
            ("POST", f"/v1/follow-ups/{made['id']}/pause"),
            ("GET", f"/v1/follow-ups/{made['id']}/runs"),
            ("GET", f"/v1/follow-ups/{made['id']}/results"),
        ):
            response = await http.request(method, path, headers=b.headers)
            assert response.status_code == 404, (method, path, response.text)
        listed = (await http.get("/v1/follow-ups", headers=b.headers)).json()["items"]
        assert made["id"] not in {i["id"] for i in listed}


async def test_staff_reads_and_the_writes_need_dispatch() -> None:
    staff = await _tenant(role="staff")
    async with _client() as http:
        assert (await http.get("/v1/follow-ups", headers=staff.headers)).status_code == 200
        refused = await http.post(
            "/v1/follow-ups",
            json={"name": "x", "trigger": {"kind": "manual"}, "steps": STEPS},
            headers=staff.headers,
        )
        assert refused.status_code == 403, refused.text


async def test_every_write_is_audited() -> None:
    t = await _tenant()
    async with _client() as http:
        made = await _create(http, t)
        await _publish(http, t, made)
        await http.post(f"/v1/follow-ups/{made['id']}/pause", headers=t.headers)
    async with tenant_session(t.tenant_id) as session:
        actions = set(
            (
                await session.execute(
                    text("SELECT action FROM audit_log WHERE object_id = :o"), {"o": made["id"]}
                )
            ).scalars()
        )
    assert {"follow_up.created", "follow_up.published", "follow_up.paused"} <= actions
