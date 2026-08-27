"""The acceptance ledger (migration a9d4e70c31b8). INSERT-only (hard rule 4).

One row is one act: a named person, at a named instant, accepting one document at one
version, having been shown one acceptance statement. There is no status column and no
withdrawal row, which is where this ledger deliberately differs from `consent_ledger` and
`whatsapp_alert_optin_ledger` next door: those record CONSENT, which DPDP §6(6) requires
to be as easy to withdraw as to give. This records CONTRACT FORMATION. A client who no
longer wants to be bound ends the engagement (`tenant_erasure_requests`, FLOWS §9); they
do not un-accept the terms they operated under last month, and a table that let them
would be destroying the evidence of the period it covers.
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, Index, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from apps.api.db.base import Base, PKMixin


class LegalAcceptance(PKMixin, Base):
    """One organisation's acceptance of one version of one published document.

    WHAT IT RECORDS AS EVIDENCE, AND WHAT IT DELIBERATELY DOES NOT.

    A clickwrap is only worth what it can prove, and the four things a court or a buyer's
    counsel asks are: WHICH document, at WHICH version, accepted by WHOM, and WHEN — plus
    the wording that was on the screen when they clicked, because "I accepted something"
    and "I accepted THIS" are different claims. Those five are the columns below;
    `statement_version` is the last of them, pinned by version rather than copied, for the
    reason `whatsapp_optin.ALERT_NOTICE_VERSION` gives: a version string is evidence only
    while the text it names can still be produced, and the text lives in
    `legal/statements.py` where a year-old row can still resolve it.

    **NO `ip` AND NO `user_agent`, AND THAT IS A DECISION RATHER THAN AN OMISSION.** They
    are the conventional clickwrap evidence and they are already recorded — `write_audit`
    stamps the caller's IP into `audit_log` (`scripts/check_audit_ip.py` exists to keep it
    doing so), the acceptance row and its audit row commit in the SAME transaction, and
    the audit row names this row by id. So a second copy here would add no fact and no
    corroboration: it would be the same value, written by the same statement, in a table
    with weaker guarantees — `audit_log` is hash-chained (BACKEND-PATTERNS §7) and this
    table is merely append-only. What it WOULD add is a second store of personal data
    under DPDP with its own retention obligation, in a table a client's own console reads,
    on a screen whose whole subject is how carefully we handle their data. A user agent
    string adds a device fingerprint on top of that and settles nothing a dispute turns
    on: nobody has ever argued about which browser accepted the terms.

    The constraints below mirror migration `a9d4e70c31b8` — the CHECKs are the source of
    truth and this class must not drift from them (DATA-MODEL §10).
    """

    __tablename__ = "legal_acceptances"
    __table_args__ = (
        # Non-blank, all three. The vocabulary itself is NOT a CHECK: which documents are
        # acceptable is a product decision (`catalogue.ACCEPTABLE_SLUGS`) that must be
        # able to change without a migration, and the service refuses an unknown slug
        # before the INSERT. What the database guarantees is that no row is meaningless.
        CheckConstraint("btrim(document_slug) <> ''", name="slug_present"),
        CheckConstraint("btrim(document_version) <> ''", name="version_present"),
        CheckConstraint("btrim(statement_version) <> ''", name="statement_present"),
        # Exactly the read `service.latest_acceptances` runs — newest row per
        # (tenant, document). `accepted_at DESC, created_at DESC` for the reason
        # `ix_whatsapp_alert_optin_current` uses both: two rows in the same instant must
        # still resolve deterministically rather than by planner whim. Declared with a
        # DESC ordering and an INCLUDE, so autogenerate cannot faithfully diff it; the
        # migration is the source of truth for its existence.
        Index(
            "ix_legal_acceptances_current",
            "tenant_id",
            "document_slug",
            text("accepted_at DESC"),
            text("created_at DESC"),
            postgresql_include=["document_version"],
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False
    )
    #: The `/legal/<slug>` segment. Stable — these pages are linked from contracts.
    document_slug: Mapped[str] = mapped_column(Text, nullable=False)
    #: The version string in force when the person clicked, review state included
    #: (`catalogue.version_of`). Compared against the catalogue on every gate read.
    document_version: Mapped[str] = mapped_column(Text, nullable=False)
    #: Which acceptance wording was on the screen (`legal/statements.py`).
    statement_version: Mapped[str] = mapped_column(Text, nullable=False)
    #: WHO. The organisation's owner — the only role the route lets through — as a
    #: `users.id`, not a typed name: an auditor asks who, and a string nobody can resolve
    #: to a person is not an answer.
    accepted_by_user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    #: WHEN they accepted. Separate from `created_at` for the reason
    #: `whatsapp_alert_optin_ledger` separates `captured_at`: one is the act, the other is
    #: when we wrote it down, and only the first is what the contract dates from.
    accepted_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now(), nullable=False)
