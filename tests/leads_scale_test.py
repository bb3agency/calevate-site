"""The Leads surface at real sizes: does what it SAYS match what it SENDS?

Three separate ways this endpoint pair could tell a client something untrue, and each
one of them was reachable from the shipped UI:

1. **The export ignored the screen.** `GET /v1/leads/export.csv` took `agent_id` and
   nothing else, so filtering to `hot` and pressing Export mailed out every contact in
   the account. The frontend said so on the button, which is honest and is not the
   feature.
2. **The status tally described the page, not the business.** With no per-status count
   in the response, the only numbers the UI had were the ≤100 rows it happened to hold,
   already narrowed server-side — so filtering to `hot` rendered `new 0, contacted 0`,
   which reads as "you have no new leads".
3. **`ORDER BY updated_at DESC` is not a total order.** Leads imported in one
   transaction share `updated_at` to the microsecond, and an unstable sort under
   LIMIT/OFFSET silently repeats some rows and drops others. `total` stays right while
   the pages themselves lose leads.

Every assertion here is scoped to a tenant this module creates, because other suites run
against the same database.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

import pytest
from apps.api.crm import service as crm
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

LIST = "/v1/leads"
EXPORT = "/v1/leads/export.csv"

SCHEMA = [{"key": "intent", "label": "Intent", "type": "text", "description": "what they want"}]


class Org:
    """One tenant, its agents, and a member's dev token."""

    def __init__(self, tenant_id: uuid.UUID, slug: str, token: str, agents: list[uuid.UUID]):
        self.tenant_id = tenant_id
        self.slug = slug
        self.token = token
        self.agents = agents

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Org-Slug": self.slug}


async def _org(role: str = "owner", *, agents: int = 1) -> Org:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    slug = f"ls-{tenant_id.hex[:10]}"
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    agent_ids = [uuid.uuid4() for _ in range(agents)]

    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Scale Motors', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": slug},
        )
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
        for n, agent_id in enumerate(agent_ids):
            await session.execute(
                text(
                    "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                    "status, engine, created_at, updated_at) VALUES (:id, :tid, :name, "
                    "'outbound', 'Idi AI assistant.', 'live', 'fake', now(), now())"
                ),
                {"id": agent_id, "tid": tenant_id, "name": f"Agent {n}"},
            )
            await session.execute(
                text(
                    "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                    "created_at, updated_at) VALUES (:id, :tid, :aid, :v, CAST(:f AS jsonb), "
                    "now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    # Descending versions so `lead_columns`' unfiltered "latest schema"
                    # branch and its per-agent branch pick DIFFERENT rows — otherwise a
                    # broken agent filter would still look right.
                    "v": len(agent_ids) - n,
                    "f": json.dumps(SCHEMA),
                },
            )
    return Org(tenant_id, slug, f"dev:client:{clerk_id}", agent_ids)


async def _seed(
    org: Org,
    *,
    status: str,
    count: int,
    agent_index: int = 0,
    name: str = "Ravi",
    same_instant: bool = False,
) -> list[str]:
    """Insert `count` leads and return their phone numbers.

    `same_instant` stamps every row with one `updated_at` — the bulk-import shape that
    an unstable ORDER BY turns into a lossy paginator.
    """
    agent_id = org.agents[agent_index]
    phones = [f"+9198{uuid.uuid4().int % 100000000:08d}" for _ in range(count)]
    stamp = "now()" if not same_instant else "TIMESTAMPTZ '2026-01-01 10:00:00+00'"
    async with tenant_session(org.tenant_id) as session:
        for phone in phones:
            await session.execute(
                text(
                    "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, "
                    "status, data, created_at, updated_at) VALUES (:i, :t, :a, :p, :n, "
                    f"'webhook', :s, CAST('{{}}' AS jsonb), {stamp}, {stamp})"
                ),
                {
                    "i": uuid7(),
                    "t": org.tenant_id,
                    "a": agent_id,
                    "p": phone,
                    "n": name,
                    "s": status,
                },
            )
    return phones


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _csv_phones(body: str) -> set[str]:
    """The phone column of an export, as a set. Header row dropped.

    Parsed with `csv.reader` rather than `line.split(",")`. The hand-rolled version read
    the raw field INCLUDING its quotes, so it broke the moment the writer moved to
    `QUOTE_ALL` — which it did so the formula guard keeps working, since OWASP's tab
    prefix has to sit inside the quoted field. It would have broken just as hard on a
    client whose lead name contains a comma, which is not exotic.

    The lesson is worth the four lines: a test that parses the format under test loosely
    goes red for reasons that are not its subject, and the next reader has to decide
    whether the product or the assertion is wrong.

    THE TAB IS PART OF THE FORMAT, not noise to be tolerated. Every scalar column goes
    through `disarm_for_csv` now, and E.164 begins with `+` — a formula leader Excel
    would otherwise evaluate, eating the country-code marker — so every phone cell is
    tab-prefixed. Stripping it here is this reader's job; `redteam_extraction_poisoning_test`
    is where the prefix itself is asserted, and these tests are about which ROWS the
    export contains.
    """
    rows = list(csv.reader(io.StringIO(body.strip())))
    return {row[0].removeprefix("\t") for row in rows[1:] if row}


