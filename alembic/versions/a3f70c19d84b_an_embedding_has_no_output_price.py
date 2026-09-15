"""an embedding has no output price: platform_model_prices.output_usd_per_mtok nullable

Revision ID: a3f70c19d84b
Revises: f4b18c7d2e59
Create Date: 2026-09-15 12:00:00.000000

WHAT THIS IS FOR (D-608)
------------------------
`platform_model_prices` (c7f1a9e34b62) is where an operator records what a vendor charges
THIS account, read off their own invoice -- the one door hard rule 7 lets a figure reach
`unit_cost_paid` through. It was built for CHAT models, which are billed on two legs, so
both price columns are NOT NULL.

An EMBEDDING model is billed on ONE. The request returns a vector: there are no output
tokens, the vendor's `usage` block carries no output half, and every metering site in this
tree already records `tokens_out=0` as the TRUTH about an embedding rather than as a
default (`kb/pack_vectors._vectors_for`, `retrieval/embedding`). Google's page for
`gemini-embedding-2` prints one figure -- $0.20 per 1M INPUT tokens, no output charge
(VENDOR-PUBLISHED, founder-relayed 2026-09-11; `ai.google.dev` is egress-blocked from this
container and nothing here re-fetched it). So the operator has nothing to type in the
second box.

WHY NULL AND NOT ZERO
---------------------
A zero is a figure somebody entered; NULL is a fact about the vendor. The distinction is
load-bearing in two places that would both break on a zero: `billing/rates
.LlmPriceAttestation.__post_init__` refuses a non-positive price outright -- deliberately,
because a model priced at nothing bills every request at Rs 0 while looking like a working
leg -- and `ck_platform_model_prices_positive` does the same at the store. Storing zero
would mean weakening the one guard that catches a fat-fingered price, to encode a fact the
type system can carry for free.

THE EXISTING CHECK NEEDS NO CHANGE, WHICH WAS CHECKED RATHER THAN ASSUMED (hard rule 12).
`ck_platform_model_prices_positive` is `input_usd_per_mtok > 0 AND output_usd_per_mtok > 0`
(c7f1a9e34b62:120). In SQL a comparison against NULL evaluates to NULL, and a CHECK
constraint passes on anything that is not FALSE -- so a NULL output leg already satisfies
it while a zero or a negative one is still refused, which is exactly the rule wanted. A
second constraint spelling the same thing was written here and deleted: two guards for one
invariant is the drift this repository refuses elsewhere.

`llm_inr_per_ktok` renders a NULL output leg as an exact Rs 0.0000 rate, which is
arithmetically identical on a row whose quantity is always zero and honest on one that is
not.

WHY NOT A SECOND TABLE
----------------------
An operator reading a price off an invoice performs ONE act whatever it buys, and this
repository already refused to split that act once (D-547 put the VOICE price on the model
pricing panel rather than giving it its own). A `platform_embedding_prices` twin would
mean a second effective-dated reader, a second append-only registration, a second audit
action and a second snapshot leg -- for a row that differs from its neighbour by one
nullable column.

TENANCY (hard rule 1)
---------------------
No new table. `platform_model_prices` is platform-global and already registered in
`db/registry.RLS_EXEMPT_TENANT_COLUMNS` with its reason -- there is no tenant whose row a
vendor's price could be. Nothing to add here.

APPEND-ONLY (hard rule 4)
-------------------------
`platform_model_prices` is in `APPEND_ONLY_TABLES` and carries the immutability trigger.
DROP NOT NULL does not touch it: the trigger refuses UPDATE and DELETE, and this migration
issues neither. `check_ledger_immutability` re-verifies afterwards.

LOCKING
-------
One `ALTER COLUMN ... DROP NOT NULL`: catalogue-only on any supported Postgres, no scan
and no rewrite, so the ACCESS EXCLUSIVE lock is held for the length of a catalogue write.

DOWNGRADE
---------
Restores NOT NULL. It will FAIL LOUDLY if any input-only attestation exists, and that is
the correct behaviour rather than a gap: the old schema cannot represent those rows, and
the alternative -- deleting them, or back-filling a zero -- would either mutate an
append-only ledger or fabricate a vendor price. An operator who genuinely needs the old
schema has to decide what happens to that evidence; a migration must not decide it for
them silently. Hard rule 8 asks for reversible and reviewed, not for reversible at the
cost of inventing money.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "a3f70c19d84b"
down_revision: str | None = "f4b18c7d2e59"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.execute("ALTER TABLE platform_model_prices ALTER COLUMN output_usd_per_mtok DROP NOT NULL")


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    # Fails, by design, while any input-only attestation is on file. See DOWNGRADE above.
    op.execute("ALTER TABLE platform_model_prices ALTER COLUMN output_usd_per_mtok SET NOT NULL")
