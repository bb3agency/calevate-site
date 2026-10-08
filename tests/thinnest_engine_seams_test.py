"""The last ThinnestAI seams (D-678, D-687): who answers a number, knowledge longer than one
document, and an agent's own choice of a hosted voice and the engine's model.

Vendor shapes are the mirror's (`thinnest-findings/mirror/pages/api-reference/`):
`voices-and-models.md:67-87` (numbers), `knowledge.md:9-52` (documents, 200,000-character
text cap), `agents.md:105-110,152-161` (`model`, `voice.voice`).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import engine_choice, lifecycle, prompts
from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import DICTATED_SPEECH_CAPABILITIES, FakeEngine
from apps.api.engine.thinnest import (
    BASE_URL,
    KB_TEXT_MAX_CHARS,
    KB_TOTAL_MAX_CHARS,
    THINNEST_CAPABILITIES,
    ThinnestEngine,
)
from calevate_shared.engine import AgentConfig, EngineAgentRef, KBSourceRef
from sqlalchemy import text
from tests.conftest import accept_agreements
from tests.hosted_voice_fakes import (
    OFF_KEY,
    READY_KEY,
    CatalogueRows,
    HostingEngine,
    selected,
)

Handler = Callable[[httpx.Request], httpx.Response]


def _engine(handler: Handler) -> ThinnestEngine:
    return ThinnestEngine(
        api_key="ta_live_test",
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )


def _path(request: httpx.Request) -> str:
    return request.url.path.removeprefix("/api/v1")


# --- 1. numbers: which agent answers -----------------------------------------------


async def test_a_listed_number_names_the_agent_answering_it() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert _path(request) == "/phone-numbers"
        return httpx.Response(
            200,
            json={
                "items": [
                    {"number": "918012345678", "source": "rented", "agent": "ag_5c4a"},
                    {"number": "918012345679", "source": "brought", "agent": None},
                ],
                "nextCursor": None,
            },
        )

    numbers = await _engine(handler).list_engine_numbers()
    assert [(n.e164, n.answering_agent_ref) for n in numbers] == [
        ("+918012345678", "ag_5c4a"),
        ("+918012345679", None),
    ]


# --- 2. knowledge longer than one document ------------------------------------------


class _KnowledgeStore:
    """`/agents/{id}/knowledge` as knowledge.md:38-44 describes it, in memory."""

    def __init__(self, *, refuse_post: int | None = None) -> None:
        self.docs: dict[str, dict[str, Any]] = {}
        self.posts = 0
        self.deleted: list[str] = []
        self._refuse_post = refuse_post

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = _path(request)
        if request.method == "POST" and path == "/agents/ag_1/knowledge":
            self.posts += 1
            if self._refuse_post == self.posts:
                return httpx.Response(400, json={"error": "text"})
            body = json.loads(request.content)
            assert len(body["text"]) <= KB_TEXT_MAX_CHARS
            doc_id = f"doc_{self.posts}"
            self.docs[doc_id] = {"id": doc_id, "title": body["title"], "status": "ready"}
            return httpx.Response(201, json=self.docs[doc_id])
        if request.method == "GET" and path == "/agents/ag_1/knowledge":
            return httpx.Response(
                200, json={"items": list(reversed(self.docs.values())), "nextCursor": None}
            )
        match = re.fullmatch(r"/agents/ag_1/knowledge/(.+)", path)
        if request.method == "DELETE" and match:
            if self.docs.pop(match[1], None) is None:
                return httpx.Response(404, json={"error": "not found"})
            self.deleted.append(match[1])
            return httpx.Response(204)
        return httpx.Response(404, json={"error": "x"})


def _long_text(parts: int) -> str:
    chunk = "word " * 1_000
    count = (KB_TEXT_MAX_CHARS * parts) // (len(chunk) + 2) - 1
    return "\n\n".join([chunk.strip()] * count)


def _source(body: str) -> KBSourceRef:
    return KBSourceRef(kb_id=str(uuid.uuid4()), title="Price list", text=body)


async def test_text_that_fits_is_one_document_and_one_plain_handle() -> None:
    store = _KnowledgeStore()
    engine = _engine(store)
    handle = await engine.attach_kb("ag_1", _source("A 2BHK starts at 80 lakh."))
    assert handle == "doc_1" and store.posts == 1
    assert await engine.list_kb("ag_1") == ["doc_1"]


async def test_longer_text_is_split_and_listed_back_as_one_handle() -> None:
    store = _KnowledgeStore()
    engine = _engine(store)
    body = _long_text(3)
    assert len(body) > KB_TEXT_MAX_CHARS
    handle = await engine.attach_kb("ag_1", _source(body))
    assert store.posts >= 2
    assert await engine.list_kb("ag_1") == [handle]

    await engine.detach_kb("ag_1", handle)
    assert store.docs == {} and len(store.deleted) == store.posts
    assert await engine.list_kb("ag_1") == []


async def test_a_part_refused_midway_removes_the_parts_already_added() -> None:
    store = _KnowledgeStore(refuse_post=2)
    with pytest.raises(ProblemError) as caught:
        await _engine(store).attach_kb("ag_1", _source(_long_text(3)))
    assert caught.value.code == "engine_kb_part_failed"
    assert "part 2" in (caught.value.detail or "")
    assert store.docs == {} and store.deleted == ["doc_1"]


async def test_text_over_the_total_bound_is_refused_before_any_request() -> None:
    store = _KnowledgeStore()
    with pytest.raises(ProblemError) as caught:
        await _engine(store).attach_kb("ag_1", _source("x" * (KB_TOTAL_MAX_CHARS + 1)))
    assert caught.value.code == "engine_kb_text_too_long"
    assert store.posts == 0


async def test_an_incomplete_set_of_parts_is_listed_as_loose_documents() -> None:
    store = _KnowledgeStore()
    engine = _engine(store)
    handle = await engine.attach_kb("ag_1", _source(_long_text(3)))
    first = handle.removeprefix("cv-parts:").split(",")[0]
    store.docs.pop(first)
    listed = await engine.list_kb("ag_1")
    assert handle not in listed and first not in listed and len(listed) == store.posts - 1


async def test_detaching_a_handle_the_engine_does_not_hold_raises() -> None:
    with pytest.raises(ProblemError):
        await _engine(_KnowledgeStore()).detach_kb("ag_1", "cv-parts:doc_8,doc_9")


# --- 3. the agent's own voice and model ---------------------------------------------
# D-687: the voice is one of the operator's hosted catalogue rows (`engine:<id>` for Clear,
# `byok:<id>` for Studio); the model is the engine's own.


def _cfg(**update: Any) -> AgentConfig:
    base = AgentConfig(
        tenant_id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        name="Sunrise Clinic",
        direction="inbound",
        system_prompt="You are the receptionist.",
        opening_line="Idi AI assistant.",
    )
    return base.model_copy(update=update)


async def test_the_chosen_voice_and_model_are_sent_and_nothing_when_none_is_chosen() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "ag_1"})

    engine = _engine(handler)
    await engine.update_agent("ag_1", _cfg(engine_voice_id="priya", engine_model_id="prana-voice"))
    await engine.update_agent("ag_1", _cfg())
    chosen, default = bodies
    assert chosen["voice"]["voice"] == "priya" and chosen["model"] == "prana-voice"
    assert "voice" not in default["voice"] and "model" not in default


async def test_a_studio_voice_is_set_through_the_own_key_route_in_its_workspace() -> None:
    """set-agent-byok-voice.md:322-460: `PUT /agents/{id}/byok-voice {voice}` with the
    workspace header; the agent body names no catalogue voice. The handle comes back scoped."""
    seen: list[tuple[str, str, str | None, dict[str, Any]]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else {}
        seen.append(
            (request.method, _path(request), request.headers.get("Thinnest-Workspace"), body)
        )
        if request.method == "GET":
            return httpx.Response(200, json={"items": [], "nextCursor": None})
        return httpx.Response(201, json={"id": "ag_9", "voice": "cv-1"})

    cfg = _cfg(engine_byok_voice_id="cv-1", engine_workspace="org_studio")
    ref = await _engine(handler).create_agent(cfg)
    assert ref == "ag_9@org_studio"
    listing, create, voice = seen
    assert listing[:3] == ("GET", "/agents", "org_studio")
    assert create[:3] == ("POST", "/agents", "org_studio")
    assert "voice" not in create[3]["voice"]
    assert voice == ("PUT", "/agents/ag_9/byok-voice", "org_studio", {"voice": "cv-1"})


async def test_an_agent_cannot_be_updated_into_another_workspace() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be sent")

    with pytest.raises(ProblemError) as caught:
        await _engine(handler).update_agent(
            "ag_1", _cfg(engine_byok_voice_id="cv-1", engine_workspace="org_studio")
        )
    assert caught.value.code == "engine_agent_workspace_mismatch"


async def test_two_voices_on_one_agent_are_refused() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request may be sent")

    with pytest.raises(ProblemError) as caught:
        await _engine(handler).update_agent(
            "ag_1", _cfg(engine_voice_id="a", engine_byok_voice_id="b")
        )
    assert caught.value.code == "engine_voice_choice_conflict"


@pytest.mark.parametrize("status", [400, 409])
async def test_a_refused_studio_voice_is_said_in_our_words(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/byok-voice"):
            return httpx.Response(
                status, json={"error": "This workspace is not using its own keys."}
            )
        return httpx.Response(200, json={"id": "ag_1"})

    with pytest.raises(ProblemError) as caught:
        await _engine(handler).update_agent(
            "ag_1@org_studio", _cfg(engine_byok_voice_id="cv-1", engine_workspace="org_studio")
        )
    assert caught.value.code == "engine_byok_voice_unavailable"


async def test_another_failure_on_the_studio_voice_route_is_not_reworded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/byok-voice"):
            return httpx.Response(404, json={"error": "Agent not found."})
        return httpx.Response(200, json={"id": "ag_1"})

    with pytest.raises(ProblemError) as caught:
        await _engine(handler).update_agent(
            "ag_1@org_studio", _cfg(engine_byok_voice_id="cv-1", engine_workspace="org_studio")
        )
    assert caught.value.code != "engine_byok_voice_unavailable"


@pytest.fixture
def attested(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """The attested rate keys, as a set a test edits: the base minute and both sold keys."""
    keys = {"platform", "studio", "byok_voice"}

    async def _keys(session: Any, *, engine: str, at: Any) -> frozenset[str]:
        assert engine == "thinnest"
        return frozenset(keys)

    async def _billable(session: Any, *, engine: str, rate_key: str, at: Any) -> bool:
        return rate_key in keys

    from apps.api.agents import engine_limits

    monkeypatch.setattr(engine_choice, "attested_rate_keys", _keys)
    monkeypatch.setattr(engine_choice, "tts_price_is_billable", lambda provider: True)
    monkeypatch.setattr(engine_limits, "engine_minute_is_billable", _billable)
    return keys


async def _choose(engine: FakeEngine | None = None, *, for_publish: bool = False, **kw: Any) -> str:
    async with tenant_session(uuid.uuid4()) as session:
        return await engine_choice.require_engine_choice(
            session, engine or HostingEngine(), for_publish=for_publish, **kw
        )


async def test_no_choice_is_the_base_rate_without_reading_the_catalogue(
    attested: set[str],
) -> None:
    engine = HostingEngine()
    assert await _choose(engine, voice_id=None, model_id=None) == "platform"
    assert engine.reads == 0


async def test_a_clear_voice_meters_at_the_studio_band_and_a_studio_voice_at_its_own_key(
    attested: set[str], hosted_rows: CatalogueRows, studio_workspace: str
) -> None:
    clear = await hosted_rows.add("engine")
    studio = await hosted_rows.add("byok")
    assert await _choose(voice_id=clear, model_id="gpt-4.1") == "studio"
    assert await _choose(voice_id=studio, model_id="prana-voice", for_publish=True) == (
        "byok_voice"
    )
    assert await _choose(voice_id=None, model_id="prana-voice") == "platform"


@pytest.mark.parametrize(
    ("case", "model_id", "code"),
    [
        ("raw", None, engine_choice.VOICE_NOT_IN_CATALOGUE),
        ("missing", None, engine_choice.VOICE_NOT_IN_CATALOGUE),
        ("disabled", None, engine_choice.VOICE_NOT_ON_OFFER),
        ("not_added", None, engine_choice.VOICE_NOT_ON_OFFER),
        ("withdrawn", None, engine_choice.VOICE_NOT_ON_OFFER),
        (None, "missing", engine_choice.MODEL_NOT_IN_CATALOGUE),
        (None, "gpt-slow", engine_choice.MODEL_NOT_CALL_CAPABLE),
        (None, "gpt-x", engine_choice.MODEL_NOT_ON_PLAN),
    ],
)
async def test_a_choice_that_is_not_allowed_is_refused_by_name(
    attested: set[str],
    hosted_rows: CatalogueRows,
    case: str | None,
    model_id: str | None,
    code: str,
) -> None:
    voice: str | None = None
    if case == "raw":
        voice = "priya"
    elif case == "missing":
        voice = "engine:not-in-the-table"
    elif case == "disabled":
        voice = await hosted_rows.add("engine", state="disabled")
    elif case == "not_added":
        voice = await hosted_rows.add("engine", origin="synced")
    elif case == "withdrawn":
        voice = await hosted_rows.add("engine", withdrawn=True)
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id=voice, model_id=model_id)
    assert caught.value.code == code
    assert "ThinnestAI" not in (caught.value.detail or "")


async def test_an_unpriced_rung_is_refused_as_unpriced(
    attested: set[str], hosted_rows: CatalogueRows
) -> None:
    attested.discard("studio")
    voice = await hosted_rows.add("engine")
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id=voice, model_id=None)
    assert caught.value.code == engine_choice.VOICE_TIER_UNPRICED


async def test_a_studio_voice_without_a_studio_workspace_is_refused_plainly(
    attested: set[str], hosted_rows: CatalogueRows
) -> None:
    voice = await hosted_rows.add("byok")
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id=voice, model_id=None)
    assert caught.value.code == "engine_studio_workspace_missing"
    assert "Cartesia" not in (caught.value.detail or "")


async def test_a_studio_voice_runs_only_on_the_standard_models(
    attested: set[str], hosted_rows: CatalogueRows, studio_workspace: str
) -> None:
    """bring-your-own-keys.md:44-63 (07b): a voice-only workspace answers on its low-cost
    models, and setting another is a 400."""
    voice = await hosted_rows.add("byok")
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id=voice, model_id="gpt-4.1")
    assert caught.value.code == engine_choice.MODEL_NOT_WITH_OWN_VOICE


async def test_a_studio_publish_needs_the_engine_to_say_the_key_is_live(
    attested: set[str], hosted_rows: CatalogueRows, studio_workspace: str
) -> None:
    voice = await hosted_rows.add("byok")
    for state in (OFF_KEY, READY_KEY.model_copy(update={"voice_provider": "elevenlabs"})):
        with pytest.raises(ProblemError) as caught:
            await _choose(
                HostingEngine(key_state=state), voice_id=voice, model_id=None, for_publish=True
            )
        assert caught.value.code == engine_choice.STUDIO_KEY_NOT_READY
    # A draft save does not ask the engine.
    assert await _choose(HostingEngine(key_state=OFF_KEY), voice_id=voice, model_id=None) == (
        "byok_voice"
    )


async def test_a_studio_publish_with_the_workspace_unset_is_refused_before_any_read(
    attested: set[str], hosted_rows: CatalogueRows, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The workspace setting can be cleared between the voice check and the live check."""
    voice = await hosted_rows.add("byok")
    monkeypatch.setattr(engine_choice, "studio_workspace_ready", lambda: True)
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id=voice, model_id=None, for_publish=True)
    assert caught.value.code == "engine_studio_workspace_missing"


