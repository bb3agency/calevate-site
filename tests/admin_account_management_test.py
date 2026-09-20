"""The three account-management surfaces added for the operator console, held to the
properties that would be expensive to lose.

1. **The client directory is a PAGE of a filtered set.** `GET /v1/admin/tenants` used to
   answer with every account on the platform, and `admin.service.tenant_overview` said in
   its own docstring that paging it was the escape it could not take alone. It pages now,
   and the three things that can silently go wrong with a paged list are asserted here:
   the total must count the FILTERED set (a console that says "312 results" and shows four
   has lied about the search), the order must be total (`created_at` is not unique, so a
   page boundary inside a tie can show one account twice and hide another), and the search
   must treat `%` as a character rather than as "every client we have".

2. **Readiness for an account the operator is NOT impersonating.** The property that
   matters is that it is the SAME answer the client's own screen gives — asserted against
   `legal.readiness.readiness_rows` directly, because a route that re-derived the verdict
   would pass any test written only against the route.

3. **The activity trail is this account's ledger and only this account's.** `audit_log` is
   NOT tenant-RLS'd — that is deliberate and documented — so nothing in the database stops
   a mistake in the WHERE clause leaking one client's history into another's screen. This
   file pins it from both directions.

CONCURRENCY: every case mints its own tenants and asserts only on those, so this runs
beside the other suites on the shared Postgres. The directory cases filter by a status no
other suite writes rather than by counting rows.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, get_args
from uuid import UUID

import pytest
from apps.api.admin import routes as admin_routes
from apps.api.admin import service as admin_service
from apps.api.compliance.audit import write_audit
from apps.api.core.context import Principal
from apps.api.core.loadshed import get_platform_status
from apps.api.db.session import admin_session, tenant_session
from apps.api.legal.readiness import ROW_COPY, readiness_rows
from apps.api.main import app
from apps.api.tenancy.models import ORG_STATUSES, PLAN_TIERS
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


async def _operator() -> tuple[UUID, dict[str, str]]:
    """A live operator and the header that authenticates as them."""
    admin_id = uuid.uuid4()
    async with admin_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops Anand', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )
    return admin_id, {"Authorization": f"Bearer dev:admin:{admin_id}"}


async def _tenant(name: str, *, slug: str, status: str | None = None) -> UUID:
    created = await admin_service.create_organization(
        name=name,
        slug=slug,
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    if status is not None:
        # The TENANT's own session: `app.admin` widens `USING` on `organizations` and no
        # `WITH CHECK` anywhere, so an UPDATE through it is refused by RLS.
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE organizations SET status = :s WHERE id = :t"),
                {"s": status, "t": tenant_id},
            )
    return tenant_id


async def _get(path: str, headers: dict[str, str]) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.get(path, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ============================================================================
# 1. The directory: filters, totals, order
# ============================================================================


def test_the_filter_literals_are_the_columns_they_filter() -> None:
    """A status added to the CHECK constraint and not to the filter is unsearchable, and
    nothing else in the build would say so — the route would simply 422 a value the
    database happily stores. `Literal` cannot be built from a runtime tuple and still be a
    type, so this is the join between the two spellings."""
    assert get_args(admin_routes.OrgStatusFilter) == ORG_STATUSES
    assert get_args(admin_routes.PlanTierFilter) == PLAN_TIERS


async def test_search_matches_name_and_slug_and_treats_wildcards_as_text() -> None:
    marker = uuid.uuid4().hex[:10]
    by_name = await _tenant(f"Sunrise {marker} Clinic", slug=f"sun-{marker}")
    by_slug = await _tenant("Wholly Unrelated Motors", slug=f"slugonly-{marker}")
    _, headers = await _operator()

    found = await _get(f"/v1/admin/tenants?q={marker}", headers=headers)
    ids = {row["id"] for row in found["rows"]}
    assert {str(by_name), str(by_slug)} <= ids
    assert found["total"] == len(found["rows"]) == 2, found

    # `%` is a character an operator can type, not a request for the whole platform. Left
    # unescaped this returns every account on the instance, which is the failure mode that
    # makes a search box feel broken rather than empty.
    wild = await _get("/v1/admin/tenants?q=%25", headers=headers)
    assert wild["total"] == 0, "a literal percent sign matched something"


async def test_the_total_counts_the_filtered_set_and_the_page_is_a_window_onto_it() -> None:
    """The three properties of a paged list, in one test because they are one behaviour.

    Walking the pages must produce every account exactly once: `created_at` is not unique
    and neither is `lower(name)`, so an order without a tiebreak can repeat a row on one
    page and drop another — the classic paging defect, and invisible until a client
    complains they are missing from the console.
    """
    marker = uuid.uuid4().hex[:10]
    minted = {
        str(await _tenant(f"Paged {marker} {n}", slug=f"paged-{marker}-{n}")) for n in range(5)
    }
    _, headers = await _operator()

    first = await _get(f"/v1/admin/tenants?q={marker}&limit=2", headers=headers)
    assert first["total"] == 5, "the total must count the matches, not the page"
    assert first["limit"] == 2 and first["offset"] == 0
    assert len(first["rows"]) == 2

    walked: list[str] = []
    for offset in (0, 2, 4):
        page = await _get(f"/v1/admin/tenants?q={marker}&limit=2&offset={offset}", headers=headers)
        walked.extend(row["id"] for row in page["rows"])

    assert len(walked) == len(set(walked)) == 5, f"the walk repeated or dropped a row: {walked}"
    assert set(walked) == minted


async def test_status_and_plan_tier_narrow_and_an_unknown_sort_is_refused() -> None:
    marker = uuid.uuid4().hex[:10]
    suspended = await _tenant(f"Halted {marker}", slug=f"halt-{marker}", status="suspended")
    await _tenant(f"Running {marker}", slug=f"run-{marker}", status="active")
    _, headers = await _operator()

    narrowed = await _get(f"/v1/admin/tenants?q={marker}&status=suspended", headers=headers)
    assert [row["id"] for row in narrowed["rows"]] == [str(suspended)]
    assert narrowed["total"] == 1

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        refused = await http.get(
            "/v1/admin/tenants?sort=; DROP TABLE organizations", headers=headers
        )
    assert refused.status_code == 422, (
        "an unknown sort must be refused by name: the fragment is interpolated into SQL, "
        "and a caller who can choose it silently is a caller who can choose the ORDER BY"
    )


# ============================================================================
# 2. Readiness, for an account nobody is impersonating
# ============================================================================


async def test_readiness_is_the_same_verdict_the_client_sees() -> None:
    tenant_id = await _tenant("Readiness Dental", slug=f"ready-{uuid.uuid4().hex[:8]}")
    _, headers = await _operator()

    async with tenant_session(tenant_id) as session:
        expected = await readiness_rows(
            session, tenant_id=tenant_id, platform=await get_platform_status()
        )

    body = await _get(f"/v1/admin/tenants/{tenant_id}/readiness", headers=headers)

    assert [row["rule"] for row in body["rows"]] == [row.rule for row in expected], (
        "the operator's readiness screen and the client's own must name the same "
        "conditions — a second derivation is two answers that disagree on the day it "
        "matters"
    )
    assert body["may_operate"] is (not expected)
    assert body["blocked_on_calevate"] == sum(1 for row in expected if row.actor == "calevate")
    # A fresh account has not accepted its agreements, so there is something to report —
    # without this the assertions above would also pass against an empty list.
    assert body["rows"], "a brand-new account should be blocked on something"
    assert all(row["reason"] and row["next_step"] for row in body["rows"])


async def test_readiness_refuses_an_account_that_is_not_there() -> None:
    _, headers = await _operator()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.get(f"/v1/admin/tenants/{uuid.uuid4()}/readiness", headers=headers)
    assert response.status_code == 404, response.text


async def test_reading_readiness_is_itself_in_the_ledger() -> None:
    """SEC-COMP §5 / D-482 L-1: an admin read of one client's own state is recorded."""
    tenant_id = await _tenant("Audited Read Clinic", slug=f"audr-{uuid.uuid4().hex[:8]}")
    admin_id, headers = await _operator()

    await _get(f"/v1/admin/tenants/{tenant_id}/readiness", headers=headers)

    async with admin_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log "
                    "WHERE tenant_id = :t AND actor_id = :a AND action = 'admin.tenant_read'"
                ),
                {"t": tenant_id, "a": admin_id},
            )
        ).all()
    assert rows, "the read was not recorded"


