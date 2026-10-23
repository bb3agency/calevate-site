"""The AI notice introduces the agent by name, in Telugu and Hindi (D-865)

Revision ID: f2b7c4e9d815
Revises: a7d3e9c2f416
Create Date: 2026-10-23 21:00:00.000000

Founder decision, 23 Oct 2026: the Telugu and Hindi AI sentence becomes the agent's
introduction, said after the salutation and before the opening line:

    te  "ఇది X ఏఐ అసిస్టెంట్."
        -> "నేను X నుండి <agent>ని, ఏఐ అసిస్టెంట్‌ని మాట్లాడుతున్నాను అండి."
    hi  "मैं X का एआई असिस्टेंट हूँ।"
        -> "मैं X से <agent>, एआई असिस्टेंट, बात कर रही हूँ।"  ("रहा" for a man's voice)

`compliance/disclosure` carries the new wording for agents created from now on. This rewrites
an existing agent's AI sentence only where it is exactly D-861's default (the business name
kept as the line has it), with the agent's own name; a sentence a person wrote is left alone.
The Hindi verb follows the gender the voice catalogue states for the agent's voice, a woman's
form when it states none (`agents/voice_pick.gender_of`: male when the stated gender starts
with "m"). The legacy bundle `agents.disclosure_line` follows where it is still the AI
sentence, a space and the recording sentence.

When a live agent holds a sentence this rewrites, ONE platform live-apply run is queued
(D-720), so every live agent is republished from the rewritten rows. The deploy that carries
this also moves the platform-prompt revision (the greeting's new order), and the worker-start
run (D-739) joins a pending run rather than walking the fleet twice.

DOWNGRADE writes D-861's sentence back on lines in the new default's shape; it queues nothing
(a later publish or the drift repair carries it).
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "f2b7c4e9d815"
down_revision: str | None = "a7d3e9c2f416"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: The reason the queued run records, shown to operators on the live-apply screen.
REASON = "ai_notice_introduces_agent"

#: D-861's defaults, the business name as the one group. Copied rather than imported from
#: `compliance/disclosure`, so this file keeps meaning what it meant on the day it ran;
#: `tests/ai_notice_introduction_test.py` compares the new forms with the templates. No `(?:`
#: groups: SQLAlchemy's `text()` would read the colon as a bind parameter.
TE_OLD = r"^ఇది (.+) ఏఐ అసిస్టెంట్\.$"
HI_OLD = r"^मैं (.+) का एआई असिस्टेंट हूँ।$"

#: The zero-width non-joiner the founder's Telugu keeps between "ట్" and "ని".
ZWNJ = "‌"

#: The new defaults' shapes, the business name as the first group, for the downgrade.
TE_NEW = rf"^నేను (.+) నుండి (.+)ని, ఏఐ అసిస్టెంట్{ZWNJ}ని మాట్లాడుతున్నాను అండి\.$"
HI_NEW = r"^मैं (.+) से (.+), एआई असिस्टेंट, बात कर (रही|रहा) हूँ।$"

#: The new sentence as SQL over `a` (the agent) and `c` (its voice's catalogue row), from the
#: business name `{business}` (an SQL expression).
TE_LINE = (
    "'నేను ' || {business} || ' నుండి ' || a.name || "
    f"'ని, ఏఐ అసిస్టెంట్{ZWNJ}ని మాట్లాడుతున్నాను అండి.'"
)
HI_LINE = (
    "'मैं ' || {business} || ' से ' || a.name || ', एआई असिस्टेंट, बात कर ' || "
    "CASE WHEN lower(btrim(coalesce(c.gender, ''))) LIKE 'm%' THEN 'रहा' ELSE 'रही' END || ' हूँ।'"
)

#: (pattern a stored line must match, the sentence that replaces it) for each direction.
_UPGRADE: tuple[tuple[str, str], ...] = (
    (TE_OLD, TE_LINE),
    (HI_OLD, HI_LINE),
)
_DOWNGRADE: tuple[tuple[str, str], ...] = (
    (TE_NEW, "'ఇది ' || {business} || ' ఏఐ అసిస్టెంట్.'"),
    (HI_NEW, "'मैं ' || {business} || ' का एआई असिस्टेंट हूँ।'"),
)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _queue_platform_run() -> None:
    """One platform run when any live agent holds a sentence this migration rewrites."""
    matches = " OR ".join(f"a.ai_disclosure_line ~ {_quote(pattern)}" for pattern, _ in _UPGRADE)
    queued = execute_data_statement(
        sa.text(
            "WITH runs AS (INSERT INTO live_apply_runs (id, scope, tenant_id, reasons) "
            f"SELECT gen_random_uuid(), 'platform', NULL, '[\"{REASON}\"]'::jsonb "
            "WHERE EXISTS (SELECT 1 FROM agents a WHERE a.deleted_at IS NULL "
            "AND a.status = 'live' AND a.engine_agent_ref IS NOT NULL "
            f"AND ({matches})) RETURNING id) "
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
            "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
            "jsonb_build_object('run_id', id::text), 'pending', 0, now(), now() FROM runs"
        ),
        note="Queued one platform live apply when a live agent's AI sentence changes.",
    )
    log.info("ai notice introduces agent: %s platform live-apply run queued", queued)


def _rewrite(rules: tuple[tuple[str, str], ...]) -> None:
    """Rewrite every AI sentence matching a rule's pattern, and the legacy bundle where it is
    still that sentence, a space and the recording sentence."""
    for pattern, line in rules:
        business = f"substring(a.ai_disclosure_line FROM {_quote(pattern)})"
        rewritten = execute_data_statement(
            sa.text(
                "UPDATE agents t SET ai_disclosure_line = n.line, "
                "disclosure_line = CASE WHEN t.disclosure_line = "
                "t.ai_disclosure_line || ' ' || t.recording_notice_line "
                "THEN n.line || ' ' || t.recording_notice_line ELSE t.disclosure_line END, "
                "updated_at = now() "
                f"FROM (SELECT a.id, {line.format(business=business)} AS line FROM agents a "
                "LEFT JOIN platform_voice_catalog c ON c.voice_id = a.engine_voice_id "
                f"WHERE a.ai_disclosure_line ~ {_quote(pattern)}) AS n WHERE t.id = n.id"
            ),
            note="Rewrote AI sentences in a previous default's shape.",
        )
        log.info("ai notice introduces agent: %s ai_disclosure_line rewritten", rewritten)


def upgrade() -> None:
    # The FORCE bracket (`f4a2c7e19d63`): `agents` is FORCE-RLS'd, so without it these
    # statements match no rows.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    _queue_platform_run()
    _rewrite(_UPGRADE)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    _rewrite(_DOWNGRADE)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