async def test_a_model_missing_from_a_short_list_is_not_called_unknown(
    attested: set[str],
) -> None:
    with pytest.raises(ProblemError) as caught:
        await _choose(HostingEngine(complete=False), voice_id=None, model_id="nobody")
    assert caught.value.code == engine_choice.CATALOGUE_INCOMPLETE


async def test_a_choice_is_refused_where_the_engine_runs_our_voices_and_models() -> None:
    for kw, code in (
        ({"voice_id": "engine:x", "model_id": None}, engine_choice.VOICE_CHOICE_NOT_OFFERED),
        ({"voice_id": None, "model_id": "prana-voice"}, engine_choice.MODEL_CHOICE_NOT_OFFERED),
    ):
        with pytest.raises(ProblemError) as caught:
            await _choose(FakeEngine(), **kw)
        assert caught.value.code == code


async def test_a_dictated_leg_that_hosts_nothing_refuses_a_choice(attested: set[str]) -> None:
    dictated = FakeEngine(name="thinnest", capabilities=DICTATED_SPEECH_CAPABILITIES)
    for kw, code in (
        ({"voice_id": "engine:x", "model_id": None}, engine_choice.VOICE_CHOICE_NOT_OFFERED),
        ({"voice_id": None, "model_id": "prana-voice"}, engine_choice.MODEL_CHOICE_NOT_OFFERED),
    ):
        with pytest.raises(ProblemError) as caught:
            await _choose(dictated, **kw)
        assert caught.value.code == code


