"""An operator's "Stay signed in" switch: who may move it, and what moving it does (D-766).

The switch is `admin_users.stay_signed_in`. `sessions.session_policy` reads it on every
verification; this module is the only writer.

Two doors, in opposite directions:

* **The operator, on their own account** (`set_own`). Switching it ON lengthens the session
  that asked to the long bounds, and needs a second factor proved within
  `stepup.REAUTH_MAX_AGE` (checked by the route), because a stolen cookie must not be able
  to turn itself into a fourteen-day one. Switching it OFF needs nothing beyond a live,
  second-factor-complete session: it only ever shortens, and a person leaving a shared
  device should not meet a code prompt on the way out.
* **A superadmin, on another operator's account** (`switch_off_for`), OFF only. There is
  no door that switches it on for someone else: the longer session is a risk the operator
  takes on their own devices, and nobody can take it on their behalf.

Both doors shorten every live session of that operator in the same transaction as the
column write (`sessions.shorten_subject_sessions`), and both write an audit row with the
change. A write that changes nothing writes no audit row, as `operators.set_operator_role`
does.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.authn.sessions import (
    VerifiedSession,
    lengthen_session,
    shorten_subject_sessions,
)
from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger
from apps.api.db.result import rowcount_of
from apps.api.db.session import credential_session

log = get_logger(__name__)

#: The audit action for every change of the switch, by either door.
AUDIT_ACTION = "admin.stay_signed_in_changed"


@dataclass(frozen=True, slots=True)
class OwnChange:
    """What `set_own` did to the caller's own session."""

    stay_signed_in: bool
    #: The calling session's absolute bound after the change, for the cookie's `Max-Age`.
    absolute_expires_at: datetime


async def _write_switch(
    session: AsyncSession, *, operator_id: UUID, on: bool, at: datetime
) -> bool:
    """Set the column on a LIVE operator. True if this call changed it."""
    return (
        rowcount_of(
            await session.execute(
                text(
                    "UPDATE admin_users SET stay_signed_in = :on, updated_at = :now "
                    "WHERE id = :id AND deactivated_at IS NULL AND stay_signed_in <> :on"
                ),
                {"id": operator_id, "on": on, "now": at},
            )
        )
        == 1
    )


async def set_own(
    *, verified: VerifiedSession, on: bool, ip: str | None, now: datetime | None = None
) -> OwnChange:
    """Move the caller's own switch. The route has already checked the second factor.

    ON lengthens THIS session only. Its absolute bound is moved to fourteen days from the
    sign-in, so the cookie the route re-sets can carry the matching `Max-Age`. OFF cuts
    every live session of this operator, this one included, back to 30 minutes idle and 8
    hours from its sign-in; a session already past those ends here.
    """
    at = now or datetime.now(UTC)
    async with credential_session() as session:
        changed = await _write_switch(session, operator_id=verified.subject_id, on=on, at=at)
        if on:
            expires = await lengthen_session(session, session_id=verified.session_id, now=at)
            if expires is None:
                # Signed out or rotated between the verification and here. Raising rolls
                # the column write back with it: the switch moves only together with the
                # session that asked for it.
                raise ProblemError.unauthorized("Your session is not valid. Sign in again.")
        else:
            await shorten_subject_sessions(session, subject_id=verified.subject_id, now=at)
            expires = verified.absolute_expires_at
        if changed:
            await write_audit(
                session,
                action=AUDIT_ACTION,
                actor=Principal(
                    realm="admin", user_id=verified.subject_id, tenant_id=None, role=None
                ),
                object_type="admin_user",
                object_id=str(verified.subject_id),
                ip=ip,
                summary={"stay_signed_in": on, "by": "self"},
            )
    log.info(
        "admin_stay_signed_in_set",
        extra={"operator_id": str(verified.subject_id), "on": on, "changed": changed},
    )
    return OwnChange(stay_signed_in=on, absolute_expires_at=expires)


async def switch_off_for(
    session: AsyncSession,
    *,
    actor: Principal,
    operator_id: UUID,
    reason: str,
    ip: str | None,
    now: datetime | None = None,
) -> bool:
    """A superadmin switches another operator's setting OFF. True if it was on.

    Takes the caller's `credential_session` (`operators.switch_off_stay_signed_in`, which
    has already proved the account live). The sessions are shortened even when the switch
    was already off, which costs nothing and means the act always leaves that operator on
    the short bounds. Only a change is audited.
    """
    at = now or datetime.now(UTC)
    changed = await _write_switch(session, operator_id=operator_id, on=False, at=at)
    await shorten_subject_sessions(session, subject_id=operator_id, now=at)
    if changed:
        await write_audit(
            session,
            action=AUDIT_ACTION,
            actor=actor,
            object_type="admin_user",
            object_id=str(operator_id),
            ip=ip,
            summary={"stay_signed_in": False, "by": "superadmin", "reason": reason},
        )
    log.warning(
        "admin_stay_signed_in_switched_off",
        extra={
            "operator_id": str(operator_id),
            "actor_id": str(actor.user_id),
            "changed": changed,
        },
    )
    return changed


__all__ = ["AUDIT_ACTION", "OwnChange", "set_own", "switch_off_for"]
