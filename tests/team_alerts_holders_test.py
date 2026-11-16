"""A campaign's or inbound line's own "What it notes" answers trigger Tell my team (D-1007).

A call placed by a campaign (or taken by a line) with its own list is captured under that list
(D-1003), so an alert that could only watch the agent's fields never fired on its answers.
"""

from __future__ import annotations

import json
from typing import Any
from uuid import UUID

import httpx
import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.team_alerts import service
from apps.api.team_alerts.service import FieldTrigger, HolderRef, Rule
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _tenant
from tests.team_alerts_test import _alert_payloads, _use_schema, _verified_contact

pytestmark = pytest.mark.rls

VISIT_DAY: dict[str, Any] = {
    "key": "visit_day",
    "label": "Visit day",
    "type": "enum",
    "enum_values": ["saturday", "sunday"],
    "reason": "when they can come",
}
#: The agent's own choice field, copied onto the campaign's list as "Give it its own list" does.
BUDGET: dict[str, Any] = {
    "key": "budget_band",
    "label": "Budget band",
    "type": "enum",
    "enum_values": ["under_20l", "20l_50l", "over_50l"],
    "reason": "what they can spend",
}


async def _campaign(t: Tenant, fields: list[dict[str, Any]], name: str = "Site visits") -> UUID:
    campaign_id = uuid7()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status, "
                "extraction_fields) VALUES (:id, :t, :a, :n, 'service', 'draft', "
                "CAST(:f AS jsonb))"
            ),
            {
                "id": campaign_id,
                "t": t.tenant_id,
                "a": t.agent_id,
                "n": name,
                "f": json.dumps(fields),
            },
        )
    return campaign_id


async def _line(t: Tenant, fields: list[dict[str, Any]]) -> UUID:
    line_id = uuid7()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO inbound_lines (id, tenant_id, agent_id, name, extraction_fields, "
                "created_at, updated_at) VALUES (:id, :t, :a, 'Front desk', CAST(:f AS jsonb), "
                "now(), now())"
            ),
            {"id": line_id, "t": t.tenant_id, "a": t.agent_id, "f": json.dumps(fields)},
        )
    return line_id


async def _call(
    t: Tenant, *, campaign_id: UUID | None = None, inbound_line_id: UUID | None = None
) -> UUID:
    call_id = uuid7()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, campaign_id, inbound_line_id, "
                "engine_call_id, direction, status, from_e164, to_e164, started_at, created_at, "
                "updated_at) VALUES (:id, :t, :a, :g, :l, :e, 'outbound', 'completed', "
                "'+914000000000', '+919812345678', now(), now(), now())"
            ),
            {
                "id": call_id,
                "t": t.tenant_id,
                "a": t.agent_id,
                "g": campaign_id,
                "l": inbound_line_id,
                "e": f"tah-{call_id.hex}",
            },
        )
    return call_id


async def _after(t: Tenant, call_id: UUID, data: dict[str, Any]) -> str:
    async with tenant_session(t.tenant_id) as session:
        return await service.queue_after_call(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            call_id=call_id,
            lead_id=None,
            hot=False,
            outcome_key=None,
            outcome_label=None,
            data=data,
            labels={"visit_day": "Visit day", "budget_band": "Budget band"},
        )


async def test_an_answer_on_a_campaigns_own_list_tells_the_team() -> None:
    t = await _tenant()
    await _use_schema(t)
    await _verified_contact(t)
    campaign_id = await _campaign(t, [VISIT_DAY])
    from apps.api.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://t"
    ) as client:
        offered = await client.get(f"/v1/agents/{t.agent_id}/team-alert", headers=t.headers)
        assert offered.status_code == 200, offered.text
        holders = offered.json()["holders"]
        assert [(h["kind"], h["id"], h["name"]) for h in holders] == [
            ("campaign", str(campaign_id), "Site visits")
        ]
        assert [(f["key"], f["values"]) for f in holders[0]["fields"]] == [
            ("visit_day", ["saturday", "sunday"])
        ]
        put = await client.put(
            f"/v1/agents/{t.agent_id}/team-alert",
            json={
                "on_fields": [
                    {"key": "visit_day", "values": ["saturday"], "campaign_id": str(campaign_id)}
                ]
            },
            headers=t.headers,
        )
        assert put.status_code == 200, put.text
        assert put.json()["on_fields"] == [
            {
                "key": "visit_day",
                "values": ["saturday"],
                "campaign_id": str(campaign_id),
                "inbound_line_id": None,
            }
        ]

    on_campaign = await _call(t, campaign_id=campaign_id)
    assert await _after(t, on_campaign, {"visit_day": "sunday"}) == "not_worth_telling"
    assert await _after(t, on_campaign, {"visit_day": "saturday"}) == "queued"
    # The same answer on a call the campaign did not capture is another list's.
    assert await _after(t, await _call(t), {"visit_day": "saturday"}) == "not_worth_telling"
    async with tenant_session(t.tenant_id) as session:
        reasons = (
            await session.execute(
                text("SELECT reasons FROM team_alerts WHERE call_id = :c"), {"c": on_campaign}
            )
        ).scalar_one()
    assert reasons == [
        {"kind": "field", "key": "visit_day", "label": "Visit day", "values": ["saturday"]}
    ]
    assert len(await _alert_payloads(t.tenant_id)) == 1


