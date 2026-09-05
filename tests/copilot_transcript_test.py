"""`copilot_conversation_turns` (migration c7e0b2a94f13, D-540): isolation, lifetime, bounds.

Hard rule 1's test is `test_a_second_tenant_sees_zero_turns`, and the migration is
incomplete without it: a new tenant table's isolation claim is TESTED — read AND written
from a second tenant's RLS scope, requiring zero rows — not assumed.

The rest pins the three properties the founder's decisions rest on, each of which is a
claim this feature makes to a client rather than an implementation detail:

* the conversation belongs to the PERSON and is shared across their devices, so a second
  device reading it sees the first device's turns;
* it ends when their LAST session ends — and **not** when one of several ends, which is
  the half the two decisions pull against and the half a naive implementation gets wrong;
* what is stored is redacted, so a phone number a person typed does not reach a column.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.copilot import session_run, transcript
from apps.api.db.session import credential_session, tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

pytestmark = pytest.mark.asyncio


async def _tenant_with_user() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Transcript Clinic",
        slug=f"chat-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = created["id"]
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


async def _open_session(
    user_id: uuid.UUID,
    *,
    started: datetime,
    ends: datetime,
    realm: str = "client",
    family: uuid.UUID | None = None,
) -> uuid.UUID:
    """One `auth_sessions` row with a chosen interval.

    Written directly rather than through `authn.sessions.issue_session`, and the reason is
    that the thing under test is what the ROWS mean: a run is derived from intervals, and
    a test that could only produce intervals starting now could not express "signed out an
    hour ago" at all. The columns are the ones `session_run._INTERVALS` reads.
    """
    session_id = uuid.uuid4()
    async with credential_session() as session:
        await session.execute(
            text(
                "INSERT INTO auth_sessions (id, family_id, realm, subject_id, token_hash, "
                "last_seen_at, idle_expires_at, absolute_expires_at, created_at, updated_at) "
                "VALUES (:id, :fid, :realm, :sid, :hash, :start, :ends, :ends, :start, :start)"
            ),
            {
                "id": session_id,
                "fid": family or uuid.uuid4(),
                "realm": realm,
                "sid": user_id,
                "hash": session_id.bytes,
                "start": started,
                "ends": ends,
            },
        )
    return session_id


async def _turn_count(tenant_id: uuid.UUID, user_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM copilot_conversation_turns WHERE user_id = :uid"),
                    {"uid": user_id},
                )
            ).scalar()
            or 0
        )


async def test_a_second_tenant_sees_zero_turns() -> None:
    """HARD RULE 1. One tenant's conversation is invisible AND unwritable from another's
    scope — the read half AND the write half, because a FORCEd policy with no WITH CHECK
    would pass the first and fail the second silently."""
    first_tenant, first_user = await _tenant_with_user()
    second_tenant, _ = await _tenant_with_user()
    run = datetime.now(UTC)

    async with tenant_session(first_tenant) as session:
        await transcript.append_exchange(
            session,
            realm=transcript.CLIENT,
            owner_id=first_user,
            tenant_id=first_tenant,
            run_started_at=run,
            screen_route="/leads",
            question="how many leads came in today",
            answer="Eleven.",
        )
    assert await _turn_count(first_tenant, first_user) == 2

    async with tenant_session(second_tenant) as session:
        visible = (
            await session.execute(text("SELECT count(*) FROM copilot_conversation_turns"))
        ).scalar()
        assert int(visible or 0) == 0
        # And the write half: a row addressed at the FIRST tenant, inserted from the
        # second's scope, must not land. The policy has no WITH CHECK of its own — the
        # `USING` clause of a FORCEd policy applies to INSERT too — so this is the
        # assertion that proves it rather than the assumption that it does.
        with pytest.raises(DBAPIError):
            await session.execute(
                text(
                    "INSERT INTO copilot_conversation_turns "
                    "(id, tenant_id, user_id, run_started_at, role, content, screen_route, "
                    "created_at, updated_at) VALUES "
                    "(:id, :tid, :uid, now(), 'user', 'smuggled', '/leads', now(), now())"
                ),
                {"id": uuid.uuid4(), "tid": first_tenant, "uid": first_user},
            )


async def test_the_same_person_sees_one_conversation_from_two_devices() -> None:
    """FOUNDER'S DECISION 2. The conversation is keyed on the PERSON, so a second device
    loading it gets the first device's turns — there is no per-device thread to diverge."""
    tenant_id, user_id = await _tenant_with_user()
    run = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await transcript.append_exchange(
            session,
            realm=transcript.CLIENT,
            owner_id=user_id,
            tenant_id=tenant_id,
            run_started_at=run,
            screen_route="/agents",
            question="what does the greeting say",
            answer="It opens with the clinic's name.",
        )
    # A DIFFERENT SESSION OBJECT — which is what a second device is, on this side of the
    # wire: a separate connection, the same person, the same run.
    async with tenant_session(tenant_id) as other_device:
        page = await transcript.load(
            other_device,
            realm=transcript.CLIENT,
            owner_id=user_id,
            run_started_at=run,
        )
    assert [turn.role for turn in page.turns] == ["user", "assistant"]
    assert page.turns[0].content.endswith("what does the greeting say")


