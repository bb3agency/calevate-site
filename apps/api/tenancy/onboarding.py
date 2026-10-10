"""When an account's onboarding is finished, and the move out of `onboarding` (D-695).

An account is born `onboarding` (`admin/service._write_tenant_root`). D-695 defined what
finishing it means — somebody has accepted an invitation into the account, and the business
profile holds what every agent needs before it may go live (`go_live_blockers`) — and
`admin/onboarding.unfinished_onboardings` drops an account from the operator's work list
the moment both hold. Nothing moved the stored status, so a finished account kept reading
"Onboarding" on every admin screen while the work list said it was done.

`complete_onboarding_if_finished` is that move. It is called where either half can become
true: after a business profile save and after an invitation is accepted. It is one-way and
only ever leaves `onboarding`: an operator's `active`/`suspended` and a closure are never
touched, and a later edit that empties the profile does not send a working account back.

KYC, the no-cold-calls pledge and payment are NOT part of it. They are separate axes with
their own gates (`compliance/service.check_dispatch`, D-692, D-697): inbound answering needs
none of them, and a trial account that has not paid is still onboarded once its business is
set up. `organizations.status` gates nothing between `onboarding` and `active` — both dial
(`compliance/service._STOPPED_STATUSES`) — so this move changes what the console says and
which work list the account is on, never what the account may do.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.compliance.audit import write_audit
from apps.api.core.logging import get_logger
from apps.api.tenancy.business_profile import go_live_blockers, load_profile

log = get_logger(__name__)

#: Under the tenant session `memberships` is RLS-scoped to this account; `users` is not.
_OWNER_PRESENT = (
    "SELECT 1 FROM memberships m JOIN users u ON u.id = m.user_id "
    "WHERE u.deactivated_at IS NULL LIMIT 1"
)
_INVITE_PENDING = "SELECT 1 FROM invitations WHERE used_at IS NULL AND expires_at > now() LIMIT 1"

#: The CAS: only an account still in `onboarding` moves, so a concurrent operator change
#: or a closure always wins.
_COMPLETE = (
    "UPDATE organizations SET status = 'active', updated_at = now() "
    "WHERE id = :tid AND status = 'onboarding' AND deleted_at IS NULL RETURNING id"
)


@dataclass(frozen=True, slots=True)
class OwnerStatus:
    owner_present: bool
    invite_pending: bool


async def owner_status(scoped: AsyncSession) -> OwnerStatus:
    """Whether anybody has joined this account, and whether an invitation is still live.
    `scoped` is the tenant's own session."""
    owner = (await scoped.execute(text(_OWNER_PRESENT))).first() is not None
    pending = (await scoped.execute(text(_INVITE_PENDING))).first() is not None
    return OwnerStatus(owner_present=owner, invite_pending=pending)


def onboarding_finished(*, owner_present: bool, blockers: list[str] | tuple[str, ...]) -> bool:
    """THE definition of a finished onboarding, shared by the work list and the move."""
    return owner_present and not blockers


async def complete_onboarding_if_finished(session: AsyncSession, *, tenant_id: UUID) -> bool:
    """Move this account from `onboarding` to `active` if its onboarding is finished.

    Runs in the caller's transaction on the tenant's own session, so the move commits with
    the save or the acceptance that finished it. Returns whether it moved.
    """
    status = (
        await session.execute(
            text("SELECT status FROM organizations WHERE id = :tid"), {"tid": tenant_id}
        )
    ).scalar_one_or_none()
    if status != "onboarding":
        return False
    owner = await owner_status(session)
    blockers = go_live_blockers(await load_profile(session, tenant_id=tenant_id))
    if not onboarding_finished(owner_present=owner.owner_present, blockers=blockers):
        return False
    moved = (await session.execute(text(_COMPLETE), {"tid": tenant_id})).first() is not None
    if moved:
        await write_audit(
            session,
            action="tenant.onboarding_completed",
            actor_type="system",
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
            summary={"status": "active"},
        )
        log.info("tenant_onboarding_completed", extra={"tenant_id": str(tenant_id)})
    return moved


__all__ = [
    "OwnerStatus",
    "complete_onboarding_if_finished",
    "onboarding_finished",
    "owner_status",
]
