"""Pip's script proposal job (`apps/workers/script_proposal.py`): the charge for a finished
draft commits with the stored proposal, never before it."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_proposals
from apps.api.db.session import tenant_session
from apps.workers import script_proposal as worker
from calevate_shared.call_script import CallScript
from tests.conftest import create_org_with_receptionist

pytestmark = [pytest.mark.rls]


async def _requested() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    created = await create_org_with_receptionist(
        name="Proposal Shop",
        slug=f"prop-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.request_proposal(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            mode="change",
            change="Ask for the delivery area first.",
            answers={},
            requested_by=uuid.uuid4(),
        )
    return tenant_id, agent_id, proposal.id


async def test_the_draft_is_charged_in_the_transaction_that_stores_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, proposal_id = await _requested()
    sessions: dict[str, object] = {}

    async def drafted(*_args: Any) -> Any:
        return SimpleNamespace(
            script=CallScript(opening_line="Namaste!"),
            earlier=(),
            model="gemini-2.5-flash-lite",
            capability=SimpleNamespace(disclosure=None),
        )

    real_store = script_proposals.store_ready

    async def store(session: Any, **kwargs: Any) -> bool:
        sessions["store"] = session
        return await real_store(session, **kwargs)

    async def meter(session: Any, **_kwargs: Any) -> None:
        sessions.setdefault("meter", session)

    monkeypatch.setattr(worker, "_draft", drafted)
    monkeypatch.setattr(worker.script_proposals, "store_ready", store)
    monkeypatch.setattr(worker.crm_assist, "meter_earlier", meter)
    monkeypatch.setattr(worker.crm_assist, "meter_assist", meter)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal_id),
    }
    assert await worker.draft_script_proposal({}, payload) == "ready"
    assert sessions["meter"] is sessions["store"]
