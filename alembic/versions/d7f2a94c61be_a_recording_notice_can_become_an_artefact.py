"""The recording notice becomes a recordable basis — `purpose='recording'` gets a writer.

Revision ID: d7f2a94c61be
Revises: b6f21d9c4e07

--------------------------------------------------------------------------------
WHAT WAS WRONG
--------------------------------------------------------------------------------

`purpose='recording'` has been a permitted `consent_ledger` value since the first
migration and has had NO WRITER ANYWHERE in the tree — not in `apps/`, not in `scripts/`,
not in the seed. It was a CHECK value describing an artefact the product could not
produce, on the one obligation (DPDP notice-and-consent for recording a person's voice)
that every call in the system engages.

A positive artefact only became possible when `calls.disclosure_played` started being
genuinely written (P3.3, `apps/workers/pipeline.py::_record_disclosure`), because the
same transcript pass that scores the AI sentence can score the RECORDING sentence — and
`compliance/disclosure.disclosure_spoken` is already generic over which line it is given.

**⚠ AND THE PREMISE HAS ONE CORRECTION THAT MATTERS.** `calls.disclosure_played` is NOT
evidence that the recording notice was announced. Since D-163 it scores the **AI
sentence only** — `pipeline._load_call_context` deliberately selects
`CASE WHEN a.ai_disclosure_enabled THEN a.ai_disclosure_line ELSE '' END`, and the
comment there says why: an agent whose owner switched the RECORDING notice off would
otherwise be scored against a sentence it was never asked to say. So this revision does
not lean on that column. The pipeline scores `agents.recording_notice_line` separately,
against the same transcript, gated on `agents.recording_notice_enabled`.

--------------------------------------------------------------------------------
WHAT THIS REVISION ADDS, AND WHY IT IS A NEW SOURCE RATHER THAN AN EXISTING ONE
--------------------------------------------------------------------------------

One new `consent_source`: **`in_call_recording_notice`**.

`CONSENT_SOURCES`' own comment in `compliance/models.py` says the vocabulary is "never
'assumed', never 'implied', never inferred" — and every existing member describes a
person SAYING or DOING something (`inbound_call_verbal`, `web_form_optin`,
`offline_form_optin`, `whatsapp_inbound_message`). What this artefact records is a
different basis: the business announced that the call was being recorded, and the caller
went on speaking. Filing that under `inbound_call_verbal` would be a false statement
about how the record was obtained — the caller said nothing about recording — and it is
exactly the laundering hard rule 11 forbids. A basis that is not one of the existing four
gets its own name, so that anybody reading the row, the export or a regulator's copy can
see the basis rather than infer it.

**THIS DOES NOT SETTLE WHETHER RECORDING CONSENT IS REQUIRED, AND MUST NOT BE READ AS
SETTLING IT.** That is OPERATIONS §2 gate 37(a) — is a voice recording SPDI biometric
data — and it is with an advocate. LEGAL-OPS-PLAYBOOK §12.3 records the founder's
current posture in one line ("Recording: cautious practice = announce. Case law on
one-party recording is messy; do not rely on 'India is one-party' as a slogan"). What
this revision does is make the ARTEFACT exist, so that whichever way the advice lands
there is a per-call record of what the caller was told and when. **No gate reads
`purpose='recording'`** — not `check_dispatch`, not the campaign launch gate, not
`apply_retention` — so nothing in the system behaves differently because of these rows.

--------------------------------------------------------------------------------
THE THREE CONSTRAINTS
--------------------------------------------------------------------------------

1. `ck_consent_ledger_source_enum` is widened by exactly one member.
2. `ck_consent_ledger_recording_notice_scope` — NEW. The new source may appear ONLY on a
   `purpose='recording'` row, and only with `call_id` set. Both halves are the same
   protection: the basis is "this specific call opened with the notice", so it names the
   call, and it can never be spent as a messaging opt-in or as permission to dial. The
   service layer refuses it on both other purposes too; this is the constraint that makes
   the refusal true of anything that bypasses the service.
3. `ck_consent_ledger_granted_consent_carries_evidence` is UNCHANGED and already binds:
   it is purpose-blind, so a `granted` recording row must carry `evidence` (the pipeline
   writes the notice's turn index and the line's hash prefix — never the text, hard rule
   6) and may not come from `staff_recorded_request`.

`lock_timeout` bounds the wait so a queued ACCESS EXCLUSIVE cannot park in front of every
other session (hard rule 8).

RLS: no new table and no new column, so no new policy. `consent_ledger` has carried its
FORCEd `tenant_isolation` policy since `05bba2f3c19c`.

Append-only: nothing here UPDATEs or DELETEs a row (hard rule 4).

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Same honest wrinkle as `c2f7a91b4e63`, for the same reason and with the same answer.
Rows written under this revision are `consent_ledger` rows and hard rule 4 forbids
deleting them, so the narrowed source CHECK is restored **NOT VALID**: it binds every
future INSERT (the new source becomes unwritable again, which is the pre-migration
behaviour) while leaving the rows already captured in place. Validating it would fail,
and the only way to make it validate is a deletion this repository does not permit.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d7f2a94c61be"
down_revision: str | None = "b6f21d9c4e07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "consent_ledger"

CK_SOURCE = "ck_consent_ledger_source_enum"
CK_RECORDING_SCOPE = "ck_consent_ledger_recording_notice_scope"

# Spelled out rather than imported from `compliance/models.py`. A migration is a snapshot
# of the schema on the day it ran; importing today's tuple would silently rewrite history
# the next time somebody adds a member (the rule `c2f7a91b4e63` states and follows).
_SOURCE_SQL_BEFORE = (
    "consent_source IS NULL OR consent_source IN ('inbound_call_verbal', 'web_form_optin', "
    "'offline_form_optin', 'whatsapp_inbound_message', 'staff_recorded_request')"
)
_SOURCE_SQL = (
    "consent_source IS NULL OR consent_source IN ('inbound_call_verbal', 'web_form_optin', "
    "'offline_form_optin', 'whatsapp_inbound_message', 'staff_recorded_request', "
    "'in_call_recording_notice')"
)
_RECORDING_SCOPE_SQL = (
    "consent_source IS DISTINCT FROM 'in_call_recording_notice' "
    "OR (purpose = 'recording' AND call_id IS NOT NULL)"
)


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_SOURCE}")
    for name, expression in (
        (CK_SOURCE, _SOURCE_SQL),
        (CK_RECORDING_SCOPE, _RECORDING_SCOPE_SQL),
    ):
        # NOT VALID then VALIDATE: the widening cannot fail on existing rows (it only
        # adds a permitted value) and the scope check matches zero of them, but the
        # two-step takes a weaker lock for the scan and is the pattern this table's
        # earlier revisions use.
        op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {name} CHECK ({expression}) NOT VALID")
        op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {name}")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_RECORDING_SCOPE}")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_SOURCE}")
    # NOT VALID on purpose — see the DOWNGRADE section of the module docstring.
    op.execute(
        f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_SOURCE} CHECK ({_SOURCE_SQL_BEFORE}) NOT VALID"
    )
