"""caller memory: the agent says so, and forgets on a clock of its own (D-507)

Revision ID: e1a4d70c9b52
Revises: c6b1f0d47e83
Create Date: 2026-09-01

D-506 built cross-call caller memory, switched off, and named three things the founder had
to decide before it could be offered. This migration is those three answers in schema.

--------------------------------------------------------------------------------
(a) THE AGENT SAYS IT — `agents.caller_memory_notice_line`
--------------------------------------------------------------------------------
D-163 split the opening into two obligations with two switches, because both hold whatever
this product is configured to do: the call IS AI and the call IS recorded, so a client who
gives those notices in writing may switch off the spoken form. Cross-call memory is not
like that. It exists ONLY because `agents.caller_memory_enabled` is on — a choice this
system records — so the third sentence takes NO SWITCH OF ITS OWN and is spoken exactly
when that flag is true. The state "remembers a caller and does not say so" is therefore not
constructible, rather than merely discouraged.

It is SPOKEN and not only written because `compliance/caller_notice.py`'s draft reaches the
people who came through the client's own funnel, and an INBOUND caller has visited no
website and agreed to no page. Inbound is the product; a notice that misses the caller it
is about is not a notice.

NOT NULL and non-blank like `ai_disclosure_line`, whether or not memory is on, so that
switching it on can never be the moment somebody finds there is nothing to say. Backfilled
in the caller's own language from `agents.language_primary` rather than defaulted to English
for everyone: an agent whose other two sentences are Telugu and whose third is English is a
script that lost its place, and D-36 makes Telugu the product default.

--------------------------------------------------------------------------------
(c) ITS OWN CLOCK — `retention_policies.data_category = 'caller_memory'`
--------------------------------------------------------------------------------
180 days, `delete`. It rode the tenant's `transcript` policy (365 by default, and settable
higher) because `DERIVED_COPIES` argued a memory belongs to the clock of the words it was
distilled from. That argument had the shape of the feature backwards: the PURPOSE of a
memory is to outlive the call, so inheriting the call's period is not a convenience, it is
the wrong clock. `copilot_memory` already answered the same question at 180/`delete` and
its reasons transfer — nothing depends on these rows, use regenerates them, and there is no
anonymised form of a sentence. What does not transfer is the subject: a copilot memory is
about the client's own staff using a product they bought; this is about a caller who never
chose us, which is why the shorter of the two numbers wins where they disagree.

THE ROW IS WRITTEN FOR EVERY EXISTING ORGANISATION, as `d4a9c17e6b02` did for its own
category and for its reason: without it, every tenant created before today holds caller
memories no policy row expires — the exact hole a new category is supposed to close rather
than one it may open.

--------------------------------------------------------------------------------
WHAT THIS MIGRATION DOES NOT DO
--------------------------------------------------------------------------------
(b), the SPDI question, is not schema. The SPDI Rules 2011 list is EXHAUSTIVE and includes
"physical, physiological and mental health condition", and no classifier over a free-text
distilled fact can be trusted to decide whether "asked about IVF pricing" is one. So the
refusal lives at the one door that exists — `compliance/caller_memory.remember` — and is
tested there, rather than as a CHECK constraint that would have to encode a judgement the
database cannot make.
"""

from __future__ import annotations

from alembic import op

revision = "e1a4d70c9b52"
down_revision = "c6b1f0d47e83"
branch_labels = None
depends_on = None

_CATEGORY = "caller_memory"
_TTL_DAYS = 180
_ACTION = "delete"

#: Every category admitted AFTER this migration. Written out rather than derived from the
#: constraint, so a reader sees the whole list at the point it changes.
_CATEGORIES_AFTER = (
    "recording",
    "transcript",
    "lead",
    "consent_log",
    "engine_payload",
    "kb",
    "copilot_memory",
    _CATEGORY,
)
_CATEGORIES_BEFORE = tuple(c for c in _CATEGORIES_AFTER if c != _CATEGORY)

