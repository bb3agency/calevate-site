"""The needs-attention queue (SURFACES §2b).

The claim under test: everything the platform refuses to do quietly ends up here, in
words the client can act on — and nothing the client CANNOT act on leaks in. A queue
that mixes "your form needs a consent checkbox" with "engine webhook 502" trains its
reader to skim, and a skimmed queue is no queue at all.

The second claim, added with the counts fix: **the numbers are about the SET, the list
is about the PAGE.** Each source used to fetch 25 rows and count what came back, so a
client with 40 blocked leads read 25 — on the chip, in the nav bell, and as the "of M"
in "showing the 2 most recent of M". The three tests at the bottom are the ones that
fail if that ever comes back, and they are written to fail on the OLD numbers rather
than merely to pass on the new ones.
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


async def _blocked_leads_bulk(tenant_id: uuid.UUID, agent_id: uuid.UUID, count: int) -> None:
    """`count` blocked leads in two statements — the per-lead helper is 2N round trips.

    Every event gets the same `now()`, which is exactly the case the merge has to get
    right: ties in `occurred_at` must not let an older row from another source jump the
    queue.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) SELECT gen_random_uuid(), :t, :a, "
                "'+9198' || lpad(g::text, 8, '0'), 'Ravi ' || g, 'webhook', 'new', now(), now() "
                "FROM generate_series(1, :n) g"
            ),
            {"t": tenant_id, "a": agent_id, "n": count},
        )
        await session.execute(
            text(
                "INSERT INTO lead_events (id, tenant_id, lead_id, type, payload, actor, "
                "created_at, updated_at) SELECT gen_random_uuid(), :t, l.id, 'note', "
                '\'{"kind": "blocked", "rule": "dnc"}\'::jsonb, \'system\', now(), now() '
                "FROM leads l WHERE l.tenant_id = :t"
            ),
            {"t": tenant_id},
        )


async def test_a_source_bigger_than_the_page_reports_the_true_count() -> None:
    """THE regression test for the saturating badge.

    30 blocked leads and 4 rejected documents, asked for a 10-row page: the list is 10
    and the counts are 30 and 4. The version this replaces answered `len(page)` per
    source, so it said 10 and 4 — and a client with 40 blocked leads was told 25 by a
    number that had no way of admitting it was a ceiling.
    """
    tenant_id, agent_id = await _tenant()
    await _blocked_leads_bulk(tenant_id, agent_id, 30)
    async with tenant_session(tenant_id) as session:
        for n in range(4):
            await session.execute(
                text(
                    "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, status, "
                    "version, rejection_reason, created_at, updated_at) VALUES (:i, :t, :a, "
                    "'text', :n, 'rejected', 1, 'Prices are out of date.', now(), now())"
                ),
                {"i": uuid7(), "t": tenant_id, "a": agent_id, "n": f"Doc {n}"},
            )
        queue = await attention_queue(session, limit=10)

    assert queue["counts"] == {"lead_blocked": 30, "kb_rejected": 4}
    assert queue["total"] == 34, "the badge counts what EXISTS, not what fitted on a page"
    assert len(queue["items"]) == 10, "the page is still a page"
    # The sentence the screen builds out of these two: "showing the 10 most recent of 34".
    assert queue["total"] > len(queue["items"])


async def test_the_page_is_the_newest_rows_even_when_one_source_fills_it() -> None:
    """A source is fetched to the MERGED limit, so the merge can hand the whole page to
    one source when that is where the newest rows are.

    Capping each source lower (the old 25 under a merged 50) made the queue print a
    three-day-old rejection above blocked calls from this morning that it never
    fetched — a "most recent" list that was not.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO kb_sources (id, tenant_id, agent_id, kind, name, status, version, "
                "rejection_reason, created_at, updated_at) VALUES (:i, :t, :a, 'text', 'Old doc', "
                "'rejected', 1, 'Out of date.', now() - interval '3 days', "
                "now() - interval '3 days')"
            ),
            {"i": uuid7(), "t": tenant_id, "a": agent_id},
        )
    await _blocked_leads_bulk(tenant_id, agent_id, 30)

    async with tenant_session(tenant_id) as session:
        queue = await attention_queue(session, limit=28)

    kinds = {item["kind"] for item in queue["items"]}
    assert kinds == {"lead_blocked"}, "a 3-day-old rejection is not one of the 28 newest"
    assert len(queue["items"]) == 28
    assert queue["counts"] == {"lead_blocked": 30, "kb_rejected": 1}


async def test_a_healthy_campaign_neither_counts_nor_takes_a_slot_on_the_page() -> None:
    """ "Stalled" is decided in SQL, so a busy campaign cannot crowd out a stalled one.

    Four healthy running campaigns, touched most recently, and one paused campaign
    behind them. When the filter ran in Python after `LIMIT`, asking for a small page
    fetched four healthy campaigns, discarded them, and reported an account with a
    stalled campaign as having nothing to attend to.
    """
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        for name, status, contact_status, age in (
            ("Paused push", "paused", "pending", "1 hour"),
            ("Busy A", "running", "pending", "1 minute"),
            ("Busy B", "running", "pending", "1 minute"),
            ("Busy C", "running", "pending", "1 minute"),
            ("Busy D", "running", "pending", "1 minute"),
        ):
            campaign_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                    "status, concurrency, created_at, updated_at) VALUES (:i, :t, :a, :n, "
                    f"'service', :st, 3, now(), now() - interval '{age}')"
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
        queue = await attention_queue(session, limit=2)

    assert queue["counts"] == {"campaign_stalled": 1}
    assert [item["title"] for item in queue["items"]] == [
        "Campaign “Paused push” is not making calls"
    ]


async def test_the_queue_is_tenant_scoped_like_everything_else() -> None:
    tenant_a, agent_a = await _tenant()
    tenant_b, _ = await _tenant()
    await _blocked_lead(tenant_a, agent_a, "dnc")
    async with tenant_session(tenant_b) as session:
        queue = await attention_queue(session)
    assert queue["total"] == 0, "tenant B never sees tenant A's blocked leads"
