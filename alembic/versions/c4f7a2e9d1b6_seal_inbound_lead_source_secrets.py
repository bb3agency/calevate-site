"""inbound_webhooks: seal the lead-source secrets at rest (D-735)

Revision ID: c4f7a2e9d1b6
Revises: b8e2d4f6a1c3
Create Date: 2026-10-11 18:00:00.000000

`secret_ref` and `previous_secret_ref` held each lead source's credential in plaintext — for
a Meta Lead Ads source, the client's own Meta App Secret. This revision seals every existing
value with the platform envelope (`apps/api/ingest/sealed_secret.py`), so a database read no
longer hands them out. No schema changes: the sealed form is text in the same columns.

THE KEK MUST BE PRESENT. Sealing is done in Python under `PLATFORM_KEK`, so this revision
runs where the API runs (the `migrate` service reads the same `.env`). Without a usable key
it refuses by name rather than leaving some rows sealed and some not.

ROLLOUT IS SAFE IN EITHER ORDER. The reader (`open_source_secret`) accepts both forms, so a
release that already reads sealed values verifies against a database this has not reached
yet, and a row written in plaintext by an older process during the deploy is sealed the
next time its secret is rotated (or by re-running this revision's logic). Each value is
sealed only if it is not sealed already, so a partial run can simply be repeated.

`alembic upgrade --sql` cannot seal: the statement is a function of a key and a random DEK,
not fixed SQL. Offline it writes a note into the script and changes nothing; the rows stay
readable in plaintext until this revision runs online.

The downgrade opens every sealed value back to plaintext, which is what an older release
reads.

THE RLS BRACKET: `inbound_webhooks` is FORCE ROW LEVEL SECURITY, which subjects the owner
to `tenant_isolation`; without lifting it for the owner these UPDATEs would match nothing
(`tests/migration_rls_bracket_test.py`). Restored in `finally`.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import sqlalchemy as sa
from alembic import op
from apps.api.db.migration_offline import emit_note, is_offline

revision: str = "c4f7a2e9d1b6"
down_revision: str | None = "b8e2d4f6a1c3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROWS = "SELECT id, tenant_id, secret_ref, previous_secret_ref FROM inbound_webhooks"
_WRITE = (
    "UPDATE inbound_webhooks SET secret_ref = :current, previous_secret_ref = :previous "
    "WHERE id = :id"
)


def _rewrite(transform: Callable[[str | None, object, object], str | None]) -> int:
    bind = op.get_bind()
    op.execute("ALTER TABLE inbound_webhooks NO FORCE ROW LEVEL SECURITY")
    try:
        changed = 0
        for row_id, tenant_id, current, previous in bind.execute(sa.text(_ROWS)).all():
            new_current = transform(current, tenant_id, row_id)
            new_previous = transform(previous, tenant_id, row_id)
            if (new_current, new_previous) == (current, previous):
                continue
            bind.execute(
                sa.text(_WRITE),
                {"id": row_id, "current": new_current, "previous": new_previous},
            )
            changed += 1
        return changed
    finally:
        op.execute("ALTER TABLE inbound_webhooks FORCE ROW LEVEL SECURITY")


def upgrade() -> None:
    if is_offline():
        emit_note(
            "c4f7a2e9d1b6: lead-source secrets are sealed in Python and cannot be rendered "
            "as SQL; run this revision online. Plaintext rows stay readable until then."
        )
        return
    from apps.api.ingest.sealed_secret import is_sealed, seal_source_secret

    def seal(value: str | None, tenant_id: object, row_id: object) -> str | None:
        if value is None or is_sealed(value):
            return value
        return seal_source_secret(value, tenant_id=str(tenant_id), webhook_id=str(row_id))

    sealed = _rewrite(seal)
    print(  # noqa: T201 - the deploy log is the only reader
        f"c4f7a2e9d1b6: sealed the secrets of {sealed} lead source(s)."
    )


def downgrade() -> None:
    if is_offline():
        emit_note("c4f7a2e9d1b6: run the downgrade online; sealed values need the key.")
        return
    from apps.api.ingest.sealed_secret import is_sealed, open_source_secret

    def open_(value: str | None, tenant_id: object, row_id: object) -> str | None:
        if value is None or not is_sealed(value):
            return value
        return open_source_secret(value, tenant_id=str(tenant_id), webhook_id=str(row_id))

    opened = _rewrite(open_)
    print(  # noqa: T201 - the deploy log is the only reader
        f"c4f7a2e9d1b6: restored {opened} lead source secret(s) to plaintext."
    )