# --------------------------------------------------------------- 1. export filters


async def test_the_export_honours_the_status_filter() -> None:
    """Filter to `hot`, press Export, get the hot ones. The whole point."""
    org = await _org()
    hot = await _seed(org, status="hot", count=4)
    new = await _seed(org, status="new", count=6)

    async with _client() as http:
        response = await http.get(f"{EXPORT}?status=hot", headers=org.headers)

    assert response.status_code == 200, response.text
    exported = _csv_phones(response.text)
    assert exported == set(hot), "the export did not narrow to the filtered status"
    for phone in new:
        assert phone not in response.text, "a filtered export leaked an unfiltered contact"


async def test_the_export_honours_the_search_filter() -> None:
    org = await _org()
    lakshmi = await _seed(org, status="new", count=3, name="Lakshmi")
    ravi = await _seed(org, status="new", count=5, name="Ravi")

    async with _client() as http:
        by_name = await http.get(f"{EXPORT}?search=Lakshmi", headers=org.headers)
        # The list search also matches a phone SUFFIX; the export must match the same
        # rows or "export what I am looking at" is still false for half the searches.
        by_suffix = await http.get(f"{EXPORT}?search={ravi[0][-4:]}", headers=org.headers)

    assert by_name.status_code == 200, by_name.text
    assert _csv_phones(by_name.text) == set(lakshmi)
    assert by_suffix.status_code == 200, by_suffix.text
    assert ravi[0] in _csv_phones(by_suffix.text)


async def test_the_export_and_the_list_agree_on_what_the_filters_mean() -> None:
    """The contract that makes the button honest: same query string, same rows.

    Asserted as an identity between the two endpoints rather than against a literal,
    so a filter added to one and forgotten on the other fails here.
    """
    org = await _org()
    await _seed(org, status="hot", count=7, name="Priya")
    await _seed(org, status="hot", count=3, name="Ravi")
    await _seed(org, status="won", count=5, name="Priya")

    query = "status=hot&search=Priya"
    async with _client() as http:
        listed = await http.get(f"{LIST}?{query}&limit=200", headers=org.headers)
        exported = await http.get(f"{EXPORT}?{query}", headers=org.headers)

    assert listed.status_code == 200 and exported.status_code == 200
    assert listed.json()["total"] == 7
    # Masked on screen, full in the file — same seven people either way.
    assert len(_csv_phones(exported.text)) == listed.json()["total"]
    suffixes = {item["phone_masked"][-2:] for item in listed.json()["items"]}
    assert {p[-2:] for p in _csv_phones(exported.text)} == suffixes


async def test_agent_id_filters_rows_on_both_routes_not_just_columns() -> None:
    """`agent_id` picked the COLUMNS on `/v1/leads` and did not filter the ROWS — so the
    table rendered agent B's leads under agent A's capture list. Both routes now scope
    the rows, which is also what the export's own too-large remediation has always
    promised ("Export one agent at a time with ?agent_id=")."""
    org = await _org(agents=2)
    first = await _seed(org, status="new", count=5, agent_index=0)
    second = await _seed(org, status="new", count=8, agent_index=1)

    async with _client() as http:
        listed = await http.get(f"{LIST}?agent_id={org.agents[1]}", headers=org.headers)
        exported = await http.get(f"{EXPORT}?agent_id={org.agents[1]}", headers=org.headers)
        unscoped = await http.get(LIST, headers=org.headers)

    assert listed.status_code == 200, listed.text
    assert listed.json()["total"] == 8, "agent_id still does not filter the list's rows"
    assert _csv_phones(exported.text) == set(second)
    for phone in first:
        assert phone not in exported.text
    # And omitting it keeps meaning "everything", so the existing contract survives.
    assert unscoped.json()["total"] == 13