#: The third sentence per language, and it MUST match
#: `apps/api/compliance/disclosure.CALLER_MEMORY_NOTICE_TEMPLATES` — pinned by
#: `tests/caller_memory_notice_test.py`, which reads both. Copied rather than imported for
#: the reason every migration copies its constants: this file must keep meaning what it
#: meant on the day it ran, and an import would make an old migration change under a new
#: release.
_NOTICE = {
    "te-IN": "Meeru adigina daani gurinchi oka chinna note nenu gurthu pettukuntaanu.",
    "hi-IN": "Aapne kya poocha, uska ek chhota note main yaad rakhta hoon.",
    "en-IN": "I keep a short note of what you ask about, so I remember it if you call again.",
}
_FALLBACK = _NOTICE["en-IN"]


#: The row `d4a9c17e6b02` meant to write for every existing organisation and, on a
#: deployment whose migration role is subject to RLS, did not. Retyped from
#: `scripts/seed.DEFAULT_RETENTION_POLICIES` rather than imported, for the reason every
#: migration copies its constants: this file must keep meaning what it meant on the day it
#: ran. `tests/retention_caller_memory_test.py` reads both and fails if they drift.
_REPAIR: tuple[str, int, str] = ("copilot_memory", 180, "delete")


def _seed_policy(category: str, ttl_days: int, action: str) -> str:
    """One default policy row per organisation, for a category, skipping any that has one.

    Runs inside the `NO FORCE` bracket: `organizations` and `retention_policies` are both
    FORCE ROW LEVEL SECURITY, so outside it the SELECT sees nothing and the INSERT is a
    silent no-op.
    """
    return (
        "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, action, "
        f"created_at) SELECT gen_random_uuid(), id, '{category}', {ttl_days}, '{action}', "
        "now() FROM organizations "
        "ON CONFLICT ON CONSTRAINT uq_retention_policies_tenant_id_data_category DO NOTHING"
    )


def _in_list(categories: tuple[str, ...]) -> str:
    return "({})".format(", ".join(repr(c) for c in categories))


