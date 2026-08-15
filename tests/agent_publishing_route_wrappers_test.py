"""Four agent-lifecycle routes nothing drove at the HTTP layer (PLAN part 8).

`POST …/agents/{agent_id}/prompt/rollback`, `POST …/agents/{agent_id}/undo`,
`GET /v1/agents/{agent_id}/engine-state` and `GET /v1/agents/{agent_id}/experiment`.

The services beneath all four are well covered — `two_speed_publishing_test` drives
`undo_staged`, `publish_verification_test` drives `engine_drift_for`,
`experiment_stats_test` drives `results_for`, and `prompt_history_test` drives
`rollback_prompt`. What none of them touches is the wrapper: whether the route is
reachable by the principal who needs it, whether the response model carries the fields
the screen reads, and whether the audit row that makes a recovery "loud rather than
silent" is actually written.

What is asserted here:

1. **The two READS are readable by `staff`.** Both are `agents:read`, and both exist to
   EXPLAIN something — "the engine is running something else", "this test cannot be
   stopped yet". `impersonation_reads_test` asserts that rule over the route table by
   reading declarations; this drives it with a principal who holds only the read
   permissions, which is the half a declaration cannot prove.
2. **Neither read leaks across tenants.** `engine-state` and `experiment` take the
   agent id from the PATH and the tenant from the SESSION — the shape that leaks if the
   service ever stops scoping. A neighbour's agent id answers as though the agent does
   not exist.
3. **`rollback` is copy-forward and AUDITED.** `prompts.rollback_prompt:257` justifies
   applying a rollback immediately — the slow lane's one exception — on the grounds
   that `prompt_routes.rollback_prompt` writes an audit row naming both versions. That
   is a safety argument resting on a route, and nothing held the route to it.
4. **`undo` audits only a real undo.** The `if result.undone` guard is the
   "audit follows a transition, not a button press" convention; a second press is 200
   with `undone: false` and no second row.

D-22 is not re-asserted: both mutating routes declare `agents:write`, and
`realm_boundary_test::test_no_route_declaring_a_mutating_permission_is_reachable_while_impersonating`
already drives every such route under a real grant.

CONCURRENCY: every case mints its own tenant and asserts only on rows it created.
"""

from __future__ import annotations

import logging
import uuid

import pytest
from apps.api.agents import prompts
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.two_speed_publishing_test import (
    APPLIED,
    STAGED,
    _live_agent_with_a_staged_draft,
    _tenant,
)

ROLLBACK = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/prompt/rollback"
UNDO = "/v1/admin/tenants/{tenant_id}/agents/{agent_id}/undo"
ENGINE_STATE = "/v1/agents/{agent_id}/engine-state"
EXPERIMENT = "/v1/agents/{agent_id}/experiment"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "cid": clerk_id, "role": role},
        )
    return f"dev:admin:{clerk_id}"


async def _make_member(tenant_id: uuid.UUID, role: str = "owner") -> str:
    user_id = uuid.uuid4()
    clerk_id = f"user_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, clerk_user_id, email, created_at, updated_at) "
                "VALUES (:id, :cid, :email, now(), now())"
            ),
            {"id": user_id, "cid": clerk_id, "email": f"{clerk_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, :role, now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id, "role": role},
        )
    return f"dev:client:{clerk_id}"


async def _slug(tenant_id: uuid.UUID) -> str:
    # `organizations` is tenant-scoped: an untenanted session sees zero rows.
    async with tenant_session(tenant_id) as session:
        return str(
            (
                await session.execute(
                    text("SELECT slug FROM organizations WHERE id = :t"), {"t": tenant_id}
                )
            ).scalar_one()
        )


async def _client_headers(tenant_id: uuid.UUID, role: str = "staff") -> dict[str, str]:
    token = await _make_member(tenant_id, role=role)
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": await _slug(tenant_id)}


async def _audit(tenant_id: uuid.UUID, action: str) -> list[tuple[str, str, str | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT object_type, object_id, ip FROM audit_log "
                    "WHERE tenant_id = :t AND action = :a ORDER BY at, id"
                ),
                {"t": tenant_id, "a": action},
            )
        ).all()
    return [(str(r[0]), str(r[1]), None if r[2] is None else str(r[2])) for r in rows]


