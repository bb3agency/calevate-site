"""Is this account still open for business? One predicate, both realms (D-194).

`assert_account_open` lived in `admin/service.py`, which is the module that OWNS account
lifecycle — so that was the right home right up until a CLIENT-realm path needed the same
question. `agents.service.publish_agent` is that path: it puts an agent on the phone, and
it asked nothing about whether the account it belongs to had been churned or erased, so an
operator with a hand-typed uuid could put an offboarded client's agent back into service —
answering calls, collecting caller numbers, against a tenant on a retention clock and, if
the account was erased, under a certificate saying its data is gone.

`agents/` importing `admin/` to ask would have been backwards: `tenancy/signup.py` already
imports `admin.service`, so the arrow points that way and adding the reverse one creates
the cycle. This module holds the predicate instead and imports nothing but `core` and `db`,
so every realm can ask without anybody importing anybody's service layer.

The behaviour is unchanged and deliberately so — this is a move, not a rewrite. The two
`admin/service.py` call sites were migrated in the same change rather than left pointing at
a re-export, because two ways to ask one question is the drift this repo treats as a defect
even while both work.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError


async def assert_account_open(session: AsyncSession, *, tenant_id: UUID) -> None:
    """May a key to this account be minted, or redeemed? Absent → 404, closed → 409.

    THE ONE PREDICATE BEHIND BOTH ENDS OF AN INVITATION, for the reason `create_invitation`
    gives about its own two refusals: an invitation has a mint site and a burn site, and a
    rule enforced at only one of them is a rule with a hole in it.

    What it refuses, and why each is a support incident rather than a theoretical state:

    - **No row** (a mistyped tenant id, or another tenant's id under RLS). `invitations`
      carries `fk_invitations_tenant_id_organizations`, so this used to surface as an
      IntegrityError escaping the route: a 500, an `unhandled_exception` alert, and an
      operator told nothing. D-65's third answer is a 404, and it is the same answer a
      tenant the caller cannot see gets — the id is not confirmed either way.
    - **`churned` or soft-deleted.** These were both a cheerful 201 and, worse, a 200 on
      the accept: `core/auth.py` resolves memberships with `o.deleted_at IS NULL AND
      o.status <> 'churned'`, so the invitee burned their single-use token, got a
      membership row, and was then told "You are not a member of this account" on their
      very first request — with no way back, because the token is single-use and the
      account is closed. Handing out a key to an offboarded tenant is also the wrong
      direction of travel for FLOWS §9: that account is on the retention clock, not
      taking on staff.

    **`suspended` is deliberately NOT refused.** Suspension is the reversible control
    (`_LIFECYCLE_FROM` lets it go straight back to `active`), it stops OUTBOUND DIALLING
    and nothing else, and the account being suspended over non-payment is exactly when
    someone needs to add the person who will pay. Refusing here would make a billing
    stop into an access stop, which is a different decision and not this function's to
    make.

    Reads under the caller's own session on purpose: every caller already runs inside
    `tenant_session(tenant_id)`, `organizations`' policy matches on `id`, and so a
    neighbour's id is invisible rather than merely filtered.
    """
    row = (
        await session.execute(
            text("SELECT status, deleted_at FROM organizations WHERE id = :tid"),
            {"tid": tenant_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Client")
    status, deleted_at = row
    if deleted_at is not None or status == "churned":
        # `account_closed` is `compliance.service.account_stopped_blocker`'s own rule name
        # for this same condition. Two surfaces refusing one state under two names is how
        # an operator ends up believing they are two different problems.
        raise ProblemError.conflict(
            "account_closed",
            "This account has been closed.",
            remediation=(
                "Closing an account is final — set up a new client account if they are coming back."
            ),
        )


__all__ = ["assert_account_open"]
