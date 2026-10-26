"""Questions to answer (D-893 lane L5): one list, answered through the teach path.

Each test names the failure it guards against: a question asked twice under two names, a
practice or setup question asked when the business already said it, a draft offered with no
source or written from stale inputs, a model call in the request, an answer that never
reaches the agents or leaves the gaps open, and a neighbour's rows.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, cast

import pytest
from apps.api.agents import test_conversations
from apps.api.core.errors import ProblemError
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.insights import service as gap_service
from apps.api.main import app
from apps.api.teach import facts as fact_store
from apps.api.teach import questions
from apps.workers import teach_questions as draft_worker
from apps.workers.script_assist import JsonAnswer
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements, create_org_with_receptionist


@dataclass(frozen=True)
class _Turn:
    speaker: Any
    text: str


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    created = await create_org_with_receptionist(
        name="Raghava Organics",
        slug=f"tq-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    # The fixture's account comes with a filled-in profile; these tests start from an
    # account that has told us nothing yet.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE business_profiles SET hours = '{}'::jsonb, branches = '[]'::jsonb, "
                "services = '[]'::jsonb"
            )
        )
    return tenant_id, uuid.UUID(str(created["agent_id"])), str(created["slug"])


async def _call(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'inbound', 'completed', now(), now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"tq-{call_id.hex}"},
        )
    return call_id


async def _gap(tenant_id: uuid.UUID, agent_id: uuid.UUID, caller: str) -> uuid.UUID:
    call_id = await _call(tenant_id, agent_id)
    await gap_service.record_call_gaps(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        turns=[_Turn("caller", caller), _Turn("agent", "Sorry, I don't know about that.")],
    )
    return call_id


async def _profile(tenant_id: uuid.UUID, **values: str) -> None:
    columns = ", ".join(values)
    params = ", ".join(f"CAST(:{k} AS jsonb)" for k in values)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                f"INSERT INTO business_profiles (id, tenant_id, {columns}, created_at, "
                f"updated_at) VALUES (:id, :tid, {params}, now(), now()) "
                "ON CONFLICT (tenant_id) DO UPDATE SET "
                + ", ".join(f"{k} = EXCLUDED.{k}" for k in values)
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, **values},
        )


async def _list(tenant_id: uuid.UUID, **kwargs: Any) -> questions.QuestionList:
    async with tenant_session(tenant_id) as session:
        return await questions.list_questions(session, tenant_id=tenant_id, **kwargs)


async def _owner(tenant_id: uuid.UUID) -> str:
    user_id = uuid.uuid4()
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
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return f"dev:client:{user_id}"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


# --- the list -------------------------------------------------------------------------


async def test_one_topic_is_one_question_across_agents_ranked_by_calls() -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _gap(tenant_id, agent_id, "How much is the chilli powder?")
    latest = await _gap(tenant_id, agent_id, "What is the price of turmeric?")
    await _gap(tenant_id, agent_id, "Do you deliver to Kukatpally?")
    found = await _list(tenant_id)
    keys = [q.key for q in found.items]
    assert keys.count("pricing") == 1
    pricing = next(q for q in found.items if q.key == "pricing")
    assert pricing.why == "callers" and pricing.callers == 2
    assert pricing.question == questions.TOPIC_QUESTIONS["pricing"]
    assert pricing.latest_call_id == latest
    # Most-asked first: two calls on prices before one on delivery.
    assert keys.index("pricing") < keys.index("delivery")


async def test_practice_and_setup_questions_appear_only_while_nothing_answers_them() -> None:
    tenant_id, _agent_id, _ = await _tenant()
    keys = {q.key: q.why for q in (await _list(tenant_id)).items}
    assert keys == {"pricing": "practice", "timings": "setup", "location": "setup"}

    await _profile(
        tenant_id,
        hours='{"mon": {"opens": "09:00", "closes": "18:00"}}',
        services='[{"name": "Chilli powder", "price_inr": "120"}]',
    )
    async with tenant_session(tenant_id) as session:
        await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=["The shop is on MG Road, opposite the bus stand."],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
        # The profile's priced service is what practice callers needed too (D-849).
        assert await test_conversations.missing_facts(session) == []
    assert (await _list(tenant_id)).items == []


async def test_an_agent_scope_narrows_the_callers_questions_only() -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _gap(tenant_id, agent_id, "Do you deliver to Kukatpally?")
    other = await _list(tenant_id, agent_id=uuid.uuid4())
    assert "delivery" not in {q.key for q in other.items}
    assert {q.why for q in other.items} == {"practice", "setup"}


# --- answering and dismissing -----------------------------------------------------------


async def test_answering_saves_a_fact_closes_every_gap_on_the_topic_and_republishes() -> None:
    tenant_id, agent_id, _ = await _tenant()
    await _gap(tenant_id, agent_id, "Do you deliver to Kukatpally?")
    async with tenant_session(tenant_id) as session:
        settled = await questions.answer_question(
            session,
            tenant_id=tenant_id,
            key="delivery",
            answer="We deliver across Hyderabad within two days.",
            saved_by=None,
            client_user_id=None,
            auto_approve=True,
        )
        assert settled.gaps_closed == 1 and settled.fact_id is not None
        origin = (
            await session.execute(
                text("SELECT origin FROM kb_facts WHERE id = :id"), {"id": settled.fact_id}
            )
        ).scalar()
        assert origin == "call_gap"
        status = (
            await session.execute(
                text("SELECT status FROM knowledge_gaps WHERE topic_key = 'delivery'")
            )
        ).scalar()
        assert status == "taught"
        # The facts source got a new version: that is how the next call carries it.
        versions = (
            await session.execute(
                text("SELECT count(*) FROM kb_sources WHERE name = :name"),
                {"name": fact_store.FACTS_SOURCE_NAME},
            )
        ).scalar()
        assert versions == 1
    assert "delivery" not in {q.key for q in (await _list(tenant_id)).items}

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as again:
            await questions.answer_question(
                session,
                tenant_id=tenant_id,
                key="delivery",
                answer="Twice.",
                saved_by=None,
                client_user_id=None,
                auto_approve=True,
            )
    assert again.value.code == "question_not_open"


async def test_a_dismissed_setup_question_stays_dismissed_until_a_caller_asks_it() -> None:
    tenant_id, agent_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await questions.dismiss_question(
            session,
            tenant_id=tenant_id,
            key="location",
            reason="We only take calls; there is no shop.",
            client_user_id=None,
        )
    assert "location" not in {q.key for q in (await _list(tenant_id)).items}
    await _gap(tenant_id, agent_id, "Where is your shop address?")
    asked = next(q for q in (await _list(tenant_id)).items if q.key == "location")
    assert asked.why == "callers" and asked.callers == 1


# --- drafts -------------------------------------------------------------------------------


async def test_a_read_queues_one_draft_per_inputs_and_none_without_a_change() -> None:
    tenant_id, _agent_id, _ = await _tenant()
    first = await _list(tenant_id, queue_drafts=True)
    assert all(q.drafting for q in first.items)
    again = await _list(tenant_id, queue_drafts=True)
    assert all(q.drafting for q in again.items)
    assert await _queued(tenant_id) == len(first.items)

    # A new fact changes the inputs, so each draft is queued again exactly once.
    async with tenant_session(tenant_id) as session:
        await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=["We sell only organic spices."],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
    await _list(tenant_id, queue_drafts=True)
    assert await _queued(tenant_id) == 2 * len(first.items)


async def _queued(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM outbox_messages WHERE job = :job "
                        "AND payload->>'tenant_id' = :tid"
                    ),
                    {"job": questions.DRAFT_JOB, "tid": str(tenant_id)},
                )
            ).scalar_one()
        )


def test_a_draft_is_kept_only_with_a_source_that_exists() -> None:
    sources = [questions.Source("profile", "Your business profile", "Hours: Mon 09:00-18:00")]
    grounded = draft_worker.parse_draft({"answer": " We open at 9. ", "source": 1}, sources)
    assert grounded is not None and grounded.answer == "We open at 9."
    assert grounded.source is sources[0]
    assert draft_worker.parse_draft({"answer": "We open at 9.", "source": 7}, sources) is None
    unsourced = draft_worker.parse_draft({"answer": "We open at 9.", "source": None}, sources)
    assert unsourced is not None and unsourced.answer is None
    empty = draft_worker.parse_draft({"answer": None, "source": None}, sources)
    assert empty is not None and empty.answer is None


async def test_the_worker_stores_a_grounded_draft_and_the_list_offers_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _agent_id, _ = await _tenant()
    await _profile(tenant_id, branches='[{"label": "Main", "address": "MG Road"}]')
    async with tenant_session(tenant_id) as session:
        await fact_store.add_facts(
            session,
            tenant_id=tenant_id,
            texts=["Chilli powder is 120 rupees for 250 g."],
            origin="taught",
            teaching_id=None,
            created_by=None,
            auto_approve=True,
        )
        # Prices are known now; only the hours question is left.
    listed = await _list(tenant_id, queue_drafts=True)
    assert [q.key for q in listed.items] == ["timings"]
    async with tenant_session(tenant_id) as session:
        fingerprint = (
            await session.execute(
                text("SELECT inputs_hash FROM teach_questions WHERE question_key = 'timings'")
            )
        ).scalar_one()

    seen: dict[str, str] = {}

    async def fake_ask_json(description: str, instruction: str, **kwargs: Any) -> Any:
        seen["prompt"] = description
        assert kwargs["gemini_only"] is True
        value = kwargs["parse"]({"answer": "Open 9 to 6.", "source": 1})
        return JsonAnswer(value=value, capability=cast(Any, _Capability()))

    class _Capability:
        available = True
        reason = None
        disclosure = None

    class _Leg:
        serves_dashboard = True

    async def no_meter(*args: Any, **kwargs: Any) -> None:
        return None

    monkeypatch.setattr(draft_worker, "ask_json", fake_ask_json)
    monkeypatch.setattr(draft_worker, "google_assist_leg", lambda: _Leg())
    monkeypatch.setattr(crm_assist, "meter_assist", no_meter)
    monkeypatch.setattr(crm_assist, "meter_earlier", no_meter)

    async def allowed(session: Any, *, tenant_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(draft_worker, "require_ai_assist", allowed)
    outcome = await draft_worker.draft_teach_question(
        {},
        {"tenant_id": str(tenant_id), "question_key": "timings", "inputs_hash": fingerprint},
    )
    assert outcome == "drafted"
    assert "When are you open?" in seen["prompt"]
    offered = (await _list(tenant_id)).items[0]
    assert offered.draft == "Open 9 to 6." and offered.draft_source_kind is not None
    assert offered.drafting is False

    # The same job delivered twice does nothing the second time.
    again = await draft_worker.draft_teach_question(
        {},
        {"tenant_id": str(tenant_id), "question_key": "timings", "inputs_hash": fingerprint},
    )
    assert again == "stale"


async def test_no_draft_without_sources_and_no_model_call(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, _agent_id, _ = await _tenant()
    await _list(tenant_id, queue_drafts=True)
    async with tenant_session(tenant_id) as session:
        fingerprint = (
            await session.execute(
                text("SELECT inputs_hash FROM teach_questions WHERE question_key = 'pricing'")
            )
        ).scalar_one()

    async def never(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no model call without a source")

    monkeypatch.setattr(draft_worker, "ask_json", never)
    outcome = await draft_worker.draft_teach_question(
        {},
        {"tenant_id": str(tenant_id), "question_key": "pricing", "inputs_hash": fingerprint},
    )
    assert outcome == "no_sources"
    pricing = next(q for q in (await _list(tenant_id)).items if q.key == "pricing")
    assert pricing.draft is None and pricing.drafting is False


# --- the routes and the neighbour ---------------------------------------------------------


async def test_the_routes_list_answer_and_dismiss_and_write_audit_rows() -> None:
    tenant_id, agent_id, slug = await _tenant()
    await _gap(tenant_id, agent_id, "Do you deliver to Kukatpally?")
    token = await _owner(tenant_id)
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        listed = await http.get(
            "/v1/teach/questions", headers=headers, params={"agent_id": str(agent_id)}
        )
        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert body["open_count"] == len(body["items"]) >= 1
        answered = await http.post(
            "/v1/teach/questions/delivery/answer",
            headers=headers,
            json={"answer": "Yes, across Hyderabad."},
        )
        assert answered.status_code == 200, answered.text
        assert answered.json()["gaps_closed"] == 1
        dismissed = await http.post(
            "/v1/teach/questions/location/dismiss",
            headers=headers,
            json={"reason": "No shop."},
        )
        assert dismissed.status_code == 200, dismissed.text
        unknown = await http.post(
            "/v1/teach/questions/no_such_topic/dismiss", headers=headers, json={}
        )
        assert unknown.status_code == 409
    async with tenant_session(tenant_id) as session:
        audits = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :tid "
                    "AND object_type = 'teach_question' ORDER BY created_at"
                ),
                {"tid": tenant_id},
            )
        ).all()
    assert [a[0] for a in audits] == ["teach_question.answer", "teach_question.dismiss"]


async def test_a_neighbour_sees_none_of_the_rows() -> None:
    tenant_id, _agent_id, _ = await _tenant()
    neighbour, _n_agent, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await questions.dismiss_question(
            session, tenant_id=tenant_id, key="location", reason=None, client_user_id=None
        )
    async with tenant_session(neighbour) as session:
        rows = (await session.execute(text("SELECT count(*) FROM teach_questions"))).scalar()
    assert rows == 0
    assert "location" in {q.key for q in (await _list(neighbour)).items}
