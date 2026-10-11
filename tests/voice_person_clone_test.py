"""A cloned voice of a real person, offered to Studio clients under a name we give it (D-721).

The voice is marked by an operator; until the speaker's consent is recorded, and it has a
name of our own, it cannot be switched on and is never on a client's picker. Every record
and every change to it is audited. Clients see the operator's name for the voice and never
the provider's, so they are not told whose voice it is.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import engine_catalogue_routes
from apps.api.agents.engine_catalogue_routes import engine_catalogue
from apps.api.agents.hosted_voices import name_reveals_speaker
from apps.api.core.context import Principal
from apps.api.db.session import admin_session, untenanted_session
from apps.api.main import app
from apps.api.ops import hosted_voice_routes as routes
from apps.workers import storage
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text
from tests.hosted_voice_fakes import CatalogueRows, HostingEngine, selected

PDF = b"%PDF-1.4\n%consent\n"
STATEMENT = "I agree that a cloned copy of my voice may be offered to Calevate's clients."


def _http() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


@pytest.fixture
async def operator() -> tuple[dict[str, str], UUID]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}, admin_id


@pytest.fixture
def consent_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """The object store for consent documents, in memory."""
    objects: dict[str, bytes] = {}

    async def _store(*, key: str, data: bytes) -> str:
        objects[key] = data
        return key

    async def _read(key: str) -> bytes | None:
        return objects.get(key)

    monkeypatch.setattr(storage, "store_voice_consent", _store)
    monkeypatch.setattr(storage, "read_voice_consent", _read)
    return objects


@pytest.fixture
def priced(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = frozenset({"platform", "premium", "studio", "byok_voice"})

    async def _keys(session: Any, *, engine: str, at: Any) -> frozenset[str]:
        return keys

    monkeypatch.setattr(engine_catalogue_routes, "attested_rate_keys", _keys)
    monkeypatch.setattr(engine_catalogue_routes, "tts_price_is_billable", lambda provider: True)


async def _audit_actors(action: str, voice_id: str) -> list[str]:
    """Who wrote each audit entry for this voice, oldest first. `audit_log` holds the actor,
    the act and the object; the summary goes to the audit log stream, not the table."""
    async with untenanted_session() as session:
        rows = await session.execute(
            text(
                "SELECT actor_id FROM audit_log WHERE action = :a AND object_id = :v "
                "AND object_type = 'platform_voice_catalog' ORDER BY at"
            ),
            {"a": action, "v": voice_id},
        )
        return [str(row[0]) for row in rows.all()]


async def _record(
    http: AsyncClient,
    headers: dict[str, str],
    voice_id: str,
    *,
    speaker: str = "Test Speaker",
    document: bytes | None = PDF,
    confirm: str | None = None,
) -> Response:
    files = {"document": ("signed.pdf", document, "application/pdf")} if document else None
    return await http.post(
        "/v1/ops/voices/hosted/clone-consent",
        headers={**headers, "X-Confirm-Action": confirm or routes.consent_confirmation(voice_id)},
        data={
            "voice_id": voice_id,
            "speaker_name": speaker,
            "statement": STATEMENT,
            "consented_on": "2026-10-10",
        },
        files=files,
    )


def _code(response: Response) -> str:
    return str(response.json()["type"]).rsplit("/", 1)[-1]


async def test_a_marked_clone_cannot_be_offered_until_its_consent_and_name_are_recorded(
    operator: tuple[dict[str, str], UUID],
    hosted_rows: CatalogueRows,
    consent_store: dict[str, bytes],
) -> None:
    headers, admin_id = operator
    voice = await hosted_rows.add("byok", label="Sri (instant clone)", state="disabled")
    with selected(HostingEngine()):
        async with _http() as http:
            marked = await http.patch(
                "/v1/ops/voices/hosted/person-clone",
                headers={**headers, "X-Confirm-Action": routes.person_clone_confirmation(voice)},
                json={"voice_id": voice, "person_clone": True},
            )
            without_consent = await http.patch(
                "/v1/ops/voices/hosted",
                headers=headers,
                json={"voice_id": voice, "state": "enabled"},
            )
            recorded = await _record(http, headers, voice)
            without_name = await http.patch(
                "/v1/ops/voices/hosted",
                headers=headers,
                json={"voice_id": voice, "state": "enabled"},
            )
            named = await http.patch(
                "/v1/ops/voices/hosted/display-name",
                headers=headers,
                json={"voice_id": voice, "display_label": "Aditya"},
            )
            enabled = await http.patch(
                "/v1/ops/voices/hosted",
                headers=headers,
                json={"voice_id": voice, "state": "enabled"},
            )
    assert marked.status_code == 200, marked.text
    assert marked.json()["voice"]["clone_blocker"] is not None
    assert _code(without_consent) == "voice_clone_consent_missing"
    assert "consent" in without_consent.json()["detail"]
    assert recorded.status_code == 200, recorded.text
    consent = recorded.json()["voice"]["clone_consent"]
    assert consent["speaker_name"] == "Test Speaker"
    assert consent["scope"] == "Calls made by Calevate clients' agents."
    assert consent["recorded_by"] == str(admin_id) and consent["recorded_by_name"] == "Ops"
    assert consent["has_document"] is True
    # The document is kept sealed, never as the bytes uploaded.
    assert len(consent_store) == 1 and PDF not in next(iter(consent_store.values()))
    assert _code(without_name) == "voice_clone_name_missing"
    assert named.status_code == 200 and named.json()["voice"]["label"] == "Aditya"
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["voice"]["offered"] is True


async def test_marking_an_offered_voice_without_consent_is_refused(
    operator: tuple[dict[str, str], UUID], hosted_rows: CatalogueRows
) -> None:
    headers, _ = operator
    voice = await hosted_rows.add("byok", state="enabled")
    with selected(HostingEngine()):
        async with _http() as http:
            refused = await http.patch(
                "/v1/ops/voices/hosted/person-clone",
                headers={**headers, "X-Confirm-Action": routes.person_clone_confirmation(voice)},
                json={"voice_id": voice, "person_clone": True},
            )
    assert _code(refused) == "voice_clone_consent_missing"


async def test_both_clone_writes_need_their_step_up_confirmation_for_that_voice(
    operator: tuple[dict[str, str], UUID],
    hosted_rows: CatalogueRows,
    consent_store: dict[str, bytes],
) -> None:
    headers, _ = operator
    voice = await hosted_rows.add("byok", state="disabled")
    other = await hosted_rows.add("byok", state="disabled")
    with selected(HostingEngine()):
        async with _http() as http:
            no_header = await http.patch(
                "/v1/ops/voices/hosted/person-clone",
                headers=headers,
                json={"voice_id": voice, "person_clone": True},
            )
            wrong_voice = await _record(
                http, headers, voice, confirm=routes.consent_confirmation(other)
            )
    assert _code(no_header) == "step_up_required"
    assert _code(wrong_voice) == "step_up_required"
    assert consent_store == {}


async def test_the_consent_record_and_every_change_to_it_are_audited(
    operator: tuple[dict[str, str], UUID],
    hosted_rows: CatalogueRows,
    consent_store: dict[str, bytes],
) -> None:
    headers, admin_id = operator
    voice = await hosted_rows.add("byok", state="disabled")
    with selected(HostingEngine()):
        async with _http() as http:
            first = await _record(http, headers, voice)
            replaced = await _record(
                http, headers, voice, speaker="Test Speaker Two", document=None
            )
            unmarked = await http.patch(
                "/v1/ops/voices/hosted/person-clone",
                headers={**headers, "X-Confirm-Action": routes.person_clone_confirmation(voice)},
                json={"voice_id": voice, "person_clone": False},
            )
    assert first.status_code == replaced.status_code == unmarked.status_code == 200
    assert await _audit_actors("ops.voice_clone_consent_recorded", voice) == [str(admin_id)] * 2
    assert await _audit_actors("ops.voice_person_clone_set", voice) == [str(admin_id)]
    # A replacement without a new document keeps the signed copy already stored.
    assert replaced.json()["voice"]["clone_consent"]["speaker_name"] == "Test Speaker Two"
    assert replaced.json()["voice"]["clone_consent"]["has_document"] is True
    # Unmarking keeps the record and its document as evidence; only the mark goes.
    body = unmarked.json()["voice"]
    assert body["person_clone"] is False
    assert body["clone_consent"]["speaker_name"] == "Test Speaker Two"
    assert len(consent_store) == 1


async def test_the_signed_document_is_served_back_and_its_reading_audited(
    operator: tuple[dict[str, str], UUID],
    hosted_rows: CatalogueRows,
    consent_store: dict[str, bytes],
) -> None:
    headers, _ = operator
    voice = await hosted_rows.add("byok", state="disabled")
    with selected(HostingEngine()):
        async with _http() as http:
            await _record(http, headers, voice)
            document = await http.get(
                "/v1/ops/voices/hosted/clone-consent/document",
                headers=headers,
                params={"voice_id": voice},
            )
            not_a_document = await _record(http, headers, voice, document=b"not a pdf")
    assert document.status_code == 200 and document.content == PDF
    assert document.headers["content-type"] == "application/pdf"
    assert document.headers["cache-control"] == "no-store"
    assert len(await _audit_actors("ops.voice_clone_consent_document_read", voice)) == 1
    assert _code(not_a_document) == "voice_consent_document_format"


async def test_a_name_that_says_whose_voice_it_is_is_refused(
    operator: tuple[dict[str, str], UUID],
    hosted_rows: CatalogueRows,
    consent_store: dict[str, bytes],
) -> None:
    headers, _ = operator
    voice = await hosted_rows.add("byok", state="disabled")
    with selected(HostingEngine()):
        async with _http() as http:
            await _record(http, headers, voice, speaker="Srinivas Rao")
            refused = await http.patch(
                "/v1/ops/voices/hosted/display-name",
                headers=headers,
                json={"voice_id": voice, "display_label": "Srinivas"},
            )
    assert _code(refused) == "voice_clone_name_reveals_speaker"
    assert name_reveals_speaker("Voice of Rao", "Srinivas Rao")
    assert not name_reveals_speaker("Aditya", "K. Srinivas Rao")


async def test_a_client_sees_the_name_we_gave_it_and_never_the_providers(
    operator: tuple[dict[str, str], UUID],
    hosted_rows: CatalogueRows,
    consent_store: dict[str, bytes],
    priced: None,
) -> None:
    headers, _ = operator
    voice = await hosted_rows.add("byok", label="Sri (instant clone)", state="disabled")
    with selected(HostingEngine()):
        async with _http() as http:
            await _record(http, headers, voice)
            await http.patch(
                "/v1/ops/voices/hosted/display-name",
                headers=headers,
                json={"voice_id": voice, "display_label": "Aditya"},
            )
            enabled = await http.patch(
                "/v1/ops/voices/hosted",
                headers=headers,
                json={"voice_id": voice, "state": "enabled"},
            )
        assert enabled.status_code == 200, enabled.text
        client = Principal(
            realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner"
        )
        catalogue = await engine_catalogue(client)
    offered = {v.voice_id: v for v in catalogue.voices}
    assert offered[voice].label == "Aditya" and offered[voice].rung == "studio"
    assert "Sri" not in offered[voice].model_dump_json()


async def test_a_clone_whose_consent_is_cleared_leaves_the_picker_even_if_left_enabled(
    hosted_rows: CatalogueRows, priced: None
) -> None:
    """Defence in depth: the offer itself checks the consent, so a voice switched on by any
    other door (the assistant's curation action) is still not offered without it."""
    voice = await hosted_rows.add("byok", state="enabled")
    async with admin_session() as session:
        await session.execute(
            text(
                "UPDATE platform_voice_catalog SET person_clone = true, display_label = 'Aditya' "
                "WHERE voice_id = :v"
            ),
            {"v": voice},
        )
    with selected(HostingEngine()):
        client = Principal(
            realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner"
        )
        catalogue = await engine_catalogue(client)
    assert voice not in {v.voice_id for v in catalogue.voices}


async def test_the_agents_on_a_voice_are_read_one_voice_at_a_time(
    operator: tuple[dict[str, str], UUID], hosted_rows: CatalogueRows
) -> None:
    headers, _ = operator
    voice = await hosted_rows.add("engine")
    with selected(HostingEngine()):
        async with _http() as http:
            empty = await http.get(
                "/v1/ops/voices/hosted/agents", headers=headers, params={"voice_id": voice}
            )
            unknown = await http.get(
                "/v1/ops/voices/hosted/agents",
                headers=headers,
                params={"voice_id": "engine:does-not-exist"},
            )
    assert empty.status_code == 200 and empty.json() == {"voice_id": voice, "agents": []}
    assert unknown.status_code == 404


async def test_the_list_carries_the_ids_and_facts_the_detail_shows(
    operator: tuple[dict[str, str], UUID], hosted_rows: CatalogueRows
) -> None:
    headers, _ = operator
    voice = await hosted_rows.add("engine", label="Anjali", accent="en-IN", vendor_id="anj-1")
    with selected(HostingEngine()):
        async with _http() as http:
            listed = await http.get("/v1/ops/voices/hosted", headers=headers)
    row = {v["voice_id"]: v for v in listed.json()["voices"]}[voice]
    assert row["vendor_id"] == "anj-1" and row["vendor_label"] == "Anjali"
    assert row["accent_label"] == "Indian English"
    assert row["person_clone"] is False and row["clone_blocker"] is None
