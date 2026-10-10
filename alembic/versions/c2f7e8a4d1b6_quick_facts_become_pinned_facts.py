"""quick facts become the business's pinned facts (founder decision 9, 10 Oct 2026)

Revision ID: c2f7e8a4d1b6
Revises: a9c4e2f7d138
Create Date: 2026-10-10 23:45:00.000000

Every question/answer pair in a script's quick facts (`structured_script.faqs`, in the
draft AND the live version of every agent that is not deleted) is copied into
`kb_facts` as a PINNED fact of that agent's business, origin `quick_fact`. Knowledge
belongs to the client (D-689), so a pair two agents of one business both carry is copied
once: the same question and answer, compared trimmed and case-blind, is one fact. Nothing
is cut: an answer is kept whole (the column holds what `FaqEntry` allowed).

Schema first: a fact gains the caller's `question` and a `position` for the pinned order,
and its text may run to 2,000 characters (a quick-fact answer's own limit), so the copy
loses nothing.

`prompt_versions` is immutable history and is not touched. From here the quick-facts
section of every compiled body comes from these rows (`teach/pinned.py`).

The read side (`agents`, `prompt_versions`) and the write side (`kb_facts`) are FORCE-RLS
tables, so the statement runs inside a `NO FORCE` / `FORCE` bracket; without it the owner
sees no rows and copies nothing.

DOWNGRADE deletes the pinned facts this revision made (`origin = 'quick_fact'`), including
any an owner has edited since, then any fact longer than the old 500-character limit, and
drops the two columns. The scripts still hold their quick facts, so nothing a script had
is lost by going back.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c2f7e8a4d1b6"
down_revision: str | None = "a9c4e2f7d138"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_COPY = """
INSERT INTO kb_facts (id, tenant_id, question, text, pinned, origin, position, created_at,
                      updated_at)
SELECT gen_random_uuid(), tenant_id, question, answer, true, 'quick_fact',
       row_number() OVER (PARTITION BY tenant_id ORDER BY first_agent, first_at, ord),
       now(), now()
FROM (
    SELECT DISTINCT ON (a.tenant_id, lower(btrim(f->>'question')), lower(btrim(f->>'answer')))
           a.tenant_id,
           btrim(f->>'question') AS question,
           btrim(f->>'answer') AS answer,
           a.created_at AS first_agent,
           pv.created_at AS first_at,
           e.ord
    FROM agents a
    JOIN prompt_versions pv ON pv.id IN (a.system_prompt_id, a.live_prompt_id)
    CROSS JOIN LATERAL jsonb_array_elements(
        CASE WHEN jsonb_typeof(pv.structured_script->'faqs') = 'array'
             THEN pv.structured_script->'faqs' ELSE '[]'::jsonb END
    ) WITH ORDINALITY AS e(f, ord)
    WHERE a.deleted_at IS NULL
      AND jsonb_typeof(e.f) = 'object'
      AND btrim(COALESCE(f->>'question', '')) <> ''
      AND btrim(COALESCE(f->>'answer', '')) <> ''
    ORDER BY a.tenant_id, lower(btrim(f->>'question')), lower(btrim(f->>'answer')),
             a.created_at, pv.created_at, e.ord
) AS pairs
"""


def _bracket(sql: str) -> None:
    # Spelled out rather than looped, so `tests/migration_rls_bracket_test.py` can read it.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_versions NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_facts NO FORCE ROW LEVEL SECURITY")
    op.execute(sql)
    op.execute("ALTER TABLE kb_facts FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_versions FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    op.add_column("kb_facts", sa.Column("question", sa.Text(), nullable=True))
    op.add_column("kb_facts", sa.Column("position", sa.Integer(), nullable=True))
    op.drop_constraint(op.f("ck_kb_facts_text_length"), "kb_facts", type_="check")
    op.create_check_constraint(
        op.f("ck_kb_facts_text_length"), "kb_facts", "char_length(text) BETWEEN 1 AND 2000"
    )
    op.create_check_constraint(
        op.f("ck_kb_facts_question_length"),
        "kb_facts",
        "question IS NULL OR char_length(question) <= 500",
    )
    _bracket(_COPY)


def downgrade() -> None:
    _bracket("DELETE FROM kb_facts WHERE origin = 'quick_fact' OR char_length(text) > 500")
    op.drop_constraint(op.f("ck_kb_facts_question_length"), "kb_facts", type_="check")
    op.drop_constraint(op.f("ck_kb_facts_text_length"), "kb_facts", type_="check")
    op.create_check_constraint(
        op.f("ck_kb_facts_text_length"), "kb_facts", "char_length(text) BETWEEN 1 AND 500"
    )
    op.drop_column("kb_facts", "position")
    op.drop_column("kb_facts", "question")
