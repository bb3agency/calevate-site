"""The worker's session read serves an experiment arm, and the agent's own ref its own row.

An arm is published as its own `pipecat_agents` row under the REAL agent (migration
`d9a6e2c85b41`), with a ref minted from the VARIANT's id, and `dispatch_call` dials that
ref for every assigned call. The session read used to parse the ref and match
`pipecat_agents.agent_id` on the parsed id, so:

* an arm's ref parsed to the variant's id, no row matched, and every assigned call was
  refused `worker_agent_unknown`;
* the agent's own ref matched its row AND every arm's, and `.first()` picked one.

Both reads now key on the ref, which is UNIQUE, and answer the real agent's id, which is
what observations, settlement and the attestation are filed against.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import tenant_session
from apps.api.engine.pipecat import PipecatEngine
from apps.api.worker import service as worker_service
from calevate_shared.worker_api import AttestationIn
from sqlalchemy import text
from tests.pipecat_engine_test import _config, _make_the_agent_live, _org

pytestmark = [pytest.mark.rls]

ARM_SCRIPT = "You are arm B of the clinic."


async def _agent_with_one_arm() -> tuple[uuid.UUID, uuid.UUID, str, str]:
    """(tenant, agent, the agent's ref, the arm's ref), both published on this engine."""
    tenant_id, agent_id = await _org()
    cfg = _config(tenant_id, agent_id)
    engine = PipecatEngine()
    ref = await engine.create_agent(cfg)
    await _make_the_agent_live(tenant_id, agent_id, ref)
    variant_id, experiment_id = uuid.uuid4(), uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        prompt_id = (
            await session.execute(
                text("SELECT id FROM prompt_versions WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar()
        await session.execute(
            text(
                "INSERT INTO prompt_experiments (id, tenant_id, agent_id, name, status, "
                "conversion_metric, started_at, created_at, updated_at) VALUES (:i, :t, :a, "
                "'arm session', 'running', 'lead_won', now(), now(), now())"
            ),
            {"i": experiment_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO prompt_experiment_variants (id, tenant_id, experiment_id, label, "
                "prompt_version_id, disclosure_line, weight_bp, created_at, updated_at) "
                "VALUES (:i, :t, :e, 'B', :p, 'Idi AI assistant.', 5000, now(), now())"
            ),
            {"i": variant_id, "t": tenant_id, "e": experiment_id, "p": prompt_id},
        )
    arm_cfg = cfg.model_copy(update={"agent_id": str(variant_id), "system_prompt": ARM_SCRIPT})
    arm_ref = await engine.create_agent(arm_cfg)
    return tenant_id, agent_id, ref, arm_ref


async def test_an_arms_ref_is_served_the_arms_version_under_the_real_agent() -> None:
    tenant_id, agent_id, _ref, arm_ref = await _agent_with_one_arm()

    served = await worker_service.load_session(arm_ref)

    assert served.tenant_id == tenant_id
    assert served.agent_id == agent_id, "the real agent, never the variant's id"
    assert ARM_SCRIPT in served.system_prompt


async def test_the_agents_own_ref_is_never_served_an_arm() -> None:
    _tenant_id, agent_id, ref, _arm_ref = await _agent_with_one_arm()

    for _ in range(3):
        served = await worker_service.load_session(ref)
        assert served.agent_id == agent_id
        assert ARM_SCRIPT not in served.system_prompt


async def test_an_arm_call_attests_against_the_real_agent() -> None:
    """The worker attests with the ref the call started on and the agent the session read
    answered; both have to name the same agent or the attestation is refused."""
    _tenant_id, _agent_id, _ref, arm_ref = await _agent_with_one_arm()
    served = await worker_service.load_session(arm_ref)

    answer = await worker_service.record_prompt_attestation(
        arm_ref,
        AttestationIn(
            agent_id=served.agent_id,
            agent_config_version_id=served.agent_config_version_id,
            observed_prompt_sha256=served.prompt_sha256,
        ),
    )

    assert answer.matches
