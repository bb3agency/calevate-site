"""A call is priced from the agent's OWN published row, never from an experiment arm's.

Each arm is a `pipecat_agents` row under the real `agent_id` (migration `d9a6e2c85b41`).
Two readers that fall back to "the agent's currently published version" used to match on
`p.agent_id`, so with an arm running:

* `worker/service._published_models` (a settlement that names no version) could price the
  call from the arm's model config;
* `workers/pipeline.settled_voice_tier` found two rows and raised.

Both now key on the agent's own ref, which is UNIQUE.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.billing.rates import PREMIUM_VOICE_TIER
from apps.api.db.session import tenant_session
from apps.api.worker import service as worker_service
from apps.workers.pipeline import settled_voice_tier
from sqlalchemy import text
from tests.worker_session_arm_test import _agent_with_one_arm

pytestmark = [pytest.mark.rls]


async def _give_the_arm_another_voice(tenant_id: uuid.UUID, arm_ref: str) -> None:
    """The fixture publishes both rows with Cartesia; the arm is moved to Gnani so a reader
    that picked it would answer differently.

    `agent_config_versions` is append-only (hard rule 4), so the arm gets a NEW version row
    carrying the Gnani voice and its `pipecat_agents` row is re-pointed at it, which is what
    a republish of the arm does."""
    new_version = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        inserted = await session.execute(
            text(
                "INSERT INTO agent_config_versions (id, tenant_id, agent_id, prompt_sha256, "
                "model_config_sha256, composed_prompt, opening_line, model_config) "
                "SELECT :nv, v.tenant_id, v.agent_id, v.prompt_sha256, "
                "encode(sha256(convert_to(CAST(:nv AS text), 'UTF8')), 'hex'), v.composed_prompt, "
                "v.opening_line, jsonb_set(v.model_config, '{tts_provider}', '\"gnani\"') "
                "FROM agent_config_versions AS v JOIN pipecat_agents AS p "
                "ON p.agent_config_version_id = v.id WHERE p.engine_agent_ref = :ref"
            ),
            {"nv": new_version, "ref": arm_ref},
        )
        assert inserted.rowcount == 1, "the arm must have its own published row"
        await session.execute(
            text(
                "UPDATE pipecat_agents SET agent_config_version_id = :nv "
                "WHERE engine_agent_ref = :ref"
            ),
            {"nv": new_version, "ref": arm_ref},
        )


async def test_a_settlement_naming_no_version_is_priced_from_the_agents_own_row() -> None:
    tenant_id, agent_id, _ref, arm_ref = await _agent_with_one_arm()
    await _give_the_arm_another_voice(tenant_id, arm_ref)

    async with tenant_session(tenant_id) as session:
        for _ in range(3):
            models = await worker_service._published_models(
                session, tenant_id=tenant_id, agent_id=agent_id, version_id=None
            )
            assert models.tts_provider == "cartesia"


async def test_a_call_that_synthesised_nothing_takes_the_agents_own_voice_tier() -> None:
    """No `tts_kchars` row and no parked re-meter demand: the published-config fallback."""
    tenant_id, agent_id, _ref, arm_ref = await _agent_with_one_arm()
    await _give_the_arm_another_voice(tenant_id, arm_ref)
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "status, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
                "'completed', now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "ecid": f"arm-{call_id}"},
        )
        tier = await settled_voice_tier(session, call_id=call_id)
    assert tier == PREMIUM_VOICE_TIER
