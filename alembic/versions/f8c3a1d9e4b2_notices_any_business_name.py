"""Bring the remaining old-template opening notices to the current wording, whatever name they carry

Revision ID: f8c3a1d9e4b2
Revises: d6f2b8a41c73
Create Date: 2026-10-11 00:00:00.000000

`a2d8e6c4f1b7` (no greeting) and `e9b4c2a7d136` (own script, D-745) rewrote a notice only when
it equalled the template output for the agent's CURRENT `organizations.name`. A line whose
business name differs from the account name (the account was renamed, or the name was
typed differently) kept "Namaskaram, idi <name> AI assistant." in production. This matches the
template's SHAPE instead, keeps the name exactly as the line has it, and writes the current
wording:

    te  "Namaskaram, idi X AI assistant." / "Idi X AI assistant."        -> "ఇది X AI assistant."
    hi  "Namaste, main X ka AI assistant hoon." / "Main X ka AI assistant hoon."
                                                                      -> "मैं X का AI assistant हूँ।"
    en  "Hello, this is the AI assistant for X."                      -> "This is the AI assistant for X."

and the legacy bundle `agents.disclosure_line` the same way. Anything that is not one of these
exact shapes is left alone. One platform live-apply run is queued when a live agent changes.

DOWNGRADE writes the Latin-letter, no-greeting shape back (the greeting a line carried before
cannot be recovered from the rewritten value).
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement

revision: str = "f8c3a1d9e4b2"
down_revision: str | None = "d6f2b8a41c73"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

REASON = "notices_any_business_name"

#: (column, POSIX pattern, replacement naming the group that holds the business name).
#: No `(?:` groups: SQLAlchemy's `text()` would read `:Namaskaram` as a bind parameter.
_REWRITES: tuple[tuple[str, str, str], ...] = (
    (
        "ai_disclosure_line",
        r"^(Namaskaram, i|I)di (.+) AI assistant\.$",
        r"ఇది \2 AI assistant.",
    ),
    (
        "ai_disclosure_line",
        r"^(Namaste, m|M)ain (.+) ka AI assistant hoon\.$",
        r"मैं \2 का AI assistant हूँ।",
    ),
    (
        "ai_disclosure_line",
        r"^Hello, this is the AI assistant for (.+)\.$",
        r"This is the AI assistant for \1.",
    ),
    (
        "disclosure_line",
        r"^(Namaskaram, i|I)di (.+) AI assistant\. Ee call record avutundi\.$",
        r"ఇది \2 AI assistant. ఈ call record అవుతుంది.",
    ),
    (
        "disclosure_line",
        r"^(Namaste, m|M)ain (.+) ka AI assistant hoon\. Yeh call record ho rahi hai\.$",
        r"मैं \2 का AI assistant हूँ। यह call record हो रही है।",
    ),
    (
        "disclosure_line",
        r"^Hello, this is the AI assistant for (.+)\. This call is being recorded\.$",
        r"This is the AI assistant for \1. This call is being recorded.",
    ),
)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def upgrade() -> None:
    # The FORCE bracket (`f4a2c7e19d63`): `agents` is FORCE-RLS'd, so without it these
    # statements match no rows.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    live = " OR ".join(
        f"(a.{column} ~ {_quote(pattern)})"
        for column, pattern, _ in _REWRITES
        if column == "ai_disclosure_line"
    )
    queued = execute_data_statement(
        sa.text(
            "WITH runs AS (INSERT INTO live_apply_runs (id, scope, tenant_id, reasons) "
            f"SELECT gen_random_uuid(), 'platform', NULL, '[\"{REASON}\"]'::jsonb "
            "WHERE EXISTS (SELECT 1 FROM agents a WHERE a.deleted_at IS NULL "
            f"AND a.status = 'live' AND a.engine_agent_ref IS NOT NULL AND ({live})) "
            "RETURNING id) "
            "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
            "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
            "jsonb_build_object('run_id', id::text), 'pending', 0, now(), now() FROM runs"
        ),
        note="Queued one platform live apply when a live agent's notice changes.",
    )
    log.info("notices any business name: %s platform live-apply run queued", queued)
    for column, pattern, replacement in _REWRITES:
        rewritten = execute_data_statement(
            sa.text(
                f"UPDATE agents SET {column} = regexp_replace({column}, {_quote(pattern)}, "
                f"{_quote(replacement)}), updated_at = now() "
                f"WHERE {column} ~ {_quote(pattern)}"
            ),
            note=f"Rewrote {column} values in an old template shape.",
        )
        log.info("notices any business name: %s %s rewritten", rewritten, column)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


#: The downgrade: current wording back to the Latin-letter, no-greeting shape, any name.
_REVERSE: tuple[tuple[str, str, str], ...] = (
    ("ai_disclosure_line", r"^ఇది (.+) AI assistant\.$", r"Idi \1 AI assistant."),
    ("ai_disclosure_line", r"^मैं (.+) का AI assistant हूँ।$", r"Main \1 ka AI assistant hoon."),
    (
        "disclosure_line",
        r"^ఇది (.+) AI assistant\. ఈ call record అవుతుంది\.$",
        r"Idi \1 AI assistant. Ee call record avutundi.",
    ),
    (
        "disclosure_line",
        r"^मैं (.+) का AI assistant हूँ। यह call record हो रही है।$",
        r"Main \1 ka AI assistant hoon. Yeh call record ho rahi hai.",
    ),
)


def downgrade() -> None:
    # The greeting a line carried before cannot be recovered, so this writes the shape
    # `a2d8e6c4f1b7` left (Latin letters, no greeting). English is already that shape.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    for column, pattern, replacement in _REVERSE:
        execute_data_statement(
            sa.text(
                f"UPDATE agents SET {column} = regexp_replace({column}, {_quote(pattern)}, "
                f"{_quote(replacement)}), updated_at = now() "
                f"WHERE {column} ~ {_quote(pattern)}"
            ),
            note=f"Wrote {column} values back in Latin letters.",
        )
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
