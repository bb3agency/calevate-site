"""An account leaves `onboarding` when its onboarding is finished (D-695).

Finished means an owner has joined and the business profile holds what an agent needs to
go live — the same rule the operator's unfinished-onboardings list uses. The move happens
on the save or the acceptance that completes it, is audited, and never touches an account
an operator has already moved.

Concurrency: every case creates its own run-unique tenant and looks only at it.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.admin import service as admin_service
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.tenancy.onboarding import complete_onboarding_if_finished
from apps.api.tenancy.profile_service import ProfilePatch, save_profile
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist, seed_business_profile


async def _tenant() -> uuid.UUID:
    created = await create_org_with_receptionist(
        name="Sunrise Dental",
        slug=f"onbd-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _user() -> uuid.UUID:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": user_id, "e": f"{user_id}@example.com"},
        )
    return user_id


async def _owner(tenant_id: uuid.UUID) -> None:
    user_id = await _user()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )


async def _status(tenant_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT status FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
        )


async def _completions(tenant_id: uuid.UUID) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                        "AND action = 'tenant.onboarding_completed'"
                    ),
                    {"t": tenant_id},
                )
            ).scalar_one()
        )


async def _save(tenant_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await save_profile(
            session,
            tenant_id=tenant_id,
            patch=ProfilePatch.model_validate({"booking_rules": "Walk-ins welcome."}),
            user_id=None,
        )


async def test_the_save_that_finishes_setup_moves_the_account_to_active() -> None:
    tenant_id = await _tenant()
    await _owner(tenant_id)
    await seed_business_profile(tenant_id)
    assert await _status(tenant_id) == "onboarding"

    await _save(tenant_id)

    assert await _status(tenant_id) == "active"
    assert await _completions(tenant_id) == 1


async def test_a_profile_alone_does_not_finish_onboarding() -> None:
    """FAILS IF the move ignores the owner: an account nobody can sign in to is not set up."""
    tenant_id = await _tenant()
    await seed_business_profile(tenant_id)
    await _save(tenant_id)
    assert await _status(tenant_id) == "onboarding"
    assert await _completions(tenant_id) == 0


async def test_accepting_the_invite_finishes_an_account_whose_profile_is_ready() -> None:
    tenant_id = await _tenant()
    await seed_business_profile(tenant_id)
    user_id = await _user()
    async with tenant_session(tenant_id) as session:
        _, token = await admin_service.create_invitation(
            session,
            tenant_id=tenant_id,
            email=f"{user_id}@example.com",
            role="owner",
            created_by=None,
        )
    async with tenant_session(tenant_id) as session:
        await admin_service.accept_invitation(session, raw_token=token, user_id=user_id)
    assert await _status(tenant_id) == "active"


async def test_an_operator_set_state_is_never_overwritten() -> None:
    """FAILS IF the move is not a CAS on `onboarding`: a suspended account whose setup is
    complete must stay suspended."""
    tenant_id = await _tenant()
    await _owner(tenant_id)
    await seed_business_profile(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'suspended' WHERE id = :t"), {"t": tenant_id}
        )
    async with tenant_session(tenant_id) as session:
        assert await complete_onboarding_if_finished(session, tenant_id=tenant_id) is False
    assert await _status(tenant_id) == "suspended"
    assert await _completions(tenant_id) == 0


async def test_the_hourly_sweep_moves_an_account_finished_before_the_move_existed() -> None:
    """FAILS IF only a save or an acceptance can move an account: one whose owner and
    profile were already in place when D-710 shipped would read "Onboarding" for good."""
    from apps.workers.onboarding_completion import complete_finished_onboardings

    finished = await _tenant()
    await _owner(finished)
    await seed_business_profile(finished)
    unfinished = await _tenant()
    await seed_business_profile(unfinished)

    summary = await complete_finished_onboardings({})

    assert "moved=" in summary
    assert await _status(finished) == "active"
    assert await _completions(finished) == 1
    assert await _status(unfinished) == "onboarding", "no owner has joined it"


async def test_the_sweep_reaches_a_finished_account_behind_unfinished_newer_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The sweep reads accounts in `onboarding` newest first, capped. One it asks and finds
    unfinished is set aside for a while, so accounts nobody finishes cannot fill every read
    and leave an older finished one reading "Onboarding" for ever."""
    from apps.workers import onboarding_completion

    prefix = f"onbdsa{uuid.uuid4().hex[:6]}"

    async def _named(suffix: str) -> uuid.UUID:
        created = await create_org_with_receptionist(
            name="Sunrise Dental",
            slug=f"{prefix}-{suffix}",
            vertical_template="clinic",
            billing_email=None,
            language="te-IN",
            created_by=None,
        )
        return uuid.UUID(str(created["id"]))

    finished = await _named("old")
    await _owner(finished)
    await seed_business_profile(finished)
    await _named("new")
    monkeypatch.setattr(
        onboarding_completion,
        "_ONBOARDING",
        onboarding_completion._ONBOARDING.replace(
            "WHERE deleted_at IS NULL", f"WHERE slug LIKE '{prefix}-%' AND deleted_at IS NULL"
        ),
    )
    monkeypatch.setattr(onboarding_completion, "SWEEP_BUDGET", 1)

    await onboarding_completion.complete_finished_onboardings({})
    await onboarding_completion.complete_finished_onboardings({})

    assert await _status(finished) == "active"
