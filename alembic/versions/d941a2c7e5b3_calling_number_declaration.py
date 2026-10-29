"""calling-number declaration: an attestation on autodialer_notices, and an outbound audience

Revision ID: d941a2c7e5b3
Revises: c9d4e7a2b815
Create Date: 2026-10-30 12:00:00.000000

D-941 restores the declaration D-762 removed, as the TCCCPR amendment of 18 Sep 2026 asks
it: the numbers a sender's automated calls come from, declared in advance. The client now
gives the numbers, the date and reference of its declaration, and an attestation of a
versioned text; the provider and objective the D-637 notice asked become optional, because
nobody can yet name the provider for a rented number (D-762). Their existing CHECKs already
pass a NULL, so only NOT NULL goes. A row carries either the attestation or the old notice's
provider and objective, so every row still says what was declared.

`platform_announcements.audience` gains `outbound`: accounts with an agent that places
calls. The one announcement D-941 sends goes to them, and it is inserted here so it reaches
every such account, including ones that start calling after the deploy.
"""

from __future__ import annotations

from alembic import op

revision: str = "d941a2c7e5b3"
down_revision: str | None = "c9d4e7a2b815"
branch_labels: None = None
depends_on: None = None

TABLE = "autodialer_notices"
ANNOUNCEMENTS = "platform_announcements"
ANNOUNCEMENT_ID = "019a33c0-d941-7000-8000-0000000d0941"
_OLD_AUDIENCES = "'all', 'trial', 'paid', 'tenant'"
_NEW_AUDIENCES = "'all', 'trial', 'paid', 'tenant', 'outbound'"
MESSAGE = (
    "From 17 Nov, automated calls may only come from numbers you have declared. "
    "Declare your calling numbers now so your calls keep going."
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN access_provider DROP NOT NULL")
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN objective DROP NOT NULL")
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN attestation_version smallint")
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN attestation_sha256 text")
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT ck_{TABLE}_attestation_paired "
        "CHECK ((attestation_version IS NULL) = (attestation_sha256 IS NULL))"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT ck_{TABLE}_attestation_sha256_hex "
        "CHECK (attestation_sha256 IS NULL OR attestation_sha256 ~ '^[0-9a-f]{64}$')"
    )
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT ck_{TABLE}_attested_or_described "
        "CHECK (attestation_sha256 IS NOT NULL "
        "OR (access_provider IS NOT NULL AND objective IS NOT NULL))"
    )

    op.execute(f"ALTER TABLE {ANNOUNCEMENTS} DROP CONSTRAINT ck_{ANNOUNCEMENTS}_audience")
    op.execute(
        f"ALTER TABLE {ANNOUNCEMENTS} ADD CONSTRAINT ck_{ANNOUNCEMENTS}_audience "
        f"CHECK (audience IN ({_NEW_AUDIENCES}))"
    )
    op.execute(
        f"INSERT INTO {ANNOUNCEMENTS} (id, message, link_url, link_label, tone, audience, "
        "starts_at, ends_at, created_at, updated_at) VALUES "
        f"('{ANNOUNCEMENT_ID}', '{MESSAGE}', '/verify-business#calling-numbers', "
        "'Declare numbers', 'warning', 'outbound', now(), "
        "'2026-11-18T00:00:00+05:30', now(), now()) ON CONFLICT (id) DO NOTHING"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DELETE FROM {ANNOUNCEMENTS} WHERE id = '{ANNOUNCEMENT_ID}'")
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {ANNOUNCEMENTS} WHERE audience = 'outbound') "
        "THEN RAISE EXCEPTION 'an operator has written an announcement for the outbound "
        "audience; end or re-target it first. Not downgraded.'; END IF; END $$"
    )
    op.execute(f"ALTER TABLE {ANNOUNCEMENTS} DROP CONSTRAINT ck_{ANNOUNCEMENTS}_audience")
    op.execute(
        f"ALTER TABLE {ANNOUNCEMENTS} ADD CONSTRAINT ck_{ANNOUNCEMENTS}_audience "
        f"CHECK (audience IN ({_OLD_AUDIENCES}))"
    )

    # Bracketed: the table is FORCE RLS and fail-closed on an unset `app.tenant_id`, so an
    # unbracketed check reads zero rows and the refusal below never fires. DDL is
    # transactional, so FORCE is back before commit.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(
        f"DO $$ BEGIN IF EXISTS (SELECT 1 FROM {TABLE} WHERE attestation_sha256 IS NOT NULL) "
        "THEN RAISE EXCEPTION 'clients have declared their calling numbers; the table is "
        "append-only, so those rows cannot be fitted back into the D-637 shape. Not "
        "downgraded.'; END IF; END $$"
    )
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT ck_{TABLE}_attested_or_described")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT ck_{TABLE}_attestation_sha256_hex")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT ck_{TABLE}_attestation_paired")
    op.execute(f"ALTER TABLE {TABLE} DROP COLUMN attestation_sha256")
    op.execute(f"ALTER TABLE {TABLE} DROP COLUMN attestation_version")
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN objective SET NOT NULL")
    op.execute(f"ALTER TABLE {TABLE} ALTER COLUMN access_provider SET NOT NULL")
