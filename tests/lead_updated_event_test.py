"""`lead.updated` was subscribable and nothing had ever produced one (D-23).

The event has been in `integrations.service.EVENT_TYPES`, in the endpoint form's
checkbox list ("A lead's details change" — `apps/web/src/lib/api/integrations.ts`) and in
`DEFAULT_SHEET_COLUMNS` since the outbound sync shipped. No line of code enqueued one. A
client could tick the box, watch the endpoint save, and wait forever — which is worse
than the feature being absent, because an absent feature does not get relied on.

What this file pins, in the order it matters:

1. an edit that MOVES something produces exactly one event per lead per request;
2. an edit that moves NOTHING produces none — re-saving an unedited row is not news for
   somebody's CRM, and the rename had to grow a CAS to be able to say so;
3. a BULK edit produces one per lead that moved and reads the endpoint list once;
4. the payload is the shape WEBHOOKS §1.2 publishes and the order the Sheets writer's
   default columns expect, with the phone MASKED at the fan-out like `lead.created`;
5. the outbox row commits with the lead row — a rolled-back edit tells nobody.
"""

from __future__ import annotations

import itertools
import json
import uuid
from typing import Any

from apps.api.crm import service as crm
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import service as integrations
from sqlalchemy import text
from tests.api_security_test import _make_tenant

LEAD_NUMBER = "+919876500077"
#: `uq_leads_tenant_id_phone_e164_agent_id` — one number per agent, so a fixture that
#: wants several leads has to give each of them its own.
_SEQ = itertools.count(1)


async def _tenant_with_endpoint(
    events: tuple[str, ...] = ("lead.updated",),
    mapping: dict[str, Any] | None = None,
) -> tuple[uuid.UUID, uuid.UUID]:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, active, created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://crm.example/hook', 'whsec_lead_updated', :events, CAST(:m AS jsonb), "
                "true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "events": list(events),
                "m": json.dumps(mapping or {}),
            },
        )
    return tenant_id, endpoint_id


async def _lead(
    tenant_id: uuid.UUID, *, status: str = "new", name: str = "Ravi", phone: str | None = None
) -> uuid.UUID:
    lead_id = uuid7()
    number = phone or f"+9198765{next(_SEQ):05d}"
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, status, source, "
                "schema_version, created_at, updated_at) VALUES (:id, :tid, :aid, :p, :n, :s, "
                "'inbound_call', 1, now(), now())"
            ),
            {
                "id": lead_id,
                "tid": tenant_id,
                "aid": agent_id,
                "p": number,
                "n": name,
                "s": status,
            },
        )
    return lead_id


async def _queued(tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Every `lead.updated` payload sitting in this tenant's outbox, oldest first."""
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT payload FROM outbox_messages WHERE job = 'deliver_outbound_webhook' "
                    "AND payload->>'tenant_id' = :tid AND payload->>'event' = 'lead.updated' "
                    "ORDER BY created_at, id"
                ),
                {"tid": str(tenant_id)},
            )
        ).all()
    return [dict(row[0]) for row in rows]


async def test_a_status_edit_produces_one_event_with_the_published_payload() -> None:
    tenant_id, _ = await _tenant_with_endpoint()
    lead_id = await _lead(tenant_id)

    async with tenant_session(tenant_id) as session:
        await crm.update_lead(session, lead_id, status="hot", name=None, actor="tester")

    queued = await _queued(tenant_id)
    assert len(queued) == 1, "a lead moved stage and the client's CRM was told once"
    data = queued[0]["data"]
    # The shape WEBHOOKS §1.2 publishes for a `lead.*` event, key for key.
    assert set(data) == {"lead_id", "phone", "name", "source", "status"}
    assert data["lead_id"] == str(lead_id)
    assert data["status"] == "hot", "the payload carries the value AFTER the edit"
    # And the same column order the Sheets writer would lay the row out in, so an
    # endpoint of either kind gets a payload it can render.
    assert set(integrations.DEFAULT_SHEET_COLUMNS["lead.updated"]) == set(data)


async def test_the_phone_is_masked_at_the_fan_out_like_every_other_lead_event() -> None:
    """The event is new; the redaction rule is not, and it is not re-implemented here."""
    tenant_id, _ = await _tenant_with_endpoint()
    lead_id = await _lead(tenant_id, phone=LEAD_NUMBER)
    async with tenant_session(tenant_id) as session:
        await crm.update_lead(session, lead_id, status="hot", name=None, actor="tester")

    body = json.dumps(await _queued(tenant_id))
    assert LEAD_NUMBER not in body
    assert LEAD_NUMBER.removeprefix("+91") not in body
    assert "[redacted]" in body, "masked, not dropped — a missing key would pass the line above"


