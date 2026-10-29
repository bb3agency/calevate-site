"""Pip speaks up on its own (D-936): each detector fires on its data and stays quiet without it,
one note per episode, the daily cap, the routes, the sweep, and tenant isolation (hard rule 1).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.billing.wallet import Runway
from apps.api.copilot import notes
from apps.api.copilot.notes import Thresholds, run_detectors
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.tenancy.models import PROFILE_STEPS
from apps.workers import pip_notes
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.conftest import COMPLETE_PROFILE, fund_wallet, seed_business_profile

LIMITS = Thresholds(
    hot_lead_hours=4, runway_days=5, gap_repeat_calls=3, good_week_percent=20, daily_cap=3
)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _agent(tenant_id: UUID) -> UUID:
    async with tenant_session(tenant_id) as session:
        return UUID(
            str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one())
        )


async def _hot_lead(tenant_id: UUID, *, hours_ago: float) -> UUID:
    agent_id = await _agent(tenant_id)
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "status_set_at, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, 'Asha', "
                "'inbound_call', 'hot', :at, :at, :at)"
            ),
            {
                "id": lead_id,
                "tid": tenant_id,
                "aid": agent_id,
                "phone": f"+9190000{uuid.uuid4().int % 100000:05d}",
                "at": datetime.now(UTC) - timedelta(hours=hours_ago),
            },
        )
    return lead_id


async def _call(
    tenant_id: UUID, *, at: datetime, lead_id: UUID | None = None, status: str = "completed"
) -> UUID:
    agent_id = await _agent(tenant_id)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, lead_id, engine_call_id, direction, "
                "status, started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :lid, :e, "
                "'outbound', :status, :at, :at, :at)"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "lid": lead_id,
                "e": f"pn-{call_id.hex}",
                "status": status,
                "at": at,
            },
        )
    return call_id


async def _run(tenant_id: UUID, limits: Thresholds = LIMITS) -> dict[str, int]:
    async with tenant_session(tenant_id) as session:
        return await run_detectors(session, tenant_id=tenant_id, thresholds=limits)


async def _notes(tenant_id: UUID) -> list[tuple[str, str, Any, Any, Any]]:
    async with tenant_session(tenant_id) as session:
        rows = await session.execute(
            text(
                "SELECT kind, subject, payload, resolved_at, dismissed_at FROM copilot_notes "
                "ORDER BY created_at"
            )
        )
        return [(str(r[0]), str(r[1]), r[2], r[3], r[4]) for r in rows.all()]


# --- hot leads nobody called back -----------------------------------------------------------


async def test_a_hot_lead_left_waiting_is_noted_once_and_resolved_by_a_call() -> None:
    """FAILS IF: a hot lead past the threshold with no call goes unnoticed, a fresh one is
    noted, a second run opens a second note for the same episode, or the call back leaves
    the note open."""
    tenant_id, _, _ = await _make_tenant()
    await _hot_lead(tenant_id, hours_ago=1)
    assert (await _run(tenant_id))["opened"] == 0, "a lead marked hot an hour ago is not waiting"

    waiting = await _hot_lead(tenant_id, hours_ago=6)
    first = await _run(tenant_id)
    second = await _run(tenant_id)
    assert first["opened"] == 1
    assert second["opened"] == 0, "the same episode must not be noted twice"
    rows = await _notes(tenant_id)
    assert [(r[0], r[1]) for r in rows] == [("hot_lead_waiting", "account")]
    assert rows[0][2]["count"] == 1 and rows[0][2]["lead_ids"] == [str(waiting)]

    await _call(tenant_id, at=datetime.now(UTC), lead_id=waiting)
    assert (await _run(tenant_id))["resolved"] == 1
    assert (await _notes(tenant_id))[0][3] is not None


# --- credit forecast ------------------------------------------------------------------------


def _projected(days: int) -> Any:
    async def read_runway(*_: Any, **__: Any) -> tuple[Runway, None]:
        return (
            Runway(
                basis="projected",
                days=days,
                daily_burn_inr=None,
                history_days=30,
                beyond_horizon=False,
            ),
            None,
        )

    return read_runway


async def test_credit_running_out_soon_is_noted_and_a_long_runway_is_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a projection inside the threshold is not noted, or one beyond it is."""
    tenant_id, _, _ = await _make_tenant()
    await fund_wallet(tenant_id, "5000.00")
    monkeypatch.setattr(notes, "read_runway", _projected(30))
    assert (await _run(tenant_id))["opened"] == 0
    monkeypatch.setattr(notes, "read_runway", _projected(3))
    assert (await _run(tenant_id))["opened"] == 1
    rows = await _notes(tenant_id)
    assert rows[0][0] == "balance_runway" and rows[0][2] == {"days": 3}


