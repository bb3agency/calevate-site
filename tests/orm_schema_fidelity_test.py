"""The ORM and the migrated schema agree about the things `check_metadata_columns` does not.

That guardrail deliberately judges COLUMNS ONLY, and its docstring argues the scope well:
`compare_metadata` reports ~39 differences against the live schema and 38 are indexes and
constraints the migrations create on purpose and the models deliberately do not declare
(partial predicates, `CONCURRENTLY` builds, named constraints) — "a guard that failed on
all 39 would be a guard somebody turns off in a week".

That argument is about ONE DIRECTION. `remove_index` / `remove_constraint` (the database
has it, the models do not) is the legitimate half. The OPPOSITE direction has no such
excuse and had no guard, and D-192 found three instances of it plus two missing foreign
keys:

    ix_qa_reports_tenant_id          declared by TenantMixin, never built
    ix_qa_call_samples_tenant_id     declared by TenantMixin, never built
    ix_lead_saved_views_user_id      declared by the model, never built
    fk_qa_reports_tenant_id_organizations        built, never declared
    fk_qa_call_samples_tenant_id_organizations   built, never declared

`alembic/env.py` generates the next migration against `Base.metadata`, so the first three
are a proposed `CREATE INDEX` on tables whose index budget was decided by measurement
(DATA-MODEL §10) and the last two are a proposed `DROP CONSTRAINT` on the foreign key that
makes offboarding a workflow rather than a cascade — in a diff a human is asked to skim.

So this file asserts two properties, both narrow enough to stay green and both impossible
to satisfy by accident:

  1. Every tenant-scoped table's ORM `tenant_id` declares the FK to `organizations` with
     `ON DELETE RESTRICT`. Checked in metadata alone — no database needed — because it is
     a statement about what the models SAY, and that is what autogenerate reads.
  2. Nothing the models declare is absent from the migrated database: no `add_index`, no
     `add_fk`, no `add_column`. The mirror ops are deliberately NOT judged, for exactly the
     reason `check_metadata_columns` gives.

`add_constraint` is excluded from (2) and the exclusion is argued rather than assumed: an
unnamed `UniqueConstraint` in a model and its named counterpart in the database round-trip
as a `remove_constraint` + `add_constraint` PAIR under this repo's naming convention, so
six of them are permanent noise that says nothing about whether the constraint exists.
Uniqueness is covered instead by (2)'s index half, since every unique constraint in
PostgreSQL is backed by an index that `add_index` would name.
"""

from __future__ import annotations

import re

import pytest
from apps.api.db.registry import TENANT_TABLES, Base
from scripts.check_metadata_columns import compare_entries
from sqlalchemy import CheckConstraint, create_engine, text

#: Ops that mean "the models declare this and the database does not have it". The direction
#: with no legitimate instance — see the module docstring for why the mirror is excluded.
MODEL_AHEAD_OPS = ("add_index", "add_fk", "add_column")

#: `dnc_list` is in TENANT_TABLES and its `tenant_id` is NULLABLE by design (a global row
#: belongs to no tenant, DATA-MODEL §6). The FK is still required and still RESTRICT; only
#: the nullability differs, which this file does not judge.
EXPECTED_ONDELETE = "RESTRICT"


@pytest.fixture(scope="module")
def url() -> str:
    """The migrated database, or a skip. Comparing against anything but the real
    `pg_catalog` would be comparing the models to themselves."""
    from apps.api.core.settings import get_settings

    settings = get_settings()
    resolved = (settings.alembic_database_url or settings.database_url).replace(
        "+asyncpg", "+psycopg"
    )
    engine = create_engine(resolved)
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception as exc:  # pragma: no cover - local machines without docker
        pytest.skip(f"no database: {type(exc).__name__}: {exc}")
    finally:
        engine.dispose()
    return resolved


def test_every_tenant_table_declares_its_organizations_foreign_key() -> None:
    """RED before D-192 on `qa_reports` and `qa_call_samples`.

    Both use `TenantMixin`, whose comment claimed the FK and whose `mapped_column()` call
    named none — so the two tables that trusted the shared mixin were the two the schema's
    most-repeated invariant was missing from, while the forty-one that hand-write the
    column were fine. A mixin that is wrong is worse than no mixin: it is wrong quietly.
    """
    missing, wrong_target, wrong_ondelete = [], [], []
    for table_name in TENANT_TABLES:
        table = Base.metadata.tables[table_name]
        column = table.c["tenant_id"]
        keys = list(column.foreign_keys)
        if not keys:
            missing.append(table_name)
            continue
        key = keys[0]
        if key.target_fullname != "organizations.id":
            wrong_target.append(f"{table_name} -> {key.target_fullname}")
        if key.ondelete != EXPECTED_ONDELETE:
            wrong_ondelete.append(f"{table_name} ({key.ondelete})")

    assert not missing, (
        f"{missing}: the ORM column carries no ForeignKey to organizations, so the next "
        "`alembic revision --autogenerate` proposes DROPPING the one the database has. "
        "Orphaned tenant rows become representable and offboarding stops being a workflow."
    )
    assert not wrong_target, f"{wrong_target}: tenant_id must reference organizations.id"
    assert not wrong_ondelete, (
        f"{wrong_ondelete}: ON DELETE must be RESTRICT — offboarding is an explicit "
        "workflow (FLOWS §9), never a cascade that silently destroys a client's data."
    )


