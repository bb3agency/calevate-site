"""the language column can refuse a value

Revision ID: c7a41e8b52d9
Revises: b5d3a91e7c64
Create Date: 2026-09-14 11:40:00.000000

ONE CHECK on `agents.language_primary`, and the reason it is worth a migration is what the
column was doing without it.

--------------------------------------------------------------------------------
WHAT IT HELD BEFORE
--------------------------------------------------------------------------------

`language_primary TEXT NOT NULL DEFAULT 'te-IN'` — no foreign key, no constraint, no
domain. The API's create and update models typed the field as a three-value `Literal`, so
the ROUTES were closed; everything else was not. `admin/service.create_organization`,
`admin/intake`, the seed scripts and any future backfill write this column through SQL,
and a bare `Text` accepts `xx-IN`, `telugu`, `''` and `en_IN` from every one of them.

**What that would have cost is not a wrong row on a screen.** Three surfaces speak
sentences to callers off this value and all three FALL BACK rather than fail:
`compliance/disclosure._rendered` (the AI-disclosure and recording sentences — hard rule
5), `compliance/disclosure.caller_memory_notice_for`, and `agents/handoff.py`'s spoken
handover line. An agent stored as `xx-IN` therefore opens in English, on a Telugu-first
product, to a caller who chose Telugu — with nothing logged, nothing red, and no screen
that shows the difference. The constraint turns that into a write that fails where it is
made.

--------------------------------------------------------------------------------
WHY THE OFFERED THREE AND NOT THE CONVERSATIONAL ELEVEN
--------------------------------------------------------------------------------

`calevate_shared.languages` declares, from the vendor's own SDK, that Sarvam's STT can
transcribe 23 languages and its TTS can speak 11 — so an agent could hold a call in any of
those 11. The product SELLS three (`OFFERED_LANGUAGE_IDS`), and this constraint admits
exactly those three, because the column is not a capability register: it decides which
disclosure sentence is spoken, which handover line is played, and which voices the picker
offers. A language with no written sentences is an agent that opens in the wrong one.

The twelve comprehension-only languages are excluded twice over, and that is the failure
this whole seam exists to stop: Sarvam can transcribe Assamese and cannot speak it, so an
agent configured in `as-IN` would understand every caller perfectly and answer none of
them — dead air on a live call, visible in no test and no screenshot.

Widening is a one-line change to `OFFERED_LANGUAGE_IDS` plus this constraint plus the
sentences, and `tests/product_languages_test.py` fails until all of them agree.

--------------------------------------------------------------------------------
VALIDATION: WHAT IS ACTUALLY IN THE COLUMN
--------------------------------------------------------------------------------

Checked before writing this rather than assumed (hard rule 12):
`SELECT DISTINCT language_primary FROM agents` on the development database returns exactly
`te-IN`. Every writer in the tree is either the typed route or the server default, and the
two tests that insert their own agents use `te-IN` and `en-IN`. The constraint is therefore
added `NOT VALID` and VALIDATEd in the same migration — not because a scan is expected to
fail, but because that is the lock-cheap order (a brief ACCESS EXCLUSIVE on the catalog
row, then SHARE UPDATE EXCLUSIVE for the scan, which blocks neither readers nor writers).
`lock_timeout` bounds the wait so a queued ACCESS EXCLUSIVE cannot park in front of every
other session (hard rule 8).

**A deployment whose column holds something else fails HERE, loudly, with the row named by
PostgreSQL** — which is the right place for it to fail. The rejected alternative was to
leave the constraint NOT VALID so old rows are grandfathered: that admits a permanent
population of agents whose spoken sentences are wrong, and hides them behind a constraint
that claims to be enforcing something.

RLS. No new table and no new column, so no new policy — `agents` already carries its
FORCEd `tenant_isolation` policy and a constraint is not a security object. The VALIDATE
runs inside a `NO FORCE` / `FORCE` bracket for a4e7b2c95d18's reason: this role owns the
table and is therefore subject to the policy too, so with no `app.tenant_id` GUC set the
validation scan would see ZERO ROWS and mark the constraint proven against nothing.

--------------------------------------------------------------------------------
DOWNGRADE
--------------------------------------------------------------------------------

Drops the constraint. Nothing else, and nothing is lost: the column, its type, its NOT
NULL and its server default are untouched, every row that satisfied the CHECK still
satisfies the schema without it, and the code that ran before this revision runs
unchanged against the post-downgrade schema — which is what hard rule 8 means by
reversible. No two-step deprecation applies: nothing is being removed and no writer stops
writing a column.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c7a41e8b52d9"
down_revision: str | None = "b5d3a91e7c64"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "agents"
CK_LANGUAGE = "ck_agents_language_primary_offered"

# The three the product sells, SPELLED OUT rather than imported from
# `agents/languages.PRODUCT_LANGUAGES`. A migration is a snapshot of the schema on the day
# it ran — importing today's constant would rewrite this revision's meaning the next time
# somebody adds a language, and the migration that adds the fourth is the one that should
# say so. (a4e7b2c95d18 spells out its call-cap bounds for the same reason.)
_LANGUAGE_SQL = "language_primary IN ('te-IN', 'hi-IN', 'en-IN')"


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} ADD CONSTRAINT {CK_LANGUAGE} CHECK ({_LANGUAGE_SQL}) NOT VALID")
    # Without the bracket the scan is RLS-filtered to zero rows and the constraint is
    # marked valid having proven nothing. See the docstring.
    op.execute(f"ALTER TABLE {TABLE} NO FORCE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE {TABLE} VALIDATE CONSTRAINT {CK_LANGUAGE}")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE {TABLE} DROP CONSTRAINT IF EXISTS {CK_LANGUAGE}")
