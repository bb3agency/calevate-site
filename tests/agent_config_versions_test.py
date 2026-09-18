"""`agents/config_versions.py`: what goes in a digest, and what an attestation can prove.

D-592, `docs/PIPECAT-MIGRATION.md` §1.1, migration `d4e1c7a09b35`.

THE PROPERTY UNDER TEST IS NOT "the code runs". It is that the witness can DISAGREE. A
config-version table that the attestation is derived from, or a digest the worker cannot
reproduce, both pass a naive suite and measure nothing — which is the precise defect
`owned_runtime` exists to avoid on `get_agent`. So the clauses below are built around the
two ways this can be silently useless:

* a digest that moves when the CALL changes rather than when the CONFIGURATION does
  (caller memory, a handoff destination, a dial-time merge) — every attestation would be a
  false mismatch, i.e. an incident that is not happening;
* a mismatch that the code smooths over — the row is evidence either way, so it is written
  either way and the verdict is returned rather than raised.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.config_versions import (
    latest_attestation,
    mint_config_version,
    model_config_digest,
    prompt_digest,
    record_attestation,
)
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from calevate_shared.engine import AgentConfig, ModelConfig, compose_engine_prompt
from sqlalchemy import text
from tests.conftest import accept_agreements

# No `pytestmark = pytest.mark.asyncio`: `asyncio_mode = "auto"` (pyproject.toml) already
# collects the coroutines here, and the module-level mark would be applied to the five
# SYNCHRONOUS digest clauses below — which pytest-asyncio warns about, because a sync test
# carrying that mark is usually one that was meant to be async and silently is not.


def _config(
    agent_id: uuid.UUID, tenant_id: uuid.UUID, *, script: str = "Book appointments."
) -> AgentConfig:
    return AgentConfig(
        tenant_id=str(tenant_id),
        agent_id=str(agent_id),
        name="Sunrise Clinic",
        direction="inbound",
        system_prompt=script,
        opening_line="Hello, this is an AI assistant for Sunrise Clinic.",
        models=ModelConfig(
            stt_provider="sarvam",
            stt_model="saaras:v3",
            llm_model="gpt-4o-mini",
            tts_provider="cartesia",
            tts_model="sonic-3.5",
            tts_voice="ashutosh",
        ),
    )


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Config Versions",
        slug=f"config-versions-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = uuid.UUID(str(created["id"]))
    await accept_agreements(tenant_id)
    return tenant_id, uuid.UUID(str(created["agent_id"]))


# ---------------------------------------------------------------- the digests


def test_the_prompt_digest_is_the_composed_prompt_and_nothing_else() -> None:
    """Recomputable BY THE WORKER, which only holds `compose_engine_prompt` and a config.

    Spelled out as the literal sha256 of that call rather than compared against itself, so
    a future "improvement" that salts, truncates or normalises the input fails here — the
    worker would go on computing the plain digest and every agent in the fleet would read
    as drifted.
    """
    cfg = _config(uuid.uuid4(), uuid.uuid4())
    assert prompt_digest(cfg) == hashlib.sha256(compose_engine_prompt(cfg).encode()).hexdigest()


def test_the_prompt_digest_excludes_caller_memory() -> None:
    """Caller memory is per-SESSION. In the digest, every attestation would mismatch."""
    cfg = _config(uuid.uuid4(), uuid.uuid4())
    cfg = cfg.model_copy(update={"caller_memory_enabled": True})
    with_memory = compose_engine_prompt(cfg, caller_memory=["Asked about Saturday hours."])
    assert with_memory != compose_engine_prompt(cfg), (
        "fixture is not exercising the branch: caller memory changed nothing in the prompt"
    )
    assert prompt_digest(cfg) == hashlib.sha256(compose_engine_prompt(cfg).encode()).hexdigest()
    assert prompt_digest(cfg) != hashlib.sha256(with_memory.encode()).hexdigest()


def test_the_prompt_digest_moves_when_the_script_or_the_opening_does() -> None:
    """The other direction: a digest that never moves proves nothing either."""
    base = _config(uuid.uuid4(), uuid.uuid4())
    assert prompt_digest(base) != prompt_digest(
        _config(uuid.UUID(base.agent_id), uuid.UUID(base.tenant_id), script="Sell insurance.")
    )
    assert prompt_digest(base) != prompt_digest(base.model_copy(update={"opening_line": "Hi."}))


def test_the_model_digest_covers_every_leg_and_is_order_independent() -> None:
    """One changed leg, one changed digest — on each of the three."""
    cfg = _config(uuid.uuid4(), uuid.uuid4())
    base = model_config_digest(cfg)
    assert base == model_config_digest(cfg.model_copy(deep=True)), "digest is not stable"
    for field, value in (
        ("stt_model", "saaras:v4"),
        ("llm_model", "gemini-2.5-flash-lite"),
        ("tts_voice", "anushka"),
    ):
        moved = cfg.model_copy(update={"models": cfg.models.model_copy(update={field: value})})
        assert model_config_digest(moved) != base, field


def test_the_handoff_destination_is_outside_both_digests() -> None:
    """`AgentConfig.handoff` is resolved from the roster AND A CLOCK at publish time, so an
    unchanged agent has a different one at 09:00 and at 21:00 (`agents/handoff.on_duty`).
    In either digest, a config version would be minted every time the rota turned over and
    a session that outlived the turnover would attest a mismatch."""
    from calevate_shared.engine import HandoffSpec

    cfg = _config(uuid.uuid4(), uuid.uuid4())
    handed = cfg.model_copy(
        update={
            "handoff": HandoffSpec(
                destination_e164="+919000000001",
                trigger="Hand over when the caller asks for a person.",
                spoken_line="Putting you through now.",
            )
        }
    )
    assert prompt_digest(handed) == prompt_digest(cfg)
    assert model_config_digest(handed) == model_config_digest(cfg)


# ---------------------------------------------------------------- minting


async def test_minting_the_same_content_twice_returns_one_version() -> None:
    """Content-addressed: a publish that changes nothing writes nothing."""
    tenant_id, agent_id = await _tenant()
    cfg = _config(agent_id, tenant_id)
    async with tenant_session(tenant_id) as session:
        first = await mint_config_version(session, tenant_id, cfg)
        second = await mint_config_version(session, tenant_id, cfg)
    assert first.minted is True
    assert second.minted is False
    assert second.id == first.id
    assert first.prompt_sha256 == prompt_digest(cfg)
    assert first.model_config_sha256 == model_config_digest(cfg)


async def test_a_changed_script_mints_a_second_version() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        first = await mint_config_version(session, tenant_id, _config(agent_id, tenant_id))
        second = await mint_config_version(
            session, tenant_id, _config(agent_id, tenant_id, script="Sell insurance.")
        )
    assert second.minted is True
    assert second.id != first.id


async def test_a_version_is_immutable_once_written() -> None:
    """Hard rule 4 at the database, not in the service: the trigger refuses both verbs."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        version = await mint_config_version(session, tenant_id, _config(agent_id, tenant_id))

    for statement in (
        "UPDATE agent_config_versions SET prompt_sha256 = repeat('a', 64) WHERE id = :id",
        "DELETE FROM agent_config_versions WHERE id = :id",
    ):
        async with tenant_session(tenant_id) as session:
            with pytest.raises(Exception) as raised:
                await session.execute(text(statement), {"id": version.id})
            assert (
                "append-only" in str(raised.value).lower() or "forbid" in str(raised.value).lower()
            )


