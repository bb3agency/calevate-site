"""One live OTP challenge per (realm, subject, purpose) — the rule, in pg_catalog (D-320)

Revision ID: f1c8b7d5a903
Revises: e7b45c19a308
Create Date: 2026-08-18 00:00:00.000000

`apps/api/authn/otp.py` opens with a section titled ONE LIVE CHALLENGE PER (SUBJECT,
PURPOSE) and argues the whole guess-budget design on it:

    "Issuing a new code invalidates the previous one. Without that rule, 'resend the
    code' becomes an attempt-budget reset: an attacker requests twenty codes and gets
    twenty lots of five guesses against a moving target, and the per-row ceiling means
    nothing."

The rule was implemented as a retire (`UPDATE ... WHERE consumed_at IS NULL`) followed by
a mint (`INSERT`), two statements in one transaction and nothing serializing them. Under
READ COMMITTED two overlapping calls each retire what the other has not yet committed and
each insert. Measured on this tree, against this schema, before the fix — two
`issue_challenge` calls for one admin, the second opening while the first was still
uncommitted:

    live challenges: 2
    retired code accepted: True   newest code accepted: True

Two valid codes for one subject, which is the accumulation the docstring says cannot
happen, reachable by a double-tap on "resend".

`authn/locks.lock_subject_credentials` is the FIX — an advisory transaction lock taken
before the retire, the house primitive for a read-decide-write whose critical section is
a transaction (BACKEND-PATTERNS §5). This index is not the fix and must not be read as
one: it is the invariant written where `pg_catalog` can hold it, so a future writer that
mints a challenge without the lock is refused by the database rather than quietly
reopening the hole. The same relationship `billing/models.py` describes between
`lock_tenant_credits` and `ux_credit_ledger_*`.

WHY THE INDEX ALONE WOULD NOT DO. The loser of the race would meet a unique violation and
the resend endpoint would answer 500 to a person who pressed a button twice.
`kb/service._lock_agent_publishes` rejects an index-only fix for the same reason and in
almost the same words.

WHY `auth_email_tokens` GETS NO EQUIVALENT INDEX. "One live token" is true of
`password_reset` (`service.request_password_reset` invalidates first) and is deliberately
NOT true of `email_verify`, which nothing invalidates and which a person may legitimately
have two of in a mailbox. A unique index there would refuse a resend that is allowed. The
lock in `tokens.invalidate_outstanding` covers the purposes that DO promise exclusivity,
without inventing a rule for the ones that do not.

BACKFILL. Any pre-existing duplicates would refuse the index, so they are retired first —
newest survivor per group, by `created_at, id`, which is the ordering `issue_challenge`
itself would have produced. A challenge retired here is one a person can no longer answer;
they press resend and get a live one, which is the same recovery as an expiry. On a
deployment with no duplicates (every one at the time of writing) it updates nothing.

LOCK: `CREATE UNIQUE INDEX` takes ShareLock on `auth_otp_challenges` — writers block,
readers do not — and the table holds at most a handful of live rows per operator, so the
build is microseconds. `lock_timeout` is set for the same reason `e7b45c19a308` sets it:
the hazard is acquisition behind an idle-in-transaction session, not the scan.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "f1c8b7d5a903"
# Re-pointed at merge time from `e7b45c19a308`, which was head when this revision was
# authored on a parallel branch. Three revisions have landed since, `c1e9a4f7d302` last;
# leaving the old parent would have forked the chain and made `alembic upgrade head`
# refuse to choose. Nothing about the SQL depends on the position: this adds a partial
# unique index to `auth_otp_challenges` and touches no object any revision between the
# two touches.
down_revision: str | None = "c1e9a4f7d302"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "ux_auth_otp_challenges_live"

LOCK_TIMEOUT = "SET LOCAL lock_timeout = '5s'"

# `consumed_at IS NULL` is the whole definition of "live" that `issue_challenge` and
# `verify_challenge` both use. Expiry is deliberately NOT part of it: an expired but
# unconsumed row is still retired by the next issue, so including `expires_at > now()`
# would make the predicate non-immutable (which Postgres refuses in an index predicate)
# for no gain.
PREDICATE = "consumed_at IS NULL"


def upgrade() -> None:
    op.execute(LOCK_TIMEOUT)
    op.execute(
        """
        WITH ranked AS (
            SELECT id,
                   row_number() OVER (
                       PARTITION BY realm, subject_id, purpose
                       ORDER BY created_at DESC, id DESC
                   ) AS rank
            FROM auth_otp_challenges
            WHERE consumed_at IS NULL
        )
        UPDATE auth_otp_challenges c
           SET consumed_at = now(), updated_at = now()
          FROM ranked r
         WHERE c.id = r.id AND r.rank > 1
        """
    )
    op.execute(
        f"CREATE UNIQUE INDEX {INDEX} ON auth_otp_challenges "
        f"(realm, subject_id, purpose) WHERE {PREDICATE}"
    )


def downgrade() -> None:
    # The retirements are not undone: they are indistinguishable from an ordinary
    # supersede, and re-opening a challenge that a person has already been told is dead
    # would hand back a live credential. Dropping the index restores the schema; nothing
    # restores a spent one-time code, and nothing should.
    op.execute(LOCK_TIMEOUT)
    op.execute(f"DROP INDEX {INDEX}")