def _sql_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    # --- (a) the third sentence -------------------------------------------------------
    # Added nullable, backfilled, then made NOT NULL: the table has rows, and a NOT NULL
    # with a server default would rewrite every one of them under an ACCESS EXCLUSIVE lock
    # AND would put English on a Telugu agent.
    op.execute("ALTER TABLE agents ADD COLUMN caller_memory_notice_line TEXT")
    # `agents.language_primary`, NOT a column on `organizations` — that table has no
    # language at all, and the first draft of this migration joined to one that does not
    # exist. The agent is the right subject anyway: the sentence is spoken BY an agent, and
    # a tenant may run agents in different languages.
    case_arms = " ".join(
        f"WHEN language_primary = {_sql_quote(lang)} THEN {_sql_quote(sentence)}"
        for lang, sentence in _NOTICE.items()
    )
    # THE `NO FORCE` / `FORCE` BRACKET, and this migration failed in production without it.
    # `agents` is FORCE ROW LEVEL SECURITY, which subjects the TABLE OWNER to the policy
    # too, and `tenant_isolation` is fail-closed on an unset `app.tenant_id` — so the
    # backfill matched zero rows, reported success, and the `SET NOT NULL` behind it then
    # failed on the rows the migration believed it had filled. It passed locally because
    # the development database had no agents in it, which is the worst way for a data
    # migration to pass: vacuously. `d3b71c9a5e08` had already written this bracket and its
    # reasoning down for `call_extractions`; not looking is what cost the deploy.
    #
    # It lifts RLS for the OWNER only — `calevate_app` is not the owner and is NOSUPERUSER
    # NOBYPASSRLS, so it keeps every policy throughout — DDL is transactional in Postgres
    # so FORCE is restored before anything commits and any failure rolls the bracket back,
    # and it needs no superuser, which a managed-Postgres owner generally is not.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE agents SET caller_memory_notice_line = CASE "
        f"{case_arms} ELSE {_sql_quote(_FALLBACK)} END"
    )
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents ALTER COLUMN caller_memory_notice_line SET NOT NULL")
    op.execute(
        "ALTER TABLE agents ADD CONSTRAINT ck_agents_caller_memory_notice_nonempty "
        "CHECK (length(btrim(caller_memory_notice_line)) > 0)"
    )

    # --- (c) its own retention clock --------------------------------------------------
    op.execute("ALTER TABLE retention_policies DROP CONSTRAINT ck_retention_policies_category_enum")
    op.execute(
        "ALTER TABLE retention_policies ADD CONSTRAINT ck_retention_policies_category_enum "
        f"CHECK (data_category IN {_in_list(_CATEGORIES_AFTER)})"
    )
    # SAME BRACKET, THREE TABLES. `organizations`, `retention_policies` and `caller_chunks`
    # are all FORCE ROW LEVEL SECURITY, so unbracketed this SELECT sees no organisations,
    # inserts nothing, and reports success — the reach-backwards silently not happening,
    # which is indistinguishable from it working.
    #
    # ⚠ AND THAT IS NOT HYPOTHETICAL: `d4a9c17e6b02` seeds the `copilot_memory` row with
    # this exact unbracketed statement, so on any deployment whose migration role is
    # subject to RLS it inserted ZERO rows and every organisation created before it holds
    # copilot memories nothing expires. `_REPAIR` below fixes that while the bracket is
    # open, because the migration that should have done it has already run and cannot run
    # again. `ON CONFLICT DO NOTHING` makes it a no-op where the seed did work.
    op.execute("ALTER TABLE organizations NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE retention_policies NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE caller_chunks NO FORCE ROW LEVEL SECURITY")
    op.execute(_seed_policy(_CATEGORY, _TTL_DAYS, _ACTION))
    op.execute(_seed_policy(*_REPAIR))
    # WIDEN THE CHECK BEFORE THE UPDATE THAT NEEDS IT. This ran the other way round and
    # passed, because the unbracketed UPDATE matched nothing — a constraint violation
    # cannot happen on zero rows. Fixing the RLS bug is what made the ordering bug visible,
    # which is the argument for exercising a data migration against data rather than
    # against an empty table.
    op.execute("ALTER TABLE caller_chunks DROP CONSTRAINT ck_caller_chunks_retention_category_enum")
    op.execute(
        "ALTER TABLE caller_chunks ADD CONSTRAINT ck_caller_chunks_retention_category_enum "
        f"CHECK (retention_category IN {_in_list(('transcript', 'lead', _CATEGORY))})"
    )
    # The chunks already on file under the transcript clock move to the new one. They are
    # the caller-memory scope's rows and nothing else's — `subject_kind` is the whole
    # predicate — and leaving them behind would split one subject's data across two clocks,
    # with the vector outliving the fact it was built from.
    op.execute(
        f"UPDATE caller_chunks SET retention_category = '{_CATEGORY}' "
        "WHERE subject_kind = 'caller_memory'"
    )
    op.execute("ALTER TABLE caller_chunks FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE retention_policies FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE organizations FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")

    # The chunks go back to the transcript clock BEFORE the CHECK narrows, or the narrowed
    # constraint would refuse rows this migration itself wrote.
    op.execute(
        "UPDATE caller_chunks SET retention_category = 'transcript' "
        f"WHERE retention_category = '{_CATEGORY}'"
    )
    op.execute("ALTER TABLE caller_chunks DROP CONSTRAINT ck_caller_chunks_retention_category_enum")
    op.execute(
        "ALTER TABLE caller_chunks ADD CONSTRAINT ck_caller_chunks_retention_category_enum "
        f"CHECK (retention_category IN {_in_list(('transcript', 'lead'))})"
    )
    op.execute(f"DELETE FROM retention_policies WHERE data_category = '{_CATEGORY}'")
    op.execute("ALTER TABLE retention_policies DROP CONSTRAINT ck_retention_policies_category_enum")
    op.execute(
        "ALTER TABLE retention_policies ADD CONSTRAINT ck_retention_policies_category_enum "
        f"CHECK (data_category IN {_in_list(_CATEGORIES_BEFORE)})"
    )
    op.execute(
        "ALTER TABLE agents DROP CONSTRAINT ck_agents_caller_memory_notice_nonempty"
    )
    op.execute("ALTER TABLE agents DROP COLUMN caller_memory_notice_line")