# --- the publish path --------------------------------------------------------------


@pytest.fixture
def no_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.agents import service

    async def _ensure(session: Any, *, engine: str, engine_agent_ref: str) -> None:
        return None

    async def _retire(*, agent_id: Any, ref: Any) -> int:
        return 0

    monkeypatch.setattr(service, "ensure_agent_webhook", _ensure)
    monkeypatch.setattr(service, "ensure_agent_actions", _ensure)
    monkeypatch.setattr(service, "retire_in_call_actions", _retire)


async def _agent() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Choice Clinic",
        slug=f"chc-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    await accept_agreements(uuid.UUID(str(tenant_id)))
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="Greet in Telugu, then book.",
            notes=None,
            created_by=None,
        )
    return tenant_id, agent_id


async def _set_columns(tenant_id: uuid.UUID, agent_id: uuid.UUID, voice: Any, model: Any) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_voice_id = :v, engine_model_id = :m WHERE id = :a"),
            {"v": voice, "m": model, "a": agent_id},
        )


async def _route(tenant_id: uuid.UUID, ref: str) -> tuple[str, bool]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_rate_key, active FROM engine_agent_routes "
                    "WHERE engine_agent_ref = :r"
                ),
                {"r": ref},
            )
        ).one()
    return str(row[0]), bool(row[1])


