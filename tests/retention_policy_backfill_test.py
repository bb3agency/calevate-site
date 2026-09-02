"""A retention CATEGORY without a per-tenant ROW is a clock that never runs.

**THE DEFECT.** `c4d1f7b83e26` (D-179) added `engine_payload` and `kb` to
`ck_retention_policies_category_enum` and gave `apps/workers/retention.py` a sweep arm for
each. It wrote no rows. `admin/service._create_tenant_root` writes the full
`scripts/seed.DEFAULT_RETENTION_POLICIES` set for every organisation created AFTER that
migration, so the gap is invisible on a freshly migrated database and lands on exactly the
tenants that had been accumulating the data longest.

**WHY A MISSING ROW IS NOT A DEFAULT.** `retention._PROBE_SQL` selects
`FROM retention_policies` and `sweep_tenant` applies one arm per row it gets back. Nothing
in that path falls back to a platform default. A tenant with no `engine_payload` row is
therefore not swept at 90 days — it is not swept at all, silently, for ever, while
`calls.engine_payload_ref` keeps pointing at a raw vendor document holding the caller's
number and the transcript.

`a4f7d20c81be` is the repair, written as a later migration for `b7e35c2f81da`'s reason: a
revision that has already run everywhere will never run again, so editing it fixes nothing
that has happened.

Three tests, and the first is the one that would have caught this in CI:

1. a STATIC guard over the migration chain — a category the seed ships that was not in the
   original CHECK must be backfilled somewhere, or its clock only ever reaches new tenants;
2. the frozen copies in the repair still match the seed defaults;
3. the MECHANISM, against a real database: delete the row and the sweep stops reaching the
   store, restore it and the sweep reaches it again. Asserted on the object in the bucket,
   never on a row count.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from apps.api.admin import service as admin_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers import storage
from apps.workers.retention import sweep_tenant
from scripts.seed import DEFAULT_RETENTION_POLICIES
from sqlalchemy import text
from tests.conftest import FakeS3

VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"

#: The categories `05bba2f3c19c` created the table with. Those need no backfill: there was
#: no organisation before the migration that created `organizations`. Spelled as literals —
#: the point of this list is to be a record of what the schema shipped with, so importing
#: today's constant would make it agree with itself by construction.
_ORIGINAL_CATEGORIES = frozenset({"recording", "transcript", "lead", "consent_log"})

#: WHICH MIGRATION REACHES BACK FOR EACH CATEGORY THE SEED ADDED AFTER THE FIRST ONE.
#:
#: A NAMED REGISTRY rather than a grep, and the reason is that a grep cannot tell the two
#: apart: `e1a4d70c9b52` contains the quoted literals `'engine_payload'` and `'kb'` in the
#: CHECK-constraint tuple it rewrites, while seeding neither. A pattern loose enough to
#: find every real backfill is loose enough to be satisfied by a category being mentioned,
#: which is the failure this file exists to catch, passing.
#:
#: So the cost of a new category is one line here, named by the person who added it —
#: `tests/migration_rls_bracket_test.py`'s exception list makes the same trade for the same
#: reason. The two assertions below then check the claim rather than trusting it.
_BACKFILLED_BY: dict[str, str] = {
    # Seeded (unbracketed, so it matched nothing) by `d4a9c17e6b02` and actually written by
    # `e1a4d70c9b52::_REPAIR`, which ran the same statement inside a NO FORCE bracket.
    "copilot_memory": "e1a4d70c9b52",
    "caller_memory": "e1a4d70c9b52",
    # D-179 widened the CHECK in `c4d1f7b83e26` and wrote no rows at all; `a4f7d20c81be` is
    # the reach-back for both of its categories.
    "engine_payload": "a4f7d20c81be",
    "kb": "a4f7d20c81be",
}

_INSERT = re.compile(r"INSERT\s+INTO\s+retention_policies", re.IGNORECASE)


def test_every_seeded_category_added_after_the_first_migration_has_a_backfill() -> None:
    """A category the seed ships must reach the tenants that already existed.

    This is the assertion that was missing when D-179 shipped. Widening the CHECK and
    writing the sweep arm makes the category work for tenants created afterwards, and the
    two halves look complete on any database that was migrated from base — which is every
    development database and every CI run. The tenants it does not reach are only the real
    ones.
    """
    seeded = {str(policy["data_category"]) for policy in DEFAULT_RETENTION_POLICIES}
    missing = sorted(seeded - _ORIGINAL_CATEGORIES - set(_BACKFILLED_BY))
    assert not missing, (
        f"{missing} is shipped by `scripts.seed.DEFAULT_RETENTION_POLICIES` and no entry "
        "here names the migration that writes its row for the organisations that already "
        "existed. Without one, `retention.sweep_tenant` never applies that category to a "
        "tenant created before the migration that added it — the store it governs is "
        "retained for ever with no period. Add a backfill migration in the shape of "
        "`a4f7d20c81be` (NO FORCE / FORCE bracket, `ON CONFLICT DO NOTHING`) and name it "
        "here; do not edit the migration that shipped the gap, which has already run."
    )


def test_each_named_backfill_migration_exists_and_writes_a_row() -> None:
    """The registry is a claim about a file, so the file is opened.

    A pointer to a migration that does not seed anything is worse than no pointer: it
    reads as a discharged obligation. This is the same check
    `migration_rls_bracket_test.test_each_repair_names_the_migration_it_repairs` makes of
    its own list.
    """
    for category, revision in sorted(_BACKFILLED_BY.items()):
        matches = list(VERSIONS.glob(f"{revision}_*.py"))
        assert matches, f"`{category}` names migration `{revision}`, which does not exist"
        source = matches[0].read_text(encoding="utf-8")
        assert _INSERT.search(source), (
            f"`{revision}` is named as the backfill for `{category}` and contains no "
            "`INSERT INTO retention_policies` — the tenants that predate its category "
            "still hold that store with no clock on it."
        )


def test_the_repair_migrations_frozen_defaults_match_the_seed() -> None:
    """The frozen copies in `a4f7d20c81be` are the defaults a new tenant gets.

    A repair must write what the tenants that missed it WOULD have received. The migration
    retypes the values rather than importing them (a migration is a historical artefact),
    so this is the test that stops the two drifting — the discipline
    `tests/migration_rls_bracket_test.py` applies to `b7e35c2f81da`'s frozen SQL.
    """
    module = next(VERSIONS.glob("a4f7d20c81be_*.py")).read_text(encoding="utf-8")
    for policy in DEFAULT_RETENTION_POLICIES:
        category = str(policy["data_category"])
        if category in _ORIGINAL_CATEGORIES or category not in module:
            continue
        expected = f'("{category}", {policy["ttl_days"]}, "{policy["action"]}")'
        assert expected in module, (
            f"`a4f7d20c81be` repairs `{category}` with values that no longer match "
            f"`DEFAULT_RETENTION_POLICIES` ({expected} not found). A repair that writes a "
            "different TTL from the one a new tenant gets creates two classes of tenant "
            "instead of removing one."
        )


# --- the mechanism, against a real database -----------------------------------------


def _document() -> bytes:
    """What the archived vendor document actually holds — which is why it needs a clock."""
    return json.dumps(
        {
            "execution_id": "exec_backfill",
            "from": "+919876500901",
            "to": "+911140000000",
            "transcript": "namaskaram, naaku appointment kavali",
        }
    ).encode()


async def _org_with_an_expired_payload(s3: FakeS3) -> tuple[uuid.UUID, str]:
    """A tenant holding one archived payload well past the `engine_payload` default."""
    created = await admin_service.create_organization(
        name="Backfill Clinic",
        slug=f"rpb-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :ref, :t, :a, true, now(), now())"
            ),
            {"ref": f"rpb_{uuid.uuid4().hex[:12]}", "t": tenant_id, "a": agent_id},
        )
    call_id = uuid7()
    when = datetime.now(UTC) - timedelta(days=400)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, to_e164, started_at, ended_at, duration_s, created_at, updated_at) "
                "VALUES (:id, :t, :a, :e, 'inbound', 'completed', '+919876500901', "
                "'+911140000000', :w, :w, 90, :w, :w)"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"rpb_{uuid.uuid4().hex[:12]}",
                "w": when,
            },
        )
    key = await storage.archive_payload(
        tenant_id=tenant_id,
        call_id=call_id,
        engine="fake",
        execution_id="exec_backfill",
        document=_document(),
    )
    assert key is not None and key in s3.objects, "fixture precondition: the object is stored"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET engine_payload_ref = :k WHERE id = :i"),
            {"k": key, "i": call_id},
        )
    return tenant_id, key


async def _drop_policy(tenant_id: uuid.UUID, category: str) -> None:
    """Reproduce the state D-179 left a pre-existing tenant in: the category has no row."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM retention_policies WHERE data_category = :c"), {"c": category}
        )


