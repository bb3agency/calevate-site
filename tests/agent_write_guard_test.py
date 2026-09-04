"""Nothing writes to a DELETED agent, and the refusal lives in ONE place.

THE DEFECT. The console's agent screen showed a header badge reading "Deleted" and then
offered a green "Open the script builder" button under the words "Write the script first —
an agent with none cannot be switched on". It was not only bad copy: `PUT /v1/agents/{id}/
script` really did save a new version onto a retired agent, and so did the voice, the model,
the disclosure toggles, the call cap, the extraction schema, the enabled actions, the
knowledge doors and the human-handoff configuration. Four writers checked the archived state
(`update_agent`, `activate`, `deactivate`, `publish_agent`); every other one did not.

WHAT IS UNDER TEST is that the fix is a property of the WRITE PATH rather than of any
endpoint, so an endpoint written next week inherits it:

1. The guard itself refuses an archived agent and is silent on every other status.
2. A representative endpoint that had NO check of its own — the script builder's `PUT`,
   the exact button in the screenshot — is refused end to end, with the wording a person
   can act on.
3. The two moves whose subject is legitimately a retired agent still work: `restore`, and
   `archive` again (deleting a deleted agent is an idempotent success, RFC 9110 §9.2.2).
4. Reading a deleted agent still works. That is the whole difference between archiving and
   erasing, and a guard that hid the history would be a worse bug than the one it fixed.
5. The exempt list names paths that really exist, so a route rename cannot quietly turn an
   exemption into a hole.
6. The assistant refuses too, at PLAN time, so it never OFFERS the edit.
7. The knowledge door, whose agent arrives in the request BODY where the route-level guard
   cannot see it, is refused at the one place all three of its routes pass through.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.agents.write_guard import ARCHIVED_WRITE_EXEMPT_PATHS, assert_agent_writable
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import iter_api_routes
from apps.api.db.session import tenant_session
from apps.api.engine import reset_engine_cache
from httpx import ASGITransport, AsyncClient
from tests.agent_lifecycle_test import _tenant, _write_script

pytestmark = [pytest.mark.rls]


def _main_app() -> object:
    from apps.api.main import app

    return app


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_main_app()), base_url="http://api")


def _code(body: dict[str, object]) -> str:
    """The machine identifier rides in `type`'s last segment, not in a `code` field
    (`core/errors.ProblemError.as_problem`)."""
    return str(body["type"]).rsplit("/", 1)[-1]


async def _archive(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> None:
    """Retire the agent through the mover, not with an UPDATE — the CHECK constraint pairs
    `status` and `archived_at`, and a fixture that wrote one without the other would be
    testing a state the product cannot reach."""
    from apps.api.agents import lifecycle

    async with tenant_session(tenant_id) as session:
        await lifecycle.archive_agent(session, tenant_id=tenant_id, agent_id=agent_id)


async def test_the_guard_refuses_only_an_archived_agent() -> None:
    reset_engine_cache()
    tenant_id, agent_id, _token = await _tenant()

    async with tenant_session(tenant_id) as session:
        # draft — silent.
        await assert_agent_writable(session, agent_id)
        # an id nobody minted — silent. "Not yours" is `assert_visible`'s question, and
        # answering it here would turn a 404 into a 409 that confirms a neighbour's id.
        await assert_agent_writable(session, uuid.uuid4())

    await _write_script(tenant_id, agent_id)
    await _archive(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await assert_agent_writable(session, agent_id, verb="changed")
    assert raised.value.code == "agent_archived"
    assert "deleted" in raised.value.detail, (
        "the message used the server's word; the person pressed a button called Delete"
    )
    assert "Restore" in (raised.value.remediation or ""), (
        "a refusal whose answer is 'restore it' must say so"
    )


async def test_the_script_builder_cannot_write_to_a_deleted_agent() -> None:
    """THE SCREENSHOT, end to end. `PUT /v1/agents/{id}/script` had no check of its own.

    It is the representative endpoint precisely because it is not special: nothing was added
    to `script_routes.py` to make this pass, so the same assertion holds for the voice, the
    model, the toggles, the extraction schema and the handoff configuration.
    """
    reset_engine_cache()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)

    script = {"opening_line": "Hello, this is the clinic.", "steps": []}
    async with _client() as http:
        headers = {"Authorization": f"Bearer {token}"}
        before = await http.put(
            f"/v1/agents/{agent_id}/script", json={"script": script}, headers=headers
        )
        assert before.status_code == 200, before.text

        await _archive(tenant_id, agent_id)

        after = await http.put(
            f"/v1/agents/{agent_id}/script", json={"script": script}, headers=headers
        )
        assert after.status_code == 409, after.text
        body = after.json()
        assert _code(body) == "agent_archived", body
        assert "deleted" in body["detail"], body

        # AND IT STILL READS. Archiving keeps the history; a guard that hid it would be a
        # worse defect than the one it fixes.
        read = await http.get(f"/v1/agents/{agent_id}/script", headers=headers)
        assert read.status_code == 200, read.text


async def test_restore_and_a_second_delete_are_not_refused_by_their_own_guard() -> None:
    """The two exempt moves, and the reason each is exempt.

    Guarding `restore` would make the refusal's own remediation unreachable; guarding
    `archive` would turn a double-clicked Delete into an error instead of the idempotent
    success `archive_agent` already answers.
    """
    reset_engine_cache()
    tenant_id, agent_id, token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await _archive(tenant_id, agent_id)

    async with _client() as http:
        headers = {"Authorization": f"Bearer {token}"}
        again = await http.post(f"/v1/agents/{agent_id}/archive", headers=headers)
        assert again.status_code == 200, again.text
        assert again.json()["changed"] is False, again.text

        restored = await http.post(f"/v1/agents/{agent_id}/restore", headers=headers)
        assert restored.status_code == 200, restored.text

        # And the edit the guard was refusing works again the moment it is restored, which
        # is the promise the refusal's remediation makes.
        saved = await http.put(
            f"/v1/agents/{agent_id}/script",
            json={"script": {"opening_line": "Back in service.", "steps": []}},
            headers=headers,
        )
        assert saved.status_code == 200, saved.text


def test_every_exempt_path_is_a_route_that_exists() -> None:
    """A rename must not quietly turn an exemption into a hole."""
    paths = {route.path for route in iter_api_routes(_main_app())}  # type: ignore[arg-type]
    assert paths >= ARCHIVED_WRITE_EXEMPT_PATHS, sorted(ARCHIVED_WRITE_EXEMPT_PATHS - paths)


async def test_the_assistant_refuses_to_change_a_deleted_agent_before_it_offers() -> None:
    """At PLAN time, not at execute — a refusal after Confirm is an answer to the wrong
    question, and it is the one `agent_rename` used to give."""
    from apps.api.copilot.actions import WriteRefusedError
    from apps.api.copilot.write_tools import _BY_NAME, _refuse_a_deleted_agent

    reset_engine_cache()
    tenant_id, agent_id, _token = await _tenant()
    await _write_script(tenant_id, agent_id)
    tool = _BY_NAME["agent_rename"]
    args = {"agent_id": str(agent_id), "name": "Renamed while deleted"}

    async with tenant_session(tenant_id) as session:
        await _refuse_a_deleted_agent(session, tool, args)  # a live-enough agent: silent

    await _archive(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        with pytest.raises(WriteRefusedError) as refused:
            await _refuse_a_deleted_agent(session, tool, args)
    assert "deleted" in str(refused.value)
    assert "do not offer" in str(refused.value), (
        "the assistant was told the change failed, not that it must stop offering it"
    )


async def test_knowledge_cannot_be_attached_to_a_deleted_agent() -> None:
    """The agent arrives in the BODY here, so the route-level guard cannot see it. All
    three knowledge doors go through `insert_source_version`, which is where it is asked."""
    from apps.api.kb import service as kb_service

    reset_engine_cache()
    tenant_id, agent_id, _token = await _tenant()
    await _write_script(tenant_id, agent_id)
    await _archive(tenant_id, agent_id)

    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await kb_service.submit_source(
                session,
                tenant_id=tenant_id,
                agent_id=agent_id,
                name="Saturday hours",
                body="We open at 9am on Saturdays.",
                kind="text",
                uri=None,
                submitted_by=None,
            )
    assert raised.value.code == "agent_archived"
