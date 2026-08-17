"""two notices, two toggles — the AI sentence and the recording notice stop sharing a column

Revision ID: f4a1d0b6e29c
Revises: c4f18a6b90e2
Create Date: 2026-08-17 00:30:00.000000

D-163. SEC-COMP §2 has always stated TWO call-level invariants:

  1. **AI disclosure** — the first utterance identifies the assistant as AI (TRAI/UCC).
  2. **Recording consent** — "disclosure includes recording notice" (DPDP §5/§6 notice
     and consent, a different statute and a different regulator).

They shared ONE column. The seeded Telugu line says so out loud —
`"Namaskaram, idi {business} AI assistant. Ee call record avutundi."` is two sentences
under two regimes in one `TEXT NOT NULL` — and the consequence was that a client could
have both notices or neither, and nothing in between. This migration is the founder's
decision that each is separately controllable, per agent, on inbound and outbound alike.

WHAT IS *NOT* TOGGLEABLE, and is deliberately not a column here: answering truthfully
when a caller ASKS. "Are you a human?" is answered "I am an AI assistant" and "is this
recorded?" is answered "yes" on every agent, always. That behaviour lives in
`calevate_shared.engine.TRUTHFUL_ANSWER_DIRECTIVE` — a `Final` in the portability
contract, appended by every adapter to every prompt, verified on read-back by
`agents/verification.judge`, and absent from this schema on purpose. A column would be a
writer, and a writer is how a client's own script could eventually reach it.

THE FOUR COLUMNS
----------------
`ai_disclosure_line`      TEXT NOT NULL, non-empty. The AI sentence.
`recording_notice_line`   TEXT NOT NULL, non-empty. The recording sentence.
`ai_disclosure_enabled`   BOOLEAN NOT NULL DEFAULT true.
`recording_notice_enabled` BOOLEAN NOT NULL DEFAULT true.

**The text is mandatory and the toggle is not.** The compliance gate refuses an agent
with no AI disclosure ON FILE (`compliance/service.check_dispatch`), and the truthful
answer needs a sentence to give; whether the sentence is VOLUNTEERED at the top of a call
is the tenant's choice. Both toggles default TRUE so that an omission — a forgotten
column in a future INSERT, a row written by an importer — produces the posture with no
legal exposure rather than the one with it.

`agents.disclosure_line` IS UNTOUCHED, AND THAT IS HARD RULE 8
--------------------------------------------------------------
Step 1 of a two-step deprecation: this release stops READING it on the publish path and
keeps WRITING it (`compliance/disclosure.bundled_disclosure_line` joins the two sentences
whatever the toggles say, so the NOT NULL and the non-empty CHECK still hold and the
admin roster keeps rendering). Step 2 — the `drop` — is a later release, named in D-163.

THE BACKFILL, AND WHY IT DOES NOT TRY TO BE CLEVER
---------------------------------------------------
Splitting free text is not something a migration may guess at, so it does not:

* Rows whose `disclosure_line` is **exactly** one of the three strings this repository
  itself seeded (`admin/service.DISCLOSURE_TEMPLATES`, rendered per business name) are
  split at the sentence boundary this migration knows because we wrote it. That is a
  rewrite of OUR OWN string, matched by equality on the rendered suffix, not a parse.
* Every other row is copied VERBATIM into `ai_disclosure_line`, and
  `recording_notice_line` is filled from the per-language default.

The second case can leave a recording clause inside the AI sentence, so an agent that
later switches the recording notice off may still say "this call is recorded". That error
is in the OVER-disclosing direction and stays there: the toggle governs the NOTICE, never
whether the call is recorded (nothing in this codebase can switch recording off), so the
worst outcome is a client saying more than they had to. The other direction — a row that
silently stops disclosing — is not reachable from this backfill, because nothing here
sets a toggle to false.

NO RLS CHANGE, VERIFIED RATHER THAN ASSUMED. `agents` carries its FORCEd policy from
`05bba2f3c19c` and a column added to a table under RLS inherits it — there is no
per-column grant in Postgres RLS. The assertion below re-reads `pg_class.relrowsecurity`
/ `relforcerowsecurity` after the DDL rather than trusting that sentence, and
`tests/disclosure_toggle_test.py` proves the cross-tenant read returns zero rows through
the new columns specifically (hard rule 1).

REVERSIBLE. The downgrade drops the four columns and their two constraints; nothing else
depends on them, and `disclosure_line` — deliberately untouched on the way up — is still
populated on the way down, so a rollback leaves a working agent rather than a mute one.
That is the whole reason the legacy column is kept rather than migrated.
"""

