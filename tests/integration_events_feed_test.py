"""The events feed (D-1049, MASTER-PLAN W2.7, API·02 G5).

1. A webhook delivery and the feed carry the same `event_id` for the same event.
2. A key's cursor moves only on ack, forward only, and `next` reads after it.
3. The phone is masked when read unless the reader may have it.
4. An erasure removes a person's events; the 30-day sweep removes old ones.
5. RLS: another account's session reads zero rows from both tables (hard rule 1).
6. A key creates endpoints without call content, and removes only its own.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import feed, machine, service
from apps.workers import retention, webhooks_feed
from sqlalchemy import text
from tests.api_security_test import _make_tenant

PHONE = "+919845012345"


def _lead(lead_id: uuid.UUID | None = None) -> dict[str, object]:
    return {
        "lead_id": str(lead_id or uuid7()),
        "phone": PHONE,
        "name": "Sita",
        "source": "webhook",
        "status": "new",
    }


async def _endpoint(tenant_id: uuid.UUID) -> uuid.UUID:
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example/hook', 'whsec_x', ARRAY['lead.created'], true, now(), now())"
            ),
            {"id": endpoint_id, "tid": tenant_id},
        )
    return endpoint_id


async def _emit(tenant_id: uuid.UUID, *rows: dict[str, object]) -> None:
    async with tenant_session(tenant_id) as session:
        await service.enqueue_events(
            session, tenant_id=tenant_id, event="lead.created", rows=list(rows)
        )


async def test_the_webhook_and_the_feed_carry_one_event_id() -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id)
    await _emit(tenant_id, _lead())

    async with tenant_session(tenant_id) as session:
        (row,) = await feed.list_events(session)
        payload = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE payload->>'endpoint_id' = :e"),
                {"e": str(endpoint_id)},
            )
        ).scalar_one()
    envelope = service.build_envelope(
        event="lead.created",
        tenant_id=tenant_id,
        delivery_id=uuid.UUID(payload["delivery_id"]),
        data=payload["data"],
        event_id=payload["event_id"],
    )
    served = feed.serialize(row, tenant_id=tenant_id)
    assert envelope["event_id"] == served["event_id"] == served["id"] == str(row.id)
    assert envelope["id"] != served["id"]  # the delivery id is per endpoint
    assert served["data"]["phone"] == "[redacted]"
    assert feed.serialize(row, tenant_id=tenant_id, include_raw_phone=True)["data"]["phone"] == (
        PHONE
    )


async def test_a_cursor_moves_on_ack_only_and_never_backwards() -> None:
    tenant_id, _, _ = await _make_tenant()
    key = uuid.uuid4()
    await _emit(tenant_id, _lead(), _lead(), _lead())

    async with tenant_session(tenant_id) as session:
        first = await feed.next_events(session, consumer_id=key, limit=2)
        assert len(first) == 2
        # Reading again without an ack reads the same events.
        assert [e.id for e in await feed.next_events(session, consumer_id=key, limit=2)] == [
            e.id for e in first
        ]
        cursor = await feed.ack(session, tenant_id=tenant_id, consumer_id=key, event_id=first[1].id)
        assert cursor.after_event_id == first[1].id
        # A late ack of an earlier event leaves the cursor where it is.
        cursor = await feed.ack(session, tenant_id=tenant_id, consumer_id=key, event_id=first[0].id)
        assert cursor.after_event_id == first[1].id
        (rest,) = await feed.next_events(session, consumer_id=key)
        assert rest.id not in {e.id for e in first}
        assert [e.id for e in await feed.list_events(session, after=first[0].id)] == [
            first[1].id,
            rest.id,
        ]


async def test_an_unknown_position_is_refused() -> None:
    tenant_id, _, _ = await _make_tenant()
    with pytest.raises(ProblemError) as refused:
        async with tenant_session(tenant_id) as session:
            await feed.list_events(session, after=uuid.uuid4())
    assert refused.value.code == "feed_event_unknown"


async def test_another_account_reads_none_of_the_feed_or_its_cursors() -> None:
    owner, _, _ = await _make_tenant()
    other, _, _ = await _make_tenant()
    key = uuid.uuid4()
    await _emit(owner, _lead())
    async with tenant_session(owner) as session:
        (event,) = await feed.list_events(session)
        await feed.ack(session, tenant_id=owner, consumer_id=key, event_id=event.id)

    async with tenant_session(other) as session:
        for table in ("integration_events", "integration_event_cursors"):
            assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar() == 0
        assert await feed.list_events(session) == []
        with pytest.raises(ProblemError):
            await feed.ack(session, tenant_id=other, consumer_id=uuid.uuid4(), event_id=event.id)


async def test_an_erasure_removes_the_persons_events_and_the_sweep_old_ones() -> None:
    tenant_id, _, _ = await _make_tenant()
    lead_id = uuid7()
    await _emit(tenant_id, _lead(lead_id), {**_lead(), "phone": "+919000000001"})
    async with tenant_session(tenant_id) as session:
        removed = await retention._erase_integration_events(
            session, phone=PHONE, lead_ids=[lead_id], call_ids=[]
        )
        assert removed == 1
        (left,) = await feed.list_events(session)
        assert left.data["phone"] == "+919000000001"
        await session.execute(
            text("DELETE FROM integration_events WHERE id = :id"),
            {"id": left.id},
        )
        await session.execute(
            text(
                "INSERT INTO integration_events (id, tenant_id, event_type, data, created_at) "
                "VALUES (:id, :tid, 'lead.created', '{}'::jsonb, :at)"
            ),
            {"id": uuid7(), "tid": tenant_id, "at": datetime.now(UTC) - timedelta(days=31)},
        )
    assert await webhooks_feed._sweep_tenant(tenant_id) == 1


async def test_a_row_is_never_rewritten() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _emit(tenant_id, _lead())
    with pytest.raises(Exception, match=r"append-only|forbid|not allowed|immutable"):
        async with tenant_session(tenant_id) as session:
            await session.execute(text("UPDATE integration_events SET event_type = 'x'"))


def _key_principal(tenant_id: uuid.UUID) -> Principal:
    return Principal(realm="client", user_id=None, tenant_id=tenant_id, role=None)


async def test_a_key_creates_endpoints_without_call_content_and_removes_only_its_own(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _public(url: str) -> SimpleNamespace:
        return SimpleNamespace(host="example.com", port=443, url=url)

    monkeypatch.setattr(service, "assert_public_http_url", _public)
    tenant_id, _, _ = await _make_tenant()
    key_id = uuid.uuid4()
    principal = _key_principal(tenant_id)
    with pytest.raises(ProblemError):
        async with tenant_session(tenant_id) as session:
            await machine.create_machine_endpoint(
                session,
                actor=principal,
                tenant_id=tenant_id,
                key_id=key_id,
                url="https://example.com/hook",
                events=[service.RECORDING_READY_EVENT],
            )
    async with tenant_session(tenant_id) as session:
        created = await machine.create_machine_endpoint(
            session,
            actor=principal,
            tenant_id=tenant_id,
            key_id=key_id,
            url="https://example.com/hook",
            events=["*"],
            auto_subscribe_new_events=True,
        )
        choices = await service.read_endpoint_choices(session, created.id)
    assert service.RECORDING_READY_EVENT not in created.events
    assert not (
        choices.include_recording_url
        or choices.include_transcript
        or choices.include_raw_transcript
    )
    assert choices.managed_by_key_id == key_id and choices.auto_subscribe_new_events

    person_made = await _endpoint(tenant_id)
    with pytest.raises(ProblemError):
        async with tenant_session(tenant_id) as session:
            await machine.deactivate_machine_endpoint(
                session,
                actor=principal,
                tenant_id=tenant_id,
                key_id=key_id,
                endpoint_id=person_made,
            )
    async with tenant_session(tenant_id) as session:
        assert await machine.deactivate_machine_endpoint(
            session, actor=principal, tenant_id=tenant_id, key_id=key_id, endpoint_id=created.id
        )


async def test_the_router_hook_serves_the_feed_for_a_key() -> None:
    """`build_events_router` is what the `/api/v1` router mounts; its handlers read the
    feed for the key the auth dependency names and mask the phone unless told otherwise."""
    tenant_id, _, _ = await _make_tenant()
    key = uuid.uuid4()
    await _emit(tenant_id, _lead())
    principal = _key_principal(tenant_id)

    router = machine.build_events_router(lambda: principal, consumer_id_of=lambda _p: key)
    handlers = {route.path: route.endpoint for route in router.routes}  # type: ignore[attr-defined]
    assert set(handlers) == {"/events", "/events/next", "/events/next/ack"}

    async with tenant_session(tenant_id) as session:
        page = await handlers["/events/next"](
            session=session, principal=principal, type=None, limit=10
        )
        (item,) = page.events
        assert item.data["phone"] == "[redacted]" and page.next_after == item.id
        cursor = await handlers["/events/next/ack"](
            payload=machine.FeedAckIn(event_id=item.id), session=session, principal=principal
        )
        assert cursor.after_event_id == item.id
        listed = await handlers["/events"](
            session=session, principal=principal, after=None, type=None, limit=10
        )
        assert [e.id for e in listed.events] == [item.id]
