"""`ux_usage_events_tenant_call_unit` — the metering ledger's natural key (b8d3f47c2a19).

`usage_events` was the only one of the three money ledgers with no unique index. D-110
closed the double-metering race with `lock_call_writes`, and an advisory lock protects the
call sites that remember to take it — the DATABASE refused nothing. This file pins the
index that does, and specifically pins the four ways it could be wrong in a way no
double-charge test would notice:

1. **it could break the compensating-entry route.** `record_tier_correction` is how hard
   rule 4 fixes a mis-metered call: it APPENDS a `unit_type = 'other'` row against the
   same `(tenant_id, call_id)`, and two ops references correcting one call produce two of
   them. A key over every unit type would turn the one mechanism the ledger has for
   putting a mistake right into an IntegrityError.
2. **it could drift from the metering path.** The covered unit types are frozen in a
   migration (correctly — a migration is a historical fact). The set is therefore read
   back out of `pipeline._meter`'s own source here, so a sixth metered unit type
   fails on the day it lands rather than shipping unprotected.
3. **it could become a cross-tenant side channel.** A unique violation is one of the few
   things that can tell you a row you cannot SELECT exists. `tenant_id` leads the key
   precisely so it cannot, and hard rule 1 wants that asserted, not assumed.
4. **it could be used to smuggle an UPDATE past hard rule 4.** A unique index is what
   makes `ON CONFLICT DO UPDATE` writable, and on an append-only table it must still be
   refused — by the trigger, which is the guard that does not care how the UPDATE was
   spelled.

Run: uv run pytest -q tests/usage_events_unique_index_test.py
"""

from __future__ import annotations

import ast
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.models import UNIT_TYPES
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError, ProgrammingError

pytestmark = [pytest.mark.rls]

REPO_ROOT = Path(__file__).resolve().parents[1]
INDEX = "ux_usage_events_tenant_call_unit"

#: The five the migration froze. Restated here rather than imported from the revision
#: module: importing it would make the comparison below tautological (the migration is
#: one of the two things being held equal), and a revision file is not an importable API.
COVERED_UNIT_TYPES = frozenset({"telephony_s", "platform_min", "stt_s", "tts_chars", "llm_tok_out"})


