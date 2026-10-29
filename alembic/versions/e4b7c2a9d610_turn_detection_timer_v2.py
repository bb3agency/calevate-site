"""agents: `timer_v2` turn detection allowed (D-940)

Revision ID: e4b7c2a9d610
Revises: c9d4e7a2b815
Create Date: 2026-10-30 10:00:00.000000

`agents.turn_detection` may now hold `timer_v2`, ThinnestAI's timer with an AI check of
whether the caller has finished (`thinnest-findings/mirror/snapshots/2026-10-29/pages/
api-reference/agents/update-agent.md:1453-1480`). The CHECK is replaced: the new one is added
NOT VALID and then validated under `lock_timeout`, and the old one dropped in the same
transaction.

REVERSIBILITY. `downgrade()` puts an agent an operator set to `timer_v2` back on the console's
mode (NULL) before restoring the three-value CHECK; that agent's next publish then sends the
console's mode.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "e4b7c2a9d610"
down_revision: str | None = "c9d4e7a2b815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CHECK = "ck_agents_turn_detection_enum"
_STAGED = "ck_agents_turn_detection_enum_v2"
# Spelled out rather than imported from the models: a migration is a snapshot.
_BEFORE = "('timer', 'ear', 'smart')"
_AFTER = "('timer', 'ear', 'smart', 'timer_v2')"


def _replace(values: str) -> None:
    op.execute(
        f"ALTER TABLE agents ADD CONSTRAINT {_STAGED} "
        f"CHECK (turn_detection IS NULL OR turn_detection IN {values}) NOT VALID"
    )
    op.execute(f"ALTER TABLE agents VALIDATE CONSTRAINT {_STAGED}")
    op.execute(f"ALTER TABLE agents DROP CONSTRAINT {CHECK}")
    op.execute(f"ALTER TABLE agents RENAME CONSTRAINT {_STAGED} TO {CHECK}")


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    _replace(_AFTER)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Bracketed: `agents` is FORCE RLS and fail-closed on an unset `app.tenant_id`, so an
    # unbracketed UPDATE matches no row and the VALIDATE below (which reads every row,
    # policy or not) then refuses the downgrade on the first `timer_v2` agent.
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    op.execute("UPDATE agents SET turn_detection = NULL WHERE turn_detection = 'timer_v2'")
    op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
    _replace(_BEFORE)
