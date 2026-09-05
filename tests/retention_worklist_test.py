"""D-368: a tenant whose only expirable data is a knowledge source is inside the sweep.

THE DEFECT, in the words a compliance reviewer would use. Every retention period this
platform sells is enforced by one nightly job, and that job's worklist came from
`engine_agent_routes` — a table written only when an agent is PUBLISHED. D-179 then made
knowledge expirable, and a knowledge source is the one expirable artefact a tenant can
hold without ever publishing anything: upload a document, have an operator reject it, and
the tenant has a `kb_sources` row that `_KB_EXPIRABLE` matches, a `kb` policy at 365 days,
and no route. Its sweep never ran, for ever. Retention is a DPDP obligation, so that is a
compliance failure and not a backlog item — and nothing in the suite caught it, because
every retention test reached its tenant through a published agent.

Measured on the development database before the fix: **353 tenants held knowledge sources
and had no `engine_agent_routes` row**, i.e. were outside every sweep the platform had ever
run.

The closure is `retention_worklist` (migration b2e6f10c94d7): a global table holding one
tenant id, one reason from a CHECK that mirrors `compliance.models.
RETENTION_WORKLIST_REASONS` (one value today) and one timestamp — maintained by a TRIGGER
on `kb_sources`, so the invariant holds for every writer of that table rather than for the
call sites that remember it, and BACKFILLED, because a trigger only reaches forward.

What this file holds, in the order a reviewer asks it:

1. the compliance sentence itself — such a tenant is in the worklist and its data really
   does expire;
2. that the trigger, not a service function, is what puts it there;
3. hard rule 1: the new table is globally READABLE and tenant-scoped for writes, and one
   tenant cannot register, retire or re-tenant another's entry.

Run: uv run pytest -q tests/retention_worklist_test.py
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.compliance.models import RETENTION_WORKLIST_REASONS
from apps.api.db.session import tenant_session, untenanted_session
from apps.workers.retention import _due_tenants, sweep_tenant, sweep_tenants
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError
from tests.conftest import accept_agreements

_REASON = "kb_source"


async def _unpublished_tenant() -> tuple[uuid.UUID, uuid.UUID]:
    """A tenant with the shipped retention defaults, an agent, and NO published agent.

    `create_organization` mints the agent row and the six `retention_policies` rows; what
    it deliberately does not do is publish, so no `engine_agent_routes` row exists. That
    is the exact state the hole lived in — a live client mid-onboarding, not a churned one.
    """
    created = await admin_service.create_organization(
        name="Unpublished Uploads",
        slug=f"rw-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


async def _rejected_source(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, *, days_ago: int
) -> tuple[uuid.UUID, uuid.UUID]:
    """One REJECTED knowledge source and its chunk, aged. Returns (source, document).

    Written directly rather than through `kb/service`, for `kb_retention_test`'s reason:
    the property under test is what happens to a document that has sat rejected for longer
    than the tenant's `kb` period, and the service always writes `now()`.
    """
    source_id, document_id = uuid.uuid4(), uuid.uuid4()
    when = datetime.now(UTC) - timedelta(days=days_ago)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, status, version, "
                "is_active, created_at, updated_at) VALUES (:id, :t, :a, 'text', :name, "
                "'rejected', 1, false, :w, :w)"
            ),
            {
                "id": source_id,
                "t": tenant_id,
                "a": agent_id,
                # Unique per source: `uq_kb_sources_agent_id_name_version` means one
                # agent cannot hold two sources of the same name at the same version.
                "name": f"Price list (refused) {uuid.uuid4().hex[:6]}",
                "w": when,
            },
        )
        await session.execute(
            text(
                "INSERT INTO kb_documents (id, tenant_id, source_id, idx, title, content, meta, "
                "created_at, updated_at) VALUES (:id, :t, :s, 0, 'Price list', :body, "
                "CAST(:meta AS jsonb), :w, :w)"
            ),
            {
                "id": document_id,
                "t": tenant_id,
                "s": source_id,
                "body": "Consultation 500. Dr Anitha sees patients Mon-Fri.",
                "meta": json.dumps({}),
                "w": when,
            },
        )
    return source_id, document_id


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """The `engine_agent_routes` row `publish_agent` writes — the OTHER half of the
    worklist, so a tenant named by both halves can be exercised."""
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": f"fakeagent_rw_{uuid.uuid4().hex[:8]}", "t": tenant_id, "a": agent_id},
        )


async def _worklist(tenant_id: uuid.UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT reason FROM retention_worklist WHERE tenant_id = :t ORDER BY reason"),
                {"t": tenant_id},
            )
        ).scalars()
        return [str(row) for row in rows]


# --- 1. the compliance sentence ----------------------------------------------


async def test_a_tenant_with_only_a_rejected_source_is_in_the_sweeps_worklist() -> None:
    """THE DEFECT. Before this, such a tenant appeared in no worklist and its nightly
    sweep never ran — not once, not late, never."""
    tenant_id, agent_id = await _unpublished_tenant()
    await _rejected_source(tenant_id, agent_id, days_ago=400)

    async with untenanted_session() as session:
        routed = (
            await session.execute(
                text("SELECT count(*) FROM engine_agent_routes WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
    assert routed == 0, "the fixture must be a tenant the OLD worklist could not reach"

    assert tenant_id in await _due_tenants()


async def test_and_the_sweep_actually_forgets_the_document() -> None:
    """The worklist is only half the sentence: a tenant that is reachable and whose data
    still does not expire is no better off. End to end, because each link has been true on
    its own while the chain was not — which is exactly how this defect survived."""
    tenant_id, agent_id = await _unpublished_tenant()
    source_id, document_id = await _rejected_source(tenant_id, agent_id, days_ago=400)

    counts = await sweep_tenant(tenant_id)

    assert counts["kb_versions"] == 1, counts
    async with tenant_session(tenant_id) as session:
        remaining_source = (
            await session.execute(text("SELECT 1 FROM kb_sources WHERE id = :i"), {"i": source_id})
        ).first()
        remaining_document = (
            await session.execute(
                text("SELECT 1 FROM kb_documents WHERE id = :i"), {"i": document_id}
            )
        ).first()
    assert remaining_source is None, "the source row carries the name the client typed"
    assert remaining_document is None, "and the chunk carries what they uploaded"


async def test_a_tenant_holding_nothing_expirable_is_still_not_swept() -> None:
    """The cost side. This closure must not become the per-tenant fan-out D-57 and P6.2
    removed — a tenant with no calls and no knowledge stays out of the nightly walk."""
    tenant_id, _ = await _unpublished_tenant()
    assert tenant_id not in await _due_tenants()


# --- 2. what maintains it -----------------------------------------------------


async def test_the_trigger_registers_the_tenant_not_a_service_function() -> None:
    """The fixture above writes `kb_sources` with raw SQL and never calls `kb/service`, so
    the row in the worklist can only have come from the database. That is the design: the
    invariant holds for writers nobody has written yet, and for an operator inserting by
    hand during an incident.
    """
    tenant_id, agent_id = await _unpublished_tenant()
    assert await _worklist(tenant_id) == []

    await _rejected_source(tenant_id, agent_id, days_ago=10)

    assert await _worklist(tenant_id) == [_REASON]


async def test_a_second_source_does_not_add_a_second_row() -> None:
    """It is an index, not a log. A tenant that uploads a hundred documents is one row,
    or the worklist becomes the cost shape it exists to avoid."""
    tenant_id, agent_id = await _unpublished_tenant()
    await _rejected_source(tenant_id, agent_id, days_ago=10)
    await _rejected_source(tenant_id, agent_id, days_ago=20)

    assert await _worklist(tenant_id) == [_REASON]


async def test_a_tenant_in_both_sources_of_the_worklist_is_swept_once() -> None:
    """The normal case, and the one the UNION is for: nearly every tenant that holds
    knowledge ALSO has a published agent, so it is named by both halves of `_due_tenants`.

    `UNION`, not `UNION ALL`. The sweep is idempotent per tenant, so a doubled entry would
    not corrupt anything — it would silently double the tick's cost and make the "tenants
    swept" figure the log prints untrue, which is how a cost regression hides.
    """
    tenant_id, agent_id = await _unpublished_tenant()
    await _publish(tenant_id, agent_id)
    await _rejected_source(tenant_id, agent_id, days_ago=10)

    assert await _worklist(tenant_id) == [_REASON]
    assert [t for t in await _due_tenants() if t == tenant_id] == [tenant_id]


async def test_registration_survives_the_source_being_swept() -> None:
    """Deliberate, and worth pinning because the opposite is tempting. The sweep deleting
    a tenant's last expired source must not evict it from the worklist: the tenant may
    upload again tomorrow, and a worklist that empties itself would reopen the hole one
    successful sweep at a time.
    """
    tenant_id, agent_id = await _unpublished_tenant()
    await _rejected_source(tenant_id, agent_id, days_ago=400)
    await sweep_tenant(tenant_id)

    assert await _worklist(tenant_id) == [_REASON]
    assert tenant_id in await _due_tenants()


async def test_a_reason_outside_the_vocabulary_is_refused() -> None:
    """The CHECK is what keeps the table self-describing. A free-text reason column is one
    nobody can enumerate, and the point of the column is that a reader can."""
    tenant_id, _ = await _unpublished_tenant()
    with pytest.raises(IntegrityError):
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("INSERT INTO retention_worklist (tenant_id, reason) VALUES (:t, 'whatever')"),
                {"t": tenant_id},
            )


# --- 3. hard rule 1 -----------------------------------------------------------


async def test_a_tenant_session_sees_only_the_rows_it_may_see_and_the_worker_sees_all() -> None:
    """The cross-tenant zero-rows check hard rule 1 requires of any new tenant-scoped
    table — with the asymmetry this table exists for stated in the same test.

    The READ is global from an untenanted session, because a worker with no session is
    what has to ask "which tenants hold expirable data" across all of them. That is the
    exemption, and it is why the table holds a tenant id and a reason from a closed
    vocabulary and nothing else.
    """
    first, first_agent = await _unpublished_tenant()
    second, second_agent = await _unpublished_tenant()
    await _rejected_source(first, first_agent, days_ago=10)
    await _rejected_source(second, second_agent, days_ago=10)

    async with tenant_session(first) as session:
        visible = (
            await session.execute(
                text("SELECT tenant_id FROM retention_worklist WHERE tenant_id = :t"),
                {"t": second},
            )
        ).all()
    assert visible == [], "a tenant session must not read another tenant's worklist entry"

    async with untenanted_session() as session:
        globally = (
            await session.execute(
                text("SELECT count(*) FROM retention_worklist WHERE tenant_id IN (:a, :b)"),
                {"a": first, "b": second},
            )
        ).scalar()
    assert globally == 2, "and the worker's untenanted read still sees both"


async def test_a_tenant_cannot_register_retire_or_re_tenant_another_tenants_entry() -> None:
    """The half `c4b70e928a1f` had to add to `engine_agent_routes` after the fact: an
    exemption written for a READ was being applied to every verb, and a session scoped to
    tenant A could silence or steal tenant B's row. This table ships with the asymmetry
    rather than acquiring it, so the three verbs are checked here on the day it lands.

    A DELETE or UPDATE that MATCHES NOTHING is the correct refusal under RLS — the policy
    filters the rows out of the statement's view, so the write is a no-op rather than an
    error. The INSERT is the one that raises, because a row it cannot see is a row it
    cannot create either.
    """
    victim, victim_agent = await _unpublished_tenant()
    attacker, _ = await _unpublished_tenant()
    await _rejected_source(victim, victim_agent, days_ago=10)

    async with tenant_session(attacker) as session:
        with pytest.raises((IntegrityError, DBAPIError)):
            await session.execute(
                text("INSERT INTO retention_worklist (tenant_id, reason) VALUES (:t, :r)"),
                {"t": victim, "r": _REASON},
            )

    async with tenant_session(attacker) as session:
        deleted = await session.execute(
            text("DELETE FROM retention_worklist WHERE tenant_id = :t"), {"t": victim}
        )
        assert deleted.rowcount == 0
        stolen = await session.execute(
            text("UPDATE retention_worklist SET tenant_id = :a WHERE tenant_id = :v"),
            {"a": attacker, "v": victim},
        )
        assert stolen.rowcount == 0

    assert await _worklist(victim) == [_REASON], "the victim is still in the sweep's reach"


async def test_the_ops_arm_can_read_and_cannot_write() -> None:
    """The narrowing this table chose over its neighbours, pinned so it survives.

    `engine_agent_routes` and `dnc_list` both let an UNTENANTED session write any row —
    the ops/worker arm — because ops paths really do write them. Nothing writes this one
    from outside a tenant session: the trigger runs inside the tenant's own, and the
    migration's backfill runs before RLS is enabled at all. So the sessionless arm is
    SELECT and nothing else, and a future widening back to the neighbours' shape has to
    turn this test red first.
    """
    tenant_id, agent_id = await _unpublished_tenant()
    await _rejected_source(tenant_id, agent_id, days_ago=10)

    async with untenanted_session() as session:
        assert await _worklist(tenant_id) == [_REASON]
        with pytest.raises((IntegrityError, DBAPIError)):
            await session.execute(
                text("INSERT INTO retention_worklist (tenant_id, reason) VALUES (:t, :r)"),
                {"t": tenant_id, "r": _REASON},
            )

    async with untenanted_session() as session:
        removed = await session.execute(
            text("DELETE FROM retention_worklist WHERE tenant_id = :t"), {"t": tenant_id}
        )
        assert removed.rowcount == 0, "a sessionless DELETE must not be able to empty it"

    assert await _worklist(tenant_id) == [_REASON]


# --- 4. two properties recovered from the abandoned branch `agent/findings-close` ----
#
# That branch closed D-368 independently and was never merged. Its design is superseded by
# this one — it paid for the cross-tenant read with a third `RLS_EXEMPT_TENANT_COLUMNS`
# entry, where this table needs none — but two of its assertions have no equivalent above
# and are true of THIS design too, so they are recovered rather than dropped.


async def test_the_worklist_is_what_the_sweep_actually_iterates() -> None:
    """THE JOIN, and it is the link this defect lived in.

    The two tests at the top of this file are each one half: "the tenant is in
    `_due_tenants()`" and "`sweep_tenant()` expires its document". Both were TRUE
    INDIVIDUALLY while the chain between them was broken for the whole life of the
    defect — the arm always worked and the list never named the tenant — so asserting the
    halves separately is asserting exactly the thing that did not catch it.

    This runs the resolution step and the sweeping step through the entry point the cron
    uses, `sweep_tenants`, fed from `_due_tenants()` rather than from an id the test
    already holds. Filtered to our own tenant on purpose: `apply_retention` would sweep
    every tenant on the development database (353 hold knowledge sources), which buys no
    extra proof and makes a nightly-cost regression look like a slow test.
    """
    tenant_id, agent_id = await _unpublished_tenant()
    source_id, document_id = await _rejected_source(tenant_id, agent_id, days_ago=400)

    resolved = [t for t in await _due_tenants() if t == tenant_id]
    assert resolved == [tenant_id], "the worklist did not name the tenant — nothing follows"
    totals = await sweep_tenants(resolved)

    assert totals["kb_versions"] == 1, totals
    assert totals.get("tenants_failed", 0) == 0, totals
    async with tenant_session(tenant_id) as session:
        remaining_source = (
            await session.execute(text("SELECT 1 FROM kb_sources WHERE id = :i"), {"i": source_id})
        ).first()
        remaining_document = (
            await session.execute(
                text("SELECT 1 FROM kb_documents WHERE id = :i"), {"i": document_id}
            )
        ).first()
    assert remaining_source is None, "the source the resolved worklist named was not expired"
    assert remaining_document is None, "and its chunk is what actually held the client's text"


async def test_the_table_holds_a_tenant_a_reason_and_an_instant_and_nothing_else() -> None:
    """The shape is a test, not a promise.

    Every argument this table rests on is "there is nothing in it worth reading" — which
    is what lets `retention_worklist_ops_read` hand EVERY row to any session with no
    tenant GUC. A column named `source_name`, `uri` or `title` added by some later
    migration would turn that read into a cross-tenant leak of client content without
    touching a line of the model docstring making the argument.

    The reason vocabulary is pinned in the same test because the two facts are one
    argument: a tag from a closed list is safe to hand out precisely because it cannot
    carry a name.
    """
    async with untenanted_session() as session:
        columns = {
            str(row[0])
            for row in (
                await session.execute(
                    text(
                        "SELECT a.attname FROM pg_class c "
                        "JOIN pg_namespace n ON n.oid = c.relnamespace "
                        "JOIN pg_attribute a ON a.attrelid = c.oid "
                        "WHERE n.nspname = 'public' AND c.relname = 'retention_worklist' "
                        "AND a.attnum > 0 AND NOT a.attisdropped"
                    )
                )
            ).all()
        }

    assert columns == {"tenant_id", "reason", "registered_at"}, (
        f"retention_worklist grew or lost a column ({sorted(columns)}). Every row of it is "
        "readable from any session with no tenant GUC, so anything here that names client "
        "content is a leak the model's own argument does not cover."
    )
    # THE SECOND REASON ARRIVED, and this pin is what made it cost a visible diff — which
    # is what it was for. `copilot_memory` (migration d4a9c17e6b02) is the in-app
    # assistant's memory: a tenant can hold one with no published agent, exactly as it can
    # hold a rejected knowledge source, so `engine_agent_routes` cannot name it either.
    # Same hole, same feeder, one shared trigger function taking the reason as `TG_ARGV[0]`
    # rather than a second near-identical one.
    #
    # THE COLUMN ASSERTION ABOVE IS WHAT KEEPS THIS SAFE AS THE LIST GROWS: every row here
    # is readable from a session with no tenant GUC, and what a second reason adds is one
    # more tenant_id — never a word of client content.
    assert RETENTION_WORKLIST_REASONS == (_REASON, "copilot_memory"), (
        "a new reason is a new feeder and a new CHECK value — update the model, the "
        "migration and then this pin"
    )
