"""platform_voice_catalog: the engine account's voices, cached

Revision ID: c3d91f0a5b74
Revises: b8e2d47f0c19
Create Date: 2026-09-11

**WHY THIS TABLE EXISTS (D-585).** `apps/api/agents/voices.py` compiled its voice list from
SARVAM's own SDK enum — 44 speaker names. We do not publish to Sarvam; we publish through
the ENGINE, whose Sarvam provider offers a different subset. A live publish on 11 Sep 2026
returned `400 POST /v2/agent` — "Provided voice: Anushka is not available for the provider:
sarvam" — and `anushka` is the FIRST name in that enum. Worse, a voice the founder CLONES
after the code ships cannot be in a compiled Literal at all, by construction: its id exists
only on the engine account.

So the catalogue is READ from the engine's own two-step voice-config API and cached here
(VERIFIED-VENDOR-DOCS, `bolna-findings/mirror/pages/api-reference/voice/get_providers.md`
and `.../get_all.md`, read 11 Sep 2026 in the hash-pinned mirror).

**WHY THERE IS NO `tenant_id`, AND NO RLS POLICY.** This is a property of OUR engine
ACCOUNT, not of a client. One vendor account serves every tenant; its voice list is the
same list for all of them, and there is no tenant whose row any of these could be — a
`tenant_id` here would be a column that could only ever hold one value or a lie. It is the
same shape and the same argument as `platform_model_prices` (`a1f4c72b9e30`),
`platform_tts_prices` and `platform_tts_volume` (`f7c2a94e18b3`), and the written reason
`scripts/check_rls_coverage` reads lives in `apps/api/db/registry
.RLS_EXEMPT_TENANT_COLUMNS`. Every client-facing read is mediated by
`agents/voice_offer.offered_catalogue`, which answers the same catalogue to every tenant
deliberately.

**NOT APPEND-ONLY, deliberately.** Nothing here is a ledger entry: it is a cache of
somebody else's list, refreshed whole by `agents/voice_sync.py`, and every row is
re-derivable by running the sync again. An UPDATE is a cache line refreshing.

**NO BACKFILL, AND THAT IS THE DESIGN.** A migration cannot call the engine, and seeding
this from the compiled 44 would write into a cache the exact wrong list the table exists to
replace — an operator would then read rows that look synced and are not. An empty table is
the honest state "no sync has run", which `agents/voices.SEED_CATALOG` answers for (nine
voices a live engine read actually returned) while reporting `source: "seed"` on every
surface that renders the picker.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "c3d91f0a5b74"
down_revision = "b8e2d47f0c19"
branch_labels = None
depends_on = None

TABLE = "platform_voice_catalog"


def upgrade() -> None:
    op.create_table(
        TABLE,
        # OUR catalogue id, `<tts_model>:<speaker>` — the value written into
        # `agents.tts_voice`, hence the primary key.
        sa.Column("voice_id", sa.Text(), nullable=False),
        # What the ENGINE wants in its synthesizer block. Stored rather than recovered by
        # splitting `voice_id`, for the reason `voices.speech_for_voice_id` gives.
        sa.Column("engine_voice_id", sa.Text(), nullable=False),
        # The engine's own display name. A WIRE value too (their block requires `voice`
        # beside `voice_id`) and NOT derivable from a cloned voice's id.
        sa.Column("label", sa.Text(), nullable=False),
        # Text and not an enum: a row cached for a model the catalogue later stops offering
        # must still read back as itself.
        sa.Column("tts_model", sa.Text(), nullable=False),
        # Derived from `tts_model` through `model_lifecycle.TTS_MODEL_LIFECYCLE` on the way
        # in — stored for readers, never decided independently of the model (hard rule 7:
        # this column is the agent's billing TIER).
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column(
            "languages",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        # `source == 'custom'` on the engine's row: cloned or added by our account.
        sa.Column("is_custom", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("voice_id", name=op.f(f"pk_{TABLE}")),
        # The tier a minute bills at is a two-value vocabulary (`model_lifecycle
        # .TtsProvider`), and it reaches money. A typo in the sync would otherwise become a
        # provider nothing prices.
        sa.CheckConstraint(
            "provider IN ('sarvam', 'cartesia')", name=op.f(f"ck_{TABLE}_provider")
        ),
        # Empty strings are the shape a vendor row with a missing field arrives in, and an
        # empty `label` would be sent as the engine's required `voice` key.
        sa.CheckConstraint(
            "length(voice_id) > 0 AND length(engine_voice_id) > 0 AND length(label) > 0",
            name=op.f(f"ck_{TABLE}_non_blank"),
        ),
    )
    # NO RLS AND NO POLICY, deliberately — see the module docstring. The written reason
    # `check_rls_coverage` reads is in `db/registry.RLS_EXEMPT_TENANT_COLUMNS`.


def downgrade() -> None:
    # Nothing to preserve: every row is re-derivable by running the sync again, which is
    # exactly why this is a cache and not a ledger. A deployment that downgrades falls back
    # to `agents/voices.SEED_CATALOG` and says so on the picker.
    op.drop_table(TABLE)