# ============================================================================
# 3. The activity trail
# ============================================================================


async def _audit(tenant_id: UUID, *, actor_id: UUID, action: str) -> None:
    async with admin_session() as session:
        await write_audit(
            session,
            action=action,
            actor=Principal(
                user_id=actor_id,
                tenant_id=tenant_id,
                role="operator",
                realm="admin",
            ),
            tenant_id=tenant_id,
            object_type="organization",
            object_id=str(tenant_id),
        )


async def test_the_trail_is_this_account_and_names_the_operator_who_acted() -> None:
    mine = await _tenant("Trail Clinic", slug=f"trail-{uuid.uuid4().hex[:8]}")
    theirs = await _tenant("Other Clinic", slug=f"other-{uuid.uuid4().hex[:8]}")
    admin_id, headers = await _operator()

    await _audit(mine, actor_id=admin_id, action="admin.plan_tier_changed")
    await _audit(theirs, actor_id=admin_id, action="admin.plan_tier_changed")

    body = await _get(f"/v1/admin/tenants/{mine}/activity", headers=headers)
    actions = [entry["action"] for entry in body["entries"]]

    assert "admin.plan_tier_changed" in actions
    assert body["entries"][0]["actor_label"] == "Ops Anand", (
        "the trail must name the operator: 'somebody with this uuid changed the plan' is "
        "not an answer a support call can use"
    )
    assert all(entry["actor_type"] in {"admin", "user", "system"} for entry in body["entries"])

    # The isolation property. `audit_log` carries no RLS policy — by design, because the
    # admin realm reads it cross-tenant — so the WHERE clause is the ONLY thing keeping
    # one client's history off another client's screen.
    other = await _get(f"/v1/admin/tenants/{theirs}/activity", headers=headers)
    assert {entry["id"] for entry in body["entries"]}.isdisjoint(
        {entry["id"] for entry in other["entries"]}
    )


