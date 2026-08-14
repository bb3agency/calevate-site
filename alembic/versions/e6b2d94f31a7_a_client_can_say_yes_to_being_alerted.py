"""a client can say yes to being alerted on whatsapp

Revision ID: e6b2d94f31a7
Revises: 3a91c7e04d58
Create Date: 2026-08-14

`workers/whatsapp.notify_hot_lead_whatsapp` has refused every hot-lead alert since it
shipped, and `resolve_destination` says why in as many words: there is nowhere to record
that the client's owner agreed to receive WhatsApp from the Calevate WABA, so
`opt_in_at` is hardcoded `None` and the gate returns `recipient_not_opted_in` forever.
FLOWS §6 promises the owner a WhatsApp+email alert within two minutes of a hot lead;
only the email half has ever been deliverable. This migration is the other half.

It is the CLIENT-SIDE twin of `c2f7a91b4e63`, and the two must not be confused:

    c2f7a91b4e63  a CONSUMER may be messaged by a client       consent_ledger.purpose
                  (campaign follow-up; TRAI/DLT + Meta + DPDP)  = 'messaging'
    THIS ONE      a CLIENT's owner may be alerted by US         whatsapp_alert_optin_ledger
                  (hot-lead alert; Meta + DPDP, NOT TRAI/DLT)

--------------------------------------------------------------------------------
WHY NOT THE THREE COLUMNS `resolve_destination` ASKED FOR
--------------------------------------------------------------------------------

The worker's docstring sketched the migration it wanted:

    ALTER TABLE organizations
        ADD COLUMN notify_whatsapp_e164 text,
        ADD COLUMN whatsapp_opt_in_at   timestamptz,
        ADD COLUMN whatsapp_opt_in_source text;

That sketch is not built, and the reason is worth recording because it is the same
reason `consent_ledger` is a ledger:

1. **Revocation would be an UPDATE.** Three columns hold the CURRENT state, so
   withdrawing an opt-in means nulling them — which destroys the evidence of the opt-in
   that was live when we sent last month's alerts. DPDP §6(6) requires withdrawal to be
   as easy as consent, not that it erase the record of consent; and hard rule 4 already
   settled how this product revokes a messaging permission (a new row that supersedes,
   `compliance/consent.py`). A second, different answer to one question is the defect
   CLAUDE.md names, and the state-column answer is the weaker of the two.
2. **`notify_whatsapp_e164` duplicates `users.phone`.** A second copy of an owner's
   number drifts from the first, and the drift is silent: the console shows one number
   and the alert goes to the other. The opt-in here stores the number it was given FOR,
   which is not a duplicate — it is the SUBJECT of the statement, and comparing it to
   `users.phone` at send time is what makes a changed number invalidate the opt-in
   automatically (see WHY NO EXPIRY WINDOW below).
3. **An opt-in belongs to a PERSON, not to an organisation.** Meta's opt-in is obtained
   from the person who will receive the messages. `organizations` has no place to say
   WHOSE agreement it holds, so an owner handover would silently inherit the previous
   owner's consent — a new human receiving WhatsApp they never agreed to, from a WABA
   they have never heard of, which is precisely the complaint that gets a WABA
   restricted.

--------------------------------------------------------------------------------
WHAT MAKES A ROW EVIDENCE RATHER THAN A BOOLEAN (researched 2026-08-14)
--------------------------------------------------------------------------------

Meta's own documentation is unreachable from this build environment —
`developers.facebook.com` and `graph.facebook.com` both return 403 at the egress proxy
— so the requirement below is sourced from secondary summaries of it and is marked that
way, exactly as `apps/api/ingest/meta.py` marks its Meta sources. It is consistent
across every source read and consistent with the November-2024 policy update that
`compliance/consent.py` already cites.

* A business must obtain opt-in before sending business-initiated messages; the opt-in
  may be collected on any channel and need not name WhatsApp since the Nov-2024 policy
  update, but it must be an AFFIRMATIVE act (a pre-ticked box does not qualify) and it
  must state that the person will receive messages and from whom.
* Per contact, a business is expected to be able to produce three things when a number
  is challenged: the **timestamp** of the opt-in, the **source/channel** it was
  collected through, and the **consent text shown** — the exact wording the person saw
  and agreed to. "An opt-in you can't evidence is an opt-in you don't have."
  (blueticks.co/blog/whatsapp-opt-in-compliance-requirements; wetarseel.ai/whatsapp-
  business-api-opt-in-rules; cm.com/blog/whatsapp-opt-in — all SECONDARY, summarising
  developers.facebook.com "Get opt-in for WhatsApp" and the Nov-2024 Business Messaging
  Policy update.)

So the columns are not decoration: `captured_at` is the timestamp, `channel` is the
source, `notice_version` is the consent text shown — pinned by version rather than
copied, so the wording lives in one place and a row says which one it was. A grant that
cannot answer all three is refused by `ck_..._granted_optin_is_evidenced`, which is the
only form of that rule that survives a writer who never read this docstring.

DPDP §6 lands in the same place from the other direction: consent must be free,
specific, informed, unconditional and unambiguous, by clear affirmative action, limited
to the stated purpose and withdrawable as easily as given. `notice_version` is the
"informed" half made checkable; the append-only trigger is the "withdrawable" half.

--------------------------------------------------------------------------------
WHO MAY RECORD ONE, AND THE ASYMMETRY THAT MATTERS
--------------------------------------------------------------------------------

Two channels, because a client owner opting THEMSELVES in and an operator recording
that they did are different acts with different evidence:

    self_serve_console  the owner ticked an unticked box on their own settings screen,
                        authenticated as themselves in the client realm. The act IS the
                        record, so it needs no document — but the CHECK requires
                        `recorded_by_user_id = user_id`, which makes "an operator
                        quietly writing a self-serve row on someone's behalf"
                        unrepresentable rather than merely discouraged.
    operator_recorded   a Calevate operator recording that the owner agreed during
                        onboarding. Requires an admin id AND an `evidence` reference to
                        the document the agreement is in — the same shape
                        `kyc_records.ck_..._verified_names_its_evidence` uses for the
                        same reason: a release nobody can account for later is the audit
                        finding these tables exist to avoid.

This is deliberately NOT the asymmetry `consent_ledger` uses, and the difference is
argued rather than assumed. There, `staff_recorded_request` is CHECK-barred from
granting at all, because the subject is a CONSUMER STRANGER and a client's staff
asserting a stranger's opt-in is "implied consent" wearing a different name. Here the
subject is our own contracting counterparty, whose signed onboarding pack we hold, so an
evidenced operator record is the same legitimate act as `offline_form_optin` next door —
which IS grant-capable there. What must not be possible is an UNEVIDENCED one, and that
is what the CHECK forbids.

Both channels are barred from the impersonation path in the application layer: recording
is `org:manage`, which is in `MUTATING_PERMISSIONS`, so a "view as client" admin session
(D-22) cannot opt a client in while wearing their face.

--------------------------------------------------------------------------------
WHY NO EXPIRY WINDOW (a deliberate departure from `consent_ledger`)
--------------------------------------------------------------------------------

`MESSAGING_CONSENT_VALIDITY_DAYS = 365` time-boxes the CONSUMER opt-in, because TRAI's
2025 amendment refuses indefinite consent and inferred consent dies with the contractual
relationship it was inferred from. Neither premise transfers:

* TRAI/DLT is not the operative regime for this message at all. It governs commercial
  traffic to a subscriber; this is a service notification to our own paying customer
  about their own account, sent from our WABA to a person who has a live contract with
  us. Meta publishes no expiry for an opt-in.
* The relationship the consumer window stands in for is, here, a fact we can actually
  observe on every send. So the expiry is STRUCTURAL rather than clocked, and the read
  in `compliance/whatsapp_optin.py` enforces all three legs:
    - the opt-in is keyed to a `user_id`, so an owner handover does not inherit it;
    - it is keyed to the `phone_e164` it was given for, so a changed number has no
      opt-in and the alert stops until the new number is opted in;
    - `resolve_destination` already excludes deactivated users and non-owners.

That is a stronger control than a timer, and it is chosen over one for a reason worth
stating plainly: a clock would silently switch off a client's hot-lead alerts on a day
nobody is watching, which is the exact failure — "nobody was told about a hot lead" —
that this whole feature exists to prevent. A timer that fails closed on a safety alert
is not conservatism, it is an outage with a compliance justification. Revocation stays
instant and is the client's own (a new row), and every structural leg above fails closed
the moment the fact underneath it changes.

--------------------------------------------------------------------------------
THE TABLE
--------------------------------------------------------------------------------

Tenant-scoped, so it ships WITH its FORCEd `tenant_isolation` policy in this same
migration (hard rule 1) and with the cross-tenant zero-rows test in
`tests/whatsapp_optin_test.py`. Append-only, so it carries the `calevate_forbid_mutation`
trigger migration 05bba2f3c19c created (hard rule 4) and is added to
`APPEND_ONLY_TABLES`.

The index is exactly the read `read_alert_optin` runs — latest row for one
(tenant, user, phone) — with `status` and `captured_at` included so the lookup is
index-only and never sorts a heap. `(captured_at DESC, created_at DESC)` for the same
reason `ix_consent_ledger_messaging_lookup` uses both: `captured_at` is when the person
SPOKE and `created_at` is when we wrote it down, and two rows captured in the same
instant must still resolve deterministically rather than by planner whim.

NOT `CONCURRENTLY`: a concurrent build cannot run inside alembic's transaction, and the
table is new and empty, so the build is instantaneous. (`f9c2b41a8e57`'s CONCURRENTLY
index is the cautionary tale — a failed concurrent build leaves an INVALID index.)

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Reversible in hard rule 8's sense and honestly so: the table is NEW, nothing backfills
it, and no pre-existing column changes meaning. `downgrade` drops it whole.

The one consequence to state rather than discover: reverting re-opens the gap this
closes. `resolve_destination` reads this table, so without it the hot-lead WhatsApp
alert goes back to refusing `recipient_not_opted_in` for every client — the behaviour of
the release before this one, which is why the revert is safe, and a compliance decision
rather than a rollback, which is why it is written down. Nothing is deleted that a
client could be asked to reproduce: an opt-in destroyed by a downgrade is one the client
must be asked for again, so a revert that has been live long enough to collect rows
should dump the table first.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e6b2d94f31a7"
down_revision: str | None = "3a91c7e04d58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "whatsapp_alert_optin_ledger"
IX_CURRENT = "ix_whatsapp_alert_optin_current"

# Spelled out rather than imported from `compliance/models.py`. A migration is a snapshot
# of the schema on the day it ran; importing today's tuple would silently rewrite history
# the next time somebody adds a member (the rule c2f7a91b4e63, b8e4c1d70f92 and
# a4e7b2c95d18 all state).
_STATUS_SQL = "status IN ('granted', 'withdrawn')"
_CHANNEL_SQL = "channel IN ('self_serve_console', 'operator_recorded')"
# One constraint, three sentences: a grant names the wording the person agreed to; a
# self-serve grant was recorded BY its own subject; an operator's grant names the
# operator and the document. Withdrawals are exempt by construction — consent must be
# evidenced, a refusal must never be obstructed (the rule `consent_ledger` states).
_GRANT_EVIDENCE_SQL = (
    "status <> 'granted' OR (notice_version IS NOT NULL AND ("
    "(channel = 'self_serve_console' AND recorded_by_user_id = user_id) "
    "OR (channel = 'operator_recorded' AND recorded_by_admin_id IS NOT NULL "
    "AND evidence IS NOT NULL)))"
)
# Every row names exactly one recorder. "Nobody recorded this" is an anonymous consent
# record; "both recorded it" is two accountable parties for one act, which resolves to
# neither. The FKs say WHO, this says HOW MANY.
_RECORDER_SQL = "(recorded_by_user_id IS NULL) <> (recorded_by_admin_id IS NULL)"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        TABLE,
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        # WHOSE opt-in. Not the organisation's — see the docstring: an owner handover
        # must not inherit the previous owner's agreement.
        sa.Column("user_id", sa.UUID(), nullable=False),
        # The number the opt-in was given FOR. Compared against `users.phone` at send
        # time, which is what makes a changed number fail closed with no clock involved.
        sa.Column("phone_e164", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        # Meta's "source/channel" half of the evidence.
        sa.Column("channel", sa.String(), nullable=False),
        # Meta's "consent text shown" half, pinned by version rather than copied: the
        # wording lives in ONE place (`compliance/whatsapp_optin.py`) and a row records
        # which version of it the person actually saw.
        sa.Column("notice_version", sa.Text(), nullable=True),
        # Meta's "timestamp" half. When the person AGREED, which is not always when we
        # wrote it down — an operator recording an onboarding form does both at once,
        # but the two are different facts and the read orders on both.
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The client-realm principal who recorded it. For a self-serve grant this IS the
        # subject, enforced by the CHECK above.
        sa.Column("recorded_by_user_id", sa.UUID(), nullable=True),
        # The admin-realm operator who recorded it. An `admin_users.id`, not a typed
        # name: an auditor asks who, and a string nobody can resolve to a person is not
        # an answer (the rule `kyc_records.verified_by_admin_id` states).
        sa.Column("recorded_by_admin_id", sa.UUID(), nullable=True),
        # WHAT an operator's record rests on — the onboarding document reference, the
        # ticket id. A reference, never the document (the `secret_ref` principle).
        sa.Column("evidence", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(_STATUS_SQL, name=op.f(f"ck_{TABLE}_status_enum")),
        sa.CheckConstraint(_CHANNEL_SQL, name=op.f(f"ck_{TABLE}_channel_enum")),
        sa.CheckConstraint(
            _GRANT_EVIDENCE_SQL, name=op.f(f"ck_{TABLE}_granted_optin_is_evidenced")
        ),
        sa.CheckConstraint(_RECORDER_SQL, name=op.f(f"ck_{TABLE}_names_one_recorder")),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["organizations.id"],
            name=op.f(f"fk_{TABLE}_tenant_id_organizations"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f(f"fk_{TABLE}_user_id_users"), ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_user_id"],
            ["users.id"],
            name=op.f(f"fk_{TABLE}_recorded_by_user_id_users"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["recorded_by_admin_id"],
            ["admin_users.id"],
            name=op.f(f"fk_{TABLE}_recorded_by_admin_id_admin_users"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f(f"pk_{TABLE}")),
    )

    # Exactly the read `read_alert_optin` runs: latest row for one (tenant, user, phone).
    # `status` and `captured_at` are INCLUDEd so the lookup is index-only — this runs on
    # the hot-lead path, which is racing a two-minute SLO.
    op.execute(
        f"CREATE INDEX {IX_CURRENT} ON {TABLE} "
        "(tenant_id, user_id, phone_e164, captured_at DESC, created_at DESC) "
        "INCLUDE (status)"
    )

    # Tenant isolation (DATA-MODEL §1) + FORCE so the owner role is subject to it. No
    # WITH CHECK clause: for a FOR ALL policy Postgres reuses the USING expression as the
    # write check, so a session cannot insert an opt-in for a tenant it cannot read.
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY tenant_isolation ON {TABLE} USING ("
        "tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )

    # Append-only (hard rule 4), reusing the function migration 05bba2f3c19c created.
    # A withdrawal is a NEW row; the grant it supersedes survives, because the question
    # "were we allowed to send that alert in March?" is asked in April.
    op.execute(
        f"CREATE TRIGGER {TABLE}_append_only BEFORE UPDATE OR DELETE ON {TABLE} "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"DROP TRIGGER IF EXISTS {TABLE}_append_only ON {TABLE}")
    op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {TABLE}")
    op.execute(f"DROP INDEX IF EXISTS {IX_CURRENT}")
    op.drop_table(TABLE)