async def test_credit_below_the_low_line_is_left_to_the_attention_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: Pip repeats the low-credit warning the queue and the emails already give."""
    tenant_id, _, _ = await _make_tenant()
    await fund_wallet(tenant_id, "10.00")
    monkeypatch.setattr(notes, "read_runway", _projected(1))
    assert (await _run(tenant_id))["opened"] == 0


# --- one unanswered question asked again and again ------------------------------------------


async def _gap(tenant_id: UUID, *, calls: int, topic: str = "timings") -> UUID:
    agent_id = await _agent(tenant_id)
    gap_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO knowledge_gaps (id, tenant_id, agent_id, topic_key, topic_label, "
                "status, occurrence_count, call_count, example_question_redacted, "
                "example_answer_redacted, top_signal, first_seen_at, last_seen_at, created_at, "
                "updated_at) VALUES (:id, :t, :a, :topic, 'opening hours', 'open', :n, :n, "
                "'When do you open?', 'not sure', 'dont_know', now(), now(), now(), now())"
            ),
            {"id": gap_id, "t": tenant_id, "a": agent_id, "topic": topic, "n": calls},
        )
    for _ in range(calls):
        call_id = await _call(tenant_id, at=datetime.now(UTC))
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO knowledge_gap_occurrences (id, tenant_id, agent_id, call_id, "
                    "topic_key, topic_label, question_redacted, answer_redacted, signal, "
                    "hit_count, created_at, updated_at) VALUES (:id, :t, :a, :c, :topic, "
                    "'opening hours', 'When do you open?', 'not sure', 'dont_know', 1, now(), "
                    "now())"
                ),
                {"id": uuid7(), "t": tenant_id, "a": agent_id, "c": call_id, "topic": topic},
            )
    return gap_id


async def test_a_repeated_unanswered_question_is_noted_unless_setup_already_says_it() -> None:
    """FAILS IF: a gap asked on enough calls is not noted once setup covers its step, or one
    whose setup step is unfinished is noted on top of the checklist's own nudge, or a gap
    asked too few times is noted."""
    unfinished, _, _ = await _make_tenant()
    await _gap(unfinished, calls=3)
    assert (await _run(unfinished))["opened"] == 0, "the setup checklist already says this"

    finished, _, _ = await _make_tenant()
    await seed_business_profile(finished, COMPLETE_PROFILE)
    async with tenant_session(finished) as session:
        await session.execute(
            text(
                "UPDATE business_profiles SET setup_steps = CAST(:s AS jsonb) "
                "WHERE tenant_id = :tid"
            ),
            {"s": json.dumps(dict.fromkeys(PROFILE_STEPS, "done")), "tid": finished},
        )
    await _gap(finished, calls=2)
    assert (await _run(finished))["opened"] == 0, "two calls is below the threshold"
    gap_id = await _gap(finished, calls=3, topic="location")
    assert (await _run(finished))["opened"] == 1
    rows = await _notes(finished)
    assert rows[0][0] == "knowledge_gap_repeat" and rows[0][1] == str(gap_id)
    assert rows[0][2] == {"gap_id": str(gap_id), "calls": 3}


# --- a good week ------------------------------------------------------------------------------


async def test_a_good_week_is_noted_once_and_a_flat_week_is_not() -> None:
    """FAILS IF: calls and leads both well up is not noted, a flat week is, or the good week
    is noted twice."""
    tenant_id, _, _ = await _make_tenant()
    now = datetime.now(UTC)
    for _ in range(3):
        await _call(tenant_id, at=now - timedelta(days=9))
    assert (await _run(tenant_id))["opened"] == 0, "fewer calls than last week is not good"
    for _ in range(12):
        await _call(tenant_id, at=now - timedelta(hours=2))
    await _hot_lead(tenant_id, hours_ago=1)  # a second new lead this week
    first = await _run(tenant_id)
    second = await _run(tenant_id)
    assert first["opened"] == 1 and second["opened"] == 0
    kinds = [r[0] for r in await _notes(tenant_id)]
    assert kinds == ["good_week"]


# --- the daily cap and pruning ----------------------------------------------------------------


async def test_new_notes_stop_at_the_daily_cap_most_urgent_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an account gets more new notes in a day than the cap, or the cap is spent on
    a less urgent kind first."""
    tenant_id, _, _ = await _make_tenant()
    await fund_wallet(tenant_id, "5000.00")
    monkeypatch.setattr(notes, "read_runway", _projected(2))
    await _hot_lead(tenant_id, hours_ago=8)
    capped = Thresholds(
        hot_lead_hours=4, runway_days=5, gap_repeat_calls=3, good_week_percent=20, daily_cap=1
    )
    counts = await _run(tenant_id, capped)
    assert counts["opened"] == 1 and counts["capped"] >= 1
    assert [r[0] for r in await _notes(tenant_id)] == ["hot_lead_waiting"]
    assert (await _run(tenant_id, capped))["opened"] == 0, "the cap holds for the rest of the day"


