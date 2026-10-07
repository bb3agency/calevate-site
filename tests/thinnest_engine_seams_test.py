"""The last ThinnestAI seams (D-678): who answers a number, knowledge longer than one
document, and an agent's own choice of the engine's voice and model.

Vendor shapes are the mirror's (`thinnest-findings/mirror/pages/api-reference/`):
`voices-and-models.md:67-87` (numbers), `knowledge.md:9-52` (documents, 200,000-character
text cap), `agents.md:105-110,152-161` (`model`, `voice.voice`).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import engine_choice, lifecycle, prompts
from apps.api.agents.service import publish_agent
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.catalogue import CatalogueModel, CatalogueVoice, EngineCatalogue
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

PRIYA = CatalogueVoice(voice_id="priya", label="Priya", price_band="premium")
ANJALI = CatalogueVoice(voice_id="anjali", label="Anjali", price_band="standard")
PRANA = CatalogueModel(model_id="prana-voice", label="Prana", call_capable=True, plan_allows=True)
SLOW = CatalogueModel(model_id="gpt-4.1", label="GPT-4.1", call_capable=False, plan_allows=True)
LOCKED = CatalogueModel(model_id="gpt-x", label="X", call_capable=True, plan_allows=False)
CATALOGUE = EngineCatalogue(voices=[PRIYA, ANJALI], models=[PRANA, SLOW, LOCKED], complete=True)


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


class _CatalogueEngine(FakeEngine):
    def __init__(self, **kw: Any) -> None:
        super().__init__(name="thinnest", capabilities=THINNEST_CAPABILITIES, **kw)
        self.reads = 0
        self.sent: list[AgentConfig] = []

    async def read_catalogue(self) -> EngineCatalogue:
        self.reads += 1
        return CATALOGUE

    async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
        self.sent.append(cfg)
        return await super().create_agent(cfg)

    async def update_agent(self, ref: EngineAgentRef, cfg: AgentConfig) -> None:
        self.sent.append(cfg)
        await super().update_agent(ref, cfg)


@pytest.fixture
def attested(monkeypatch: pytest.MonkeyPatch) -> set[str]:
    """The attested rate keys, as a set a test edits. The base minute and the one band that
    is sold (Premium, D-681) are priced; Standard is attested too, to prove attesting a band
    does not put it on offer."""
    keys = {"platform", "premium", "standard"}

    async def _keys(session: Any, *, engine: str, at: Any) -> frozenset[str]:
        assert engine == "thinnest"
        return frozenset(keys)

    async def _billable(session: Any, *, engine: str, rate_key: str, at: Any) -> bool:
        return rate_key in keys

    from apps.api.agents import engine_limits

    monkeypatch.setattr(engine_choice, "attested_rate_keys", _keys)
    monkeypatch.setattr(engine_limits, "engine_minute_is_billable", _billable)
    return keys


async def _choose(**kw: Any) -> str:
    return await engine_choice.require_engine_choice(None, _CatalogueEngine(), **kw)  # type: ignore[arg-type]


async def test_no_choice_is_the_base_rate_without_reading_the_catalogue(
    attested: set[str],
) -> None:
    engine = _CatalogueEngine()
    key = await engine_choice.require_engine_choice(
        None,  # type: ignore[arg-type]
        engine,
        voice_id=None,
        model_id=None,
    )
    assert key == "platform" and engine.reads == 0


async def test_a_priced_voice_is_metered_at_its_band(attested: set[str]) -> None:
    assert await _choose(voice_id="priya", model_id="prana-voice") == "premium"
    assert await _choose(voice_id=None, model_id="prana-voice") == "platform"


@pytest.mark.parametrize(
    ("voice_id", "model_id", "code"),
    [
        ("nobody", None, engine_choice.VOICE_NOT_IN_CATALOGUE),
        ("anjali", None, engine_choice.VOICE_NOT_ON_OFFER),
        (None, "missing", engine_choice.MODEL_NOT_IN_CATALOGUE),
        (None, "gpt-4.1", engine_choice.MODEL_NOT_CALL_CAPABLE),
        (None, "gpt-x", engine_choice.MODEL_NOT_ON_PLAN),
    ],
)
async def test_a_choice_the_catalogue_does_not_allow_is_refused_by_name(
    attested: set[str], voice_id: str | None, model_id: str | None, code: str
) -> None:
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id=voice_id, model_id=model_id)
    assert caught.value.code == code
    assert "ThinnestAI" not in (caught.value.detail or "")


async def test_a_sold_band_nobody_priced_is_refused_as_unpriced(attested: set[str]) -> None:
    attested.discard("premium")
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id="priya", model_id=None)
    assert caught.value.code == engine_choice.VOICE_TIER_UNPRICED


async def test_a_band_that_is_not_sold_says_so_plainly(attested: set[str]) -> None:
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id="anjali", model_id=None)
    assert caught.value.code == engine_choice.VOICE_NOT_ON_OFFER
    assert caught.value.detail == "This voice is not on offer yet."


async def test_a_choice_is_refused_where_the_engine_runs_our_voices() -> None:
    with pytest.raises(ProblemError) as caught:
        await engine_choice.require_engine_choice(
            None,  # type: ignore[arg-type]
            FakeEngine(),
            voice_id="priya",
            model_id=None,
        )
    assert caught.value.code == engine_choice.VOICE_CHOICE_NOT_OFFERED


async def test_an_id_missing_from_a_short_catalogue_is_not_called_unknown(
    attested: set[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _short(self: Any) -> EngineCatalogue:
        return CATALOGUE.model_copy(update={"complete": False})

    monkeypatch.setattr(_CatalogueEngine, "read_catalogue", _short)
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id="nobody", model_id=None)
    assert caught.value.code == engine_choice.CATALOGUE_INCOMPLETE


# --- the publish path --------------------------------------------------------------


@contextmanager
def _selected(instance: FakeEngine) -> Iterator[FakeEngine]:
    import apps.api.engine as engine_module

    previous = dict(engine_module._instances)
    engine_module._instances["fake"] = instance
    try:
        yield instance
    finally:
        engine_module._instances.clear()
        engine_module._instances.update(previous)


@pytest.fixture
def no_webhook(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.agents import service

    async def _ensure(session: Any, *, engine: str, engine_agent_ref: str) -> None:
        return None

    monkeypatch.setattr(service, "ensure_agent_webhook", _ensure)
    monkeypatch.setattr(service, "ensure_agent_actions", _ensure)


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


async def _rate_key(tenant_id: uuid.UUID, ref: str) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text(
                        "SELECT engine_rate_key FROM engine_agent_routes "
                        "WHERE engine_agent_ref = :r"
                    ),
                    {"r": ref},
                )
            ).scalar_one()
        )


async def test_publish_sends_the_choice_and_meters_at_the_voices_band(
    attested: set[str], no_webhook: None
) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "priya", "prana-voice")
    with _selected(_CatalogueEngine()) as engine:
        async with tenant_session(tenant_id) as session:
            ref = await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert isinstance(engine, _CatalogueEngine)
    assert (engine.sent[-1].engine_voice_id, engine.sent[-1].engine_model_id) == (
        "priya",
        "prana-voice",
    )
    assert await _rate_key(tenant_id, ref) == "premium"


async def test_publish_refuses_an_unpriced_band_before_any_vendor_write(
    attested: set[str], no_webhook: None
) -> None:
    attested.discard("premium")
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "priya", None)
    with _selected(_CatalogueEngine()) as engine, pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert caught.value.code == engine_choice.VOICE_TIER_UNPRICED
    assert isinstance(engine, _CatalogueEngine) and engine.sent == []


@pytest.mark.parametrize(
    ("voice", "code"),
    [(None, engine_choice.VOICE_REQUIRED), ("anjali", engine_choice.VOICE_NOT_ON_OFFER)],
)
async def test_publish_refuses_no_voice_and_a_band_not_on_offer_before_any_vendor_write(
    attested: set[str], no_webhook: None, voice: str | None, code: str
) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, voice, None)
    with _selected(_CatalogueEngine()) as engine, pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert caught.value.code == code
    assert "ThinnestAI" not in (caught.value.detail or "")
    assert isinstance(engine, _CatalogueEngine) and engine.sent == []


async def test_an_engine_running_our_voices_never_sees_a_stored_choice(no_webhook: None) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "priya", "prana-voice")
    sent: list[AgentConfig] = []

    class _Recording(FakeEngine):
        async def create_agent(self, cfg: AgentConfig) -> EngineAgentRef:
            sent.append(cfg)
            return await super().create_agent(cfg)

    with _selected(_Recording()):
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert (sent[-1].engine_voice_id, sent[-1].engine_model_id) == (None, None)


async def test_a_dictated_leg_without_a_catalogue_refuses_a_stored_choice(
    no_webhook: None,
) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "priya", None)
    engine = FakeEngine(capabilities=DICTATED_SPEECH_CAPABILITIES)
    with _selected(engine), pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert caught.value.code == engine_choice.VOICE_CHOICE_NOT_OFFERED


# --- the update route's seam -------------------------------------------------------


async def test_a_draft_stores_a_valid_choice_and_refuses_an_invalid_one(
    attested: set[str],
) -> None:
    tenant_id, agent_id = await _agent()
    with _selected(_CatalogueEngine()):
        async with tenant_session(tenant_id) as session:
            await lifecycle.update_agent(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine_voice_id="priya",
                set_engine_voice_id=True,
            )
        with pytest.raises(ProblemError) as caught:
            async with tenant_session(tenant_id) as session:
                await lifecycle.update_agent(
                    session,
                    tenant_id=tenant_id,
                    agent_id=agent_id,
                    engine_model_id="gpt-4.1",
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
    assert tuple(row) == ("priya", None)


async def test_a_published_choice_cannot_be_cleared(attested: set[str]) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "anjali", None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_x', status = 'paused' WHERE id = :a"),
            {"a": agent_id},
        )
    with _selected(_CatalogueEngine()), pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await lifecycle.update_agent(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                engine_voice_id=None,
                set_engine_voice_id=True,
            )
    assert caught.value.code == lifecycle.ENGINE_CHOICE_RESET_UNSUPPORTED


# --- the workspace on its own keys (BYOK) -------------------------------------------
# BYOK is a console-only, workspace-wide setting at ThinnestAI (FOUNDER-RELAYED console
# reading, 6 Oct 2026); `Settings.thinnest_byok_enabled` records that an operator set it.


@pytest.fixture
def byok(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.api.core.settings import get_settings

    settings = get_settings().model_copy(update={"thinnest_byok_enabled": True})
    monkeypatch.setattr(engine_choice, "get_settings", lambda: settings)


async def test_under_byok_a_choice_is_refused_and_no_choice_is_the_base_rate(
    attested: set[str], byok: None
) -> None:
    with pytest.raises(ProblemError) as caught:
        await _choose(voice_id="anjali", model_id=None)
    assert caught.value.code == engine_choice.CHOICE_UNDER_BYOK
    assert await _choose(voice_id=None, model_id=None) == "platform"


async def test_under_byok_a_publish_is_refused_because_those_calls_are_not_on_sale(
    attested: set[str], byok: None, no_webhook: None
) -> None:
    """D-681: the workspace-keys mode names no band that is sold, and Studio on it waits on
    ThinnestAI's BYOK answer, so a publish is refused before any vendor write."""
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "priya", "prana-voice")
    with _selected(_CatalogueEngine()) as engine, pytest.raises(ProblemError) as caught:
        async with tenant_session(tenant_id) as session:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert caught.value.code == engine_choice.KEYS_NOT_ON_SALE
    assert isinstance(engine, _CatalogueEngine) and engine.sent == []


async def test_under_byok_the_picker_is_locked_with_a_reason(
    attested: set[str], byok: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    from apps.api.agents import engine_catalogue_routes
    from apps.api.core.context import Principal

    async def _keys(session: Any, *, engine: str, at: Any) -> frozenset[str]:
        return frozenset(attested)

    monkeypatch.setattr(engine_catalogue_routes, "attested_rate_keys", _keys)
    client = Principal(realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
    with _selected(_CatalogueEngine()):
        out = await engine_catalogue_routes.engine_catalogue(client)
    assert out.choosable is False and out.choice_note == engine_choice.BYOK_CHOICE_NOTE
    assert "ThinnestAI" not in out.choice_note


async def test_under_byok_a_published_choice_may_be_cleared(attested: set[str], byok: None) -> None:
    tenant_id, agent_id = await _agent()
    await _set_columns(tenant_id, agent_id, "anjali", None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET engine_agent_ref = 'ag_x', status = 'paused' WHERE id = :a"),
            {"a": agent_id},
        )
    with _selected(_CatalogueEngine()):
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