async def _index_definition() -> str:
    async with untenanted_session() as session:
        found = (
            await session.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND "
                    "tablename = 'usage_events' AND indexname = :name"
                ),
                {"name": INDEX},
            )
        ).scalar()
    assert found is not None, (
        f"{INDEX} is not on this database. Migration b8d3f47c2a19 creates it; if it was "
        "dropped deliberately, this whole file is the argument against that."
    )
    return str(found)


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A provisioned tenant and its agent, through the ADMIN SERVICE rather than by
    INSERTing an `organizations` row here.

    `invoice_gst_test` makes the argument and it applies to every fixture in this repo: a
    test that hand-writes a row passes against a schema the real writer no longer
    produces. `organizations` has already lost a column a fixture like this used to set.
    """
    created = await admin_service.create_organization(
        name="Index Fixture",
        slug=f"uxidx-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email="accounts@uxidx.example",
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _call(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, call_id: uuid.UUID | None = None
) -> uuid.UUID:
    """One completed call. `call_id` is an argument because one test deliberately gives
    two tenants the SAME call id — see its docstring."""
    call_id = call_id or uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, created_at, updated_at) VALUES (:i, :t, :a, :e, 'inbound', "
                "'+919876500001', 'completed', now(), now())"
            ),
            {"i": call_id, "t": tenant_id, "a": agent_id, "e": f"exec_{uuid.uuid4().hex[:12]}"},
        )
    return call_id


async def _meter_row(tenant_id: uuid.UUID, call_id: uuid.UUID | None, unit_type: str) -> None:
    """One usage_events row, written the way the pipeline writes one."""
    async with tenant_session(tenant_id) as own:
        await own.execute(
            text(
                "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, :u, 1, 0.5000, "
                "now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "u": unit_type},
        )


# ------------------------------------------------ 1. the key does what it says


async def test_a_call_cannot_be_metered_twice_for_the_same_unit() -> None:
    """The whole point. Two `telephony_s` rows for one call is a double charge on an
    append-only table, and there is no UPDATE that removes the second one."""
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id)

    await _meter_row(tenant_id, call_id, "telephony_s")
    with pytest.raises(IntegrityError) as caught:
        await _meter_row(tenant_id, call_id, "telephony_s")

    assert INDEX in str(caught.value), f"refused by something else: {caught.value}"


async def test_the_five_metered_units_are_five_separate_rows() -> None:
    """The key is (tenant, call, UNIT) and not (tenant, call): one call legitimately
    carries one row per leg, and a key one column short would reject four of five."""
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id)

    for unit in sorted(COVERED_UNIT_TYPES):
        await _meter_row(tenant_id, call_id, unit)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": call_id}
            )
        ).scalar()
    assert int(rows) == len(COVERED_UNIT_TYPES)


async def test_two_corrections_against_one_call_are_both_accepted() -> None:
    """THE CLAUSE THAT NEARLY GOT LEFT OUT.

    `billing.service.record_tier_correction` appends `unit_type = 'other'` against the
    same `(tenant_id, call_id)` — that is how hard rule 4 corrects a call metered on the
    wrong TTS rung, since the wrong row can never be edited. One ops reference may cover
    a batch, so a second reference correcting the SAME call is a legitimate second row.
    Without `unit_type IN (...)` in the index predicate, this key would convert the
    ledger's only repair mechanism into a 500 on the correction route.
    """
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id)

    await _meter_row(tenant_id, call_id, "other")
    await _meter_row(tenant_id, call_id, "other")  # must NOT raise

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM usage_events WHERE call_id = :c AND unit_type = 'other'"
                ),
                {"c": call_id},
            )
        ).scalar()
    assert int(rows) == 2, "the compensating-entry route lost a row to the metering key"


async def test_rows_with_no_call_do_not_collide() -> None:
    """`number_rental` and the restore drill's probe rows carry no `call_id`. NULLs do not
    collide in a btree, and `call_id IS NOT NULL` says so out loud — but a future edit
    that swapped the column for a sentinel would make every rental row fight the last
    one, so this is asserted rather than left to btree semantics."""
    tenant_id, _agent_id = await _tenant()

    await _meter_row(tenant_id, None, "number_rental")
    await _meter_row(tenant_id, None, "number_rental")

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE tenant_id = :t AND call_id IS NULL"),
                {"t": tenant_id},
            )
        ).scalar()
    assert int(rows) == 2


# --------------------------------------- 2. the covered set tracks the metering path


def _unit_types_the_metering_path_writes() -> set[str]:
    """Every `UNIT_TYPES` member named as a literal inside `pipeline._meter`.

    READ FROM THE AST, not from a hand-kept list and not from a grep: the metering rows
    are built as a Python list of tuples plus two conditional `rows.append(...)` calls,
    so there is no runtime value to import — and a source-text scan would match the
    docstrings in that function that discuss `tts_chars` and `llm_tok_out` in prose.
    Filtered through `UNIT_TYPES` so an unrelated string constant in the function body
    (a meta key, a tier name) is not mistaken for a unit.
    """
    tree = ast.parse((REPO_ROOT / "apps/workers/pipeline.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef | ast.FunctionDef) and node.name == "_meter":
            return {
                child.value
                for child in ast.walk(node)
                if isinstance(child, ast.Constant)
                and isinstance(child.value, str)
                and child.value in UNIT_TYPES
            }
    raise AssertionError(
        "`_meter` is no longer in apps/workers/pipeline.py — this test lost its "
        "subject, and the index's covered set is now unchecked against anything"
    )


async def test_the_index_covers_exactly_the_unit_types_the_metering_path_writes() -> None:
    """The drift guard, and the reason this file exists rather than one assertion.

    The migration froze five unit types as literals, which is right — a revision is a
    historical fact and must not change meaning because a constant elsewhere moved. The
    cost of freezing is that a SIXTH metered unit type would ship uncovered and nothing
    would say so. This is what says so: the covered set is compared against
    `_meter`'s own source, in both directions.

    Closing a failure here is a decision, not a rename: covering a new unit type means a
    new migration (this index cannot be widened in place), and NOT covering it means
    saying in `_meter` why that leg may legitimately be metered twice.
    """
    written = _unit_types_the_metering_path_writes()
    assert written, "the AST scan found no unit types at all — the scan is broken, not the code"

    definition = await _index_definition()
    in_index = {unit for unit in UNIT_TYPES if f"'{unit}'" in definition}

    assert in_index == COVERED_UNIT_TYPES, (
        f"the live index covers {sorted(in_index)}, and this file expects "
        f"{sorted(COVERED_UNIT_TYPES)} — the database and the test disagree about the key"
    )
    assert written == COVERED_UNIT_TYPES, (
        f"`_meter` writes {sorted(written)} but ux_usage_events_tenant_call_unit "
        f"covers {sorted(COVERED_UNIT_TYPES)}.\n"
        f"  metered but unprotected: {sorted(written - COVERED_UNIT_TYPES)}\n"
        f"  protected but unwritten: {sorted(COVERED_UNIT_TYPES - written)}\n"
        "A metered unit with no key is a leg that can be billed twice; widening the key "
        "needs a new migration, because a partial index cannot be altered in place."
    )
    # And 'other' is explicitly OUT — the compensating-entry namespace. Asserted rather
    # than implied by the set comparison, because that is the clause a future widening is
    # most likely to sweep back in "for consistency".
    assert "other" not in in_index, (
        "'other' is the hard-rule-4 correction namespace; covering it makes a second "
        "correction against one call an IntegrityError"
    )


async def test_the_grandfather_cutoff_is_an_aware_utc_instant() -> None:
    """A naive cutoff literal is read in the server's TimeZone and moves by five and a
    half hours on a machine set to IST — silently widening or narrowing the window in
    which a duplicate is legal. The offset must be in the index definition."""
    definition = await _index_definition()
    assert "created_at >= '2026-08-15 10:14:00+00'::timestamp with time zone" in definition, (
        f"the cutoff is not the aware UTC instant b8d3f47c2a19 wrote: {definition}"
    )
    # On `created_at`, never `occurred_at` — the poller backdates `occurred_at` to the
    # call's end, so an `occurred_at` line would leave every poller repair outside the
    # index. The migration argues this at length; here it is a fact about the schema.
    assert "occurred_at" not in definition


# --------------------------------------------------- 3. hard rule 1: no side channel


async def test_two_tenants_may_hold_the_same_call_and_unit() -> None:
    """The cross-tenant zero-rows check hard rule 1 requires, in the shape this change
    can break it.

    A unique violation is one of the very few signals that can announce a row RLS is
    hiding: if the key did not lead with `tenant_id`, tenant B inserting against a
    `call_id` belonging to tenant A would get a constraint error naming a row B cannot
    SELECT — a membership oracle over another client's call ids. `call_id` is a uuid7 and
    not guessable, which makes this narrow rather than absent; narrow is not a defence
    worth relying on.

    B writes against A's `call_id` directly. That resolves the foreign key — Postgres
    runs referential-integrity checks in a security-restricted context that is not RLS
    filtered, which is the whole reason this is reachable at all — while B's own row
    carries `tenant_id = B`. So the only thing that could refuse it is the metering key,
    and it must not.
    """
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    shared_call = await _call(tenant_a, agent_a)

    await _meter_row(tenant_a, shared_call, "telephony_s")

    # B cannot even see A's call row, which is the zero-rows half.
    async with tenant_session(tenant_b) as session:
        visible = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": shared_call}
            )
        ).scalar()
    assert int(visible) == 0, "tenant B can read tenant A's metering rows"

    # And B writing the same (call_id, unit_type) is accepted, because the key is scoped.
    await _meter_row(tenant_b, shared_call, "telephony_s")

    async with tenant_session(tenant_a) as session:
        a_rows = (
            await session.execute(
                text("SELECT count(*) FROM usage_events WHERE call_id = :c"), {"c": shared_call}
            )
        ).scalar()
    assert int(a_rows) == 1, "tenant A's ledger grew a row it did not write"


# ----------------------------------- 4. the index is not a way past the append-only rule


async def test_on_conflict_do_update_is_still_refused_by_the_append_only_trigger() -> None:
    """Hard rule 4 does not soften because the table gained a unique index.

    An upsert is the thing a unique index makes SPELLABLE, and `ON CONFLICT DO UPDATE` on
    a ledger is an edit to a row somebody has already been billed for. The append-only
    trigger is what refuses it, and it refuses it because the statement performs an
    UPDATE — not because anyone remembered to forbid this particular spelling. Pinned so
    that a future convenience upsert fails here with the rule's own message rather than
    quietly rewriting history.
    """
    tenant_id, agent_id = await _tenant()
    call_id = await _call(tenant_id, agent_id)
    await _meter_row(tenant_id, call_id, "stt_s")

    with pytest.raises((IntegrityError, ProgrammingError, DBAPIError)) as caught:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, 'stt_s', 99, "
                    "9.9999, now(), now()) "
                    "ON CONFLICT (tenant_id, call_id, unit_type) "
                    "WHERE call_id IS NOT NULL AND unit_type IN ('telephony_s', 'platform_min', "
                    "'stt_s', 'tts_chars', 'llm_tok_out') "
                    "AND created_at >= '2026-08-15 10:14:00+00:00'::timestamptz "
                    "DO UPDATE SET qty = EXCLUDED.qty"
                ),
                {"i": uuid7(), "t": tenant_id, "c": call_id},
            )
    assert "append" in str(caught.value).lower() or "immutab" in str(caught.value).lower(), (
        f"the upsert was refused, but not by the append-only rule: {caught.value}"
    )

    # And the original row is untouched — a refusal that had already written is not a
    # refusal.
    async with tenant_session(tenant_id) as session:
        qty = (
            await session.execute(
                text("SELECT qty FROM usage_events WHERE call_id = :c AND unit_type = 'stt_s'"),
                {"c": call_id},
            )
        ).scalar()
    assert Decimal(qty) == Decimal(1), f"the ledger row was rewritten to {qty}"
