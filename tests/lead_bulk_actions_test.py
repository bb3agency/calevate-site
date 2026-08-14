"""Bulk actions on the leads table (SURFACES §2, "with the researched guardrails").

What this file exists to pin is not "many rows moved". It is the four things a bulk
action gets wrong, each of which is invisible on a screen that shows a tick:

1. **Which set.** "Select all" meaning the visible page and "select all" meaning the
   whole filtered query are different actions over sets that differ by orders of
   magnitude on a table with facets. `POST /v1/leads/bulk` refuses to guess: `scope` has
   no default, and the response ECHOES the scope and the count so the sentence on screen
   is the server's answer rather than the screen's assumption.
2. **Partial failure.** A batch where three of ten rows could not move must NAME them.
   `failures[]` carries `(lead_id, rule, reason)` — the same pair `BlockerOut` and
   `CallLeadOut.blocked_rule` already use — and the count buckets never fold a failure
   into a success.
3. **Already-there is not a failure.** D-65: the caller's intent already holds, so it is
   `unchanged`, a success bucket of its own. Reporting it as a failure would make the
   most ordinary bulk outcome — re-running over a partly-overlapping set — look like an
   incident.
4. **The cap is a refusal, not a truncation.** Doing the first 500 of 5,000 and answering
   200 is the exact defect the whole slice is about.

CONCURRENCY: every test mints its own organization and asserts only through tenant-scoped
reads, so this file runs beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import logging
import uuid

import httpx
import pytest
from apps.api.crm.schemas import MAX_BULK_LEADS
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.impersonation_grant_test import view_as_headers


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


def _headers(slug: str, token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _agent(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return uuid.UUID(
            str((await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar())
        )


async def _member(tenant_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        row = (await session.execute(text("SELECT user_id FROM memberships LIMIT 1"))).first()
    assert row is not None
    return uuid.UUID(str(row[0]))


async def _seed_leads(
    tenant_id: uuid.UUID, count: int, *, status: str = "new", data: str = "{}"
) -> list[uuid.UUID]:
    """`count` extra leads, in a stable order, so a test can talk about "the first three"."""
    agent_id = await _agent(tenant_id)
    ids = [uuid.uuid4() for _ in range(count)]
    async with tenant_session(tenant_id) as session:
        for index, lead_id in enumerate(ids):
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, data, created_at, updated_at) VALUES (:i, :t, :a, :p, :n, 'manual', "
                    ":s, CAST(:d AS jsonb), now(), now())"
                ),
                {
                    "i": lead_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "p": f"+9197{uuid.uuid4().int % 100000000:08d}",
                    "n": f"Lead {index}",
                    "s": status,
                    "d": data,
                },
            )
    return ids


async def _publish_enum_field(tenant_id: uuid.UUID) -> None:
    """A newer extraction schema carrying an ENUM field, which is what a facet is made of.

    `_make_tenant`'s schema declares one TEXT field, and `crm.columns.facetable` offers
    only extraction ENUM columns — deliberately, so the facet rail is the client's own
    vocabulary and not every string a caller ever said. `lead_columns` reads the highest
    version, so publishing v2 is how a test gets a filterable field without a fixture
    change every other suite would have to absorb.
    """
    agent_id = await _agent(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) VALUES (:i, :t, :a, 2, CAST(:f AS jsonb), now(), now())"
            ),
            {
                "i": uuid.uuid4(),
                "t": tenant_id,
                "a": agent_id,
                "f": (
                    '[{"key": "budget_band", "label": "Budget band", "type": "enum", '
                    '"enum_values": ["under_20l", "over_50l"]}]'
                ),
            },
        )


async def _statuses(tenant_id: uuid.UUID, ids: list[uuid.UUID]) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT id, status FROM leads WHERE id = ANY(:ids)"), {"ids": ids}
            )
        ).all()
    by_id = {uuid.UUID(str(r[0])): str(r[1]) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


async def _event_count(tenant_id: uuid.UUID, lead_id: uuid.UUID, event_type: str) -> int:
    async with tenant_session(tenant_id) as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM lead_events WHERE lead_id = :l AND type = :t"),
                    {"l": lead_id, "t": event_type},
                )
            ).scalar()
            or 0
        )


# --- scope: the ticked rows ------------------------------------------------------


async def test_ids_scope_moves_exactly_the_ticked_rows_and_says_so() -> None:
    tenant_id, slug, token = await _make_tenant()
    ids = await _seed_leads(tenant_id, 4)
    ticked, untouched = ids[:2], ids[2:]

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={
                "scope": "ids",
                "ids": [str(i) for i in ticked],
                "action": "status",
                "status": "hot",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    # The scope and the count come back from the SERVER, so the screen's sentence is not
    # its own guess about what it asked for.
    assert body["scope"] == "ids"
    assert body["action"] == "status"
    assert (body["requested"], body["changed"], body["unchanged"]) == (2, 2, 0)
    assert body["failures"] == []
    assert await _statuses(tenant_id, ticked) == ["hot", "hot"]
    assert await _statuses(tenant_id, untouched) == ["new", "new"]


async def test_the_ids_scope_ignores_the_filter_query_string() -> None:
    """The ticked rows are the ticked rows.

    Intersecting them with a filter the person may have changed since ticking would
    silently drop rows from a set they had already confirmed — the same class of lie as
    acting on rows they cannot see. The screen's half of this contract (clear the
    selection when the lens moves) is asserted in `apps/web/tests/leadsBulk.test.tsx`.
    """
    tenant_id, slug, token = await _make_tenant()
    ids = await _seed_leads(tenant_id, 2, status="new")

    async with _client() as http:
        response = await http.post(
            # A filter that matches NONE of the ticked rows.
            "/v1/leads/bulk?status=won",
            headers=_headers(slug, token),
            json={
                "scope": "ids",
                "ids": [str(i) for i in ids],
                "action": "status",
                "status": "hot",
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 2
    assert await _statuses(tenant_id, ids) == ["hot", "hot"]


# --- scope: the whole filtered query ---------------------------------------------


async def test_filter_scope_moves_every_matching_lead_not_just_a_page() -> None:
    """The scope that makes this feature worth having, and the one that can go wrong
    quietly: the filtered set is routinely larger than the page the client is looking at."""
    tenant_id, slug, token = await _make_tenant()
    interested = await _seed_leads(tenant_id, 5, status="interested")
    others = await _seed_leads(tenant_id, 3, status="contacted")

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk?status=interested",
            headers=_headers(slug, token),
            json={"scope": "filter", "action": "status", "status": "hot"},
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["scope"] == "filter"
    assert (body["requested"], body["changed"]) == (5, 5)
    assert await _statuses(tenant_id, interested) == ["hot"] * 5
    assert await _statuses(tenant_id, others) == ["contacted"] * 3


async def test_the_filter_scope_reads_the_same_facets_the_table_does() -> None:
    """One lens across the screen, the file and this. A facet that narrowed the table and
    not the action would write to rows the client never saw."""
    tenant_id, slug, token = await _make_tenant()
    await _publish_enum_field(tenant_id)
    matching = await _seed_leads(tenant_id, 2, data='{"budget_band": "over_50l"}')
    other = await _seed_leads(tenant_id, 2, data='{"budget_band": "under_20l"}')

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk?f=budget_band%3Aover_50l",
            headers=_headers(slug, token),
            json={"scope": "filter", "action": "status", "status": "won"},
        )

    assert response.status_code == 200, response.text
    assert response.json()["requested"] == 2
    assert await _statuses(tenant_id, matching) == ["won", "won"]
    assert await _statuses(tenant_id, other) == ["new", "new"]


async def test_an_unknown_facet_is_refused_rather_than_widening_the_action() -> None:
    """Same asymmetry the list and the export make, and the stakes are higher here: a
    filter that silently did nothing would WIDEN the set this route writes to."""
    _tenant_id, slug, token = await _make_tenant()
    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk?f=not_a_field%3Ax",
            headers=_headers(slug, token),
            json={"scope": "filter", "action": "status", "status": "won"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/lead_filter_unknown_field")


# --- partial failure -------------------------------------------------------------


async def test_a_batch_with_unreachable_rows_names_them_and_still_moves_the_rest() -> None:
    """THE partial-failure case, and the one a green tick would hide.

    Three ids: one of ours, one soft-deleted, one belonging to another tenant. The two
    that cannot move are named individually with a machine rule and a sentence; the one
    that can, does. A response that reported `changed: 1` and nothing else would be
    describing a success over a request that was two-thirds refused.
    """
    tenant_id, slug, token = await _make_tenant()
    other_tenant, _other_slug, _ = await _make_tenant()
    mine = (await _seed_leads(tenant_id, 1))[0]
    removed = (await _seed_leads(tenant_id, 1))[0]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET deleted_at = now() WHERE id = :l"), {"l": removed}
        )
    async with tenant_session(other_tenant) as session:
        stranger = uuid.UUID(
            str((await session.execute(text("SELECT id FROM leads LIMIT 1"))).scalar())
        )

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={
                "scope": "ids",
                "ids": [str(mine), str(removed), str(stranger)],
                "action": "status",
                "status": "hot",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["requested"], body["changed"], body["unchanged"]) == (3, 1, 0)
    named = {f["lead_id"]: f for f in body["failures"]}
    assert set(named) == {str(removed), str(stranger)}, "a failed row was not named"
    for failure in named.values():
        # A machine code to switch on AND a sentence a person can act on — errors are
        # part of the interface, per-item as well as per-request.
        assert failure["rule"] == "not_found"
        assert failure["reason"].strip()
    # The buckets add up, which is what makes "3 of 3 succeeded" impossible to write.
    assert body["changed"] + body["unchanged"] + len(body["failures"]) == body["requested"]
    # RLS did its job: the neighbour's lead did not move, and no event was invented for it.
    assert await _statuses(other_tenant, [stranger]) == ["new"]
    assert await _event_count(other_tenant, stranger, "status_change") == 0


async def test_leads_already_in_the_target_state_are_unchanged_and_not_failures() -> None:
    """ "3 of the 10 were already hot" is the batch working, not a partial outage.

    This is D-65 arriving at the bulk path: the same `transition_status` the single-lead
    PATCH goes through, so the three answers do not have a second, worse implementation
    here. The timeline is the proof — no event for a lead that did not move.
    """
    tenant_id, slug, token = await _make_tenant()
    already = await _seed_leads(tenant_id, 3, status="hot")
    moving = await _seed_leads(tenant_id, 7, status="new")

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={
                "scope": "ids",
                "ids": [str(i) for i in already + moving],
                "action": "status",
                "status": "hot",
            },
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["requested"], body["changed"], body["unchanged"]) == (10, 7, 3)
    assert body["failures"] == []
    assert await _event_count(tenant_id, already[0], "status_change") == 0
    assert await _event_count(tenant_id, moving[0], "status_change") == 1


async def test_re_running_the_same_bulk_action_changes_nothing_and_says_so() -> None:
    """Why this route needs no `Idempotency-Key`: the write is already idempotent, and
    the response can prove it rather than merely claiming it."""
    tenant_id, slug, token = await _make_tenant()
    ids = [str(i) for i in await _seed_leads(tenant_id, 4)]
    body = {"scope": "ids", "ids": ids, "action": "status", "status": "won"}

    async with _client() as http:
        first = await http.post("/v1/leads/bulk", headers=_headers(slug, token), json=body)
        second = await http.post("/v1/leads/bulk", headers=_headers(slug, token), json=body)

    assert first.json()["changed"] == 4
    assert (second.json()["changed"], second.json()["unchanged"]) == (0, 4)


# --- bulk assignment --------------------------------------------------------------


async def test_bulk_assignment_sets_the_owner_and_records_one_event_each() -> None:
    tenant_id, slug, token = await _make_tenant()
    member = await _member(tenant_id)
    ids = await _seed_leads(tenant_id, 3)

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={
                "scope": "ids",
                "ids": [str(i) for i in ids],
                "action": "assign",
                "assign_to": str(member),
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 3
    assert await _event_count(tenant_id, ids[0], "assignment") == 1
    async with tenant_session(tenant_id) as session:
        owners = (
            await session.execute(
                text("SELECT DISTINCT assigned_to FROM leads WHERE id = ANY(:ids)"), {"ids": ids}
            )
        ).all()
    assert [uuid.UUID(str(r[0])) for r in owners] == [member]


async def test_bulk_unassignment_needs_an_explicit_null_and_an_absent_key_is_refused() -> None:
    """The null that a bulk action can least afford to read wrongly: an ABSENT `assign_to`
    treated as "unassign" would clear the owner of every lead in the batch."""
    tenant_id, slug, token = await _make_tenant()
    member = await _member(tenant_id)
    ids = [str(i) for i in await _seed_leads(tenant_id, 2)]

    async with _client() as http:
        refused = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={"scope": "ids", "ids": ids, "action": "assign"},
        )
        await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={"scope": "ids", "ids": ids, "action": "assign", "assign_to": str(member)},
        )
        cleared = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={"scope": "ids", "ids": ids, "action": "assign", "assign_to": None},
        )

    assert refused.status_code == 422, refused.text
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["changed"] == 2


async def test_an_assignee_from_another_tenant_refuses_the_whole_batch() -> None:
    """A person who is not on this team is a fact about the REQUEST, not about each of N
    leads — so it is a 422 and not N identical entries in `failures`. And it must move
    nothing: the validation runs before the first write.
    """
    tenant_id, slug, token = await _make_tenant()
    other_tenant, _other_slug, _ = await _make_tenant()
    stranger = await _member(other_tenant)
    ids = await _seed_leads(tenant_id, 3)

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={
                "scope": "ids",
                "ids": [str(i) for i in ids],
                "action": "assign",
                "assign_to": str(stranger),
            },
        )

    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/lead_assignee_not_a_member")
    async with tenant_session(tenant_id) as session:
        assigned = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE id = ANY(:ids) AND assigned_to IS NOT NULL"),
                {"ids": ids},
            )
        ).scalar()
    assert assigned == 0, "a refused batch left an owner behind"


# --- the guardrails ---------------------------------------------------------------


async def test_a_filter_matching_more_than_the_cap_is_refused_not_truncated() -> None:
    """Doing the first N of a larger set and answering 200 is the failure this route
    exists to avoid. The refusal names the real size and what to do about it."""
    tenant_id, slug, token = await _make_tenant()
    # One over the cap, counting the lead `_make_tenant` seeds.
    await _seed_leads(tenant_id, MAX_BULK_LEADS)

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={"scope": "filter", "action": "status", "status": "won"},
        )

    assert response.status_code == 422, response.text
    body = response.json()
    assert body["type"].endswith("/lead_bulk_too_many")
    assert str(MAX_BULK_LEADS + 1) in body["detail"]
    assert "Narrow the filter" in body["remediation"]
    async with tenant_session(tenant_id) as session:
        moved = (
            await session.execute(text("SELECT count(*) FROM leads WHERE status = 'won'"))
        ).scalar()
    assert moved == 0, "a refused batch still wrote"


async def test_a_set_that_moved_since_the_confirmation_is_refused() -> None:
    """The researched confirmation rule, enforced at the seam it can actually be checked.

    A filter-scoped batch is agreed to against a count the person read in a dialog, and
    that count can move while they are reading it. Running anyway spends their
    confirmation on a different set of rows.
    """
    tenant_id, slug, token = await _make_tenant()
    await _seed_leads(tenant_id, 3, status="interested")

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk?status=interested",
            headers=_headers(slug, token),
            json={
                "scope": "filter",
                "action": "status",
                "status": "won",
                "expected_count": 2,
            },
        )

    assert response.status_code == 409, response.text
    body = response.json()
    assert body["type"].endswith("/lead_bulk_set_moved")
    # BOTH numbers, because "it changed" without them is not something a person can act on.
    assert "3" in body["detail"] and "2" in body["detail"]
    async with tenant_session(tenant_id) as session:
        won = (
            await session.execute(text("SELECT count(*) FROM leads WHERE status = 'won'"))
        ).scalar()
    assert won == 0


async def test_a_matching_expected_count_lets_the_action_through() -> None:
    tenant_id, slug, token = await _make_tenant()
    await _seed_leads(tenant_id, 3, status="interested")

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk?status=interested",
            headers=_headers(slug, token),
            json={
                "scope": "filter",
                "action": "status",
                "status": "won",
                "expected_count": 3,
            },
        )

    assert response.status_code == 200, response.text
    assert response.json()["changed"] == 3


async def test_the_scope_has_no_default_so_an_ambiguous_request_is_refused() -> None:
    """The guardrail in one assertion. A default would decide page-vs-query on the
    caller's behalf, which is the ambiguity this field exists to remove."""
    tenant_id, slug, token = await _make_tenant()
    ids = [str(i) for i in await _seed_leads(tenant_id, 1)]

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={"ids": ids, "action": "status", "status": "won"},
        )

    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "validation"


