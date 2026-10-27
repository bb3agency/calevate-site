"""The client's campaign controls (D-773): edit, delete, stop, duplicate, add from leads,
the complaint-spike review, the money pauses and the results.

Each control is driven through its route, so the permission, the CAS and the audit row are
tested together, and against a second tenant, so RLS is part of every answer.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.billing.service import current_billing_month, record_entry
from apps.api.campaigns import controls
from apps.api.campaigns import service as campaigns
from apps.api.campaigns.routes import router as campaigns_router
from apps.api.compliance.optout import DETECTED_IN_CALL, OptOutSignal, record_call_optout
from apps.api.core.errors import install_error_handlers
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.workers import campaign_dispatch
from apps.workers.inbound_cutover import apply_inbound_credit_state
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements, create_org_with_receptionist, fund_wallet


def _client() -> AsyncClient:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(campaigns_router)
    return AsyncClient(transport=ASGITransport(app=application), base_url="http://api")


class Account:
    def __init__(self, tenant_id: uuid.UUID, agent_id: uuid.UUID, token: str) -> None:
        self.tenant_id = tenant_id
        self.agent_id = agent_id
        self.headers = {"Authorization": f"Bearer {token}"}


async def _account(*, funded: bool = True) -> Account:
    reset_engine_cache()
    created = await create_org_with_receptionist(
        name="Controls Motors",
        slug=f"ctl-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    await accept_agreements(tenant_id)
    if funded:
        await fund_wallet(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return Account(tenant_id, agent_id, f"dev:client:{user_id}")


async def _campaign(account: Account, *, contacts: int = 0, status: str = "draft") -> uuid.UUID:
    async with tenant_session(account.tenant_id) as session:
        campaign_id = await campaigns.create_campaign(
            session,
            tenant_id=account.tenant_id,
            agent_id=account.agent_id,
            name=f"Autumn {uuid.uuid4().hex[:4]}",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=3,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        if contacts:
            await campaigns.add_contacts(
                session,
                tenant_id=account.tenant_id,
                campaign_id=campaign_id,
                contacts=[{"phone": f"98765{n:05d}", "name": f"Lead {n}"} for n in range(contacts)],
            )
        if status != "draft":
            await session.execute(
                text("UPDATE campaigns SET status = :s, launched_at = now() WHERE id = :c"),
                {"s": status, "c": campaign_id},
            )
    return campaign_id


async def _one(tenant_id: uuid.UUID, sql: str, **params: Any) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), params)).first()


async def _audits(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> list[str]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE tenant_id = :t AND object_id = :o "
                    "ORDER BY at, id"
                ),
                {"t": tenant_id, "o": str(campaign_id)},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def _call(
    account: Account, campaign_id: uuid.UUID, *, status: str, to: str, duration: int = 0
) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "campaign_id, to_e164, duration_s, started_at, ended_at, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :ref, 'outbound', :st, :cid, :to, :d, now(), now(), "
                "now(), now())"
            ),
            {
                "id": call_id,
                "tid": account.tenant_id,
                "aid": account.agent_id,
                "ref": f"exec_{uuid.uuid4().hex}",
                "st": status,
                "cid": campaign_id,
                "to": to,
                "d": duration,
            },
        )
    return call_id


# --- edit a draft -------------------------------------------------------------------------


async def test_a_draft_is_edited_and_the_fields_changed_are_audited() -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    async with _client() as client:
        response = await client.patch(
            f"/v1/campaigns/{campaign_id}",
            headers=account.headers,
            json={
                "name": "Renamed",
                "concurrency": 2,
                "calling_hours": {"start": "10:00", "end": "13:00"},
                "retry_policy": {"max_attempts": 4, "gaps_minutes": [15, 60, 1440]},
            },
        )
    assert response.status_code == 204, response.text
    row = await _one(
        account.tenant_id,
        "SELECT name, concurrency, calling_hours, retry_policy FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert row[0] == "Renamed" and row[1] == 2
    assert row[2] == {"start": "10:00", "end": "13:00"}
    assert row[3] == {"max_attempts": 4, "backoff_minutes": [15, 60, 1440]}
    assert await _audits(account.tenant_id, campaign_id) == ["campaign.updated"]


async def test_clearing_the_calling_hours_returns_to_the_platform_window() -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    async with _client() as client:
        await client.patch(
            f"/v1/campaigns/{campaign_id}",
            headers=account.headers,
            json={"calling_hours": {"start": "10:00", "end": "13:00"}},
        )
        response = await client.patch(
            f"/v1/campaigns/{campaign_id}", headers=account.headers, json={"calling_hours": None}
        )
    assert response.status_code == 204
    row = await _one(
        account.tenant_id, "SELECT calling_hours FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert row[0] is None


@pytest.mark.parametrize(
    ("body", "code"),
    [
        (
            {"retry_policy": {"max_attempts": 3, "gaps_minutes": [30]}},
            "campaign_retry_gaps_invalid",
        ),
        ({"retry_policy": {"max_attempts": 2, "gaps_minutes": [7]}}, "campaign_retry_gaps_invalid"),
        ({"name": None}, "campaign_field_required"),
        (
            {"calling_hours": {"start": "08:00", "end": "12:00"}},
            "campaign_window_outside_platform_hours",
        ),
    ],
)
async def test_an_edit_the_rules_refuse_names_the_rule(body: dict[str, Any], code: str) -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    async with _client() as client:
        response = await client.patch(
            f"/v1/campaigns/{campaign_id}", headers=account.headers, json=body
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith(f"/{code}")


async def test_a_running_campaign_cannot_be_edited() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    async with _client() as client:
        response = await client.patch(
            f"/v1/campaigns/{campaign_id}", headers=account.headers, json={"name": "Later"}
        )
    assert response.status_code == 422 or response.status_code == 409
    assert response.json()["type"].endswith("/campaign_not_draft")


async def test_contacts_never_tried_are_removed_and_tried_ones_kept() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=3)
    async with tenant_session(account.tenant_id) as session:
        ids = (
            (
                await session.execute(
                    text("SELECT id FROM campaign_contacts WHERE campaign_id = :c ORDER BY id"),
                    {"c": campaign_id},
                )
            )
            .scalars()
            .all()
        )
        await session.execute(
            text("UPDATE campaign_contacts SET attempts = 1 WHERE id = :i"), {"i": ids[0]}
        )
    async with _client() as client:
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/remove",
            headers=account.headers,
            json={"contact_ids": [str(i) for i in ids]},
        )
    assert response.json() == {"removed": 2}


# --- delete a draft -----------------------------------------------------------------------


async def test_a_draft_with_no_history_is_deleted_with_its_contacts() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=2)
    async with _client() as client:
        response = await client.delete(f"/v1/campaigns/{campaign_id}", headers=account.headers)
    assert response.json() == {"outcome": "deleted"}
    assert (
        await _one(account.tenant_id, "SELECT 1 FROM campaigns WHERE id = :c", c=campaign_id)
        is None
    )
    assert (
        await _one(
            account.tenant_id,
            "SELECT 1 FROM campaign_contacts WHERE campaign_id = :c",
            c=campaign_id,
        )
        is None
    )
    assert await _audits(account.tenant_id, campaign_id) == ["campaign.deleted"]


async def test_a_draft_a_call_names_is_kept_as_stopped() -> None:
    account = await _account()
    campaign_id = await _campaign(account)
    await _call(account, campaign_id, status="completed", to="+919876500001")
    async with _client() as client:
        response = await client.delete(f"/v1/campaigns/{campaign_id}", headers=account.headers)
    assert response.json() == {"outcome": "stopped"}
    row = await _one(account.tenant_id, "SELECT status FROM campaigns WHERE id = :c", c=campaign_id)
    assert row[0] == "cancelled"


async def test_only_a_draft_can_be_deleted() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    async with _client() as client:
        response = await client.delete(f"/v1/campaigns/{campaign_id}", headers=account.headers)
    assert response.json()["type"].endswith("/campaign_not_draft")


async def test_another_accounts_campaign_is_not_found_for_every_control() -> None:
    owner, stranger = await _account(), await _account()
    campaign_id = await _campaign(owner, contacts=1)
    async with _client() as client:
        answers = [
            await client.patch(
                f"/v1/campaigns/{campaign_id}", headers=stranger.headers, json={"name": "Mine"}
            ),
            await client.delete(f"/v1/campaigns/{campaign_id}", headers=stranger.headers),
            await client.post(f"/v1/campaigns/{campaign_id}/stop", headers=stranger.headers),
            await client.post(
                f"/v1/campaigns/{campaign_id}/duplicate", headers=stranger.headers, json={}
            ),
            await client.get(f"/v1/campaigns/{campaign_id}/contacts", headers=stranger.headers),
            await client.get(f"/v1/campaigns/{campaign_id}/results", headers=stranger.headers),
            await client.get(f"/v1/campaigns/{campaign_id}/opt-outs", headers=stranger.headers),
        ]
    assert [a.status_code for a in answers] == [404] * len(answers)
    row = await _one(
        owner.tenant_id, "SELECT name, status FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert row[1] == "draft" and not row[0].startswith("Mine")


# --- stop for good ------------------------------------------------------------------------


async def test_stop_cancels_a_running_campaign_once_and_drops_its_repeat() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=2, status="running")
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text('UPDATE campaigns SET schedule = \'{"kind": "recurring"}\' WHERE id = :c'),
            {"c": campaign_id},
        )
    async with _client() as client:
        first = await client.post(f"/v1/campaigns/{campaign_id}/stop", headers=account.headers)
        second = await client.post(f"/v1/campaigns/{campaign_id}/stop", headers=account.headers)
    assert (first.status_code, second.status_code) == (204, 204)
    row = await _one(
        account.tenant_id, "SELECT status, schedule FROM campaigns WHERE id = :c", c=campaign_id
    )
    assert row[0] == "cancelled" and row[1] is None
    assert await _audits(account.tenant_id, campaign_id) == ["campaign.stopped"]


async def test_two_concurrent_stops_move_the_campaign_once() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="paused")

    async def stop_once() -> bool:
        async with tenant_session(account.tenant_id) as session:
            return await controls.stop_campaign(session, campaign_id=campaign_id)

    outcomes = await asyncio.gather(stop_once(), stop_once())
    assert sorted(outcomes) == [False, True]


async def test_a_completed_campaign_cannot_be_stopped() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="completed")
    async with _client() as client:
        response = await client.post(f"/v1/campaigns/{campaign_id}/stop", headers=account.headers)
    assert response.status_code == 409


# --- duplicate and re-call ----------------------------------------------------------------


async def test_duplicate_copies_settings_and_with_unreached_only_the_people_never_reached() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=4, status="cancelled")
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = CASE phone_e164 "
                "WHEN '+919876500000' THEN 'connected' WHEN '+919876500001' THEN 'dnc_blocked' "
                "WHEN '+919876500002' THEN 'failed' ELSE 'pending' END WHERE campaign_id = :c"
            ),
            {"c": campaign_id},
        )
        await session.execute(
            text(
                "UPDATE campaigns SET retry_policy = "
                '\'{"max_attempts": 2, "backoff_minutes": [60]}\' WHERE id = :c'
            ),
            {"c": campaign_id},
        )
    async with _client() as client:
        plain = await client.post(
            f"/v1/campaigns/{campaign_id}/duplicate", headers=account.headers, json={}
        )
        recall = await client.post(
            f"/v1/campaigns/{campaign_id}/duplicate",
            headers=account.headers,
            json={"with_unreached": True},
        )
    assert plain.status_code == 201 and plain.json()["contacts_added"] == 0
    assert recall.json()["contacts_added"] == 2
    copy = await _one(
        account.tenant_id,
        "SELECT name, status, retry_policy, consent_source FROM campaigns WHERE id = :c",
        c=uuid.UUID(recall.json()["id"]),
    )
    assert copy[0].startswith("Call again: ") and copy[1] == "draft"
    assert copy[2] == {"max_attempts": 2, "backoff_minutes": [60]}
    assert copy[3] is None, "the consent declaration is about a list and is asked again"


async def test_a_running_campaign_cannot_be_recalled() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=1, status="running")
    async with _client() as client:
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/duplicate",
            headers=account.headers,
            json={"with_unreached": True},
        )
    assert response.json()["type"].endswith("/campaign_still_running")


# --- add from leads -----------------------------------------------------------------------


async def _lead(
    account: Account, *, phone: str, status: str, source: str = "inbound_call"
) -> uuid.UUID:
    lead_id = uuid7()
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:id, :t, :a, :p, 'Lead', :src, :st, now(), now())"
            ),
            {
                "id": lead_id,
                "t": account.tenant_id,
                "a": account.agent_id,
                "p": phone,
                "src": source,
                "st": status,
            },
        )
    return lead_id


async def test_leads_are_added_by_selection() -> None:
    account = await _account()
    await _lead(account, phone="+919811100001", status="hot")
    picked = await _lead(account, phone="+919811100003", status="lost")
    campaign_id = await _campaign(account)
    async with _client() as client:
        by_id = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/from-leads",
            headers=account.headers,
            json={"lead_ids": [str(picked)]},
        )
    assert by_id.json()["added"] == 1


async def test_leads_are_added_by_the_lens_with_the_confirmed_count() -> None:
    account = await _account()
    picked = await _lead(account, phone="+919811100011", status="hot")
    await _lead(account, phone="+919811100012", status="hot")
    await _lead(account, phone="+919811100013", status="lost")
    campaign_id = await _campaign(account)
    async with _client() as client:
        uncounted = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/from-leads",
            headers=account.headers,
            json={"lens": {"status": "hot"}},
        )
        moved = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/from-leads",
            headers=account.headers,
            json={"lens": {"status": "hot"}, "expected_count": 3},
        )
        added = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/from-leads",
            headers=account.headers,
            json={"lens": {"status": "hot"}, "expected_count": 2},
        )
        two_ways = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/from-leads",
            headers=account.headers,
            json={"lens": {"status": "hot"}, "expected_count": 2, "lead_ids": [str(picked)]},
        )
    assert uncounted.json()["type"].endswith("/campaign_leads_count_required")
    assert moved.status_code == 409
    assert moved.json()["type"].endswith("/campaign_leads_set_moved")
    assert added.status_code == 200, added.text
    assert (added.json()["added"], added.json()["plan_id"]) == (2, None)
    assert two_ways.json()["type"].endswith("/campaign_leads_selection_invalid")
    assert "campaign.contacts_added" in await _audits(account.tenant_id, campaign_id)


async def test_a_lens_larger_than_one_add_runs_as_an_approved_plan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    account = await _account()
    await _lead(account, phone="+919811100021", status="hot")
    await _lead(account, phone="+919811100022", status="hot")
    campaign_id = await _campaign(account)
    monkeypatch.setattr(controls, "MAX_LEADS_PER_ADD", 1)
    async with _client() as client:
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/from-leads",
            headers=account.headers,
            json={"lens": {"status": "hot"}, "expected_count": 2},
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["added"] == 0 and body["plan_id"] is not None
    plan = await _one(
        account.tenant_id,
        "SELECT tool, status, target_count + excluded_count FROM copilot_plans WHERE id = :p",
        p=uuid.UUID(body["plan_id"]),
    )
    assert (plan[0], plan[2]) == ("campaign_add_leads", 2)
    assert plan[1] in ("approved", "running", "done")


async def test_another_accounts_leads_are_never_added() -> None:
    owner, stranger = await _account(), await _account()
    foreign = await _lead(stranger, phone="+919822200001", status="hot")
    campaign_id = await _campaign(owner)
    async with _client() as client:
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/from-leads",
            headers=owner.headers,
            json={"lead_ids": [str(foreign)]},
        )
        # The lens runs under the caller's RLS too: the stranger's lead is not counted.
        by_lens = await client.post(
            f"/v1/campaigns/{campaign_id}/contacts/from-leads",
            headers=owner.headers,
            json={"lens": {}, "expected_count": 0},
        )
    assert response.json()["added"] == 0
    assert by_lens.status_code == 200, by_lens.text
    assert by_lens.json()["added"] == 0


# --- complaint-spike review ---------------------------------------------------------------


async def _spiked_and_paused(account: Account) -> uuid.UUID:
    campaign_id = await _campaign(account, status="running")
    calls = []
    for n in range(4):
        phone = f"+91987650{n:04d}"
        calls.append((await _call(account, campaign_id, status="completed", to=phone), phone))
    async with tenant_session(account.tenant_id) as session:
        for call_id, phone in calls[:3]:
            await record_call_optout(
                session,
                tenant_id=account.tenant_id,
                raw_phone=phone,
                call_id=call_id,
                detected_by=DETECTED_IN_CALL,
                signal=OptOutSignal(
                    rule="engine_tool_call", language="en", turn_idx=None, matched="stop calling"
                ),
            )
    from apps.api.campaigns.complaint_spike import check_complaint_spike

    async with tenant_session(account.tenant_id) as session:
        spike = await check_complaint_spike(
            session, tenant_id=account.tenant_id, campaign_id=campaign_id
        )
    assert spike is not None and spike.paused
    return campaign_id


async def test_a_complaint_spike_pause_needs_a_review_before_resume() -> None:
    account = await _account()
    campaign_id = await _spiked_and_paused(account)
    async with _client() as client:
        progress = (
            await client.get(f"/v1/campaigns/{campaign_id}", headers=account.headers)
        ).json()
        refused = await client.post(f"/v1/campaigns/{campaign_id}/resume", headers=account.headers)
        opt_outs = (
            await client.get(f"/v1/campaigns/{campaign_id}/opt-outs", headers=account.headers)
        ).json()
        reviewed = await client.post(
            f"/v1/campaigns/{campaign_id}/complaint-review",
            headers=account.headers,
            json={"reviewed": True},
        )
        again = await client.post(
            f"/v1/campaigns/{campaign_id}/complaint-review",
            headers=account.headers,
            json={"reviewed": True},
        )
        resumed = await client.post(f"/v1/campaigns/{campaign_id}/resume", headers=account.headers)
    assert progress["pause_reason"] == "complaint_spike"
    assert progress["complaint_review_required"] is True
    assert refused.json()["type"].endswith("/complaint_review_required")
    assert len(opt_outs) == 3 and opt_outs[0]["words_redacted"] == "stop calling"
    assert (reviewed.status_code, again.status_code, resumed.status_code) == (204, 204, 204)
    assert (await _audits(account.tenant_id, campaign_id)).count(
        "campaign.complaint_review_confirmed"
    ) == 1
    # The reviewed opt-outs do not pause it a second time.
    from apps.api.campaigns.complaint_spike import check_complaint_spike

    async with tenant_session(account.tenant_id) as session:
        assert (
            await check_complaint_spike(
                session, tenant_id=account.tenant_id, campaign_id=campaign_id
            )
            is None
        )


async def test_a_review_with_nothing_to_review_is_refused() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="paused")
    async with _client() as client:
        response = await client.post(
            f"/v1/campaigns/{campaign_id}/complaint-review",
            headers=account.headers,
            json={"reviewed": True},
        )
    assert response.json()["type"].endswith("/complaint_review_not_needed")


async def test_a_second_pause_click_keeps_the_complaint_hold() -> None:
    account = await _account()
    campaign_id = await _spiked_and_paused(account)
    async with _client() as client:
        await client.post(f"/v1/campaigns/{campaign_id}/pause", headers=account.headers)
        refused = await client.post(f"/v1/campaigns/{campaign_id}/resume", headers=account.headers)
    assert refused.json()["type"].endswith("/complaint_review_required")


# --- out of credit and the spending cap ---------------------------------------------------


async def _drain(tenant_id: uuid.UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await record_entry(
            session,
            tenant_id=tenant_id,
            delta=Decimal("-10000.00"),
            reason="adjustment",
            ref=f"drain-{uuid.uuid4().hex}",
            allow_negative=True,
        )


async def test_out_of_credit_pauses_with_its_reason_and_a_top_up_resumes_it() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=2, status="running")
    await _drain(account.tenant_id)
    result = await campaign_dispatch._dispatch_for_campaign(
        account.tenant_id, campaign_id, 2, campaigns.DEFAULT_RETRY_POLICY
    )
    assert result == {"dialled": 0, "blocked": 0, "exhausted": 0}
    row = await _one(
        account.tenant_id,
        "SELECT status, auto_pause_reason FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert tuple(row) == ("paused", "out_of_credit")
    attempts = await _one(
        account.tenant_id,
        "SELECT sum(attempts) FROM campaign_contacts WHERE campaign_id = :c",
        c=campaign_id,
    )
    assert attempts[0] == 0, "nobody was claimed"
    async with _client() as client:
        refused = await client.post(f"/v1/campaigns/{campaign_id}/resume", headers=account.headers)
    assert refused.json()["type"].endswith("/no_credits")

    await fund_wallet(account.tenant_id, "20000.00")
    await apply_inbound_credit_state({"job_try": 1}, {"tenant_id": str(account.tenant_id)})
    await apply_inbound_credit_state({"job_try": 1}, {"tenant_id": str(account.tenant_id)})
    row = await _one(
        account.tenant_id,
        "SELECT status, auto_pause_reason FROM campaigns WHERE id = :c",
        c=campaign_id,
    )
    assert tuple(row) == ("running", None)
    actions = await _audits(account.tenant_id, campaign_id)
    assert actions == ["campaign.paused", "campaign.resumed"], "the second job run is a no-op"


async def test_a_person_paused_campaign_is_not_resumed_by_a_top_up() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="paused")
    await apply_inbound_credit_state({"job_try": 1}, {"tenant_id": str(account.tenant_id)})
    row = await _one(account.tenant_id, "SELECT status FROM campaigns WHERE id = :c", c=campaign_id)
    assert row[0] == "paused"


async def test_the_spending_cap_pauses_and_does_not_resume_by_itself() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=1, status="running")
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped, created_at, updated_at) "
                "VALUES (:t, :m, 0, 0, 0, true, now(), now())"
            ),
            {"t": account.tenant_id, "m": current_billing_month()},
        )
    await campaign_dispatch._dispatch_for_campaign(
        account.tenant_id, campaign_id, 1, campaigns.DEFAULT_RETRY_POLICY
    )
    await apply_inbound_credit_state({"job_try": 1}, {"tenant_id": str(account.tenant_id)})
    async with _client() as client:
        progress = (
            await client.get(f"/v1/campaigns/{campaign_id}", headers=account.headers)
        ).json()
        refused = await client.post(f"/v1/campaigns/{campaign_id}/resume", headers=account.headers)
    assert (progress["status"], progress["pause_reason"]) == ("paused", "spend_cap")
    assert refused.json()["type"].endswith("/spend_cap")


# --- the detail page's facts --------------------------------------------------------------


async def test_a_running_campaign_that_cannot_call_says_why() -> None:
    account = await _account()
    campaign_id = await _campaign(account, status="running")
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET consent_source = NULL, consent_collected_at = NULL "
                "WHERE id = :c"
            ),
            {"c": campaign_id},
        )
    async with _client() as client:
        progress = (
            await client.get(f"/v1/campaigns/{campaign_id}", headers=account.headers)
        ).json()
    rules = [b["rule"] for b in progress["not_calling"]]
    assert "consent_provenance_missing" in rules
    assert progress["effective_concurrency"] <= progress["concurrency"]
    assert progress["retry_policy"] == {"max_attempts": 3, "gaps_minutes": [30, 120]}


async def test_results_count_outcomes_from_the_calls_and_spend_in_rupees() -> None:
    account = await _account()
    campaign_id = await _campaign(account, contacts=4, status="running")
    phones = ["+919876500000", "+919876500001", "+919876500002", "+919876500003"]
    answered = await _call(account, campaign_id, status="completed", to=phones[0], duration=90)
    busy = await _call(account, campaign_id, status="busy", to=phones[1])
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'connected', attempts = 1, "
                "last_call_id = :call, last_attempt_at = now() "
                "WHERE campaign_id = :c AND phone_e164 = :p"
            ),
            {"call": answered, "c": campaign_id, "p": phones[0]},
        )
        await session.execute(
            text(
                "UPDATE campaign_contacts SET status = 'pending', attempts = 1, "
                "last_call_id = :call, last_attempt_at = now(), "
                "next_attempt_at = now() + interval '30 minutes' "
                "WHERE campaign_id = :c AND phone_e164 = :p"
            ),
            {"call": busy, "c": campaign_id, "p": phones[1]},
        )
        await record_entry(
            session,
            tenant_id=account.tenant_id,
            delta=Decimal("-7.50"),
            reason="usage",
            ref=str(answered),
        )
    async with _client() as client:
        page = (
            await client.get(f"/v1/campaigns/{campaign_id}/contacts", headers=account.headers)
        ).json()
        busy_only = (
            await client.get(
                f"/v1/campaigns/{campaign_id}/contacts",
                headers=account.headers,
                params={"outcome": "busy"},
            )
        ).json()
        summary = (
            await client.get(f"/v1/campaigns/{campaign_id}/results", headers=account.headers)
        ).json()
    assert page["counts"]["connected"] == 1
    assert page["counts"]["busy"] == 1
    assert page["counts"]["not_called"] == 2
    assert busy_only["total"] == 1
    item = busy_only["items"][0]
    assert item["will_retry"] is True and item["next_attempt_at"] is not None
    assert item["call_id"] == str(busy)
    assert summary["pickup_rate"] == 0.5
    assert summary["average_call_s"] == 90
    assert Decimal(summary["credits_spent_inr"]) == Decimal("7.50")


async def test_results_break_down_the_agents_outcomes_and_each_choice_field() -> None:
    """D-905: counts per business outcome over the answered calls, and per value of each
    enum the agent captures over the people reached, with the gaps counted too."""
    account = await _account()
    campaign_id = await _campaign(account, contacts=3, status="running")
    fields = [
        {
            "key": "registered",
            "label": "Registered",
            "type": "enum",
            "enum_values": ["Yes", "No"],
        }
    ]
    async with tenant_session(account.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO extraction_schemas (id, tenant_id, agent_id, version, fields, "
                "created_at, updated_at) VALUES (:id, :t, :a, 99, CAST(:f AS jsonb), now(), "
                "now())"
            ),
            {"id": uuid7(), "t": account.tenant_id, "a": account.agent_id, "f": json.dumps(fields)},
        )
    answers = [
        ("yes", "onboarded", "Onboarded"),
        ("Yes", "onboarded", "Onboarded"),
        (None, None, None),
    ]
    for n, (registered, key, label) in enumerate(answers):
        phone = f"+91987650000{n}"
        lead_id = await _lead(account, phone=phone, status="contacted")
        call_id = await _call(account, campaign_id, status="completed", to=phone, duration=60)
        async with tenant_session(account.tenant_id) as session:
            await session.execute(
                text("UPDATE leads SET data = CAST(:d AS jsonb) WHERE id = :l"),
                {"d": json.dumps({"registered": registered} if registered else {}), "l": lead_id},
            )
            await session.execute(
                text(
                    "UPDATE calls SET lead_id = :l, business_outcome = :k, "
                    "business_outcome_label = :lb WHERE id = :c"
                ),
                {"l": lead_id, "k": key, "lb": label, "c": call_id},
            )
    async with _client() as client:
        summary = (
            await client.get(f"/v1/campaigns/{campaign_id}/results", headers=account.headers)
        ).json()
    assert summary["business_outcomes"] == [{"key": "onboarded", "label": "Onboarded", "count": 2}]
    assert summary["business_outcomes_unset"] == 1
    registered = next(f for f in summary["fields"] if f["key"] == "registered")
    assert registered["values"] == [{"value": "Yes", "count": 2}, {"value": "No", "count": 0}]
    assert registered["not_captured"] == 1


async def test_the_page_filters_by_status_and_counts_every_status() -> None:
    account = await _account()
    await _campaign(account, status="running")
    await _campaign(account)
    await _campaign(account)
    async with _client() as client:
        page = (
            await client.get(
                "/v1/campaigns/page", headers=account.headers, params={"status": "draft"}
            )
        ).json()
    assert page["total"] == 2 and len(page["items"]) == 2
    assert page["status_counts"]["running"] == 1


async def test_a_transactional_campaign_cannot_be_filed() -> None:
    account = await _account()
    async with _client() as client:
        response = await client.post(
            "/v1/campaigns",
            headers=account.headers,
            json={
                "agent_id": str(account.agent_id),
                "name": "Receipts",
                "classification": "transactional",
            },
        )
    assert response.status_code == 422
