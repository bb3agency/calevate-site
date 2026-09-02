"""re-run the three backfills row-level security swallowed

Revision ID: b7e35c2f81da
Revises: e1a4d70c9b52
Create Date: 2026-09-02

`tests/migration_rls_bracket_test.py` found seven migrations that write rows to FORCE-RLS
tables without lifting RLS. The owner is subject to `tenant_isolation`, which is fail-closed
on an unset `app.tenant_id`, so each statement matched ZERO rows and reported success. Those
revisions have already run everywhere and will never run again, so editing them repairs
nothing that has happened — only a later migration can. This is that migration.

--------------------------------------------------------------------------------
WHAT IS AND IS NOT REPAIRED HERE, AND WHY
--------------------------------------------------------------------------------
Of the seven, only the ones whose statement lives in `upgrade()` can have done damage; four
were `downgrade()`-only and a downgrade has never run in production. Those four are fixed
IN PLACE in the same change as this file — a downgrade that has never executed can be
corrected without rewriting history, and the fix matters for any future fresh install that
migrates the whole chain from base.

So three are repaired here:

* **`f4a1d0b6e29c` — the disclosure split.** Splits the legacy bundled `disclosure_line`
  into `ai_disclosure_line` / `recording_notice_line` (D-163). Hard rule 5 territory.
* **`f4b1e9a2c7d0` — the extraction-field key rename.** `description` -> `reason` inside
  `extraction_schemas.fields`; a schema still carrying the old key renders a column
  `crm/columns.resolve` cannot resolve.
* **`e83b5d1a4c07` — `calls.crm_notified_at`.** Backfilled from the outbox so the CRM probe
  stops rescanning delivered calls.

**NOT repaired: `dc1aaeeeff02`'s `kb_chunks` projection, deliberately.** Its INSERT is
already the sweep's own self-healing statement — the worker READS `_BACKFILL` from that
module precisely so the two cannot drift — so the projection heals itself on the next tick
and duplicating that SQL here would be a second way to do one thing (CLAUDE.md), with the
copy free to rot. The guard clears that migration for a second reason too: it inserts
BEFORE the table's policy exists, which its own docstring states outright.

**NOT repaired: `d4a9c17e6b02`'s copilot-memory retention row** — `e1a4d70c9b52::_REPAIR`
already carries it.

--------------------------------------------------------------------------------
EVERY STATEMENT HERE IS IDEMPOTENT, BECAUSE THIS RUNS ON HEALTHY DEPLOYMENTS TOO
--------------------------------------------------------------------------------
A deployment whose migration role was NOT subject to RLS (a superuser owner, which is the
local development case) ran all three correctly the first time. This migration runs there
as well and must be a no-op, so each statement carries a predicate that is false once the
work is done. Two of the three were already written that way and are copied verbatim; the
third was not, and is the one place this file deviates from the original — see `_CALLS`.

The FROZEN COPY discipline applies as always: the sentences and SQL below are copies of
what those migrations held on the day they were written, not imports of today's constants,
because a repair must reproduce what SHOULD have happened then rather than what today's
templates would say. `tests/migration_rls_bracket_test.py` reads this file and the
originals and fails if the copies drift.
"""

from __future__ import annotations

from alembic import op

revision = "b7e35c2f81da"
down_revision = "e1a4d70c9b52"
branch_labels = None
depends_on = None

#: FROZEN COPIES of `f4a1d0b6e29c`'s tables, which were themselves frozen copies of
#: `compliance/disclosure.{AI_DISCLOSURE,RECORDING_NOTICE}_TEMPLATES`. Two hops from the
#: live constants and deliberately so: this repair must write what that migration would
#: have written, not what today's product would say to a new agent.
_AI_TEMPLATES = {
    "te-IN": "Namaskaram, idi {business} AI assistant.",
    "hi-IN": "Namaste, main {business} ka AI assistant hoon.",
    "en-IN": "Hello, this is the AI assistant for {business}.",
}
_RECORDING_TEMPLATES = {
    "te-IN": "Ee call record avutundi.",
    "hi-IN": "Yeh call record ho rahi hai.",
    "en-IN": "This call is being recorded.",
}
_FALLBACK_LANGUAGE = "en-IN"

#: `f4b1e9a2c7d0`'s rename, verbatim. Idempotent by its own `WHERE EXISTS`: once no element
#: carries `description`, it matches nothing. `WITH ORDINALITY` + `ORDER BY` preserve field
#: order, which is the order the extraction prompt lists fields in.
_RENAME_KEY = """
UPDATE extraction_schemas
SET fields = COALESCE(
    (
        SELECT jsonb_agg(
            CASE
                WHEN elem ? 'description'
                THEN (elem - 'description') || jsonb_build_object('reason', elem -> 'description')
                ELSE elem
            END
            ORDER BY ord
        )
        FROM jsonb_array_elements(fields) WITH ORDINALITY AS t(elem, ord)
    ),
    fields
)
WHERE EXISTS (
    SELECT 1 FROM jsonb_array_elements(fields) AS e WHERE e ? 'description'
)
"""