async def _publish(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def test_publish_sends_a_clear_voice_in_our_workspace_and_meters_its_band(
    attested: set[str], no_webhook: None, hosted_rows: CatalogueRows
) -> None:
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine", vendor_id=f"asha-{uuid.uuid4().hex[:6]}")
    await _set_columns(tenant_id, agent_id, voice, "prana-voice")
    with selected(HostingEngine()) as engine:
        ref = await _publish(tenant_id, agent_id)
    assert isinstance(engine, HostingEngine)
    sent = engine.sent[-1]
    assert sent.engine_voice_id == voice.removeprefix("engine:")
    assert (sent.engine_byok_voice_id, sent.engine_workspace) == (None, None)
    assert sent.engine_model_id == "prana-voice"
    assert "@" not in ref and await _route(tenant_id, ref) == ("studio", True)


async def test_publish_puts_a_studio_voice_in_the_studio_workspace(
    attested: set[str], no_webhook: None, hosted_rows: CatalogueRows, studio_workspace: str
) -> None:
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("byok")
    await _set_columns(tenant_id, agent_id, voice, None)
    with selected(HostingEngine()) as engine:
        ref = await _publish(tenant_id, agent_id)
    assert isinstance(engine, HostingEngine)
    sent = engine.sent[-1]
    assert (sent.engine_voice_id, sent.engine_byok_voice_id) == (
        None,
        voice.removeprefix("byok:"),
    )
    assert sent.engine_workspace == studio_workspace and ref.endswith(f"@{studio_workspace}")
    assert await _route(tenant_id, ref) == ("byok_voice", True)


async def test_a_rung_switch_re_creates_the_agent_in_the_other_workspace(
    attested: set[str], no_webhook: None, hosted_rows: CatalogueRows, studio_workspace: str
) -> None:
    tenant_id, agent_id = await _agent()
    clear = await hosted_rows.add("engine")
    studio = await hosted_rows.add("byok")
    await _set_columns(tenant_id, agent_id, clear, None)
    with selected(HostingEngine()) as engine:
        first = await _publish(tenant_id, agent_id)
        await _set_columns(tenant_id, agent_id, studio, None)
        second = await _publish(tenant_id, agent_id)
    assert isinstance(engine, HostingEngine)
    assert engine.deleted == [first]
    assert second.endswith(f"@{studio_workspace}") and second != first
    assert await _route(tenant_id, first) == ("studio", False)
    assert await _route(tenant_id, second) == ("byok_voice", True)


@pytest.mark.parametrize("held", ["number", "experiment"])
async def test_a_rung_switch_is_refused_while_something_cannot_follow_the_agent(
    attested: set[str],
    no_webhook: None,
    hosted_rows: CatalogueRows,
    studio_workspace: str,
    held: str,
) -> None:
    tenant_id, agent_id = await _agent()
    clear = await hosted_rows.add("engine")
    studio = await hosted_rows.add("byok")
    await _set_columns(tenant_id, agent_id, clear, None)
    with selected(HostingEngine()) as engine:
        first = await _publish(tenant_id, agent_id)
        async with tenant_session(tenant_id) as session:
            if held == "number":
                await session.execute(
                    text(
                        "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                        "dlt_status, created_at, updated_at) VALUES (:id, :tid, :aid, :e, "
                        "'160', 'registered', now(), now())"
                    ),
                    {
                        "id": uuid.uuid4(),
                        "tid": tenant_id,
                        "aid": agent_id,
                        "e": f"+91160{uuid.uuid4().int % 10_000_000:07d}",
                    },
                )
            else:
                await session.execute(
                    text(
                        "INSERT INTO prompt_experiments (id, tenant_id, agent_id, name, status, "
                        "conversion_metric, started_at, created_at, updated_at) VALUES (:i, :t, "
                        ":a, 'arm test', 'running', 'lead_won', now(), now(), now())"
                    ),
                    {"i": uuid.uuid4(), "t": tenant_id, "a": agent_id},
                )
        await _set_columns(tenant_id, agent_id, studio, None)
        with pytest.raises(ProblemError) as caught:
            await _publish(tenant_id, agent_id)
    assert caught.value.code == (
        "engine_rung_switch_number_held" if held == "number" else "engine_rung_switch_agent_busy"
    )
    assert isinstance(engine, HostingEngine) and engine.deleted == []
    assert await _route(tenant_id, first) == ("studio", True)


@pytest.mark.parametrize(
    ("state", "code"),
    [(None, engine_choice.VOICE_REQUIRED), ("disabled", engine_choice.VOICE_NOT_ON_OFFER)],
)
async def test_publish_refuses_no_voice_and_a_voice_not_on_offer_before_any_vendor_write(
    attested: set[str],
    no_webhook: None,
    hosted_rows: CatalogueRows,
    state: str | None,
    code: str,
) -> None:
    tenant_id, agent_id = await _agent()
    voice = None if state is None else await hosted_rows.add("engine", state=state)
    await _set_columns(tenant_id, agent_id, voice, None)
    with selected(HostingEngine()) as engine, pytest.raises(ProblemError) as caught:
        await _publish(tenant_id, agent_id)
    assert caught.value.code == code
    assert isinstance(engine, HostingEngine) and engine.sent == []


async def test_an_engine_running_our_voices_never_sees_a_stored_choice(no_webhook: None) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "engine:priya", "prana-voice")
    sent: list[AgentConfig] = []

    class _Recording(FakeEngine):
        async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
            sent.append(cfg)
            return await super().create_agent(cfg)

    with selected(_Recording()):
        await _publish(tenant_id, agent_id)
    last = sent[-1]
    assert (last.engine_voice_id, last.engine_byok_voice_id, last.engine_workspace) == (
        None,
        None,
        None,
    )
    assert last.engine_model_id is None