async def test_a_config_with_no_truthful_answer_floor_is_refused() -> None:
    """Hard rule 5 becomes STRUCTURAL here: the worker loads this row, so a version minted
    without the floor is an agent that can be scripted into claiming it is human, and the
    row is immutable so nothing later can repair it.

    The floor is asserted by monkeypatching the composer rather than by hand-building a
    prompt, because the real composer puts the directive in unconditionally — which is the
    point, and means the only reachable caller is one composing elsewhere.
    """
    tenant_id, agent_id = await _tenant()
    import apps.api.agents.config_versions as module

    original = module.compose_engine_prompt
    module.compose_engine_prompt = lambda cfg, **kw: "Say whatever you like."  # type: ignore[assignment]
    try:
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as raised:
                await mint_config_version(session, tenant_id, _config(agent_id, tenant_id))
    finally:
        module.compose_engine_prompt = original  # type: ignore[assignment]
    assert raised.value.code == "agent_config_floor_absent"


# ---------------------------------------------------------------- attestation


async def test_an_agreeing_worker_attests_a_match() -> None:
    tenant_id, agent_id = await _tenant()
    cfg = _config(agent_id, tenant_id)
    async with tenant_session(tenant_id) as session:
        version = await mint_config_version(session, tenant_id, cfg)
        seen = datetime.now(UTC)
        attestation = await record_attestation(
            session,
            tenant_id,
            agent_id=agent_id,
            agent_config_version_id=version.id,
            prompt_sha256=prompt_digest(cfg),
            observed_at=seen,
        )
    assert attestation.matches is True
    assert attestation.observed_at == seen