#: `e83b5d1a4c07`'s backfill PLUS one added predicate — the only deviation in this file.
#:
#: The original ran immediately after the column was added, when every row was NULL, so it
#: needed no guard. Re-running it now without one would OVERWRITE values the application has
#: written since with the outbox's `min(created_at)` — silently moving a timestamp the CRM
#: probe reads, on rows that were never broken. `AND c.crm_notified_at IS NULL` makes it
#: repair-only.
_CALLS = """
UPDATE calls c SET crm_notified_at = o.first_at FROM (
  SELECT (payload -> 'data' ->> 'call_id')::uuid AS call_id,
         min(created_at) AS first_at
  FROM outbox_messages
  WHERE job = 'deliver_outbound_webhook'
    AND payload -> 'data' ->> 'call_id' ~
        '^[0-9a-fA-F]{8}(-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}$'
  GROUP BY 1
) o WHERE c.id = o.call_id AND c.crm_notified_at IS NULL
"""

#: Every table this migration reads or writes, all FORCE ROW LEVEL SECURITY. `organizations`
#: is on the list because the disclosure repair JOINS it for the business name — the READ
#: side is filtered by its own policy, which is the half a target-only reading of this bug
#: misses (`tests/migration_rls_bracket_test.READ_SIDE`).
#:
#: WRITTEN OUT ONE STATEMENT PER TABLE below rather than looped over this tuple, which is
#: what the first draft did. A loop builds `ALTER TABLE {table} NO FORCE ...` from a
#: variable, so the bracket exists at runtime and is INVISIBLE to any reader that works
#: from the source — including `tests/migration_rls_bracket_test.py`, which duly flagged
#: this file as carrying the very bug it repairs. A guard that cannot see a mitigation is
#: not the guard's failure alone: a human skimming for "does this lift RLS on `calls`"
#: cannot grep for it either.
_BRACKETED = ("agents", "organizations", "extraction_schemas", "calls", "outbox_messages")


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE extraction_schemas NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE calls NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE outbox_messages NO FORCE ROW LEVEL SECURITY")
    try:
        # --- f4a1d0b6e29c: the disclosure split ---------------------------------------
        # Idempotent by `ai_disclosure_line IS NULL`, which is the original's own guard: an
        # agent whose split already happened is skipped. Rows are taken in the same order
        # the original took them — the verbatim tail-split first, then the template
        # fallback — so a database repaired here ends up where the original would have put
        # it rather than somewhere defensible-but-different.
        for language, notice in _RECORDING_TEMPLATES.items():
            quoted = _sql_quote(notice)
            op.execute(
                "UPDATE agents SET "
                "  ai_disclosure_line = btrim(left(disclosure_line, "
                f"    length(disclosure_line) - length({quoted}))), "
                f"  recording_notice_line = {quoted} "
                f"WHERE language_primary = {_sql_quote(language)} "
                "  AND ai_disclosure_line IS NULL "
                f"  AND right(disclosure_line, length({quoted})) = {quoted} "
                "  AND length(btrim(left(disclosure_line, "
                f"    length(disclosure_line) - length({quoted})))) > 0"
            )
        # A row whose bundled line does not end in our own recording sentence cannot be
        # split — it is a tenant's own wording, or a language we do not ship. It is filled
        # from THIS platform's template for the agent's language and its organisation's
        # name, which is what `create_organization` would have written. A compliance
        # sentence is not something a migration may leave blank, and generating one from
        # our own template is the only invention here that is not a guess.
        for language, ai_template in _AI_TEMPLATES.items():
            notice = _RECORDING_TEMPLATES[language]
            op.execute(
                "UPDATE agents a SET "
                f"  ai_disclosure_line = replace({_sql_quote(ai_template)}, "
                "    '{business}', o.name), "
                f"  recording_notice_line = {_sql_quote(notice)} "
                "FROM organizations o "
                f"WHERE o.id = a.tenant_id AND a.language_primary = {_sql_quote(language)} "
                "  AND a.ai_disclosure_line IS NULL"
            )
        # A language outside the three we ship — the column is free text, not an enum — is
        # not left NULL. English is the fallback the renderer itself uses.
        op.execute(
            "UPDATE agents a SET "
            f"  ai_disclosure_line = replace({_sql_quote(_AI_TEMPLATES[_FALLBACK_LANGUAGE])}, "
            "    '{business}', o.name), "
            f"  recording_notice_line = {_sql_quote(_RECORDING_TEMPLATES[_FALLBACK_LANGUAGE])} "
            "FROM organizations o "
            "WHERE o.id = a.tenant_id AND a.ai_disclosure_line IS NULL"
        )

        # --- f4b1e9a2c7d0: the extraction-field key rename ------------------------------
        op.execute(_RENAME_KEY)

        # --- e83b5d1a4c07: calls.crm_notified_at ----------------------------------------
        op.execute(_CALLS)
    finally:
        # RESTORED IN A `finally`, not merely after. DDL is transactional in Postgres, so a
        # failure would roll the whole bracket back anyway — but a bracket that depends on
        # the transaction for its safety reads as if it does not need closing, and the next
        # person to copy this pattern into a non-transactional context would inherit an
        # open one. Half a bracket is a tenancy hole (hard rule 1) that no RLS coverage
        # check would then see, because `relrowsecurity` is still true and only FORCE is
        # gone.
        op.execute("ALTER TABLE outbox_messages FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE calls FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE extraction_schemas FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    """Deliberately empty, and that is not laziness (hard rule 8 asks for reversible).

    This migration writes no schema and invents no data: it fills in values three earlier
    migrations were supposed to write and could not see the rows to write. Undoing it would
    mean re-emptying columns the application now depends on — `ai_disclosure_line` is NOT
    NULL with a non-blank CHECK, so "undo" is not even expressible — and would restore a
    state that was a defect rather than a decision. Downgrading past this revision leaves
    the repaired rows repaired, which is the correct outcome.
    """