import sqlalchemy as sa
from alembic import op

revision = "f4a1d0b6e29c"
# LINEARISED ONTO `e83b5d1a4c07` rather than onto `c4f18a6b90e2`, which is what this
# revision was written against. Both were authored in parallel off the same parent, which
# left the chain with two heads — and `check_wiring` requires exactly one, for the reason
# `alembic upgrade head` refuses to guess between them.
#
# Re-parenting is safe HERE and is not safe in general. These two revisions are disjoint
# and order-independent: `e83b5d1a4c07` adds `calls.crm_notified_at` and
# `outbox_messages.dedupe_key` with their indexes; this one adds four columns to `agents`
# and backfills from `agents` alone. Neither reads a table the other writes, so composing
# them in either order produces the same schema and the same data. A merge revision would
# have been the alternative and buys nothing here — it exists to make a genuine
# convergence explicit, and there is no convergence to make explicit when the two sides
# never touch.
down_revision = "e83b5d1a4c07"
branch_labels = None
depends_on = None

CK_AI_NONEMPTY = "ck_agents_ai_disclosure_nonempty"
CK_RECORDING_NONEMPTY = "ck_agents_recording_notice_nonempty"

# FROZEN COPIES of `compliance/disclosure.{AI_DISCLOSURE,RECORDING_NOTICE}_TEMPLATES` as
# they read the day this revision was written. A migration is a historical artefact and
# importing today's constants would make an OLD migration replay differently after a
# future template edit — the standard alembic discipline, and the reason
# `tests/disclosure_toggle_test.py` asserts the two copies still agree TODAY so the drift
# is caught while it is still free.
AI_TEMPLATES = {
    "te-IN": "Namaskaram, idi {business} AI assistant.",
    "hi-IN": "Namaste, main {business} ka AI assistant hoon.",
    "en-IN": "Hello, this is the AI assistant for {business}.",
}
RECORDING_TEMPLATES = {
    "te-IN": "Ee call record avutundi.",
    "hi-IN": "Yeh call record ho rahi hai.",
    "en-IN": "This call is being recorded.",
}
DEFAULT_LANGUAGE = "en-IN"


