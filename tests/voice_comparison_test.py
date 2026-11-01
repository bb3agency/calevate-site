"""The blind Cartesia / Sarvam voice comparison (D-946): admin only, no client touched.

The Sarvam key goes into a comparison workspace of its own, never our developer workspace
(which holds the Cartesia key free-trial Studio agents speak on) and never a client's. A round
pairs every Cartesia voice with every Sarvam voice on every sentence; what the page renders
before the round is finished names no voice and no provider. Clips are cached, so a pair
heard twice costs the provider nothing more.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid
from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.errors import ProblemError
from apps.api.core.platform_config import is_secret_key
from apps.api.engine.catalogue import HostedVoice, PreviewAudio
from apps.api.engine.thinnest_customers import Customer
from apps.api.engine.thinnest_workspace import current_workspace
from apps.api.main import app
from apps.api.ops import voice_comparison as vc
from apps.api.ops import voice_comparison_routes as routes
from apps.api.ops.secret_probes import PROBES
from apps.api.ops.secret_service import manageable_secret_keys
from apps.workers import storage, voice_comparison_key
from calevate_shared.engine import ByokVoiceTuning
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.hosted_voice_fakes import (
    MP3,
    OFF_KEY,
    READY_KEY,
    WAV,
    CatalogueRows,
    HostingEngine,
    selected,
)

LAB = "org_voice-lab-fixture"
DEVELOPER = "org_developer-fixture"
SARVAM_KEY = "sk_sarvam_" + "x" * 24
SARVAM = [
    HostedVoice(voice_id="anushka", label="Anushka", source="byok", language="te-IN"),
    HostedVoice(voice_id="abhilash", label="Abhilash", source="byok", language="te-IN"),
]


class LabEngine(HostingEngine):
    """Speaks MP3 where Cartesia is (our developer workspace) and WAV in the lab, as the
    platform does for Sarvam (bring-your-own-keys.md:321), listing Sarvam voices there."""

    async def list_own_key_voices(self) -> Any:
        listing = await super().list_own_key_voices()
        if current_workspace() == LAB:
            return listing.model_copy(update={"voices": SARVAM, "provider": "sarvam"})
        return listing

    async def preview_own_key_voice(
        self,
        *,
        voice_id: str,
        text: str | None,
        language: str | None,
        tuning: ByokVoiceTuning | None = None,
    ) -> PreviewAudio:
        await super().preview_own_key_voice(
            voice_id=voice_id, text=text, language=language, tuning=tuning
        )
        if current_workspace() == LAB:
            return PreviewAudio(data=WAV, content_type="audio/wav")
        return PreviewAudio(data=MP3, content_type="audio/mpeg")


class FakeCustomers:
    def __init__(self, *, exists: bool = False) -> None:
        self.exists = exists
        self.created: list[str] = []

    async def developer_workspace_id(self) -> str:
        return DEVELOPER

    async def find(self, external_id: str, *, archived: bool = False) -> Customer | None:
        if external_id != vc.VOICE_LAB_REF or not self.exists:
            return None
        return Customer(
            workspace_id=LAB, external_id=external_id, archived_at=None, erase_after=None
        )

    async def create(self, *, name: str, external_id: str, timezone: str) -> Customer:
        self.created.append(external_id)
        self.exists = True
        return Customer(
            workspace_id=LAB, external_id=external_id, archived_at=None, erase_after=None
        )


@pytest.fixture
def customers(monkeypatch: pytest.MonkeyPatch) -> FakeCustomers:
    fake = FakeCustomers()
    monkeypatch.setattr(vc, "thinnest_customers", lambda: fake)
    return fake


@pytest.fixture
def sarvam_key(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    from apps.api.core.settings import get_settings

    monkeypatch.setenv("SARVAM_VOICE_API_KEY", SARVAM_KEY)
    get_settings.cache_clear()
    yield
    monkeypatch.delenv("SARVAM_VOICE_API_KEY", raising=False)
    get_settings.cache_clear()


@pytest.fixture
def clips(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    stored: dict[str, bytes] = {}

    async def _store(*, key: str, data: bytes, content_type: str) -> str:
        stored[key] = data
        return key

    async def _read(key: str) -> bytes | None:
        return stored.get(key)

    monkeypatch.setattr(storage, "store_voice_preview", _store)
    monkeypatch.setattr(storage, "read_voice_preview", _read)
    return stored


@pytest.fixture
async def admin() -> AsyncIterator[dict[str, str]]:
    from apps.api.db.session import untenanted_session

    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    yield {"Authorization": f"Bearer dev:admin:{admin_id}"}


@pytest.fixture
async def cartesia_rows() -> AsyncIterator[list[str]]:
    rows = CatalogueRows()
    vendor_ids = [f"car{uuid.uuid4().hex[:8]}", f"car{uuid.uuid4().hex[:8]}"]
    for i, vendor in enumerate(vendor_ids):
        await rows.add("byok", label=f"Cartesia {i}", vendor_id=vendor, accent="te")
    yield vendor_ids
    await rows.cleanup()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _lab_engine(*, lab_ready: bool = True) -> LabEngine:
    engine = LabEngine()
    sarvam_ready = READY_KEY.model_copy(update={"voice_provider": "sarvam"})
    engine.workspace_keys[LAB] = sarvam_ready if lab_ready else OFF_KEY
    return engine


SETUP = {"X-Confirm-Action": routes.SETUP_CONFIRMATION}


# --- the credential ---------------------------------------------------------------------


def test_the_sarvam_voice_key_is_a_sealed_console_credential_with_a_probe() -> None:
    """Stored like the Cartesia key: a secret the console seals and rotates, never a config
    value, with the same Sarvam probe the extraction key has."""
    assert is_secret_key(vc.SARVAM_VOICE_SECRET)
    assert vc.SARVAM_VOICE_SECRET in manageable_secret_keys()
    assert PROBES[vc.SARVAM_VOICE_SECRET].url == PROBES["sarvam_api_key"].url


async def test_set_up_installs_sarvam_only_in_the_comparison_workspace(
    admin: dict[str, str],
    customers: FakeCustomers,
    sarvam_key: None,
    caplog: pytest.LogCaptureFixture,
) -> None:
    engine = _lab_engine(lab_ready=False)
    caplog.set_level(logging.DEBUG)
    with selected(engine):
        async with _client() as http:
            refused = await http.post("/v1/ops/voice-comparison/setup", headers=admin)
            done = await http.post("/v1/ops/voice-comparison/setup", headers={**admin, **SETUP})
    assert refused.json()["type"].rsplit("/", 1)[-1] == "step_up_required"
    assert done.status_code == 200, done.text
    body = done.json()
    assert body["sarvam_ready"] is True and body["voice_provider"] == "sarvam"
    assert customers.created == [vc.VOICE_LAB_REF]
    # Only the lab: never our developer workspace (None) and never a client's.
    assert engine.installed == [("sarvam", None)]
    assert engine.installed_in == [LAB]
    assert engine.enabled_in == [LAB]
    assert engine.key_state.voice_provider == "cartesia"
    assert SARVAM_KEY not in caplog.text
    assert SARVAM_KEY not in done.text


async def test_set_up_without_a_stored_key_is_refused_before_anything_is_made(
    admin: dict[str, str], customers: FakeCustomers
) -> None:
    engine = _lab_engine()
    with selected(engine):
        async with _client() as http:
            response = await http.post("/v1/ops/voice-comparison/setup", headers={**admin, **SETUP})
    assert response.json()["type"].rsplit("/", 1)[-1] == "voice_comparison_no_sarvam_key"
    assert customers.created == [] and engine.installed == []


async def test_a_lab_that_resolves_to_our_own_workspace_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class Same(FakeCustomers):
        async def find(self, external_id: str, *, archived: bool = False) -> Customer | None:
            return Customer(
                workspace_id=DEVELOPER, external_id=external_id, archived_at=None, erase_after=None
            )

    monkeypatch.setattr(vc, "thinnest_customers", lambda: Same())
    with pytest.raises(ProblemError) as raised:
        await vc.find_voice_lab()
    assert raised.value.code == "voice_comparison_workspace_is_ours"


async def test_a_rotation_reinstalls_the_key_in_the_lab(
    customers: FakeCustomers, monkeypatch: pytest.MonkeyPatch
) -> None:
    customers.exists = True
    engine = _lab_engine()

    async def _key() -> str:
        return SARVAM_KEY

    monkeypatch.setattr(voice_comparison_key, "_current_key", _key)
    with selected(engine):
        assert await voice_comparison_key.push_voice_comparison_key({}, {"version": 2}) == "pushed"
    assert engine.installed_in == [LAB]


async def test_a_rotation_with_no_lab_pushes_nothing(
    customers: FakeCustomers, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = _lab_engine()

    async def _key() -> str:
        return SARVAM_KEY

    monkeypatch.setattr(voice_comparison_key, "_current_key", _key)
    with selected(engine):
        assert await voice_comparison_key.push_voice_comparison_key({}, {}) == "no_workspace"
    assert engine.installed == []


# --- catalogue and sentences --------------------------------------------------------------


async def test_the_sarvam_voices_come_from_the_platforms_listing_in_the_lab(
    admin: dict[str, str], customers: FakeCustomers, cartesia_rows: list[str]
) -> None:
    customers.exists = True
    engine = _lab_engine()
    with selected(engine):
        async with _client() as http:
            response = await http.get("/v1/ops/voice-comparison/voices", headers=admin)
    body = response.json()
    assert [v["vendor_id"] for v in body["sarvam"]] == ["anushka", "abhilash"]
    assert set(cartesia_rows) <= {v["vendor_id"] for v in body["cartesia"]}
    assert LAB in engine.listed_in


async def test_the_default_sentences_are_our_telugu_spoken_style_lines(
    admin: dict[str, str],
) -> None:
    async with _client() as http:
        response = await http.get("/v1/ops/voice-comparison/sentences", headers=admin)
    sentences = response.json()["sentences"]
    assert 5 <= len(sentences) <= vc.MAX_SENTENCES
    assert all(len(s) <= vc.MAX_SENTENCE_CHARS for s in sentences)
    # Telugu letters, and the number rules' phrases are among them.
    assert all(any("ఀ" <= ch <= "౿" for ch in s) for s in sentences)
    assert any("రూపీస్" in s for s in sentences)


def test_every_pair_crosses_providers_and_the_sides_are_drawn() -> None:
    trials = vc.plan_trials(2, 3, 4)
    assert len(trials) == 2 * 3 * 4
    for _, a, b in trials:
        assert (a < 2) != (b < 2)
    assert any(a < 2 for _, a, _ in trials) and any(a >= 2 for _, a, _ in trials)


# --- a round, end to end -------------------------------------------------------------------


async def _round(
    http: AsyncClient, admin: dict[str, str], cartesia: list[str], sentences: list[str]
) -> dict[str, Any]:
    response = await http.post(
        "/v1/ops/voice-comparison/rounds",
        headers=admin,
        json={
            "title": "Telugu test",
            "cartesia_voice_ids": cartesia,
            "sarvam_voice_ids": ["anushka"],
            "sentences": sentences,
        },
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


async def _drop(round_id: str) -> None:
    from apps.api.db.session import admin_session

    async with admin_session() as session:
        await session.execute(
            text("DELETE FROM platform_voice_comparison_rounds WHERE id = :id"),
            {"id": UUID(round_id)},
        )


async def test_the_page_is_blind_until_the_round_is_finished(
    admin: dict[str, str],
    customers: FakeCustomers,
    cartesia_rows: list[str],
    clips: dict[str, bytes],
) -> None:
    customers.exists = True
    engine = _lab_engine()
    sentences = ["నమస్కారం అండి", "వన్ ట్వంటీ రూపీస్"]
    with selected(engine):
        async with _client() as http:
            created = await _round(http, admin, cartesia_rows, sentences)
            try:
                read = (
                    await http.get(
                        f"/v1/ops/voice-comparison/rounds/{created['id']}", headers=admin
                    )
                ).json()
                early = await http.get(
                    f"/v1/ops/voice-comparison/rounds/{created['id']}/summary", headers=admin
                )
                early_csv = await http.get(
                    f"/v1/ops/voice-comparison/rounds/{created['id']}/export", headers=admin
                )
            finally:
                await _drop(created["id"])
    assert created["pairs"] == 2 * 1 * 2 == len(read["trials"])
    rendered = str(created) + str(read)
    for secret in (*cartesia_rows, "anushka", "Anushka", "Cartesia 0", "provider", "vendor"):
        assert secret not in rendered
    assert set(read["trials"][0]) == {
        "id",
        "position",
        "sentence",
        "rating_a",
        "rating_b",
        "preference",
        "rated",
    }
    assert early.status_code == 409 and early_csv.status_code == 409


async def test_rating_finishing_revealing_and_exporting_a_round(
    admin: dict[str, str],
    customers: FakeCustomers,
    cartesia_rows: list[str],
    clips: dict[str, bytes],
) -> None:
    customers.exists = True
    engine = _lab_engine()
    sentence = "వన్ ట్వంటీ రూపీస్"
    with selected(engine):
        async with _client() as http:
            created = await _round(http, admin, cartesia_rows[:1], [sentence])
            round_id = created["id"]
            try:
                (trial,) = created["trials"]
                url = f"/v1/ops/voice-comparison/trials/{trial['id']}"
                a = await http.get(f"{url}/audio", headers=admin, params={"side": "a"})
                b = await http.get(f"{url}/audio", headers=admin, params={"side": "b"})
                again = await http.get(f"{url}/audio", headers=admin, params={"side": "a"})
                unfinished = await http.post(
                    f"/v1/ops/voice-comparison/rounds/{round_id}/finish", headers=admin
                )
                bad = await http.put(
                    url, headers=admin, json={"rating_a": 6, "rating_b": 3, "preference": "a"}
                )
                rated = await http.put(
                    url, headers=admin, json={"rating_a": 4, "rating_b": 2, "preference": "a"}
                )
                finished = await http.post(
                    f"/v1/ops/voice-comparison/rounds/{round_id}/finish", headers=admin
                )
                late = await http.put(
                    url, headers=admin, json={"rating_a": 1, "rating_b": 1, "preference": "b"}
                )
                summary = await http.get(
                    f"/v1/ops/voice-comparison/rounds/{round_id}/summary", headers=admin
                )
                exported = await http.get(
                    f"/v1/ops/voice-comparison/rounds/{round_id}/export", headers=admin
                )
                audits = await _audit_counts(round_id, str(trial["id"]))
            finally:
                await _drop(round_id)
    # One clip per side, spoken once each and then served from the cache.
    assert len(engine.previews) == 2
    assert {a.headers["content-type"], b.headers["content-type"]} == {"audio/mpeg", "audio/wav"}
    assert again.content == a.content
    assert all(line == (sentence, "te-IN") for line in engine.preview_lines)
    assert unfinished.status_code == 409
    assert bad.status_code == 422
    assert rated.status_code == 200 and rated.json()["rated"] is True
    assert finished.json()["finished_at"] is not None
    assert late.status_code == 409
    body = summary.json()
    by_provider = {p["provider"]: p for p in body["providers"]}
    preferred_provider = next(v["provider"] for v in body["voices"] if v["preferred"] == 1)
    assert by_provider[preferred_provider]["mean_naturalness"] == 4.0
    assert by_provider["sarvam"]["characters"] == len(sentence)
    assert by_provider["cartesia"]["characters"] == len(sentence)
    rows = list(csv.DictReader(io.StringIO(exported.text)))
    assert exported.headers["content-type"].startswith("text/csv")
    assert len(rows) == 1 and rows[0]["preferred_provider"] == preferred_provider
    assert rows[0]["naturalness_a"] == "4" and rows[0]["sentence"] == sentence
    assert audits == {
        "ops.voice_comparison_started": 1,
        "ops.voice_comparison_rated": 1,
        "ops.voice_comparison_finished": 1,
        "ops.voice_comparison_exported": 1,
    }


async def _audit_counts(round_id: str, trial_id: str) -> dict[str, int]:
    """This round's and this pair's audit rows, by action."""
    from apps.api.db.session import untenanted_session

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, count(*) FROM audit_log "
                    "WHERE object_id IN (:r, :t) GROUP BY action"
                ),
                {"r": round_id, "t": trial_id},
            )
        ).all()
    return {str(r[0]): int(r[1]) for r in rows}


async def test_a_round_with_an_unlisted_voice_is_refused(
    admin: dict[str, str], customers: FakeCustomers, cartesia_rows: list[str]
) -> None:
    customers.exists = True
    with selected(_lab_engine()):
        async with _client() as http:
            response = await http.post(
                "/v1/ops/voice-comparison/rounds",
                headers=admin,
                json={
                    "cartesia_voice_ids": cartesia_rows[:1],
                    "sarvam_voice_ids": ["not-a-sarvam-voice"],
                    "sentences": ["నమస్కారం"],
                },
            )
    assert response.json()["type"].rsplit("/", 1)[-1] == "voice_comparison_unknown_voice"


async def test_a_client_cannot_reach_the_comparison() -> None:
    client = {"Authorization": f"Bearer dev:client:{uuid.uuid4()}"}
    async with _client() as http:
        for path in ("/setup", "/voices", "/sentences", "/rounds"):
            response = await http.get(f"/v1/ops/voice-comparison{path}", headers=client)
            assert response.status_code in {401, 403}, path


def test_a_csv_cell_cannot_start_a_formula() -> None:
    from types import SimpleNamespace
    from typing import cast

    round_ = SimpleNamespace(
        voices=[
            {"provider": "cartesia", "vendor_id": "c", "label": "=HYPERLINK()"},
            {"provider": "sarvam", "vendor_id": "s", "label": "S"},
        ],
        sentences=["=1+1"],
    )
    trial = SimpleNamespace(
        position=1,
        sentence_index=0,
        voice_a=0,
        voice_b=1,
        rating_a=3,
        rating_b=3,
        preference="none",
        rated_at=None,
        rated_by=None,
    )
    out = vc.export_csv(cast(Any, round_), [cast(Any, trial)])
    assert "\n=1+1" not in out and ",=HYPERLINK" not in out
