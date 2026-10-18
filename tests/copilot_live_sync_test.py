"""One person's Pip conversation in step on every device, live (D-782).

What is proved here, each a property somebody could break without a screen noticing:

1. The question is stored, and the person's devices are told, BEFORE the answer exists —
   under the id the asking browser sent — and the answer lands under its own id when the
   run ends, on both realms.
2. `answering` is true while a run of this person's is in flight on any device, survives
   one of two concurrent runs finishing, and ignores a run whose `finally` never ran.
3. A note about a conversation goes to its owner's channel ALONE: a colleague on the same
   account, connected to the same live stream route, never receives it (zero leak), and a
   conversation write announces nothing on the account's channel.
4. A repeated turn id stores one row; an id that is somebody else's stores nothing.
5. Redis failing never fails a question, a read or a clear.
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from apps.api.admin import service as admin_service
from apps.api.billing import ai_quota
from apps.api.copilot import admin_routes, live_sync, service, transcript
from apps.api.copilot.schemas import CopilotAskIn
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.core.redis import get_redis
from apps.api.db.base import uuid7
from apps.api.db.session import credential_session, get_engine, tenant_session, untenanted_session
from apps.api.db.transition import _identifier
from apps.api.live import capture, hub, publish, routes
from apps.api.live.topics import PERSON_TOPICS, TABLE_TOPICS, TENANT_TOPICS, person_channel
from apps.api.main import app
from apps.workers import chat
from apps.workers.extraction import assist_capability
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session
from tests.conftest import make_tenant_with_pip as _make_tenant

BODY: dict[str, Any] = {
    "screen": {"route": "/c/x/leads", "title": "Leads", "realm": "client"},
    "question": "how many leads came in today",
    "fields": [],
    "facts": [],
    "history": [],
}


# ------------------------------------------------------------------ helpers


@pytest.fixture(autouse=True)
def _the_platform_brake_is_not_this_suites_business(monkeypatch: pytest.MonkeyPatch) -> None:
    """`copilot/route_test`'s fixture, for its reason: `platform_ai_spend` is shared."""

    async def not_tripped(*args: Any, **kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(ai_quota, "platform_brake_tripped", not_tripped)


async def _live_run(realm: str, subject: UUID) -> None:
    """A live sign-in run: a transcript turn is stamped with one (D-540) and a dev token
    carries no `auth_sessions` row. `route_test`'s idiom."""
    async with credential_session() as credentials:
        await credentials.execute(
            text(
                "INSERT INTO auth_sessions (id, family_id, realm, subject_id, token_hash, "
                "last_seen_at, idle_expires_at, absolute_expires_at, created_at, updated_at) "
                "VALUES (:id, :fid, :realm, :sid, :hash, now(), now() + interval '1 hour', "
                "now() + interval '1 hour', now() - interval '1 minute', now())"
            ),
            {
                "id": (session_id := uuid.uuid4()),
                "fid": uuid.uuid4(),
                "realm": realm,
                "sid": subject,
                "hash": session_id.bytes,
            },
        )


@pytest.fixture
def notes(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, UUID]]:
    """Every conversation note `live_sync` sends, as (realm, person)."""
    sent: list[tuple[str, UUID]] = []

    async def _record(realm: str, person: UUID) -> None:
        sent.append((realm, person))

    monkeypatch.setattr(live_sync, "publish_conversation_note", _record)
    return sent


async def _stream_events(client: AsyncClient, path: str, body: dict[str, Any]) -> list[str]:
    names: list[str] = []
    async with client.stream("POST", path, json=body, headers=_HEADERS) as response:
        assert response.status_code == 200, await response.aread()
        async for line in response.aiter_lines():
            if line.startswith("event:"):
                names.append(line[len("event:") :].strip())
    return names


_HEADERS: dict[str, str] = {}


async def _stored(realm: transcript.Realm, owner: UUID, tenant_id: UUID | None) -> list[Any]:
    opener = tenant_session(tenant_id) if tenant_id is not None else untenanted_session()
    async with opener as session:
        rows = await session.execute(
            text(
                f"SELECT id, role, content FROM {_identifier(realm.table, 'table')} "
                f"WHERE {_identifier(realm.owner, 'owner')} = :owner ORDER BY created_at, id"
            ),
            {"owner": owner},
        )
    return [(UUID(str(row[0])), row[1], row[2]) for row in rows]


