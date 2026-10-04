"""`phone_numbers.provider` names a carrier this platform dials on, or nothing (D-663)

Revision ID: c8f5d1b74a30
Revises: b7e4c0a63f29
Create Date: 2026-10-02 00:00:00.000000

The column was free text typed by an operator ("Vobiz", "vobiz.ai", "Exotel"), and nothing
compared it with the carrier a dial actually goes out on. The dial gate now does
(`agents.service.agent_outbound_number_blocker`, rule `number_not_on_carrier`): a caller id
that is not on the carrier placing the call is a number that account cannot present.

So the column now holds `calevate_shared.carrier.CarrierName` or NULL:

1. Every value is trimmed and lower-cased.
2. The spellings an operator would type for the two carriers map to the carrier's name.
3. Anything else becomes NULL. A NULL provider is "not on the active carrier", which the
   dial gate refuses by name with a remediation, so a number whose provider was something
   else (a client's Exotel connection) is held back from dialling rather than presented on
   an account that does not hold it.
4. A CHECK keeps it that way.

RLS is unchanged: `phone_numbers` already carries its FORCEd tenant policy. FORCE makes the
owner subject to it too, and `tenant_isolation` is fail-closed on an unset `app.tenant_id`,
so an unbracketed UPDATE would match zero rows and the CHECK would then refuse the first
non-carrier spelling. The UPDATE is bracketed in `NO FORCE` ... `FORCE` (`d3b71c9a5e08`):
that lifts row security for the owner only, and DDL is transactional, so FORCE is back
before commit.

DOWNGRADE drops the CHECK only. The normalisation is not reversed: the original spellings
are not kept anywhere, and putting back an invented one would be worse than leaving the
carrier name.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c8f5d1b74a30"
down_revision: str | None = "b7e4c0a63f29"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CHECK = "ck_phone_numbers_provider_carrier"

#: Lower-cased, trimmed spellings -> carrier. Mirrors `agents.service.CARRIER_SPELLINGS`,
#: frozen here because a migration must not change meaning when the application code does.
_SPELLINGS: dict[str, str] = {
    "vobiz": "vobiz",
    "vobiz.ai": "vobiz",
    "vobiz ai": "vobiz",
    "www.vobiz.ai": "vobiz",
    "plivo": "plivo",
    "plivo.com": "plivo",
    "plivo inc": "plivo",
    "www.plivo.com": "plivo",
}


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    cases = " ".join(f"WHEN '{spelling}' THEN '{name}'" for spelling, name in _SPELLINGS.items())
    op.execute("ALTER TABLE phone_numbers NO FORCE ROW LEVEL SECURITY")
    op.execute(
        "UPDATE phone_numbers SET provider = "
        f"CASE lower(btrim(provider)) {cases} ELSE NULL END "
        "WHERE provider IS NOT NULL"
    )
    op.execute("ALTER TABLE phone_numbers FORCE ROW LEVEL SECURITY")
    op.execute(
        f"ALTER TABLE phone_numbers ADD CONSTRAINT {_CHECK} "
        "CHECK (provider IS NULL OR provider IN ('vobiz', 'plivo'))"
    )


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute(f"ALTER TABLE phone_numbers DROP CONSTRAINT IF EXISTS {_CHECK}")
