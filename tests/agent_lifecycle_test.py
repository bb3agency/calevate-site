"""An agent has a life: created, activated, deactivated, archived, restored (D-440).

WHAT IS UNDER TEST, and they are four different claims:

1. **Creation cannot route around the compliance floor.** A newly created agent has both
   notices on file, both switched on, a composed opening line and no script — so it
   exists, discloses, and cannot be put on a phone until somebody writes what it says.
2. **The four states are a machine, not a column.** Every legal edge moves, every illegal
   one is a 409 naming what it found, and re-asserting a state the agent already holds is
   a success that writes no ledger entry (RFC 9110 §9.2.2).
3. **"Off" reaches the vendor.** Outbound stops by itself — `check_dispatch` refuses a
   non-live agent per contact — but inbound is answered by whatever the engine has bound
   to the number, so deactivate and archive have to release those bindings or "paused"
   would mean "stops calling out, still picks up".
4. **Archived is never dialled and never assignable, and is NOT a delete.** The agent, its
   calls and its history stay readable; publishing it is refused, the dial gate refuses
   it, a campaign cannot be created against it and the launch gate names it separately
   from "not published yet".

Cross-tenant isolation is asserted on the whole new surface rather than on one route: an
agent id from a neighbouring tenant must be a 404 on every one of them (hard rule 1).
"""

from __future__ import annotations

import asyncio
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle, prompts
from apps.api.agents.routes import router as agents_router
from apps.api.agents.service import publish_agent
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.service import check_dispatch
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.core.rbac import assert_policy_registry_complete
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import get_engine, reset_engine_cache
from apps.api.engine.fake import FakeEngine
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import accept_agreements

# `asyncio_mode = "auto"` already runs the coroutines here; the marker this file needs
# is the tenancy one, so `-m rls` picks up the cross-tenant case below with the rest
# of the isolation suite.
pytestmark = [pytest.mark.rls]


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(agents_router)
    # The boot assertion over the assembled app: a new route that forgets its
    # `permission_meta` fails here rather than silently in production with an open door.
    assert_policy_registry_complete(application)
    return application


def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant(role: str = "owner") -> tuple[uuid.UUID, uuid.UUID, str]:
    """(tenant_id, seeded receptionist id, client dev bearer) for a fresh org."""
    created = await admin_service.create_organization(
        name="Lifecycle Clinic",
        slug=f"life-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    # The four agreements, accepted (migration a9d4e70c31b8) — supplied, never assumed
    # away, in the shape `arm_agent_for_outbound` established. Every dial, launch and
    # publish gate now refuses an organisation that has not accepted them, so a fixture
    # without this reports `agreements_not_accepted` in place of the answer under test.
    await accept_agreements(uuid.UUID(str(created["id"])))
    tenant_id = uuid.UUID(str(created["id"]))
    agent_id = uuid.UUID(str(created["agent_id"]))
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
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return tenant_id, agent_id, f"dev:client:{user_id}"


async def _write_script(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """A script, because activation without one is refused by name."""
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body="[IDENTITY]\nYou are the receptionist for Lifecycle Clinic.\n",
            notes=None,
            created_by=None,
        )


async def _number(tenant_id: uuid.UUID, agent_id: uuid.UUID, ref: str) -> uuid.UUID:
    """A provisioned number BOUND to the agent, with the engine-side handle set.

    Written directly rather than through `provision_number` because `engine_number_ref` is
    the telephony vendor's own onboarding output and a fixture that could only produce the
    freshly-provisioned state could not set up the release assertions below.
    """
    number_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO phone_numbers (id, tenant_id, agent_id, e164, series, "
                "dlt_status, engine_number_ref, created_at, updated_at) "
                "VALUES (:id, :tid, :aid, :e, '160', 'registered', :ref, now(), now())"
            ),
            {
                "id": number_id,
                "tid": tenant_id,
                "aid": agent_id,
                "e": f"+91160{uuid.uuid4().int % 10_000_000:07d}",
                "ref": ref,
            },
        )
    return number_id


async def _status(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> tuple[str, Any]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, archived_at FROM agents WHERE id = :aid"), {"aid": agent_id}
            )
        ).first()
    assert row is not None
    return str(row[0]), row[1]


def _fresh_engine() -> FakeEngine:
    reset_engine_cache()
    engine = get_engine()
    assert isinstance(engine, FakeEngine)
    return engine


def _code(body: dict[str, Any]) -> str:
    """The stable machine identifier a client switches on.

    It rides in `type` as the last path segment (`core/errors.ProblemError.as_problem`),
    not in a `code` field — read it that way here rather than teaching every assertion the
    URL shape.
    """
    return str(body["type"]).rsplit("/", 1)[-1]


async def _move(token: str, agent_id: uuid.UUID, verb: str) -> tuple[int, dict[str, Any]]:
    async with _client(_app()) as http:
        response = await http.post(
            f"/v1/agents/{agent_id}/{verb}", headers={"Authorization": f"Bearer {token}"}
        )
    body: dict[str, Any] = response.json()
    return response.status_code, body


# --- 1. creation and the compliance floor -------------------------------------------


