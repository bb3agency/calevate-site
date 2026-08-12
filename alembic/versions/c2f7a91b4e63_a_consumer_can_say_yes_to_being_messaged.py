"""a consumer can say yes to being messaged

Revision ID: c2f7a91b4e63
Revises: b1d5c8e73f04
Create Date: 2026-08-12 18:20:00.000000

`escalate_campaign_contact` shipped in a state where it refuses 100% of the time.
`workers/whatsapp.resolve_escalation_destination` asks `consent_ledger` for a
`messaging` purpose that the CHECK constraint does not permit, so the read returns
nothing, every exhausted contact records `recipient_not_opted_in`, and no follow-up has
ever been sent. That was deliberate — a live read against the table the consent belongs
in, rather than a hardcoded `False` — and this migration is the other half of it.

--------------------------------------------------------------------------------
WHAT IS ADDED, AND WHAT IS DELIBERATELY NOT
--------------------------------------------------------------------------------

Added: the `messaging` purpose, a `consent_source` column that says HOW the statement
was obtained, three CHECKs that make an unevidenced grant unrepresentable, and the
partial index the lookup walks.

**Not added: a single row.** There is no backfill, and writing one would be the worst
thing this migration could do. Consent to be CALLED is not consent to be MESSAGED:

  * `campaigns.consent_source` (b8e4c1d70f92) says the client may DIAL this list. Meta's
    WhatsApp Business Messaging Policy requires an opt-in that names the business and
    states the person is opting in to receive messages from it; a list provenance of
    "existing customer" says neither. (Meta permits the opt-in to be collected on any
    channel and need not be WhatsApp-specific, but it must still be an opt-in TO BE
    MESSAGED, obtained by an affirmative act — pre-ticked boxes do not qualify.)
  * `consent_ledger`'s existing rows are `recording`/`callback`/`marketing`, captured
    DURING a call and keyed to `call_id`. A person who agreed to be recorded agreed to
    a thing that was already happening to them.
  * DPDP §6 consent is purpose-bound: it must be free, specific, informed and
    unambiguous, given by clear affirmative action, and limited to the purpose stated.
    Deriving a messaging permission from a recording permission is precisely the
    secondary use that section forbids.

So every consumer starts with no messaging consent, and the escalation keeps refusing
for them, which is the truth. What changes is that the refusal is now *fixable* by
somebody actually saying yes.

--------------------------------------------------------------------------------
WHY A COLUMN AND NOT A KEY IN `evidence`
--------------------------------------------------------------------------------

`evidence JSONB` already exists and could hold `{"source": ...}`. It is the wrong home
for the same reason b8e4c1d70f92 gave for `campaigns.consent_source`: a JSONB key is
not CHECKABLE. A column with a CHECK lets the database refuse `source: "assumed"` — and
refusing it in the schema is the only refusal that survives a future writer who has not
read this docstring. The four grant-capable members are the ones we can evidence:

    inbound_call_verbal      the person said yes on a recorded call — call_id + the
                             transcript span, the same evidence shape SEC-COMP §2 already
                             requires for recording consent
    web_form_optin           an unticked box on the client's own form — evidence carries
                             the form/notice reference and the version shown
    offline_form_optin       paper or in-store — evidence carries the document reference
    whatsapp_inbound_message the person messaged our WABA first, or replied to it —
                             evidence carries the provider message id

...and a fifth that may only ever WITHDRAW:

    staff_recorded_request   a human at the client typing "they asked us to stop"

`staff_recorded_request` is CHECK-barred from `status = 'granted'`. That asymmetry is
the point of it: consent must be evidenced, a refusal must not be obstructed. A staff
member who could assert a grant on a consumer's behalf is the "implied consent" this
slice exists to make unrepresentable, wearing a different name.

--------------------------------------------------------------------------------
CONSTRAINTS
--------------------------------------------------------------------------------

1. `ck_consent_ledger_purpose_enum` — widened. Dropped and recreated rather than
   altered (Postgres has no ALTER CONSTRAINT for a CHECK expression). Added NOT VALID
   and VALIDATEd separately: NOT VALID takes a brief ACCESS EXCLUSIVE for the catalog
   row and scans nothing, VALIDATE scans under SHARE UPDATE EXCLUSIVE and blocks
   neither readers nor writers. Every existing row already satisfies the wider
   predicate — this is a WIDENING, so the scan can only pass — but leaving it NOT VALID
   would mean the planner ignores it and future ADD CONSTRAINTs re-scan.
2. `ck_consent_ledger_source_enum` — the five members, admitting NULL EXPLICITLY so the
   pre-existing rows (and every future recording-consent row) are unaffected.
3. `ck_consent_ledger_messaging_names_its_source` — `purpose = 'messaging'` implies a
   source. This is the "never assumed" rule as a database constraint.
4. `ck_consent_ledger_granted_consent_carries_evidence` — a GRANT must carry `evidence`,
   may not come from `staff_recorded_request`, and if it is verbal must name its
   `call_id`. Withdrawals are exempt by construction.

`lock_timeout` bounds the wait so a queued ACCESS EXCLUSIVE cannot park in front of
every other session (hard rule 8).

--------------------------------------------------------------------------------
THE INDEX
--------------------------------------------------------------------------------

    (tenant_id, phone_e164, captured_at DESC, created_at DESC) WHERE purpose = 'messaging'

Exactly the lookup `compliance.consent.read_messaging_consent` runs: latest row for one
(tenant, phone), append-only so the newest row is the current state. All four columns
are in the index, so the read is index-only and never sorts — the ledger is the fastest-
growing table in the schema and a follow-up must not walk it.

PARTIAL, so it indexes only messaging rows and costs nothing on the recording-consent
rows that dominate the table today. NOT `CONCURRENTLY`: a concurrent build cannot run
inside alembic's transaction, and the predicate matches zero rows on every existing
database, so the build is instantaneous. (`f9c2b41a8e57`'s CONCURRENTLY index is the
cautionary tale — a concurrent build that fails leaves an INVALID index behind.)

RLS: no new table, so no new policy. `consent_ledger` has carried its FORCEd
`tenant_isolation` policy since 05bba2f3c19c, and a column is not a separate security
object — the new column inherits it. Asserted rather than assumed:
`tests/messaging_consent_test.py::test_another_tenant_can_neither_read_nor_write_a_
messaging_consent_row`.

Append-only: nothing here UPDATEs or DELETEs a row, and the `consent_ledger_append_only`
trigger would refuse it if it tried. A withdrawal is a new row (hard rule 4).

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Reversible in hard rule 8's sense — the pre-migration code runs against the
post-downgrade schema — with one honest wrinkle that is stated rather than hidden.

Rows recorded under this revision cannot be deleted: they are `consent_ledger` rows, and
hard rule 4 forbids removing them. So the narrowed `purpose` CHECK is restored **NOT
VALID**. A NOT VALID CHECK still binds every future INSERT — which is exactly the
pre-migration behaviour, `messaging` becomes unwritable again — while leaving the rows
already there in place. Validating it would fail, and the only way to make it validate
would be to destroy consent records, including withdrawals.

**`consent_source` is deliberately NOT dropped**, and that asymmetry is the interesting
part of this migration. Dropping it was the first draft, and it was wrong twice over:

  * It destroys the provenance of consent records the same downgrade is forbidden to
    delete — leaving rows that say "granted" with no way to show how. Hard rule 8's
    two-step deprecation exists for exactly this: a column stops being written before it
    stops existing, and this one never stops being written while its rows are there.
  * It makes the migration NOT RE-APPLIABLE, which is the failure that caught it.
    Downgrade-then-upgrade left the surviving `messaging` rows with a freshly-added,
    all-NULL `consent_source`, so `VALIDATE CONSTRAINT
    ck_consent_ledger_messaging_names_its_source` failed and `alembic upgrade head`
    aborted mid-migration. A reversible migration that cannot be re-applied is not
    reversible; it is a one-way door with a handle painted on it.

So the downgrade removes the four constraints and the index, restores the narrow
`purpose` CHECK, and LEAVES the nullable column in place. Pre-migration code neither
reads nor writes it — every INSERT in this repo names its columns — so the older release
runs against that schema unchanged, which is the sense hard rule 8 means by reversible.
The upgrade is correspondingly written as `ADD COLUMN IF NOT EXISTS`, so a re-upgrade
finds the column and its data exactly as it left them.

Reverting still re-opens the gap this closes — `messaging` becomes unwritable, so every
campaign follow-up goes back to refusing — which makes a revert a compliance decision
rather than a rollback. That is stated here rather than discovered later.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c2f7a91b4e63"
down_revision: str | None = "b1d5c8e73f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "consent_ledger"

CK_PURPOSE = "ck_consent_ledger_purpose_enum"
CK_SOURCE = "ck_consent_ledger_source_enum"
CK_MESSAGING_SOURCE = "ck_consent_ledger_messaging_names_its_source"
CK_GRANT_EVIDENCE = "ck_consent_ledger_granted_consent_carries_evidence"
IX_MESSAGING = "ix_consent_ledger_messaging_lookup"

# Spelled out rather than imported from `compliance/models.py`. A migration is a
# snapshot of the schema on the day it ran; importing today's tuple would silently
# rewrite history the next time somebody adds a member (the rule b8e4c1d70f92 and
# a4e7b2c95d18 both state).
_PURPOSE_SQL = "purpose IN ('recording', 'callback', 'marketing', 'messaging')"
_PURPOSE_SQL_BEFORE = "purpose IN ('recording', 'callback', 'marketing')"
_SOURCE_SQL = (
    "consent_source IS NULL OR consent_source IN ('inbound_call_verbal', 'web_form_optin', "
    "'offline_form_optin', 'whatsapp_inbound_message', 'staff_recorded_request')"
)
_MESSAGING_SOURCE_SQL = "purpose <> 'messaging' OR consent_source IS NOT NULL"
# One constraint, three sentences: a grant is evidenced, a grant is never asserted by
# staff on the subject's behalf, and a verbal grant names the call it was spoken on.
_GRANT_EVIDENCE_SQL = (
    "consent_source IS NULL OR status <> 'granted' OR ("
    "evidence IS NOT NULL "
    "AND consent_source <> 'staff_recorded_request' "
    "AND (consent_source <> 'inbound_call_verbal' OR call_id IS NOT NULL))"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Nullable, no default: catalog-only since PG11 — no rewrite, no scan. `IF NOT
    # EXISTS` (hence `op.execute` rather than `op.add_column`) because the downgrade
    # deliberately leaves this column behind — see the DOWNGRADE section above. A
    # re-upgrade must find the existing column and its data rather than fail, or the
    # surviving `messaging` rows would come back sourceless and fail the VALIDATE below.
    op.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS consent_source text")

    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_PURPOSE}")
    for name, expression in (
        (CK_PURPOSE, _PURPOSE_SQL),
        (CK_SOURCE, _SOURCE_SQL),
        (CK_MESSAGING_SOURCE, _MESSAGING_SOURCE_SQL),
        (CK_GRANT_EVIDENCE, _GRANT_EVIDENCE_SQL),
    ):
        op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {name}")

    op.execute(
        f"CREATE INDEX {IX_MESSAGING} ON {TABLE} "
        "(tenant_id, phone_e164, captured_at DESC, created_at DESC) "
        "WHERE purpose = 'messaging'"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP INDEX IF EXISTS {IX_MESSAGING}")
    for name in (CK_GRANT_EVIDENCE, CK_MESSAGING_SOURCE, CK_SOURCE, CK_PURPOSE):
        op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {name}")
    # `consent_source` stays. It holds the provenance of rows this downgrade may not
    # delete (hard rule 4), the pre-migration code neither reads nor writes it, and
    # dropping it is what made this migration non-re-appliable — see DOWNGRADE above.
    # NOT VALID on purpose — see the DOWNGRADE section of the module docstring. It binds
    # every future INSERT (restoring the pre-migration refusal) without requiring a scan
    # that any already-captured `messaging` row would fail, and which hard rule 4
    # forbids fixing by deletion.
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_PURPOSE} CHECK ({_PURPOSE_SQL_BEFORE}) NOT VALID"
    )
