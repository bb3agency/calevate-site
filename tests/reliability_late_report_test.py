"""An abandoned holder reports its outcome after somebody else finished the work.

`claim_idempotency` and `claim_inbox_event` both hand a lapsed claim to a SECOND holder on
purpose — "a crashed attempt must not own the key until the TTL sweep", "an at-most-once
engine event whose key says duplicate is a silently dropped call". That design decision
creates a state in which TWO callers legitimately hold the same row id, and the first one
is by definition the one whose report arrives late.

`mark_outbox_failed` already argues at length why its own `AND status = 'pending'` is
"load-bearing rather than decorative": without it "a late failure report drags a message
that has ALREADY been published back to pending, and the next dispatcher tick queues its
job a second time". The four terminal writers in this file had no such guard, and the
consequence is worse than the outbox's because there is no dedupe behind them:

* an idempotency record reopened by a late `fail_idempotency` answers the client's next
  retry `fresh` instead of replaying the stored response, so `POST /v1/leads/{id}/call`
  places a SECOND REAL PHONE CALL and `POST /v1/calls/{id}/assist` pays for a second model
  run;
* an inbox row reopened by a late `mark_inbox_failed` makes the vendor's next retry
  re-drive the whole post-call pipeline for a call already metered and notified on.

HOW THE OVERLAP IS PRODUCED, and why it is not a contrivance: the lease is evaluated as
`updated_at < now() - CLAIM_LEASE`, so "the first holder has been silent for ten minutes"
is expressed by moving `updated_at` back rather than by sleeping. That is the exact
condition the re-claim CAS is written to detect; nothing else about the sequence is
simulated, and every state transition below is the production function.

The second half of the file pins D-322: a deadline written by the app's clock and judged
by the database's is two clocks on one number.

SHARED DATABASE DISCIPLINE: every row hangs off ids/keys this module mints, and the
fixtures delete exactly those.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import timedelta

import pytest
import pytest_asyncio
from apps.api.db.session import untenanted_session
from apps.api.reliability.service import (
    CLAIM_LEASE,
    IDEMPOTENCY_TTL,
    body_hash,
    claim_idempotency,
    claim_inbox_event,
    complete_idempotency,
    fail_idempotency,
    mark_inbox_failed,
    mark_inbox_processed,
)
from sqlalchemy import text

RUN = uuid.uuid4().hex[:12]
SCOPE = f"late-report-{RUN}"
PROVIDER = f"late-report-{RUN}"


@pytest_asyncio.fixture(autouse=True)
async def _cleanup() -> AsyncIterator[None]:
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM idempotency_records WHERE scope_key = :s"), {"s": SCOPE}
        )
        await session.execute(
            text("DELETE FROM webhook_inbox_events WHERE provider = :p"), {"p": PROVIDER}
        )


async def _age_claim(table: str, row_id: uuid.UUID) -> None:
    """Make the holder look silent for longer than `CLAIM_LEASE`.

    The lease is the ONLY thing that distinguishes "in flight" from "abandoned", and it
    reads `updated_at`. Moving that column back is how a ten-minute silence is expressed
    in a test that must finish in a second — not a shortcut around the mechanism, but the
    mechanism's own input.
    """
    async with untenanted_session() as session:
        await session.execute(
            text(f"UPDATE {table} SET updated_at = now() - :age WHERE id = :id"),
            {"age": CLAIM_LEASE + timedelta(minutes=1), "id": row_id},
        )


# ══════════════════════════ idempotency ══════════════════════════


async def _claim(key: str) -> object:
    async with untenanted_session() as session:
        return await claim_idempotency(
            session,
            scope=SCOPE,
            route="/v1/leads/{lead_id}/call",
            method="POST",
            key=key,
            request_hash=body_hash({"lead": key}),
        )


@pytest.mark.asyncio
async def test_a_late_failure_cannot_reopen_a_completed_idempotency_record() -> None:
    key = f"key-{uuid.uuid4().hex}"

    first = await _claim(key)
    assert first.state == "fresh"  # type: ignore[attr-defined]

    # The first holder goes silent. The lease lapses and the client's retry re-claims —
    # this is `claim_idempotency`'s designed recovery, not a fault.
    await _age_claim("idempotency_records", first.record_id)  # type: ignore[attr-defined]
    second = await _claim(key)
    assert second.state == "fresh"  # type: ignore[attr-defined]
    assert second.record_id == first.record_id  # type: ignore[attr-defined]

    # The second holder does the work and stores its response.
    async with untenanted_session() as session:
        await complete_idempotency(
            session,
            record_id=second.record_id,  # type: ignore[attr-defined]
            response_status=200,
            response_payload={"call_id": "the-one-call-we-placed"},
        )

    # NOW the first holder finally comes back and reports its own defeat.
    async with untenanted_session() as session:
        await fail_idempotency(session, record_id=first.record_id)  # type: ignore[attr-defined]

    third = await _claim(key)
    assert third.state == "replay", (  # type: ignore[attr-defined]
        "a late failure report from an abandoned attempt reopened a COMPLETED record, so "
        "the next retry of this Idempotency-Key re-executes the mutation — for "
        "POST /v1/leads/{lead_id}/call that is a second real phone call"
    )
    assert third.response_payload == {"call_id": "the-one-call-we-placed"}  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_a_late_completion_cannot_overwrite_a_released_key() -> None:
    """The mirror: the abandoned holder SUCCEEDS late, after the key was released.

    Storing its response would answer the client's retry with the output of an attempt
    whose caller has long since been told it failed — and, on the assist path, bill for
    one run while replaying another's summary.
    """
    key = f"key-{uuid.uuid4().hex}"
    first = await _claim(key)
    await _age_claim("idempotency_records", first.record_id)  # type: ignore[attr-defined]
    second = await _claim(key)
    async with untenanted_session() as session:
        await fail_idempotency(session, record_id=second.record_id)  # type: ignore[attr-defined]
    async with untenanted_session() as session:
        await complete_idempotency(
            session,
            record_id=first.record_id,  # type: ignore[attr-defined]
            response_status=200,
            response_payload={"stale": True},
        )

    async with untenanted_session() as session:
        status = (
            await session.execute(
                text("SELECT status FROM idempotency_records WHERE id = :id"),
                {"id": first.record_id},  # type: ignore[attr-defined]
            )
        ).scalar_one()
    assert status == "failed", (
        "a late completion overwrote a key that had already been released; the client's "
        "retry would replay a response belonging to an attempt it was told had failed"
    )


# ══════════════════════════ webhook inbox ══════════════════════════


async def _claim_event(event_key: str) -> object:
    async with untenanted_session() as session:
        return await claim_inbox_event(
            session,
            provider=PROVIDER,
            event_key=event_key,
            payload_hash=body_hash({"execution": event_key}),
            event_name="call.completed",
        )


@pytest.mark.asyncio
async def test_a_late_failure_cannot_reopen_a_processed_inbox_event() -> None:
    event_key = f"exec-{uuid.uuid4().hex}"

    first = await _claim_event(event_key)
    assert first.state == "claimed"  # type: ignore[attr-defined]

    await _age_claim("webhook_inbox_events", first.row_id)  # type: ignore[attr-defined]
    second = await _claim_event(event_key)
    assert second.state == "claimed"  # type: ignore[attr-defined]

    async with untenanted_session() as session:
        await mark_inbox_processed(session, row_id=second.row_id)  # type: ignore[attr-defined]

    async with untenanted_session() as session:
        await mark_inbox_failed(
            session,
            row_id=first.row_id,  # type: ignore[attr-defined]
            error="the abandoned consumer finally gave up",
        )

    third = await _claim_event(event_key)
    assert third.state == "duplicate", (  # type: ignore[attr-defined]
        "a late failure report reopened an event that was already PROCESSED, so the "
        "vendor's next retry re-drives the post-call pipeline for a call that has "
        "already been metered, extracted and notified on"
    )


# ══════════════════════════ one clock per deadline (D-322) ══════════════════════════


@pytest.mark.asyncio
async def test_the_idempotency_ttl_is_measured_by_one_clock() -> None:
    """`expires_at - created_at` is EXACTLY the TTL, and the transaction is aged first.

    Postgres `now()` is transaction START time, so with `expires_at` computed in Python
    when the statement was built, this difference was the TTL plus however long the
    transaction had already been running — plus whatever the app and database clocks
    disagreed by. The `pg_sleep` is what makes that measurable rather than sub-millisecond:
    a request that reads a lead and checks a quota before claiming its key is doing the
    same thing more slowly.
    """
    key = f"key-{uuid.uuid4().hex}"
    async with untenanted_session() as session:
        await session.execute(text("SELECT pg_sleep(0.5)"))
        claim = await claim_idempotency(
            session,
            scope=SCOPE,
            route="/v1/leads/{lead_id}/call",
            method="POST",
            key=key,
            request_hash=body_hash({"lead": key}),
        )
        drift = (
            await session.execute(
                text("SELECT expires_at - created_at FROM idempotency_records WHERE id = :id"),
                {"id": claim.record_id},
            )
        ).scalar_one()

    assert drift == IDEMPOTENCY_TTL, (
        f"the record's lifetime is {drift}, not {IDEMPOTENCY_TTL}: `expires_at` and "
        "`created_at` were stamped by different clocks, so how long an Idempotency-Key "
        "survives depends on how busy the transaction that minted it was"
    )
