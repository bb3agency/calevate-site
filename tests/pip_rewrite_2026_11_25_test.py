"""Pip rewrites the scripts it still owns under the script rules of 25 Nov 2026 (founder,
25 Nov 2026: once the fixed writer ships, every script Pip wrote and the owner has not edited
since is rewritten; an edited one gets only the line repairs).

Against a real database, with Pip's writer replaced at its seam so no model is called. Every
organisation is minted here and every assertion is scoped to its own ids.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import script_heal
from apps.api.campaigns import script_history
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.workers import campaign_script
from apps.workers import script_heal as heal_job
from calevate_shared.call_script import CallScript, ConversationStage
from sqlalchemy import text
from tests import script_heal_2026_11_24_test as heal_test

REWRITTEN = CallScript(
    schema_version=2,
    opening_line="Hello, this is Asha from ShopBook. Can we talk for a minute now?",
    stages=[
        ConversationStage(
            id="s1",
            name="Check installation",
            instruction="Ask whether the app is on their home screen.",
            sounds_like="Is ShopBook on your home screen?",
        )
    ],
)


@pytest.fixture(autouse=True)
def _no_extra_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(heal_test.get_settings(), "script_mistake_repair_passes", 0)


async def _record(tenant_id: UUID, line_id: UUID, *authors: str) -> None:
    async with tenant_session(tenant_id) as session:
        for author in authors:
            await script_history.record(
                session,
                tenant_id=tenant_id,
                kind="line",
                holder_id=line_id,
                script=heal_test._script(heal_test.PLAIN),
                author=author,  # type: ignore[arg-type]
            )


async def _owns(tenant_id: UUID, line_id: UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        return await script_history.pip_owns(session, "line", line_id)


async def _new_line(tenant_id: UUID, agent_id: UUID) -> UUID:
    return await heal_test._line(tenant_id, agent_id, heal_test._script(heal_test.PLAIN))


async def test_a_script_is_pips_until_the_owner_acts_after_pips_last_draft() -> None:
    """FAILS IF: a script the owner edited after Pip wrote it, or one older than the history,
    counts as Pip's; or one only Pip's own passes touched does not."""
    tenant_id, agent_id = await heal_test._account("own")
    line_id = await _new_line(tenant_id, agent_id)
    assert not await _owns(tenant_id, line_id), "made by the owner"
    await _record(tenant_id, line_id, "pip_draft", "pip_repair", "pip_outcomes", "system")
    assert await _owns(tenant_id, line_id)
    await _record(tenant_id, line_id, "owner")
    assert not await _owns(tenant_id, line_id)
    await _record(tenant_id, line_id, "pip_draft", "restored")
    assert not await _owns(tenant_id, line_id)

    older = await _new_line(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("DELETE FROM script_versions WHERE inbound_line_id = :h"), {"h": older}
        )
    await _record(tenant_id, older, "earlier")
    assert not await _owns(tenant_id, older), "older than the history: never rewritten"


async def _proposal_ask(tenant_id: UUID, line_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT script_proposal->'ask' FROM inbound_lines WHERE id = :h"),
                {"h": line_id},
            )
        ).scalar()


async def _clear_proposal(tenant_id: UUID, line_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET script_proposal = NULL WHERE id = :h"), {"h": line_id}
        )


async def _pass(tenant_id: UUID, line_id: UUID) -> str:
    await heal_test._queue(tenant_id, "line", line_id)
    return await heal_job.repair_holder_script({}, heal_test._payload(tenant_id, "line", line_id))


async def test_the_repair_pass_asks_one_rewrite_of_a_script_pip_owns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a script Pip owns gets only line repairs, its rewrite is asked again on the
    next pass, or a script the owner edited is rewritten."""
    tenant_id, agent_id = await heal_test._account("rewrite")
    line_id = await _new_line(tenant_id, agent_id)
    await _record(tenant_id, line_id, "pip_draft")
    heal_test._writer(monkeypatch, None)

    assert await _pass(tenant_id, line_id) == "rewriting"
    assert await _proposal_ask(tenant_id, line_id) == {"rewrite": script_history.REWRITE_RULES}
    row = await heal_test._row(tenant_id, "inbound_lines", line_id)
    assert script_heal.REWRITE_KEY in row.script_heal_fixed

    await _clear_proposal(tenant_id, line_id)
    assert await _pass(tenant_id, line_id) != "rewriting", "asked once per holder"

    edited = await _new_line(tenant_id, agent_id)
    await _record(tenant_id, edited, "pip_draft", "owner")
    assert await _pass(tenant_id, edited) != "rewriting"
    assert await _proposal_ask(tenant_id, edited) is None


async def test_no_rewrite_is_asked_while_pip_is_off(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await heal_test._account("off", pip_on=False)
    line_id = await _new_line(tenant_id, agent_id)
    await _record(tenant_id, line_id, "pip_draft")
    heal_test._writer(monkeypatch, None)
    assert await _pass(tenant_id, line_id) == "skipped"
    assert await _proposal_ask(tenant_id, line_id) is None


async def _ask_rewrite(tenant_id: UUID, line_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        proposal = await lines.request_proposal(
            session,
            tenant_id=tenant_id,
            line_id=line_id,
            requested_by=None,
            ask={"rewrite": script_history.REWRITE_RULES},
        )
    return campaign_script._line(tenant_id, line_id, proposal.id)


async def test_a_written_rewrite_is_saved_as_a_pip_version_while_the_script_is_unchanged() -> None:
    """FAILS IF: the rewrite waits for a review nobody asked for, is saved over an owner's
    save made meanwhile, or is not kept as a version the Versions list can undo."""
    tenant_id, agent_id = await heal_test._account("save")
    line_id = await _new_line(tenant_id, agent_id)
    await _record(tenant_id, line_id, "pip_draft")
    holder = await _ask_rewrite(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        await campaign_script._save_if_rewrite(session, holder, REWRITTEN)
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
        newest = (await script_history.versions(session, "line", line_id))[0]
    assert line.script == REWRITTEN and line.proposal is None
    assert newest.author == "pip_draft" and newest.reason == script_history.REWRITE_REASON

    holder = await _ask_rewrite(tenant_id, line_id)
    owners = heal_test._script("Open the app and say which page shows.")
    async with tenant_session(tenant_id) as session:
        await lines.save_script(session, line_id, owners, author="owner")
    async with tenant_session(tenant_id) as session:
        await campaign_script._save_if_rewrite(session, holder, REWRITTEN)
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert line.script == owners and line.proposal is None


async def test_a_failed_rewrite_leaves_no_failure_on_the_owners_page() -> None:
    tenant_id, agent_id = await heal_test._account("fail")
    line_id = await _new_line(tenant_id, agent_id)
    holder = await _ask_rewrite(tenant_id, line_id)
    await campaign_script._fail(holder, "Pip could not write it.", reason="refused")
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert line.proposal is None


def test_a_rewrite_is_written_whole_not_as_an_edit() -> None:
    assert campaign_script._rewrite({"rewrite": script_history.REWRITE_RULES})
    assert not campaign_script._rewrite({"tone": "warm"})
