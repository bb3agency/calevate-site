"""The auto-healer against a real database (D-701): isolation, the ledger, incidents, the
health score from real call rows, a line held and given back, and the HTTP surfaces.

SHARED DATABASE DISCIPLINE: every organisation here is minted by this module and every
assertion is scoped to its own ids; nothing counts rows globally.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import prompts
from apps.api.agents import service as agents_service
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.healer import health, incidents, ledger, protection, status
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from tests.conftest import accept_agreements, fund_wallet

pytestmark = pytest.mark.asyncio

TENANT_TABLES = (
    "heal_client_incidents",
    "heal_fallback_phones",
    "agent_health_windows",
    "heal_proposals",
)


async def _org(prefix: str) -> tuple[UUID, UUID, str]:
    created = await admin_service.create_organization(
        name="Healer Clinic",
        slug=f"heal-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"])), str(created["slug"])


async def _incident(*, tenant_id: UUID | None = None, agent_id: UUID | None = None) -> UUID:
    async with untenanted_session() as session:
        incident_id, opened = await incidents.open_incident(
            session,
            key=incidents.dedupe_key("line_protection", uuid.uuid4()),
            playbook="line_protection",
            trigger_code="agent_line_broken",
            scope="agent",
            tenant_id=tenant_id,
            agent_id=agent_id,
        )
    assert opened
    return incident_id


async def _seed(tenant_id: UUID, agent_id: UUID) -> None:
    incident_id = await _incident(tenant_id=tenant_id, agent_id=agent_id)
    async with tenant_session(tenant_id) as session:
        await protection.client_incident(
            session,
            tenant_id=tenant_id,
            incident_id=incident_id,
            agent_id=agent_id,
            kind="line_protected",
        )
        await session.execute(
            text(
                "INSERT INTO heal_fallback_phones (id, tenant_id, phone_e164, created_at, "
                "updated_at) VALUES (:id, :t, '+919000000071', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id},
        )
        await health.record_window(
            session,
            tenant_id=tenant_id,
            start=health.window_start(datetime.now(UTC)),
            counts=health.WindowCounts(
                agent_id=agent_id,
                calls=3,
                short_calls=0,
                failed_calls=0,
                slow_starts=0,
                escalations=0,
                knowledge_misses=0,
                action_failures=0,
                language_misses=0,
            ),
        )
        await session.execute(
            text(
                "INSERT INTO heal_proposals (id, tenant_id, agent_id, kind, status, created_at, "
                "updated_at) VALUES (:id, :t, :a, 'review_knowledge', 'pending', now(), now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id},
        )


# --- isolation ------------------------------------------------------------------------------


@pytest.mark.rls
async def test_each_healer_table_shows_a_tenant_only_its_own_rows() -> None:
    first, first_agent, _ = await _org("rls-a")
    second, second_agent, _ = await _org("rls-b")
    await _seed(first, first_agent)
    await _seed(second, second_agent)
    async with tenant_session(first) as session:
        for table in TENANT_TABLES:
            mine = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            theirs = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": second}
                )
            ).scalar()
            assert mine == 1, table
            assert theirs == 0, table


@pytest.mark.rls
async def test_an_untenanted_session_reads_only_the_notice_worklist() -> None:
    """`heal_client_incidents` carries a read-only policy for the untenanted notice sweep;
    the other three are fail-closed, and nothing is writable without a tenant."""
    tenant_id, agent_id, _ = await _org("rls-untenanted")
    await _seed(tenant_id, agent_id)
    async with untenanted_session() as session:
        for table in ("heal_fallback_phones", "agent_health_windows", "heal_proposals"):
            count = (
                await session.execute(
                    text(f"SELECT count(*) FROM {table} WHERE tenant_id = :t"), {"t": tenant_id}
                )
            ).scalar()
            assert count == 0, table
        visible = (
            await session.execute(
                text("SELECT count(*) FROM heal_client_incidents WHERE tenant_id = :t"),
                {"t": tenant_id},
            )
        ).scalar()
        assert visible == 1
    async with untenanted_session() as session:
        result = await session.execute(
            text("UPDATE heal_client_incidents SET must_act = true WHERE tenant_id = :t"),
            {"t": tenant_id},
        )
    assert getattr(result, "rowcount", 0) == 0, "an untenanted session wrote a client row"


# --- the ledger and incidents ----------------------------------------------------------------


async def test_the_ledger_refuses_an_update() -> None:
    async with untenanted_session() as session:
        action_id = await ledger.record(
            session, playbook="outbox_replay", step="act", outcome="ok", detail="replayed=1"
        )
    with pytest.raises(DBAPIError):
        async with untenanted_session() as session:
            await session.execute(
                text("UPDATE heal_actions SET outcome = 'failed' WHERE id = :id"),
                {"id": action_id},
            )


async def test_the_ledger_redacts_a_phone_in_its_detail() -> None:
    async with untenanted_session() as session:
        action_id = await ledger.record(
            session,
            playbook="outbox_replay",
            step="act",
            outcome="failed",
            detail="to +919876543210",
        )
        detail = (
            await session.execute(
                text("SELECT detail FROM heal_actions WHERE id = :id"), {"id": action_id}
            )
        ).scalar()
    assert "9876543210" not in str(detail)


async def test_one_open_incident_per_key_and_a_new_one_after_it_resolves() -> None:
    key = incidents.dedupe_key("outbox_replay", "outbox_dead_letter", uuid.uuid4())
    async with untenanted_session() as session:
        first, opened = await incidents.open_incident(
            session,
            key=key,
            playbook="outbox_replay",
            trigger_code="outbox_dead_letter",
            scope="platform",
        )
        again, reopened = await incidents.open_incident(
            session,
            key=key,
            playbook="outbox_replay",
            trigger_code="outbox_dead_letter",
            scope="platform",
        )
        assert opened and not reopened and again == first
        incident = await incidents.read_incident(session, first)
        assert incident is not None
        assert await incidents.advance(session, incident, state="resolved", next_in_s=None)
        # The CAS refuses a second advance from the state it no longer has.
        assert not await incidents.advance(session, incident, state="resolved", next_in_s=None)
        fresh, opened_again = await incidents.open_incident(
            session,
            key=key,
            playbook="outbox_replay",
            trigger_code="outbox_dead_letter",
            scope="platform",
        )
    assert opened_again and fresh != first


# --- the health score from real calls -------------------------------------------------------


async def _call(
    tenant_id: UUID, agent_id: UUID, *, at: datetime, status: str, seconds: int
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, started_at, duration_s, created_at, updated_at) VALUES (:i, :t, :a, "
                ":e, 'inbound', '+919000000072', :s, :at, :d, :at, now())"
            ),
            {
                "i": uuid7(),
                "t": tenant_id,
                "a": agent_id,
                "e": f"heal_{uuid.uuid4().hex[:12]}",
                "s": status,
                "at": at,
                "d": seconds,
            },
        )


async def test_a_line_whose_calls_fail_reads_as_broken() -> None:
    tenant_id, agent_id, _ = await _org("score")
    start = health.window_start(datetime.now(UTC)) - health.WINDOW
    for minute in range(6):
        await _call(
            tenant_id,
            agent_id,
            at=start + timedelta(minutes=minute),
            status="failed" if minute % 2 else "completed",
            seconds=3,
        )
    async with tenant_session(tenant_id) as session:
        counts = await health.count_window(session, start=start)
        mine = [c for c in counts if c.agent_id == agent_id]
        assert len(mine) == 1 and mine[0].calls == 6
        assert mine[0].failed_calls == 3 and mine[0].short_calls == 3
        value, baseline, deviating = await health.record_window(
            session, tenant_id=tenant_id, start=start, counts=mine[0]
        )
        assert value == health.score(mine[0])
        assert baseline is None and deviating is True
        verdict = await health.verdict_for(session, agent_id=agent_id, now=datetime.now(UTC))
    assert verdict.broken is True


async def test_a_trial_call_never_counts() -> None:
    tenant_id, agent_id, _ = await _org("trial")
    start = health.window_start(datetime.now(UTC)) - health.WINDOW
    await _call(tenant_id, agent_id, at=start + timedelta(minutes=1), status="failed", seconds=0)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET trial_call = true WHERE agent_id = :a"), {"a": agent_id}
        )
        assert [
            c for c in await health.count_window(session, start=start) if c.agent_id == agent_id
        ] == []


# --- a line held and given back --------------------------------------------------------------


async def _published(prefix: str) -> tuple[UUID, UUID, str]:
    reset_engine_cache()
    tenant_id, agent_id, slug = await _org(prefix)
    await accept_agreements(tenant_id)
    await fund_wallet(tenant_id)
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Healer Clinic.\n",
            notes=None,
            created_by=None,
        )
        await session.execute(
            text("UPDATE agents SET direction = 'inbound' WHERE id = :a"), {"a": agent_id}
        )
        await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    return tenant_id, agent_id, slug


async def _reason(tenant_id: UUID, agent_id: UUID) -> str | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT inbound_silence_reason FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()


async def _opening(tenant_id: UUID, agent_id: UUID) -> str:
    async with tenant_session(tenant_id) as session:
        ref = (
            await session.execute(
                text("SELECT engine_agent_ref FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar()
    snapshot = await get_engine().get_agent(str(ref))
    return str(snapshot.system_prompt or "")


async def test_a_held_line_survives_a_republish_and_comes_back_on_restore() -> None:
    tenant_id, agent_id, _ = await _published("hold")
    incident_id = await _incident(tenant_id=tenant_id, agent_id=agent_id)
    async with tenant_session(tenant_id) as session:
        held = await protection.protect_agent(
            session, tenant_id=tenant_id, incident_id=incident_id, agent_id=agent_id
        )
    # No engine in the suite can hand a caller over, so even with no fallback phone the
    # hold is the polite unavailable line.
    assert held.hold == "paused"
    assert await _reason(tenant_id, agent_id) == agents_service.INBOUND_SILENCE_HEALER
    assert agents_service.CREDIT_STOP_MESSAGE in await _opening(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        assert await protection.healer_holds_line(session, agent_id=agent_id)
        # A client's republish puts the ordinary script back; the hold must come back with it.
        await agents_service.publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert await _reason(tenant_id, agent_id) == agents_service.INBOUND_SILENCE_HEALER
    assert agents_service.CREDIT_STOP_MESSAGE in await _opening(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        restored = await protection.restore_agent(
            session, tenant_id=tenant_id, incident_id=incident_id, agent_id=agent_id
        )
        state = (
            await session.execute(
                text("SELECT state FROM heal_client_incidents WHERE incident_id = :i"),
                {"i": incident_id},
            )
        ).scalar()
    assert restored.lifted is True
    assert state == "resolved"
    assert await _reason(tenant_id, agent_id) is None
    assert agents_service.CREDIT_STOP_MESSAGE not in await _opening(tenant_id, agent_id)


async def test_the_wallet_does_not_lift_a_healer_hold() -> None:
    tenant_id, agent_id, _ = await _published("wallet")
    incident_id = await _incident(tenant_id=tenant_id, agent_id=agent_id)
    async with tenant_session(tenant_id) as session:
        await protection.protect_agent(
            session, tenant_id=tenant_id, incident_id=incident_id, agent_id=agent_id
        )
        outcome = await agents_service.reconcile_inbound_answering(
            session, get_engine(), tenant_id=tenant_id, exhausted=False
        )
    assert outcome.withheld >= 1
    assert await _reason(tenant_id, agent_id) == agents_service.INBOUND_SILENCE_HEALER


# --- HTTP -----------------------------------------------------------------------------------


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _owner(tenant_id: UUID) -> str:
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
    return f"dev:client:{user_id}"


async def _admin() -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'superadmin', now(), now())"
            ),
            {"id": admin_id},
        )
    return f"dev:admin:{admin_id}"


async def test_the_owner_sets_and_clears_a_fallback_phone() -> None:
    tenant_id, _, slug = await _org("phone")
    headers = {"Authorization": f"Bearer {await _owner(tenant_id)}", "X-Org-Slug": slug}
    async with _client() as client:
        refused = await client.put(
            "/v1/healer/fallback-phone", json={"phone_e164": "+14155550100"}, headers=headers
        )
        assert refused.status_code == 422, refused.text
        saved = await client.put(
            "/v1/healer/fallback-phone", json={"phone_e164": "+919000000073"}, headers=headers
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["phone_e164"] == "+919000000073"
        read = await client.get("/v1/healer/fallback-phone", headers=headers)
        assert read.json()["phone_e164"] == "+919000000073"
        cleared = await client.delete("/v1/healer/fallback-phone", headers=headers)
        assert cleared.json()["phone_e164"] is None
    async with tenant_session(tenant_id) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t AND action LIKE "
                    "'healer.fallback_phone_%'"
                ),
                {"t": tenant_id},
            )
        ).scalar()
    assert audited == 2


async def test_the_client_reads_its_incidents_in_plain_words() -> None:
    tenant_id, agent_id, slug = await _org("words")
    await _seed(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {await _owner(tenant_id)}", "X-Org-Slug": slug}
    async with _client() as client:
        response = await client.get("/v1/healer/incidents", headers=headers)
        proposals_read = await client.get("/v1/healer/proposals", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["open"] == 1
    item = body["items"][0]
    assert item["kind"] == "line_protected" and item["headline"]
    assert "9000000071" not in response.text
    assert proposals_read.json()["pending"] == 1


async def test_the_operator_overview_lists_every_playbook() -> None:
    headers = {"Authorization": f"Bearer {await _admin()}"}
    async with _client() as client:
        overview = await client.get("/v1/ops/healer", headers=headers)
        listed = await client.get("/v1/ops/healer/incidents", headers=headers)
        actions = await client.get("/v1/ops/healer/actions", headers=headers)
    assert overview.status_code == 200, overview.text
    keys = {p["key"] for p in overview.json()["playbooks"]}
    assert {"engine_drift", "outbox_replay", "line_protection", "engine_outage"} <= keys
    assert listed.status_code == 200 and actions.status_code == 200


async def test_resolving_needs_the_step_up_word() -> None:
    incident_id = await _incident()
    headers = {"Authorization": f"Bearer {await _admin()}"}
    async with _client() as client:
        response = await client.post(
            f"/v1/ops/healer/incidents/{incident_id}/resolve", headers=headers
        )
    assert response.status_code in (401, 403), response.text


async def test_the_public_status_page_names_no_client() -> None:
    tenant_id, agent_id, _ = await _org("public")
    async with untenanted_session() as session:
        incident_id, _ = await incidents.open_incident(
            session,
            key=incidents.dedupe_key("status_post", uuid.uuid4()),
            playbook="status_post",
            trigger_code="status_post",
            scope="platform",
            tenant_id=tenant_id,
            agent_id=agent_id,
            component="numbers",
            public_title="Some numbers are slow to connect",
        )
    async with _client() as client:
        response = await client.get("/v1/public/status")
    assert response.status_code == 200, response.text
    assert str(tenant_id) not in response.text and str(agent_id) not in response.text
    components = {c["key"]: c["state"] for c in response.json()["components"]}
    assert components["numbers"] == "degraded"
    assert any(i["id"] == str(incident_id) for i in response.json()["incidents"])
    async with untenanted_session() as session:
        await incidents.set_public(session, incident_id, title=None, component=None)
        page = await status.status_page(session)
    assert all(i.id != str(incident_id) for i in page.incidents)


def _unused(_: Any) -> None:  # pragma: no cover - keeps the import list honest for mypy
    return None
