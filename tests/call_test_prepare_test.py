"""D-822: "Make this call a test" asked of Pip (`call_test_prepare`).

Pip fills in the call page's test form and saves nothing: the person checks it and saves it
through `POST /v1/calls/{call_id}/test-case`, which removes what Pip left. Each test names
what would go wrong: a test saved unseen, a caller's raw words copied, a form that reopens
after it was saved, an Undo that overwrites a newer preparation, a neighbour's rows.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.copilot import write_tools
from apps.api.copilot.write_tools_test import _audit, _principal, _user_of
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.api.teach import test_cases
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.api_security_test import _make_tenant

TOOL = "call_test_prepare"


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _headers(token: str, slug: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Org-Slug": slug}


async def _call(tenant_id: UUID, *, caller_says: bool = True) -> UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar_one()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "headline, started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'inbound', 'completed', 'Asked about chilli', now(), now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"ct_{call_id.hex[:12]}"},
        )
        turns = [("agent", "Namaskaram", "Namaskaram")]
        if caller_says:
            turns.append(
                (
                    "caller",
                    "naa number 9876543210, chilli undha?",
                    "naa number [phone], chilli undha?",
                )
            )
        for idx, (speaker, raw, redacted) in enumerate(turns):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, created_at, updated_at) VALUES (:id, :t, :c, :i, :s, :raw, "
                    ":red, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "t": tenant_id,
                    "c": call_id,
                    "i": idx,
                    "s": speaker,
                    "raw": raw,
                    "red": redacted,
                },
            )
    return call_id


async def _run(tenant_id: UUID, token: str, args: dict[str, Any], *, role: str = "owner") -> Any:
    return await write_tools.run_immediate(
        TOOL,
        json.dumps(args),
        principal=_principal(tenant_id, _user_of(token), role=role),
        seed=f"calltest-{uuid.uuid4()}",
        ip=None,
    )


def _args(
    call_id: UUID, expected: str | None = "Gives the chilli price from knowledge."
) -> dict[str, Any]:
    return {"call_id": str(call_id), "expected": expected, "title": None}


async def _pending_rows(tenant_id: UUID) -> list[Any]:
    async with tenant_session(tenant_id) as session:
        return list(
            (
                await session.execute(
                    text("SELECT call_id, requested_by, expected, title FROM call_test_case_drafts")
                )
            ).all()
        )


async def test_pip_fills_the_form_and_saves_no_test() -> None:
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call(tenant_id)
    receipt = await _run(tenant_id, token, _args(call_id))
    assert receipt.applied is True and receipt.tool == TOOL
    assert receipt.action_id is not None

    [row] = await _pending_rows(tenant_id)
    assert (row.call_id, row.requested_by) == (call_id, _user_of(token))
    assert row.expected == "Gives the chilli price from knowledge."
    assert ("agent_test_case.prepared", "call", str(call_id)) in await _audit(tenant_id)
    async with tenant_session(tenant_id) as session:
        saved = (await session.execute(text("SELECT count(*) FROM agent_test_cases"))).scalar()
    assert saved == 0

    async with _client() as http:
        form = await http.get(f"/v1/calls/{call_id}/test-case-draft", headers=_headers(token, slug))
    assert form.status_code == 200, form.text
    body = form.json()
    assert body["pending"] == {"expected": "Gives the chilli price from knowledge.", "title": None}
    # The caller's lines are the form's own redacted read; Pip copied none of them.
    assert body["caller_lines"] == ["naa number [phone], chilli undha?"]


async def test_saving_the_form_keeps_the_test_and_closes_what_pip_left() -> None:
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call(tenant_id)
    await _run(tenant_id, token, _args(call_id))
    async with _client() as http:
        saved = await http.post(
            f"/v1/calls/{call_id}/test-case",
            headers=_headers(token, slug),
            json={
                "title": "Chilli",
                "caller_lines": ["naa number [phone], chilli undha?"],
                "expected": "Gives the chilli price.",
            },
        )
        form = await http.get(f"/v1/calls/{call_id}/test-case-draft", headers=_headers(token, slug))
    assert saved.status_code == 201, saved.text
    assert await _pending_rows(tenant_id) == []
    assert form.json()["pending"] is None


async def test_discarding_removes_it_and_a_second_discard_is_not_found() -> None:
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call(tenant_id)
    await _run(tenant_id, token, _args(call_id, expected=None))
    async with _client() as http:
        first = await http.delete(
            f"/v1/calls/{call_id}/test-case-draft/pending", headers=_headers(token, slug)
        )
        second = await http.delete(
            f"/v1/calls/{call_id}/test-case-draft/pending", headers=_headers(token, slug)
        )
    assert first.status_code == 204
    assert second.status_code == 404
    assert await _pending_rows(tenant_id) == []


async def test_undo_restores_the_earlier_form_and_refuses_after_it_was_saved() -> None:
    tenant_id, slug, token = await _make_tenant()
    call_id = await _call(tenant_id)
    await _run(tenant_id, token, _args(call_id, expected="First wording."))
    second = await _run(tenant_id, token, _args(call_id, expected="Second wording."))
    async with _client() as http:
        undone = await http.post(
            f"/v1/copilot/actions/{second.action_id}/undo", headers=_headers(token, slug)
        )
    assert undone.status_code == 200, undone.text
    [row] = await _pending_rows(tenant_id)
    assert row.expected == "First wording."

    third = await _run(tenant_id, token, _args(call_id, expected="Third wording."))
    async with _client() as http:
        await http.delete(
            f"/v1/calls/{call_id}/test-case-draft/pending", headers=_headers(token, slug)
        )
        refused = await http.post(
            f"/v1/copilot/actions/{third.action_id}/undo", headers=_headers(token, slug)
        )
    assert refused.status_code == 409, refused.text
    assert await _pending_rows(tenant_id) == []


async def test_a_call_the_caller_said_nothing_in_is_refused_before_anything_is_written() -> None:
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call(tenant_id, caller_says=False)
    with pytest.raises(write_tools.WriteRefusedError) as refused:
        await _run(tenant_id, token, _args(call_id))
    assert "caller said nothing" in refused.value.reason
    assert await _pending_rows(tenant_id) == []


async def test_a_role_without_the_save_permission_is_refused() -> None:
    tenant_id, _slug, token = await _make_tenant()
    call_id = await _call(tenant_id)
    with pytest.raises(write_tools.WriteRefusedError):
        await _run(tenant_id, token, _args(call_id), role="ghost")
    assert await _pending_rows(tenant_id) == []


@pytest.mark.rls
async def test_a_neighbours_call_is_not_found_and_their_prepared_tests_are_invisible() -> None:
    tenant_a, _slug_a, token_a = await _make_tenant()
    tenant_b, _slug_b, token_b = await _make_tenant()
    call_a = await _call(tenant_a)
    await _run(tenant_a, token_a, _args(call_a))
    with pytest.raises(ProblemError) as missing:
        await _run(tenant_b, token_b, _args(call_a))
    assert missing.value.status == 404
    async with tenant_session(tenant_b) as session:
        seen = (
            await session.execute(
                text("SELECT count(*) FROM call_test_case_drafts WHERE tenant_id = :a"),
                {"a": tenant_a},
            )
        ).scalar()
        assert seen == 0
        assert (
            await test_cases.read_pending(session, call_id=call_a, user_id=_user_of(token_a))
            is None
        )
