"""`created_at` is the EVENT's instant, and it survives the retry ladder unchanged.

The field was read from the clock in the delivery worker, which made it the moment we
managed to POST rather than the moment the client's data changed. Two consequences, both
invisible from a green delivery log and both fixed together:

* **Nothing in the envelope ordered two updates to one lead.** Attempt 3 of an edit made
  at 09:00 goes out at 09:03 carrying `09:03`, so a receiver doing last-write-wins by
  timestamp applies it after an unrelated 09:01 edit that was delivered first — quietly
  reverting the client's own newer data inside their CRM. `delivery_id` is a uuid7 and so
  is time-ordered, but docs/WEBHOOKS.md never said so and no client should have to know
  our id scheme to sort their inbox.
* **One delivery id carried a different body on each attempt**, so the retained
  `sent_body` and whatever the receiver kept could disagree for a delivery that is by
  contract one delivery.

Both are properties of the ENVELOPE, so they are asserted against the envelope and the
outbox row rather than through a live POST — the delivery path is covered next door in
`outbound_sync_test.py` and does not need re-proving here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service
from sqlalchemy import text
from tests.outbound_sync_test import _tenant_with_endpoint


def test_the_same_delivery_carries_the_same_created_at_on_every_attempt() -> None:
    """Retry number three is not a new event and must not look like one."""
    delivery_id, tenant_id = uuid7(), uuid7()
    occurred_at = datetime.now(UTC).isoformat()

    envelopes = [
        service.build_envelope(
            event="lead.updated",
            tenant_id=tenant_id,
            delivery_id=delivery_id,
            data={"lead_id": "1"},
            occurred_at=occurred_at,
        )
        for _ in range(3)
    ]

    assert {e["created_at"] for e in envelopes} == {occurred_at}
    assert envelopes[0] == envelopes[2], "the body of one delivery is one body"


def test_an_envelope_with_no_stamped_instant_still_carries_one() -> None:
    """The fallback, which is what makes this change safe for outbox rows that were
    already queued when it landed. It is the OLD behaviour — the clock at build time —
    kept deliberately rather than allowed to be a null a receiver has to handle."""
    before = datetime.now(UTC)
    envelope = service.build_envelope(
        event="lead.created", tenant_id=uuid7(), delivery_id=uuid7(), data={}
    )
    assert datetime.fromisoformat(str(envelope["created_at"])) >= before


@pytest.mark.asyncio
async def test_the_fan_out_stamps_the_instant_the_event_happened() -> None:
    """The stamp is written in the caller's transaction, beside the delivery id, so it
    is the enqueue moment and not a worker's later reading of a clock."""
    tenant_id, endpoint_id = await _tenant_with_endpoint(events=("lead.created",))
    before = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await service.enqueue_event(
            session, tenant_id=tenant_id, event="lead.created", data={"lead_id": str(uuid.uuid4())}
        )
    after = datetime.now(UTC)

    async with untenanted_session() as session:
        payload = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = :job "
                    "AND payload->>'tenant_id' = :t AND payload->>'endpoint_id' = :e"
                ),
                {"job": service.OUTBOUND_WEBHOOK_JOB, "t": str(tenant_id), "e": str(endpoint_id)},
            )
        ).scalar_one()

    stamped = datetime.fromisoformat(str(payload["occurred_at"]))
    assert before <= stamped <= after
    assert stamped.tzinfo is not None, "UTC, ISO-8601 — docs/WEBHOOKS.md §1.2"


@pytest.mark.asyncio
async def test_one_bulk_edit_is_one_instant_across_every_row_and_endpoint() -> None:
    """A bulk action moves up to `MAX_BULK_LEADS` leads in one transaction. They happened
    together, so they carry one `created_at` — n clock reads would smear a single edit
    across a few milliseconds that no receiver could ever act on, and would make the
    field look like a per-row ordering key it is not."""
    tenant_id, _ = await _tenant_with_endpoint(events=("lead.updated",))
    async with tenant_session(tenant_id) as session:
        await service.enqueue_events(
            session,
            tenant_id=tenant_id,
            event="lead.updated",
            rows=[{"lead_id": str(uuid.uuid4())} for _ in range(4)],
        )

    async with untenanted_session() as session:
        stamps = (
            (
                await session.execute(
                    text(
                        "SELECT payload->>'occurred_at' FROM outbox_messages "
                        "WHERE job = :job AND payload->>'tenant_id' = :t"
                    ),
                    {"job": service.OUTBOUND_WEBHOOK_JOB, "t": str(tenant_id)},
                )
            )
            .scalars()
            .all()
        )

    assert len(stamps) == 4
    assert len(set(stamps)) == 1
