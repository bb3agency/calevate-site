"""two stores that held personal data outside every retention policy get a clock

Revision ID: c4d1f7b83e26
Revises: b3d9f6a2c815
Create Date: 2026-08-17 09:40:00.000000

D-179. `retention_policies.data_category` has admitted exactly four categories since
migration 05bba2f3c19c — `recording|transcript|lead|consent_log` — and two stores of
tenant personal data fall outside all four. The legal audit (docs/LEGAL-SURFACE.md F-2
and F-3) names both, and this migration is the schema half of closing them.

--------------------------------------------------------------------------------
1. `engine_payload` — the archived raw vendor document (F-2)
--------------------------------------------------------------------------------

`calls.engine_payload_ref` (D-126) points at the engine's own document for a call. It
carries the caller's number and the transcript, so it is personal data whatever it was
kept for. A DPDP erasure reaches it (`_erase_engine_payloads`), which means the ONLY
people whose copy expires are the ones who filed a §12 request; everybody else's sits
there for ever. The bucket's 90-day `engine-payloads/` lifecycle rule was the notional
clock and `infra/README.md` §5 records that nothing in `infra/` has ever been applied to
a real bucket — so the clock did not exist.

DPDP §8(7) is a duty to stop holding personal data once the purpose is served, and a
store outside every retention policy a tenant can set cannot discharge it.

**The TTL default is 90 days and is not invented here.** It is the number
`infra/object-lifecycle/policy.json` already carries for the `engine-payloads/` prefix,
i.e. the period this repository already decided the archive is useful for; what changes
is that a mechanism that runs now enforces it. It is a per-tenant DEFAULT — a tenant may
lengthen or shorten it like any other category — and it deliberately sits below the
`transcript` default, because the archive is a debugging copy of data the tenant's own
transcript policy governs in its readable form.

--------------------------------------------------------------------------------
2. `kb` — superseded knowledge-base versions (F-3)
--------------------------------------------------------------------------------

`kb_sources`/`kb_documents` hold what a client uploads for their agents to answer from,
and publishing a new version ARCHIVES the old one rather than replacing it
(`kb/service.publish_source`). Nothing has ever deleted a `kb_documents` row, so every
version ever published survives — including the superseded ones no screen shows — and a
client whose price list names staff, doctors or contact numbers is holding third-party
personal data with no period attached.

The sweep arm this category drives expires SUPERSEDED and REJECTED versions only, never
the live one: a retention clock that deleted the knowledge an agent is currently
answering from would be an outage we caused, and the live version's period is the
client's engagement, not a TTL. It also refuses any source that still carries an engine
handle in `kb_documents.meta` — a superseded version has its handle cleared when it is
detached (`kb/service._detach_superseded`), so a handle still recorded means a detach
that never completed, and forgetting our copy of a document the engine still holds would
strand the only record that can address it.

**The TTL default is 365 days**, matching the `transcript` default rather than inventing
a third number: a superseded version is content of the same class and its remaining use —
rolling a bad publish back (FLOWS §7) — is measured in days, not years. Like every other
row here it is a default a tenant may change.

--------------------------------------------------------------------------------
What this migration deliberately does NOT do
--------------------------------------------------------------------------------

* **It does not add `campaign_contact`.** That gap is recorded in
  `tests/dpdp_known_gaps_test.py` and it is open for a reason this migration cannot
  close: how long a client's OWN uploaded contact list is kept is a commitment in their
  DPA, and the number is the founder's to give. Widening a CHECK is not permission to
  answer a question nobody asked us.
* **It does not touch the recording floor.** `ck_retention_policies_recording_ttl_floor`
  is untouched and still refuses a recording TTL below 90 days.
* **It adds no table**, so it adds no RLS policy: both new categories are rows in
  `retention_policies`, which is already tenant-scoped with FORCEd RLS, and the two
  stores they reach (`calls`, `kb_sources`/`kb_documents`) are already tenant-scoped
  too. `tests/kb_retention_test.py` and `tests/engine_payload_retention_test.py` carry
  the cross-tenant zero-rows assertions for the new sweep arms (hard rule 1).

Reversible. The downgrade narrows the CHECK back to four, which means it must first
DELETE the policy rows of the two new categories — a constraint cannot be re-imposed
over rows that violate it. That is stated rather than hidden: downgrading this migration
throws away two per-tenant settings, and re-upgrading re-seeds them at the defaults
above for new tenants only. Nothing is deleted from `calls`, `kb_sources` or
`kb_documents` by either direction.
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c4d1f7b83e26"
down_revision: str | None = "b3d9f6a2c815"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Spelled out rather than imported from `apps.api.compliance.models`: a migration is a
# historical record of the schema at one moment, and importing today's constant would
# make this file silently mean something different the next time the tuple changes.
_CATEGORIES_AFTER = ("recording", "transcript", "lead", "consent_log", "engine_payload", "kb")
_CATEGORIES_BEFORE = ("recording", "transcript", "lead", "consent_log")
_CONSTRAINT = "ck_retention_policies_category_enum"


def _category_check(categories: tuple[str, ...]) -> str:
    return "data_category IN ({})".format(", ".join(repr(c) for c in categories))


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, "retention_policies", type_="check")
    op.create_check_constraint(_CONSTRAINT, "retention_policies", _category_check(_CATEGORIES_AFTER))

    # PARTIAL, for `ix_webhook_deliveries_retained_body`'s reason exactly: the sweep
    # clears `engine_payload_ref` and no row ever regains one, so the population this
    # index serves is the small live tail rather than every call ever made.
    op.execute(
        "CREATE INDEX ix_calls_archived_engine_payload ON calls (created_at) "
        "WHERE engine_payload_ref IS NOT NULL"
    )
    # The superseded-version worklist. Leading with `tenant_id` because the sweep runs
    # inside one tenant's RLS context and asks "which of MY archived versions are older
    # than my TTL"; partial on `is_active = false` because a live version is never a
    # candidate and the live rows are the ones every other reader wants.
    op.execute(
        "CREATE INDEX ix_kb_sources_superseded ON kb_sources (tenant_id, updated_at) "
        "WHERE is_active = false"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_kb_sources_superseded")
    op.execute("DROP INDEX IF EXISTS ix_calls_archived_engine_payload")
    # Before the narrower CHECK can be re-imposed, the rows it would reject have to go.
    # See the docstring: this is real setting loss and it is the price of the downgrade.
    op.execute("DELETE FROM retention_policies WHERE data_category IN ('engine_payload', 'kb')")
    op.drop_constraint(_CONSTRAINT, "retention_policies", type_="check")
    op.create_check_constraint(
        _CONSTRAINT, "retention_policies", _category_check(_CATEGORIES_BEFORE)
    )
