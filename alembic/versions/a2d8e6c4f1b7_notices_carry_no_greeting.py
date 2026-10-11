"""The AI notice says who is calling, never hello: the opening line is the greeting (D-720)

Revision ID: a2d8e6c4f1b7
Revises: f1a7c3e9b2d4
Create Date: 2026-10-10 21:30:00.000000

Founder decision, 10 Oct 2026: the notice wording stays ours and locked (hard rule 5,
D-163/D-708), but a notice never greets, because the agent's opening line is the greeting.
`compliance/disclosure.AI_DISCLOSURE_TEMPLATES` lost its greeting words in D-708, and only
for agents created afterwards; every older agent still opens "Namaskaram, idi <business> AI
assistant." and then its opening line says hello again, so callers hear two greetings.

This rewrites a stored line ONLY when it is exactly what an old template produced for the
agent's business (`organizations.name`), into what the current template produces:

    te  "Namaskaram, idi {b} AI assistant."        -> "Idi {b} AI assistant."
    hi  "Namaste, main {b} ka AI assistant hoon."  -> "Main {b} ka AI assistant hoon."
    en  "Hello, this is the AI assistant for {b}." -> "This is the AI assistant for {b}."

and the legacy bundle `agents.disclosure_line` (the AI sentence, a space, the recording
sentence) the same way. The recording sentences never carried a greeting and are unchanged.
A line somebody edited, or one whose business has since been renamed, does not match and is
left exactly as it is; the online run logs how many lines still open with a greeting word.

Every client with a live agent whose line changed gets a live-apply run
(`agents/live_apply.py`), so those agents speak the new notice from their next call without
being switched off and on.

DOWNGRADE restores the old wording on agents created before the template changed
(2026-10-10 18:55 IST); a line on an agent created after it was never an old output.
"""

from collections.abc import Sequence
from logging import getLogger

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import execute_data_statement, probe_skipped_offline

revision: str = "a2d8e6c4f1b7"
down_revision: str | None = "f1a7c3e9b2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = getLogger("alembic.runtime.migration")

#: When the templates lost their greeting (commit 9ca389f4). An agent created after this
#: was given the new wording, so a downgrade never rewrites it.
TEMPLATE_CHANGED_AT = "2026-10-10T18:55:13+05:30"

#: (old AI sentence, new AI sentence, recording sentence), `{b}` being the business name.
_LINES = (
    ("Namaskaram, idi {b} AI assistant.", "Idi {b} AI assistant.", "Ee call record avutundi."),
    (
        "Namaste, main {b} ka AI assistant hoon.",
        "Main {b} ka AI assistant hoon.",
        "Yeh call record ho rahi hai.",
    ),
    (
        "Hello, this is the AI assistant for {b}.",
        "This is the AI assistant for {b}.",
        "This call is being recorded.",
    ),
)


def _quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _mapping(*, upgrade: bool) -> str:
    """A VALUES list of (from_ai, to_ai, from_bundle, to_bundle) templates."""
    rows = []
    for old, new, recording in _LINES:
        src, dst = (old, new) if upgrade else (new, old)
        rows.append(
            "("
            + ", ".join(
                _quote(v) for v in (src, dst, f"{src} {recording}", f"{dst} {recording}")
            )
            + ")"
        )
    return "VALUES " + ", ".join(rows)


def _matches(column: str, template: str) -> str:
    return f"a.{column} = replace(m.{template}, '{{b}}', o.name)"


def _rewrite(*, upgrade: bool) -> None:
    mapping = f"m(from_ai, to_ai, from_bundle, to_bundle) AS ({_mapping(upgrade=upgrade)})"
    created = "" if upgrade else f" AND a.created_at < '{TEMPLATE_CHANGED_AT}'"
    # The FORCE bracket (`f4a2c7e19d63`): `agents` is FORCE-RLS'd, so without it these
    # statements match no rows.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    if upgrade:
        # Queued BEFORE the rewrite, from the same match, so the runs name exactly the
        # clients whose live agents are about to change.
        queued = execute_data_statement(
            sa.text(
                f"WITH {mapping}, runs AS ("
                "INSERT INTO live_apply_runs (id, scope, tenant_id, reasons) "
                "SELECT gen_random_uuid(), 'tenant', t.tenant_id, "
                "'[\"notice_greeting_removed\"]'::jsonb FROM ("
                "SELECT DISTINCT a.tenant_id FROM agents a "
                "JOIN organizations o ON o.id = a.tenant_id CROSS JOIN m "
                "WHERE a.deleted_at IS NULL AND a.status = 'live' "
                f"AND a.engine_agent_ref IS NOT NULL AND {_matches('ai_disclosure_line', 'from_ai')}"
                ") t RETURNING id) "
                "INSERT INTO outbox_messages (id, job, payload, status, attempt_count, "
                "created_at, updated_at) SELECT gen_random_uuid(), 'apply_live_settings', "
                "jsonb_build_object('run_id', id::text), 'pending', 0, now(), now() FROM runs"
            ),
            note="Queued a live apply for each client whose live agent's notice changes.",
        )
        log.info("notice greeting rewrite: %s client live-apply runs queued", queued)
    rewritten = execute_data_statement(
        sa.text(
            f"WITH {mapping} UPDATE agents a SET ai_disclosure_line = "
            "replace(m.to_ai, '{b}', o.name), updated_at = now() "
            "FROM organizations o, m WHERE o.id = a.tenant_id "
            f"AND {_matches('ai_disclosure_line', 'from_ai')}{created}"
        ),
        note="Rewrote AI notices that exactly match an old template output.",
    )
    bundles = execute_data_statement(
        sa.text(
            f"WITH {mapping} UPDATE agents a SET disclosure_line = "
            "replace(m.to_bundle, '{b}', o.name), updated_at = now() "
            "FROM organizations o, m WHERE o.id = a.tenant_id "
            f"AND {_matches('disclosure_line', 'from_bundle')}{created}"
        ),
        note="Rewrote legacy bundled disclosure lines that exactly match an old output.",
    )
    log.info("notice greeting rewrite: %s AI lines, %s bundled lines", rewritten, bundles)
    if upgrade and not probe_skipped_offline(
        "Not counted offline: AI notices that still open with a greeting word."
    ):
        skipped = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT count(*) FROM agents WHERE deleted_at IS NULL AND "
                    "ai_disclosure_line ~* '^(namaskaram|namaskar|namaste|hello|hi|vanakkam)\\M'"
                )
            )
            .scalar()
        )
        log.info("notice greeting rewrite: %s AI lines open with a greeting and were skipped "
                 "(edited, or the business was renamed)", skipped)
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    _rewrite(upgrade=True)


def downgrade() -> None:
    _rewrite(upgrade=False)
