"""Campaign state transitions: what the refusal SAYS, and what the ledger RECORDS.

Two loose ends D-65 left named, and they are the same defect from opposite sides — a
transition that happened but was not written down, and a transition that did not happen
being described in words nobody can act on.

**`launch_campaign`'s CAS used to raise `InvalidStatusTransitionError("campaign",
"non-draft", "running")`.** "non-draft" is not a state; it is a placeholder for the read
nobody did. The branch is nearly unreachable — the launch gate refuses on status first —
but "nearly" is the whole point: it is reached exactly in the race where one tick's gate
read happens before another tick's commit, which is the moment an operator most needs the
message to name the state actually found. Reached here by patching the gate's PREVIEW
(`launch_blockers`) rather than by racing two ticks and hoping, which is the same
technique `campaign_schedule_test.py` uses to pin the CAS-loser branch deterministically.
The patch does not weaken any production path: the gate is still what every real caller
runs, and `scripts/check_compliance_invariants.py` asserts that structurally.

**Pause and resume wrote NO audit row at all.** They are the two controls that start and
stop calls going out to the public, and until now "who stopped the campaign at 16:40" had
no answer anywhere in the system. The rule they follow is the repo's, not a new one: the
row belongs to a REAL transition (`integrations/routes.py::deactivate_endpoint` and
`tenancy.members.set_role` make the same call), so a second click — or the retry of a
request whose response was lost — must add nothing to an append-only ledger. Both
directions are asserted, because a test that only checks the row appears would pass on a
version that writes one per button press.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.admin import service as admin_service
from apps.api.campaigns import service
from apps.api.campaigns.routes import router as campaigns_router
from apps.api.core.errors import InvalidStatusTransitionError, ProblemError, install_error_handlers
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.national_dnd_test import record_test_scrub


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(campaigns_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


async def _tenant() -> tuple[uuid.UUID, uuid.UUID, str]:
    """(tenant, agent, client bearer) — an owner, so `leads:dispatch` is held."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Transition Motors",
        slug=f"trn-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET status = 'live', direction = 'outbound' WHERE id = :a"),
            {"a": agent_id},
        )
        await service.record_dlt_registration(
            session,
            tenant_id=tenant_id,
            pe_id=f"1102{uuid.uuid4().int % 10**9:09d}",
            entity_name="Transition Motors Pvt Ltd",
            status="active",
            tm_link_status="active",
            registered_at=datetime.now(UTC) - timedelta(days=30),
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
    return tenant_id, agent_id, f"dev:client:{user_id}"


async def _launchable_campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        number_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, e164, series, dlt_status, created_at, "
                "updated_at) VALUES (:id, :tid, :e, '140', 'registered', now(), now())"
            ),
            {"id": number_id, "tid": tenant_id, "e": f"+9180{uuid.uuid4().int % 10**8:08d}"},
        )
        template_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO dlt_templates (id, tenant_id, kind, classification, body, status, "
                "created_at, updated_at) VALUES (:id, :tid, 'voice', 'promotional', :body, "
                "'approved', now(), now())"
            ),
            {"id": template_id, "tid": tenant_id, "body": "Hello from {#var#}, an AI assistant."},
        )
        campaign_id = await service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Transition test",
            classification="promotional",
            number_id=number_id,
            dlt_template_id=template_id,
            concurrency=1,
            calling_hours=None,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        await service.add_contacts(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            contacts=[{"phone": "9876520001"}],
        )
        # The national DND scrub SEC-COMP §3 asks for (migration a1c8e40f27b9).
        # A promotional campaign is launch-ready only once an access provider has
        # preference-scrubbed its list, so this fixture supplies the fact through the
        # production writer — `tests/national_dnd_test.py` proves the refusal is real.
        await record_test_scrub(session, campaign_id)
    return campaign_id


async def _audit_actions(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> list[str]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE object_id = :c "
                    "AND action IN ('campaign.paused', 'campaign.resumed') ORDER BY created_at"
                ),
                {"c": str(campaign_id)},
            )
        ).all()
    return [str(row[0]) for row in rows]


# ------------------------------------------------- AF2: the CAS names what it found