async def test_a_dictated_leg_without_hosted_voices_refuses_a_stored_choice(
    no_webhook: None,
) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "priya", None)
    engine = FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)
    with selected(engine), pytest.raises(ProblemError) as caught:
        await _publish(tenant_id, agent_id)
    assert caught.value.code == engine_choice.VOICE_CHOICE_NOT_OFFERED


# --- the update route's seam -------------------------------------------------------


async def test_a_draft_stores_a_valid_choice_and_refuses_an_invalid_one(
    attested: set[str], hosted_rows: CatalogueRows
) -> None:
    tenant_id, agent_id = await _agent()
    voice = await hosted_rows.add("engine")
    with selected(HostingEngine()):
        async with tenant_session(tenant_id) as session:
            await lifecycle.update_agent(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine_voice_id=voice,
                set_engine_voice_id=True,
            )
        with pytest.raises(ProblemError) as caught:
            async with tenant_session(tenant_id) as session:
                await lifecycle.update_agent(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    engine_model_id="gpt-slow",
                    set_engine_model_id=True,
                )
    assert caught.value.code == engine_choice.MODEL_NOT_CALL_CAPABLE
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT engine_voice_id, engine_model_id FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).one()
    assert tuple(row) == (voice, None)


async def test_a_published_choice_cannot_be_cleared(attested: set[str]) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "engine:anjali", None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_x', status = 'paused' WHERE id = :a"),
            {"a": agent_id},
        )
    with selected(HostingEngine()), pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await lifecycle.update_agent(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine_voice_id=None,
                set_engine_voice_id=True,
            )
    assert caught.value.code == lifecycle.ENGINE_CHOICE_RESET_UNSUPPORTED


