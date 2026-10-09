"""Google sign-in, self-serve account creation and Sheets through the client's Google (D-703)

Revision ID: c3e8f1a7b952
Revises: b7d4e2a91c3f
Create Date: 2026-10-10 09:00:00.000000

1. `auth_identities`: a person's Google account, keyed on Google's `sub` (never the email,
   which Google says can change), under the same deny-by-default `app.auth` policy as
   `auth_credentials`. One Google account opens one Calevate account.
2. `auth_otp_challenges.purpose` gains `signup`: the code that proves a mailbox before a
   self-serve account exists. It is keyed on a pseudo-subject derived from the address,
   which is why the column has no foreign key.
3. `integration_credentials.kind` gains `google_sheets`: the client's own Google
   connection with the `drive.file` scope, reaching only the sheets they pick.

DOWNGRADE refuses while a Google identity, a pending signup code or a Sheets connection
exists, rather than deleting a way somebody signs in.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c3e8f1a7b952"
down_revision: str | None = "b7d4e2a91c3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

AUTH_GUC = "current_setting('app.auth', true) = 'on'"

_OLD_OTP = ("login_challenge", "email_verify", "step_up")
_NEW_OTP = (*_OLD_OTP, "signup")
_OLD_KINDS = (
    "aisensy",
    "meta_cloud",
    "interakt",
    "custom_api",
    "google_calendar",
    "razorpay",
    "zoho_crm",
    "hubspot",
)
_NEW_KINDS = (*_OLD_KINDS, "google_sheets")


def _replace_check(table: str, name: str, predicate: str) -> None:
    op.drop_constraint(op.f(f"ck_{table}_{name}"), table, type_="check")
    op.create_check_constraint(op.f(f"ck_{table}_{name}"), table, predicate)


def upgrade() -> None:
    op.create_table(
        "auth_identities",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("realm", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_subject", sa.Text(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint("realm IN ('client')", name=op.f("ck_auth_identities_realm_enum")),
        sa.CheckConstraint("provider IN ('google')", name=op.f("ck_auth_identities_provider_enum")),
        sa.CheckConstraint(
            "length(provider_subject) BETWEEN 1 AND 255",
            name=op.f("ck_auth_identities_provider_subject_len"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_auth_identities")),
        sa.UniqueConstraint(
            "provider", "provider_subject", name="uq_auth_identities_provider_subject"
        ),
        sa.UniqueConstraint(
            "realm", "subject_id", "provider", name="uq_auth_identities_realm_subject_provider"
        ),
    )
    op.execute("ALTER TABLE auth_identities ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE auth_identities FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY credential_store_only ON auth_identities "
        f"USING ({AUTH_GUC}) WITH CHECK ({AUTH_GUC})"
    )
    _replace_check("auth_otp_challenges", "purpose_enum", f"purpose IN {_NEW_OTP!r}")
    _replace_check("integration_credentials", "kind_enum", f"kind IN {_NEW_KINDS!r}")


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
          PERFORM set_config('app.auth', 'on', true);
          IF EXISTS (SELECT 1 FROM auth_identities)
             OR EXISTS (SELECT 1 FROM auth_otp_challenges WHERE purpose = 'signup')
             OR EXISTS (SELECT 1 FROM integration_credentials WHERE kind = 'google_sheets')
          THEN
            RAISE EXCEPTION 'Google sign-ins, pending signups or Sheets connections exist; '
              'remove them deliberately before downgrading';
          END IF;
        END $$;
        """
    )
    _replace_check("integration_credentials", "kind_enum", f"kind IN {_OLD_KINDS!r}")
    _replace_check("auth_otp_challenges", "purpose_enum", f"purpose IN {_OLD_OTP!r}")
    op.execute("DROP POLICY IF EXISTS credential_store_only ON auth_identities")
    op.drop_table("auth_identities")