async def test_a_lost_launch_race_names_the_state_it_actually_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`non-draft` told an operator nothing. `paused` tells them what happened.

    The gate is patched to green so the CAS is REACHED — which is exactly the state a
    real race produces: the loser's `launch_blockers` ran before the winner committed, so
    it saw a launchable campaign and the CAS is the only thing left to refuse. What the
    refusal must not do is describe the state with a placeholder.
    """
    tenant_id, agent_id, _ = await _tenant()
    campaign_id = await _launchable_campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        assert await service.set_campaign_status(
            session, campaign_id=campaign_id, to_status="paused", from_statuses=("running",)
        )

    async def _gate_says_yes(*_a: object, **_k: object) -> list[service.LaunchBlocker]:
        return []

    monkeypatch.setattr(service, "launch_blockers", _gate_says_yes)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(InvalidStatusTransitionError) as excinfo:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    assert excinfo.value.status == 409
    assert "from paused to running" in excinfo.value.detail
    assert "non-draft" not in excinfo.value.detail, "a placeholder is not a state"


async def test_a_launch_of_a_campaign_that_is_not_there_is_a_404_not_a_conflict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other zero-row fact, and the reason D-65 separates them: 409 asserts a row
    exists. Under RLS a neighbouring tenant's id is invisible, so answering "conflict"
    would both be wrong and confirm the id."""
    tenant_id, _, _ = await _tenant()

    async def _gate_says_yes(*_a: object, **_k: object) -> list[service.LaunchBlocker]:
        return []

    monkeypatch.setattr(service, "launch_blockers", _gate_says_yes)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as excinfo:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=uuid7())
    assert excinfo.value.status == 404


async def test_the_gate_still_refuses_a_launched_campaign_before_the_cas_is_reached() -> None:
    """The branch above is nearly unreachable, and this is what keeps it that way: with
    the real gate in place, launching a running campaign is a NAMED business-rule refusal
    the client can read, not a 409 about a state machine."""
    tenant_id, agent_id, _ = await _tenant()
    campaign_id = await _launchable_campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
        with pytest.raises(ProblemError) as excinfo:
            await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)
    assert excinfo.value.code == "campaign_launch_blocked"
    assert any(field.get("rule") == "status" for field in excinfo.value.fields or [])


# ------------------------------------------- AF3: pause/resume are on the record


async def test_pausing_and_resuming_are_written_down_once_each() -> None:
    """ "Who stopped the calls, and when" had no answer before this. It is the first
    question after a complaint about a campaign that should not have been running."""
    tenant_id, agent_id, token = await _tenant()
    campaign_id = await _launchable_campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as client:
        paused = await client.post(f"/v1/campaigns/{campaign_id}/pause", headers=headers)
        resumed = await client.post(f"/v1/campaigns/{campaign_id}/resume", headers=headers)
    assert (paused.status_code, resumed.status_code) == (204, 204)
    assert await _audit_actions(tenant_id, campaign_id) == [
        "campaign.paused",
        "campaign.resumed",
    ]


async def test_a_second_click_is_still_a_success_and_still_writes_nothing() -> None:
    """The half a "does it audit?" test would miss.

    Pause is idempotent by design (D-65, RFC 9110 §9.2.2) — the panicked double-click and
    the retry of a request whose response was lost are the SAME request as the first. An
    append-only ledger that gained a row for each of them would report two people
    stopping the campaign, one of whom does not exist, and `audit_log` is the artefact
    whose whole value is that it cannot be argued with.
    """
    tenant_id, agent_id, token = await _tenant()
    campaign_id = await _launchable_campaign(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await service.launch_campaign(session, tenant_id=tenant_id, campaign_id=campaign_id)

    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as client:
        first = await client.post(f"/v1/campaigns/{campaign_id}/pause", headers=headers)
        second = await client.post(f"/v1/campaigns/{campaign_id}/pause", headers=headers)
    assert (first.status_code, second.status_code) == (204, 204)
    # 204 and EMPTY, both halves asserted: the transition answers with no body at all
    # (the constant `{"status": "paused"}` it used to return said only what the URL
    # already did, in a shape neither the generated client nor the redaction guardrail
    # could describe). A 204 carrying bytes is a contradiction some frameworks ship.
    assert second.content == b""
    assert await _audit_actions(tenant_id, campaign_id) == ["campaign.paused"]


async def test_a_refused_transition_writes_no_row_for_the_thing_it_refused() -> None:
    """A 409 is a transition that did NOT happen. A row for it would be a ledger entry
    describing an event, written at the moment we established the event did not occur."""
    tenant_id, agent_id, token = await _tenant()
    campaign_id = await _launchable_campaign(tenant_id, agent_id)

    headers = {"Authorization": f"Bearer {token}"}
    async with _client() as client:
        # A draft is neither running nor paused: both controls are a 409 naming `draft`.
        refused = await client.post(f"/v1/campaigns/{campaign_id}/pause", headers=headers)
    assert refused.status_code == 409
    assert "from draft to paused" in refused.json()["detail"]
    assert await _audit_actions(tenant_id, campaign_id) == []