def test_the_models_declare_nothing_the_database_does_not_have(url: str) -> None:
    """RED before D-192 with three `add_index` ops and two `add_fk`-shaped gaps.

    The `add_*` direction is the one with no legitimate instance: a model that declares an
    index the schema has never had makes autogenerate offer to build it, which is how a
    measured index decision (DATA-MODEL §10) gets reversed by a diff nobody argued with.
    """
    entries = compare_entries(url)
    ahead = []
    for entry in entries:
        if entry[0] not in MODEL_AHEAD_OPS:
            continue
        subject = entry[3] if entry[0] == "add_column" else entry[1]
        ahead.append(f"{entry[0]}: {getattr(subject, 'name', subject)}")

    assert not ahead, (
        f"{ahead}: declared on an ORM model and ABSENT from the migrated database. Either "
        "write the migration that creates it, or delete the declaration — leaving it means "
        "the next autogenerate proposes it, and a model is not a place to record an "
        "intention (e7c3d10a9f52: 'a deprecation that un-deprecates itself')."
    )


def test_every_orm_check_constraint_exists_in_the_database(url: str) -> None:
    """RED before D-192 on `organizations.plan_tier`.

    `compare_metadata` does not diff CHECK constraints AT ALL, so this direction is invisible
    to every guard in the repo, and a `CheckConstraint` in a model is a DDL instruction that
    SQLAlchemy never evaluates client-side. Declaring one and not migrating it therefore puts
    the rule in a place that cannot refuse a row — `plan_tier` had been that way since D-39,
    and the database happily took `'enterprise_platinum'`.

    MATCHED ON THE PREDICATE, NOT THE NAME. Names drift harmlessly (`ck_platform_state_
    tm_status_enum` in the model against `ck_platform_state_tm_registration_enum` in the
    database; three constraints whose model name already carried the `ck_<table>_` prefix the
    naming convention adds again). A test keyed on names would report six cosmetic failures
    and get switched off, which is the failure mode `check_metadata_columns` describes. What
    cannot drift harmlessly is the SET OF VALUES a constraint admits, so each model check is
    reduced to the literals it names and looked for in some constraint on the same table.

    ⚠ THE LITERAL PATTERN ADMITS `.` AND `-`, AND IT DID NOT UNTIL D-454. It was
    `[A-Za-z0-9_]+`, which matches every status and vertical word this schema had — and
    matches NO model identifier, because every one of them carries a dot or a hyphen
    (`gpt-4o-mini`, `gpt-4.1-mini`). A constraint whose literals it cannot read reduces to
    an EMPTY set, and the empty set takes the `continue` below: `ck_agents_llm_model_allowed`
    and `ck_organizations_default_llm_model_allowed` would have been skipped in silence,
    which is this test's own failure mode rather than a gap in its subject. Widening costs
    nothing, because the pattern is applied to the model side and the database side
    identically — a literal it now reads on one side it also reads on the other.
    """
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT c.relname, pg_get_constraintdef(con.oid) FROM pg_constraint con "
                    "JOIN pg_class c ON c.oid = con.conrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = 'public' "
                    "WHERE con.contype = 'c'"
                )
            ).all()
    finally:
        engine.dispose()

    live: dict[str, list[str]] = {}
    for table_name, definition in rows:
        live.setdefault(table_name, []).append(definition)

    unenforced = []
    for table_name, table in sorted(Base.metadata.tables.items()):
        for constraint in table.constraints:
            if not isinstance(constraint, CheckConstraint):
                continue
            literals = set(re.findall(r"'([A-Za-z0-9_.-]+)'", str(constraint.sqltext)))
            if not literals:
                continue  # a purely numeric or column-only predicate; nothing to match on
            if not any(
                literals <= set(re.findall(r"'([A-Za-z0-9_.-]+)'", definition))
                for definition in live.get(table_name, [])
            ):
                unenforced.append(f"{table_name}.{constraint.name} -> {sorted(literals)}")

    assert not unenforced, (
        f"{unenforced}: declared as a CheckConstraint on the ORM model and no constraint on "
        "that table admits the same values. A CheckConstraint is a DDL instruction — "
        "SQLAlchemy never evaluates it — so a rule that was never migrated is a rule nothing "
        "enforces, and `compare_metadata` does not report CHECK constraints in either "
        "direction. Write the ALTER TABLE, or delete the declaration."
    )


def test_the_reverse_direction_is_deliberately_not_judged(url: str) -> None:
    """The scope of this file, pinned so it cannot quietly widen.

    Migrations legitimately build things the models do not declare — partial indexes,
    `CONCURRENTLY` builds, named constraints. If this ever reaches zero, the two assertions
    above stopped being narrow and started being `compare_metadata` with extra steps, which
    is the guard `check_metadata_columns` explains at length why nobody keeps.
    """
    reverse = [e for e in compare_entries(url) if e[0] in ("remove_index", "remove_fk")]
    assert reverse, (
        "the database no longer has anything the models leave undeclared — check whether "
        "the partial and CONCURRENTLY indexes are still there before relaxing this file"
    )