async def test_a_created_agent_is_a_draft_that_already_discloses() -> None:
    """The floor is satisfied AT CREATION, not at publish (hard rule 5).

    Both sentences exist and are non-blank, both toggles are on, the opening line is
    composed server-side from them — and the agent is a `draft` carrying no script, which
    is what makes the refusal in the next test the honest answer rather than a placeholder
    on a clinic's phone line.
    """
    tenant_id, _, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.post(
            "/v1/agents",
            json={"name": "  After-hours line  ", "direction": "both", "language_primary": "te-IN"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["name"] == "After-hours line", "a blank-padded name was stored unstripped"
    assert body["direction"] == "both"
    assert body["archived_at"] is None
    assert body["published"] is False
    assert body["inbound_number_count"] == 0
    assert body["ai_disclosure_line"].strip(), "an agent was created with no AI sentence on file"
    assert body["recording_notice_line"].strip()
    assert body["ai_disclosure_enabled"] is True
    assert body["recording_notice_enabled"] is True
    assert body["ai_disclosure_line"] in body["opening_line"]
    assert "Lifecycle Clinic" in body["ai_disclosure_line"], (
        "the AI sentence names a business other than the one that owns the agent"
    )

    # The wire is not the only place the floor has to hold: the column is what the dial
    # gate and the publish path read.
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT ai_disclosure_line, recording_notice_line, disclosure_line, "
                    "status, engine, system_prompt_id FROM agents WHERE id = :aid"
                ),
                {"aid": uuid.UUID(body["id"])},
            )
        ).first()
    assert row is not None
    assert row[0].strip() and row[1].strip() and row[2].strip()
    assert row[3] == "draft"
    assert row[5] is None, "a created agent came with a script nobody wrote"