# --- our own workspace on all three of its own keys (BYOK) --------------------------


@pytest.fixture
def byok(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.core.settings import get_settings

    settings = get_settings().model_copy(update={"thinnest_byok_enabled": True})
    monkeypatch.setattr(engine_choice, "get_settings", lambda: settings)


async def test_under_byok_a_choice_is_refused_and_no_choice_is_the_base_rate(
    attested: set[str], byok: None
) -> None:
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id="engine:anjali", model_id=None)
    assert caught.value.code == engine_choice.CHOICE_UNDER_BYOK
    assert await _choose(voice_id=None, model_id=None) == "platform"


async def test_under_byok_a_publish_is_refused_because_those_calls_are_not_on_sale(
    attested: set[str], byok: None, no_webhook: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, None, None)

    async def _own(self: Any) -> bool:
        return True

    monkeypatch.setattr(HostingEngine, "own_keys_in_use", _own)
    with selected(HostingEngine()) as engine, pytest.raises(ProblemError) as caught:
        await _publish(tenant_id, agent_id)
    assert caught.value.code == engine_choice.KEYS_NOT_ON_SALE
    assert isinstance(engine, HostingEngine) and engine.sent == []


async def test_under_byok_the_picker_is_locked_with_a_reason(
    attested: set[str], byok: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.agents import engine_catalogue_routes
    from apps.api.core.context import Principal

    async def _keys(session: Any, *, engine: str, at: Any) -> frozenset[str]:
        return frozenset(attested)

    monkeypatch.setattr(engine_catalogue_routes, "attested_rate_keys", _keys)
    client = Principal(realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
    with selected(HostingEngine()):
        out = await engine_catalogue_routes.engine_catalogue(client)
    assert out.choosable is False and out.choice_note == engine_choice.BYOK_CHOICE_NOTE
    assert "ThinnestAI" not in out.choice_note


async def test_under_byok_a_published_choice_may_be_cleared(attested: set[str], byok: None) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "engine:anjali", None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_x', status = 'paused' WHERE id = :a"),
            {"a": agent_id},
        )
    with selected(HostingEngine()):
        async with tenant_session(tenant_id) as session:
            await lifecycle.update_agent(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine_voice_id=None,
                set_engine_voice_id=True,
            )


async def test_a_telugu_agent_is_sent_telugu_and_an_unmapped_one_follows_the_caller() -> None:
    bodies: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "ag_1"})

    engine = _engine(handler)
    await engine.update_agent("ag_1", _cfg(language_primary="te-IN"))
    await engine.update_agent("ag_1", _cfg(language_primary="kn-IN"))
    assert [b["language"] for b in bodies] == ["Telugu", "auto"]


async def test_a_studio_voice_is_refused_while_our_voice_keys_synthesis_is_unpriced(
    attested: set[str],
    hosted_rows: CatalogueRows,
    studio_workspace: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(engine_choice, "tts_price_is_billable", lambda provider: False)
    voice = await hosted_rows.add("byok")
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id=voice, model_id=None)
    assert caught.value.code == engine_choice.VOICE_TIER_UNPRICED
    assert "Cartesia" not in (caught.value.detail or "")


async def test_a_model_on_an_engine_that_lists_no_models_is_refused(attested: set[str]) -> None:
    """The model leg is the engine's, and this engine publishes no model list to check it on."""
    bare = FakeEngine(name="thinnest", capabilities=THINNEST_CAPABILITIES)
    with pytest.raises(ProblemError) as caught:
        await _choose(bare, voice_id=None, model_id="prana-voice")
    assert caught.value.code == engine_choice.MODEL_CHOICE_NOT_OFFERED