async def test_ids_and_filter_scope_may_not_be_mixed() -> None:
    """Sending both is a caller that does not know which set it means, and the server
    must not pick one for it."""
    tenant_id, slug, token = await _make_tenant()
    ids = [str(i) for i in await _seed_leads(tenant_id, 1)]

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={"scope": "filter", "ids": ids, "action": "status", "status": "won"},
        )
    assert response.status_code == 422, response.text


# --- who may do it -----------------------------------------------------------------


async def test_staff_may_run_a_bulk_action_because_it_is_the_daily_job() -> None:
    """`leads:write`, which staff hold — the same permission the inline selects use. A
    bulk-only permission would be a fourth RBAC entry every role holds exactly when it
    holds this one."""
    tenant_id, slug, token = await _make_tenant(role="staff")
    ids = [str(i) for i in await _seed_leads(tenant_id, 2)]

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=_headers(slug, token),
            json={"scope": "ids", "ids": ids, "action": "status", "status": "contacted"},
        )
    assert response.status_code == 200, response.text


async def test_a_read_only_impersonating_admin_cannot_run_a_bulk_action() -> None:
    """D-22: `leads:write` is in MUTATING_PERMISSIONS, so "view as client" is refused
    this without the route needing to know about impersonation at all."""
    tenant_id, slug, _token = await _make_tenant()
    ids = [str(i) for i in await _seed_leads(tenant_id, 1)]
    admin_clerk = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:i, :c, 'Ops', 'operator', now(), now())"
            ),
            {"i": uuid.uuid4(), "c": admin_clerk},
        )

    async with _client() as http:
        response = await http.post(
            "/v1/leads/bulk",
            headers=await view_as_headers(
                http, f"dev:admin:{admin_clerk}", slug, **{"X-Org-Slug": slug}
            ),
            json={"scope": "ids", "ids": ids, "action": "status", "status": "won"},
        )
    assert response.status_code == 403, response.text
    assert response.json()["kind"] == "permission"


