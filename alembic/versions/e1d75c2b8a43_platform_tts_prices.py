"""platform_tts_prices — the operator-attested TTS price, effective-dated, append-only

Revision ID: e1d75c2b8a43
Revises: c9f3a71e58d2
Create Date: 2026-09-07 00:00:00.000000

D-547 / PLAN-CREDIT-LOTS-AND-VOICE-TIERS §3.5. A second voice tier (Cartesia Sonic 3.5)
arrives on a BYOK plan, and Bolna's own pricing page says of BYOK: *"Bolna does not charge
for those components. You only pay your providers directly, plus Bolna's platform fee"*
(plan ADDENDUM 3 §3.5). So the synthesizer leg of a Cartesia call is **₹0 from the engine**
and `CostBreakdown.tts_inr` — the figure `workers/pipeline.py` writes as `unit_cost_paid`
today — stops being a cost at all for that tier. Metering it from the vendor is not an
option either: what Cartesia bills is a MONTHLY PLAN with a character allotment, not a
per-call charge. The cost of a Cartesia minute is therefore a figure only an operator can
state, off their own Cartesia invoice, which is exactly what `platform_model_prices` does
for the LLM legs — and this table is its TTS twin, for the same reason and with the same
shape.

## Why a second table and not a second column on that one

`platform_model_prices` is keyed on a model in `calevate_shared.engine.LLM_MODELS` and its
figures are USD per MILLION TOKENS. A TTS price has neither: it is per THOUSAND CHARACTERS
and it belongs to a VOICE PROVIDER, not to a language model. Widening that table would
have meant a nullable unit column and a key that means two things, which is the shape a
reader has to be told about rather than one it can see.

## INR, and NOT the USD the LLM table stores

The LLM table stores dollars because the vendor publishes dollars and the USD->INR rate
moves under it (D-475). This figure is derived by the operator from a monthly PLAN — a
committed spend divided by its character allotment (Startup: ₹4,312 / 1.25M chars =
₹3.4496 per 1,000) — so the division and any conversion have already happened by the time
a human can read it off an invoice. Storing dollars would mean asking them to un-divide it.
The `source_note` is required and is where the plan, the period and any fx used are
recorded, so the figure stays re-derivable by a reader rather than being a bare number.

⚠ **UNKNOWN, AND NOT RESOLVED BY THIS MIGRATION: Cartesia's OVERAGE rate per character
past the plan allotment** (plan ADDENDUM 1, unknown #3). An operator attesting the plan's
marginal rate is attesting the price of a character INSIDE the allotment; a deployment that
runs past it is paying more than this table says. That is a founder/vendor question
(`cartesia.ai/pricing` or support), not a code one.

## Append-only, effective-dated, platform-scoped

The same three properties `platform_model_prices` carries, for the same three reasons: a
correction is a NEW instant so a re-rendered month resolves the price it was struck at;
the shared `calevate_forbid_mutation` / `calevate_forbid_truncate` triggers apply with no
carve-out and `ENABLE ALWAYS` so `session_replication_role = replica` cannot switch them
off; and there is no tenant whose row this could be (one Cartesia account for the whole
deployment), so it carries no `tenant_id` and is registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` with that as the written reason.

**Locking.** One `CREATE TABLE`, one index, two triggers on the new table. Nothing existing
is touched; both trigger functions already exist (05bba2f3c19c, a2e9f31c605d).

**Downgrade** drops the table, which destroys the attested price history — recoverable only
by re-attesting from the vendor invoices, exactly as `platform_model_prices`' downgrade is.
No usage row is touched: `unit_cost_paid` is a NUMERIC already written on the row, so a
call metered while this table existed keeps the cost it was metered at.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "e1d75c2b8a43"
down_revision: str | None = "c9f3a71e58d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.create_table(
        "platform_tts_prices",
        # OUR voice-tier vocabulary — `agents/voices.VoiceProvider`, which is the same
        # Literal `billing/lots.VoiceTier` spells. Text and not an enum, for
        # `platform_model_prices.model`'s reason: a price read back for a historical month
        # must resolve even for a provider the catalogue no longer offers.
        sa.Column("provider", sa.Text(), nullable=False),
        # The instant this price becomes authoritative. Part of the PK, so a correction is
        # a DISTINCT instant rather than a silent second row.
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        # RUPEES per THOUSAND CHARACTERS — see the module docstring for why the unit is not
        # the LLM table's USD/Mtok. NUMERIC(12,6): the Startup plan's own figure is
        # ₹3.4496/1k and a plan an order of magnitude larger divides finer still.
        sa.Column("inr_per_1k_chars", sa.Numeric(12, 6), nullable=False),
        sa.Column("attested_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "attested_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        # The operator's stated evidence — required, because it is what makes this an
        # attestation rather than a guess. The plan, its period and its allotment go here.
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["attested_by"],
            ["admin_users.id"],
            name=op.f("fk_platform_tts_prices_attested_by_admin_users"),
        ),
        sa.PrimaryKeyConstraint("provider", "effective_from", name=op.f("pk_platform_tts_prices")),
        # STRICTLY POSITIVE at the database, not only at the API. An attested ₹0 meters
        # every Cartesia character at nothing while looking like a working leg, which is
        # the one metering failure nobody investigates — `platform_model_prices` refuses a
        # zero for the identical reason and this is the same class of number.
        sa.CheckConstraint("inr_per_1k_chars > 0", name=op.f("ck_platform_tts_prices_positive")),
    )
    # The resolution query — "this provider's price with the greatest effective_from at or
    # before instant T" — walks this index rather than scanning the provider's history.
    op.create_index(
        "ix_platform_tts_prices_provider",
        "platform_tts_prices",
        ["provider", sa.text("effective_from DESC")],
    )
    op.execute(
        "CREATE TRIGGER platform_tts_prices_append_only "
        "BEFORE UPDATE OR DELETE ON platform_tts_prices "
        "FOR EACH ROW EXECUTE FUNCTION calevate_forbid_mutation()"
    )
    op.execute(
        "CREATE TRIGGER platform_tts_prices_forbid_truncate "
        "BEFORE TRUNCATE ON platform_tts_prices "
        "FOR EACH STATEMENT EXECUTE FUNCTION calevate_forbid_truncate()"
    )
    op.execute(
        "ALTER TABLE platform_tts_prices ENABLE ALWAYS TRIGGER platform_tts_prices_append_only"
    )
    op.execute(
        "ALTER TABLE platform_tts_prices "
        "ENABLE ALWAYS TRIGGER platform_tts_prices_forbid_truncate"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(
        "DROP TRIGGER IF EXISTS platform_tts_prices_forbid_truncate ON platform_tts_prices"
    )
    op.execute("DROP TRIGGER IF EXISTS platform_tts_prices_append_only ON platform_tts_prices")
    op.drop_index("ix_platform_tts_prices_provider", table_name="platform_tts_prices")
    op.drop_table("platform_tts_prices")
