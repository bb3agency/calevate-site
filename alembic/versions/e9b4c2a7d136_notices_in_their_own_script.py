"""The Telugu and Hindi opening notices are written in their own script (D-745)

Revision ID: e9b4c2a7d136
Revises: d2a7e5c19f04
Create Date: 2026-10-11 00:00:00.000000

Founder decision, 11 Oct 2026, amending D-708: the notice MEANING stays ours and locked
(hard rule 5, D-163), but a Telugu or Hindi sentence written in Latin letters is read by the
voice as if it were English. `compliance/disclosure` now writes them in Telugu script and
Devanagari, keeping the English words people use in English letters, and the Hindi memory
sentence says "we" so it assumes no gender. That reaches agents created from now on; this
rewrites the stored lines of every existing agent, ONLY where a line is exactly what the
previous template produced for the agent's business (`organizations.name`):

    te  "Idi {b} AI assistant."            -> "ఇది {b} AI assistant."
    te  "Ee call record avutundi."         -> "ఈ call record అవుతుంది."
    te  "Meeru adigina daani gurinchi oka chinna note nenu gurthu pettukuntaanu."
        -> "మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను."
    hi  "Main {b} ka AI assistant hoon."   -> "मैं {b} का AI assistant हूँ।"
    hi  "Yeh call record ho rahi hai."     -> "यह call record हो रही है।"
    hi  "Aapne kya poocha, uska ek chhota note main yaad rakhta hoon."
        -> "आपने जो पूछा, उसका एक छोटा note हम याद रखते हैं।"

and the legacy bundle `agents.disclosure_line` (AI sentence, a space, recording sentence) the
same way. A line somebody edited, or whose business has been renamed, is left as it is.

When a live agent's line changes, ONE platform live-apply run is queued (D-720), so every
live agent is republished once from the rewritten rows and the drift sweep then finds the
engine holding what is composed. A worker start that queues the platform-prompt run
(D-739) while this one is pending joins it rather than walking the fleet twice.

DOWNGRADE writes the Latin-letter wording back on lines that exactly match the new
templates; it queues nothing (a later publish or the drift repair carries it).
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "e9b4c2a7d136"
down_revision: str | None = "d2a7e5c19f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: (old AI, new AI, old recording, new recording, old memory, new memory); `{b}` = business.
_LINES = (
    (
        "Idi {b} AI assistant.",
        "ఇది {b} AI assistant.",
        "Ee call record avutundi.",
        "ఈ call record అవుతుంది.",
        "Meeru adigina daani gurinchi oka chinna note nenu gurthu pettukuntaanu.",
        "మీరు అడిగిన దాని గురించి ఒక చిన్న note గుర్తు పెట్టుకుంటాను.",
    ),
    (
        "Main {b} ka AI assistant hoon.",
        "मैं {b} का AI assistant हूँ।",
        "Yeh call record ho rahi hai.",
        "यह call record हो रही है।",
        "Aapne kya poocha, uska ek chhota note main yaad rakhta hoon.",
        "आपने जो पूछा, उसका एक छोटा note हम याद रखते हैं।",
    ),
)

#: The reason the queued run records, shown to operators on the live-apply screen.
REASON = "notices_in_own_script"


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _values(rows: list[tuple[str, str]]) -> str:
    return "VALUES " + ", ".join(f"({_quote(a)}, {_quote(b)})" for a, b in rows)


def _pairs(*, upgrade: bool) -> dict[str, list[tuple[str, str]]]:
    """Per column, (from, to) templates."""
    out: dict[str, list[tuple[str, str]]] = {
        "ai_disclosure_line": [],
        "recording_notice_line": [],
        "caller_memory_notice_line": [],
        "disclosure_line": [],
    }
    for old_ai, new_ai, old_rec, new_rec, old_mem, new_mem in _LINES:
        for column, old, new in (
            ("ai_disclosure_line", old_ai, new_ai),
            ("recording_notice_line", old_rec, new_rec),
            ("caller_memory_notice_line", old_mem, new_mem),
            ("disclosure_line", f"{old_ai} {old_rec}", f"{new_ai} {new_rec}"),
        ):
            out[column].append((old, new) if upgrade else (new, old))
    return out


def _matches(column: str) -> str:
    return f"a.{column} = replace(m.src, '{{b}}', o.name)"


def _rewrite(*, upgrade: bool) -> None:
    pairs = _pairs(upgrade=upgrade)
    # The FORCE bracket (`f4a2c7e19d63`): `agents` is FORCE-RLS'd, so without it these
    # statements match no rows.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    if upgrade:
        # Before the rewrite, from the same match: one platform run when any live agent's
        # spoken notice is about to change.
        live = " OR ".join(
            f"EXISTS (SELECT 1 FROM agents a JOIN organizations o ON o.id = a.tenant_id "
            f"CROSS JOIN ({_values(pairs[column])}) AS m(src, dst) "
            "WHERE a.deleted_at IS NULL AND a.status = 'live' "
            f"AND a.engine_agent_ref IS NOT NULL AND {_matches(column)})"
            for column in ("ai_disclosure_line", "recording_notice_line", "caller_memory_notice_line")
        )
        queued = execute_data_statement(
            sa.text(
                "WITH runs AS (INSERT INTO live_apply_runs (id, scope, tenant_id, reasons) "
                f"SELECT gen_random_uuid(), 'platform', NULL, '[\"{REASON}\"]'::jsonb "
                f"WHERE {live} RETURNING id) "
                "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
                "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
                "jsonb_build_object('run_id', id::text), 'pending', 0, now(), now() FROM runs"
            ),
            note="Queued one platform live apply when a live agent's notice changes.",
        )
        log.info("notices in own script: %s platform live-apply run queued", queued)
    for column, rows in pairs.items():
        rewritten = execute_data_statement(
            sa.text(
                f"UPDATE agents a SET {column} = replace(m.dst, '{{b}}', o.name), "
                f"updated_at = now() FROM organizations o, ({_values(rows)}) AS m(src, dst) "
                f"WHERE o.id = a.tenant_id AND {_matches(column)}"
            ),
            note=f"Rewrote {column} values that exactly match a previous template output.",
        )
        log.info("notices in own script: %s %s rewritten", rewritten, column)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rewrite(upgrade=True)


def downgrade() -> None:
    _rewrite(upgrade=False)