# --- the record --------------------------------------------------------------------


async def test_the_audit_row_records_counts_and_scope_and_no_lead_data(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ "Moved four leads I had ticked" and "moved every hot lead in the account" are the
    two ends of an incident, so the record has to tell them apart — while carrying no
    phone number, no name and no facet VALUE (hard rule 6).

    Two places, because `write_audit` puts them there: the chained ROW in `audit_log`
    (which has no summary column, deliberately — hashing a field the row does not carry
    would make the chain unverifiable) and the summary on the `audit` log line, keyed by
    the same entry id. Both are asserted, because a record that says a bulk write
    happened without saying how wide it was is not the record an incident needs.
    """
    tenant_id, slug, token = await _make_tenant()
    await _publish_enum_field(tenant_id)
    await _seed_leads(tenant_id, 2, status="interested", data='{"budget_band": "over_50l"}')

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await http.post(
                "/v1/leads/bulk?status=interested&f=budget_band%3Aover_50l",
                headers=_headers(slug, token),
                json={"scope": "filter", "action": "status", "status": "won"},
            )
    assert response.status_code == 200, response.text

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT object_type, entry_hash FROM audit_log "
                    "WHERE action = 'lead.bulk_status' ORDER BY at DESC LIMIT 1"
                )
            )
        ).first()
    assert row is not None, "a bulk write left no audit trail"
    assert row[0] == "lead"
    assert row[1], "the entry did not join the hash chain"

    entry = next(r for r in caplog.records if r.getMessage() == "audit")
    assert entry.scope == "filter"  # type: ignore[attr-defined]
    assert (entry.requested, entry.changed, entry.failed) == (2, 2, 0)  # type: ignore[attr-defined]
    # THE FACET VALUE IS ABSENT, which is the hard-rule-6 half: a value like "over_50l"
    # is the client's own captured data. So are the leads' names and numbers, and the id
    # list is not a summary either. (`field_filters` is present but collapses to
    # "[N items]" through `redact_mapping`'s length cap — the same thing happens to the
    # export's audit row, and the count is what survives. Worth knowing before anyone
    # reads this record expecting key names.)
    assert entry.__dict__.get("field_filters")
    assert "over_50l" not in str(entry.__dict__)
    assert "Lead 0" not in str(entry.__dict__)
