"""Changing the agent's main language on Name and voice after its first work was asked for:
the work speaks the new language (the job is posted as soon as the agent is made, so its
script was written, or is being written, in the first one).

By who wrote what the line holds: a draft still being written is asked again; Pip's script is
rewritten whole; the ready-made script is saved again in the new language; the owner's own
script is left as they wrote it. A save that keeps the language asks for nothing.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
from apps.api.agents import starters
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from calevate_shared.call_script import CallScript
from sqlalchemy import text
from tests.first_run_test import _client, _owner, _tenant
from tests.first_run_work_test import (
    _drafted_line,
    _no_allowance,
    _no_voice,  # noqa: F401  (the autouse fixture: no voice is picked)
    _written,
)

TELUGU = {"name": "Anjali", "language_primary": "te-IN", "languages_extra": ["en-IN"]}
HINDI = {"name": "Anjali", "language_primary": "hi-IN", "languages_extra": ["en-IN"]}


async def _proposal(tenant_id: uuid.UUID, line_id: uuid.UUID) -> dict[str, Any] | None:
    async with tenant_session(tenant_id) as session:
        found = (
            await session.execute(
                text("SELECT script_proposal FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
    return None if found is None else dict(found)


async def _save_agent(headers: dict[str, str], body: dict[str, Any]) -> None:
    async with _client() as http:
        saved = await http.put("/v1/first-run/agent", headers=headers, json=body)
    assert saved.status_code == 200, saved.text


async def test_a_first_draft_still_being_written_is_asked_again() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    line_id = await _drafted_line(tenant_id, headers)
    before = await _proposal(tenant_id, line_id)
    assert before is not None and before["status"] == "drafting"
    await _save_agent(headers, HINDI)
    after = await _proposal(tenant_id, line_id)
    assert after is not None and after["status"] == "drafting" and after["auto_save"] is True
    assert after["id"] != before["id"], "the job reading the old language is stopped"


async def test_a_script_pip_wrote_is_rewritten_in_the_new_language() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    line_id = await _drafted_line(tenant_id, headers)
    await _written(tenant_id, line_id)
    assert await _proposal(tenant_id, line_id) is None
    await _save_agent(headers, HINDI)
    asked = await _proposal(tenant_id, line_id)
    assert asked is not None and asked["status"] == "drafting"
    assert asked["ask"] == {"rewrite": "language:hi-IN"}
    # Saved by the writer only while the script is still this one (`_save_if_rewrite`).
    assert asked["base_script"] is not None


async def test_a_script_the_owner_saved_keeps_their_words() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    line_id = await _drafted_line(tenant_id, headers)
    await _written(tenant_id, line_id)
    own = CallScript(opening_line="Hello, this is Madhav Homes.")
    async with tenant_session(tenant_id) as session:
        await lines.save_script(session, line_id, own, author="owner")
    await _save_agent(headers, HINDI)
    assert await _proposal(tenant_id, line_id) is None
    async with tenant_session(tenant_id) as session:
        assert (await lines.read_line(session, line_id)).script == own


async def test_the_ready_made_script_is_saved_again_in_the_new_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _no_allowance(monkeypatch)
    spoken: list[str] = []
    original = starters.ready_made_script

    async def _recording(*args: Any, **kwargs: Any) -> CallScript:
        spoken.append(str(kwargs["language"]))
        return await original(*args, **kwargs)

    monkeypatch.setattr(starters, "ready_made_script", _recording)
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    line_id = await _drafted_line(tenant_id, headers)
    async with tenant_session(tenant_id) as session:
        first = (await lines.read_line(session, line_id)).version
    await _save_agent(headers, HINDI)
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert spoken == ["te-IN", "hi-IN"]
    assert line.script is not None and line.version == first + 1
    assert await _proposal(tenant_id, line_id) is None, "Pip was not asked"


async def test_a_save_that_keeps_the_language_asks_for_nothing() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    line_id = await _drafted_line(tenant_id, headers)
    await _written(tenant_id, line_id)
    await _save_agent(headers, {**TELUGU, "name": "Priya"})
    assert await _proposal(tenant_id, line_id) is None
