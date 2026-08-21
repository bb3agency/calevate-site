"""`campaign.completed` was subscribable and nothing had ever produced one (D-23).

The second half of the defect `tests/lead_updated_event_test.py` closed for `lead.updated`,
and the one `tests/crm_egress_known_gaps_test.py` recorded rather than fixed: the event has
been in `integrations.service.EVENT_TYPES`, in the endpoint route's `EventName` Literal and
on the integrations screen as "A campaign finishes" since D-23, and no line of code enqueued
one. A client could tick the box, watch the endpoint save, and wait forever.

**A test that asserts the event is SUBSCRIBABLE proves nothing** — `EVENT_TYPES`, the route's
Literal and `DEFAULT_SHEET_COLUMNS` all named it throughout the years it was never produced.
So every test here asserts it is PRODUCED, from the real dispatch path:

1. a campaign that runs out of contacts fans one event out to every subscribed endpoint,
   through `_dispatch_for_campaign` — not through a helper called directly;
2. the payload is AGGREGATES ONLY, and `service.body_subject` refuses to name a subject for
   it, so no forensic body of it is ever retained;
3. it shares a TRANSACTION with the terminal `status = 'completed'` write — proved by
   failing the enqueue and requiring the campaign to still be `running`;
4. a re-ARMED repeat produces nothing: that campaign did not finish, it is waiting;
5. an endpoint that did not subscribe hears nothing, and a neighbouring tenant's never does.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service
from apps.api.campaigns.scheduling import schedule_recurrence
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.integrations import service as integrations
from apps.workers import campaign_dispatch
from sqlalchemy import text
from tests.national_dnd_test import record_test_scrub

# 11:00 IST — inside the platform calling window, so nothing here is ever refused by the
# clock. Same instant `campaign_recurrence_test` pins, for the same reason.
NOON_IST = datetime(2026, 8, 11, 5, 30, tzinfo=UTC)
IST_OFFSET = timedelta(hours=5, minutes=30)
EVERY_DAY = [1, 2, 3, 4, 5, 6, 7]


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: NOON_IST + IST_OFFSET)


_TENANTS: list[uuid.UUID] = []


@pytest.fixture(autouse=True)
async def _leave_the_platform_quiet() -> AsyncIterator[None]:
    """Cancel every campaign this module armed. A campaign left `running` on the shared
    development database makes its tenant permanently dispatchable, which shows up as
    another suite's measurement rather than as this one's litter."""
    yield
    for tenant_id in _TENANTS:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'cancelled', schedule = NULL, "
                    "updated_at = now() WHERE status IN ('scheduled', 'running', 'paused')"
                )
            )
    _TENANTS.clear()


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Completion Motors",
        slug=f"done-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_done_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    async with tenant_session(tenant_id) as session:
        await service.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Completion Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
        )
    _TENANTS.append(tenant_id)
    return tenant_id, agent_id


async def _endpoint(
    tenant_id: uuid.UUID, *, events: tuple[str, ...] = ("campaign.completed",)
) -> uuid.UUID:
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, active, created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example/hook', 'whsec_campaign_completed', :events, "
                "CAST('{}' AS jsonb), true, now(), now())"
            ),
            {"id": endpoint_id, "tid": tenant_id, "events": list(events)},
        )
    return endpoint_id


async def _running_campaign(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    *,
    name: str = "August clearance",
    phones: tuple[str, ...] = ("9876510001", "9876510002"),
    recurring: bool = False,
) -> uuid.UUID:
    """A launched, gate-clean promotional campaign — built by the production writers, so
    `dispatch_blockers` passes for the reasons production passes it rather than because a
    test wrote a status.

    A `recurring` one cannot simply be launched and then given a repeat: only a DRAFT is
    schedulable. So it takes the route production takes — the repeat is armed on the
    draft, its occurrence is rewound into the past, and the dispatch tick's own
    `_fire_due_schedules` starts it through the full launch gate.
    """
    async with tenant_session(tenant_id) as session:
        number_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, dlt_status, "
                "created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, '140', 'registered', now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                # BOUND TO THE CAMPAIGN'S AGENT (D-424): the launch gate refuses a campaign
                # whose approved number is not the number its agent dials from.
                "aid": agent_id,
                "e": f"+9180{uuid.uuid4().int % 10**8:08d}",
            },
        )
        template_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
        )
        campaign_id = await service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name=name,
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=3,
            calling_hours=None,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": p, "name": f"Lead {p[-4:]}"} for p in phones],
        )
        await record_test_scrub(session, campaign_id)
        if not recurring:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
            return campaign_id
        await schedule_recurrence(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            days=EVERY_DAY,
            at=(NOON_IST + IST_OFFSET).time(),
            until=None,
        )
        # The only thing a test cannot do is wait a day: `start_at` is exactly where
        # `schedule_recurrence` put the next occurrence, and this writes a past instant
        # into it through that same key.
        await session.execute(
            text(
                "UPDATE campaigns SET schedule = jsonb_set(schedule, '{start_at}', "
                "to_jsonb(CAST(:s AS text))) WHERE id = :c"
            ),
            {
                "s": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
                "c": campaign_id,
            },
        )
    assert await campaign_dispatch._fire_due_schedules(tenant_id) == 1
    return campaign_id


async def _settle_contacts(tenant_id: uuid.UUID, campaign_id: uuid.UUID, *, connected: int) -> None:
    """Every contact reaches a terminal state, `connected` of them reached a human.

    This is the post-call pipeline's write (`resolve_campaign_contact`), performed here
    because these tests are about what happens AFTER it — the campaign has nothing left
    to dial and the next tick has to notice.
    """
    async with tenant_session(tenant_id) as session:
        ids = [
            row[0]
            for row in (
                await session.execute(
                    text(
                        "SELECT id FROM campaign_contacts WHERE campaign_id = :c "
                        "ORDER BY created_at, id"
                    ),
                    {"c": campaign_id},
                )
            ).all()
        ]
        for index, contact_id in enumerate(ids):
            await session.execute(
                text("UPDATE campaign_contacts SET status = :s, updated_at = now() WHERE id = :i"),
                {"s": "connected" if index < connected else "no_answer", "i": contact_id},
            )


async def _complete(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> None:
    """Run the REAL dispatch path over a campaign with nothing left to dial.

    `_dispatch_for_campaign`, not `emit_campaign_completed` and not `complete_or_rearm`:
    the defect this file closes was an event with no PRODUCER, so a test that called the
    producer directly would assert the one thing that was never in doubt.
    """
    await campaign_dispatch._dispatch_for_campaign(tenant_id, campaign_id, 5, {})


async def _queued(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every `campaign.completed` outbox payload for this tenant, oldest first."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = 'deliver_outbound_webhook' "
                    "AND payload->>'tenant_id' = :tid "
                    "AND payload->>'event' = 'campaign.completed' ORDER BY created_at, id"
                ),
                {"tid": str(tenant_id)},
            )
        ).all()
    return [dict(row[0]) for row in rows]


async def _status(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM campaigns WHERE id = :c"), {"c": campaign_id}
                )
            ).scalar()
        )


# ------------------------------------------------------------------ it is produced


async def test_a_campaign_that_finishes_tells_every_subscribed_endpoint() -> None:
    """The whole defect, in one assertion: the dispatch tick completes a campaign and an
    outbox row exists. Before this change the campaign completed and nothing was queued."""
    tenant_id, agent_id = await _tenant()
    await _endpoint(tenant_id)
    campaign_id = await _running_campaign(tenant_id, agent_id)
    await _settle_contacts(tenant_id, campaign_id, connected=1)

    await _complete(tenant_id, campaign_id)

    assert await _status(tenant_id, campaign_id) == "completed"
    queued = await _queued(tenant_id)
    assert len(queued) == 1, "the campaign finished and the client's CRM was told once"
    assert queued[0]["data"]["campaign_id"] == str(campaign_id)


async def test_the_payload_is_aggregates_and_carries_no_person() -> None:
    """Aggregates only — and the counts have to be RIGHT, or a client reconciling their
    own call log against the event learns not to trust it."""
    tenant_id, agent_id = await _tenant()
    await _endpoint(tenant_id)
    campaign_id = await _running_campaign(
        tenant_id, agent_id, name="Diwali offer", phones=("9876520001", "9876520002", "9876520003")
    )
    await _settle_contacts(tenant_id, campaign_id, connected=2)

    await _complete(tenant_id, campaign_id)

    data = (await _queued(tenant_id))[0]["data"]
    assert set(data) == {
        "campaign_id",
        "name",
        "contacts_total",
        "contacts_reached",
        "completed_at",
    }
    assert data["name"] == "Diwali offer", "the CAMPAIGN's name, which is not a person's"
    assert data["contacts_total"] == 3
    assert data["contacts_reached"] == 2, "only `connected` counts as reached"
    # The layout a Sheets endpoint subscribed to this event would lay the row out in.
    # Before this change there was none, and such an endpoint was refused at creation.
    assert set(integrations.DEFAULT_SHEET_COLUMNS["campaign.completed"]) == set(data)

    body = json.dumps(await _queued(tenant_id))
    for number in ("9876520001", "9876520002", "9876520003"):
        assert number not in body, "a contact's number reached an event that carries none"
    assert "Lead 0001" not in body, "a contact's name reached an event that carries none"


async def test_no_forensic_body_of_this_event_is_ever_retained() -> None:
    """`service.body_subject` returning None is what stops `record_delivery` filing a
    copy of the body. It is the reason the payload may be aggregates and must stay them:
    an object no DPDP erasure can enumerate a subject for is one we refuse to write."""
    tenant_id, agent_id = await _tenant()
    await _endpoint(tenant_id)
    campaign_id = await _running_campaign(tenant_id, agent_id)
    await _settle_contacts(tenant_id, campaign_id, connected=1)
    await _complete(tenant_id, campaign_id)

    assert integrations.body_subject((await _queued(tenant_id))[0]["data"]) is None


async def test_the_completed_at_is_the_row_the_same_transaction_wrote() -> None:
    """One stamp for one event. `completed_at` is read from `campaigns.updated_at`, which
    `complete_or_rearm`'s UPDATE wrote — a second `datetime.now()` here would put a
    different instant in the event than in the row the client can query."""
    tenant_id, agent_id = await _tenant()
    await _endpoint(tenant_id)
    campaign_id = await _running_campaign(tenant_id, agent_id)
    await _settle_contacts(tenant_id, campaign_id, connected=1)
    await _complete(tenant_id, campaign_id)

    async with tenant_session(tenant_id) as session:
        updated_at = (
            await session.execute(
                text("SELECT updated_at FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar()
    completed_at = (await _queued(tenant_id))[0]["data"]["completed_at"]
    assert datetime.fromisoformat(completed_at) == updated_at


# --------------------------------------------------------- it shares the transaction


async def test_the_outbox_row_and_the_terminal_status_write_share_a_transaction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """BACKEND-PATTERNS §4, proved by breaking it rather than by reading the code.

    The enqueue is made to fail AFTER `complete_or_rearm` has already written
    `status = 'completed'`. If the two were in different transactions the status would
    survive and the client's CRM would never hear — the exact "campaign finished, nobody
    told" defect the outbox exists to make unrepresentable. They are in one, so the
    status write rolls back with the enqueue and the NEXT tick completes the campaign
    again, because `complete_or_rearm` is a CAS off `running` rather than a one-shot.
    """
    tenant_id, agent_id = await _tenant()
    await _endpoint(tenant_id)
    campaign_id = await _running_campaign(tenant_id, agent_id)
    await _settle_contacts(tenant_id, campaign_id, connected=1)

    class EnqueueError(RuntimeError):
        pass

    async def _boom(*_args: Any, **_kwargs: Any) -> int:
        raise EnqueueError

    monkeypatch.setattr(campaign_dispatch.integrations, "enqueue_event", _boom)
    with pytest.raises(EnqueueError):
        await _complete(tenant_id, campaign_id)

    assert await _status(tenant_id, campaign_id) == "running", (
        "the campaign was recorded as completed in a transaction the event did not share"
    )
    assert await _queued(tenant_id) == []

    # And the completion is not lost — the retry is the next tick, with nothing patched.
    monkeypatch.undo()
    await _complete(tenant_id, campaign_id)
    assert await _status(tenant_id, campaign_id) == "completed"
    assert len(await _queued(tenant_id)) == 1


# ------------------------------------------------------------- it fires exactly once


async def test_a_repeat_that_rearms_produces_nothing_because_it_did_not_finish() -> None:
    """`complete_or_rearm` sends a recurring campaign back to `scheduled`. That campaign
    has not finished — it is waiting for its next occurrence — and telling a client's CRM
    "campaign completed" every night for a nightly repeat would be a lie told on a
    schedule."""
    tenant_id, agent_id = await _tenant()
    await _endpoint(tenant_id)
    campaign_id = await _running_campaign(tenant_id, agent_id, recurring=True)
    await _settle_contacts(tenant_id, campaign_id, connected=1)

    await _complete(tenant_id, campaign_id)

    assert await _status(tenant_id, campaign_id) == "scheduled"
    assert await _queued(tenant_id) == [], "a re-armed repeat announced a completion"


async def test_a_second_tick_over_a_completed_campaign_does_not_announce_it_twice() -> None:
    """The CAS is what makes it once. A receiver that got two "campaign completed" events
    for one campaign would double-count it in whatever the client built on top."""
    tenant_id, agent_id = await _tenant()
    await _endpoint(tenant_id)
    campaign_id = await _running_campaign(tenant_id, agent_id)
    await _settle_contacts(tenant_id, campaign_id, connected=1)

    await _complete(tenant_id, campaign_id)
    await _complete(tenant_id, campaign_id)

    assert len(await _queued(tenant_id)) == 1


# ------------------------------------------------------------------- who is told, and who is not


async def test_an_endpoint_that_did_not_subscribe_hears_nothing() -> None:
    tenant_id, agent_id = await _tenant()
    await _endpoint(tenant_id, events=("lead.created", "call.completed"))
    campaign_id = await _running_campaign(tenant_id, agent_id)
    await _settle_contacts(tenant_id, campaign_id, connected=1)

    await _complete(tenant_id, campaign_id)

    assert await _status(tenant_id, campaign_id) == "completed"
    assert await _queued(tenant_id) == []


async def test_a_neighbours_endpoint_is_never_in_this_tenants_fan_out() -> None:
    """Hard rule 1: the endpoint SELECT in `enqueue_events` is scoped by RLS alone, and
    this producer runs in a worker rather than behind a request principal — which is
    exactly where a missing tenant scope is easiest not to notice."""
    mine, my_agent = await _tenant()
    my_endpoint = await _endpoint(mine)
    theirs, _ = await _tenant()
    their_endpoint = await _endpoint(theirs)
    campaign_id = await _running_campaign(mine, my_agent)
    await _settle_contacts(mine, campaign_id, connected=1)

    await _complete(mine, campaign_id)

    queued = await _queued(mine)
    assert [row["endpoint_id"] for row in queued] == [str(my_endpoint)]
    assert str(their_endpoint) not in json.dumps(queued)
    assert await _queued(theirs) == []
