"""a client chooses a model on ANY declared leg — the two CHECKs stop being Azure-only

Revision ID: d3a7c81f45be
Revises: c7f1a9e34b62
Create Date: 2026-08-23 06:10:00.000000

`b7d2f10c93ae` constrained `agents.llm_model` and `organizations.default_llm_model` to a
FROZEN COPY of the Azure allow-list — `('gpt-4.1-mini', 'gpt-4o-mini')` — because at the
time that was the whole of what anybody could choose. The product now offers three legs
(Azure OpenAI, OpenAI direct, Google Gemini): the founder holds all three vendor accounts,
installs all three keys in the ops console, and clients pick from whichever models are
offerable. The constraints are what stops those choices being written at all, so they move
first or nothing else in the change is reachable.

WHAT THIS REVISION DOES
-----------------------
Drops and re-adds both CHECKs over the wider list. Nothing else: no column is added, no
column is dropped, no row is rewritten. `agents.llm_model` and
`organizations.default_llm_model` keep their types, their nullability and every value they
hold.

WHY DROP-AND-ADD RATHER THAN `ALTER ... DROP CONSTRAINT` PLUS A NEW NAME
------------------------------------------------------------------------
The names are load-bearing: `tests/llm_model_selection_test.py` reads them, the downgrade
of `b7d2f10c93ae` drops them by name, and an operator reading a violation message sees
them. A second constraint under a new name would leave the old, narrower one in force — so
the widening would silently not happen, which is the failure that looks exactly like
success. Postgres has no `ALTER CONSTRAINT` for a CHECK's expression, so drop-and-add under
the SAME name is the only way to widen one, and it is atomic inside this transaction.

THE ALLOW-LIST IS COPIED, FROZEN, HERE — the same alembic discipline `b7d2f10c93ae`
argued at length and for the same reason: importing `calevate_shared.engine` would make
THIS revision replay differently after a future model is added, so the values are written
out as they read today and `tests/llm_model_selection_test.py` asserts the frozen copy
still equals the live set. Adding a model to a `Literal` fails that test until a new
revision widens the constraint, which is the "not a one-line change" the Literal's own
comment warns about.

⚠ WHICH SET IS FROZEN HERE, AND WHY IT IS THE WIDER OF THE TWO CANDIDATES
------------------------------------------------------------------------
It is `LLM_MODEL_NAMES` — every model in the catalogue — and NOT `SELECTABLE_LLM_MODELS`,
which is what the API actually offers. That is deliberate and it is the one judgement in
this revision worth arguing with:

* A CHECK is a FLOOR against values no writer should ever produce — a restore that lands
  without constraints, a hand-run UPDATE during an incident, a future importer. It is not
  the product's policy surface. `validate_llm_model` refuses a non-offerable model at the
  write path, `offerable_models()` decides what a picker shows, and `in_call_llm` refuses
  again at publish; three layers already state the narrower rule, in code that can consult
  a live credential and a live attestation.
* A constraint frozen at the SELECTABLE set would have to be migrated every time a model's
  `selectable` flag moved — and `selectable` moves for reasons that are not schema-shaped
  at all: somebody reads a vendor's deprecation page, a trap turns out to be mitigable. A
  DDL migration gated on a docs reading is a migration that will be skipped.
* And the failure it would prevent is one nothing can reach: to write a withdrawn model
  into these columns you would have to bypass the API entirely, at which point you have
  also bypassed the layer that knows whether a key is installed.

So: the catalogue is the floor, the code is the policy. A value outside the CATALOGUE is a
typo or a corrupted restore and is refused by the database; a value inside it that nobody
may choose today is refused by three code paths that can see facts a CHECK cannot.

REVERSIBLE, AND THE DOWNGRADE IS THE INTERESTING DIRECTION
----------------------------------------------------------
`downgrade()` restores `b7d2f10c93ae`'s exact two-model list. **That can FAIL, on purpose,
and the failure is the good outcome.** If any account has by then chosen an OpenAI or
Gemini model, `ADD CONSTRAINT` validates the existing rows and refuses by name — telling an
operator exactly which rows contradict the narrower rule, instead of silently leaving a
value the code one release back cannot price, cannot address and cannot authenticate. A
downgrade that "succeeded" by dropping those choices would be destroying a client's
configuration to make a rollback quiet. The remedy is named in this docstring and is one
UPDATE: null the offending columns (which means "inherit"), then downgrade.

TWO-STEP DEPRECATION IS NOT OWED HERE (hard rule 8) because nothing is removed: this
revision only ever WIDENS the admitted set. Every value legal before is legal after.

NO RLS CHANGE, VERIFIED RATHER THAN ASSUMED
-------------------------------------------
`organizations` carries its FORCEd policy (matching on `id`, not `tenant_id` — it is the
tenant root) and `agents` carries its own. This revision touches no policy and adds no
column, so nothing about RLS should move — and "should not move" is exactly the class of
sentence that stays true until a neighbouring `ALTER TABLE` turns FORCE off. So
`_assert_rls_still_forced` re-reads `pg_class` after the DDL rather than trusting it, the
same way `b7d2f10c93ae` does and for the same reason (hard rule 1).
"""

