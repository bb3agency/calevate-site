"""Tamil, Kannada, Malayalam and Marathi: built, and hidden from clients until ready (D-855).

The four are in the wire enum, the CHECK constraints and every spoken-sentence table, and
no client can choose, publish or see one until the console switch names it AND its
readiness record (`agents/languages.STAGED_LANGUAGE_READINESS`) is complete. The record is
checked when the switch is written and again on every read, so a row written around the
console offers nothing unready. Test accounts get a language once its sentences are
reviewed, so the test call the record asks for can be made.

Run: uv run pytest -q tests/staged_languages_test.py
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from apps.api.agents import languages
from apps.api.agents.languages import (
    STAGED_LANGUAGE_READINESS,
    StagedLanguageReadiness,
    assert_staged_languages_may_switch_on,
    client_language_tags,
    enabled_staged_tags,
    published_extra_languages,
    readiness_note,
    refuse_unoffered_language,
)
from apps.api.agents.routes import router as agents_router
from apps.api.core import platform_config as pc
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.ops import config_controls as controls
from apps.api.ops import config_service
from calevate_shared.languages import offered_language_tags, staged_language_tags
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.platform_config_hardening_test import _admin_id
from tests.product_languages_test import _tenant

TAMIL = "ta-IN"

REVIEWED = StagedLanguageReadiness(
    sentences_reviewed_by="A native speaker", sentences_reviewed_on=date(2026, 10, 24)
)
READY = StagedLanguageReadiness(
    sentences_reviewed_by="A native speaker",
    sentences_reviewed_on=date(2026, 10, 24),
    test_call_checked_on=date(2026, 10, 25),
    engine_confirmation="ThinnestAI reply of 25 Oct 2026",
)


@pytest.fixture
def tamil_switched_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "staged_agent_languages_enabled", TAMIL)


@pytest.fixture
def tamil_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(languages.STAGED_LANGUAGE_READINESS, TAMIL, READY)  # type: ignore[arg-type]


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(agents_router)
    return application


# ----------------------------------------------------------------- what is offered


def test_nothing_staged_is_offered_by_default() -> None:
    assert get_settings().staged_agent_languages_enabled == ""
    assert client_language_tags() == offered_language_tags()
    assert set(STAGED_LANGUAGE_READINESS) == set(staged_language_tags())


def test_no_staged_language_is_ready_today() -> None:
    """Every record starts empty: the sentences were drafted by a non-native writer and
    NEED NATIVE-SPEAKER REVIEW, and no test call or ThinnestAI confirmation exists."""
    for tag in staged_language_tags():
        record = STAGED_LANGUAGE_READINESS[tag]
        assert not record.ready and not record.testable, tag
        assert len(record.missing()) == 3, tag


@pytest.mark.usefixtures("tamil_switched_on")
def test_a_switched_on_language_stays_hidden_until_its_record_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The read-time half of the guard: a `platform_settings` row written in psql reaches
    the same code as one written through the console."""
    assert enabled_staged_tags() == ()
    monkeypatch.setitem(languages.STAGED_LANGUAGE_READINESS, TAMIL, REVIEWED)  # type: ignore[arg-type]
    assert enabled_staged_tags() == (), "reviewed sentences alone do not offer it to everyone"
    monkeypatch.setitem(languages.STAGED_LANGUAGE_READINESS, TAMIL, READY)  # type: ignore[arg-type]
    assert client_language_tags() == (*offered_language_tags(), TAMIL)


def test_a_test_account_gets_a_language_once_its_sentences_are_reviewed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    test_account, other = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(get_settings(), "staged_language_test_tenant_ids", f"{test_account},junk")
    assert TAMIL not in client_language_tags(test_account)
    monkeypatch.setitem(languages.STAGED_LANGUAGE_READINESS, TAMIL, REVIEWED)  # type: ignore[arg-type]
    assert TAMIL in client_language_tags(test_account)
    assert TAMIL not in client_language_tags(other)


# ----------------------------------------------------------------- the switch


def test_the_switch_refuses_an_unready_or_unknown_language() -> None:
    with pytest.raises(ProblemError) as caught:
        assert_staged_languages_may_switch_on(TAMIL)
    assert caught.value.code == "staged_language_not_ready"
    assert "Tamil still needs" in caught.value.detail
    with pytest.raises(ProblemError) as unknown:
        assert_staged_languages_may_switch_on("te-IN")
    assert unknown.value.code == "staged_language_unknown"
    assert_staged_languages_may_switch_on("")