async def test_an_edit_that_changes_nothing_tells_nobody() -> None:
    """Three no-ops: the same status, the same name, the same owner.

    The rename is the one that needed work — it was a blanket `SET name = :name` that
    always reported success and always bumped `updated_at`, so a client re-saving a row
    would have posted to their CRM (and re-sorted their own Leads table) for nothing.
    """
    tenant_id, _ = await _tenant_with_endpoint()
    lead_id = await _lead(tenant_id, status="hot", name="Ravi")

    async with tenant_session(tenant_id) as session:
        await crm.update_lead(
            session,
            lead_id,
            status="hot",
            name="Ravi",
            assignee=crm.AssigneeChange(user_id=None),
            actor="tester",
        )

    assert await _queued(tenant_id) == [], "a no-op edit produced an outbound delivery"


async def test_two_fields_moving_in_one_patch_is_one_event_not_two() -> None:
    tenant_id, _ = await _tenant_with_endpoint()
    lead_id = await _lead(tenant_id, status="new", name="Ravi")

    async with tenant_session(tenant_id) as session:
        await crm.update_lead(session, lead_id, status="hot", name="Ravi Kumar", actor="tester")

    queued = await _queued(tenant_id)
    assert len(queued) == 1, "one edit, one event — a client's CRM must not see it twice"
    assert queued[0]["data"]["name"] == "Ravi Kumar"
    assert queued[0]["data"]["status"] == "hot"


async def test_a_bulk_action_emits_one_event_per_lead_that_actually_moved() -> None:
    """`unchanged` is a success bucket and it is not news. Only `changed` is."""
    tenant_id, _ = await _tenant_with_endpoint()
    moving = [await _lead(tenant_id, status="new") for _ in range(3)]
    already = await _lead(tenant_id, status="hot")

    async with tenant_session(tenant_id) as session:
        outcome = await crm.apply_bulk_leads(
            session,
            targets=crm.BulkTargets(ids=[*moving, already], missing=[]),
            action="status",
            status="hot",
            actor="tester",
        )

    assert (outcome.changed, outcome.unchanged) == (3, 1)
    queued = await _queued(tenant_id)
    assert {row["data"]["lead_id"] for row in queued} == {str(i) for i in moving}
    assert len(queued) == 3


async def test_two_endpoints_each_get_their_own_row_with_their_own_delivery_id() -> None:
    """Endpoints fail independently, so the fan-out is per endpoint even in bulk."""
    tenant_id, first = await _tenant_with_endpoint()
    second = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', "
                "'https://other.example/hook', 'whsec_second', ARRAY['lead.updated'], true, "
                "now(), now())"
            ),
            {"id": second, "tid": tenant_id},
        )
    leads = [await _lead(tenant_id) for _ in range(2)]

    async with tenant_session(tenant_id) as session:
        await crm.apply_bulk_leads(
            session,
            targets=crm.BulkTargets(ids=leads, missing=[]),
            action="status",
            status="hot",
            actor="tester",
        )

    queued = await _queued(tenant_id)
    assert len(queued) == 4, "two leads times two endpoints"
    assert {row["endpoint_id"] for row in queued} == {str(first), str(second)}
    assert len({row["delivery_id"] for row in queued}) == 4, (
        "a shared delivery id would let one receiver's dedupe swallow another's event"
    )


async def test_an_endpoint_that_did_not_subscribe_hears_nothing() -> None:
    tenant_id, _ = await _tenant_with_endpoint(events=("lead.created", "call.completed"))
    lead_id = await _lead(tenant_id)
    async with tenant_session(tenant_id) as session:
        await crm.update_lead(session, lead_id, status="hot", name=None, actor="tester")
    assert await _queued(tenant_id) == []


async def test_the_outbox_row_rolls_back_with_the_edit_that_produced_it() -> None:
    """BACKEND-PATTERNS §4: no delivery without a committed domain write."""
    tenant_id, _ = await _tenant_with_endpoint()
    lead_id = await _lead(tenant_id)

    class RollbackError(RuntimeError):
        pass

    try:
        async with tenant_session(tenant_id) as session:
            await crm.update_lead(session, lead_id, status="hot", name=None, actor="tester")
            raise RollbackError
    except RollbackError:
        pass

    assert await _queued(tenant_id) == [], "the CRM was told about an edit that rolled back"
    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(text("SELECT status FROM leads WHERE id = :i"), {"i": lead_id})
        ).scalar()
    assert status == "new", "the edit itself did not roll back, so this proves nothing"


async def test_a_neighbours_endpoint_is_never_in_this_tenants_fan_out() -> None:
    """Hard rule 1: the endpoint SELECT is scoped by RLS alone, so it is worth pinning."""
    mine, my_endpoint = await _tenant_with_endpoint()
    theirs, their_endpoint = await _tenant_with_endpoint()
    lead_id = await _lead(mine)

    async with tenant_session(mine) as session:
        await crm.update_lead(session, lead_id, status="hot", name=None, actor="tester")

    queued = await _queued(mine)
    assert [row["endpoint_id"] for row in queued] == [str(my_endpoint)]
    assert str(their_endpoint) not in json.dumps(queued)
    assert await _queued(theirs) == []