# --- the routes -------------------------------------------------------------------------------


async def test_the_panel_reads_marks_seen_and_dismisses_and_a_dismissed_note_stays_away() -> None:
    """FAILS IF: the route does not return the note with an in-app screen button, the
    launcher count does not drop when seen, or a dismissed note comes back on the next run
    while its condition still holds."""
    tenant_id, slug, token = await _make_tenant()
    await _hot_lead(tenant_id, hours_ago=6)
    await _run(tenant_id)
    headers = _headers(token, slug)
    async with _client() as http:
        read = (await http.get("/v1/copilot/notes", headers=headers)).json()
        mine = [n for n in read["notes"] if n["source"] == "pip"]
        assert read["unread"] == 1 and len(mine) == 1
        note = mine[0]
        assert note["button"] == {
            "kind": "open",
            "label": "Open leads",
            "screen": "Leads",
            "route": "/c/{slug}/leads",
            "prompt": None,
        }
        assert "Asha" not in note["line"] and "+91" not in note["line"]
        assert (await http.post("/v1/copilot/notes/seen", headers=headers)).status_code == 200
        assert (await http.get("/v1/copilot/notes", headers=headers)).json()["unread"] == 0
        acted = await http.post(f"/v1/copilot/notes/{note['id']}/acted", headers=headers)
        assert acted.status_code == 200
        gone = await http.post(f"/v1/copilot/notes/{note['id']}/dismiss", headers=headers)
        assert gone.status_code == 200
        again = await http.post(f"/v1/copilot/notes/{note['id']}/dismiss", headers=headers)
        assert again.status_code == 404
    assert (await _run(tenant_id))["opened"] == 0, "dismissed while the lead still waits"
    async with _client() as http:
        after = (await http.get("/v1/copilot/notes", headers=headers)).json()
    assert [n for n in after["notes"] if n["source"] == "pip"] == []


async def test_a_linked_item_is_the_attention_queues_own_count_and_cannot_be_dismissed() -> None:
    """FAILS IF: low credit is copied into a stored note rather than read from the queue."""
    tenant_id, slug, token = await _make_tenant()
    await fund_wallet(tenant_id, "10.00")
    async with _client() as http:
        read = (await http.get("/v1/copilot/notes", headers=_headers(token, slug))).json()
    linked = [n for n in read["notes"] if n["id"] == "linked:credit_low"]
    assert len(linked) == 1 and linked[0]["dismissible"] is False
    assert linked[0]["button"]["route"] == "/c/{slug}/billing"
    assert await _notes(tenant_id) == []


# --- isolation --------------------------------------------------------------------------------


async def test_another_account_reads_zero_notes() -> None:
    """FAILS IF: one tenant's session or route can see another tenant's notes (hard rule 1)."""
    owner, _, _ = await _make_tenant()
    await _hot_lead(owner, hours_ago=6)
    await _run(owner)
    other, other_slug, other_token = await _make_tenant()
    async with tenant_session(other) as session:
        count = (await session.execute(text("SELECT count(*) FROM copilot_notes"))).scalar_one()
    assert count == 0
    async with untenanted_session() as session:
        bare = (await session.execute(text("SELECT count(*) FROM copilot_notes"))).scalar_one()
    assert bare == 0
    async with _client() as http:
        read = (
            await http.get("/v1/copilot/notes", headers=_headers(other_token, other_slug))
        ).json()
    assert [n for n in read["notes"] if n["source"] == "pip"] == []


# --- the sweep --------------------------------------------------------------------------------


async def test_the_sweep_queues_one_keyed_job_per_open_account_and_stops_when_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the hourly pass does not queue a keyed per-account job, or runs while the
    config row has switched notes off."""
    tenant_id, _, _ = await _make_tenant()
    queued: list[tuple[str, str, str | None]] = []

    async def enqueue(job: str, *args: Any, job_id: str | None = None, **_: Any) -> str:
        queued.append((job, str(args[0]), job_id))
        return job_id or ""

    monkeypatch.setattr(pip_notes, "enqueue", enqueue)
    await pip_notes.sweep_pip_notes({})
    mine = [q for q in queued if q[1] == str(tenant_id)]
    assert len(mine) == 1 and mine[0][0] == "detect_pip_notes"
    assert mine[0][2] is not None and str(tenant_id) in mine[0][2]

    class Off:
        pip_notes_enabled = False

    monkeypatch.setattr(pip_notes, "get_settings", lambda: Off())
    queued.clear()
    await pip_notes.sweep_pip_notes({})
    assert queued == []


async def test_the_job_runs_the_detectors_in_the_accounts_own_session() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _hot_lead(tenant_id, hours_ago=30)
    await pip_notes.detect_pip_notes({}, str(tenant_id))
    assert [r[0] for r in await _notes(tenant_id)] == ["hot_lead_waiting"]
