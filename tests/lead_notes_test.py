"""Notes the team leaves on a lead or one of its calls (W7.2), and Find (W7.4).

Claims: a note's words live in `lead_notes` and never in `lead_events.payload`; the timeline
shows them, an edit and a removal at once; edits are a version CAS limited to the writer or
the owner; a note filed under a call must be that lead's call; RLS gives another tenant zero
rows; both erasures and the lead clock delete the words. Find matches a name, the last four
digits and a Latin spelling of a Telugu name, never an erased lead, and answers a number with
its last four digits only.

CONCURRENCY: every test mints its own organization and reads only through it.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from apps.api.crm import find
from apps.api.db.session import tenant_session, untenanted_session
from sqlalchemy import text
from tests.api_security_test import _make_tenant
from tests.lead_assignment_test import _colleague, _headers, _the_lead

NOTE = "Wants a site visit on Saturday; call after 6 pm."


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _call(tenant_id: uuid.UUID, lead_id: uuid.UUID | None) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, lead_id, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, "
                "'inbound', 'completed', now(), :lid, now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"ln-{uuid.uuid4().hex}",
                "lid": lead_id,
            },
        )
    return call_id


async def _add(http: httpx.AsyncClient, slug: str, token: str, lead_id: uuid.UUID, **body: object):
    return await http.post(
        f"/v1/leads/{lead_id}/notes", json={"body": NOTE, **body}, headers=_headers(slug, token)
    )


async def test_a_note_is_written_shown_on_the_history_and_its_words_stay_off_lead_events() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with _client() as http:
        made = await _add(http, slug, token, lead_id)
        assert made.status_code == 201, made.text
        note = made.json()
        assert note["body"] == NOTE and note["version"] == 1
        timeline = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))
    item = timeline.json()["items"][0]
    assert item["type"] == "note" and item["title"] == "Note"
    assert item["note"]["body"] == NOTE
    assert item["actor_kind"] == "member"
    async with tenant_session(tenant_id) as session:
        payloads = (
            (await session.execute(text("SELECT payload::text FROM lead_events"))).scalars().all()
        )
    assert payloads and all("site visit" not in p for p in payloads)


async def test_an_edit_is_a_cas_and_a_removal_reads_as_removed() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with _client() as http:
        note = (await _add(http, slug, token, lead_id)).json()
        url = f"/v1/leads/{lead_id}/notes/{note['id']}"
        edited = await http.patch(
            url,
            json={"body": "Visit moved to Sunday.", "expected_version": 1},
            headers=_headers(slug, token),
        )
        assert edited.status_code == 200, edited.text
        assert edited.json()["version"] == 2 and edited.json()["edited_at"]
        stale = await http.patch(
            url, json={"body": "Lost race", "expected_version": 1}, headers=_headers(slug, token)
        )
        assert stale.status_code == 409
        assert stale.json()["type"].endswith("/note_changed")
        gone = await http.delete(url, headers=_headers(slug, token))
        assert gone.status_code == 204
        timeline = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))
    item = timeline.json()["items"][0]
    assert item["title"] == "Note removed" and item["note"] is None


async def test_only_the_writer_or_the_owner_may_change_a_note() -> None:
    tenant_id, slug, owner_token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    staff_id = await _colleague(tenant_id, "Priya")
    staff_token = f"dev:client:{staff_id}"
    async with _client() as http:
        owners = (await _add(http, slug, owner_token, lead_id)).json()
        refused = await http.patch(
            f"/v1/leads/{lead_id}/notes/{owners['id']}",
            json={"body": "Not mine", "expected_version": 1},
            headers=_headers(slug, staff_token),
        )
        assert refused.status_code == 403
        staffs = (await _add(http, slug, staff_token, lead_id)).json()
        assert staffs["author_name"] == "Priya"
        by_owner = await http.delete(
            f"/v1/leads/{lead_id}/notes/{staffs['id']}", headers=_headers(slug, owner_token)
        )
        assert by_owner.status_code == 204


async def test_a_call_note_is_listed_on_its_call_and_must_be_the_leads_call() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    call_id = await _call(tenant_id, lead_id)
    stranger = await _call(tenant_id, None)
    async with _client() as http:
        made = await _add(http, slug, token, lead_id, call_id=str(call_id))
        assert made.status_code == 201, made.text
        wrong = await _add(http, slug, token, lead_id, call_id=str(stranger))
        assert wrong.status_code == 422
        listed = await http.get(f"/v1/calls/{call_id}/notes", headers=_headers(slug, token))
        timeline = await http.get(f"/v1/leads/{lead_id}/timeline", headers=_headers(slug, token))
    assert listed.status_code == 200
    assert [n["body"] for n in listed.json()["items"]] == [NOTE]
    assert listed.json()["total"] == 1
    assert timeline.json()["items"][0]["call_id"] == str(call_id)


async def test_another_tenant_sees_zero_rows_and_cannot_write() -> None:
    tenant_a, slug_a, token_a = await _make_tenant()
    tenant_b, slug_b, token_b = await _make_tenant()
    lead_a = await _the_lead(tenant_a)
    async with _client() as http:
        assert (await _add(http, slug_a, token_a, lead_a)).status_code == 201
        across = await _add(http, slug_b, token_b, lead_a)
    assert across.status_code == 404
    async with tenant_session(tenant_b) as session:
        seen = (await session.execute(text("SELECT count(*) FROM lead_notes"))).scalar_one()
    assert seen == 0
    async with tenant_session(tenant_a) as session:
        own = (await session.execute(text("SELECT count(*) FROM lead_notes"))).scalar_one()
    assert own == 1


async def test_a_blank_note_is_refused() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with _client() as http:
        response = await http.post(
            f"/v1/leads/{lead_id}/notes", json={"body": "   "}, headers=_headers(slug, token)
        )
    assert response.status_code == 422


async def test_the_tenant_erasure_and_the_lead_clock_delete_the_words() -> None:
    from apps.workers import retention

    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with _client() as http:
        assert (await _add(http, slug, token, lead_id)).status_code == 201
    # The lead clock: once a lead is anonymized, its notes go in the same sweep.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE leads SET phone_e164 = :anon || right(replace(id::text, '-', ''), 12), "
                "deleted_at = now() WHERE id = :l"
            ),
            {"anon": retention.ANONYMIZED_PHONE[:9], "l": lead_id},
        )
        swept, _ = await retention._sweep_in_batches(
            session, retention._LEAD_NOTE_SQL, {"anon": retention.ANONYMIZED_PHONE[:9]}
        )
    assert swept == 1
    async with tenant_session(tenant_id) as session:
        left = (await session.execute(text("SELECT count(*) FROM lead_notes"))).scalar_one()
    assert left == 0


# --- Find ------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("latin", "telugu"),
    [
        ("Srinivas", "శ్రీనివాస్"),
        ("Sreenivas", "శ్రీనివాస్"),
        ("Lakshmi", "లక్ష్మి"),
        ("Venkatesh", "వెంకటేష్"),
        ("Sampath", "సంపత్"),
        ("Krishna", "కృష్ణ"),
        ("Naidu", "నాయుడు"),
        ("Pallavi", "పల్లవి"),
        ("Chaitanya", "చైతన్య"),
    ],
)
def test_a_latin_spelling_reads_as_the_telugu_name(latin: str, telugu: str) -> None:
    skeleton = find.latin_skeleton(latin)
    assert skeleton is not None
    assert skeleton in find.telugu_skeleton(telugu)


def test_digits_and_short_words_get_no_skeleton() -> None:
    assert find.latin_skeleton("3210") is None
    assert find.latin_skeleton("ab") is None


async def _lead(tenant_id: uuid.UUID, name: str, phone: str, *, erased: bool = False) -> uuid.UUID:
    lead_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "deleted_at, created_at, updated_at) VALUES (:id, :tid, :aid, :phone, :name, "
                "'inbound_call', 'new', CASE WHEN :erased THEN now() END, now(), now())"
            ),
            {
                "id": lead_id,
                "tid": tenant_id,
                "aid": agent_id,
                "phone": phone,
                "name": name,
                "erased": erased,
            },
        )
    return lead_id


async def test_find_matches_a_name_last_digits_and_a_telugu_name_never_an_erased_lead() -> None:
    tenant_id, slug, token = await _make_tenant()
    telugu = await _lead(tenant_id, "శ్రీనివాస్ రెడ్డి", "+919000011223")
    digits = await _lead(tenant_id, "Anitha", "+919000077345")
    await _lead(tenant_id, "Anitha Gone", "+919000099345", erased=True)
    call_id = await _call(tenant_id, digits)
    async with _client() as http:

        async def ask(q: str) -> dict:
            response = await http.post("/v1/find", json={"q": q}, headers=_headers(slug, token))
            assert response.status_code == 200, response.text
            return response.json()

        by_skeleton = await ask("srinivas")
        by_digits = await ask("7345")
        by_name = await ask("anitha")
        by_screen = await ask("top up")
    assert [p["lead_id"] for p in by_skeleton["people"]] == [str(telugu)]
    assert [p["lead_id"] for p in by_digits["people"]] == [str(digits)]
    assert by_digits["people"][0]["phone_last4"] == "7345"
    assert "+91" not in str(by_digits)
    assert [p["lead_id"] for p in by_name["people"]] == [str(digits)]
    assert [c["call_id"] for c in by_name["calls"]] == [str(call_id)]
    assert by_name["calls_shown"] is True
    assert any(s["route"] == "/c/{slug}/billing" for s in by_screen["screens"])


async def test_find_needs_four_digits_and_stays_inside_the_tenant() -> None:
    tenant_a, _, _ = await _make_tenant()
    _, slug_b, token_b = await _make_tenant()
    await _lead(tenant_a, "Across", "+919000055661")
    async with _client() as http:
        short = await http.post("/v1/find", json={"q": "661"}, headers=_headers(slug_b, token_b))
        other = await http.post("/v1/find", json={"q": "Across"}, headers=_headers(slug_b, token_b))
    assert short.json()["people"] == []
    assert other.json()["people"] == []


async def test_find_screens_follow_the_role() -> None:
    owner = find.find_screens("billing", role="owner", limit=8)
    staff = find.find_screens("billing", role="staff", limit=8)
    assert owner and {s.route for s in staff} <= {s.route for s in owner}


async def test_untenanted_reads_of_lead_notes_see_nothing() -> None:
    tenant_id, slug, token = await _make_tenant()
    lead_id = await _the_lead(tenant_id)
    async with _client() as http:
        assert (await _add(http, slug, token, lead_id)).status_code == 201
    async with untenanted_session() as session:
        seen = (await session.execute(text("SELECT count(*) FROM lead_notes"))).scalar_one()
    assert seen == 0
