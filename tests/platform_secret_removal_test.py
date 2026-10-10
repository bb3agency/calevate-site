"""Removing a platform credential (PLATFORM-CONFIG §7, migration c2b7e5a94d18).

A removal is a NEW VERSION with `removed = true`, because `platform_secrets` is append-only
(hard rule 4). What must hold, worst failure first:

1. **A removed key is not in force anywhere.** It resolves as not set, so `Settings` falls
   back to the code default, and every LLM leg keyed on it stops being offered — the
   copilot then answers on another leg rather than calling the vendor with a dead key.
2. **The environment still wins, so a key it sets cannot be removed here.** Removing it in
   the console would leave it in force while the console said it was gone.
3. **It is attributable**: step-up confirmed, audited, and refused without an admin identity.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest import mock

import pytest
from apps.api.agents import llm_models
from apps.api.copilot import service as copilot_service
from apps.api.copilot.loop_test import PAYLOAD
from apps.api.copilot.model_tiers import tier_leg, tier_model
from apps.api.core import platform_config as pc
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.core.stepup import StepUp
from apps.api.db.session import untenanted_session
from apps.api.ops.model_pricing import (
    PROVIDER_CREDENTIAL,
    attest_price,
    installed_llm_legs,
    offerable_models,
)
from apps.api.ops.pricing_snapshot import (
    install_pricing_readers,
    refresh_pricing_snapshot,
    uninstall_pricing_readers,
)
from apps.api.ops.secret_routes import remove_secret_route, secret_removal_confirmation
from apps.api.ops.secret_service import (
    read_secrets,
    remove_secret,
    resolve_secrets,
    rewrap_all,
    set_secret,
)
from apps.workers import chat
from apps.workers.extraction import AZURE_PROVIDER, GOOGLE_PROVIDER
from calevate_shared.config import Settings
from calevate_shared.engine import LLM_MODELS
from fastapi import BackgroundTasks
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from tests.admin_security_test import _make_admin
from tests.platform_secrets_test import (
    KEY,
    SECRET,
    SHADOWED_KEY,
    _admin_id,
    _auth,
    _client,
    _request,
)

GOOGLE_KEY = PROVIDER_CREDENTIAL["google"]
GOOGLE_MODEL = "gemini-2.5-flash-lite"


async def _purge_as_owner() -> None:
    """Remove this suite's rows from the two append-only tables it writes, as the OWNER,
    restoring each trigger's prior mode verbatim (`platform_secrets_test._purge` says why
    plain `ENABLE` is not the inverse of `DISABLE`)."""
    owner_url = Settings().alembic_database_url
    assert owner_url, "ALEMBIC_DATABASE_URL required: both tables are append-only"
    engine = create_async_engine(owner_url)
    targets = (
        ("platform_secrets", "key", [KEY, SHADOWED_KEY, GOOGLE_KEY]),
        ("platform_model_prices", "model", [GOOGLE_MODEL]),
    )
    try:
        async with engine.begin() as conn:
            for table, column, values in targets:
                modes = (
                    await conn.execute(
                        text(
                            "SELECT t.tgname, t.tgenabled FROM pg_trigger t "
                            f"WHERE t.tgrelid = '{table}'::regclass AND NOT t.tgisinternal"
                        )
                    )
                ).all()
                await conn.execute(text(f"ALTER TABLE {table} DISABLE TRIGGER USER"))
                await conn.execute(
                    text(f"DELETE FROM {table} WHERE {column} = ANY(:v)"), {"v": values}
                )
                for name, mode in modes:
                    verb = {"A": "ENABLE ALWAYS", "R": "ENABLE REPLICA", "D": "DISABLE"}.get(
                        str(mode), "ENABLE"
                    )
                    await conn.execute(text(f'ALTER TABLE {table} {verb} TRIGGER "{name}"'))
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    uninstall_pricing_readers()
    await _purge_as_owner()
    pc.reset_for_test()
    await pc.refresh(force=True)


async def _rows(key: str) -> list[tuple[int, bool, bool, str]]:
    """(version, retired, removed, last_four) for every stored version of one key."""
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT version, retired_at IS NOT NULL, removed, last_four "
                    "FROM platform_secrets WHERE key = :k ORDER BY version"
                ),
                {"k": key},
            )
        ).all()
    return [(int(v), bool(r), bool(d), str(f)) for v, r, d, f in rows]


# --- the tombstone ----------------------------------------------------------------------


async def test_a_removal_is_a_new_version_that_resolves_as_not_set() -> None:
    admin = await _admin_id()
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
        removed = await remove_secret(session, key=KEY, actor_id=admin)

    assert (removed.version, removed.installed, removed.last_four) == (2, False, "")
    # The installed version is RETIRED, never edited; the removal is the version in force.
    assert await _rows(KEY) == [(1, True, False, SECRET[-4:]), (2, False, True, "")]
    async with untenanted_session() as session:
        assert KEY not in (await resolve_secrets(session)).values
        listed = next(r for r in await read_secrets(session) if r.key == KEY)
    # "Version 2 of 2": the history is kept and counted, and the key reads as not set.
    assert (listed.installed, listed.version, listed.versions, listed.last_four) == (
        False,
        2,
        2,
        "",
    )
    assert listed.created_by is not None


async def test_a_key_installed_after_a_removal_is_in_force_again() -> None:
    admin = await _admin_id()
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
        await remove_secret(session, key=KEY, actor_id=admin)
        again = await set_secret(session, key=KEY, value="co-live-reinstalled-77", actor_id=admin)
        resolved = await resolve_secrets(session)
    assert (again.version, again.installed) == (3, True)
    assert resolved.values[KEY] == "co-live-reinstalled-77"


async def test_a_removal_reaches_this_process_settings() -> None:
    """End to end through the config refresh: the stored value leaves `Settings` and the
    code default (here `None`) comes back."""
    admin = await _admin_id()
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
    await pc.refresh(force=True)
    assert getattr(get_settings(), KEY) == SECRET

    async with untenanted_session() as session:
        await remove_secret(session, key=KEY, actor_id=admin)
    await pc.refresh(force=True)
    assert getattr(get_settings(), KEY) == Settings.model_fields[KEY].get_default()


async def test_nothing_installed_means_nothing_to_remove() -> None:
    """A second tombstone would record a change nobody made."""
    admin = await _admin_id()
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as never:
            await remove_secret(session, key=KEY, actor_id=admin)
    assert (never.value.code, never.value.status) == ("secret_not_installed", 409)

    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
        await remove_secret(session, key=KEY, actor_id=admin)
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as twice:
            await remove_secret(session, key=KEY, actor_id=admin)
    assert twice.value.code == "secret_not_installed"
    assert len(await _rows(KEY)) == 2


async def test_a_key_the_environment_sets_cannot_be_removed_here() -> None:
    admin = await _admin_id()
    with mock.patch.dict(os.environ, {SHADOWED_KEY.upper(): "env-held-value"}):
        async with untenanted_session() as session:
            await set_secret(session, key=SHADOWED_KEY, value="stored-and-inert", actor_id=admin)
        async with untenanted_session() as session:
            with pytest.raises(ProblemError) as raised:
                await remove_secret(session, key=SHADOWED_KEY, actor_id=admin)
    assert raised.value.code == "secret_set_in_environment"
    assert raised.value.status == 422
    assert "CARTESIA_API_KEY" in (raised.value.remediation or "")
    assert [removed for _, _, removed, _ in await _rows(SHADOWED_KEY)] == [False]


async def test_a_removal_flag_cannot_be_edited_onto_an_installed_version() -> None:
    """The trigger guards `removed` like the ciphertext: a rewrap may move a row's wrapping,
    never turn an installed version into a removal or back."""
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=await _admin_id())
    with pytest.raises(Exception) as raised:
        async with untenanted_session() as session:
            await session.execute(
                text("UPDATE platform_secrets SET removed = true WHERE key = :k"), {"k": KEY}
            )
    assert "append-only" in str(raised.value)


async def test_a_rewrap_reads_a_removal_like_any_other_version() -> None:
    """The tombstone seals the empty string so a KEK rotation needs no tombstone branch."""
    admin = await _admin_id()
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin)
        await remove_secret(session, key=KEY, actor_id=admin)
        result = await rewrap_all(session)
    assert not [name for name in result.unreadable if name.startswith(f"{KEY}#")]


# --- the route ----------------------------------------------------------------------------


async def test_the_route_needs_the_removal_confirmation_and_writes_nothing_without_it() -> None:
    admin_id = await _admin_id()
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=admin_id)
    token = await _make_admin()
    async with _client() as http:
        bare = await http.delete(f"/v1/ops/secrets/{KEY}", headers=_auth(token))
        # Consent to ROTATING a key is not consent to removing it.
        rotate_word = await http.delete(
            f"/v1/ops/secrets/{KEY}", headers=_auth(token, f"set_secret:{KEY}")
        )
    for response in (bare, rotate_word):
        assert response.status_code == 403, response.text
        assert response.json()["type"].endswith("/step_up_required")
    assert len(await _rows(KEY)) == 1


async def test_the_route_removes_audits_and_reports_not_installed() -> None:
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=await _admin_id())
        since = (
            await session.execute(text("SELECT coalesce(max(at), now()) FROM audit_log"))
        ).scalar_one()
    token = await _make_admin()
    async with _client() as http:
        response = await http.delete(
            f"/v1/ops/secrets/{KEY}", headers=_auth(token, secret_removal_confirmation(KEY))
        )
        listed = await http.get("/v1/ops/secrets", headers=_auth(token))
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["installed"], body["version"], body["last_four"]) == (False, 2, "")
    entry = next(s for s in listed.json()["secrets"] if s["key"] == KEY)
    assert (entry["installed"], entry["version"], entry["versions"]) == (False, 2, 2)

    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT action, object_type, object_id, actor_id IS NOT NULL "
                    "FROM audit_log WHERE at >= :since AND action = 'platform.secret_removed'"
                ),
                {"since": since},
            )
        ).all()
    assert [tuple(row) for row in audited] == [
        ("platform.secret_removed", "platform_secrets", KEY, True)
    ]


async def test_the_route_refuses_an_environment_key_as_problem_json() -> None:
    token = await _make_admin()
    with mock.patch.dict(os.environ, {SHADOWED_KEY.upper(): "env-held-value"}):
        async with _client() as http:
            response = await http.delete(
                f"/v1/ops/secrets/{SHADOWED_KEY}",
                headers=_auth(token, secret_removal_confirmation(SHADOWED_KEY)),
            )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/secret_set_in_environment")


async def test_a_removal_with_no_admin_identity_is_refused() -> None:
    async with untenanted_session() as session:
        await set_secret(session, key=KEY, value=SECRET, actor_id=await _admin_id())
    principal = Principal(realm="admin", user_id=None, tenant_id=None, role=None)
    async with untenanted_session() as session:
        with pytest.raises(ProblemError) as raised:
            await remove_secret_route(
                session,
                _request(),
                BackgroundTasks(),
                principal,
                KEY,
                StepUp(present=False, verified_at=None),
                x_confirm_action=secret_removal_confirmation(KEY),
            )
    assert raised.value.code == "secret_actor_unknown"
    assert len(await _rows(KEY)) == 1


# --- the effect: a removed Google key takes Gemini off the offer, and off the wire ---------


async def _install_google(admin: uuid.UUID, now: datetime) -> None:
    async with untenanted_session() as session:
        await attest_price(
            session,
            model=GOOGLE_MODEL,
            input_usd_per_mtok=Decimal("0.10"),
            output_usd_per_mtok=Decimal("0.40"),
            effective_from=now,
            source_note="ai studio console",
            actor_id=admin,
        )
        await set_secret(session, key=GOOGLE_KEY, value="gk-installed-for-removal", actor_id=admin)


async def test_removing_the_google_key_takes_every_gemini_model_off_the_offer() -> None:
    admin, now = await _admin_id(), datetime.now(UTC)
    await _install_google(admin, now)
    async with untenanted_session() as session:
        assert "google" in await installed_llm_legs(session)
        assert GOOGLE_MODEL in await offerable_models(session, at=now)

    async with untenanted_session() as session:
        await remove_secret(session, key=GOOGLE_KEY, actor_id=admin)
    async with untenanted_session() as session:
        assert "google" not in await installed_llm_legs(session)
        assert not {m for m in await offerable_models(session, at=now) if m in _gemini_models()}

    # And through the seam every picker and the copilot read.
    install_pricing_readers()
    await refresh_pricing_snapshot()
    assert "google" not in llm_models.installed_llm_providers()
    assert not llm_models.offerable_models() & _gemini_models()


def _gemini_models() -> frozenset[str]:
    return frozenset(m for m, spec in LLM_MODELS.items() if spec.provider == "google")


async def test_the_copilot_sends_nothing_to_google_after_the_key_is_removed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The founder's case: the key was replaced with junk, the assistant still called
    Gemini, got an HTTP error and fell back. After a removal the tier's Gemini model is not
    offerable, so the selector never chooses Google — even on a process whose `Settings`
    still holds the stale key — and the answer comes from the platform's Azure leg."""
    admin, now = await _admin_id(), datetime.now(UTC)
    await _install_google(admin, now)
    async with untenanted_session() as session:
        await remove_secret(session, key=GOOGLE_KEY, actor_id=admin)
    install_pricing_readers()
    await refresh_pricing_snapshot()

    settings = get_settings()
    monkeypatch.setattr(settings, "copilot_fast_model", GOOGLE_MODEL, raising=False)
    monkeypatch.setattr(settings, "gemini_api_key", "..", raising=False)
    monkeypatch.setattr(settings, "azure_openai_resource", "calevate-test", raising=False)
    monkeypatch.setattr(settings, "azure_openai_api_key", "k", raising=False)
    monkeypatch.setattr(settings, "azure_openai_deployment", "dep", raising=False)
    monkeypatch.setattr(settings, "sarvam_api_key", None, raising=False)
    assert tier_model("fast") == GOOGLE_MODEL
    leg = tier_leg("fast")
    assert leg.provider == GOOGLE_PROVIDER and not leg.serves_dashboard

    sent: list[chat.ChatLeg] = []

    async def _stream(
        chat_leg: chat.ChatLeg, messages: Sequence[Any], **kwargs: Any
    ) -> AsyncIterator[chat.StreamEvent]:
        sent.append(chat_leg)
        yield chat.StreamEvent(text="Nine.")
        yield chat.StreamEvent(outcome=chat.ChatOutcome(content="Nine.", finish_reason="stop"))

    monkeypatch.setattr(chat, "stream", _stream)
    events = [e async for e in copilot_service.run_copilot(PAYLOAD, tenant_leg=leg)]

    assert sent, "the copilot answered without any leg"
    assert all(chat_leg.dialect != "google" for chat_leg in sent)
    spend = events[-1].spend
    assert spend is not None and spend.capability.provider == AZURE_PROVIDER