async def test_an_answer_on_a_lines_own_list_tells_the_team() -> None:
    t = await _tenant()
    await _use_schema(t)
    await _verified_contact(t)
    line_id = await _line(t, [VISIT_DAY])
    async with tenant_session(t.tenant_id) as session:
        view = await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(
                on_fields=(FieldTrigger("visit_day", ("sunday",), HolderRef("line", line_id)),)
            ),
        )
    assert [h.ref for h in view.holders] == [HolderRef("line", line_id)]
    on_line = await _call(t, inbound_line_id=line_id)
    assert await _after(t, on_line, {"visit_day": "sunday"}) == "queued"


async def test_an_agent_answer_still_fires_on_its_own_and_its_campaigns_calls() -> None:
    t = await _tenant()
    await _use_schema(t)
    await _verified_contact(t)
    campaign_id = await _campaign(t, [BUDGET, VISIT_DAY])
    async with tenant_session(t.tenant_id) as session:
        await service.save_rule(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            rule=Rule(on_fields=(FieldTrigger("budget_band", ("over_50l",)),)),
        )
    assert await _after(t, await _call(t), {"budget_band": "over_50l"}) == "queued"
    held = await _call(t, campaign_id=campaign_id)
    assert await _after(t, held, {"budget_band": "over_50l"}) == "queued"


async def test_an_answer_off_the_holders_list_or_an_archived_holder_is_refused() -> None:
    t = await _tenant()
    await _use_schema(t)
    campaign_id = await _campaign(t, [VISIT_DAY])

    async def _save(trigger: FieldTrigger) -> None:
        async with tenant_session(t.tenant_id) as session:
            await service.save_rule(
                session, tenant_id=t.tenant_id, agent_id=t.agent_id, rule=Rule(on_fields=(trigger,))
            )

    on_campaign = HolderRef("campaign", campaign_id)
    with pytest.raises(ProblemError) as refused:
        await _save(FieldTrigger("visit_day", ("monday",), on_campaign))
    assert refused.value.code == "team_alert_choice_unknown"
    with pytest.raises(ProblemError):
        await _save(FieldTrigger("budget_band", ("over_50l",), on_campaign))

    await _save(FieldTrigger("visit_day", ("saturday",), on_campaign))
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET archived_at = now(), archived_by_realm = 'client' "
                "WHERE id = :c"
            ),
            {"c": campaign_id},
        )
        view = await service.read_rule(session, agent_id=t.agent_id)
    assert view.holders == [] and view.rule.on_fields == ()


async def test_another_tenants_campaign_is_neither_offered_nor_accepted() -> None:
    t, other = await _tenant(), await _tenant()
    await _use_schema(t)
    await _use_schema(other)
    theirs = await _campaign(t, [VISIT_DAY])
    async with tenant_session(other.tenant_id) as session:
        assert (await service.read_rule(session, agent_id=other.agent_id)).holders == []
        with pytest.raises(ProblemError) as refused:
            await service.save_rule(
                session,
                tenant_id=other.tenant_id,
                agent_id=other.agent_id,
                rule=Rule(
                    on_fields=(
                        FieldTrigger("visit_day", ("saturday",), HolderRef("campaign", theirs)),
                    )
                ),
            )
        assert refused.value.code == "team_alert_choice_unknown"
        # RLS: the other tenant's session sees none of this tenant's holders.
        for table in ("campaigns", "inbound_lines"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            assert count == 0, table