def upgrade() -> None:
    # Added NULLABLE with no default, then filled, then made NOT NULL. The three-step is
    # the standard for a NOT NULL column whose value is per-row: a `server_default` would
    # make every existing agent claim a sentence it never had, and this way the fill is
    # visible SQL a reviewer can read rather than a default nobody sees.
    op.add_column("agents", sa.Column("ai_disclosure_line", sa.Text(), nullable=True))
    op.add_column("agents", sa.Column("recording_notice_line", sa.Text(), nullable=True))

    for language, notice in RECORDING_TEMPLATES.items():
        # THE ONE ROW SHAPE WE ARE ENTITLED TO SPLIT: a line this repository generated,
        # recognised by its own suffix. `right(disclosure_line, length(:notice))` is an
        # equality on the tail, not a search — so "…AI assistant. Ee call record
        # avutundi." splits and a tenant's own sentence that merely mentions recording
        # does not.
        op.execute(
            sa.text(
                "UPDATE agents SET "
                "  ai_disclosure_line = btrim(left(disclosure_line, "
                "    length(disclosure_line) - length(:notice))), "
                "  recording_notice_line = :notice "
                "WHERE language_primary = :lang "
                "  AND right(disclosure_line, length(:notice)) = :notice "
                "  AND length(btrim(left(disclosure_line, "
                "    length(disclosure_line) - length(:notice)))) > 0"
            ).bindparams(notice=notice, lang=language)
        )
        # A LEGACY LINE THAT IS BLANK IS ITSELF A LATENT DEFECT, and the backfill is where
        # it surfaces. `ck_agents_disclosure_nonempty` is `length(disclosure_line) > 0`
        # WITHOUT a `btrim`, so `'   '` has always satisfied it — an agent that opens a
        # call disclosing nothing, which `tests/campaign_dispatch_audit_test.py` names as
        # the one shape that CHECK still admits and which the dial gate had to refuse at
        # run time. The new columns carry `btrim`, so such a row cannot simply be copied.
        # It is filled from THIS platform's own template for the agent's language and its
        # organization's name — precisely what `admin/service.create_organization` would
        # have written — because a compliance sentence is not something a migration may
        # leave blank, and inventing one from our own template is the only invention here
        # that is not a guess. Runs BEFORE the verbatim copy so it wins for these rows.
        op.execute(
            sa.text(
                "UPDATE agents a SET "
                "  ai_disclosure_line = replace(:ai_template, '{business}', o.name), "
                "  recording_notice_line = :notice "
                "FROM organizations o "
                "WHERE o.id = a.tenant_id AND a.language_primary = :lang "
                "  AND a.ai_disclosure_line IS NULL "
                "  AND length(btrim(a.disclosure_line)) = 0"
            ).bindparams(notice=notice, lang=language, ai_template=AI_TEMPLATES[language])
        )
        # Anything else in this language: copied verbatim, notice defaulted. See the
        # docstring for why a verbatim copy is the safe direction of error.
        op.execute(
            sa.text(
                "UPDATE agents SET ai_disclosure_line = disclosure_line, "
                "  recording_notice_line = :notice "
                "WHERE language_primary = :lang AND ai_disclosure_line IS NULL "
                "  AND length(btrim(disclosure_line)) > 0"
            ).bindparams(notice=notice, lang=language)
        )

    # A language outside the three we ship (the column is free text, not an enum) falls
    # back to English rather than to NULL — a row this migration could not classify must
    # still satisfy the NOT NULL below, and failing the whole release over an unexpected
    # locale would be a worse answer than an English recording notice. `NULLIF`+`COALESCE`
    # applies the blank rule above to those rows too, in one statement rather than by
    # repeating the join.
    op.execute(
        sa.text(
            "UPDATE agents a SET "
            "  ai_disclosure_line = COALESCE(NULLIF(btrim(a.disclosure_line), ''), "
            "    replace(:ai_template, '{business}', o.name)), "
            "  recording_notice_line = :notice "
            "FROM organizations o "
            "WHERE o.id = a.tenant_id AND a.ai_disclosure_line IS NULL"
        ).bindparams(
            notice=RECORDING_TEMPLATES[DEFAULT_LANGUAGE],
            ai_template=AI_TEMPLATES[DEFAULT_LANGUAGE],
        )
    )

    op.alter_column("agents", "ai_disclosure_line", nullable=False)
    op.alter_column("agents", "recording_notice_line", nullable=False)

    # Spelled out rather than `op.create_check_constraint`, which applies this project's
    # naming convention to a name that already carries it and produces
    # `ck_agents_ck_agents_…` (measured on a real database — see `c4f18a6b90e2`).
    op.execute(
        f"ALTER TABLE agents ADD CONSTRAINT {CK_AI_NONEMPTY} "
        "CHECK (length(btrim(ai_disclosure_line)) > 0)"
    )
    op.execute(
        f"ALTER TABLE agents ADD CONSTRAINT {CK_RECORDING_NONEMPTY} "
        "CHECK (length(btrim(recording_notice_line)) > 0)"
    )

    op.add_column(
        "agents",
        sa.Column(
            "ai_disclosure_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
    )
    op.add_column(
        "agents",
        sa.Column(
            "recording_notice_enabled", sa.Boolean(), server_default="true", nullable=False
        ),
    )

    _assert_rls_still_forced()


def _assert_rls_still_forced() -> None:
    """Hard rule 1, re-read from the catalog instead of asserted in the docstring.

    Adding a column to an RLS'd table inherits the policy — there is no per-column RLS in
    Postgres — but "inherits" is the kind of sentence that is true until somebody's
    `ALTER TABLE` in a neighbouring revision turns FORCE off. `check_rls_coverage` asks
    this of the whole schema on every `make guardrails`; asking it HERE is what stops a
    release shipping the four columns onto an unprotected table in the first place.
    """
    row = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'public.agents'::regclass"
            )
        )
        .first()
    )
    if row is None or not (row[0] and row[1]):
        raise RuntimeError(
            "agents is not FORCE ROW LEVEL SECURITY after this migration; the four "
            "disclosure columns would be readable across tenants (hard rule 1)"
        )


def downgrade() -> None:
    op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {CK_RECORDING_NONEMPTY}")
    op.execute(f"ALTER TABLE agents DROP CONSTRAINT IF EXISTS {CK_AI_NONEMPTY}")
    op.drop_column("agents", "recording_notice_enabled")
    op.drop_column("agents", "ai_disclosure_enabled")
    op.drop_column("agents", "recording_notice_line")
    op.drop_column("agents", "ai_disclosure_line")
