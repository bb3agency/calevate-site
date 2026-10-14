"""The live change stream (D-774): what is announced, to whom, and when it stops.

Four claims, each tested at the layer that makes it:

1. **Every table is classified.** A write to a table the map does not name would be a feed
   that silently never updates; the registry is held against `Base.metadata`.
2. **A note goes out only for committed work.** Captured at the cursor, published from
   `after_commit`; a rollback and a compare-and-swap that changed nothing announce nothing.
3. **A note says nothing about anyone** (hard rule 6): a topic and an instant, plus the
   tenant id on the operator stream only.
4. **A client hears only its own account** (hard rule 1), and a stream stops when the
   session that opened it stops being entitled to it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
import pytest_asyncio
from apps.api.admin import service as admin_service
from apps.api.authn.sessions import (
    issue_session,
    revoke_session,
    rotate_session,
    session_still_live,
    verify_session,
)
from apps.api.core.errors import install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.session import credential_session, get_engine, tenant_session, untenanted_session
from apps.api.live import capture, hub, publish, routes
from apps.api.live.schemas import LiveChange
from apps.api.live.topics import (
    OPERATOR_CHANNEL,
    QUIET_TABLES,
    TABLE_TOPICS,
    TENANT_TOPICS,
    tenant_channel,
)
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text
from sqlalchemy.orm import Session

pytestmark = [pytest.mark.rls]


# ------------------------------------------------------------------ fixtures


async def _all_tables() -> set[str]:
    """Every table the migrated database has — not `Base.metadata`, which misses the tables
    only hand-written SQL reaches, and those are written just the same."""
    async with untenanted_session() as session:
        rows = await session.execute(
            text(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' "
                "AND tablename <> 'alembic_version'"
            )
        )
    return {str(row[0]) for row in rows}


@pytest.fixture
def captured(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[list[tuple[uuid.UUID | None, frozenset[str]]]]:
    """Install the capture on the test engine, record what `after_commit` would publish
    instead of publishing it, and take the listeners off again afterwards so the rest of
    the suite runs as it always did."""
    seen: list[tuple[uuid.UUID | None, frozenset[str]]] = []
    monkeypatch.setattr(
        capture, "schedule_publish", lambda tenant, topics: seen.append((tenant, topics))
    )
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


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, str, uuid.UUID]:
    """(tenant_id, slug, user_id) — a fresh org with one member."""
    slug = f"live-{uuid.uuid4().hex[:8]}"
    created = await admin_service.create_organization(
        name="Live Updates Clinic",
        slug=slug,
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
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
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return tenant_id, slug, user_id


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(routes.router)
    assert_policy_registry_complete(application)
    return application


def _events(body: str) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    for block in body.split("\n\n"):
        name = next((line[7:] for line in block.splitlines() if line.startswith("event: ")), None)
        data = next((line[6:] for line in block.splitlines() if line.startswith("data: ")), None)
        if name is not None and data is not None:
            out.append((name, json.loads(data)))
    return out


@pytest_asyncio.fixture
async def fresh_hub() -> AsyncIterator[None]:
    await hub.stop_hub()
    yield
    await hub.stop_hub()


# ------------------------------------------------------------------ 1. the registry


async def test_every_table_is_either_announced_or_quiet_with_a_reason() -> None:
    tables = await _all_tables()
    unclassified = sorted(tables - set(TABLE_TOPICS) - set(QUIET_TABLES))
    assert unclassified == [], (
        "tables with no live topic and no reason to be quiet; add each to "
        "apps/api/live/topics.py (TABLE_TOPICS or QUIET_TABLES)"
    )
    assert set(TABLE_TOPICS) & set(QUIET_TABLES) == set()
    assert all(reason.strip() for reason in QUIET_TABLES.values())


async def test_the_registry_names_no_table_that_does_not_exist() -> None:
    tables = await _all_tables()
    assert sorted((set(TABLE_TOPICS) | set(QUIET_TABLES)) - tables) == []


def test_a_client_topic_is_a_topic_the_map_produces() -> None:
    assert set(TABLE_TOPICS.values()) >= TENANT_TOPICS
    assert {"alerts", "platform"}.isdisjoint(TENANT_TOPICS)


@pytest.mark.parametrize(
    ("statement", "topics"),
    [
        ("INSERT INTO calls (id) VALUES (:id)", {"calls"}),
        ("UPDATE campaign_contacts c SET status = 'dialing' WHERE id = :id", {"campaigns"}),
        ("DELETE FROM scheduled_callbacks WHERE id = :id", {"callbacks"}),
        (
            "WITH moved AS (UPDATE leads SET status = 'hot' WHERE id = :id RETURNING id) "
            "INSERT INTO lead_events (id) SELECT id FROM moved",
            {"leads"},
        ),
        ("SELECT id FROM campaigns WHERE id = :id FOR UPDATE SKIP LOCKED", set()),
        (
            "INSERT INTO credit_ledger (id) VALUES (:id) ON CONFLICT (ref) DO UPDATE SET id = :id",
            {"wallet"},
        ),
        ("UPDATE auth_sessions SET last_seen_at = now()", set()),
        ("SELECT * FROM calls", set()),
    ],
)
def test_the_write_target_decides_the_topic(statement: str, topics: set[str]) -> None:
    assert capture.topics_in(statement) == topics


# ------------------------------------------------------------------ 2. after commit only


async def test_a_committed_write_is_announced_for_its_tenant(captured: list[Any]) -> None:
    tenant_id, _slug, _user = await _tenant()
    captured.clear()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE memberships SET updated_at = now() WHERE tenant_id = :id"),
            {"id": tenant_id},
        )
    assert captured == [(tenant_id, frozenset({"account"}))]


async def test_a_rolled_back_write_is_never_announced(captured: list[Any]) -> None:
    tenant_id, _slug, _user = await _tenant()
    captured.clear()
    with pytest.raises(RuntimeError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE memberships SET updated_at = now() WHERE tenant_id = :id"),
                {"id": tenant_id},
            )
            raise RuntimeError("the caller fails after writing")
    assert captured == []
    # And the next transaction on a pooled connection does not inherit the discarded note.
    async with tenant_session(tenant_id) as session:
        await session.execute(text("SELECT 1"))
    assert captured == []


async def test_a_write_that_changed_no_row_is_not_announced(captured: list[Any]) -> None:
    tenant_id, _slug, _user = await _tenant()
    captured.clear()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE memberships SET updated_at = now() WHERE tenant_id = :id"),
            {"id": uuid.uuid4()},
        )
    assert captured == []


async def test_a_write_with_no_tenant_goes_to_operators_only(captured: list[Any]) -> None:
    slug = f"live-{uuid.uuid4().hex[:8]}"
    captured.clear()
    async with untenanted_session() as session:
        await session.execute(text("INSERT INTO reserved_slugs (slug) VALUES (:s)"), {"s": slug})
        await session.execute(text("DELETE FROM reserved_slugs WHERE slug = :s"), {"s": slug})
    assert captured == [(None, frozenset({"platform"}))]


async def test_a_publish_that_fails_never_fails_the_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failures: list[str] = []

    class _Broken:
        def pipeline(self, **_: Any) -> Any:
            raise ConnectionError("redis is down")

    monkeypatch.setattr(publish, "get_redis", lambda: _Broken())
    monkeypatch.setattr(
        publish, "record_live_publish_failure", lambda *, reason: failures.append(reason)
    )
    await publish.publish_changes(uuid.uuid4(), {"calls"})
    assert failures == ["ConnectionError"]


# ------------------------------------------------------------------ 3. no personal data


def test_a_note_carries_a_topic_and_an_instant_and_nothing_else() -> None:
    tenant_id = uuid.uuid4()
    at = datetime(2026, 10, 14, 9, 30, tzinfo=UTC)
    notes = publish._notes(tenant_id, {"leads", "alerts"}, at)
    by_channel: dict[str, list[dict[str, Any]]] = {}
    for channel, body in notes:
        by_channel.setdefault(channel, []).append(json.loads(body))

    client_notes = by_channel[tenant_channel(tenant_id)]
    assert client_notes == [{"topic": "leads", "at": "2026-10-14T09:30:00Z", "tenant_id": None}]
    operator_topics = {note["topic"] for note in by_channel[OPERATOR_CHANNEL]}
    assert operator_topics == {"leads", "alerts"}
    assert {note["tenant_id"] for note in by_channel[OPERATOR_CHANNEL]} == {str(tenant_id)}
    assert set(LiveChange.model_fields) == {"topic", "at", "tenant_id"}


# ------------------------------------------------------------------ 4. the stream


async def test_the_stream_needs_a_signed_in_member() -> None:
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as client:
        refused = await client.get("/v1/live")
    assert refused.status_code == 401


async def _read_stream(
    monkeypatch: pytest.MonkeyPatch,
    *,
    path: str,
    headers: dict[str, str],
    publish_after: list[tuple[uuid.UUID | None, set[str]]],
    max_age_s: float = 1.5,
) -> list[tuple[str, dict[str, Any]]]:
    monkeypatch.setattr(routes, "MAX_AGE_S", max_age_s)

    async def _later() -> None:
        await asyncio.sleep(0.5)
        for tenant, topics in publish_after:
            await publish.publish_changes(tenant, topics)  # type: ignore[arg-type]

    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as client:
        task = asyncio.create_task(_later())
        response = await client.get(path, headers=headers, timeout=10)
        await task
    assert response.status_code == 200
    assert response.headers.get("x-accel-buffering") == "no"
    return _events(response.text)


async def test_a_client_hears_its_own_account_and_never_another(
    monkeypatch: pytest.MonkeyPatch, fresh_hub: None
) -> None:
    mine, slug, user = await _tenant()
    theirs, _other_slug, _other_user = await _tenant()

    events = await _read_stream(
        monkeypatch,
        path="/v1/live",
        headers={"Authorization": f"Bearer dev:client:{user}", "X-Org-Slug": slug},
        publish_after=[(theirs, {"calls", "leads"}), (mine, {"wallet"})],
    )

    names = [name for name, _ in events]
    assert names[0] == "ready"
    changes = [data for name, data in events if name == "change"]
    assert [change["topic"] for change in changes] == ["wallet"]
    assert all(change["tenant_id"] is None for change in changes)
    assert events[-1] == ("closed", {"reason": "max_age"})


async def test_a_stream_stops_when_its_caller_is_no_longer_entitled(
    monkeypatch: pytest.MonkeyPatch, fresh_hub: None
) -> None:
    tenant_id, slug, user = await _tenant()
    monkeypatch.setattr(routes, "HEARTBEAT_S", 0.3)

    async def _remove_member() -> None:
        await asyncio.sleep(0.4)
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("DELETE FROM memberships WHERE user_id = :uid"), {"uid": user}
            )

    remover = asyncio.create_task(_remove_member())
    events = await _read_stream(
        monkeypatch,
        path="/v1/live",
        headers={"Authorization": f"Bearer dev:client:{user}", "X-Org-Slug": slug},
        publish_after=[],
        max_age_s=10,
    )
    await remover
    assert events[0][0] == "ready"
    assert events[-1] == ("closed", {"reason": "session_ended"})


async def test_a_stream_that_cannot_hear_anything_ends_at_once(
    monkeypatch: pytest.MonkeyPatch, fresh_hub: None
) -> None:
    _tenant_id, slug, user = await _tenant()

    async def _never(_self: Any, _timeout: float) -> bool:
        return False

    monkeypatch.setattr(hub.LiveHub, "wait_connected", _never)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as client:
        response = await client.get(
            "/v1/live",
            headers={"Authorization": f"Bearer dev:client:{user}", "X-Org-Slug": slug},
        )
    assert response.status_code == 200
    assert _events(response.text) == []


async def test_one_person_cannot_hold_unbounded_streams(monkeypatch: pytest.MonkeyPatch) -> None:
    _tenant_id, slug, user = await _tenant()
    monkeypatch.setitem(routes._open, ("client", user), routes.MAX_STREAMS_PER_PERSON)
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as client:
        refused = await client.get(
            "/v1/live",
            headers={"Authorization": f"Bearer dev:client:{user}", "X-Org-Slug": slug},
        )
    assert refused.status_code == 429
    assert refused.json()["type"].endswith("/too_many_live_streams")


async def test_the_operator_stream_carries_every_account_with_its_id(
    monkeypatch: pytest.MonkeyPatch, fresh_hub: None
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
    tenant_id = uuid.uuid4()
    events = await _read_stream(
        monkeypatch,
        path="/v1/admin/live",
        headers={"Authorization": f"Bearer dev:admin:{admin_id}"},
        publish_after=[(tenant_id, {"calls"}), (None, {"alerts"})],
    )
    changes = [(data["topic"], data["tenant_id"]) for name, data in events if name == "change"]
    assert changes == [("calls", str(tenant_id)), ("alerts", None)]


def test_a_full_queue_asks_the_browser_to_resync() -> None:
    live_hub = hub.LiveHub()
    sub = hub.Subscription(channel="c")
    live_hub._subs["c"] = {sub}
    body = LiveChange(topic="calls", at=datetime.now(UTC)).model_dump_json()
    for _ in range(hub.QUEUE_MAX + 1):
        live_hub.deliver("c", body)
    assert sub.queue.qsize() == hub.QUEUE_MAX
    assert sub.resync == "fell_behind"
    live_hub.deliver("c", '{"topic": "calls", "phone": "+919876543210"}')
    assert sub.queue.qsize() == hub.QUEUE_MAX


# ------------------------------------------------------------------ the session re-check


@pytest_asyncio.fixture
async def subject() -> AsyncIterator[uuid.UUID]:
    subject_id = uuid.uuid4()
    yield subject_id
    async with credential_session() as session:
        await session.execute(
            text("DELETE FROM auth_sessions WHERE subject_id = :s"), {"s": subject_id}
        )


async def test_the_recheck_neither_slides_nor_revokes(subject: uuid.UUID) -> None:
    async with credential_session() as session:
        issued = await issue_session(session, realm="client", subject_id=subject)
    async with credential_session() as session:
        seen_before = (
            await session.execute(
                text("SELECT last_seen_at FROM auth_sessions WHERE id = :i"),
                {"i": issued.session_id},
            )
        ).scalar_one()

    later = datetime.now(UTC) + timedelta(minutes=10)
    assert await session_still_live(token=issued.token, realm="client", now=later) is not None
    async with credential_session() as session:
        seen_after = (
            await session.execute(
                text("SELECT last_seen_at FROM auth_sessions WHERE id = :i"),
                {"i": issued.session_id},
            )
        ).scalar_one()
    assert seen_after == seen_before

    # A rotation (the console's "stay signed in", a step-up) supersedes the stream's
    # cookie. The stream is told to close; the person stays signed in.
    verified = (await verify_session(token=issued.token, realm="client")).require_live()
    async with credential_session() as session:
        rotated = await rotate_session(session, verified=verified)
    assert await session_still_live(token=issued.token, realm="client") is None
    assert (await verify_session(token=rotated.token, realm="client")).live

    async with credential_session() as session:
        await revoke_session(session, session_id=rotated.session_id, reason="signed_out")
    assert await session_still_live(token=rotated.token, realm="client") is None


async def test_a_client_credential_never_opens_the_operator_stream() -> None:
    _tenant_id, slug, user = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as client:
        refused = await client.get(
            "/v1/admin/live",
            headers={"Authorization": f"Bearer dev:client:{user}", "X-Org-Slug": slug},
        )
    assert refused.status_code == 401


def test_the_api_and_the_workers_both_announce_their_commits() -> None:
    """Most feed changes are committed by the workers; a capture installed only in the API
    would leave every call, lead and dial silent until the safety poll. voice-runtime is
    deliberately absent (hard rule 3)."""
    import inspect

    from apps.api import main
    from apps.workers import settings as worker_settings

    assert "install_change_capture(get_engine())" in inspect.getsource(main._startup)
    assert "install_change_capture(get_engine())" in inspect.getsource(worker_settings.startup)


async def test_a_stopping_process_ends_its_streams_at_once(
    monkeypatch: pytest.MonkeyPatch, fresh_hub: None
) -> None:
    """uvicorn waits for open connections before it shuts down, so a stream that ignored
    SIGTERM would hold every deploy for the whole graceful timeout."""
    _tenant_id, slug, user = await _tenant()

    async def _stop_soon() -> None:
        await asyncio.sleep(0.5)
        hub.end_live_streams()

    stopper = asyncio.create_task(_stop_soon())
    events = await _read_stream(
        monkeypatch,
        path="/v1/live",
        headers={"Authorization": f"Bearer dev:client:{user}", "X-Org-Slug": slug},
        publish_after=[],
        max_age_s=30,
    )
    await stopper
    assert events[-1] == ("closed", {"reason": "shutting_down"})


def test_an_exit_callback_runs_before_the_drain_and_can_be_withdrawn() -> None:
    from apps.api.core import bootstrap

    seen: list[str] = []

    def callback() -> None:
        seen.append("ended")

    forget = bootstrap.on_exit_signal(callback)
    assert seen == []
    for registered in list(bootstrap._exit_callbacks):
        registered()
    forget()
    forget()
    assert seen == ["ended"]
    assert callback not in bootstrap._exit_callbacks