import sqlalchemy as sa
from alembic import op

revision = "d3a7c81f45be"
down_revision = "c7f1a9e34b62"
branch_labels = None
depends_on = None

CK_ORG_MODEL = "ck_organizations_default_llm_model_allowed"
CK_AGENT_MODEL = "ck_agents_llm_model_allowed"

# FROZEN COPY of `calevate_shared.engine.LLM_MODEL_NAMES` as it read the day this revision
# was written — the three per-leg Literals unioned. See the docstring for why it is a copy,
# and for why it is the catalogue rather than the selectable set.
ALLOWED_LLM_MODELS = (
    # azure_openai
    "gpt-4.1-mini",
    "gpt-4o-mini",
    # openai direct
    "gpt-5.4-mini",
    "gpt-5.6-luna",
    # google gemini
    "gemini-2.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-3.1-flash-lite",
    "gemini-3.5-flash",
)

# FROZEN COPY of what `b7d2f10c93ae` admitted, for the downgrade. Written out rather than
# imported from that module for the identical reason the list above is: a revision that read
# another revision's constant would replay differently once that one was edited.
PRIOR_ALLOWED_LLM_MODELS = ("gpt-4.1-mini", "gpt-4o-mini")


def _in_list(models: tuple[str, ...]) -> str:
    """The `IN (...)` body, sorted at the source so the constraint text is byte-stable
    across interpreter runs — an unordered set here would make `alembic revision
    --autogenerate` offer a spurious diff on every invocation."""
    return ", ".join(f"'{model}'" for model in sorted(models))


def _apply(models: tuple[str, ...]) -> None:
    """Re-state both CHECKs over `models`, under their existing names.

    ONE function for both directions, because upgrade and downgrade differ ONLY in the list
    — and a downgrade spelled out separately is where the two constraint names, the two
    column names and the NULL clause drift apart unnoticed.

    `DROP ... IF EXISTS` then `ADD`: the drop is tolerant because a database restored from
    before `b7d2f10c93ae` legitimately has no such constraint, and the ADD is not, because a
    constraint that failed to apply is the whole point of running this.

    Spelled with `op.execute` rather than `op.create_check_constraint`, which applies this
    project's naming convention to a name that already carries it and produces
    `ck_organizations_ck_organizations_…` (measured on a real database — see `c4f18a6b90e2`).
    """
    admitted = _in_list(models)
    for table, constraint, column in (
        ("organizations", CK_ORG_MODEL, "default_llm_model"),
        ("agents", CK_AGENT_MODEL, "llm_model"),
    ):
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT IF EXISTS {constraint}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {constraint} "
            f"CHECK ({column} IS NULL OR {column} IN ({admitted}))"
        )
    _assert_rls_still_forced()


def _assert_rls_still_forced() -> None:
    """Hard rule 1, re-read from the catalog instead of asserted in the docstring.

    `check_rls_coverage` asks this of the whole schema on every `make guardrails`; asking
    it HERE is what stops a release shipping a client's model choice onto a table whose
    protection somebody turned off in a neighbouring revision.
    """
    for table in ("organizations", "agents"):
        row = (
            op.get_bind()
            .execute(
                sa.text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = CAST(:qualified AS regclass)"
                ),
                {"qualified": f"public.{table}"},
            )
            .first()
        )
        if row is None or not (row[0] and row[1]):
            raise RuntimeError(
                f"{table} is not FORCE ROW LEVEL SECURITY after this migration; the "
                "language-model selection would be readable across tenants (hard rule 1)"
            )


def upgrade() -> None:
    _apply(ALLOWED_LLM_MODELS)


def downgrade() -> None:
    # MAY REFUSE, AND THAT IS CORRECT — see the docstring. If an account has chosen a model
    # from a leg the narrower list does not know, Postgres validates the existing rows and
    # names the constraint. Null those columns (which means "inherit") and re-run.
    _apply(PRIOR_ALLOWED_LLM_MODELS)