async def test_a_disagreeing_worker_is_recorded_rather_than_refused() -> None:
    """THE CLAUSE THE WHOLE DESIGN EXISTS FOR. A worker on a stale deploy reports a
    different prompt; the row is written anyway, because it is the evidence, and the
    verdict comes back False rather than as an exception that would lose it."""
    tenant_id, agent_id = await _tenant()
    cfg = _config(agent_id, tenant_id)
    stale = hashlib.sha256(b"a prompt from last week").hexdigest()
    async with tenant_session(tenant_id) as session:
        version = await mint_config_version(session, tenant_id, cfg)
        attestation = await record_attestation(
            session,
            tenant_id,
            agent_id=agent_id,
            agent_config_version_id=version.id,
            prompt_sha256=stale,
        )
        written = (
            await session.execute(
                text("SELECT prompt_sha256 FROM agent_config_attestations WHERE id = :id"),
                {"id": attestation.id},
            )
        ).scalar()
    assert attestation.matches is False
    assert written == stale, "the disagreement was not persisted, so nothing can see it"


async def test_latest_attestation_is_the_newest_and_is_none_before_any_worker_runs() -> None:
    """`get_agent` answers from this. None is a real answer — a published agent nobody has
    dialled has no witness yet, and reporting the config version instead would be the
    control plane agreeing with itself."""
    tenant_id, agent_id = await _tenant()
    cfg = _config(agent_id, tenant_id)
    async with tenant_session(tenant_id) as session:
        assert await latest_attestation(session, agent_id) is None
        version = await mint_config_version(session, tenant_id, cfg)
        older = datetime.now(UTC) - timedelta(minutes=5)
        await record_attestation(
            session,
            tenant_id,
            agent_id=agent_id,
            agent_config_version_id=version.id,
            prompt_sha256=hashlib.sha256(b"older").hexdigest(),
            observed_at=older,
        )
        newest = await record_attestation(
            session,
            tenant_id,
            agent_id=agent_id,
            agent_config_version_id=version.id,
            prompt_sha256=prompt_digest(cfg),
            observed_at=older + timedelta(minutes=4),
        )
        found = await latest_attestation(session, agent_id)
    assert found is not None
    assert found.id == newest.id
    assert found.matches is True


async def test_an_attestation_naming_another_agents_version_is_refused() -> None:
    """The FK would refuse it too; this names WHICH id was wrong and keeps the transaction
    usable, rather than surfacing an IntegrityError three layers down."""
    tenant_id, agent_id = await _tenant()
    other_tenant, other_agent = await _tenant()
    async with tenant_session(other_tenant) as session:
        stranger = await mint_config_version(
            session, other_tenant, _config(other_agent, other_tenant)
        )
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await record_attestation(
                session,
                tenant_id,
                agent_id=agent_id,
                agent_config_version_id=stranger.id,
                prompt_sha256=hashlib.sha256(b"anything").hexdigest(),
            )
    assert raised.value.code == "agent_config_version_unknown"
