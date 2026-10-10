"""Which client onboardings are still unfinished (D-695).

The operator's part of onboarding is now two steps — create the account, invite the
owner — and the client's part is the business profile, which they fill in themselves. An
onboarding is unfinished while the account is still `onboarding` and either nobody has
accepted an invitation yet or the profile still lacks what an agent needs to go live.

`directory` is an `admin_session()`, the only session that can enumerate tenants. Each
candidate is then read under its OWN tenant session, so the profile, the members and the
contacts are read under ordinary RLS; this module holds no cross-tenant view of any table
but `organizations`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.db.session import tenant_session
from apps.api.tenancy.business_profile import go_live_blockers, load_profile, step_state
from apps.api.tenancy.models import PROFILE_STEPS
from apps.api.tenancy.onboarding import OwnerStatus, onboarding_finished, owner_status


@dataclass(frozen=True, slots=True)
class UnfinishedOnboarding:
    tenant_id: UUID
    name: str
    slug: str
    created_at: datetime
    vertical_template: str
    #: Has anybody accepted into this account yet? False covers "never invited", "invite
    #: outstanding" and "link expired" alike: in all three the operator still owes an invite.
    owner_present: bool
    #: Setup steps the client has answered or skipped, out of `steps_total`.
    steps_done: int
    steps_total: int
    #: What still stops an agent going live (`business_profile.go_live_blockers`' codes).
    blockers: tuple[str, ...]
    #: When the client last saved their profile, or None if they never have.
    profile_saved_at: datetime | None
    #: Is a live (unused, unexpired) invitation out? With `owner_present` False and this
    #: False the account has nobody invited at all, and the operator must invite.
    invite_pending: bool


_CANDIDATES = (
    "SELECT id, name, slug, created_at, vertical_template FROM organizations "
    "WHERE deleted_at IS NULL AND status = 'onboarding' ORDER BY created_at DESC"
)


async def unfinished_onboardings(directory: AsyncSession) -> list[UnfinishedOnboarding]:
    """Every account whose onboarding is unfinished, most recently worked on first.

    N+1 by construction, bounded by the accounts still in onboarding — the same trade
    `admin/holds.py` documents.
    """
    rows = (await directory.execute(text(_CANDIDATES))).all()
    unfinished: list[UnfinishedOnboarding] = []
    for org in rows:
        tenant_id = UUID(str(org[0]))
        async with tenant_session(tenant_id) as scoped:
            profile = await load_profile(scoped, tenant_id=tenant_id)
            status = await owner_status(scoped)
        owner = status.owner_present
        blockers = tuple(go_live_blockers(profile))
        if onboarding_finished(owner_present=owner, blockers=blockers):
            continue
        unfinished.append(
            UnfinishedOnboarding(
                tenant_id=tenant_id,
                name=str(org[1]),
                slug=str(org[2]),
                created_at=org[3],
                vertical_template=str(org[4]),
                owner_present=owner,
                steps_done=sum(step_state(profile, s) != "todo" for s in PROFILE_STEPS),
                steps_total=len(PROFILE_STEPS),
                blockers=blockers,
                profile_saved_at=profile.updated_at,
                invite_pending=status.invite_pending,
            )
        )
    unfinished.sort(key=lambda row: row.profile_saved_at or row.created_at, reverse=True)
    return unfinished


__all__ = ["OwnerStatus", "UnfinishedOnboarding", "owner_status", "unfinished_onboardings"]
