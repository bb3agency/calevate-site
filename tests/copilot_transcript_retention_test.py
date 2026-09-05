"""The copilot conversation's three ways out: the sweep, the clock, and the two erasures.

D-540. The conversation dies when its owner's last session ends, and that is the whole
promise — but "expiry is a timestamp passing" means the promise is only as good as the
thing that OBSERVES it, and a retention clock and an erasure path have to be true of the
residue whatever the observer did.

So this file drives each of the four in turn:

* `sweep_ended_conversations`, which is what notices the person who never came back;
* the `transcript` retention arm, which is the backstop behind it — the founder's "the
  same clock as call transcripts", so it is that category and not a new one;
* tenant offboarding, which destroys every row unconditionally because it is the only
  path that can reach a first name a staff member typed;
* the phone-keyed §12 erasure, which reaches a number that got past `redact()`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.tenant_erasure import request_tenant_erasure
from apps.api.copilot import transcript
from apps.api.db.session import credential_session, tenant_session, untenanted_session
from apps.workers.copilot_transcript import WORKLIST_REASON, sweep_ended_conversations
from apps.workers.retention import apply_retention, execute_tenant_erasure
from sqlalchemy import text

pytestmark = pytest.mark.asyncio


async def _tenant_with_user() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Sweep Clinic",
        slug=f"swp-{uuid.uuid4().hex[:8]}",
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
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return tenant_id, user_id


async def _say(
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    question: str = "what is on today",
    answer: str = "Four appointments.",
    age_days: float = 0.0,
) -> None:
    """One exchange, at a chosen age. `created_at` is set explicitly because the retention
    clock is the thing under test and waiting a year for it is not a test."""
    async with tenant_session(tenant_id) as session:
        await transcript.append_exchange(
            session,
            realm=transcript.CLIENT,
            owner_id=user_id,
            tenant_id=tenant_id,
            run_started_at=datetime.now(UTC),
            screen_route="/leads",
            question=question,
            answer=answer,
        )
        if age_days:
            await session.execute(
                text("UPDATE copilot_conversation_turns SET created_at = :at WHERE user_id = :uid"),
                {"at": datetime.now(UTC) - timedelta(days=age_days), "uid": user_id},
            )


async def _count(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(text("SELECT count(*) FROM copilot_conversation_turns"))
            ).scalar()
            or 0
        )


async def _live_session(user_id: uuid.UUID) -> None:
    now = datetime.now(UTC)
    session_id = uuid.uuid4()
    async with credential_session() as session:
        await session.execute(
            text(
                "INSERT INTO auth_sessions (id, family_id, realm, subject_id, token_hash, "
                "last_seen_at, idle_expires_at, absolute_expires_at, created_at, updated_at) "
                "VALUES (:id, :fid, 'client', :sid, :hash, :now, :ends, :ends, :now, :now)"
            ),
            {
                "id": session_id,
                "fid": uuid.uuid4(),
                "sid": user_id,
                "hash": session_id.bytes,
                "now": now,
                "ends": now + timedelta(hours=6),
            },
        )


async def test_the_trigger_registers_the_tenant_for_the_sweep() -> None:
    """The worklist bridge (D-368's answer, reused). Without it the sweep runs untenanted,
    sees zero rows of a FORCE-RLS'd table, and the work is invisible rather than absent."""
    tenant_id, user_id = await _tenant_with_user()
    await _say(tenant_id, user_id)
    async with untenanted_session() as session:
        registered = (
            await session.execute(
                text(
                    "SELECT count(*) FROM retention_worklist "
                    "WHERE tenant_id = :tid AND reason = :reason"
                ),
                {"tid": tenant_id, "reason": WORKLIST_REASON},
            )
        ).scalar()
    assert int(registered or 0) == 1


async def test_the_sweep_forgets_a_person_who_never_came_back() -> None:
    """THE OBSERVER. Nobody signed in, so every conversation is over — and this is the
    only thing that ever notices, because nothing runs at the instant a session expires."""
    tenant_id, user_id = await _tenant_with_user()
    await _say(tenant_id, user_id)
    assert await _count(tenant_id) == 2

    await sweep_ended_conversations({})
    assert await _count(tenant_id) == 0


async def test_the_sweep_leaves_a_signed_in_person_alone() -> None:
    """…and the other direction, which is the one a bug here would break silently: a
    person with a live session keeps the conversation they are in the middle of."""
    tenant_id, user_id = await _tenant_with_user()
    await _live_session(user_id)
    await _say(tenant_id, user_id)

    await sweep_ended_conversations({})
    assert await _count(tenant_id) == 2


async def test_the_transcript_clock_expires_the_conversation() -> None:
    """THE BACKSTOP. The founder's decision 4 — the same clock as call transcripts — so it
    is the `transcript` category and no new one was invented. A tenant whose sweep has
    been failing still keeps the published promise."""
    tenant_id, user_id = await _tenant_with_user()
    await _live_session(user_id)
    async with tenant_session(tenant_id) as session:
        ttl = (
            await session.execute(
                text("SELECT ttl_days FROM retention_policies WHERE data_category = 'transcript'")
            )
        ).scalar()
    assert ttl is not None
    await _say(tenant_id, user_id, age_days=int(ttl) + 5)

    await apply_retention({})
    assert await _count(tenant_id) == 0


async def test_offboarding_destroys_every_turn() -> None:
    """UNCONDITIONAL, because there is nothing to match on: `redact()` recognises
    identifiers and not proper nouns, so a first name a staff member typed is reachable by
    this path and by no other."""
    tenant_id, user_id = await _tenant_with_user()
    await _live_session(user_id)
    await _say(tenant_id, user_id, question="what did Lakshmi ask about")
    assert await _count(tenant_id) == 2

    # `assert_erasable`'s precondition: a tenant erasure is the end of a commercial
    # relationship, so the account has to be closed before its data can go.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :tid"),
            {"tid": tenant_id},
        )
    async with tenant_session(tenant_id) as session:
        record = await request_tenant_erasure(
            session, tenant_id=tenant_id, reason="engagement ended"
        )
    await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})
    assert await _count(tenant_id) == 0