# ------------------------------------------------------------------ 1. question first


async def test_the_question_is_stored_and_announced_before_the_answer_exists(
    monkeypatch: pytest.MonkeyPatch, notes: list[tuple[str, UUID]]
) -> None:
    tenant_id, slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    await _live_run("client", user_id)
    question_id, answer_id = uuid7(), uuid7()
    seen_mid_run: dict[str, Any] = {}

    async def _run(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        # What another device would read while Pip is still answering.
        seen_mid_run["turns"] = await _stored(transcript.CLIENT, user_id, tenant_id)
        seen_mid_run["answering"] = await live_sync.is_answering("client", user_id)
        seen_mid_run["notes"] = list(notes)
        yield service.CopilotEvent(text="Eleven.")

    monkeypatch.setattr(service, "run_copilot", _run)
    _HEADERS.clear()
    _HEADERS.update({"Authorization": f"Bearer {token}", "X-Org-Slug": slug})
    body = {**BODY, "turn_ids": {"question": str(question_id), "answer": str(answer_id)}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        events = await _stream_events(http, "/v1/copilot/ask", body)
        loaded = await http.get("/v1/copilot/conversation", headers=_HEADERS)

    assert events == ["text", "done"]
    assert seen_mid_run["turns"] == [(question_id, "user", BODY["question"])]
    assert seen_mid_run["answering"] is True
    assert seen_mid_run["notes"] == [("client", user_id)]
    # After the run: the answer under the browser's id, the mark settled, a second note.
    assert await _stored(transcript.CLIENT, user_id, tenant_id) == [
        (question_id, "user", BODY["question"]),
        (answer_id, "assistant", "Eleven."),
    ]
    assert notes == [("client", user_id), ("client", user_id)]
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["answering"] is False
    assert [turn["id"] for turn in loaded.json()["turns"]] == [str(question_id), str(answer_id)]


async def test_a_run_that_fails_still_settles_and_keeps_the_question(
    monkeypatch: pytest.MonkeyPatch, notes: list[tuple[str, UUID]]
) -> None:
    tenant_id, slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    await _live_run("client", user_id)

    async def _dies(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        for frame in ():  # an async generator that fails before its first frame
            yield frame
        raise RuntimeError("the provider hung up")

    monkeypatch.setattr(service, "run_copilot", _dies)
    _HEADERS.clear()
    _HEADERS.update({"Authorization": f"Bearer {token}", "X-Org-Slug": slug})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        events = await _stream_events(http, "/v1/copilot/ask", BODY)

    assert events == ["error"]
    turns = await _stored(transcript.CLIENT, user_id, tenant_id)
    assert [(role, content) for _id, role, content in turns] == [("user", BODY["question"])]
    assert await live_sync.is_answering("client", user_id) is False
    assert len(notes) == 2


async def test_a_question_that_cannot_be_stored_is_still_answered(
    monkeypatch: pytest.MonkeyPatch, notes: list[tuple[str, UUID]]
) -> None:
    tenant_id, slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    await _live_run("client", user_id)
    real_append = transcript.append_turn

    async def _question_fails(session: Any, **kwargs: Any) -> bool:
        if kwargs["role"] == "user":
            raise RuntimeError("the database refused")
        return await real_append(session, **kwargs)

    async def _run(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        yield service.CopilotEvent(text="Eleven.")

    monkeypatch.setattr(transcript, "append_turn", _question_fails)
    monkeypatch.setattr(service, "run_copilot", _run)
    _HEADERS.clear()
    _HEADERS.update({"Authorization": f"Bearer {token}", "X-Org-Slug": slug})
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        events = await _stream_events(http, "/v1/copilot/ask", BODY)

    assert events == ["text", "done"]
    turns = await _stored(transcript.CLIENT, user_id, tenant_id)
    assert [role for _id, role, _content in turns] == ["assistant"]


async def test_an_operators_question_is_stored_first_on_the_admin_table(
    monkeypatch: pytest.MonkeyPatch, notes: list[tuple[str, UUID]]
) -> None:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    await _live_run("admin", admin_id)
    question_id, answer_id = uuid7(), uuid7()
    mid_run: list[Any] = []

    async def _gate(_session: Any) -> None:
        return None

    async def _run(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        mid_run.extend(await _stored(transcript.ADMIN, admin_id, None))
        yield service.CopilotEvent(text="Nine accounts.")
        yield service.CopilotEvent(
            spend=service.CopilotSpend(
                usage=chat.TokenUsage(prompt_tokens=10, output_tokens=10),
                capability=assist_capability(),
            )
        )

    monkeypatch.setattr(admin_routes, "require_platform_ai", _gate)
    monkeypatch.setattr(service, "run_copilot", _run)
    _HEADERS.clear()
    _HEADERS.update({"Authorization": f"Bearer dev:admin:{admin_id}"})
    body = {
        **BODY,
        "screen": {"route": "/admin/tenants", "title": "Accounts", "realm": "admin"},
        "turn_ids": {"question": str(question_id), "answer": str(answer_id)},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        events = await _stream_events(http, "/v1/admin/copilot/ask", body)
        loaded = await http.get("/v1/admin/copilot/conversation", headers=_HEADERS)
        cleared = await http.delete("/v1/admin/copilot/conversation", headers=_HEADERS)

    assert events == ["text", "done"]
    assert mid_run == [(question_id, "user", BODY["question"])]
    assert [turn["id"] for turn in loaded.json()["turns"]] == [str(question_id), str(answer_id)]
    assert loaded.json()["answering"] is False
    assert cleared.json() == {"cleared": 2}
    assert notes == [("admin", admin_id)] * 3


async def test_start_again_tells_the_persons_other_windows(
    notes: list[tuple[str, UUID]],
) -> None:
    tenant_id, slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    await _live_run("client", user_id)
    async with credential_session() as credentials:
        run = (
            await credentials.execute(
                text("SELECT min(created_at) FROM auth_sessions WHERE subject_id = :s"),
                {"s": user_id},
            )
        ).scalar_one()
    async with tenant_session(tenant_id) as session:
        await transcript.append_exchange(
            session,
            realm=transcript.CLIENT,
            owner_id=user_id,
            tenant_id=tenant_id,
            run_started_at=run,
            screen_route="/c/x/leads",
            question="q",
            answer="a",
        )
    headers = {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        cleared = await http.delete("/v1/copilot/conversation", headers=headers)

    assert cleared.status_code == 200, cleared.text
    assert cleared.json() == {"cleared": 2}
    assert notes == [("client", user_id)]
    assert await _stored(transcript.CLIENT, user_id, tenant_id) == []


# ------------------------------------------------------------------ 2. answering


async def test_answering_holds_while_any_run_of_the_person_is_in_flight() -> None:
    person = uuid.uuid4()
    first, second = uuid.uuid4(), uuid.uuid4()
    assert await live_sync.is_answering("client", person) is False

    await live_sync.answer_started("client", person, first)
    await live_sync.answer_started("client", person, second)
    await live_sync.answer_settled("client", person, first)
    assert await live_sync.is_answering("client", person) is True
    # The other realm's id space is a different person.
    assert await live_sync.is_answering("admin", person) is False

    await live_sync.answer_settled("client", person, second)
    assert await live_sync.is_answering("client", person) is False


async def test_a_run_whose_finally_never_ran_stops_counting() -> None:
    person = uuid.uuid4()
    key = live_sync.answering_key("client", person)
    stale = time.time() - live_sync.ANSWERING_TTL_S - 1
    await get_redis().zadd(key, {str(uuid.uuid4()): stale})
    assert await live_sync.is_answering("client", person) is False
    assert live_sync.ANSWERING_TTL_S > service.TOTAL_BUDGET_S


async def test_redis_failing_never_fails_the_conversation(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Down:
        def pipeline(self, **_: Any) -> Any:
            raise ConnectionError("redis is down")

        async def zrem(self, *_: Any) -> int:
            raise ConnectionError("redis is down")

        async def zcount(self, *_: Any) -> int:
            raise ConnectionError("redis is down")

        async def publish(self, *_: Any) -> int:
            raise ConnectionError("redis is down")

    monkeypatch.setattr(live_sync, "get_redis", lambda: _Down())
    monkeypatch.setattr(publish, "get_redis", lambda: _Down())
    failures: list[str] = []
    monkeypatch.setattr(
        publish, "record_live_publish_failure", lambda *, reason: failures.append(reason)
    )
    person, run = uuid.uuid4(), uuid.uuid4()
    await live_sync.answer_started("client", person, run)
    await live_sync.answer_settled("client", person, run)
    await live_sync.conversation_changed("client", person)
    assert await live_sync.is_answering("client", person) is False
    assert failures == ["ConnectionError"] * 3


# ------------------------------------------------------------------ 3. zero leak


def test_a_conversation_is_a_person_topic_and_never_an_account_one() -> None:
    assert {"conversation"} == PERSON_TOPICS
    assert PERSON_TOPICS.isdisjoint(TENANT_TOPICS)
    assert PERSON_TOPICS.isdisjoint(TABLE_TOPICS.values())
    for table in ("copilot_conversation_turns", "admin_copilot_conversation_turns"):
        assert capture.topics_in(f"INSERT INTO {table} (id) VALUES (:id)") == frozenset()


async def test_a_note_reaches_its_owners_channel_and_carries_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent: list[tuple[str, str]] = []

    class _Recorder:
        async def publish(self, channel: str, body: str) -> int:
            sent.append((channel, body))
            return 1

    monkeypatch.setattr(publish, "get_redis", lambda: _Recorder())
    person = uuid.uuid4()
    await publish.publish_conversation_note("client", person)
    [(channel, body)] = sent
    assert channel == person_channel("client", person)
    note = json.loads(body)
    assert set(note) == {"topic", "at", "tenant_id"}
    assert note["topic"] == "conversation"
    assert note["tenant_id"] is None


def test_the_hub_hands_a_persons_note_to_that_person_alone() -> None:
    live_hub = hub.LiveHub()
    account = "calevate:live:tenant:t"
    mine = hub.Subscription(channel=account, also=(person_channel("client", "me"),))
    theirs = hub.Subscription(channel=account, also=(person_channel("client", "them"),))
    for sub in (mine, theirs):
        for name in (sub.channel, *sub.also):
            live_hub._subs.setdefault(name, set()).add(sub)
    body = json.dumps({"topic": "conversation", "at": "2026-10-15T09:00:00Z"})

    live_hub.deliver(person_channel("client", "me"), body)
    assert mine.queue.qsize() == 1
    assert theirs.queue.qsize() == 0

    live_hub.deliver(account, json.dumps({"topic": "leads", "at": "2026-10-15T09:00:00Z"}))
    assert mine.queue.qsize() == 2
    assert theirs.queue.qsize() == 1
    assert live_hub.listeners == 2

    live_hub.unsubscribe(mine)
    assert person_channel("client", "me") not in live_hub._subs
    assert live_hub._subs[account] == {theirs}


@pytest_asyncio.fixture
async def fresh_hub() -> AsyncIterator[None]:
    await hub.stop_hub()
    yield
    await hub.stop_hub()


def _live_app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(routes.router)
    assert_policy_registry_complete(application)
    return application


async def _second_member(tenant_id: UUID) -> UUID:
    colleague = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": colleague, "email": f"{colleague}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": colleague},
        )
    return colleague


def _changes(text_body: str) -> list[str]:
    topics: list[str] = []
    for block in text_body.split("\n\n"):
        lines = block.splitlines()
        if "event: change" in lines:
            data = next(line[6:] for line in lines if line.startswith("data: "))
            topics.append(json.loads(data)["topic"])
    return topics


async def test_a_colleague_on_the_same_account_never_hears_my_conversation(
    monkeypatch: pytest.MonkeyPatch, fresh_hub: None
) -> None:
    """THE ZERO-LEAK PROOF over the real route, real Redis and the real hub: two members of
    one account each hold `GET /v1/live`; a conversation note for one of them reaches that
    stream and not the other, while an account note reaches both."""
    created = await admin_service.create_organization(
        name="Live Sync Clinic",
        slug=(slug := f"sync-{uuid.uuid4().hex[:8]}"),
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    me = await _second_member(tenant_id)
    colleague = await _second_member(tenant_id)
    monkeypatch.setattr(routes, "MAX_AGE_S", 1.5)

    async def _later() -> None:
        await asyncio.sleep(0.6)
        await publish.publish_conversation_note("client", me)
        await publish.publish_changes(tenant_id, {"leads"})

    async with AsyncClient(transport=ASGITransport(app=_live_app()), base_url="http://api") as c:
        task = asyncio.create_task(_later())
        mine, theirs = await asyncio.gather(
            c.get(
                "/v1/live",
                headers={"Authorization": f"Bearer dev:client:{me}", "X-Org-Slug": slug},
                timeout=10,
            ),
            c.get(
                "/v1/live",
                headers={"Authorization": f"Bearer dev:client:{colleague}", "X-Org-Slug": slug},
                timeout=10,
            ),
        )
        await task

    assert _changes(mine.text) == ["conversation", "leads"]
    assert _changes(theirs.text) == ["leads"]


@pytest.fixture
def captured(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[Any]]:
    """`live_updates_test.captured`: what `after_commit` would publish, recorded."""
    seen: list[Any] = []
    monkeypatch.setattr(capture, "schedule_publish", lambda tenant, topics: seen.append(topics))
    engine = get_engine()
    capture.install_change_capture(engine)
    try:
        yield seen
    finally:
        sync = engine.sync_engine
        event.remove(sync, "after_cursor_execute", capture._after_cursor_execute)
        event.remove(sync, "commit", capture._drop_sink)
        event.remove(sync, "rollback", capture._drop_sink)
        event.remove(sync.pool, "checkin", capture._drop_sink_on_checkin)
        event.remove(Session, "after_begin", capture._after_begin)
        event.remove(Session, "after_commit", capture._after_commit)
        event.remove(Session, "after_soft_rollback", capture._after_soft_rollback)
        delattr(sync, capture._INSTALLED)


async def test_a_conversation_write_announces_nothing_to_the_account(captured: list[Any]) -> None:
    tenant_id, _slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    captured.clear()
    async with tenant_session(tenant_id) as session:
        await transcript.append_turn(
            session,
            realm=transcript.CLIENT,
            turn_id=uuid7(),
            owner_id=user_id,
            tenant_id=tenant_id,
            run_started_at=datetime.now(UTC),
            screen_route="/c/x/leads",
            role="user",
            spoken="a private question",
        )
    assert captured == []


# ------------------------------------------------------------------ 4. idempotent ids


async def test_a_repeated_turn_id_stores_one_row_and_a_foreign_one_stores_nothing() -> None:
    tenant_id, _slug, token = await _make_tenant()
    owner = UUID(token.rsplit(":", 1)[1])
    other_tenant, _other_slug, other_token = await _make_tenant()
    other = UUID(other_token.rsplit(":", 1)[1])
    run = datetime.now(UTC)
    turn_id = uuid7()

    async def _append(tenant: UUID, person: UUID, spoken: str) -> bool:
        async with tenant_session(tenant) as session:
            return await transcript.append_turn(
                session,
                realm=transcript.CLIENT,
                turn_id=turn_id,
                owner_id=person,
                tenant_id=tenant,
                run_started_at=run,
                screen_route="/c/x/leads",
                role="user",
                spoken=spoken,
            )

    assert await _append(tenant_id, owner, "first") is True
    assert await _append(tenant_id, owner, "first, again") is False
    assert await _append(other_tenant, other, "someone else's id") is False
    assert await _stored(transcript.CLIENT, owner, tenant_id) == [(turn_id, "user", "first")]
    assert await _stored(transcript.CLIENT, other, other_tenant) == []


def test_the_two_turn_ids_must_differ() -> None:
    same = str(uuid7())
    with pytest.raises(ValueError, match="different ids"):
        CopilotAskIn.model_validate({**BODY, "turn_ids": {"question": same, "answer": same}})


# ------------------------------------------------------------------ 5. zero-cost answers


async def test_a_zero_cost_admin_answer_reaches_the_operators_other_window(
    monkeypatch: pytest.MonkeyPatch, fresh_hub: None
) -> None:
    """The identity short-circuit answers from a constant and spends nothing. Its question is
    stored first (D-782), so its answer must be stored too, under the browser's id, and the
    operator's other window must hear about both — not a question left without an answer."""
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    await _live_run("admin", admin_id)
    reached: list[str] = []

    def _stream(leg: Any, messages: Any, **kwargs: Any) -> Any:
        reached.append("provider")
        raise AssertionError("an identity question must not reach a provider")

    async def _gate(_session: Any) -> None:
        return None

    monkeypatch.setattr(chat, "stream", _stream)
    monkeypatch.setattr(admin_routes, "require_platform_ai", _gate)
    monkeypatch.setattr(routes, "MAX_AGE_S", 2.5)
    question_id, answer_id = uuid7(), uuid7()
    headers = {"Authorization": f"Bearer dev:admin:{admin_id}"}
    body = {
        **BODY,
        "question": "what model are you?",
        "screen": {"route": "/admin/tenants", "title": "Accounts", "realm": "admin"},
        "turn_ids": {"question": str(question_id), "answer": str(answer_id)},
    }

    async def _ask_from_this_window() -> list[str]:
        await asyncio.sleep(0.6)
        _HEADERS.clear()
        _HEADERS.update(headers)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
            return await _stream_events(http, "/v1/admin/copilot/ask", body)

    async with AsyncClient(transport=ASGITransport(app=_live_app()), base_url="http://api") as c:
        other_window, events = await asyncio.gather(
            c.get("/v1/admin/live", headers=headers, timeout=10), _ask_from_this_window()
        )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        loaded = await http.get("/v1/admin/copilot/conversation", headers=headers)

    assert reached == []
    assert events == ["text", "done"]
    # Question stored, answer stored and the mark settled: one note each, on this person's
    # own stream (the operator stream carries no conversation note of anyone's).
    assert _changes(other_window.text) == ["conversation", "conversation"]
    turns = loaded.json()["turns"]
    assert [(turn["id"], turn["role"]) for turn in turns] == [
        (str(question_id), "user"),
        (str(answer_id), "assistant"),
    ]
    assert turns[1]["content"]
    assert loaded.json()["answering"] is False


async def test_a_zero_cost_client_answer_is_stored_under_the_browsers_id(
    monkeypatch: pytest.MonkeyPatch, notes: list[tuple[str, UUID]]
) -> None:
    """The client route's equivalent: the same short-circuit, the same rule."""
    tenant_id, slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    await _live_run("client", user_id)

    def _stream(leg: Any, messages: Any, **kwargs: Any) -> Any:
        raise AssertionError("an identity question must not reach a provider")

    monkeypatch.setattr(chat, "stream", _stream)
    question_id, answer_id = uuid7(), uuid7()
    _HEADERS.clear()
    _HEADERS.update({"Authorization": f"Bearer {token}", "X-Org-Slug": slug})
    body = {
        **BODY,
        "question": "what model are you?",
        "turn_ids": {"question": str(question_id), "answer": str(answer_id)},
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        events = await _stream_events(http, "/v1/copilot/ask", body)

    assert events == ["text", "done"]
    turns = await _stored(transcript.CLIENT, user_id, tenant_id)
    assert [(turn_id, role) for turn_id, role, _content in turns] == [
        (question_id, "user"),
        (answer_id, "assistant"),
    ]
    assert notes == [("client", user_id), ("client", user_id)]


async def test_an_answer_that_was_only_a_proposal_card_is_stored_as_its_card(
    monkeypatch: pytest.MonkeyPatch, notes: list[tuple[str, UUID]]
) -> None:
    """A reload must show what Pip did, not the question alone (which reads as sent twice)."""
    from apps.api.copilot.schemas import CopilotProposalEvent

    tenant_id, slug, token = await _make_tenant()
    user_id = UUID(token.rsplit(":", 1)[1])
    await _live_run("client", user_id)
    question_id, answer_id = uuid7(), uuid7()

    async def _run(payload: Any, **kwargs: Any) -> AsyncIterator[service.CopilotEvent]:
        yield service.CopilotEvent(
            proposal=CopilotProposalEvent(
                token="t",
                tool="agent_tests_fix",
                title="Suggest fixes for the failed tests",
                summary="Pip works out fixes for 10 failed tests.",
                object_type="agent",
                object_id="a",
                current=None,
                proposed="fixes",
                cost=None,
                reversal="Discard it on the Test section.",
                expires_at=datetime.now(UTC) + timedelta(minutes=10),
            )
        )

    monkeypatch.setattr(service, "run_copilot", _run)
    _HEADERS.clear()
    _HEADERS.update({"Authorization": f"Bearer {token}", "X-Org-Slug": slug})
    body = {**BODY, "turn_ids": {"question": str(question_id), "answer": str(answer_id)}}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        await _stream_events(http, "/v1/copilot/ask", body)

    assert await _stored(transcript.CLIENT, user_id, tenant_id) == [
        (question_id, "user", BODY["question"]),
        (
            answer_id,
            "assistant",
            "Suggest fixes for the failed tests. Pip works out fixes for 10 failed tests.",
        ),
    ]
