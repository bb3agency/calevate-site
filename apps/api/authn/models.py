"""The two tables the first-party credential layer owns (D-165).

NEITHER IS TENANT-SCOPED, AND THAT IS A DECISION RATHER THAN AN OMISSION. Identity
crosses tenants in this product — one person can be the owner of one clinic and staff at
another (`memberships` is the many-to-many, DATA-MODEL §2) — so a password or a session
that carried a `tenant_id` would either be duplicated per membership or would be wrong.
`users` and `admin_users` already sit outside tenant isolation for exactly this reason.

WHAT PROTECTS THEM INSTEAD IS STRICTER THAN TENANT ISOLATION, not weaker. `users` today
has no RLS at all, so any session in the process can read it; that is tolerable for a
directory of email addresses and intolerable for password hashes and live session
tokens, where one over-broad query in a tenant-scoped code path is platform-wide account
takeover. So both tables below are ENABLE + FORCE ROW LEVEL SECURITY with a
DENY-BY-DEFAULT policy: the only session that sees a row is one that has set
`app.auth` — `db/session.credential_session()`, which nothing but this package opens.
A `tenant_session`, an `admin_session`, an `invite_session` and a bare
`untenanted_session` all see zero rows, and `tests/authn_rls_test.py` drives every one
of them against real rows.

`subject_id` HAS NO FOREIGN KEY, and the alternative was worse. It points at
`users.id` on the client realm and `admin_users.id` on the admin realm — two tables that
are deliberately separate (TRD §11: an operator account is not a weak client account) —
and PostgreSQL has no polymorphic FK. The three ways out were: two nullable FK columns
(a CHECK to keep exactly one populated, and every query learning which to join), one
merged identity table (collapsing the realm separation this whole migration is written
to preserve), or this: an unconstrained uuid plus a `realm` discriminator, with the
orphan risk handled where deletion happens. Deletion is the whole risk, and it is
already handled: `users` is soft-deleted (`deactivated_at`) and never hard-deleted,
because memberships and audit rows must survive (hard rule 4), so a dangling
`subject_id` is not a state this schema can reach through the application.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, Index, LargeBinary, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin, TimestampMixin

#: The two realms a credential or a session can belong to. Spelled here, mirrored by a
#: CHECK constraint in the migration, and mirrored again by `core.context.Realm` — the
#: `system` member of that Literal is deliberately absent: a background job has no
#: password and no session.
AUTHN_REALMS = ("admin", "client")

#: Why a session stopped being usable. A closed vocabulary rather than free text, because
#: this value is read by an operator during an incident and "logout" vs "reuse_detected"
#: are the two ends of the question they are asking.
REVOCATION_REASONS = (
    # The person signed out.
    "signed_out",
    # Every session for this subject was dropped: password change, deactivation, or a
    # role change (ASVS 5.0 V7 — entitlements changing must not leave live sessions).
    "subject_revoked",
    # A token that had already been rotated away was presented again. Under
    # `sessions.verify_session` this revokes the whole family, not just the replayed row.
    "reuse_detected",
    # An operator or a support action ended this session from outside.
    "administrative",
)


class AuthCredential(PKMixin, TimestampMixin, Base):
    """One password, for one subject, in one realm.

    There is at most one row per (realm, subject): this is a password store, not a
    credential ledger. History is not kept here — a previous password hash is a liability
    with no reader, and "when did this password last change" is the one fact a support
    conversation actually needs, which `password_set_at` carries.
    """

    __tablename__ = "auth_credentials"
    __table_args__ = (
        UniqueConstraint("realm", "subject_id", name="uq_auth_credentials_realm_subject_id"),
        CheckConstraint(f"realm IN {AUTHN_REALMS!r}", name="realm_enum"),
    )

    realm: Mapped[str] = mapped_column(Text, nullable=False)
    #: `users.id` (client realm) or `admin_users.id` (admin realm). See the module
    #: docstring for why this is not a foreign key.
    subject_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: The Argon2 PHC string — `$argon2id$v=19$m=19456,t=2,p=1$<salt>$<hash>`. It carries
    #: its own parameters, which is what makes `check_needs_rehash` able to upgrade a row
    #: written under older ones without a schema column recording them.
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    #: When this password was last set. Read by `hashing.set_password`'s callers and by
    #: the session layer's "revoke everything older than the password" rule.
    password_set_at: Mapped[datetime] = mapped_column(nullable=False)


class AuthSession(PKMixin, TimestampMixin, Base):
    """One opaque server-side session. The row IS the session; the cookie is a pointer.

    Opaque rather than a self-contained JWT, and the reason is the one property this
    product cannot do without: REVOCATION THAT BITES ON THE NEXT REQUEST. An operator
    lifting the big red switch, a client owner removing a staff member, and D-22's
    "authority is re-read every request" all depend on a session that can be destroyed
    centrally. A stateless token is revocable only by keeping a denylist, which is a
    server-side session with extra steps and worse failure modes (ASVS 5.0 moved
    self-contained tokens into their own chapter for this reason). We pay one indexed
    primary-key lookup per request for it; `core/auth.py` already pays a `users` read and
    a `memberships` read on the same path, so the marginal cost is noise.
    """

    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(f"realm IN {AUTHN_REALMS!r}", name="realm_enum"),
        CheckConstraint(
            f"revoked_reason IS NULL OR revoked_reason IN {REVOCATION_REASONS!r}",
            name="revoked_reason_enum",
        ),
        CheckConstraint(
            "revoked_at IS NULL OR revoked_reason IS NOT NULL",
            name="revocation_states_its_reason",
        ),
        # The reuse-detection query and the "sign me out everywhere" query, in that order
        # of how much they matter. Neither is served by the unique index on token_hash.
        Index("ix_auth_sessions_family_id", "family_id"),
        Index("ix_auth_sessions_realm_subject_id", "realm", "subject_id"),
    )

    #: Every session produced by rotating an earlier one shares its family. A replayed
    #: token revokes the FAMILY, because a leak we can see one member of is a leak we
    #: cannot bound (RFC 9700 §4.14.2's refresh-token reuse rule, applied to a session
    #: that rotates on privilege change rather than on every call).
    family_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    realm: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: SHA-256 of the bearer token under a realm-separated domain string — see
    #: `sessions.token_fingerprint` for why a fast hash is correct here and why the realm
    #: is inside the hash rather than only beside it.
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    #: Slid forward on use, subject to `sessions.IDLE_WRITE_FLOOR` so that reading a
    #: dashboard does not mean a row write per request.
    last_seen_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Inactivity bound. OWASP Session Management Cheat Sheet: enforced SERVER-side.
    idle_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Total lifetime bound, never extended. This is what caps how long a stolen cookie
    #: is worth stealing when the victim keeps using the product.
    absolute_expires_at: Mapped[datetime] = mapped_column(nullable=False)
    #: When this row was rotated away. Non-null means a NEWER row in the same family is
    #: the live one, and this token must never authenticate again.
    superseded_at: Mapped[datetime | None]
    revoked_at: Mapped[datetime | None]
    revoked_reason: Mapped[str | None] = mapped_column(Text)
    #: When this SESSION completed a second factor — the first-party replacement for
    #: Clerk's `fva[1]` claim (`core/auth.py::_second_factor_age_minutes`). NULL means it
    #: never did, which on the admin realm is a refusal. It is a property of the session
    #: rather than of the subject on purpose: enrolling MFA must not retroactively bless
    #: sessions that were established without it.
    mfa_verified_at: Mapped[datetime | None]


__all__ = ["AUTHN_REALMS", "REVOCATION_REASONS", "AuthCredential", "AuthSession"]
