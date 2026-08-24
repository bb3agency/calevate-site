"""outbound_webhooks opt-ins: recording URL, redacted transcript, raw transcript

Revision ID: c3a9f1b48e70
Revises: f4b1e9a2c7d0
Create Date: 2026-08-24 10:00:00.000000

`call.completed` deliberately carries the summary and outcome and NOT the transcript or
the recording (docs/WEBHOOKS.md: "the summary — never the transcript — is what leaves on
a webhook"). This adds three PER-ENDPOINT opt-ins that let a client ask for more against
their OWN endpoint, each one a fact recorded in the config row rather than assumed:

* `include_recording_url` — a signed, short-TTL link to OUR copy of the recording (never
  the audio bytes; the link expires on `storage.PRESIGN_TTL_S`).
* `include_transcript` — the REDACTED transcript (`transcript_turns.text_redacted`), the
  same text a `calls:read` holder sees on the dashboard.
* `include_raw_transcript` — the UNREDACTED transcript. Layered on top of
  `include_transcript` and gated at the registration route with the same role control as
  a raw transcript read (`calls:read_raw`); every delivery that carries it writes an
  `audit_log` row (hard rule 5). Personal data leaving to a third party, so it defaults
  OFF like the other two.

All three default FALSE, so an endpoint that predates this migration behaves exactly as
before: no recording, no transcript, unchanged payload.

NO RLS CHANGE. `outbound_webhooks` is already tenant-RLS'd (migration 05bba2f3c19c) and
these columns ride on that row; they add no new tenant surface. Every read of them is the
existing tenant-scoped fan-out select in `integrations.service.enqueue_events`.

Reversible and rewrite-free: three `NOT NULL DEFAULT false` boolean adds take no table
rewrite on PG16 (the default is stored in the catalogue, not backfilled into every row),
and the downgrade drops columns nothing outside this feature references.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "c3a9f1b48e70"
down_revision: str | None = "f4b1e9a2c7d0"
branch_labels: str | None = None
depends_on: str | None = None


_COLUMNS = ("include_recording_url", "include_transcript", "include_raw_transcript")


def upgrade() -> None:
    for name in _COLUMNS:
        op.add_column(
            "outbound_webhooks",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.text("false")),
        )


def downgrade() -> None:
    for name in reversed(_COLUMNS):
        op.drop_column("outbound_webhooks", name)
