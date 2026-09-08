"""What a migration does when `alembic upgrade --sql` renders it with no database.

`alembic upgrade head --sql` — the emit-SQL-for-a-human-to-review path `docs/DEPLOYMENT.md`
documents — runs every `upgrade()` with **no connection at all**. `op.get_bind()` returns
`None` there, so a migration that queries the database to decide what to do dies with
`AttributeError: 'NoneType' object has no attribute 'first'` at whichever revision reads
first, and every revision after it is unreachable. That is what this module ends.

The three shapes, and why each gets the answer it gets
-----------------------------------------------------
**A PROBE** — "is FORCE RLS still on?", "would this unique index collide?", "is `vector`
installed?" — reads the live catalog to fail EARLY with a sentence an operator can act on.
Offline there is nothing to read, and the emitted script is not the thing that would be
harmed: it is run against a real database, where the very next statement (a unique index, a
narrower CHECK, a restored NOT NULL) re-enforces the same invariant and Postgres refuses.
So the probe is SKIPPED and `probe_skipped_offline()` writes into the script the sentence
that says which check did not run — the reviewer of a `--sql` file learns it at the
revision it belongs to, rather than reading a script that looks fully checked.

**A DATA STATEMENT** — a backfill whose SQL is fixed. This one MUST be emitted: a silently
missing backfill in a reviewed SQL script is the worst outcome available, worse than the
render failing. Only the `.rowcount` is impossible offline, and a row count is never
load-bearing here — it is a log line. `execute_data_statement()` therefore emits the
statement and returns `None` for the count.

**A REFUSAL** — none, today. No migration in this tree needs a value it cannot get offline
in order to decide WHAT SQL TO EMIT; every reader is a probe or a count. If one ever does,
it must `raise` naming its own revision, so a human running `--sql` is stopped at that
revision instead of handed an incomplete script.

`print()` IS NOT AVAILABLE ON THIS PATH, and that is why `emit_note` exists
--------------------------------------------------------------------------
Offline mode writes the rendered SQL to **stdout**, which is what `> upgrade.sql`
captures. The two migrations that `print()` an operator sentence (`a8d3f61c04e7`,
`c9f3a71e58d2`) would inject prose into the middle of the script — a file somebody pipes
into `psql`. `static_output` is alembic's own offline-only output buffer and is the
counterpart of `print` here; `emit_note` prefixes every line with `--` so what lands is a
SQL comment either way.

WHAT THIS DOES NOT DO: it does not change one byte of online behaviour. Every function
here is a pass-through when `context.is_offline_mode()` is false.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op


def is_offline() -> bool:
    """True when alembic is rendering SQL (`--sql`) rather than holding a connection."""
    return context.is_offline_mode()


def emit_note(note: str) -> None:
    """Write `note` into the rendered script as SQL comment lines. Offline only, no-op online.

    `static_output` rather than `print` because stdout IS the script on this path (see the
    module docstring), and rather than `op.execute("-- ...")` because that appends a `;` and
    goes through the DDL compiler for something that is not DDL.
    """
    if not context.is_offline_mode():
        return
    rendered = "\n".join(f"-- {line}" if line else "--" for line in note.splitlines())
    op.get_context().impl.static_output(rendered)


def probe_skipped_offline(note: str) -> bool:
    """True when there is no connection to probe with; records `note` in the rendered script.

    Call it as the first line of a guard — `if probe_skipped_offline("..."): return` — so the
    guard's own SQL is never reached offline. `note` says which check did not run and what
    re-enforces it on the target database, because a reviewer of the emitted file has no
    other way to learn that a check they can see in the migration source was not performed.
    """
    if not context.is_offline_mode():
        return False
    emit_note(note)
    return True


def execute_data_statement(statement: sa.TextClause, *, note: str) -> int | None:
    """Run a fixed data statement, returning its row count — or emit it, returning `None`.

    The statement is emitted offline BECAUSE it is fixed: nothing about it depends on a
    value only a live database could supply, so leaving it out of the rendered script would
    ship a reviewed migration whose data half silently did not happen. The count is what
    cannot survive: offline there are no rows to count, and every caller uses it for an
    operator log line rather than for a decision, so `None` is the honest answer and each
    caller prints `note` instead of a number it does not have.
    """
    if not context.is_offline_mode():
        return op.get_bind().execute(statement).rowcount
    emit_note(note)
    op.execute(statement)
    return None
