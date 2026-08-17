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

from sqlalchemy import (
    CheckConstraint,
    Index,
    LargeBinary,
    SmallInteger,
    Text,
    UniqueConstraint,
)
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


#: What an emailed single-use token is FOR. The purpose is inside the token's hash domain
#: (`codes.token_fingerprint`), not merely beside it in a column, for the same reason the
#: realm is inside a session token's: a verification token that could be redeemed as a
#: password reset would turn "prove you read this mailbox" into "take this account", and a
#: column somebody has to remember to filter on is one forgotten predicate away from that.
EMAIL_TOKEN_PURPOSES = (
    # Prove the mailbox exists and belongs to the person who claimed it (C-12).
    "email_verify",
    # Set a new password without knowing the old one (C-13).
    "password_reset",
    # An invitation's set-your-password leg. Distinct from `password_reset` because it is
    # issued to somebody who has no account yet and is bound to an `invitations` row.
    "invite_password",
    # THE FIRST ADMINISTRATOR (D-167). Its own purpose rather than a `password_reset`
    # with a longer clock, because the two differ in more than duration: this one is
    # minted by a script with database credentials rather than by a request, it is the
    # single most privileged act in a deployment's life, and it is redeemed by an endpoint
    # that refuses an account which already has a password. Sharing the purpose would mean
    # a reset token could be redeemed at the bootstrap endpoint and vice versa — and the
    # purpose is inside the hash domain precisely so that cannot happen.
    "admin_bootstrap",
)

#: What a short numeric challenge is for. Deliberately a SHORT list: a 6-digit code is a
#: ~20-bit secret, so every purpose added here is a new surface that needs the throttle in
#: `throttle.py` to be correct.
#:
#: `login_challenge` IS THIS PRODUCT'S SECOND FACTOR (D-166). There is no authenticator app,
#: no shared secret and no recovery-code sheet: on a realm that requires a second factor, a
#: correct password issues a session that can do exactly one thing — answer an emailed code.
#: See `service.py` on why that is the whole of "MFA" here.
OTP_PURPOSES = (
    # The second factor. Emailed after a correct password on a realm that requires one.
    "login_challenge",
    # Emailed to confirm a newly-claimed address.
    "email_verify",
)


class AuthEmailToken(PKMixin, TimestampMixin, Base):
    """A single-use, high-entropy secret that arrived in somebody's mailbox.

    One table, three purposes (`EMAIL_TOKEN_PURPOSES`), with the purpose inside the hash
    domain so the three cannot be traded for one another. Burned by CAS on
    `used_at IS NULL`, exactly as `invitations` already is — one mechanism, two callers.

    `subject_id` IS NULLABLE, and only for `invite_password`: an invitee has no account
    until they redeem, so there is no subject to name yet. `invitation_id` carries the
    binding instead, and the CHECK below makes "exactly one of the two" a schema property
    rather than a convention every query has to uphold.
    """

    __tablename__ = "auth_email_tokens"
    __table_args__ = (
        CheckConstraint(f"purpose IN {EMAIL_TOKEN_PURPOSES!r}", name="purpose_enum"),
        CheckConstraint(f"realm IN {AUTHN_REALMS!r}", name="realm_enum"),
        # A token names a subject OR an invitation, never neither and never both. Neither
        # would be a token that redeems into nothing; both would be two answers to "whose
        # account does this open" and a future reader would have to guess which wins.
        CheckConstraint(
            "(subject_id IS NULL) <> (invitation_id IS NULL)",
            name="names_exactly_one_recipient",
        ),
        UniqueConstraint("token_hash", name="uq_auth_email_tokens_token_hash"),
        # "Invalidate every outstanding reset for this subject", which a successful reset
        # and a password change both have to do.
        Index("ix_auth_email_tokens_realm_subject_id", "realm", "subject_id"),
    )

    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    realm: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    #: `invitations.id`. No FK for the same reason `subject_id` has none — and here there
    #: is a second: the invitation row is tenant-scoped and FORCE-RLS'd, so a credential
    #: session cannot see it anyway. The join happens in `tenancy`, under a tenant session.
    invitation_id: Mapped[UUID | None] = mapped_column(PgUUID(as_uuid=True))
    token_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    used_at: Mapped[datetime | None]


class AuthOtpChallenge(PKMixin, TimestampMixin, Base):
    """A short numeric code, emailed, with a deliberately small budget of guesses.

    THIS IS THE TABLE THE REFERENCE IMPLEMENTATION GOT WRONG, so the reasoning is here
    rather than in a commit message. Theirs stored `sha256(code)` unsalted for a 6-digit
    code: 900,000 candidates is a rainbow table you can build in a second, so one SQL
    injection read or one leaked backup recovered every live OTP in the system. Ours is
    `hmac-sha256(pepper, purpose || code)` where the pepper is derived from `PLATFORM_KEK`
    and therefore is NOT IN THIS DATABASE — the same doctrine `hashing.py` applies to
    passwords, and it is worth more here than there, because a 6-digit code has ~20 bits
    of entropy and a password has rather more.

    `attempts` is the OTHER half of that defence and it is on the ROW rather than only in
    Redis. NIST SP 800-63B requires a rate-limiting mechanism whenever the authenticator
    output has fewer than 64 bits of entropy, and a 6-digit code has ~20 — so the budget
    has to survive a Redis flush. Redis throttles the CALLER; this column bounds the
    CHALLENGE, and an attacker who can reset one cannot reset the other.
    """

    __tablename__ = "auth_otp_challenges"
    __table_args__ = (
        CheckConstraint(f"purpose IN {OTP_PURPOSES!r}", name="purpose_enum"),
        CheckConstraint(f"realm IN {AUTHN_REALMS!r}", name="realm_enum"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        # The verify path reads the newest live challenge for a subject and purpose.
        Index(
            "ix_auth_otp_challenges_realm_subject_purpose",
            "realm",
            "subject_id",
            "purpose",
        ),
    )

    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    realm: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[UUID] = mapped_column(PgUUID(as_uuid=True), nullable=False)
    #: Keyed HMAC, never a bare digest. See the class docstring.
    code_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    #: Set the moment a correct code is accepted, so the same code cannot be spent twice
    #: (OWASP MFA cheat sheet: "invalidate the OTP on successful verification").
    consumed_at: Mapped[datetime | None]
    #: Wrong guesses so far. SMALLINT because the ceiling is single digits by design.
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


__all__ = [
    "AUTHN_REALMS",
    "EMAIL_TOKEN_PURPOSES",
    "OTP_PURPOSES",
    "REVOCATION_REASONS",
    "AuthCredential",
    "AuthEmailToken",
    "AuthOtpChallenge",
    "AuthSession",
]
