"""Knowledge belongs to the client, not to one agent (D-689)

Revision ID: e6b2d9f4a1c3
Revises: d8f3a1c6e2b9
Create Date: 2026-10-08 20:00:00.000000

The founder's decision of 8 Oct 2026: a client's uploaded documents and web pages are shared
by every one of that client's agents. `kb_sources.agent_id` was NOT NULL and the version
sequence was numbered per `(agent_id, name)`, so knowledge was per agent.

What changes:

* `kb_sources.agent_id`, `kb_uploads.agent_id`, `kb_chunks.agent_id` and
  `kb_index_documents.agent_id` become NULLABLE and the code stops writing them. The columns
  stay (hard rule 8: a column is dropped in a later release than the one that stops writing
  it). The values already on `kb_sources` and `kb_uploads` are kept as provenance — which
  agent's screen a pre-D-689 source was first added on — and nothing reads them.
* `kb_chunks.agent_id` IS CLEARED. It is a derived projection, and its foreign key to
  `agents` is `ON DELETE CASCADE`: left populated, deleting an agent row would delete chunks
  of knowledge every other agent of the client still answers from.
* The version sequence is numbered per `(tenant_id, name)`.
* `engine_kb_routes` holds one claim per (source, agent): on an engine whose knowledge is
  per vendor agent (ThinnestAI) the same source is one vendor document on each agent.
  `uq (source_id)` becomes `uq (source_id, agent_id)`; the primary key on the vendor handle
  is unchanged, so two rows can still never claim one vendor object.

NAMES THAT COLLIDE ACROSS AGENTS. Two agents of one client could each hold a source called
"Prices"; under one sequence they would become versions of each other and publishing one
would archive the other. Both are kept: the agent whose source of that name is OLDEST keeps
the name, and every other agent's source of that name is renamed "<name> (<agent name>)",
with " 2", " 3" appended if that is taken too. Renaming loses nothing — each keeps its own
text and version history — where merging would silently retire knowledge a client approved.
`kb_documents.title` carries the source name and moves with it.

The data statements read and write FORCE-RLS tables, so each is bracketed by `NO FORCE` /
`FORCE` on the tables it touches (`tests/migration_rls_bracket_test.py`).

DOWNGRADE. Restores NOT NULL by giving every tenant-level row the tenant's oldest live
agent, and refuses — rather than deleting knowledge — when a tenant holds tenant-level
sources and no agent, or when a source is attached to more than one agent's vendor copy.
The renames are not reverted: the new names are valid under the old constraint as well.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from apps.api.db.migration_offline import probe_skipped_offline

revision: str = "e6b2d9f4a1c3"
down_revision: str | None = "d8f3a1c6e2b9"
branch_labels: str | None = None
depends_on: str | None = None

_OLD_SOURCE_UQ = "uq_kb_sources_agent_id_name_version"
_NEW_SOURCE_UQ = "uq_kb_sources_tenant_id_name_version"
_OLD_ROUTE_UQ = "uq_engine_kb_routes_source"
_NEW_ROUTE_UQ = "uq_engine_kb_routes_source_agent"
#: `SubmitIn.name`'s ceiling at this revision.
_NAME_MAX = 120

_COLLIDING = """
SELECT s.tenant_id, s.name, s.agent_id, a.name AS agent_name, min(s.created_at) AS first_at
FROM kb_sources s JOIN agents a ON a.id = s.agent_id
WHERE (s.tenant_id, s.name) IN (
  SELECT tenant_id, name FROM kb_sources WHERE agent_id IS NOT NULL
  GROUP BY tenant_id, name HAVING count(DISTINCT agent_id) > 1
)
GROUP BY s.tenant_id, s.name, s.agent_id, a.name
ORDER BY s.tenant_id, s.name, first_at, s.agent_id
"""


def _free_name(taken: set[str], base: str, agent_name: str) -> str:
    stem = f"{base} ({agent_name})"
    candidate = stem[:_NAME_MAX]
    counter = 2
    while candidate in taken:
        suffix = f" {counter}"
        candidate = f"{stem[: _NAME_MAX - len(suffix)]}{suffix}"
        counter += 1
    return candidate


def _rename_colliding(conn: sa.Connection) -> None:
    rows = conn.execute(sa.text(_COLLIDING)).all()
    names_by_tenant: dict[object, set[str]] = {}
    keeper: set[tuple[object, str]] = set()
    for tenant_id, name, agent_id, agent_name, _first in rows:
        if (tenant_id, name) not in keeper:
            # The oldest agent's source of this name keeps it.
            keeper.add((tenant_id, name))
            continue
        taken = names_by_tenant.get(tenant_id)
        if taken is None:
            taken = set(
                conn.execute(
                    sa.text("SELECT DISTINCT name FROM kb_sources WHERE tenant_id = :tid"),
                    {"tid": tenant_id},
                ).scalars()
            )
            names_by_tenant[tenant_id] = taken
        new_name = _free_name(taken, str(name), str(agent_name))
        taken.add(new_name)
        params = {"tid": tenant_id, "aid": agent_id, "old": name, "new": new_name}
        conn.execute(
            sa.text(
                "UPDATE kb_documents SET title = :new WHERE source_id IN ("
                "SELECT id FROM kb_sources WHERE tenant_id = :tid AND agent_id = :aid "
                "AND name = :old)"
            ),
            params,
        )
        conn.execute(
            sa.text(
                "UPDATE kb_sources SET name = :new, updated_at = now() "
                "WHERE tenant_id = :tid AND agent_id = :aid AND name = :old"
            ),
            params,
        )


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    op.alter_column("kb_sources", "agent_id", nullable=True)
    op.alter_column("kb_uploads", "agent_id", nullable=True)
    op.alter_column("kb_chunks", "agent_id", nullable=True)
    op.alter_column("kb_index_documents", "agent_id", nullable=True)

    op.execute("ALTER TABLE kb_sources NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_documents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_chunks NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    try:
        # Offline (`--sql`) there are no rows to find collisions in, so the renames are not
        # emitted; the unique constraint below is what refuses on a target that has any.
        if not probe_skipped_offline(
            "D-689: names colliding across one tenant's agents are renamed only online; "
            "uq_kb_sources_tenant_id_name_version refuses if any remain."
        ):
            _rename_colliding(op.get_bind())
        op.execute("UPDATE kb_chunks SET agent_id = NULL WHERE agent_id IS NOT NULL")
    finally:
        op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_chunks FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_documents FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_sources FORCE ROW LEVEL SECURITY")

    op.drop_constraint(_OLD_SOURCE_UQ, "kb_sources", type_="unique")
    op.create_unique_constraint(_NEW_SOURCE_UQ, "kb_sources", ["tenant_id", "name", "version"])
    op.drop_constraint(_OLD_ROUTE_UQ, "engine_kb_routes", type_="unique")
    op.create_unique_constraint(_NEW_ROUTE_UQ, "engine_kb_routes", ["source_id", "agent_id"])


_TENANT_FIRST_AGENT = (
    "(SELECT a.id FROM agents a WHERE a.tenant_id = {alias}.tenant_id "
    "ORDER BY a.deleted_at IS NOT NULL, a.created_at, a.id LIMIT 1)"
)


def downgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '3s'")
    if probe_skipped_offline(
        "D-689 downgrade: the refusals for fanned-out claims and agentless tenants are not "
        "checked offline; SET NOT NULL and the old unique constraint refuse instead."
    ):
        _downgrade_schema()
        return
    conn = op.get_bind()
    fanned = conn.execute(
        sa.text(
            "SELECT count(*) FROM (SELECT source_id FROM engine_kb_routes "
            "GROUP BY source_id HAVING count(*) > 1) many"
        )
    ).scalar()
    if fanned:
        raise RuntimeError(
            f"{fanned} knowledge source(s) are attached to more than one agent's vendor "
            "copy; the previous schema allows one. Withdraw them before downgrading."
        )
    op.execute("ALTER TABLE kb_sources NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_uploads NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_chunks NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE kb_index_documents NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE agents NO FORCE ROW LEVEL SECURITY")
    try:
        orphaned = conn.execute(
            sa.text(
                "SELECT count(*) FROM kb_sources s WHERE s.agent_id IS NULL AND NOT EXISTS "
                "(SELECT 1 FROM agents a WHERE a.tenant_id = s.tenant_id)"
            )
        ).scalar()
        if orphaned:
            raise RuntimeError(
                f"{orphaned} knowledge source(s) belong to a client with no agent; the "
                "previous schema needs one. Delete them or create an agent first."
            )
        op.execute(
            "UPDATE kb_sources s SET agent_id = "
            + _TENANT_FIRST_AGENT.format(alias="s")
            + " WHERE s.agent_id IS NULL"
        )
        op.execute(
            "UPDATE kb_uploads u SET agent_id = s.agent_id FROM kb_sources s "
            "WHERE s.id = u.source_id AND u.agent_id IS NULL"
        )
        op.execute(
            "UPDATE kb_chunks c SET agent_id = s.agent_id FROM kb_sources s "
            "WHERE s.id = c.source_id AND c.agent_id IS NULL"
        )
        op.execute(
            "UPDATE kb_index_documents x SET agent_id = "
            + _TENANT_FIRST_AGENT.format(alias="x")
            + " WHERE x.agent_id IS NULL"
        )
    finally:
        op.execute("ALTER TABLE agents FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_index_documents FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_chunks FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_uploads FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE kb_sources FORCE ROW LEVEL SECURITY")
    _downgrade_schema()


def _downgrade_schema() -> None:
    op.drop_constraint(_NEW_ROUTE_UQ, "engine_kb_routes", type_="unique")
    op.create_unique_constraint(_OLD_ROUTE_UQ, "engine_kb_routes", ["source_id"])
    op.drop_constraint(_NEW_SOURCE_UQ, "kb_sources", type_="unique")
    op.create_unique_constraint(_OLD_SOURCE_UQ, "kb_sources", ["agent_id", "name", "version"])
    op.alter_column("kb_index_documents", "agent_id", nullable=False)
    op.alter_column("kb_chunks", "agent_id", nullable=False)
    op.alter_column("kb_uploads", "agent_id", nullable=False)
    op.alter_column("kb_sources", "agent_id", nullable=False)
