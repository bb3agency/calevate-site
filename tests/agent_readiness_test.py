"""The agent readiness score (D-870, weights D-873): the formula, and the reads behind the gauge.

The formula is pure (`readiness.score`), so its arithmetic is pinned without a database;
the DB half proves `gather` reads the right rows and that one account never reads
another's agent (hard rule 1).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from apps.api.agents import readiness
from apps.api.agents.call_rules import OPENING_LINE_MAX_CHARS
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

NOW = datetime(2026, 10, 24, 6, 30, tzinfo=UTC)
AGENT = uuid.UUID("01890000-0000-7000-8000-000000000001")

FULL = readiness.ReadinessInputs(
    agent_id=AGENT,
    agent_name="Reception",
    tests_passed=10,
    tests_counted=10,
    has_test_run=True,
    knowledge_items=8,
    open_gaps=0,
    opening_chars=60,
    opening_room=100,
    published=True,
    live=True,
    draft_waiting=False,
    out_of_sync=False,
    missed_7d=0,
)


def _points(out: readiness.AgentReadinessOut) -> dict[str, int]:
    return {c.key: c.points for c in out.components}


def test_the_maximum_is_one_hundred_and_needs_no_fixes() -> None:
    out = readiness.score(FULL, now=NOW)
    assert out.score == 100 == sum(readiness.MAX_POINTS.values())
    assert out.fixes == []
    assert all(c.state == "full" for c in out.components)


def test_each_component_follows_its_rule() -> None:
    out = readiness.score(
        replace(
            FULL,
            tests_passed=7,
            tests_counted=10,
            knowledge_items=3,
            open_gaps=2,
            opening_chars=OPENING_LINE_MAX_CHARS + 1,
            draft_waiting=True,
            missed_7d=3,
        ),
        now=NOW,
    )
    assert _points(out) == {
        "tests": 25,  # 35 * 7 / 10 = 24.5, half up
        "knowledge": 14,  # (5 for 1-4 items + (10 - 2*2)) * 25 / 20 = 13.75
        "opening": 5,  # set, but too long to be spoken
        "live": 8,  # live, with a draft waiting
        "missed": 4,  # 10 - 2*3
    }
    assert out.score == 56


def test_half_points_round_up_and_components_never_go_negative() -> None:
    out = readiness.score(
        replace(FULL, tests_passed=1, tests_counted=2, open_gaps=9, missed_7d=40), now=NOW
    )
    points = _points(out)
    assert points["tests"] == 18  # 17.5 rounds half up
    assert points["knowledge"] == 13  # (10 for stock + max(0, 10 - 18)) * 25 / 20 = 12.5
    assert points["missed"] == 0


def test_an_opening_line_that_does_not_fit_the_greeting_budget_loses_points() -> None:
    out = readiness.score(replace(FULL, opening_chars=50, opening_room=40), now=NOW)
    assert _points(out)["opening"] == 5


def test_fixes_come_biggest_first_with_ties_in_component_order() -> None:
    empty = readiness.ReadinessInputs(
        agent_id=AGENT,
        agent_name="New",
        tests_passed=0,
        tests_counted=0,
        has_test_run=False,
        knowledge_items=0,
        open_gaps=0,
        opening_chars=0,
        opening_room=None,
        published=False,
        live=False,
        draft_waiting=False,
        out_of_sync=False,
        missed_7d=0,
    )
    out = readiness.score(empty, now=NOW)
    assert out.score == 23  # knowledge: no gaps, 10 * 25 / 20 = 12.5 → 13; missed 10
    assert [(f.component, f.points) for f in out.fixes] == [
        ("tests", 35),
        ("opening", 15),
        ("live", 15),
        ("knowledge", 12),
    ]
    assert out.fixes[0].href == f"/agents/{AGENT}?section=training"
    assert out.fixes[3].href == "/knowledge"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def test_the_reads_score_the_stored_agent_and_stay_inside_the_account() -> None:
    tenant_a, slug_a, token_a = await _make_tenant()
    _tenant_b, slug_b, token_b = await _make_tenant()
    async with tenant_session(tenant_a) as session:
        agent_id = uuid.UUID(
            str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar())
        )
        await session.execute(
            text(
                "INSERT INTO kb_facts (id, tenant_id, text, origin, created_at, updated_at) "
                "VALUES (:id, :tid, 'We open at 9am.', 'taught', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_a},
        )

    headers_a = {"Authorization": f"Bearer {token_a}", "X-Org-Slug": slug_a}
    headers_b = {"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_b}
    async with _client() as http:
        one = await http.get(f"/v1/agents/{agent_id}/readiness", headers=headers_a)
        account = await http.get("/v1/readiness", headers=headers_a)
        neighbour = await http.get(f"/v1/agents/{agent_id}/readiness", headers=headers_b)

    assert one.status_code == 200, one.text
    body = one.json()
    points = {c["key"]: c["points"] for c in body["components"]}
    assert set(points) == set(readiness.MAX_POINTS)
    assert points["knowledge"] == 19  # (one fact (5) + no open gaps (10)) * 25 / 20 = 18.75
    assert points["tests"] == 0
    assert body["score"] == sum(points.values())
    assert account.status_code == 200
    assert account.json()["score"] == body["score"]
    assert [a["agent_id"] for a in account.json()["agents"]] == [str(agent_id)]
    assert neighbour.status_code == 404
