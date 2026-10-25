"""The real-estate starter's example lines ask the size openly and offer the next days (D-888)

Revision ID: c8e4a1f7b2d5
Revises: c8e2f4a6b913
Create Date: 2026-10-25 21:00:00.000000

On the Sri Estates calls of 25 Oct 2026 the agent asked "two or three BHK?" of a caller who
wanted five, and on a Sunday evening offered a site visit "this weekend, Saturday or Sunday".
Both are the real-estate plan's own example lines (`agents/trade_playbooks.TRADE_WORDS`),
which a starter stores on each step of the agent's script, so the plan's new lines reach only
agents made from now on.

This queues one `refresh_example_lines` outbox message per account with an agent (not
deleted) whose current script has a step holding one of the old lines word for word. The
worker (`apps/workers/example_line_refresh.py`) puts the new line on that step, writes a new
script version and republishes a live agent; a line anybody edited is not touched. Nothing is
rewritten in place: every prompt version stays as it was heard.

DOWNGRADE queues the inverse for agents holding the new lines, which includes agents made from
the new plan after this ran. The versions the worker wrote stay on file as history.
"""

import json
from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "c8e4a1f7b2d5"
down_revision: str | None = "c8e2f4a6b913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: FROZEN COPIES, not imports: a migration keeps meaning what it meant on the day it ran.
#: `tests/sri_estates_call_2026_10_25_test.py` holds them equal to the shipped plan.
#: `apps/workers/example_line_refresh.JOB_NAME`.
JOB = "refresh_example_lines"

#: (the old line, the new one), Telugu, Hindi and English.
REPLACEMENTS: tuple[tuple[str, str], ...] = (
    ("టూ బీహెచ్కే కావాలా, త్రీ బీహెచ్కే కావాలా అండి?", "ఎన్ని బీహెచ్కే కావాలి అండి?"),
    ("टू बीएचके चाहिए या थ्री बीएचके?", "कितने बीएचके चाहिए जी?"),
    ("Are you looking at a two or a three BHK?", "How many bedrooms are you looking for?"),
    (
        "ఒకసారి సైట్ విజిట్ కి రండి అండి, ఈ వీకెండ్ కుదురుతుందా?",
        "ఒకసారి సైట్ విజిట్ కి రండి అండి, రేపు కుదురుతుందా, ఎల్లుండి కుదురుతుందా?",
    ),
    (
        "एक बार साइट विज़िट कर लीजिए जी, इस वीकेंड ठीक रहेगा?",
        "एक बार साइट विज़िट कर लीजिए जी, कल ठीक रहेगा या परसों?",
    ),
    (
        "Would you like to see the site, maybe this weekend?",
        "Would you like to see the site, tomorrow or the day after?",
    ),
    (
        "సైట్ విజిట్ కి సాటర్డే కుదురుతుందా, సండే కుదురుతుందా అండి?",
        "సైట్ విజిట్ కి రేపు కుదురుతుందా, ఎల్లుండి కుదురుతుందా అండి?",
    ),
    ("साइट विज़िट के लिए सैटरडे ठीक रहेगा या संडे?", "साइट विज़िट के लिए कल ठीक रहेगा या परसों?"),
    (
        "For a site visit, would Saturday or Sunday suit you?",
        "For a site visit, would tomorrow or the day after suit you?",
    ),
)


def _queue(pairs: Sequence[tuple[str, str]]) -> int | None:
    """One message per account with an agent whose current script has a step holding an old
    line of `pairs` exactly (after trimming, as the worker compares)."""
    olds = [old for old, _ in pairs]
    return execute_data_statement(
        sa.text(
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
            "created_at, updated_at) SELECT gen_random_uuid(), :job, jsonb_build_object("
            "'tenant_id', t.tenant_id::text, 'replacements', CAST(:pairs AS jsonb)), "
            "'pending', 0, now(), now() FROM (SELECT DISTINCT a.tenant_id FROM agents a "
            "JOIN prompt_versions pv ON pv.id = a.system_prompt_id "
            "WHERE a.deleted_at IS NULL "
            "AND jsonb_typeof(pv.structured_script -> 'stages') = 'array' "
            "AND EXISTS (SELECT 1 FROM jsonb_array_elements(pv.structured_script -> 'stages') st "
            "WHERE btrim(st ->> 'sounds_like') IN (SELECT jsonb_array_elements_text("
            "CAST(:olds AS jsonb))))) t"
        ).bindparams(
            job=JOB,
            pairs=json.dumps([list(pair) for pair in pairs], ensure_ascii=False),
            olds=json.dumps(olds, ensure_ascii=False),
        ),
        note="Queued the new real-estate example lines for accounts whose agents hold the old.",
    )


def _queue_all(*, forward: bool) -> None:
    # The FORCE bracket (`f4a2c7e19d63`): both tables are FORCE-RLS'd, so without it the
    # owner's read matches no rows and nothing is queued.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE prompt_versions NO FORCE ROW LEVEL SECURITY")
    pairs = REPLACEMENTS if forward else tuple((new, old) for old, new in REPLACEMENTS)
    queued = _queue(pairs)
    log.info("example lines (%s): %s account(s) queued", forward, queued)
    op.execute("ALTER TABLE prompt_versions FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _queue_all(forward=True)


def downgrade() -> None:
    _queue_all(forward=False)