@pytest.mark.usefixtures("tamil_ready")
def test_the_switch_accepts_a_ready_language() -> None:
    assert_staged_languages_may_switch_on(TAMIL)
    assert readiness_note(TAMIL) == "Ready to offer."


async def test_the_console_write_is_refused_before_it_is_stored() -> None:
    admin_id = await _admin_id()
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as caught:
            await config_service.set_value(
                session,
                key="staged_agent_languages_enabled",
                value=TAMIL,
                note="staged languages test",
                actor_id=admin_id,
                expected_revision=0,
            )
    assert caught.value.code == "staged_language_not_ready"


def test_the_console_shows_each_language_with_what_it_still_needs() -> None:
    field = {f.key: f for f in pc.describe(get_settings())}["staged_agent_languages_enabled"]
    assert controls.control_for(field).kind == "multi_select"
    choices = controls.choices_for(field)
    assert [c.value for c in choices] == list(staged_language_tags())
    assert [c.label for c in choices] == ["Tamil", "Kannada", "Malayalam", "Marathi"]
    for choice in choices:
        assert choice.hint is not None and choice.hint.startswith("Cannot be switched on yet")


# ----------------------------------------------------------------- client paths


async def test_a_client_cannot_choose_a_hidden_language_and_is_not_told_it_exists() -> None:
    _, token = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        created = await http.post(
            "/v1/agents",
            json={"name": "Front desk", "direction": "inbound", "language_primary": TAMIL},
            headers={"Authorization": f"Bearer {token}"},
        )
        offered = await http.get(
            "/v1/agents/languages", headers={"Authorization": f"Bearer {token}"}
        )
    assert created.status_code == 422, created.text
    assert "does not offer Tamil" in created.json()["detail"]
    assert "Kannada" not in created.json()["detail"]
    assert offered.status_code == 200, offered.text
    assert [row["tag"] for row in offered.json()["languages"]] == list(offered_language_tags())


@pytest.mark.usefixtures("tamil_switched_on", "tamil_ready")
async def test_once_ready_and_switched_on_a_client_can_choose_it() -> None:
    _, token = await _tenant()
    async with AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api") as http:
        created = await http.post(
            "/v1/agents",
            json={
                "name": "Front desk",
                "direction": "inbound",
                "language_primary": TAMIL,
                "reply_languages": [TAMIL, "en-IN"],
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        offered = await http.get(
            "/v1/agents/languages", headers={"Authorization": f"Bearer {token}"}
        )
    assert created.status_code == 201, created.text
    assert created.json()["language_primary"] == TAMIL
    assert created.json()["reply_languages"] == [TAMIL, "en-IN"]
    assert offered.json()["languages"][-1] == {"tag": TAMIL, "name": "Tamil"}


def test_publishing_refuses_a_hidden_main_language_and_drops_a_hidden_extra() -> None:
    tenant = uuid.uuid4()
    with pytest.raises(ProblemError) as caught:
        refuse_unoffered_language(TAMIL, tenant_id=tenant)
    assert caught.value.code == "agent_language_not_offered"
    refuse_unoffered_language("te-IN", tenant_id=tenant)
    assert published_extra_languages("te-IN", [TAMIL, "en-IN"], tenant_id=tenant) == ["en-IN"]


async def test_the_database_holds_a_staged_language() -> None:
    """Widened by migration d6f1a8c3e925, so switching a language on needs no migration."""
    tenant_id, _ = await _tenant()
    agent_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, status, "
                "language_primary, languages_extra, disclosure_line, ai_disclosure_line, "
                "recording_notice_line, caller_memory_notice_line, created_at, updated_at) "
                "VALUES (:id, :tid, 'Raw write', 'inbound', 'draft', 'mr-IN', "
                "ARRAY['kn-IN', 'ml-IN']::text[], 'x', 'x', 'x', 'x', now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id},
        )
        stored = (
            await session.execute(
                text("SELECT language_primary FROM agents WHERE id = :id"), {"id": agent_id}
            )
        ).scalar_one()
    assert stored == "mr-IN"
