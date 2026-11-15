"""Pip's campaign script goes through what every Pip script does (D-992 with D-989, D-957).

1. A campaign's first script is written whole from the main task and materials, not as an
   edit of an empty script; a campaign that has a script gets an edit of the one the
   request was made from.
2. The call-mistake checks read the draft and their repair rewrites what they find, metered.
3. A draft the standby wrote is disclosed (D-127 G-6), and what the repairs leave is told.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the writer is replaced.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.script_lint import LintContext
from apps.api.campaigns import workspace
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import campaign_script
from apps.workers import script_proposal as proposal_worker
from calevate_shared.call_script import CallScript, ConversationStage
from sqlalchemy import text
from tests.conftest import create_org_with_receptionist

pytestmark = pytest.mark.rls

LINT = LintContext(promo=False)
MAIN_TASK = "Get every past customer to install the new app and open it once."
OPENING = "Hello, this is Asha from Sunrise Homes. Is now a good time?"
THREE_QUESTIONS = "What is your name? Which phone do you use? When can you install it?"
ONE_QUESTION = "Which phone do you use?"


def _stage(sid: str, line: str) -> ConversationStage:
    return ConversationStage(id=sid, name=sid.title(), instruction="Help them.", sounds_like=line)


def _script(*lines: str) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=OPENING,
        stages=[*(_stage(f"s{i}", line) for i, line in enumerate(lines)), _stage("close", "Thank you.")],
    )


async def _campaign(script: CallScript | None = None) -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Sunrise Homes",
        slug=f"cpw-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, campaign_id = UUID(str(created["id"])), uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, script) "
                "VALUES (:id, :t, :a, 'Install the app', 'service', CAST(:s AS jsonb))"
            ),
            {
                "id": campaign_id,
                "t": tenant_id,
                "a": created["agent_id"],
                "s": None if script is None else script.model_dump_json(),
            },
        )
        await workspace.save_main_task(session, campaign_id, MAIN_TASK)
        await workspace.add_material(
            session,
            tenant_id=tenant_id,
            campaign_id=campaign_id,
            kind="note",
            title="Offer",
            url=None,
            note="Tell them the first month is free.",
            kb_upload_id=None,
            created_by=None,
        )
    return tenant_id, campaign_id


def _answer(script: CallScript, disclosure: str | None = None) -> Any:
    return SimpleNamespace(
        script=script,
        capability=SimpleNamespace(disclosure=disclosure),
        usage=None,
        model="gemini-2.5-flash-lite",
        earlier=(),
        left_out=(),
    )


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    tenant_id: UUID,
    campaign_id: UUID,
    answers: list[Any],
) -> tuple[workspace.CampaignProposal, list[dict[str, Any]], list[str]]:
    async with tenant_session(tenant_id) as session:
        requested = await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None
        )
    calls: list[dict[str, Any]] = []
    metered: list[str] = []

    async def write(brief: Any, **kwargs: Any) -> Any:
        calls.append({"brief": brief, **kwargs})
        return answers[min(len(calls), len(answers)) - 1]

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LINT

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript) -> Any:
        return script, []

    async def meter_assist(_session: Any, **kwargs: Any) -> None:
        metered.append(kwargs["model"])

    async def meter_earlier(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(campaign_script, "draft_script", write)
    monkeypatch.setattr(proposal_worker, "draft_script", write)
    monkeypatch.setattr(proposal_worker, "lint_context_for", lint_context)
    monkeypatch.setattr(proposal_worker, "_opening_repaired", openings)
    monkeypatch.setattr(crm_assist, "meter_assist", meter_assist)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter_earlier)
    payload = {
        "tenant_id": str(tenant_id),
        "campaign_id": str(campaign_id),
        "proposal_id": str(requested.id),
    }
    assert await campaign_script.draft_campaign_script({}, payload) == "ready"
    async with tenant_session(tenant_id) as session:
        space = await workspace.read_workspace(session, campaign_id)
    assert space.proposal is not None and space.proposal.status == "ready"
    return space.proposal, calls, metered


async def test_a_first_script_is_written_whole_from_the_main_task_and_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a campaign with no script is sent to the writer as an edit of an empty
    script (no step plan, the edit's rules), or the main task and notes are not its brief."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign()
    proposal, calls, _ = await _run(
        monkeypatch, tenant_id, campaign_id, [_answer(_script(ONE_QUESTION))]
    )
    [first] = calls
    assert "edit_of" not in first
    assert MAIN_TASK in first["brief"].description
    assert "first month is free" in first["brief"].description
    assert proposal.base_script is None and proposal.script is not None


async def test_a_campaign_with_a_script_gets_an_edit_of_the_one_it_was_asked_from(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    base = _script(ONE_QUESTION)
    tenant_id, campaign_id = await _campaign(base)
    _, calls, _ = await _run(monkeypatch, tenant_id, campaign_id, [_answer(_script(ONE_QUESTION))])
    [first] = calls
    assert first["edit_of"] == base
    assert MAIN_TASK in first["change"] and "Keep anything already in the script" in first["change"]


async def test_the_call_mistake_checks_repair_the_draft_before_it_is_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: Pip's campaign script reaches the owner with a step that asks three
    questions in one turn (D-989), or the repair is not metered (hard rule 7)."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 2)
    tenant_id, campaign_id = await _campaign()
    proposal, calls, metered = await _run(
        monkeypatch,
        tenant_id,
        campaign_id,
        [_answer(_script(THREE_QUESTIONS)), _answer(_script(ONE_QUESTION))],
    )
    assert proposal.script is not None
    assert proposal.script.stages[0].sounds_like == ONE_QUESTION
    assert len(calls) == 2 and len(metered) == 2
    assert proposal.left_out == ()


async def test_a_standby_draft_is_disclosed_and_what_stays_unfixed_is_told(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a campaign script the standby wrote is offered without its disclosure
    (D-127 G-6), or a warning the repairs could not clear is dropped without a word."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign()
    proposal, _, _ = await _run(
        monkeypatch,
        tenant_id,
        campaign_id,
        [_answer(_script(THREE_QUESTIONS), disclosure="Written by our backup assistant.")],
    )
    assert proposal.disclosure == "Written by our backup assistant."
    assert [part.unfixed for part in proposal.left_out] == [True]