async def test_a_new_run_deletes_the_previous_conversation() -> None:
    """FOUNDER'S DECISION 1. Turns from a run that has ended are gone before they are
    read — cleared by the read itself, not left for a cron to notice."""
    tenant_id, user_id = await _tenant_with_user()
    old_run = datetime.now(UTC) - timedelta(hours=5)
    async with tenant_session(tenant_id) as session:
        await transcript.append_exchange(
            session,
            realm=transcript.CLIENT,
            owner_id=user_id,
            tenant_id=tenant_id,
            run_started_at=old_run,
            screen_route="/leads",
            question="anything from yesterday",
            answer="Two enquiries.",
        )
    assert await _turn_count(tenant_id, user_id) == 2

    new_run = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        page = await transcript.load(
            session, realm=transcript.CLIENT, owner_id=user_id, run_started_at=new_run
        )
    assert page.turns == ()
    assert await _turn_count(tenant_id, user_id) == 0


async def test_a_conversation_is_capped_from_the_front() -> None:
    """The ceiling deletes the OLDEST turns rather than refusing the newest: a person
    whose conversation has reached the cap wants to keep talking."""
    tenant_id, user_id = await _tenant_with_user()
    run = datetime.now(UTC)
    exchanges = (transcript.MAX_STORED_TURNS // 2) + 3
    async with tenant_session(tenant_id) as session:
        for index in range(exchanges):
            await transcript.append_exchange(
                session,
                realm=transcript.CLIENT,
                owner_id=user_id,
                tenant_id=tenant_id,
                run_started_at=run,
                screen_route="/leads",
                question=f"question {index}",
                answer=f"answer {index}",
            )
    assert await _turn_count(tenant_id, user_id) == transcript.MAX_STORED_TURNS
    async with tenant_session(tenant_id) as session:
        page = await transcript.load(
            session, realm=transcript.CLIENT, owner_id=user_id, run_started_at=run, limit=2
        )
    # The NEWEST page, and the newest exchange is the last one written.
    assert page.turns[-1].content.endswith(f"answer {exchanges - 1}")
    assert page.has_more is True


async def test_a_number_a_person_typed_does_not_reach_a_column() -> None:
    """The compliance property the whole store rests on. `redact()` runs on the way in,
    so the phone-keyed §12 erasure has nothing to find and neither does a database dump."""
    tenant_id, user_id = await _tenant_with_user()
    run = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await transcript.append_exchange(
            session,
            realm=transcript.CLIENT,
            owner_id=user_id,
            tenant_id=tenant_id,
            run_started_at=run,
            screen_route="/leads",
            question="call +919876543210 back about the scan",
            answer="I have noted it.",
        )
        page = await transcript.load(
            session, realm=transcript.CLIENT, owner_id=user_id, run_started_at=run
        )
    stored = " ".join(turn.content for turn in page.turns)
    assert "9876543210" not in stored
    assert "scan" in stored


async def test_signing_out_one_device_does_not_end_the_run() -> None:
    """THE HALF THE TWO DECISIONS PULL AGAINST, and the one a naive implementation gets
    wrong. Two overlapping sessions, one revoked: the run start must not move, so the
    thread open on the other device survives."""
    _, user_id = await _tenant_with_user()
    now = datetime.now(UTC)
    desktop = await _open_session(
        user_id, started=now - timedelta(hours=3), ends=now + timedelta(hours=6)
    )
    await _open_session(user_id, started=now - timedelta(hours=1), ends=now + timedelta(hours=8))
    before = await session_run.current_run_start(realm="client", subject_id=user_id)
    assert before is not None

    async with credential_session() as session:
        await session.execute(
            text(
                "UPDATE auth_sessions SET revoked_at = now(), revoked_reason = 'signed_out' "
                "WHERE id = :id"
            ),
            {"id": desktop},
        )
    after = await session_run.current_run_start(realm="client", subject_id=user_id)
    assert after == before


async def test_a_gap_between_sessions_starts_a_new_run() -> None:
    """…and the other half: when the LAST session really did end, the next sign-in is a
    new run, so the conversation from before it is not carried over."""
    _, user_id = await _tenant_with_user()
    now = datetime.now(UTC)
    await _open_session(user_id, started=now - timedelta(hours=9), ends=now - timedelta(hours=4))
    await _open_session(user_id, started=now - timedelta(hours=1), ends=now + timedelta(hours=6))
    started = await session_run.current_run_start(realm="client", subject_id=user_id)
    assert started is not None
    # The LATER sign-in, not the earlier one: the four-hour hole between them is a gap.
    assert started > now - timedelta(hours=2)


async def test_a_rotation_is_not_a_new_run() -> None:
    """Rotation supersedes a row and inserts its successor at the SAME instant
    (`authn/sessions.rotate_session`). Under `>` rather than `>=` in the cover test,
    proving a second factor would wipe the conversation the person was having."""
    _, user_id = await _tenant_with_user()
    now = datetime.now(UTC)
    rotated_at = now - timedelta(minutes=30)
    family = uuid.uuid4()
    first = await _open_session(
        user_id, started=now - timedelta(hours=2), ends=now + timedelta(hours=6), family=family
    )
    async with credential_session() as session:
        await session.execute(
            text("UPDATE auth_sessions SET superseded_at = :at WHERE id = :id"),
            {"at": rotated_at, "id": first},
        )
    await _open_session(user_id, started=rotated_at, ends=now + timedelta(hours=6), family=family)
    started = await session_run.current_run_start(realm="client", subject_id=user_id)
    assert started is not None
    # The ORIGINAL sign-in, not the rotation.
    assert started < rotated_at


async def test_no_live_session_is_no_run() -> None:
    """The sweep's whole predicate, and the answer a caller must read as a clearance
    rather than as an error."""
    _, user_id = await _tenant_with_user()
    now = datetime.now(UTC)
    await _open_session(user_id, started=now - timedelta(hours=9), ends=now - timedelta(hours=4))
    assert await session_run.current_run_start(realm="client", subject_id=user_id) is None
    assert user_id not in await session_run.subjects_with_live_sessions(realm="client")