def _summaries(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.getMessage() == "audit"]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# --- the reads ------------------------------------------------------------------------


async def test_staff_can_read_the_engine_state_and_every_field_is_populated() -> None:
    """The reconciliation read, driven by a principal holding only `agents:read` —
    which is the population D-22 makes this route exist for.

    Every field of `EngineStateOut` is asserted, not just the status: `in_sync` alone
    is a boolean an empty handler could return, while `engine_agent_ref` and the
    tri-state `*_applied` triple are what make the answer a FINDING rather than a
    shrug. A published, unedited agent must read back in sync.
    """
    tenant_id, agent_id, ref, _engine = await _live_agent_with_a_staged_draft()
    headers = await _client_headers(tenant_id, role="staff")
    async with _client() as http:
        response = await http.get(ENGINE_STATE.format(agent_id=agent_id), headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_id"] == str(agent_id)
    assert body["engine"] == "fake"
    assert body["engine_agent_ref"] == ref, "the handle is what makes the answer checkable"
    assert body["checked"] is True, "an unchecked read is a vendor call that did not happen"
    assert body["state"] == "applied"
    assert body["in_sync"] is True
    # Tri-state per property: the fake adapter reads all three back, so none is null.
    assert body["prompt_applied"] is True
    assert body["disclosure_applied"] is True
    assert body["voice_applied"] is True
    assert body["detail"], "a state with no sentence behind it is not actionable"


async def test_the_engine_state_of_a_neighbours_agent_is_not_visible() -> None:
    """The agent id comes from the PATH and the tenant from the SESSION. A handler that
    resolved the agent without the session's tenant would answer about somebody else's
    voice platform configuration."""
    tenant_id, _agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    _other_tenant, other_agent, _other_ref, _other_engine = await _live_agent_with_a_staged_draft()
    headers = await _client_headers(tenant_id, role="owner")
    async with _client() as http:
        response = await http.get(ENGINE_STATE.format(agent_id=other_agent), headers=headers)
    assert response.status_code == 404, response.text


async def test_staff_can_read_the_experiment_view_with_its_rules_before_any_test_runs() -> None:
    """`experiment` is null when nothing is running, and the RULES are still published —
    that is the shape the screen needs to say "no test running" rather than to render
    nothing at all. A handler returning `{}` would satisfy a status assertion."""
    tenant_id, agent_id = await _tenant()
    headers = await _client_headers(tenant_id, role="staff")
    async with _client() as http:
        response = await http.get(EXPERIMENT.format(agent_id=agent_id), headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["agent_id"] == str(agent_id)
    assert body["experiment"] is None
    rules = body["rules"]
    assert rules["metrics"], "the comparison rules are static and always published"
    assert all(m["key"] and m["label"] for m in rules["metrics"])
    assert rules["default_metric"] in {m["key"] for m in rules["metrics"]}
    assert rules["minimum_calls_per_variant"] > 0
    assert rules["split_min_bp"] > 0
    assert rules["split_total_bp"] == 10_000, "basis points, not percent"
    assert rules["peeking_caveat"], "the caveat is the honesty of the whole panel"


# --- rollback -------------------------------------------------------------------------


async def test_rollback_copies_forward_and_audits_both_version_numbers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Copy-forward, never pointer-rewind: v1 and v2 stay exactly as written and v3
    carries v1's body.

    The audit row is the load-bearing half. `prompts.rollback_prompt:257` justifies
    applying a rollback IMMEDIATELY — the one exception to the slow lane — by saying the
    route makes it loud. If this route stopped writing the row, that argument would be
    false and no test would notice.
    """
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()
    token = await _make_admin()
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            response = await http.post(
                ROLLBACK.format(tenant_id=tenant_id, agent_id=agent_id),
                headers=_auth(token),
                json={"version": 1},
            )
    assert response.status_code == 200, response.text
    assert response.json() == {"to_version": 1, "new_version": 3}

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT version, body, notes FROM prompt_versions "
                    "WHERE agent_id = :a ORDER BY version"
                ),
                {"a": agent_id},
            )
        ).all()
    assert [r[0] for r in rows] == [1, 2, 3], "history stays linear; no number is reused"
    assert rows[0][1] == APPLIED and rows[1][1] == STAGED, "the past was not rewritten"
    assert rows[2][1] == APPLIED, "v3 carries v1's body"
    assert rows[2][2] == "rollback to v1"
    # Applied, not staged: the recovery path does not wait for a second click.
    assert engine._agents[ref].system_prompt == APPLIED

    assert await _audit(tenant_id, "prompt.rolled_back") == [("agent", str(agent_id), "127.0.0.1")]
    summary = _summaries(caplog)[-1]
    assert summary.to_version == 1  # type: ignore[attr-defined]
    assert summary.new_version == 3  # type: ignore[attr-defined]
    assert APPLIED[:20] not in str(summary.__dict__), (
        "version NUMBERS only — a prompt body embeds client business detail (hard rule 6)"
    )


async def test_rolling_back_to_a_version_that_does_not_exist_writes_nothing() -> None:
    tenant_id, agent_id, _ref, _engine = await _live_agent_with_a_staged_draft()
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            ROLLBACK.format(tenant_id=tenant_id, agent_id=agent_id),
            headers=_auth(token),
            json={"version": 99},
        )
    assert response.status_code == 404, response.text
    async with tenant_session(tenant_id) as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM prompt_versions WHERE agent_id = :a"), {"a": agent_id}
            )
        ).scalar_one()
    assert count == 2, "a failed rollback must not leave a version behind"
    assert await _audit(tenant_id, "prompt.rolled_back") == []


# --- undo -----------------------------------------------------------------------------


async def test_undo_discards_the_staged_draft_and_audits_only_a_real_undo(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A pointer moves; no `prompt_versions` row is written or deleted, so the
    discarded version stays readable and its number is never reused.

    The second press is the assertion that matters: 200 with `undone: false` and NO
    second audit row — the "audit follows a transition, not a button press" convention
    that this repo applies in five places and had tested in four.
    """
    tenant_id, agent_id, ref, engine = await _live_agent_with_a_staged_draft()
    token = await _make_admin()
    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        async with _client() as http:
            first = await http.post(
                UNDO.format(tenant_id=tenant_id, agent_id=agent_id), headers=_auth(token)
            )
            second = await http.post(
                UNDO.format(tenant_id=tenant_id, agent_id=agent_id), headers=_auth(token)
            )
    assert first.status_code == 200, first.text
    assert first.json() == {
        "agent_id": str(agent_id),
        "undone": True,
        "discarded_version": 2,
        "live_version": 1,
    }
    assert second.status_code == 200, second.text
    assert second.json()["undone"] is False, "there was nothing left to discard"

    async with tenant_session(tenant_id) as session:
        versions = (
            await session.execute(
                text("SELECT version FROM prompt_versions WHERE agent_id = :a ORDER BY version"),
                {"a": agent_id},
            )
        ).scalars()
    assert list(versions) == [1, 2], "the discarded version is still readable"
    assert engine._agents[ref].system_prompt == APPLIED, "callers still hear v1"

    assert await _audit(tenant_id, "agent.changes_undone") == [
        ("agent", str(agent_id), "127.0.0.1")
    ]
    summary = _summaries(caplog)[-1]
    assert summary.discarded_version == 2  # type: ignore[attr-defined]
    assert summary.version == 1  # type: ignore[attr-defined]


async def test_undo_on_an_agent_with_nothing_staged_is_not_an_error() -> None:
    """The button is on the screen whenever the banner is, and a race between two tabs
    must not answer 409 to the second one."""
    tenant_id, agent_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await prompts.write_prompt_version(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            body=APPLIED,
            notes=None,
            created_by=None,
        )
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            UNDO.format(tenant_id=tenant_id, agent_id=agent_id), headers=_auth(token)
        )
    assert response.status_code == 200, response.text
    assert response.json()["undone"] is False
    assert await _audit(tenant_id, "agent.changes_undone") == []