async def test_filters_do_not_open_the_export_to_staff() -> None:
    """The export is `calls:read_raw` BECAUSE it emits unmasked numbers. Adding filters
    must not have added a path where a narrower request is a cheaper permission."""
    org = await _org(role="staff")
    phones = await _seed(org, status="hot", count=3)

    async with _client() as http:
        for query in ("", "?status=hot", f"?search={phones[0][-4:]}", f"?agent_id={org.agents[0]}"):
            response = await http.get(f"{EXPORT}{query}", headers=org.headers)
            assert response.status_code == 403, f"staff exported with {query!r}"
            assert response.json()["kind"] == "permission"
            for phone in phones:
                assert phone not in response.text


async def test_a_filtered_export_is_audited_like_an_unfiltered_one() -> None:
    """The masking waiver rests on the taking being recorded. A narrower export is still
    a contact list leaving the building."""
    org = await _org()
    await _seed(org, status="hot", count=2)

    async with _client() as http:
        response = await http.get(f"{EXPORT}?status=hot", headers=org.headers)
    assert response.status_code == 200, response.text

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'leads.export' "
                    "AND tenant_id = :t"
                ),
                {"t": org.tenant_id},
            )
        ).scalar()
    assert rows == 1, "a filtered export must leave the same record an unfiltered one does"


async def test_the_export_cap_applies_to_the_filtered_rows_only() -> None:
    """The cap's remediation tells the client to narrow the export. That advice was
    unreachable while the filters did not reach the row query: narrowing changed nothing
    and the same refusal came back."""
    org = await _org()
    await _seed(org, status="new", count=6)
    await _seed(org, status="hot", count=2)

    from apps.api.core.errors import ProblemError

    original = crm.MAX_EXPORT_ROWS
    try:
        crm.MAX_EXPORT_ROWS = 4
        async with tenant_session(org.tenant_id) as session:
            with pytest.raises(ProblemError) as raised:
                await crm.export_leads_csv(session)
            # ...and the documented escape hatch actually works.
            narrowed = await crm.export_leads_csv(session, status="hot")
    finally:
        crm.MAX_EXPORT_ROWS = original

    assert raised.value.code == "lead_export_too_large"
    assert len(narrowed.strip().splitlines()) == 3, "header + two hot leads"


# --------------------------------------------------------------- 2. status counts


async def test_status_counts_describe_every_status_even_while_filtered_to_one() -> None:
    """The reported bug, stated as a test: with `?status=hot` the breakdown must still
    know about `new`. A per-status count that respected the status filter would be one
    non-zero bucket and five lies."""
    org = await _org()
    await _seed(org, status="new", count=9)
    await _seed(org, status="contacted", count=4)
    await _seed(org, status="hot", count=2)

    async with _client() as http:
        response = await http.get(f"{LIST}?status=hot", headers=org.headers)

    body = response.json()
    counts = body["status_counts_matching_search"]
    assert body["total"] == 2, "`total` still counts what you asked for"
    assert counts["new"] == 9 and counts["contacted"] == 4 and counts["hot"] == 2
    # Silent statuses are 0, not absent: the UI renders a badge per status and a
    # missing key is how "no leads at all" becomes indistinguishable from "no data".
    assert counts["won"] == 0 and counts["lost"] == 0 and counts["interested"] == 0
    assert sum(counts.values()) == 15


async def test_status_counts_respect_the_search_and_agent_filters() -> None:
    """The name says `matching_search`, so it must: a breakdown of the whole account
    next to a searched page would be two different populations under one heading."""
    org = await _org(agents=2)
    await _seed(org, status="new", count=5, name="Lakshmi")
    await _seed(org, status="hot", count=3, name="Lakshmi")
    await _seed(org, status="new", count=7, name="Ravi")
    await _seed(org, status="won", count=4, name="Lakshmi", agent_index=1)

    async with _client() as http:
        searched = await http.get(f"{LIST}?search=Lakshmi", headers=org.headers)
        scoped = await http.get(f"{LIST}?agent_id={org.agents[1]}", headers=org.headers)
        everything = await http.get(LIST, headers=org.headers)

    searched_counts = searched.json()["status_counts_matching_search"]
    assert searched_counts["new"] == 5, "the counts ignored the search filter"
    assert searched_counts["hot"] == 3
    assert searched_counts["won"] == 4
    assert searched.json()["total"] == 12

    assert scoped.json()["status_counts_matching_search"]["won"] == 4
    assert scoped.json()["status_counts_matching_search"]["new"] == 0
    assert everything.json()["status_counts_matching_search"]["new"] == 12


async def test_counts_are_a_property_of_the_account_not_of_the_page() -> None:
    """The failure the UI worked around: a tally computed from the rows it holds is
    capped by the page size. 140 leads over a 50-row page must still count 140."""
    org = await _org()
    await _seed(org, status="new", count=140)

    async with _client() as http:
        response = await http.get(f"{LIST}?limit=50", headers=org.headers)

    body = response.json()
    assert len(body["items"]) == 50
    assert body["total"] == 140
    assert body["status_counts_matching_search"]["new"] == 140


