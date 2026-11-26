"""Pip's campaign script, end to end through the job (D-1004).

1. The owner's tone and instruction reach the writer, and the edit is checked against the
   campaign's own sources (a figure from them is not "a figure no fact gives").
2. The review pass stores one "why" per part Pip wrote, turns a claim no source backs into a
   warning on its part, and is metered with the draft. Its failure keeps the draft.
3. A draft too long for the agent's box is shortened once, never touching the openings, and
   one still too long is offered with a warning rather than refused at Keep.
4. The route stores the tone and instruction, keeps the typed text out of the audit row and
   refuses a tone it does not offer.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the writer and the review are replaced.
"""

from __future__ import annotations

import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.prompt_size import PromptSize, SizePart
from apps.api.agents.script_lint import LintContext
from apps.api.campaigns import workspace
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.workers.campaign_script_ask import INSTRUCTION_MAX
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_starters_test import _tenant
from tests.campaign_script_writer_2026_11_15_test import (
    MAIN_TASK,
)

pytestmark = pytest.mark.rls

LINT = LintContext(promo=False)


def _size(over: int) -> PromptSize:
    return PromptSize(
        total=20_000 + over,
        limit=20_000,
        layers=(SizePart("client_script", "Your script", 9_000),),
        script_parts=(SizePart("[CONVERSATION]", "Steps", 6_000),),
    )


async def _route_campaign() -> tuple[UUID, UUID, str]:
    tenant_id, token = await _tenant("real_estate", "Sunrise Homes")
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT id FROM agents ORDER BY created_at LIMIT 1"))
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification) "
                "VALUES (:id, :t, :a, 'Visits', 'service')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await workspace.save_main_task(session, campaign_id, MAIN_TASK)
    return tenant_id, campaign_id, token


async def _post(token: str, campaign_id: UUID, body: dict[str, Any]) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.post(
            f"/v1/campaigns/{campaign_id}/script/proposal",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )


async def test_the_route_stores_the_ask_and_keeps_the_typed_words_out_of_the_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.campaigns import workspace_routes

    summaries: list[dict[str, Any]] = []
    written = workspace_routes.write_audit

    async def write_audit(session: Any, **kwargs: Any) -> Any:
        summaries.append(kwargs.get("summary") or {})
        return await written(session, **kwargs)

    monkeypatch.setattr(workspace_routes, "write_audit", write_audit)
    tenant_id, campaign_id, token = await _route_campaign()
    refused = await _post(token, campaign_id, {"tone": "shouty"})
    assert refused.status_code == 422, refused.text
    too_long = await _post(token, campaign_id, {"instruction": "x" * (INSTRUCTION_MAX + 1)})
    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["detail"] == (
        f"Keep the note for Pip to {INSTRUCTION_MAX:,} characters or fewer."
    )
    response = await _post(
        token, campaign_id, {"tone": "warm", "instruction": "  Say   our name slowly. "}
    )
    assert response.status_code == 202, response.text
    assert response.json()["why"] == {}
    async with tenant_session(tenant_id) as session:
        asked = (
            await session.execute(
                text("SELECT script_proposal->'ask' FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
    assert asked == {"tone": "warm", "instruction": "Say our name slowly."}
    [audit] = summaries
    assert audit["tone"] == "warm" and audit["instructed"] is True
    assert "slowly" not in str(audit)
