"""The needs-attention queue (SURFACES §2b).

The claim under test: everything the platform refuses to do quietly ends up here, in
words the client can act on — and nothing the client CANNOT act on leaks in. A queue
that mixes "your form needs a consent checkbox" with "engine webhook 502" trains its
reader to skim, and a skimmed queue is no queue at all.
"""

from __future__ import annotations

import uuid

from apps.api.admin import service as admin_service
from apps.api.crm.attention import BLOCK_REMEDIES, attention_queue
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from sqlalchemy import text


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Attention Clinic",
        slug=f"attn-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return created["id"], created["agent_id"]


async def _blocked_lead(tenant_id: uuid.UUID, agent_id: uuid.UUID, rule: str) -> uuid.UUID:
    lead_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, :p, 'Ravi', 'webhook', 'new', "
                "now(), now())"
            ),
            {
                "i": lead_id,
                "t": tenant_id,
                "a": agent_id,
                "p": f"+9198{uuid.uuid4().int % 100000000:08d}",
            },
        )
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) VALUES (:i, :t, :l, 'note', "
                "CAST(:p AS jsonb), 'system', now(), now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "l": lead_id,
                "p": f'{{"kind": "blocked", "rule": "{rule}"}}',
            },
        )
    return lead_id


async def test_a_blocked_dial_appears_with_a_remedy_not_a_rule_name() -> None:
    tenant_id, agent_id = await _tenant()
    await _blocked_lead(tenant_id, agent_id, "no_form_consent")
    async with tenant_session(tenant_id) as session:
        queue = await attention_queue(session)

    assert queue["total"] == 1
    item = queue["items"][0]
    assert item["kind"] == "lead_blocked"
    assert item["title"] == "Ravi was not called"
    assert item["detail"] == BLOCK_REMEDIES["no_form_consent"]
    assert "consent checkbox" in item["detail"], "the remedy tells them what to DO"


async def test_an_unmapped_rule_still_appears_rather_than_vanishing() -> None:
    """A rule whose copy has not been written yet is shown raw — silently dropping the
    item would hide a blocked lead behind our own housekeeping."""
    tenant_id, agent_id = await _tenant()
    await _blocked_lead(tenant_id, agent_id, "some_future_rule")
    async with tenant_session(tenant_id) as session:
        queue = await attention_queue(session)
    assert queue["total"] == 1
    assert "some_future_rule" in queue["items"][0]["detail"]


async def test_a_contacted_lead_leaves_the_queue() -> None:
    """The queue is a to-do list, not a history: once the owner rang them by hand and
    moved the lead on, the block is dealt with."""
    tenant_id, agent_id = await _tenant()
    lead_id = await _blocked_lead(tenant_id, agent_id, "calling_hours")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE leads SET status = 'contacted' WHERE id = :l"), {"l": lead_id}
        )
        queue = await attention_queue(session)
    assert queue["total"] == 0


async def test_a_paused_campaign_and_a_drained_running_one_both_surface() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        for name, status, contact_status in (
            ("Paused push", "paused", "pending"),
            ("Drained push", "running", "dnc_blocked"),
        ):
            campaign_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                    "status, concurrency, created_at, updated_at) VALUES (:i, :t, :a, :n, "
                    "'service', :st, 3, now(), now())"
                ),
                {"i": campaign_id, "t": tenant_id, "a": agent_id, "n": name, "st": status},
            )
            await session.execute(
                text(
                    "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, "
                    "status, attempts, created_at, updated_at) VALUES (:i, :t, :c, :p, :st, 0, "
                    "now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": campaign_id,
                    "p": f"+9198{uuid.uuid4().int % 100000000:08d}",
                    "st": contact_status,
                },
            )
        queue = await attention_queue(session)

    kinds = [item["kind"] for item in queue["items"]]
    details = " | ".join(item["detail"] for item in queue["items"])
    assert kinds.count("campaign_stalled") == 2
    assert "Paused with 1 contacts still to call." in details
    assert "do-not-call list" in details, "the drained campaign says WHY it is silent"


async def test_a_healthy_running_campaign_stays_out_of_the_queue() -> None:
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        campaign_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status, "
                "concurrency, created_at, updated_at) VALUES (:i, :t, :a, 'Healthy', 'service', "
                "'running', 3, now(), now())"
            ),
            {"i": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, status, "
                "attempts, created_at, updated_at) VALUES (:i, :t, :c, '+919876500001', "
                "'pending', 0, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": campaign_id},
        )
        queue = await attention_queue(session)
    assert queue["total"] == 0, "a campaign doing its job is not attention-worthy"


async def test_rejected_knowledge_appears_and_pending_review_does_not() -> None:
    """Waiting for US is not the client's to-do; a rejection with a note is."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        for status, note in (("pending_approval", None), ("rejected", "Prices are out of date.")):
            await session.execute(
                text(
                    "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, status, "
                    "version, rejection_reason, created_at, updated_at) VALUES (:i, :t, :a, "
                    "'text', :n, :st, 1, :note, now(), now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "a": agent_id,
                    "n": f"Doc {status}",
                    "st": status,
                    "note": note,
                },
            )
        queue = await attention_queue(session)

    assert queue["total"] == 1
    item = queue["items"][0]
    assert item["kind"] == "kb_rejected"
    assert item["detail"] == "Prices are out of date."


async def test_the_queue_is_tenant_scoped_like_everything_else() -> None:
    tenant_a, agent_a = await _tenant()
    tenant_b, _ = await _tenant()
    await _blocked_lead(tenant_a, agent_a, "dnc")
    async with tenant_session(tenant_b) as session:
        queue = await attention_queue(session)
    assert queue["total"] == 0, "tenant B never sees tenant A's blocked leads"
