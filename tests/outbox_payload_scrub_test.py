"""A published outbox row keeps no payload — the promise `authn` was already making.

`apps/api/authn/service._enqueue_auth_email` puts a LIVE one-time credential in
`outbox_messages.payload`: a password-reset token, an invitation link, an OTP. Its
docstring bounded that exposure on one sentence — *"the row is deleted on successful
dispatch"* — and the sentence was false. Publishing UPDATEs the row to `published`;
nothing removed it until `retention.prune_reliability_tables` reached it at
`RELIABILITY_PRUNE_AFTER`, which is NINETY DAYS. A security argument resting on a premise
the code does not implement is worse than no argument, because it stops the next reader
looking.

The same statement carries a second, wider obligation. `retention.py`'s own comment says
what else is in that column — "a lead's name, phone number and call summary … an unbounded
copy of tenant personal data sitting OUTSIDE every retention policy a tenant can set, and
outside the DPDP erasure path" — and pruning bounded the GROWTH without shortening the
EXPOSURE. Scrubbing at publish takes it from ninety days to the length of a dispatch tick,
for every job, without a new table, a new sweep or a new schedule.

What must survive is the answer to "was this delivery made": `job`, `job_id`,
`published_at`, `attempt_count`, `status`. Those are asserted here too, because a scrub
that took the evidence with it would be trading one defect for another.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import mark_outbox_failed, mark_outbox_published
from sqlalchemy import text

RUN = uuid.uuid4().hex[:12]
SECRET = f"tok_live_credential_{RUN}"

#: Cleaned up BY ID: the payload marker this suite would otherwise search by is exactly
#: what the code under test removes.
_WRITTEN: list[UUID] = []


@pytest.fixture(scope="module", autouse=True)
async def _clean_up_after_ourselves() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE id = ANY(CAST(:ids AS uuid[]))"),
            {"ids": [str(message_id) for message_id in _WRITTEN]},
        )


async def _pending_row(job: str, payload: dict[str, Any]) -> UUID:
    message_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                "created_at, updated_at) VALUES (:id, 'default', :job, CAST(:payload AS jsonb), "
                "'pending', 0, now(), now())"
            ),
            {"id": message_id, "job": job, "payload": json.dumps(payload)},
        )
    _WRITTEN.append(message_id)
    return message_id


async def _row(message_id: UUID) -> tuple[str, dict[str, Any], str | None, int]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, payload, job_id, attempt_count FROM outbox_messages "
                    "WHERE id = :id"
                ),
                {"id": message_id},
            )
        ).first()
    assert row is not None
    return str(row[0]), dict(row[1]), row[2], int(row[3])


async def test_publishing_forgets_the_credential_it_carried() -> None:
    """THE REGRESSION. Before this, the token was still readable ninety days later."""
    message_id = await _pending_row(
        "deliver_auth_email",
        {"kind": "password_reset", "to": "someone@example.com", "secret": SECRET},
    )
    async with untenanted_session() as session:
        await mark_outbox_published(session, message_id=message_id, job_id="job-123")

    status, payload, job_id, _ = await _row(message_id)
    assert status == "published"
    assert payload == {}, f"the payload survived publication: {sorted(payload)}"
    assert job_id == "job-123", "the trace from the row to the work it became must survive"


async def test_the_delivery_evidence_survives_the_scrub() -> None:
    """The 90-day floor exists so somebody can still ask "was this delivery made". The
    scrub must not take the answer with the content."""
    message_id = await _pending_row("deliver_outbound_webhook", {"lead": "a name", "phone": "+91"})
    async with untenanted_session() as session:
        await mark_outbox_published(session, message_id=message_id, job_id="job-456")

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT job, job_id, status, published_at IS NOT NULL, locked_until "
                    "FROM outbox_messages WHERE id = :id"
                ),
                {"id": message_id},
            )
        ).first()
    assert row is not None
    assert (row[0], row[1], row[2], row[3], row[4]) == (
        "deliver_outbound_webhook",
        "job-456",
        "published",
        True,
        None,
    )


async def test_a_dead_lettered_row_keeps_its_payload() -> None:
    """THE ONE THAT MUST NOT BE SCRUBBED. `status = 'failed'` IS the outbox dead-letter
    queue, and `POST /v1/ops/outbox/replay` flips those rows back to `pending` for the
    next tick to re-publish. A failed row with an empty payload would be replayed into a
    job with no arguments — an operator's recovery action turned into a second, silent
    failure."""
    message_id = await _pending_row("deliver_outbound_webhook", {"marker": f"dlq-{RUN}"})
    async with untenanted_session() as session:
        await mark_outbox_failed(
            session, message_id=message_id, error="receiver refused", attempt_count=99
        )

    status, payload, _, _ = await _row(message_id)
    assert status == "failed"
    assert payload == {"marker": f"dlq-{RUN}"}, "the DLQ lost the payload it replays from"


async def test_the_scrub_and_the_status_flip_are_one_statement() -> None:
    """A second UPDATE would leave a window in which the row is published and the secret
    is still there — the exposure again, with a process crash for a trigger. Read off the
    SQL rather than inferred, the way `check_audit_ip` reads a call site."""
    import inspect

    from apps.api.reliability import service

    source = inspect.getsource(service.mark_outbox_published)
    statements = source.count("UPDATE outbox_messages")
    assert statements == 1, f"{statements} UPDATEs — the scrub must ride the status flip"
    assert "payload = '{}'::jsonb" in source
