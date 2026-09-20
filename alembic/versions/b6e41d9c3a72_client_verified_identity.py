"""Client-verified identity — the result and the reference, never the document

Revision ID: b6e41d9c3a72
Revises: d8a05e4c7b13
Create Date: 2026-09-20 11:05:00.000000

D-635. D-47 gave us an entity check performed by a person at Calevate against a public
business registry. That answers "is this a real business"; it does not answer "who,
personally, stood behind this account", which is the only question that matters when a
client misuses the platform and somebody has to be held to it. The Telecommunications
Act 2023 s.3(7) puts three years and ₹50 lakh on obtaining a telecom identifier on
another person's identity, and on a self-serve motion the applicant is a stranger.

WHAT THIS MIGRATION DOES **NOT** ADD, AND WHY THAT IS THE WHOLE DESIGN
-----------------------------------------------------------------------
No Aadhaar number. No PAN of a natural person. No document, scan, image or file
reference to one. The client authenticates DIRECTLY with a licensed aggregator's
DigiLocker flow; the aggregator is the intermediary that handles the Aadhaar, and what
crosses to us is four things — verified or not, which provider, that provider's own
transaction reference, and the verified holder's NAME.

That is not squeamishness, it is a live page. `/legal/privacy` tells every client that
this schema refuses a twelve-digit bare number and cites **Aadhaar Act 2016 s.29** for
why: s.29 restricts what may be done with identity information collected for
authentication once you hold it. A column holding one would have made a published notice
false, which is a DPDP problem before it is an engineering one.

A **masked or hashed** Aadhaar was considered and refused on three grounds: s.29(3)'s
restriction attaches to identity information regardless of masking; a hash over the ~10^9
Indian Aadhaar space reverses on one machine in minutes (the same defect `a3f7d21c8b45`
had just removed from `campaign_contacts.dedupe_hash`); and it buys nothing the
provider's reference does not already buy. A third party's transaction id is BETTER
liability evidence than a scan we hold — it is corroborated by a licensed intermediary's
own records, and it carries no retention clock of its own.

THE WIDENED CONSTRAINT — EXTENDED, NOT REMOVED
-----------------------------------------------
`ck_kyc_records_verified_names_its_evidence` said: a `verified` row names what was
checked, against what reference, BY WHOM (an admin) and when. An aggregator-verified row
has no admin, so the naive move is to relax the constraint to let `verified_by_admin_id`
be null — which deletes the guarantee for the operator path too, and leaves a `verified`
row that can name nobody at all.

Instead the predicate becomes a DISJUNCTION over `verification_source`, and each arm is
as strict as the original: an `operator` row still names its document, its reference and
its admin; an `aggregator` row names its provider, that provider's reference and the name
the provider returned. Either way a `verified` row can say who verified it, which is what
the constraint was always for. `verified_at` is required by both arms, as before.

`ck_kyc_records_document_ref_is_not_an_aadhaar` is untouched and still passes, because
nothing here writes `document_ref`. Two more guards of the same shape are added, on
`verification_reference` and on `verified_name` — a name column is exactly where a
careless paste lands, and the check costs one regex and fails at the moment of the
mistake rather than at the next audit.

`kyc_verification_requests` — WHY A SECOND TABLE
-------------------------------------------------
The webhook is unauthenticated: the aggregator holds no Calevate session. So the tenant
has to come from somewhere, and the one place it must NOT come from is the payload — a
payload that names its own tenant IS the forgery. It comes from a row we wrote ourselves
when the client started the run, looked up by `(provider, provider_ref)`, which is also
the natural idempotency key: UNIQUE on that pair, so a redelivery finds the row already
terminal and changes nothing.

It is a separate table from `kyc_records` rather than four more nullable columns on it
because a tenant may attempt verification several times (abandoned, expired, failed at
the provider) while holding exactly one verification RESULT, and squeezing an attempt
log into a one-row-per-tenant table would lose every attempt but the last — including
the failed ones, which are the interesting ones.

MUTABLE, and absent from `APPEND_ONLY_TABLES` for the same reason `kyc_records` is: a
request is created and then completes, fails or expires, and the webhook reads its
current state. Who changed it and when is `audit_log`'s job.

RLS
---
New tenant table, so hard rule 1 in full: `tenant_id`, ENABLE + FORCE, and the standard
DATA-MODEL §1 `tenant_isolation` policy created HERE beside the table. The webhook reads
it on an UNTENANTED session on purpose and by necessity — it has no tenant yet, that is
what it is looking up — which is precisely why the lookup is keyed on a provider
reference the caller had to be told by us, and why everything downstream of the lookup
runs under `tenant_session(resolved)`. The cross-tenant zero-rows proof is
`tests/kyc_client_verification_test.py::test_tenant_b_cannot_see_tenant_as_verification_
request`.

LOCKING
-------
The `ALTER TABLE ... ADD COLUMN` calls are catalogue-only (nullable, no default, no
rewrite on PG11+). The backfill below them touches one row per tenant on a table that
holds at most one row per organization, so it is not a batched backfill and does not need
to be. The CHECK constraints are added NOT VALID and VALIDATEd separately anyway, because
"small today" is not a locking argument and VALIDATE takes the weaker SHARE UPDATE
EXCLUSIVE. `lock_timeout` is set so a migration that cannot get its lock fails fast
rather than queueing behind a long read and stalling every writer behind it.

THE BACKFILL IS LOAD-BEARING, NOT COSMETIC
-------------------------------------------
Every `kyc_records` row that exists was written by the ops route, which is the only
writer that has ever existed. Without `verification_source = 'operator'` on them, the
widened constraint matches NEITHER arm and VALIDATE fails on any deployment holding a
verified row. The backfill runs before the constraint and covers every row, not only the
verified ones, so a `submitted` row that is later verified by ops does not have to
remember to set it.

DOWNGRADE
---------
Drops the new table and its policy, restores the ORIGINAL constraint text verbatim, and
drops the four columns. It is exercised (upgrade → downgrade → upgrade) rather than
assumed. It LOSES aggregator-verified results — unavoidable, this is the only place they
live — and the restored constraint would refuse them, so any such row is moved back to
`submitted` first rather than left to fail the VALIDATE. That makes the revert a
compliance decision (those clients become unverified again and stop dialling), not a
rollback detail.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b6e41d9c3a72"
down_revision: str | None = "d8a05e4c7b13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_EVIDENCE = "ck_kyc_records_verified_names_its_evidence"

# The ORIGINAL predicate, kept verbatim so `downgrade` restores exactly what was there
# rather than somebody's recollection of it.
_EVIDENCE_BEFORE = (
    "status <> 'verified' OR (document_kind IS NOT NULL AND document_ref IS NOT NULL "
    "AND verified_by_admin_id IS NOT NULL AND verified_at IS NOT NULL)"
)

# "A verified row names whoever verified it — human or provider." Two arms, each as
# strict as the one predicate it replaces; `verified_at` is required by both.
_EVIDENCE_AFTER = (
    "status <> 'verified' OR (verified_at IS NOT NULL AND ("
    "  (verification_source = 'operator'"
    "     AND document_kind IS NOT NULL AND document_ref IS NOT NULL"
    "     AND verified_by_admin_id IS NOT NULL)"
    "  OR"
    "  (verification_source = 'aggregator'"
    "     AND verification_provider IS NOT NULL AND verification_reference IS NOT NULL"
    "     AND verified_name IS NOT NULL)"
    "))"
)

# The licensed aggregators/intermediaries this product would consider, plus the in-house
# adapter. Stored rather than assumed because a reference is meaningless without knowing
# whose it is — the same argument `CARRIER_APPLICATION_CARRIERS` makes one table over.
# `fake` is a member so the seam can be exercised end to end against a contract we own
# (no vendor's is readable from this environment); a `fake` row is self-describing and
# nobody mistakes it for a verification, the property `migration_backfill` has in
# `FIRST_CAMPAIGN_DECISION_SOURCES`.
_PROVIDERS = "('setu', 'digio', 'cashfree', 'sandbox', 'fake')"

_AADHAAR = "^[0-9]{12}$"

_REQUEST_POLICY = (
    "CREATE POLICY tenant_isolation ON kyc_verification_requests USING ("
    "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    # WHO verified: a person at Calevate, or the client themselves through a licensed
    # aggregator. It is the discriminant of the widened evidence constraint, so it is not
    # decoration — a row whose source is null can never be `verified`.
    op.add_column("kyc_records", sa.Column("verification_source", sa.Text(), nullable=True))
    op.add_column("kyc_records", sa.Column("verification_provider", sa.Text(), nullable=True))
    # The PROVIDER's own transaction id for the run that produced this result. This is the
    # liability artefact: it is what a third party can be asked to corroborate. It is NOT
    # an identity document and no identity document is derivable from it.
    op.add_column("kyc_records", sa.Column("verification_reference", sa.Text(), nullable=True))
    # The holder name the provider returned, as it stands in the source record. A NAME —
    # deliberately without the number it was read from, exactly as `signatory_name` is.
    op.add_column("kyc_records", sa.Column("verified_name", sa.Text(), nullable=True))

    # Before the constraint, not after: see THE BACKFILL IS LOAD-BEARING above.
    #
    # AND BRACKETED, or it backfills NOTHING and says it succeeded. `kyc_records` is FORCE
    # ROW LEVEL SECURITY, which binds the table OWNER too, and `tenant_isolation` is
    # fail-closed on an unset `app.tenant_id` — which a migration never sets. Unbracketed,
    # this UPDATE matches zero rows on a deployment that holds any, reports success, and
    # the constraint below is then added over rows the migration believes it fixed. The
    # bracket lifts RLS for the owner only; `calevate_app` is NOSUPERUSER NOBYPASSRLS and
    # keeps every policy throughout, and DDL is transactional so FORCE is restored before
    # commit (the reasoning in full: `d3b71c9a5e08`).
    op.execute("ALTER TABLE kyc_records NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE kyc_records SET verification_source = 'operator'")
    op.execute("ALTER TABLE kyc_records FORCE ROW LEVEL SECURITY")

    op.execute(f"ALTER TABLE kyc_records DROP CONSTRAINT {_EVIDENCE}")
    op.execute(
        f"ALTER TABLE kyc_records ADD CONSTRAINT {_EVIDENCE} CHECK ({_EVIDENCE_AFTER}) NOT VALID"
    )
    op.execute(
        "ALTER TABLE kyc_records ADD CONSTRAINT ck_kyc_records_verification_source_enum "
        "CHECK (verification_source IS NULL OR "
        "verification_source IN ('operator', 'aggregator')) NOT VALID"
    )
    op.execute(
        "ALTER TABLE kyc_records ADD CONSTRAINT ck_kyc_records_verification_provider_enum "
        f"CHECK (verification_provider IS NULL OR verification_provider IN {_PROVIDERS}) NOT VALID"
    )
    # A provider named with no reference, or a reference with no provider, is half a fact.
    op.execute(
        "ALTER TABLE kyc_records ADD CONSTRAINT ck_kyc_records_provider_and_reference_travel "
        "CHECK ((verification_provider IS NULL) = (verification_reference IS NULL)) NOT VALID"
    )
    # Same backstop as `document_ref`, on the two columns an aggregator result writes. A
    # name column is where a careless paste lands, and this fails at the moment of the
    # mistake rather than at the next audit.
    op.execute(
        "ALTER TABLE kyc_records ADD CONSTRAINT "
        "ck_kyc_records_verification_reference_is_not_an_aadhaar "
        f"CHECK (verification_reference IS NULL OR verification_reference !~ '{_AADHAAR}') NOT VALID"
    )
    op.execute(
        "ALTER TABLE kyc_records ADD CONSTRAINT ck_kyc_records_verified_name_is_not_an_aadhaar "
        f"CHECK (verified_name IS NULL OR verified_name !~ '{_AADHAAR}') NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    for name in (
        _EVIDENCE,
        "ck_kyc_records_verification_source_enum",
        "ck_kyc_records_verification_provider_enum",
        "ck_kyc_records_provider_and_reference_travel",
        "ck_kyc_records_verification_reference_is_not_an_aadhaar",
        "ck_kyc_records_verified_name_is_not_an_aadhaar",
    ):
        op.execute(f"ALTER TABLE kyc_records VALIDATE CONSTRAINT {name}")

    op.create_table(
        "kyc_verification_requests",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        # The provider's id for this run. UNIQUE with `provider`, which is what makes the
        # webhook idempotent without a second mechanism: a redelivery resolves to the row
        # it already closed.
        sa.Column("provider_ref", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), server_default="created", nullable=False),
        # WHICH branch this run is for. A sole proprietor IS the entity, so verifying the
        # person completes the record; for every other entity type the person verified is
        # the authorised SIGNATORY and an operator still has to record the CIN/GSTIN.
        sa.Column("entity_type", sa.Text(), nullable=False),
        # Why it failed, when it did — the provider's reason in OUR vocabulary, never
        # their raw payload.
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.CheckConstraint(
            "status IN ('created', 'completed', 'failed', 'expired')",
            name=op.f("ck_kyc_verification_requests_status_enum"),
        ),
        sa.CheckConstraint(
            f"provider IN {_PROVIDERS}",
            name=op.f("ck_kyc_verification_requests_provider_enum"),
        ),
        sa.CheckConstraint(
            "entity_type IN ('sole_proprietorship', 'partnership', 'llp', 'private_limited', "
            "'public_limited', 'trust_or_society', 'huf')",
            name=op.f("ck_kyc_verification_requests_entity_type_enum"),
        ),
        sa.CheckConstraint(
            "status <> 'failed' OR failure_reason IS NOT NULL",
            name=op.f("ck_kyc_verification_requests_failed_names_its_reason"),
        ),
        # Nothing about a provider's run id should ever be twelve bare digits. If it is,
        # somebody has put an identity number where a transaction id goes.
        sa.CheckConstraint(
            f"provider_ref !~ '{_AADHAAR}'",
            name=op.f("ck_kyc_verification_requests_provider_ref_is_not_an_aadhaar"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_kyc_verification_requests")),
        sa.UniqueConstraint(
            "provider", "provider_ref", name=op.f("uq_kyc_verification_requests_provider_ref")
        ),
    )
    op.create_index(
        op.f("ix_kyc_verification_requests_tenant_id"),
        "kyc_verification_requests",
        ["tenant_id"],
        unique=False,
    )
    op.execute(
        "ALTER TABLE kyc_verification_requests ADD CONSTRAINT "
        "fk_kyc_verification_requests_tenant_id_organizations "
        "FOREIGN KEY (tenant_id) REFERENCES organizations (id) ON DELETE RESTRICT NOT VALID"
    )
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "ALTER TABLE kyc_verification_requests "
        "VALIDATE CONSTRAINT fk_kyc_verification_requests_tenant_id_organizations"
    )
    op.execute("ALTER TABLE kyc_verification_requests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kyc_verification_requests FORCE ROW LEVEL SECURITY")
    op.execute(_REQUEST_POLICY)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON kyc_verification_requests")
    op.drop_index(
        op.f("ix_kyc_verification_requests_tenant_id"), table_name="kyc_verification_requests"
    )
    op.drop_table("kyc_verification_requests")

    # An aggregator-verified row cannot satisfy the restored constraint — it names no
    # admin and the columns proving who DID verify it are about to be dropped. Moving it
    # back to `submitted` is the honest outcome: that client is unverified again and
    # stops dialling, which is the compliance consequence of the revert rather than a
    # detail of it. Leaving the row alone would instead fail the constraint add and abort
    # the downgrade halfway.
    # Bracketed for the reason the upgrade's backfill is: unbracketed it matches zero
    # rows, and the constraint restored below then fails on the rows it was meant to move.
    op.execute("ALTER TABLE kyc_records NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE kyc_records SET status = 'submitted', verified_at = NULL "
        "WHERE status = 'verified' AND verification_source = 'aggregator'"
    )
    op.execute("ALTER TABLE kyc_records FORCE ROW LEVEL SECURITY")
    for name in (
        "ck_kyc_records_verified_name_is_not_an_aadhaar",
        "ck_kyc_records_verification_reference_is_not_an_aadhaar",
        "ck_kyc_records_provider_and_reference_travel",
        "ck_kyc_records_verification_provider_enum",
        "ck_kyc_records_verification_source_enum",
    ):
        op.execute(f"ALTER TABLE kyc_records DROP CONSTRAINT IF EXISTS {name}")
    op.execute(f"ALTER TABLE kyc_records DROP CONSTRAINT {_EVIDENCE}")
    op.execute(f"ALTER TABLE kyc_records ADD CONSTRAINT {_EVIDENCE} CHECK ({_EVIDENCE_BEFORE})")

    op.drop_column("kyc_records", "verified_name")
    op.drop_column("kyc_records", "verification_reference")
    op.drop_column("kyc_records", "verification_provider")
    op.drop_column("kyc_records", "verification_source")