async def test_a_tenant_with_no_engine_payload_row_is_never_swept(s3: FakeS3) -> None:
    """THE DEFECT, reproduced. No row, no arm, and the caller's number and transcript stay
    in the bucket — with the sweep reporting a clean tick.

    Asserted on `s3.objects`, never on the counter alone: the counter reads 0 both when
    the arm did not run and when it ran and found nothing, and those are the two states
    this whole finding is about telling apart.
    """
    tenant_id, key = await _org_with_an_expired_payload(s3)
    await _drop_policy(tenant_id, "engine_payload")

    counts = await sweep_tenant(tenant_id)

    assert counts["engine_payloads"] == 0, counts
    assert key in s3.objects, (
        "an archived vendor document was destroyed without a policy row — if the sweep "
        "has grown a platform default this test is describing the wrong mechanism"
    )


async def test_restoring_the_row_is_all_it_takes_for_the_sweep_to_reach_it(
    s3: FakeS3,
) -> None:
    """And the repair, as the migration performs it: one row per organisation, at the
    seed's own default, and the store the category governs is reached on the next tick."""
    tenant_id, key = await _org_with_an_expired_payload(s3)
    await _drop_policy(tenant_id, "engine_payload")
    assert (await sweep_tenant(tenant_id))["engine_payloads"] == 0

    policy = next(
        entry for entry in DEFAULT_RETENTION_POLICIES if entry["data_category"] == "engine_payload"
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO retention_policies (id, tenant_id, data_category, ttl_days, "
                "action, created_at) VALUES (:id, :t, :c, :ttl, :a, now())"
            ),
            {
                "id": uuid7(),
                "t": tenant_id,
                "c": policy["data_category"],
                "ttl": policy["ttl_days"],
                "a": policy["action"],
            },
        )

    counts = await sweep_tenant(tenant_id)

    assert counts["engine_payloads"] == 1, counts
    assert key not in s3.objects, "the archived vendor document survived its restored clock"