async def test_counts_never_see_another_tenants_leads() -> None:
    """A GROUP BY with no `WHERE tenant_id` is only safe while RLS is doing its job.
    Aggregates are exactly where a policy gap shows up as a number rather than a row."""
    mine = await _org()
    theirs = await _org()
    await _seed(mine, status="new", count=3)
    await _seed(theirs, status="new", count=11)

    async with _client() as http:
        response = await http.get(LIST, headers=mine.headers)

    assert response.json()["status_counts_matching_search"]["new"] == 3
    assert response.json()["total"] == 3


async def test_soft_deleted_leads_are_absent_from_counts_and_export() -> None:
    """`deleted_at IS NULL` is on the row query; a count or an export that forgot it
    would put deleted people back in front of the client."""
    org = await _org()
    phones = await _seed(org, status="new", count=5)
    async with tenant_session(org.tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET deleted_at = now() WHERE phone_e164 = :p"), {"p": phones[0]}
        )

    async with _client() as http:
        listed = await http.get(LIST, headers=org.headers)
        exported = await http.get(EXPORT, headers=org.headers)

    assert listed.json()["status_counts_matching_search"]["new"] == 4
    assert listed.json()["total"] == 4
    assert phones[0] not in exported.text


# --------------------------------------------------------------- 3. pagination


async def test_paging_a_bulk_import_returns_every_lead_exactly_once() -> None:
    """Offset pagination is kept (see the note in `list_leads`), but it is only correct
    over a TOTAL order. `ORDER BY updated_at DESC` alone is not one: 220 leads written
    in a single import share the timestamp, Postgres may return them in any order per
    query, and the same row lands on page 1 and page 3 while another lands nowhere.
    `total` stays right the whole time, which is what makes it hard to notice.
    """
    org = await _org()
    seeded = await _seed(org, status="new", count=220, same_instant=True)

    seen: list[str] = []
    async with _client() as http:
        for offset in range(0, 250, 50):
            page = await http.get(f"{LIST}?limit=50&offset={offset}", headers=org.headers)
            assert page.status_code == 200, page.text
            assert page.json()["total"] == len(seeded)
            seen.extend(item["id"] for item in page.json()["items"])

    assert len(seen) == len(seeded), "paging returned the wrong number of rows"
    assert len(set(seen)) == len(seeded), "a row appeared on two pages while another vanished"


async def test_the_last_page_is_the_last_page() -> None:
    """Off-by-one at the boundary: a page starting exactly at `total` is empty, and the
    page before it is full."""
    org = await _org()
    await _seed(org, status="new", count=201, same_instant=True)

    async with _client() as http:
        full = await http.get(f"{LIST}?limit=200&offset=0", headers=org.headers)
        tail = await http.get(f"{LIST}?limit=200&offset=200", headers=org.headers)
        past = await http.get(f"{LIST}?limit=200&offset=201", headers=org.headers)

    assert len(full.json()["items"]) == 200, "the documented 200 cap is not the cap"
    assert len(tail.json()["items"]) == 1
    assert past.json()["items"] == []
    assert past.json()["total"] == 201, "an empty page still reports the true total"


async def test_the_export_is_ordered_deterministically_too() -> None:
    """Same tiebreaker, milder stake: the export refuses rather than truncating, so an
    unstable sort here does not lose rows — it makes the FILE unreproducible. Two
    exports of an account nobody touched in between should diff to nothing, or every
    client who keeps the CSV in a spreadsheet gets phantom churn."""
    org = await _org()
    seeded = await _seed(org, status="new", count=60, same_instant=True)

    async with tenant_session(org.tenant_id) as session:
        first = await crm.export_leads_csv(session, status="new")
        second = await crm.export_leads_csv(session, status="new")

    assert _csv_phones(first) == set(seeded), "header + every seeded lead"
    assert first == second, "the same export ran twice and produced two different files"


async def test_an_over_cap_limit_is_refused_rather_than_silently_clamped() -> None:
    """`limit=5000` used to be clamped to 200 by the service while the response echoed
    `limit: 5000` — a page that reports a size it is not."""
    org = await _org()
    await _seed(org, status="new", count=3)

    async with _client() as http:
        response = await http.get(f"{LIST}?limit=5000", headers=org.headers)
    assert response.status_code == 422

    async with _client() as http:
        ok = await http.get(f"{LIST}?limit=200", headers=org.headers)
    body: dict[str, Any] = ok.json()
    assert body["limit"] == 200 and body["offset"] == 0
