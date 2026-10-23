"""The caller-memory sentence says why, then what (D-861)

Revision ID: c3e8a1f5d702
Revises: d6f1a8c3e925
Create Date: 2026-10-23 18:00:00.000000

Founder decision, 23 Oct 2026: the memory sentence is reworded and said after the greeting.
`compliance/disclosure.CALLER_MEMORY_NOTICE_TEMPLATES` carries the new wording for agents
created from now on; this rewrites `agents.caller_memory_notice_line` on every existing agent
ONLY where it is exactly the previous template for some language, so a sentence an owner or
operator edited is left as it is:

    te  "మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను."
        -> "మీరు మళ్ళీ call చేసినప్పుడు గుర్తుండేలా, ఈ call గురించి ఒక చిన్న note ఉంచుకుంటాను."
    en  "I keep a short note of what you ask about, so I remember it if you call again."
        -> "So I remember it when you call again, I keep a short note about this call."

and the same for hi, ta, kn, ml and mr. Matched on the text, not on the agent's language: a
line is the old default whatever language the agent speaks now.

When a live agent that remembers callers holds an old line, ONE platform live-apply run is
queued (D-720), so every live agent is republished once from the rewritten rows and the
drift sweep then finds the engine holding what is composed. The deploy that carries this
also moves the platform-prompt revision (the greeting now comes before the notices), and
the worker-start run (D-739) joins a pending run rather than walking the fleet twice.

DOWNGRADE writes the previous wording back on lines that exactly match the new one; it queues
nothing (a later publish or the drift repair carries it).
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "c3e8a1f5d702"
down_revision: str | None = "d6f1a8c3e925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: (previous template, new template) per language. Copied rather than imported from
#: `compliance/disclosure`, so this file keeps meaning what it meant on the day it ran;
#: `tests/caller_memory_notice_test.py` reads it as source and compares.
_LINES: tuple[tuple[str, str, str], ...] = (
    (
        "te-IN",
        "మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను.",
        "మీరు మళ్ళీ call చేసినప్పుడు గుర్తుండేలా, ఈ call గురించి ఒక చిన్న note ఉంచుకుంటాను.",
    ),
    (
        "hi-IN",
        "आपने जो पूछा, उसका एक छोटा note हम याद रखते हैं।",
        "आप दोबारा call करें तो याद रहे, इसलिए हम इस call का एक छोटा note रखते हैं।",
    ),
    (
        "en-IN",
        "I keep a short note of what you ask about, so I remember it if you call again.",
        "So I remember it when you call again, I keep a short note about this call.",
    ),
    (
        "ta-IN",
        "நீங்கள் கேட்டதைப் பற்றி ஒரு சின்ன note வைத்துக்கொள்கிறேன்.",
        "நீங்கள் மீண்டும் call செய்யும்போது நினைவில் இருக்க, இந்த call பற்றி ஒரு சின்ன note "
        "வைத்துக்கொள்கிறேன்.",
    ),
    (
        "kn-IN",
        "ನೀವು ಕೇಳಿದ್ದರ ಬಗ್ಗೆ ಒಂದು ಚಿಕ್ಕ note ನೆನಪಿಟ್ಟುಕೊಳ್ಳುತ್ತೇನೆ.",
        "ನೀವು ಮತ್ತೆ call ಮಾಡಿದಾಗ ನೆನಪಿರಲಿ ಎಂದು, ಈ call ಬಗ್ಗೆ ಒಂದು ಚಿಕ್ಕ note ಇಟ್ಟುಕೊಳ್ಳುತ್ತೇನೆ.",
    ),
    (
        "ml-IN",
        "നിങ്ങൾ ചോദിച്ചതിനെക്കുറിച്ച് ഒരു ചെറിയ note ഞാൻ ഓർത്തുവെക്കും.",
        "നിങ്ങൾ വീണ്ടും call ചെയ്യുമ്പോൾ ഓർമ്മയുണ്ടാകാൻ, ഈ call പറ്റി ഒരു ചെറിയ note ഞാൻ "
        "സൂക്ഷിക്കും.",
    ),
    (
        "mr-IN",
        "तुम्ही जे विचारले, त्याची एक छोटी note आम्ही लक्षात ठेवतो.",
        "तुम्ही पुन्हा call केल्यावर लक्षात राहावे म्हणून, या call ची एक छोटी note आम्ही ठेवतो.",
    ),
)

#: The reason the queued run records, shown to operators on the live-apply screen.
REASON = "memory_sentence_reworded"


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _values(*, upgrade: bool) -> str:
    pairs = [(old, new) if upgrade else (new, old) for _tag, old, new in _LINES]
    return "VALUES " + ", ".join(f"({_quote(src)}, {_quote(dst)})" for src, dst in pairs)


def _rewrite(*, upgrade: bool) -> None:
    values = _values(upgrade=upgrade)
    # The FORCE bracket (`f4a2c7e19d63`): `agents` is FORCE-RLS'd, so without it these
    # statements match no rows.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    if upgrade:
        # Before the rewrite, from the same match: one platform run when a live agent that
        # speaks the sentence is about to change. An agent with memory off holds the line
        # on file but never says it, so it alone is no reason to republish the fleet.
        queued = execute_data_statement(
            sa.text(
                "WITH runs AS (INSERT INTO live_apply_runs (id, scope, tenant_id, reasons) "
                f"SELECT gen_random_uuid(), 'platform', NULL, '[\"{REASON}\"]'::jsonb "
                "WHERE EXISTS (SELECT 1 FROM agents a "
                f"CROSS JOIN ({values}) AS m(src, dst) "
                "WHERE a.deleted_at IS NULL AND a.status = 'live' "
                "AND a.engine_agent_ref IS NOT NULL AND a.caller_memory_enabled "
                "AND a.caller_memory_notice_line = m.src) RETURNING id) "
                "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
                "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
                "jsonb_build_object('run_id', id::text), 'pending', 0, now(), now() FROM runs"
            ),
            note="Queued one platform live apply when a live agent's memory sentence changes.",
        )
        log.info("memory sentence reworded: %s platform live-apply run queued", queued)
    rewritten = execute_data_statement(
        sa.text(
            "UPDATE agents a SET caller_memory_notice_line = m.dst, updated_at = now() "
            f"FROM ({values}) AS m(src, dst) WHERE a.caller_memory_notice_line = m.src"
        ),
        note="Rewrote caller_memory_notice_line values that exactly match a previous template.",
    )
    log.info("memory sentence reworded: %s caller_memory_notice_line rewritten", rewritten)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rewrite(upgrade=True)


def downgrade() -> None:
    _rewrite(upgrade=False)