async def test_the_trail_is_newest_first_and_pages() -> None:
    tenant_id = await _tenant("Paged Trail", slug=f"ptrail-{uuid.uuid4().hex[:8]}")
    admin_id, headers = await _operator()
    for n in range(4):
        await _audit(tenant_id, actor_id=admin_id, action=f"admin.thing_{n}")

    page = await _get(f"/v1/admin/tenants/{tenant_id}/activity?limit=2", headers=headers)
    assert page["total"] >= 4
    assert len(page["entries"]) == 2
    stamps = [entry["at"] for entry in page["entries"]]
    assert stamps == sorted(stamps, reverse=True), "an activity trail reads newest first"

    filtered = await _get(
        f"/v1/admin/tenants/{tenant_id}/activity?actor_type=user", headers=headers
    )
    assert filtered["entries"] == [], "no client-side actor has touched this account"


@pytest.mark.parametrize("limit", [0, 201])
async def test_the_trail_page_is_bounded(limit: int) -> None:
    """The bound is on WORK, not on taste: `audit_log` is the fastest-growing table here."""
    tenant_id = await _tenant("Bounded Trail", slug=f"btrail-{uuid.uuid4().hex[:8]}")
    _, headers = await _operator()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        response = await http.get(
            f"/v1/admin/tenants/{tenant_id}/activity?limit={limit}", headers=headers
        )
    assert response.status_code == 422


# ============================================================================
# The console's rule vocabulary is the gates' own
# ============================================================================


#: The readiness screen's rule → remedy-screen table, as a path.
_RULE_SCREENS_TSX = (
    Path(__file__).resolve().parents[1]
    / "apps/web/src/app/admin/tenants/[tenantId]/readiness/page.tsx"
)


def test_the_console_links_remedies_by_rule_names_the_gates_really_emit() -> None:
    """The readiness screen maps a rule name to the screen that clears it. A key that is
    not a rule is a row that silently loses its link — and this test exists because the
    first draft of that table carried `spend_capped` and `account_stopped`, neither of
    which any gate has ever emitted (`spend_cap` and `account_closed` do).

    Asserted from Python across the language boundary because that is where the truth is:
    `ROW_COPY` is keyed by the same names and is itself checked against the gates' emitted
    vocabulary. The generated API client cannot close this one — the rule set is an open
    `str` on the wire, deliberately, so a screen never drops a blocker it has no word for.
    """
    source = _RULE_SCREENS_TSX.read_text()
    block = source[
        source.index("const RULE_SCREENS") : source.index(
            "\n};", source.index("const RULE_SCREENS")
        )
    ]
    keys = set(re.findall(r"^  ([a-z_]+): \{", block, re.MULTILINE))

    assert keys, "the remedy table could not be read — has it been renamed?"
    unknown = keys - set(ROW_COPY)
    assert not unknown, (
        f"these are not readiness rules, so their rows lose their remedy link: {sorted(unknown)}. "
        f"The rules this screen can receive are {sorted(ROW_COPY)}."
    )
