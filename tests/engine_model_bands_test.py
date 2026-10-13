"""The per-minute band of an engine's own models, recorded by an operator (founder, 11 Oct 2026).

The band used to be a hand-edited table in the ThinnestAI adapter; it is now an append-only,
audited record, and the adapter returns no band at all. A model with no record is shown to an
operator as not checked and is offered to nobody (hard rule 7). The pickers leave out a model
the engine says cannot answer a call or our plan cannot pick, and a client is sent no models.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import engine_catalogue_routes, engine_choice
from apps.api.agents.engine_model_bands import (
    TIER_OF_BAND,
    listed_models,
    record_engine_model_band,
    recorded_bands,
    with_recorded_bands,
)
from apps.api.agents.llm_tiers import engine_model_token
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine.catalogue import CatalogueModel, EngineCatalogue
from apps.api.main import app
from apps.api.ops import engine_model_band_routes as routes
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.hosted_voice_fakes import (
    LOCKED,
    MODELS,
    NANO,
    PRANA,
    PREMIUM_MODEL,
    SLOW,
    HostingEngine,
    selected,
)

#: What migration `e5b1c8d42a07` carries over, by raw model id.
SEEDED = {
    "prana": "none",
    "gpt-oss-120b": "none",
    "prana-voice": "none",
    "gpt-4.1-nano": "none",
    "gpt-5.4-nano": "none",
    "gpt-5-nano": "none",
    "gpt-5.6-luna": "none",
    "gpt-5-mini": "premium",
}
EVERY_KEY = frozenset({"platform", "standard", "premium", "studio", "byok_voice"})


def _fresh_model(**update: Any) -> CatalogueModel:
    """A call-capable model whose id carries dots, as the vendor's newest ids do, and that no
    other test records a band for."""
    base = CatalogueModel(
        model_id=f"composer-v0.1-{uuid.uuid4().hex[:8]}",
        label="Composer v0.1",
        call_capable=True,
        plan_allows=True,
        voice_only_byok=False,
    )
    return base.model_copy(update=update)


async def _record(model_id: str, band: str) -> None:
    async with untenanted_session() as session:
        await record_engine_model_band(
            session,
            engine="thinnest",
            model_id=model_id,
            band=band,  # type: ignore[arg-type]
            source_note="test reading",
            actor_id=None,
        )


async def _admin(role: str = "superadmin") -> dict[str, str]:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return {"Authorization": f"Bearer dev:admin:{admin_id}"}


def _http() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _audits(object_id: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text(
                        "SELECT count(*) FROM audit_log WHERE action = "
                        "'platform.engine_model_band_recorded' AND object_id = :o"
                    ),
                    {"o": object_id},
                )
            ).scalar_one()
        )


# --- the record ---------------------------------------------------------------------


async def test_the_migration_carries_the_console_reading_over_by_model_id() -> None:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT model_id, band FROM platform_engine_model_bands "
                    "WHERE engine = 'thinnest' AND recorded_by IS NULL "
                    "AND source_note LIKE 'Carried over%'"
                )
            )
        ).all()
        bands = await recorded_bands(session, engine="thinnest")
    assert {str(r[0]): str(r[1]) for r in rows} == SEEDED
    for model_id, band in SEEDED.items():
        assert bands[model_id].band == band
    # Composer v0.1 and Qwen3.6 27B were never read, and stay unpriced until somebody records them.
    assert "composer-v0.1" not in bands and "qwen3.6-27b" not in bands


async def test_the_record_is_append_only_and_the_newest_row_is_in_force() -> None:
    model = _fresh_model()
    await _record(model.model_id, "premium")
    await _record(model.model_id, "none")
    async with untenanted_session() as session:
        assert (await recorded_bands(session, engine="thinnest"))[model.model_id].band == "none"
    for statement in (
        "UPDATE platform_engine_model_bands SET band = 'premium' WHERE model_id = :m",
        "DELETE FROM platform_engine_model_bands WHERE model_id = :m",
    ):
        with pytest.raises(DBAPIError, match="append-only"):
            async with untenanted_session() as session:
                await session.execute(text(statement), {"m": model.model_id})


async def test_an_unattributed_row_must_say_where_it_came_from() -> None:
    with pytest.raises(DBAPIError):
        async with untenanted_session() as session:
            await session.execute(
                text(
                    "INSERT INTO platform_engine_model_bands (engine, model_id, band) "
                    "VALUES ('thinnest', :m, 'none')"
                ),
                {"m": f"x-{uuid.uuid4().hex[:8]}"},
            )


# --- the bands reach the catalogue only from the record -----------------------------


def test_the_adapter_returns_latency_and_never_a_band() -> None:
    from apps.api.engine import thinnest

    mini = thinnest._catalogue_model("gpt-5-mini", "GPT-5 Mini", {"voice": True, "available": True})
    assert (mini.surcharge, mini.tier, mini.console_latency_ms) == (None, None, 823)
    qwen = thinnest._catalogue_model("qwen3.6-27b", "Qwen3.6 27B", {"voice": True})
    assert (qwen.surcharge, qwen.console_latency_ms) == (None, None)


async def test_bands_and_tiers_come_from_the_record_alone() -> None:
    fresh = _fresh_model(surcharge="premium")
    catalogue = EngineCatalogue(
        models=[PRANA.model_copy(update={"surcharge": None}), PREMIUM_MODEL, fresh], complete=True
    )
    async with untenanted_session() as session:
        banded = with_recorded_bands(catalogue, await recorded_bands(session, engine="thinnest"))
    by_id = {m.model_id: m for m in banded.models}
    assert (by_id["prana-voice"].surcharge, by_id["prana-voice"].tier) == ("none", "standard")
    assert (by_id["gpt-5-mini"].surcharge, by_id["gpt-5-mini"].tier) == ("premium", "plus")
    # What the adapter said is ignored: no record, no band.
    assert (by_id[fresh.model_id].surcharge, by_id[fresh.model_id].tier) == (None, None)
    assert TIER_OF_BAND == {"none": "standard", "premium": "plus"}


def test_a_model_that_cannot_answer_a_call_on_our_plan_is_not_listed() -> None:
    assert listed_models([PRANA, SLOW, LOCKED, NANO]) == [PRANA, NANO]


@pytest.fixture
def attested(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _keys(session: Any, *, engine: str, at: Any) -> frozenset[str]:
        return EVERY_KEY

    monkeypatch.setattr(engine_choice, "attested_rate_keys", _keys)
    monkeypatch.setattr(engine_choice, "tts_price_is_billable", lambda provider: True)
    monkeypatch.setattr(engine_catalogue_routes, "attested_rate_keys", _keys)
    monkeypatch.setattr(engine_catalogue_routes, "tts_price_is_billable", lambda provider: True)


async def test_a_model_is_refused_until_its_band_is_recorded_then_accepted(
    attested: None,
) -> None:
    fresh = _fresh_model()
    engine = HostingEngine(models=(*MODELS, fresh))

    async def _choose() -> str:
        async with tenant_session(uuid.uuid4()) as session:
            return await engine_choice.require_engine_choice(
                session, engine, voice_id=None, model_id=fresh.model_id
            )

    with pytest.raises(ProblemError) as caught:
        await _choose()
    assert caught.value.code == engine_choice.MODEL_NOT_ON_PLAN
    assert caught.value.detail == "Not available yet: calls on this model have not been priced."
    await _record(fresh.model_id, "none")
    assert await _choose() == "platform"


async def test_the_operator_catalogue_reads_the_recorded_band_and_hides_unusable_models(
    attested: None,
) -> None:
    fresh = _fresh_model()
    paid = _fresh_model()
    operator = Principal(realm="admin", user_id=uuid.uuid4(), tenant_id=None, role="superadmin")
    with selected(HostingEngine(models=(*MODELS, fresh, paid))):
        before = await engine_catalogue_routes.engine_catalogue(operator)
        await _record(fresh.model_id, "none")
        await _record(paid.model_id, "premium")
        after = await engine_catalogue_routes.engine_catalogue(operator)
    ids = [m.model_id for m in before.models]
    assert engine_model_token(SLOW.model_id) not in ids
    assert engine_model_token(LOCKED.model_id) not in ids
    row = {m.model_id: m for m in before.models}[engine_model_token(fresh.model_id)]
    assert row.price_band is None and not row.offerable
    assert (row.reason or "").startswith("Not checked yet")
    row = {m.model_id: m for m in after.models}[engine_model_token(fresh.model_id)]
    assert row.price_band == "none" and row.offerable and row.label == "Composer v0.1"
    # D-750: a model recorded as paid is hidden like an unusable one, GPT-5 Mini included.
    after_ids = [m.model_id for m in after.models]
    assert engine_model_token(paid.model_id) not in after_ids
    assert engine_model_token("gpt-5-mini") not in after_ids


async def test_a_client_is_sent_no_models_and_no_model_name(
    attested: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(get_settings(), "thinnest_in_call_default_model", "prana-voice")
    client = Principal(realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role="owner")
    operator = Principal(realm="admin", user_id=uuid.uuid4(), tenant_id=None, role="superadmin")
    engine = HostingEngine()
    with selected(engine):
        client_view = await engine_catalogue_routes.engine_catalogue(client)
        assert engine.reads == 0, "the client realm does not read the engine's model list"
        operator_view = await engine_catalogue_routes.engine_catalogue(operator)
    assert client_view.models == [] and client_view.default_model_label is None
    assert operator_view.default_model_label == "Prana"
    assert [m.usable_with_studio_voice for m in operator_view.models][:2] == [True, False]


# --- the ops routes -----------------------------------------------------------------


async def test_the_ops_list_shows_every_usable_model_with_its_band_or_none() -> None:
    fresh = _fresh_model()
    with selected(HostingEngine(models=(*MODELS, fresh))):
        async with _http() as http:
            response = await http.get("/v1/ops/engine-model-bands", headers=await _admin())
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["engine"] == "thinnest" and body["available"] is True
    by_id = {m["model_id"]: m for m in body["models"]}
    assert SLOW.model_id not in by_id and LOCKED.model_id not in by_id
    assert by_id[fresh.model_id]["band"] is None
    # The ops screen still lists a paid model, so its record can be read and corrected.
    assert by_id["gpt-5-mini"]["band"] == "premium"
    assert "tier" not in by_id["gpt-5-mini"]
    assert by_id["gpt-5-mini"]["catalogue_id"] == engine_model_token("gpt-5-mini")
    assert by_id["prana-voice"]["usable_with_studio_voice"] is True


async def test_recording_a_band_is_step_up_confirmed_and_audited() -> None:
    fresh = _fresh_model()
    headers = await _admin()
    path = f"/v1/ops/engine-model-bands/thinnest/{fresh.model_id}"
    object_id = f"thinnest:{fresh.model_id}"
    with selected(HostingEngine(models=(*MODELS, fresh))):
        async with _http() as http:
            refused = await http.post(path, headers=headers, json={"band": "premium"})
            wrong = await http.post(
                path,
                headers={
                    **headers,
                    "X-Confirm-Action": routes.engine_model_band_confirmation("thinnest", "other"),
                },
                json={"band": "premium"},
            )
            assert await _audits(object_id) == 0
            recorded = await http.post(
                path,
                headers={
                    **headers,
                    "X-Confirm-Action": routes.engine_model_band_confirmation(
                        "thinnest", fresh.model_id
                    ),
                },
                json={"band": "premium", "source_note": "  console dropdown, 11 Oct 2026  "},
            )
    assert refused.json()["type"].rsplit("/", 1)[-1] == "step_up_required"
    assert wrong.status_code >= 400
    assert recorded.status_code == 200, recorded.text
    body = recorded.json()
    assert (body["model_id"], body["band"]) == (fresh.model_id, "premium")
    assert body["source_note"] == "console dropdown, 11 Oct 2026"
    assert body["recorded_by"] is not None
    assert await _audits(object_id) == 1
    async with untenanted_session() as session:
        assert (await recorded_bands(session, engine="thinnest"))[fresh.model_id].band == "premium"


@pytest.mark.parametrize(
    ("case", "status", "code"),
    [
        ("unlisted", 404, "engine_model_not_in_catalogue"),
        ("slow", 422, "engine_model_not_listed"),
        ("other_engine", 404, "engine_model_band_unknown_engine"),
        ("bad_band", 422, None),
    ],
)
async def test_a_band_for_a_model_that_cannot_be_offered_is_refused(
    case: str, status: int, code: str | None
) -> None:
    engine_name, model_id, band = "thinnest", "gpt-5-mini", "premium"
    if case == "unlisted":
        model_id = f"qwen3.6-27b-{uuid.uuid4().hex[:6]}"
    elif case == "slow":
        model_id = SLOW.model_id
    elif case == "other_engine":
        engine_name = "fake"
    else:
        band = "studio"
    headers = {
        **(await _admin()),
        "X-Confirm-Action": routes.engine_model_band_confirmation(engine_name, model_id),
    }
    with selected(HostingEngine()):
        async with _http() as http:
            response = await http.post(
                f"/v1/ops/engine-model-bands/{engine_name}/{model_id}",
                headers=headers,
                json={"band": band},
            )
    assert response.status_code == status, response.text
    if code is not None:
        assert response.json()["type"].rsplit("/", 1)[-1] == code


@pytest.mark.parametrize("who", ["operator", "client", "nobody"])
async def test_only_a_superadmin_reaches_the_band_routes(who: str) -> None:
    if who == "operator":
        headers = await _admin("operator")
    elif who == "client":
        headers = {"Authorization": f"Bearer dev:client:{uuid.uuid4()}"}
    else:
        headers = {}
    with selected(HostingEngine()):
        async with _http() as http:
            listed = await http.get("/v1/ops/engine-model-bands", headers=headers)
            posted = await http.post(
                "/v1/ops/engine-model-bands/thinnest/gpt-5-mini",
                headers={
                    **headers,
                    "X-Confirm-Action": routes.engine_model_band_confirmation(
                        "thinnest", "gpt-5-mini"
                    ),
                },
                json={"band": "none"},
            )
    assert listed.status_code in {401, 403}
    assert posted.status_code in {401, 403}


def test_the_routes_ask_for_ops_manage() -> None:
    from apps.api.core.rbac import SUPERADMIN_ONLY_PERMISSIONS

    assert routes.PERMISSION == "ops:manage"
    assert routes.PERMISSION in SUPERADMIN_ONLY_PERMISSIONS


# --- D-750: only models included in the per-minute price ------------------------------


async def test_a_paid_model_is_refused_at_publish_with_the_operator_reason(attested: None) -> None:
    """Founder, 11 Oct 2026: Calevate offers no paid model, on either rung, so GPT-5 Mini
    (recorded "premium" by the migration) is refused whatever voice the agent speaks."""
    from apps.api.agents.engine_catalogue_offer import PAID_MODEL_CLIENT

    async with tenant_session(uuid.uuid4()) as session:
        with pytest.raises(ProblemError) as caught:
            await engine_choice.require_engine_choice(
                session, HostingEngine(), voice_id=None, model_id="gpt-5-mini"
            )
    assert caught.value.code == engine_choice.MODEL_PAID
    assert caught.value.detail == PAID_MODEL_CLIENT


async def test_the_in_call_default_refuses_a_paid_model_in_plain_words() -> None:
    from apps.api.agents.engine_catalogue_offer import PAID_MODEL_OPERATOR

    with selected(HostingEngine()):
        async with untenanted_session() as session:
            with pytest.raises(ProblemError) as caught:
                await engine_choice.resolve_in_call_default(session, "GPT-5 Mini")
    assert caught.value.code == engine_choice.IN_CALL_DEFAULT_UNUSABLE
    assert caught.value.detail == PAID_MODEL_OPERATOR
