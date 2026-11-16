"""'Just the business': the agent page tries an agent with no job's script (founder, 16 Nov 2026).

An agent is staff with no script of its own; its words are written on an Inbound line or a
campaign. Try it on the agent page tries it on "just the business" through its developer-
workspace test copy, composed from the company training and the knowledge with every platform
layer around it (`agents/business_only`), or links to a job's own test call. The agent's jobs
are read for that list, for the Overview's "Give it a job" step and for the readiness score.

Driven through the real paths on the shared fake engine: `publish_agent(onto_test_copy=True,
business_only=True)`, `kb.service._publish_config`, `try_chat.send`, `place_trial_call`, the
copies sweep, `GET /v1/agents/{id}/jobs` and `POST /v1/agents`.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import business_only, paid_test_calls, readiness, trial_calls
from apps.api.agents.service import AgentRow
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.engine import get_engine
from apps.api.engine.fake import FakeEngine
from apps.api.kb import service as kb_service
from apps.api.main import app
from apps.api.teach import try_chat
from apps.workers import agent_moves
from calevate_shared.call_script import CallScript, compile_call_script
from calevate_shared.engine import (
    CONFIDENTIALITY_MARKER,
    TRUTHFUL_ANSWER_MARKER,
    compose_engine_prompt,
)
from calevate_shared.opening_notices import OpeningNotices
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.kb_workflow_test import _tenant_with_published_agent
from tests.trial_call_placement_test import Line, _account, line  # noqa: F401

pytestmark = [pytest.mark.rls]

TRAINING = "We are a family clinic. Speak warmly and use the caller's name."
#: The fixture agent's own script (`kb_workflow_test.give_agent_a_script`).
OWN_SCRIPT = "You are the receptionist for this clinic."


def _engine() -> FakeEngine:
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    return engine


async def _with_training(tenant_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO company_trainings (id, tenant_id, training) VALUES (:i, :t, :tr) "
                "ON CONFLICT (tenant_id) DO UPDATE SET training = EXCLUDED.training"
            ),
            {"i": uuid7(), "t": tenant_id, "tr": TRAINING},
        )


async def _copy(tenant_id: UUID) -> tuple[str, bool]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT engine_agent_ref, business_only FROM agent_test_copies")
            )
        ).one()
    return str(row[0]), bool(row[1])


# --- what the holder holds ----------------------------------------------------------------


def _row(**over: Any) -> AgentRow:
    base: dict[str, Any] = {
        "id": uuid.uuid4(),
        "name": "Anjali",
        "language_primary": "en-IN",
        "business_name": "Sunrise Clinic",
        "prompt": None,
        "structured_script": None,
        "ai_disclosure_line": "I am an AI assistant.",
        "ai_disclosure_enabled": False,
        "recording_notice_line": "This call is recorded.",
        "recording_notice_enabled": False,
        "caller_memory_notice_line": "I keep a short note of this call.",
        "caller_memory_enabled": False,
        "disclosure_line": None,
    }
    base.update(over)
    return base  # type: ignore[return-value]


def test_the_agent_keeps_its_opening_and_who_it_is_and_drops_the_job() -> None:
    opening = "Hello, I am Anjali, an AI assistant."
    notices = OpeningNotices(ai="I am Anjali, an AI assistant.", line=opening)
    own = CallScript(
        schema_version=2,
        identity="You are Anjali.",
        opening_line=opening,
        opening_notices=notices,
        goal="Book a site visit for every caller.",
    )
    script = business_only.business_script(_row(structured_script=own.model_dump(mode="json")))
    assert script.opening_line == opening
    assert script.opening_notices == notices, "the woven notice words travel with their line"
    assert script.identity == "You are Anjali."
    body = compile_call_script(script)
    assert "site visit" not in body, "the job's main task is not the agent's"


def test_an_agent_with_no_opening_of_its_own_opens_as_a_call_it_places() -> None:
    script = business_only.business_script(_row())
    assert script.opening_line.strip(), "a test call never opens on silence"
    assert "Sunrise Clinic" in script.opening_line


async def test_the_copy_holds_the_training_and_no_script_inside_every_platform_layer() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _with_training(tenant_id)

    ref = await paid_test_calls.refresh_test_copy(
        tenant_id=tenant_id, agent_id=agent_id, business=True
    )

    cfg = _engine()._agents[ref]
    assert TRAINING in cfg.system_prompt
    assert OWN_SCRIPT not in cfg.system_prompt
    composed = compose_engine_prompt(cfg)
    assert CONFIDENTIALITY_MARKER in composed
    assert TRUTHFUL_ANSWER_MARKER in composed
    assert await _copy(tenant_id) == (ref, True)
    async with tenant_session(tenant_id) as session:
        own_prompt = (
            await session.execute(
                text(
                    "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.live_prompt_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar()
    assert OWN_SCRIPT in str(own_prompt), "the agent's own script is not touched"


async def test_a_knowledge_attach_resends_whichever_config_the_copy_was_last_published_as() -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    await _with_training(tenant_id)
    await paid_test_calls.refresh_test_copy(tenant_id=tenant_id, agent_id=agent_id, business=True)
    async with tenant_session(tenant_id) as session:
        attach = await kb_service._publish_config(session, tenant_id, agent_id, test_copy=True)
    assert OWN_SCRIPT not in attach.system_prompt and TRAINING in attach.system_prompt

    # A campaign's test call on a paying account puts the agent itself on the same copy.
    ref = await paid_test_calls.refresh_test_copy(tenant_id=tenant_id, agent_id=agent_id)
    assert await _copy(tenant_id) == (ref, False)
    async with tenant_session(tenant_id) as session:
        attach = await kb_service._publish_config(session, tenant_id, agent_id, test_copy=True)
    assert OWN_SCRIPT in attach.system_prompt


# --- chatting and calling with it -------------------------------------------------------


async def test_the_business_chat_talks_to_the_copy_and_keeps_its_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant_with_published_agent()
    seen: list[tuple[str, str | None]] = []

    async def _nothing(*_a: Any, **_k: Any) -> None:
        return None

    async def _send(_engine: Any, *, engine_agent_ref: str, session: str | None, **_k: Any) -> Any:
        seen.append((engine_agent_ref, session))
        return type(
            "Turn", (), {"session": "s-1", "reply": "Hello.", "tools": (), "failed_part_way": False}
        )()

    # The fake engine has no test chat; the chat's own port is what is replaced.
    monkeypatch.setattr(try_chat, "RunsTestChat", object)
    monkeypatch.setattr(try_chat, "require_ai_assist", _nothing)
    monkeypatch.setattr(try_chat, "send_test_message", _send)
    async with tenant_session(tenant_id) as session:
        await try_chat.send(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            message="When are you open?",
            chat_session=None,
            business=True,
        )
        copy_ref, business = await _copy(tenant_id)
        await try_chat.send(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            message="And on Sunday?",
            chat_session="s-1",
            business=True,
        )
    assert business
    assert seen == [(copy_ref, None), (copy_ref, "s-1")]


async def test_a_business_call_rings_through_the_copy_on_the_shared_line(
    line: Line,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, principal = await _account(line)
    asked: list[dict[str, Any]] = []

    async def _refresh(**kwargs: Any) -> str:
        asked.append(kwargs)
        return "fakeagent_business_copy"

    monkeypatch.setattr(trial_calls, "refresh_test_copy", _refresh)
    async with tenant_session(tenant_id) as session:
        placed = await trial_calls.place_trial_call(
            session,
            principal=principal,
            agent_id=agent_id,
            number="98765 43210",
            idempotency_key=str(uuid.uuid4()),
            business=True,
        )
    assert placed.status == "queued", placed
    assert asked == [{"tenant_id": tenant_id, "agent_id": agent_id, "business": True}]
    assert line.lent_to == ["fakeagent_business_copy"]


async def test_the_sweep_keeps_a_business_copy_once_the_client_has_a_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    retired: list[str] = []
    async with tenant_session(tenant_id) as session:
        agents = [
            UUID(str(a))
            for a in (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalars()
        ]
        second = await _second_agent(session, tenant_id)
        kept_for_calls, business_copy = (
            f"ref_agent_{uuid.uuid4().hex}",
            f"ref_biz_{uuid.uuid4().hex}",
        )
        for agent_id, ref, business in (
            (agents[0], kept_for_calls, False),
            (second, business_copy, True),
        ):
            await session.execute(
                text(
                    "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref, "
                    "business_only) VALUES (:i, :t, :a, :r, :b)"
                ),
                {"i": uuid7(), "t": tenant_id, "a": agent_id, "r": ref, "b": business},
            )

        async def _retire(_session: Any, *, ref: str, **_k: Any) -> None:
            retired.append(ref)

        import apps.api.agents.service as agents_service

        monkeypatch.setattr(agents_service, "retire_engine_agent", _retire)
        monkeypatch.setattr(agent_moves, "_OWN_NUMBERS_SQL", "SELECT 'num@org_own'")
        monkeypatch.setattr(agent_moves, "scope_of", lambda _ref: "org_own")
        await agent_moves._retire_test_copies(session, tenant_id=tenant_id, workspace="org_own")
    assert retired == [kept_for_calls]


async def _second_agent(session: Any, tenant_id: UUID) -> UUID:
    from apps.api.agents import lifecycle

    return await lifecycle.create_agent(
        session, tenant_id=tenant_id, name="Second", direction="both", language_primary="en-IN"
    )


# --- the agent's jobs -------------------------------------------------------------------


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def test_its_jobs_are_its_lines_and_open_campaigns_and_stay_inside_the_account() -> None:
    tenant_a, slug_a, token_a = await _make_tenant()
    _tenant_b, slug_b, token_b = await _make_tenant()
    headers_a = {"Authorization": f"Bearer {token_a}", "X-Org-Slug": slug_a}
    headers_b = {"Authorization": f"Bearer {token_b}", "X-Org-Slug": slug_b}
    async with tenant_session(tenant_a) as session:
        agent_id = UUID(
            str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar())
        )
        before = await readiness.agent_readiness(session, agent_id)
    async with _client() as http:
        empty = await http.get(f"/v1/agents/{agent_id}/jobs", headers=headers_a)
        made = await http.post(
            "/v1/inbound-lines", json={"agent_id": str(agent_id)}, headers=headers_a
        )
        one = await http.get(f"/v1/agents/{agent_id}/jobs", headers=headers_a)
        neighbour = await http.get(f"/v1/agents/{agent_id}/jobs", headers=headers_b)
    assert empty.status_code == 200 and empty.json()["total"] == 0, empty.text
    assert made.status_code in (200, 201), made.text
    body = one.json()
    assert body["total"] == 1
    assert body["jobs"] == [
        {
            "kind": "inbound_line",
            "id": made.json()["id"],
            "name": made.json()["name"],
            "status": "draft",
        }
    ]
    assert neighbour.status_code == 404

    job_before = next(c for c in before.components if c.key == "job")
    assert job_before.points == 0
    async with tenant_session(tenant_a) as session:
        after = await readiness.agent_readiness(session, agent_id)
    assert next(c for c in after.components if c.key == "job").points == readiness.MAX_POINTS["job"]
    assert not any(f.component == "job" for f in after.fixes)


# --- a new agent with no script ---------------------------------------------------------


async def _create(token: str, slug: str, name: str) -> UUID:
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with _client() as http:
        made = await http.post(
            "/v1/agents",
            json={"name": name, "direction": "both", "language_primary": "en-IN"},
            headers=headers,
        )
    assert made.status_code == 201, made.text
    return UUID(made.json()["id"])


async def test_a_new_agent_carries_what_the_business_knows_and_asks_no_one_for_a_script() -> None:
    tenant_id, slug, token = await _make_tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_profiles (id, tenant_id) VALUES (:id, :tid) "
                "ON CONFLICT (tenant_id) DO NOTHING"
            ),
            {"id": uuid7(), "tid": tenant_id},
        )
        await session.execute(
            text(
                "UPDATE business_profiles SET services = CAST(:s AS jsonb) WHERE tenant_id = :tid"
            ),
            {"s": '[{"name": "Haircut", "price_inr": "150", "notes": null}]', "tid": tenant_id},
        )
    agent_id = await _create(token, slug, "Front desk")
    async with tenant_session(tenant_id) as session:
        body = (
            await session.execute(
                text(
                    "SELECT pv.body FROM agents a JOIN prompt_versions pv "
                    "ON pv.id = a.system_prompt_id WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar()
        proposal = (
            await session.execute(
                text("SELECT script_proposal FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
        notices = (
            await session.execute(
                text("SELECT ai_disclosure_line, recording_notice_line FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).one()
    assert body is not None and "[T0 FACTS]" in str(body) and "Haircut" in str(body)
    assert proposal is None, "no script is asked of Pip"
    assert all(str(sentence).strip() for sentence in notices), "both notice sentences are on file"


async def test_a_new_agent_with_no_script_is_published_inside_every_platform_layer() -> None:
    """Name, voice, done: the agent goes on the platform with the business's facts and the
    company training inside every platform layer."""
    from apps.api.agents.service import publish_agent
    from tests.conftest import accept_agreements

    tenant_id, slug, token = await _make_tenant()
    await accept_agreements(tenant_id)
    await _with_training(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO business_profiles (id, tenant_id, services) VALUES (:id, :tid, "
                "CAST(:s AS jsonb)) ON CONFLICT (tenant_id) DO UPDATE SET services = "
                "EXCLUDED.services"
            ),
            {
                "id": uuid7(),
                "tid": tenant_id,
                "s": '[{"name": "Haircut", "price_inr": "150", "notes": null}]',
            },
        )
    agent_id = await _create(token, slug, "Front desk")
    async with tenant_session(tenant_id) as session:
        ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id, take_calls=False)
    composed = compose_engine_prompt(_engine()._agents[ref])
    assert "Haircut" in composed and TRAINING in composed
    assert CONFIDENTIALITY_MARKER in composed and TRUTHFUL_ANSWER_MARKER in composed
    assert "--- HOW TO SPEAK ---" in composed


# --- the copy under a live test call, and copies of accounts with no workspace -------------


async def _live_test_call(tenant_id: UUID, agent_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "to_e164, trial_call, status, created_at, updated_at) VALUES (:id, :t, :a, "
                ":e, 'outbound', '+919876543210', true, 'in_progress', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "e": f"live-{uuid.uuid4().hex}"},
        )


async def test_the_copy_is_never_republished_under_a_live_test_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.errors import ProblemError

    tenant_id, agent_id = await _tenant_with_published_agent()
    ref = await paid_test_calls.refresh_test_copy(
        tenant_id=tenant_id, agent_id=agent_id, business=True
    )
    await _live_test_call(tenant_id, agent_id)

    # A campaign's test call would put the agent, with that campaign's script, on the copy.
    with pytest.raises(ProblemError) as refused:
        await paid_test_calls.refresh_test_copy(tenant_id=tenant_id, agent_id=agent_id)
    assert refused.value.code == "trial_line_busy"
    assert await _copy(tenant_id) == (ref, True), "the copy under the call is left as it is"

    # A new business chat talks to the copy as it is rather than republishing it.
    published: list[str] = []

    async def _nothing(*_a: Any, **_k: Any) -> None:
        return None

    async def _refresh(**_kwargs: Any) -> str:
        published.append("again")
        return ref

    async def _send(_engine: Any, *, engine_agent_ref: str, **_k: Any) -> Any:
        assert engine_agent_ref == ref
        return type(
            "Turn", (), {"session": "s-2", "reply": "Hello.", "tools": (), "failed_part_way": False}
        )()

    monkeypatch.setattr(try_chat, "RunsTestChat", object)
    monkeypatch.setattr(try_chat, "require_ai_assist", _nothing)
    monkeypatch.setattr(try_chat, "send_test_message", _send)
    monkeypatch.setattr(try_chat, "refresh_test_copy", _refresh)
    async with tenant_session(tenant_id) as session:
        await try_chat.send(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            message="When are you open?",
            chat_session=None,
            business=True,
        )
    assert published == []
    # The one shared trial line is platform-wide: end the call so no other test meets it.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET status = 'completed' WHERE agent_id = :a"), {"a": agent_id}
        )


async def test_the_business_copy_says_every_notice_switched_on_in_its_first_words() -> None:
    from calevate_shared.engine import compose_first_utterance, said_notices
    from calevate_shared.opening_notices import first_words_disclose

    tenant_id, agent_id = await _tenant_with_published_agent()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET ai_disclosure_enabled = true, recording_notice_enabled = true "
                "WHERE id = :a"
            ),
            {"a": agent_id},
        )
    # The publish's own read-back refuses a copy that drops a notice.
    ref = await paid_test_calls.refresh_test_copy(
        tenant_id=tenant_id, agent_id=agent_id, business=True
    )
    cfg = _engine()._agents[ref]
    ai_notice = cfg.ai_notice.strip()
    assert ai_notice
    assert first_words_disclose(
        compose_first_utterance(cfg),
        ai_notice=ai_notice,
        recording_notice=cfg.opening_line.strip().removeprefix(ai_notice).strip(),
        said=said_notices(cfg.system_prompt, business=cfg.business),
    )
    assert "--- HOW TO SPEAK ---" in compose_engine_prompt(cfg)


async def test_an_idle_copy_of_an_account_with_no_workspace_is_retired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _slug, _token = await _make_tenant()
    idle, fresh = f"ref_idle_{uuid.uuid4().hex}", f"ref_fresh_{uuid.uuid4().hex}"
    async with tenant_session(tenant_id) as session:
        first = UUID(str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()))
        second = await _second_agent(session, tenant_id)
        for agent_id, ref, days in ((first, idle, 60), (second, fresh, 0)):
            await session.execute(
                text(
                    "INSERT INTO agent_test_copies (id, tenant_id, agent_id, engine_agent_ref, "
                    "business_only, last_used_at) VALUES (:i, :t, :a, :r, true, "
                    "now() - make_interval(days => :d))"
                ),
                {"i": uuid7(), "t": tenant_id, "a": agent_id, "r": ref, "d": days},
            )
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, active, created_at, updated_at) VALUES (:e, :r, :t, :a, true, "
                    "now(), now())"
                ),
                {"e": get_engine().name, "r": ref, "t": tenant_id, "a": agent_id},
            )
    retired: list[str] = []

    async def _retire(_session: Any, *, ref: str, **_k: Any) -> None:
        retired.append(ref)

    import apps.api.agents.service as agents_service

    monkeypatch.setattr(agents_service, "retire_engine_agent", _retire)
    monkeypatch.setattr(agent_moves, "engine_has_workspaces", lambda: True)
    await agent_moves.sweep_agent_moves({})
    assert idle in retired
    assert fresh not in retired