async def test_a_blank_name_is_refused() -> None:
    tenant_id, _, token = await _tenant()
    del tenant_id
    async with _client(_app()) as http:
        response = await http.post(
            "/v1/agents",
            json={"name": "   ", "direction": "inbound"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 422, response.text


async def test_a_created_agent_cannot_be_activated_until_it_has_a_script() -> None:
    """Creation is not a route around `_assert_has_a_script`.

    The refusal names the missing step. The alternative — activating it and publishing a
    hardcoded placeholder — is the defect that function exists to have removed.
    """
    _fresh_engine()
    tenant_id, _, token = await _tenant()
    async with _client(_app()) as http:
        created = await http.post(
            "/v1/agents",
            json={"name": "Silent", "direction": "inbound"},
            headers={"Authorization": f"Bearer {token}"},
        )
    agent_id = uuid.UUID(created.json()["id"])

    code, body = await _move(token, agent_id, "activate")
    assert code == 422, body
    assert _code(body) == "agent_has_no_script", body
    assert (await _status(tenant_id, agent_id))[0] == "draft", (
        "a refused activation left the agent claiming to be live"
    )


# --- 2. the state machine ------------------------------------------------------------


async def test_the_agent_walks_its_whole_life_and_the_engine_follows() -> None:
    """draft -> live -> paused -> live -> archived -> paused, with the numbers.

    ONE TEST FOR THE WHOLE WALK rather than six, because the claim is about the SEQUENCE:
    every state has to be reachable from the one before it and the engine's inbound
    bindings have to track it at each step. Six independent tests would each rebuild the
    state before them and none would assert the path.
    """
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await _number(tenant_id, agent_id, ref="num_life_1")

    code, body = await _move(token, agent_id, "activate")
    assert code == 200, body
    assert (body["status"], body["changed"]) == ("live", True)
    assert engine.inbound_agent_for("num_life_1") is not None, (
        "an activated agent is not answering the number bound to it"
    )

    # Idempotent: the intent already holds, nothing is republished.
    code, body = await _move(token, agent_id, "activate")
    assert (code, body["status"], body["changed"]) == (200, "live", False)

    code, body = await _move(token, agent_id, "deactivate")
    assert code == 200, body
    assert (body["status"], body["changed"], body["numbers_released"]) == ("paused", True, 1)
    assert engine.inbound_agent_for("num_life_1") is None, (
        "a deactivated agent is still answering its number at the voice platform"
    )
    assert (await _status(tenant_id, agent_id))[0] == "paused"

    code, body = await _move(token, agent_id, "deactivate")
    assert (code, body["changed"]) == (200, False), "a second click was reported as a conflict"

    code, body = await _move(token, agent_id, "activate")
    assert (code, body["status"], body["changed"]) == (200, "live", True)
    assert engine.inbound_agent_for("num_life_1") is not None, (
        "reactivating did not put the agent back on its number"
    )

    code, body = await _move(token, agent_id, "archive")
    assert code == 200, body
    assert (body["status"], body["changed"], body["numbers_released"]) == ("archived", True, 1)
    assert engine.inbound_agent_for("num_life_1") is None
    status, archived_at = await _status(tenant_id, agent_id)
    assert status == "archived"
    assert archived_at is not None, "archived with no archival timestamp"

    code, body = await _move(token, agent_id, "restore")
    assert code == 200, body
    assert (body["status"], body["changed"]) == ("paused", True), (
        "a restore put the agent straight back on the phone without a publish"
    )
    status, archived_at = await _status(tenant_id, agent_id)
    assert (status, archived_at) == ("paused", None)


async def test_the_illegal_edges_are_conflicts_that_name_what_they_found() -> None:
    """Three moves the table does not admit, each refused with its own answer."""
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()

    # draft -> paused: there is nothing live to switch off.
    code, body = await _move(token, agent_id, "deactivate")
    assert code == 409, body
    assert _code(body) == "invalid_status_transition", body
    assert "draft" in body["detail"], "the conflict did not name the state it found"

    # archived -> live: only a restore comes out of the archive.
    await _write_script(tenant_id, agent_id)
    assert (await _move(token, agent_id, "archive"))[0] == 200
    code, body = await _move(token, agent_id, "activate")
    assert code == 409, body
    assert _code(body) == "agent_archived", body

    # An id nobody minted is a 404 on a transition, never a 409.
    code, body = await _move(token, uuid7(), "deactivate")
    assert code == 404, body


async def test_restore_refuses_a_live_agent_rather_than_switching_it_off_behind_the_owner() -> None:
    """`restore` is `archived -> paused` ONLY, and this is the edge that proves it.

    THE DEFECT THIS PINS. `restore` and `deactivate` both END at `paused`, so a mover that
    derives its accepted sources from the TARGET accepts every in-edge of `paused` —
    including `live -> paused`, which belongs to `deactivate`. Pressing Restore on a LIVE
    agent then wrote `status = 'paused'` and returned 200, while `restore` releases no
    numbers: our record said the agent was switched off and the voice platform went on
    answering every line bound to it. That is the exact lie D-420 exists for, produced by
    the button whose whole job is to be reversible and safe.

    So the assertion is on BOTH halves — the refusal AND the phone.
    """
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await _number(tenant_id, agent_id, ref="num_restore_live")
    assert (await _move(token, agent_id, "activate"))[0] == 200
    assert engine.inbound_agent_for("num_restore_live") is not None

    code, body = await _move(token, agent_id, "restore")
    assert code == 409, body
    assert _code(body) == "agent_not_archived", body
    assert "live" in body["detail"], "the conflict did not name the state it found"
    assert "Deactivate" in body["remediation"], (
        "the refusal did not say which button actually switches a live agent off"
    )
    assert (await _status(tenant_id, agent_id))[0] == "live", "restore switched a live agent off"
    assert engine.inbound_agent_for("num_restore_live") is not None, (
        "restore took a live agent off its number without anyone asking it to"
    )


async def test_deactivate_refuses_an_archived_agent_by_name_not_with_a_constraint() -> None:
    """`deactivate` is `live -> paused` ONLY, and an archived agent is refused, not raised at.

    The same shared derivation gave `deactivate` the `archived -> paused` edge that belongs
    to `restore`, which is a back door out of the archive that writes the wrong audit
    action — and, because `deactivate` does not clear `archived_at`, one that lands on
    `ck_agents_archived_at_matches_status` and surfaces as an IntegrityError nobody
    authored instead of a refusal a client can read.
    """
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    assert (await _move(token, agent_id, "archive"))[0] == 200

    code, body = await _move(token, agent_id, "deactivate")
    assert code == 409, body
    assert _code(body) in ("agent_archived", "invalid_status_transition"), body
    status, archived_at = await _status(tenant_id, agent_id)
    assert status == "archived", "deactivate let an agent out of the archive"
    assert archived_at is not None


async def test_an_archived_agent_cannot_be_edited_or_republished() -> None:
    """The two ways back onto a phone line that do not go through `activate`.

    `publish_agent` has seven callers and five of them guard themselves with their own
    "is this agent live?" read. The guard is on the publish itself so that the rule is a
    property of the write rather than something six call sites have to remember.
    """
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    assert (await _move(token, agent_id, "archive"))[0] == 200

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
    assert raised.value.code == "agent_archived"
    assert (await _status(tenant_id, agent_id))[0] == "archived"

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}",
            json={"name": "Renamed while retired"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 409, response.text
    assert _code(response.json()) == "agent_archived"


async def test_editing_a_live_agent_republishes_it() -> None:
    """Name, direction and language all ride on `AgentConfig`, so the engine must hear it.

    The direction half is the one that rings a phone: switching a two-way agent to
    outbound-only has to make the engine stop answering its numbers, not just make our
    screens stop saying it does.
    """
    engine = _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await _number(tenant_id, agent_id, ref="num_edit_1")
    assert (await _move(token, agent_id, "activate"))[0] == 200
    assert engine.inbound_agent_for("num_edit_1") is not None

    async with _client(_app()) as http:
        response = await http.patch(
            f"/v1/agents/{agent_id}",
            json={"name": "Outbound only", "direction": "outbound"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200, response.text
    assert response.json()["direction"] == "outbound"
    assert engine.inbound_agent_for("num_edit_1") is None, (
        "an agent switched to outbound-only is still answering an inbound line"
    )
    snapshot = await engine.get_agent(
        str(
            await _fetch(tenant_id, "SELECT engine_agent_ref FROM agents WHERE id = :aid", agent_id)
        )
    )
    assert snapshot.name == "Outbound only", "the rename never reached the voice platform"


async def _fetch(tenant_id: uuid.UUID, sql: str, agent_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text(sql), {"aid": agent_id})).scalar()


# --- 3. archived is never dialled and never assignable -------------------------------


async def test_the_dial_gate_refuses_an_archived_agent() -> None:
    """No new rule: `check_dispatch` already refuses `status <> 'live'` per contact, which
    is what makes an archive stop a RUNNING campaign on the very next tick."""
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    assert (await _move(token, agent_id, "archive"))[0] == 200

    async with tenant_session(tenant_id) as session:
        decision = await check_dispatch(
            session, tenant_id=tenant_id, agent_id=agent_id, phone_e164="+919000000001"
        )
    assert decision.allowed is False
    assert decision.rule == "agent_not_live"


async def test_a_campaign_cannot_be_created_against_an_archived_agent() -> None:
    """409, and separately from the 404 a neighbour's id gets — the lifecycle question and
    the tenancy question have different answers and different next actions."""
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    assert (await _move(token, agent_id, "archive"))[0] == 200

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await campaigns_service.create_campaign(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Reminders",
                classification="service",
                number_id=None,
                dlt_template_id=None,
                concurrency=1,
            )
    assert raised.value.code == "agent_archived"


async def test_the_launch_gate_names_an_archived_agent_separately() -> None:
    """`agent_not_live` tells the client to publish it. An archived agent cannot BE
    published, so answering with that rule is a dead end with a green button at the end."""
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Reminders",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
    assert (await _move(token, agent_id, "archive"))[0] == 200
    async with tenant_session(tenant_id) as session:
        rules = {
            blocker.rule
            for blocker in await campaigns_service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
        }
    assert "agent_archived" in rules, rules
    assert "agent_not_live" not in rules, (
        "the gate told the client to publish an agent the platform refuses to publish"
    )


async def test_an_archive_racing_a_campaign_launch_cannot_produce_a_running_zombie() -> None:
    """TWO REAL TRANSACTIONS, INTERLEAVED — the race `_assert_no_campaign_is_dialling` lost.

    Both halves of that check used to be READS. Archive counted running and scheduled
    campaigns; launch read `agents.status` through `launch_blockers`. Under READ COMMITTED
    two such transactions interleave cleanly and commit a pair neither would have allowed
    on its own: `agent='archived'` with `campaign='running'`, after which the dispatcher
    refuses every contact for ever behind a screen that says "running".

    THE INTERLEAVING IS DRIVEN, NOT HOPED FOR. The launcher opens its transaction and
    reaches its gate, then signals; the archiver runs to completion; only then does the
    launcher write. That is the exact order that produced the zombie.

    WHY THE WAIT HAS A TIMEOUT AND IS NOT AN ERROR. With the fix in place the archiver
    BLOCKS on the share lock the launcher is holding, so `archive_done` is never set and
    the wait must expire for the test to finish at all — that expiry IS the lock working.
    Without the fix the archiver commits immediately and the wait returns at once. Either
    way both transactions finish and the assertion is on the pair of rows they left, which
    is the only thing that distinguishes the two worlds.
    """
    _fresh_engine()
    tenant_id, agent_id, _token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await publish_agent_in_its_own_session(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Race",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )

    gate_read = asyncio.Event()
    archive_done = asyncio.Event()

    async def launcher() -> None:
        async with tenant_session(tenant_id) as session:
            # Force the transaction open before anything is signalled, so the archiver
            # cannot slip in ahead of the snapshot this launch is reasoning from.
            await session.execute(text("SELECT 1"))
            await campaigns_service.hold_agent_for_campaign_start(session, agent_id)
            # The gate read the launch acts on. Unlocked before the fix, and the whole
            # point: what it sees is what the CAS below trusts.
            await campaigns_service.launch_blockers(
                session, tenant_id=tenant_id, campaign_id=campaign_id
            )
            gate_read.set()
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(archive_done.wait(), timeout=3.0)
            await session.execute(
                text(
                    "UPDATE campaigns SET status = 'running', launched_at = now(), "
                    "updated_at = now() WHERE id = :cid AND status IN ('draft', 'scheduled')"
                ),
                {"cid": campaign_id},
            )

    async def archiver() -> None:
        await gate_read.wait()
        async with tenant_session(tenant_id) as session:
            with contextlib.suppress(ProblemError):
                await lifecycle.archive_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        archive_done.set()

    await asyncio.gather(launcher(), archiver())

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT a.status, c.status FROM agents a JOIN campaigns c "
                    "ON c.agent_id = a.id WHERE a.id = :aid AND c.id = :cid"
                ),
                {"aid": agent_id, "cid": campaign_id},
            )
        ).first()
    assert row is not None
    outcome = (str(row[0]), str(row[1]))
    print(f"OUTCOME agent={outcome[0]!r} campaign={outcome[1]!r}")
    assert outcome != ("archived", "running"), (
        "an archived agent with a running campaign is the zombie "
        "_assert_no_campaign_is_dialling exists to prevent"
    )
    # And the two consistent endings are the only ones left: either the launch won and the
    # archive was refused by name, or the archive won and the launch never moved the row.
    assert outcome in (("live", "running"), ("archived", "draft")), outcome


async def test_the_three_agent_writers_contend_without_deadlocking() -> None:
    """Archive, campaign launch and `update_agent` racing on one agent, repeatedly.

    THE RISK THE LOCKS INTRODUCE, asserted rather than reasoned about. `archive_agent` now
    takes `FOR UPDATE`, the two campaign-start paths take `FOR SHARE`, and `update_agent`
    already held `FOR UPDATE` across a read, a write and a republish. Three writers on one
    row is where a lock-ordering mistake becomes a 40P01 in production, and a deadlock here
    would be worse than the race the locks were added to close.

    THE ORDER THAT MAKES IT SAFE is that all three take `agents` FIRST and only then reach
    `campaigns` (launch), `phone_numbers` (archive) or the engine (`update_agent`) — so
    there is no cycle to close. This drives them together to say so on data.

    Every round must end in one of the two consistent pairs, whichever writer won: the
    reverse order of the interleaving above is included by construction, because nothing
    here sequences them.
    """
    _fresh_engine()
    tenant_id, agent_id, _token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await publish_agent_in_its_own_session(tenant_id, agent_id)

    outcomes: list[tuple[str, str]] = []
    for round_number in range(6):
        async with tenant_session(tenant_id) as session:
            # A fresh draft campaign each round, and the agent put back on the frontline,
            # so every round starts from the state the race actually begins in.
            await session.execute(
                text("UPDATE agents SET status = 'live', archived_at = NULL WHERE id = :aid"),
                {"aid": agent_id},
            )
            campaign_id = await campaigns_service.create_campaign(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name=f"Contend {round_number}",
                classification="service",
                number_id=None,
                dlt_template_id=None,
                concurrency=1,
                consent_source="existing_customer",
                consent_collected_at=datetime.now(UTC) - timedelta(days=7),
            )

        start = asyncio.Barrier(3)

        async def archive(start: asyncio.Barrier = start) -> None:
            await start.wait()
            async with tenant_session(tenant_id) as session:
                with contextlib.suppress(ProblemError):
                    await lifecycle.archive_agent(session, tenant_id=tenant_id, agent_id=agent_id)

        async def launch(
            campaign_id: uuid.UUID = campaign_id, start: asyncio.Barrier = start
        ) -> None:
            await start.wait()
            async with tenant_session(tenant_id) as session:
                with contextlib.suppress(ProblemError):
                    await campaigns_service.launch_campaign(
                        session, tenant_id=tenant_id, campaign_id=campaign_id
                    )

        async def rename(round_number: int = round_number, start: asyncio.Barrier = start) -> None:
            await start.wait()
            async with tenant_session(tenant_id) as session:
                with contextlib.suppress(ProblemError):
                    await lifecycle.update_agent(
                        session,
                        tenant_id=tenant_id,
                        agent_id=agent_id,
                        name=f"Contended {round_number}",
                    )

        # No `suppress` around the gather: a deadlock surfaces as a DBAPIError out of one
        # of these, and this test exists to let it through rather than swallow it. Only
        # the domain refusals above are caught, and each is a ProblemError by name.
        await asyncio.gather(archive(), launch(), rename())

        async with tenant_session(tenant_id) as session:
            row = (
                await session.execute(
                    text(
                        "SELECT a.status, c.status FROM agents a JOIN campaigns c "
                        "ON c.agent_id = a.id WHERE a.id = :aid AND c.id = :cid"
                    ),
                    {"aid": agent_id, "cid": campaign_id},
                )
            ).first()
        assert row is not None
        outcomes.append((str(row[0]), str(row[1])))

    print(f"OUTCOMES {outcomes}")
    zombies = [pair for pair in outcomes if pair == ("archived", "running")]
    assert not zombies, f"archived agent with a running campaign in {len(zombies)} of 6 rounds"
    for pair in outcomes:
        assert pair in (("live", "running"), ("archived", "draft"), ("live", "draft")), pair


async def publish_agent_in_its_own_session(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """`live`, committed, so the race starts from the state a real launch starts from."""
    async with tenant_session(tenant_id) as session:
        await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def test_a_paused_campaign_cannot_be_resumed_behind_an_archived_agent() -> None:
    """THE OTHER DOOR into the state `archive_agent` refuses to manufacture (D-440).

    Archiving refuses while a RUNNING or SCHEDULED campaign is dialling through the agent,
    so the zombie it describes — a campaign that says "running" and is refused contact by
    contact for ever, with nothing on the screen to say why — cannot be made from that
    side. It could be made from this one: pause the campaign, archive the agent, press
    Resume, which is a bare CAS with no gate on it by design.

    Asserted on the campaign's STORED STATUS, not on the response alone: the claim is that
    the row did not move, and a 409 with a `running` row would be the worse half of the
    same bug.
    """
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Reminders",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
            consent_source="existing_customer",
            consent_collected_at=datetime.now(UTC) - timedelta(days=7),
        )
        # Straight to `paused`: the campaign is not dialling, which is exactly the state
        # `_assert_no_campaign_is_dialling` lets an archive through.
        await session.execute(
            text("UPDATE campaigns SET status = 'paused' WHERE id = :cid"), {"cid": campaign_id}
        )
    assert (await _move(token, agent_id, "archive"))[0] == 200

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await campaigns_service.assert_agent_still_assignable(session, campaign_id=campaign_id)
    assert raised.value.code == "agent_archived"

    # The campaigns router, because the refusal has to be the one a client actually meets
    # — the service assertion above proves the rule, this proves it is wired to the button.
    from apps.api.campaigns.routes import router as campaigns_router

    application = FastAPI()
    install_error_handlers(application)
    application.include_router(campaigns_router)
    assert_policy_registry_complete(application)
    async with _client(application) as http:
        response = await http.post(
            f"/v1/campaigns/{campaign_id}/resume",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 409, response.text
    assert _code(response.json()) == "agent_archived", response.text

    async with tenant_session(tenant_id) as session:
        status = (
            await session.execute(
                text("SELECT status FROM campaigns WHERE id = :cid"), {"cid": campaign_id}
            )
        ).scalar()
    assert str(status) == "paused", "resume put a campaign back on the road behind a retired agent"


async def test_an_agent_a_campaign_is_still_dialling_cannot_be_archived() -> None:
    """The zombie campaign, refused at the only place that can see it coming.

    The dispatcher refuses a non-live agent CONTACT BY CONTACT, so archiving mid-campaign
    would leave a campaign that says `running`, claims a batch every tick, is refused, and
    calls nobody — for ever, with nothing on the client's screen to explain it.

    `deactivate` is deliberately still allowed in the same state: it is the emergency
    brake, and an incident is the worst moment to be told to go and tidy up a campaign.
    """
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    assert (await _move(token, agent_id, "activate"))[0] == 200

    async with tenant_session(tenant_id) as session:
        campaign_id = await campaigns_service.create_campaign(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Reminders",
            classification="service",
            number_id=None,
            dlt_template_id=None,
            concurrency=1,
        )
        # Straight to `running` by SQL: this test is about what archiving refuses, and
        # driving the real launch would couple it to the whole §3 launch gate.
        await session.execute(
            text("UPDATE campaigns SET status = 'running' WHERE id = :cid"),
            {"cid": campaign_id},
        )

    code, body = await _move(token, agent_id, "archive")
    assert code == 409, body
    assert _code(body) == "agent_has_active_campaigns", body
    assert (await _status(tenant_id, agent_id))[0] == "live"

    # The emergency brake still works, and it is what the refusal points the client at.
    assert (await _move(token, agent_id, "deactivate"))[0] == 200
    assert (await _status(tenant_id, agent_id))[0] == "paused"


async def test_archiving_is_not_a_delete() -> None:
    """The row, its script and its calls all stay readable — that is the whole point."""
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                "status, started_at, ended_at, outcome_tag, created_at, updated_at) VALUES "
                "(:id, :tid, :aid, :eid, 'inbound', 'completed', now(), now(), 'resolved', "
                "now(), now())"
            ),
            {"id": call_id, "tid": tenant_id, "aid": agent_id, "eid": f"eng_{call_id}"},
        )
    assert (await _move(token, agent_id, "archive"))[0] == 200

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT deleted_at, system_prompt_id FROM agents WHERE id = :aid"),
                {"aid": agent_id},
            )
        ).first()
        calls = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE agent_id = :aid"), {"aid": agent_id}
            )
        ).scalar()
    assert row is not None
    assert row[0] is None, "archiving wrote the erasure column"
    assert row[1] is not None, "archiving discarded the agent's script"
    assert calls == 1, "archiving took the agent's call history with it"


