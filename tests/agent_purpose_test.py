"""An agent is for selling or for helping customers (founder, 21 Nov 2026).

What is stored and how a new agent gets it, how the owner changes it, and the account-level
words it drives. The lead move it governs is `tests/post_call_truth_test.py`.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import lifecycle
from apps.api.db.session import tenant_session
from apps.api.tenancy.business_copy import Capabilities
from apps.api.tenancy.caller_words import CallerWords, all_support
from sqlalchemy import text
from tests.agent_lifecycle_test import _app, _client, _move, _tenant, _write_script

pytestmark = [pytest.mark.rls]


def _caps(sells: bool | None) -> Capabilities:
    caps = Capabilities.unknown()
    return caps.model_copy(update={"sells": caps.sells.model_copy(update={"applies": sells})})


def test_a_new_agent_is_support_only_for_a_business_judged_to_sell_nothing() -> None:
    assert lifecycle.purpose_for_business(_caps(False)) == "support"
    assert lifecycle.purpose_for_business(_caps(True)) == "sales"
    assert lifecycle.purpose_for_business(_caps(None)) == "sales", "unjudged keeps today's"


async def _purpose(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT purpose FROM agents WHERE id = :aid"), {"aid": agent_id}
                )
            ).scalar()
        )


async def test_an_agent_created_for_a_business_that_sells_nothing_is_support(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, receptionist, token = await _tenant()
    assert await _purpose(tenant_id, receptionist) == "sales"

    async def no_sales(_session: Any, _tenant_id: uuid.UUID) -> Capabilities:
        return _caps(False)

    monkeypatch.setattr(lifecycle, "capabilities_for", no_sales)
    async with _client(_app()) as http:
        response = await http.post(
            "/v1/agents",
            json={"name": "Help desk", "direction": "inbound"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201, response.text
    assert response.json()["purpose"] == "support"


async def test_the_owner_changes_the_purpose_without_republishing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    assert (await _move(token, agent_id, "prepare"))[0] == 200
    published: list[uuid.UUID] = []
    real = lifecycle.publish_agent

    async def spy(session: Any, **kwargs: Any) -> Any:
        published.append(kwargs["agent_id"])
        return await real(session, **kwargs)

    monkeypatch.setattr(lifecycle, "publish_agent", spy)
    async with _client(_app()) as http:
        changed = await http.patch(
            f"/v1/agents/{agent_id}",
            json={"purpose": "support"},
            headers={"Authorization": f"Bearer {token}"},
        )
        refused = await http.patch(
            f"/v1/agents/{agent_id}",
            json={"purpose": "helpdesk"},
            headers={"Authorization": f"Bearer {token}"},
        )
        listed = await http.get("/v1/agents", headers={"Authorization": f"Bearer {token}"})
    assert changed.status_code == 200, changed.text
    assert changed.json()["purpose"] == "support"
    assert published == [], "a purpose change reaches nothing the voice platform holds"
    assert refused.status_code == 422
    assert next(a for a in listed.json() if a["id"] == str(agent_id))["purpose"] == "support"
    assert await _purpose(tenant_id, agent_id) == "support"


async def test_an_account_reads_caller_words_only_when_every_working_agent_is_support() -> None:
    tenant_id, agent_id, _token = await _tenant()
    async with tenant_session(tenant_id) as session:
        assert await all_support(session, tenant_id) is False
        await session.execute(
            text("UPDATE agents SET purpose = 'support' WHERE id = :aid"), {"aid": agent_id}
        )
        assert await all_support(session, tenant_id) is True
        seller = await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Sales line",
            direction="outbound",
            language_primary="te-IN",
        )
        assert await all_support(session, tenant_id) is False
        await session.execute(
            text("UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :aid"),
            {"aid": seller},
        )
        assert await all_support(session, tenant_id) is True, "an archived agent takes no calls"

    assert CallerWords(sells=True, all_support=True).leads == "interested callers"
    assert CallerWords(sells=True, all_support=True).hot_lead == "most interested caller"
    assert CallerWords(sells=True).leads == "leads"
