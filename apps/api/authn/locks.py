"""One lock, for the one invariant this package states and could not keep (D-320).

Three functions in `authn` promise that a subject has AT MOST ONE live credential of a
kind at a time, and each of them implements the promise as a RETIRE followed by an ISSUE:

* `otp.issue_challenge` — "Issuing a new code invalidates the previous one. Without that
  rule, 'resend the code' becomes an attempt-budget reset";
* `service.request_password_reset` — "Only the newest link works. Without this, 'click
  forgot password three times' leaves three live keys in a mailbox for an hour";
* `service.confirm_password_reset` — burn every outstanding reset link, so "an attacker
  who triggered a reset, then watched the victim change their password by other means"
  does not still hold a working key.

Retire-then-issue is a read-decide-write across two statements, and under READ COMMITTED
two of them interleave with no conflict to detect: A's `UPDATE ... WHERE consumed_at IS
NULL` matches nothing that B has not yet inserted, B's matches nothing A has not yet
committed, and both then INSERT. Measured on this tree before this module existed: two
overlapping `issue_challenge` calls left **two live challenges, and both codes
authenticated** — the resend-multiplies-the-budget failure the OTP module's docstring
says cannot happen, reachable by a double-tap on "resend".

`pg_advisory_xact_lock` is the house primitive for exactly this (BACKEND-PATTERNS §5,
`billing/service.lock_tenant_credits`, `kb/service._lock_agent_publishes`): the critical
section IS a database transaction, so the lock is released by COMMIT *or* ROLLBACK — the
two events that decide whether the new credential exists — and there is no TTL to tune.
The alternative, a unique index alone, is rejected here for the reason
`_lock_agent_publishes` rejects it: the loser would learn it had lost only from an
`IntegrityError`, so a second click on "resend" would answer 500 instead of mailing a
code. `auth_otp_challenges` carries one ANYWAY (migration `f1c8b7d5a903`) — but as the
structural statement of the invariant against a future writer that forgets this call,
never as the mechanism callers rely on.

WHY THE KEY IS THE SUBJECT AND NOT (SUBJECT, PURPOSE). The reset path spans two tables —
`invalidate_outstanding` on `auth_email_tokens` and, on the change-password path,
`credentials.set_password` — and a per-purpose key would let a reset request slip its new
link in between a password change and the invalidation that is supposed to kill it. One
key per subject makes every credential-minting act for one person serial, which is what
the three promises above jointly require. The cost is that one person's concurrent
sign-in and reset request queue; they are human acts, seconds apart at most, and they
already contend for the same rows.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["lock_subject_credentials", "subject_lock_key"]


def subject_lock_key(realm: str, subject_id: UUID) -> str:
    """The advisory-lock key one subject's credential writes serialize on.

    A function rather than an f-string written in three modules, for the reason
    `kb.service.publish_lock_key` gives: a lock whose key can drift is not a lock.
    """
    return f"authn:subject:{realm}:{subject_id}"


async def lock_subject_credentials(session: AsyncSession, *, realm: str, subject_id: UUID) -> None:
    """Serialize every credential-minting write for one subject, until COMMIT/ROLLBACK.

    Take it BEFORE the retire, which is the write the issue depends on. Re-entrant, so a
    transaction that retires and issues twice does not deadlock against itself.

    Requires a `credential_session()` only in the sense that its callers do; the lock
    itself is a session-independent Postgres primitive and takes no rows.
    """
    await session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": subject_lock_key(realm, subject_id)},
    )