async def test_a_number_assigned_to_a_switched_off_agent_does_not_start_ringing_it(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`engine_agent_ref` survives a deactivation, so "has a ref" stopped being the same
    question as "should answer this number" (D-440).

    `provision_number` routes a newly-assigned number to the engine the moment the agent is
    published — which is right, and would have quietly put a paused or retired agent back
    on a client's line if it kept asking only whether a ref existed.

    Asserted on the ROUTING LOG rather than on the engine's binding table, because the
    claim is that the engine is not reached AT ALL: a freshly provisioned number carries no
    `engine_number_ref` yet, so an attempt would surface as a per-number alarm rather than
    as a binding, and asserting the absence of a binding would pass for the wrong reason.
    """
    from apps.api.agents import service as agents_service

    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    assert (await _move(token, agent_id, "activate"))[0] == 200
    assert (await _move(token, agent_id, "deactivate"))[0] == 200

    with caplog.at_level("INFO"):
        async with tenant_session(tenant_id) as session:
            await agents_service.provision_number(
                session,
                tenant_id=tenant_id,
                e164=f"+91160{uuid.uuid4().int % 10_000_000:07d}",
                series="160",
                agent_id=agent_id,
                provider=None,
                purpose=None,
            )
    reached = [r.message for r in caplog.records if "inbound" in r.message]
    assert reached == [], f"a paused agent was routed onto a newly assigned number: {reached}"


# --- 4. the reads the UI is built on -------------------------------------------------


async def test_the_roster_hides_the_archive_until_it_is_asked_for() -> None:
    _fresh_engine()
    tenant_id, seeded, token = await _tenant()
    await _write_script(tenant_id, seeded)
    async with _client(_app()) as http:
        second = await http.post(
            "/v1/agents",
            json={"name": "Retired line", "direction": "inbound"},
            headers={"Authorization": f"Bearer {token}"},
        )
    retired = uuid.UUID(second.json()["id"])
    assert (await _move(token, retired, "archive"))[0] == 200

    async with _client(_app()) as http:
        headers = {"Authorization": f"Bearer {token}"}
        default = await http.get("/v1/agents", headers=headers)
        archived = await http.get("/v1/agents", params={"status": "archived"}, headers=headers)
        drafts = await http.get("/v1/agents", params={"status": "draft"}, headers=headers)

    assert {a["id"] for a in default.json()} == {str(seeded)}, (
        "the working roster is carrying the archive, which grows without limit"
    )
    assert [a["id"] for a in archived.json()] == [str(retired)]
    assert archived.json()[0]["archived_at"] is not None
    assert {a["id"] for a in drafts.json()} == {str(seeded)}


async def test_the_stats_route_counts_calls_outcomes_and_last_active() -> None:
    """One row per agent, archived ones included — the opposite default to the roster, for
    the opposite reason: this answers "what has happened", and a retired agent's history is
    the largest part of it."""
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    latest = datetime.now(UTC) - timedelta(minutes=5)
    async with tenant_session(tenant_id) as session:
        for index, (direction, status, tag, ended) in enumerate(
            [
                ("inbound", "completed", "resolved", latest - timedelta(hours=2)),
                ("inbound", "completed", "needs_follow_up", latest),
                ("outbound", "no_answer", None, latest - timedelta(hours=3)),
            ]
        ):
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, started_at, ended_at, outcome_tag, created_at, updated_at) "
                    "VALUES (:id, :tid, :aid, :eid, :dir, :st, :ended, :ended, :tag, now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant_id,
                    "aid": agent_id,
                    "eid": f"eng_stats_{uuid.uuid4()}_{index}",
                    "dir": direction,
                    "st": status,
                    "ended": ended,
                    "tag": tag,
                },
            )

    async with _client(_app()) as http:
        response = await http.get("/v1/agents/stats", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200, response.text
    rows = {row["agent_id"]: row for row in response.json()}
    stats = rows[str(agent_id)]
    assert stats["calls_total"] == 3
    assert stats["calls_inbound"] == 2
    assert stats["calls_outbound"] == 1
    assert stats["calls_connected"] == 2
    assert stats["outcomes"] == {
        "resolved": 1,
        "needs_follow_up": 1,
        "transferred": 0,
        "dropped": 0,
    }, "an outcome key was missing, so a screen indexing it would throw"
    assert stats["last_call_at"] is not None
    assert stats["last_call_at"].startswith(latest.strftime("%Y-%m-%dT%H:%M"))


async def test_an_agent_that_never_took_a_call_is_a_row_of_zeroes() -> None:
    """LEFT JOINed from `agents`, so "no calls" is an answer rather than a gap."""
    _fresh_engine()
    _, agent_id, token = await _tenant()
    async with _client(_app()) as http:
        response = await http.get("/v1/agents/stats", headers={"Authorization": f"Bearer {token}"})
    stats = {row["agent_id"]: row for row in response.json()}[str(agent_id)]
    assert stats["calls_total"] == 0
    assert stats["last_call_at"] is None
    assert stats["outcomes"] == {
        "resolved": 0,
        "needs_follow_up": 0,
        "transferred": 0,
        "dropped": 0,
    }


async def test_the_roster_counts_the_lines_an_agent_answers() -> None:
    """The honest per-agent parallelism fact — how many numbers ring it — and deliberately
    the only one: outbound concurrency is an account-level pool, not an agent property."""
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _number(tenant_id, agent_id, ref="num_par_1")
    await _number(tenant_id, agent_id, ref="num_par_2")

    async with _client(_app()) as http:
        response = await http.get(
            f"/v1/agents/{agent_id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.json()["inbound_number_count"] == 2


async def test_both_disclosure_toggles_survive_the_whole_lifecycle_and_stay_independent() -> None:
    """D-163's two switches, across D-440's four states, on the response the console reads.

    The console renders `AgentOut.ai_disclosure_enabled` / `recording_notice_enabled` as two
    switches and quotes `AgentOut.opening_line` back as the actual first utterance. So the
    claim under test is end to end and in one direction only: what the server HONOURS is
    what the screen SHOWS, at every state of the agent's life.

    ARCHIVED IS THE STATE WORTH ASSERTING. A retired agent's row is the record of what it
    used to say — the thing somebody reads when a call from six months ago is questioned —
    and a roster that dropped the posture, or an `opening_line` composed from a stale half,
    would make that record wrong exactly where it matters. The composition is the server's
    single composer either way; this pins that it stays applied to a retired row.
    """
    _fresh_engine()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer {token}"}

    async def read() -> dict[str, Any]:
        async with _client(_app()) as http:
            response = await http.get(f"/v1/agents/{agent_id}", headers=headers)
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    async def flip(payload: dict[str, bool]) -> dict[str, Any]:
        async with _client(_app()) as http:
            response = await http.patch(
                f"/v1/agents/{agent_id}/disclosure", json=payload, headers=headers
            )
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    born = await read()
    assert (born["ai_disclosure_enabled"], born["recording_notice_enabled"]) == (True, True)
    assert born["ai_disclosure_line"] in born["opening_line"]
    assert born["recording_notice_line"] in born["opening_line"]

    # ONE FIELD AT A TIME is what the screen sends — `null` means "leave alone" — so the
    # untouched half must not move. A PATCH that could only send both would make the two
    # switches a read-modify-write race against each other.
    after_recording_off = await flip({"recording_notice_enabled": False})
    assert after_recording_off["ai_disclosure_enabled"] is True
    assert after_recording_off["recording_notice_enabled"] is False
    read_back = await read()
    assert read_back["ai_disclosure_line"] in read_back["opening_line"]
    assert read_back["recording_notice_line"] not in read_back["opening_line"], (
        "the console would quote a notice the server has switched off"
    )

    assert (await _move(token, agent_id, "activate"))[0] == 200
    live = await read()
    assert (live["ai_disclosure_enabled"], live["recording_notice_enabled"]) == (True, False)

    # BOTH OFF IS A LEGAL POSTURE and the one where the screen must not fall back to the
    # legacy bundle: `disclosure_line` still holds both sentences joined (step 1 of the
    # two-step), so an empty `opening_line` beside a populated bundle is the shape a
    # careless renderer gets wrong.
    both_off = await flip({"ai_disclosure_enabled": False})
    assert both_off["opening_line"] == ""
    quiet = await read()
    assert quiet["opening_line"] == ""
    assert quiet["disclosure_line"].strip(), "the legacy bundle was blanked by a toggle"
    assert quiet["ai_disclosure_line"].strip(), "the AI sentence itself was withdrawn"
    assert quiet["truthful_answer_rule"].strip(), "the one rule no toggle reaches went missing"

    for verb in ("deactivate", "archive", "restore"):
        assert (await _move(token, agent_id, verb))[0] == 200, verb
        state = await read()
        assert (state["ai_disclosure_enabled"], state["recording_notice_enabled"]) == (
            False,
            False,
        ), f"the posture moved on {verb}"
        assert state["ai_disclosure_line"].strip() and state["recording_notice_line"].strip(), (
            f"{verb} left the agent without both sentences on file (hard rule 5)"
        )

    # And back on again from the archive-and-restore, one at a time, so the round trip is
    # proven reversible rather than merely survived.
    restored = await flip({"ai_disclosure_enabled": True, "recording_notice_enabled": True})
    assert restored["opening_line"].strip()
    final = await read()
    assert (final["ai_disclosure_enabled"], final["recording_notice_enabled"]) == (True, True)
    assert final["status"] == "paused"


async def test_an_archive_landing_mid_publish_does_not_leave_the_agent_live() -> None:
    """The RACE half of "an archived agent is never republished" (D-440).

    `publish_agent` refuses an archived agent twice: once on the row it reads, which gives
    the ordinary case a sentence a client can act on, and once in the WHERE clause of the
    UPDATE that writes `live`. This is the second one — the archive that commits after the
    read and before the write — and it is asserted the way the soft-delete twin is
    (`publish_verification_test`): the state has to be consistent whichever way it went,
    so the refusal is caught by hand rather than with `pytest.raises`.

    THE ARCHIVE IS APPLIED ON THE PUBLISH'S OWN CONNECTION, and that is the accurate
    simulation rather than a shortcut, for the reason that test records: under READ
    COMMITTED a commit from another session between the load and the UPDATE is
    indistinguishable from one applied on this one, and a genuinely concurrent archive
    cannot land in the window at all — `_load_agent(for_update=True)` holds the row lock,
    so the archive BLOCKS until the publish commits and then finds a `live` row to archive
    properly, numbers and all. That is the lock doing its job; this predicate is the floor
    under it, and the floor is what the next caller that forgets the lock falls onto.
    """
    import apps.api.engine as engine_module

    _fresh_engine()
    tenant_id, agent_id, _token = await _tenant()
    await _write_script(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:

        class ArchivingEngine(FakeEngine):
            """Archives the agent during the vendor call — the long call, and so the
            moment a real race lands."""

            async def create_agent(self, cfg: Any) -> Any:
                ref = await super().create_agent(cfg)
                await session.execute(
                    text(
                        "UPDATE agents SET status = 'archived', archived_at = now() WHERE id = :a"
                    ),
                    {"a": agent_id},
                )
                return ref

        previous = dict(engine_module._instances)
        engine_module._instances["fake"] = ArchivingEngine()
        refusal: ProblemError | None = None
        try:
            await publish_agent(session, tenant_id=tenant_id, agent_id=agent_id)
        except ProblemError as exc:
            refusal = exc
        finally:
            engine_module._instances.clear()
            engine_module._instances.update(previous)

        row = (
            await session.execute(
                text("SELECT status, engine_agent_ref, archived_at FROM agents WHERE id = :a"),
                {"a": agent_id},
            )
        ).first()
        routes = (
            await session.execute(
                text("SELECT count(*) FROM engine_agent_routes WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar_one()

    assert refusal is not None, "the publish reported success for an agent that was archived"
    assert row is not None
    assert row[0] == "archived", "the publish undid the archive and put a retired agent live"
    assert row[2] is not None, "the archival timestamp was cleared by a publish"
    assert row[1] is None, "an archived agent was given an engine ref"
    assert routes == 0, (
        "an archived agent got a routing row the vendor's next inbound webhook resolves to"
    )


# --- 5. tenancy ----------------------------------------------------------------------


async def test_a_neighbours_agent_is_a_404_on_every_new_route() -> None:
    """Hard rule 1 over the whole surface at once.

    Under RLS "that id is not yours" and "there is no such id" are deliberately the same
    answer, so a neighbour's agent must be indistinguishable from an id nobody minted —
    and it must be so on every route, not on the one somebody remembered to guard.
    """
    _fresh_engine()
    victim_tenant, victim_agent, _ = await _tenant()
    await _write_script(victim_tenant, victim_agent)
    _, _, attacker = await _tenant()

    async with _client(_app()) as http:
        headers = {"Authorization": f"Bearer {attacker}"}
        assert (await http.get(f"/v1/agents/{victim_agent}", headers=headers)).status_code == 404
        patched = await http.patch(
            f"/v1/agents/{victim_agent}", json={"name": "Mine now"}, headers=headers
        )
        assert patched.status_code == 404, patched.text
        for verb in ("activate", "deactivate", "archive", "restore"):
            response = await http.post(f"/v1/agents/{victim_agent}/{verb}", headers=headers)
            assert response.status_code == 404, f"{verb}: {response.text}"
        roster = await http.get("/v1/agents", headers=headers)
        stats = await http.get("/v1/agents/stats", headers=headers)

    assert str(victim_agent) not in {a["id"] for a in roster.json()}
    assert str(victim_agent) not in {row["agent_id"] for row in stats.json()}
    assert (await _status(victim_tenant, victim_agent))[0] == "draft", (
        "a neighbour moved this agent's lifecycle through a 404"
    )


async def test_staff_may_read_agents_but_not_move_them() -> None:
    """`org:manage` is the OWNER's permission — the person who answers for the account as
    the DLT Principal Entity — and it is what every mover on this surface asks for."""
    _fresh_engine()
    _, agent_id, staff = await _tenant(role="staff")
    async with _client(_app()) as http:
        headers = {"Authorization": f"Bearer {staff}"}
        assert (await http.get("/v1/agents", headers=headers)).status_code == 200
        created = await http.post(
            "/v1/agents", json={"name": "Nope", "direction": "inbound"}, headers=headers
        )
        moved = await http.post(f"/v1/agents/{agent_id}/archive", headers=headers)
    assert created.status_code == 403, created.text
    assert moved.status_code == 403, moved.text


# --- 6. the machine itself -----------------------------------------------------------


def test_every_transition_target_is_a_state_the_machine_knows() -> None:
    """The table cannot name a destination it has no row for — which would be a state
    reachable and unleavable, i.e. an agent nobody can move again."""
    for source, targets in lifecycle.AGENT_TRANSITIONS.items():
        assert source not in targets, f"{source} lists itself as a transition"
        unknown = targets - set(lifecycle.AGENT_TRANSITIONS)
        assert not unknown, f"{source} -> {unknown}: no row in the transition table"


def test_activate_accepts_exactly_the_states_the_table_admits() -> None:
    """`activate_agent` renders two of the table's edges as two branches and asserts no
    third, so this is what keeps the rendering and the table in step.

    Add a fifth status that may go live and this fails, which is the moment somebody has to
    decide whether `activate_agent` should carry it — rather than a defensive arm nothing
    can reach sitting in the function pretending to have decided already.
    """
    admitted = {
        source for source, targets in lifecycle.AGENT_TRANSITIONS.items() if "live" in targets
    }
    assert admitted == {"draft", "paused"}, (
        "activate_agent branches on `archived` and `live` and then publishes; the states "
        f"that may reach `live` have changed to {sorted(admitted)}"
    )


def test_the_movers_and_the_transition_table_describe_the_same_machine() -> None:
    """`AGENT_MOVERS` and `AGENT_TRANSITIONS` must be two spellings of one graph.

    THE BUG THIS REPLACES A COMMENT ABOUT. Every mover used to read its accepted sources
    off its TARGET, which is a derivation that cannot tell two movers apart — and two of
    them end at `paused`. `restore` therefore accepted `live` and switched a live agent off
    without releasing its numbers, and `deactivate` accepted `archived` and took an agent
    back out of the archive. The partition below is what makes that unrepresentable, so it
    is checked at import and again here on both directions of the disagreement.
    """
    lifecycle._assert_movers_partition_the_table()

    # An edge the table admits and no mover implements: unreachable through the API, which
    # is exactly the half a per-target derivation could not have noticed.
    with pytest.raises(AssertionError, match="Claimed by no mover"):
        lifecycle._assert_movers_partition_the_table(
            transitions={
                **lifecycle.AGENT_TRANSITIONS,
                "draft": frozenset({"live", "archived", "paused"}),
            }
        )

    # THE SHIPPED DEFECT, in the shape the target-keyed derivation produced it: `restore`
    # ALSO claiming `live -> paused`. The edge is legal and stays covered, so a set
    # equality between the two dicts is green on it — which is why this is a partition.
    with pytest.raises(AssertionError, match="Claimed by more than one mover"):
        lifecycle._assert_movers_partition_the_table(
            movers={
                **lifecycle.AGENT_MOVERS,
                "restore": (frozenset({"archived", "live"}), "paused"),
            }
        )

    # A mover claiming an edge the table forbids at all: `archived -> live`, the one edge
    # `AGENT_TRANSITIONS` argues against by name.
    with pytest.raises(AssertionError, match="Claimed but not legal"):
        lifecycle._assert_movers_partition_the_table(
            movers={
                **lifecycle.AGENT_MOVERS,
                "activate": (frozenset({"draft", "paused", "archived"}), "live"),
            }
        )


def test_the_archive_is_the_only_state_a_campaign_may_not_name() -> None:
    """Pinned so the set cannot quietly widen: refusing a DRAFT agent here would break the
    ordinary flow of assembling a campaign before publishing the agent it will use."""
    assert frozenset({"draft", "live", "paused"}) == lifecycle.ASSIGNABLE_STATUSES
