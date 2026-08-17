"""One live account per address, and a purpose for step-up re-authentication

Revision ID: c7a1e93d40b8
Revises: b3d9f6a2c815
Create Date: 2026-08-17

D-178 closes two of the four gaps AUTH-MIGRATION §11 named. Both land in one revision
because both are the schema half of ONE capability — an authentication surface whose
identity lookups and whose dangerous-action re-check are trustworthy — and because a
partial application of them serves nothing: a `step_up` purpose with no unique address is
still a sign-in that can resolve to whichever `users` row Postgres returned first.

WHAT `users.email` GETS, AND WHY THE PREDICATE IS THERE
--------------------------------------------------------
`CREATE UNIQUE INDEX uq_users_email_lower ON users (lower(email)) WHERE deactivated_at IS
NULL`. The lowered expression is `admin_users`' shape from `b3d9f6a2c815`, deliberately:
addresses are compared casefolded everywhere in this repo, and a unique index on the raw
value would let `Owner@clinic.in` and `owner@clinic.in` both exist and both try to sign in.

THE PARTIAL PREDICATE IS THE ONE DEPARTURE FROM `admin_users`, and it is what makes the two
indexes express the SAME rule rather than merely look alike. The rule is "at most one LIVE
account per address" — which is exactly what `authn/subjects.py::_CLIENT_SELECT` and
`authn/invitations.py::_find_or_create_user` already assume, both of which filter
`deactivated_at IS NULL`. `admin_users` has no `deactivated_at` at all (an operator is
removed by deleting the row — `subjects.py::_ADMIN_SELECT` says why), so on that table the
identical rule needs no predicate. Without the predicate here, a person whose account was
deactivated could never be re-onboarded under their own address, which for an SMB owner who
leaves and comes back is a real refusal bought for no safety.

What it makes true: `subjects.resolve_by_email`'s AMBIGUITY branch — two live rows for one
address, refused loudly — becomes unreachable through the database rather than merely
unlikely, and `_find_or_create_user`'s "two invitations to one address in the same
millisecond" race stops producing a duplicate row. The branch and its warning STAY (a guard
that has been made true by a constraint is not a guard to delete; it is the thing that fails
safe if the constraint is ever dropped), and `_find_or_create_user` moves to `ON CONFLICT`
against this index rather than keeping a read-then-write it can now lose cleanly.

IF THIS MIGRATION FAILS, IT FAILS BEFORE IT WRITES ANYTHING. `users` predates the
constraint and nothing has ever enforced it, so the honest hazard is real data. The
pre-flight below counts colliding LIVE rows and raises with the ids and the count — never
the addresses (hard rule 6) — and names the fix. A `CREATE UNIQUE INDEX` that fails on its
own would do the same job with a duplicate address in the error string and in the log.

WHY NOT `CONCURRENTLY`. AUTH-MIGRATION §2.2 suggested it, and it is the right instinct for a
large hot table: a plain `CREATE UNIQUE INDEX` takes a `SHARE` lock and blocks writes to
`users` for its duration. `users` at this deployment holds tens of rows, the build is
milliseconds, and `CONCURRENTLY` cannot run inside a transaction — it would mean an
`autocommit_block()`, a migration that can leave an INVALID index behind on failure, and a
downgrade that has to cope with one. The lock is cheaper than the failure mode. If this
table is ever large enough for that to stop being true, the index is rebuilt concurrently
then, against numbers measured then.

WHAT `auth_otp_challenges.purpose` GAINS
-----------------------------------------
`step_up`, a third purpose beside `login_challenge` and `email_verify`. A SEPARATE purpose
rather than reusing `login_challenge`, for the reason the purpose column exists: the purpose
is inside the code's HMAC domain (`otp._domain`) and `issue_challenge` retires the live
challenge FOR THAT PURPOSE. Shared, a step-up request would silently retire the code an
operator was mid-way through typing to finish signing in, and a login code would answer a
step-up prompt — a code minted for "prove it is still you" would be interchangeable with one
minted for "finish signing in", which is precisely the equivalence step-up exists to deny.

NO `users.password_migrated_at`, STILL, AND NOW PERMANENTLY. `b3d9f6a2c815` left it out
because the cutover tooling that would write and read it did not exist. It is not going to:
D-170 makes first-party auth the ONLY authenticator, so there is no population of
Clerk-era passwords to migrate — Clerk never gave us a hash — and every account acquires its
first-party password by redeeming a link, which `auth_credentials.password_set_at` already
timestamps. The column would be a second, emptier copy of a fact the credential row holds.
AUTH-MIGRATION §11 now says that rather than promising it.

REVERSIBLE. `downgrade` drops the index and restores the two-purpose CHECK. The CHECK
restore can legitimately fail if a `step_up` challenge row exists, which is correct: past
that point the downgrade is a restore, not a rollback, and the rows would have to be swept
first. `b3d9f6a2c815`'s docstring makes the same argument about its NOT NULLs.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7a1e93d40b8"
down_revision: str | None = "b3d9f6a2c815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

#: The index name, spelled to match `uq_admin_users_email_lower` so a reader looking at one
#: finds the other.
_USERS_EMAIL_INDEX = "uq_users_email_lower"

#: Kept in step with `authn/models.OTP_PURPOSES`, which `tests/authn_stepup_test.py` pins
#: against the live CHECK constraint rather than against this comment.
_OTP_PURPOSES_AFTER = "('login_challenge', 'email_verify', 'step_up')"
_OTP_PURPOSES_BEFORE = "('login_challenge', 'email_verify')"


def _refuse_colliding_addresses() -> None:
    """Fail before writing if two LIVE `users` rows share an address.

    Ids and a count, never an address: this runs with database credentials and its output
    lands in a deploy log (hard rule 6). An operator with the ids can find the rows.
    """
    rows = (
        op.get_bind()
        .exec_driver_sql(
            "SELECT lower(email) AS addr, count(*) AS n, "
            "       string_agg(id::text, ',' ORDER BY created_at) AS ids "
            "FROM users WHERE deactivated_at IS NULL AND email IS NOT NULL "
            "GROUP BY lower(email) HAVING count(*) > 1"
        )
        .fetchall()
    )
    if not rows:
        return
    groups = "; ".join(str(row.ids) for row in rows)
    raise RuntimeError(
        f"{len(rows)} email address(es) are shared by more than one live `users` row, so "
        f"{_USERS_EMAIL_INDEX} cannot be created. The colliding row ids, grouped: {groups}. "
        "Deactivate or merge the duplicates (oldest row is listed first in each group), then "
        "re-run this migration. `authn/subjects.resolve_by_email` is refusing sign-in for "
        "every one of these addresses today, so nobody is signing in with them meanwhile."
    )


def upgrade() -> None:
    _refuse_colliding_addresses()
    op.execute(
        f"CREATE UNIQUE INDEX {_USERS_EMAIL_INDEX} ON users (lower(email)) "
        "WHERE deactivated_at IS NULL"
    )
    op.execute("ALTER TABLE auth_otp_challenges DROP CONSTRAINT ck_auth_otp_challenges_purpose_enum")
    op.execute(
        "ALTER TABLE auth_otp_challenges ADD CONSTRAINT ck_auth_otp_challenges_purpose_enum "
        f"CHECK (purpose IN {_OTP_PURPOSES_AFTER})"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE auth_otp_challenges DROP CONSTRAINT ck_auth_otp_challenges_purpose_enum")
    op.execute(
        "ALTER TABLE auth_otp_challenges ADD CONSTRAINT ck_auth_otp_challenges_purpose_enum "
        f"CHECK (purpose IN {_OTP_PURPOSES_BEFORE})"
    )
    op.execute(f"DROP INDEX IF EXISTS {_USERS_EMAIL_INDEX}")
