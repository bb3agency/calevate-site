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
            knowledge_items=3,
            open_gaps=2,
            opening_chars=OPENING_LINE_MAX_CHARS + 1,
            draft_waiting=True,
            missed_7d=3,
        ),
        now=NOW,
    )
    assert _points(out) == {
        "knowledge": 22,  # (5 for 1-4 items + (10 - 2*2)) * 40 / 20
        "opening": 7,  # set, but too long to be spoken
        "live": 13,  # live, with a draft waiting
        "missed": 6,  # 15 - 3*3
    }
    assert out.score == 48


def test_components_never_go_negative() -> None:
    out = readiness.score(replace(FULL, open_gaps=9, missed_7d=40), now=NOW)
    points = _points(out)
    assert points["knowledge"] == 20  # (10 for stock + max(0, 10 - 18)) * 40 / 20
    assert points["missed"] == 0


def test_an_opening_line_that_does_not_fit_the_greeting_budget_loses_points() -> None:
    out = readiness.score(replace(FULL, opening_chars=50, opening_room=40), now=NOW)
    assert _points(out)["opening"] == 7


def test_fixes_come_biggest_first_with_ties_in_component_order() -> None:
    empty = readiness.ReadinessInputs(
        agent_id=AGENT,
        agent_name="New",
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
    # knowledge: no gaps, 10 * 40 / 20 = 20; missed 15; not live costs nothing (D-916)
    assert out.score == 60
    assert [(f.component, f.points) for f in out.fixes] == [
        ("knowledge", 20),
        ("opening", 20),
    ]
    assert out.fixes[0].href == "/knowledge"
    assert _points(out)["live"] == 25


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
    assert points["knowledge"] == 30  # (one fact (5) + no open gaps (10)) * 40 / 20
    assert body["score"] == sum(points.values())
    assert account.status_code == 200
    assert account.json()["score"] == body["score"]
    assert [a["agent_id"] for a in account.json()["agents"]] == [str(agent_id)]
    assert neighbour.status_code == 404


async def test_a_saved_file_with_no_text_for_the_agents_is_not_counted_as_knowledge() -> None:
    """A PDF or a link is saved but reaches the agents as empty text until D-868; only a
    source with text to send raises the knowledge score."""
    tenant_id, _slug, _token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        before = await readiness.knowledge_items(session)
        empty, read = uuid7(), uuid7()
        for source_id, name in ((empty, "Price list.pdf"), (read, "Price list.docx")):
            await session.execute(
                text(
                    "INSERT INTO kb_sources (id, tenant_id, kind, name, status, version, "
                    "is_active, created_at, updated_at) VALUES (:i, :t, 'file', :n, 'approved', 1, "
                    "true, now(), now())"
                ),
                {"i": source_id, "t": tenant_id, "n": name},
            )
        await session.execute(
            text(
                "INSERT INTO kb_documents (id, tenant_id, source_id, idx, title, content, "
                "created_at, updated_at) VALUES (:id, :tid, :sid, 0, 'Prices', "
                "'A 2BHK starts at 60 lakh.', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "sid": read},
        )
        assert await readiness.knowledge_items(session) == before + 1


async def test_what_the_business_profile_offers_and_answers_counts_as_knowledge() -> None:
    """Services and common questions live in the business profile (D-968), so a client who
    filled it in is not told to add them again; another account's profile counts for nothing
    here (hard rule 1)."""
    tenant_a, _slug_a, _token_a = await _make_tenant()
    tenant_b, _slug_b, _token_b = await _make_tenant()
    async with tenant_session(tenant_b) as session:
        before_b = await readiness.knowledge_items(session)
    async with tenant_session(tenant_a) as session:
        before = await readiness.knowledge_items(session)
        await session.execute(
            text(
                "INSERT INTO business_profiles (id, tenant_id) VALUES (:id, :tid) "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {"id": uuid7(), "tid": tenant_a},
        )
        await session.execute(
            text(
                "UPDATE business_profiles SET services = CAST(:s AS jsonb), "
                "faqs = CAST(:f AS jsonb) WHERE tenant_id = :tid"
            ),
            {
                "s": '[{"name": "Haircut", "price_inr": "150", "notes": null}, '
                '{"name": "Shave", "price_inr": null, "notes": null}]',
                "f": '[{"question": "Do you open on Sunday?", "answer": "No."}]',
                "tid": tenant_a,
            },
        )
        assert await readiness.knowledge_items(session) == before + 3
    async with tenant_session(tenant_b) as session:
        assert await readiness.knowledge_items(session) == before_b


def test_the_knowledge_fix_names_no_service_or_price() -> None:
    out = readiness.score(replace(FULL, knowledge_items=0), now=NOW)
    fix = next(f for f in out.fixes if f.component == "knowledge")
    assert fix.href == "/knowledge"
    assert "service" not in fix.action.lower() and "price" not in fix.action.lower()
