"""A script written as its campaign or line is made is as good as one asked for later (D-1031).

1. Parity of inputs: a draft asked for at creation (the first run's `auto_save`) and one asked
   for later from the page are written from the same main task, sources, campaign settings
   and details, because the job reads them when it runs.
2. The holder's own "What it notes" reaches the writer as the details to collect: since D-1028
   the agent's brief carries none, so without it no step planned where they are asked.
3. A first script is edited once with the same ask, as a later press of Generate edits it; a
   refused refining edit keeps the paid first draft.
4. The writer's ask carries the rules the research names (docs/evidence/
   script-quality-2026-11-22/RESEARCH.md).

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called.
"""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.script_lint import LintContext
from apps.api.campaigns import workspace
from apps.api.core.errors import ProblemError
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.workers import campaign_script
from apps.workers import campaign_script_ask as ask
from apps.workers import script_proposal as proposal_worker
from apps.workers.script_assist import ScriptBrief
from calevate_shared.call_script import CallScript
from sqlalchemy import text
from tests.campaign_script_writer_2026_11_15_test import (
    MAIN_TASK,
    ONE_QUESTION,
    _answer,
    _campaign,
    _script,
)

pytestmark = pytest.mark.rls

FIELDS = [
    {"key": "visit_day", "label": "Visit day", "type": "string", "reason": "to book the visit"},
    {"key": "budget", "label": "Budget", "type": "string"},
]
#: What the writer is told the calls ask: the core details a call asks, each with when, around
#: the holder's own (`script_builder.job_details`).
ASKED = (
    "Name: only if not known",
    "Visit day: to book the visit",
    "Budget",
    "Preferred time: only if they want a call later",
    "Other number: only if a call back is agreed",
)


def _seen(inputs: Any) -> tuple[Any, ...]:
    """What the writer is handed, without the account's model handle."""
    return (
        inputs.agent_id,
        inputs.main_task,
        inputs.base,
        inputs.notes,
        inputs.words,
        inputs.context.user_message(),
        inputs.context.collect,
        inputs.tone,
        inputs.instruction,
        inputs.budget,
        inputs.situation,
    )


async def test_a_campaign_draft_asked_for_at_creation_reads_what_a_later_press_reads() -> None:
    """FAILS IF: a draft asked for as the campaign is made is written from less than one asked
    for later: its main task, picked sources, campaign settings or details."""
    tenant_id, campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE campaigns SET purpose = 'They asked about plots last month', "
                "extraction_fields = CAST(:f AS jsonb) WHERE id = :c"
            ),
            {"f": json.dumps(FIELDS), "c": campaign_id},
        )
        made = await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None, auto_save=True
        )
    at_creation, part_ask = await campaign_script.campaign_inputs(tenant_id, campaign_id)
    async with tenant_session(tenant_id) as session:
        assert await workspace.clear_proposal(session, campaign_id, made.id)
        await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None
        )
    later, _ = await campaign_script.campaign_inputs(tenant_id, campaign_id)

    assert _seen(at_creation) == _seen(later) and part_ask is None
    assert at_creation.main_task == MAIN_TASK
    assert [name for name, _words in at_creation.words] == ["Offer"]
    assert "Why these people are called: They asked about plots last month" in (
        at_creation.situation
    )
    assert at_creation.context.collect == ASKED
    assert "Details to collect: " + "; ".join(ASKED) in (at_creation.context.user_message())


async def test_a_lines_draft_asked_for_at_creation_reads_what_a_later_press_reads() -> None:
    tenant_id, campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT agent_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, main_task=MAIN_TASK, created_by=None
        )
        await session.execute(
            text("UPDATE inbound_lines SET extraction_fields = CAST(:f AS jsonb) WHERE id = :l"),
            {"f": json.dumps(FIELDS), "l": line_id},
        )
        made = await lines.request_proposal(
            session, tenant_id=tenant_id, line_id=line_id, requested_by=None, auto_save=True
        )
    at_creation = await campaign_script.line_inputs(tenant_id, line_id)
    async with tenant_session(tenant_id) as session:
        await lines.clear_proposal(session, line_id, made.id)
        await lines.request_proposal(
            session, tenant_id=tenant_id, line_id=line_id, requested_by=None
        )
    later = await campaign_script.line_inputs(tenant_id, line_id)

    assert _seen(at_creation) == _seen(later)
    assert at_creation.context.collect == ASKED
    assert at_creation.context.direction in ("inbound", "both")


async def _write_first(
    monkeypatch: pytest.MonkeyPatch, tenant_id: UUID, campaign_id: UUID, *, refuse_refine: bool
) -> tuple[workspace.CampaignProposal, list[dict[str, Any]], list[str]]:
    async with tenant_session(tenant_id) as session:
        requested = await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None
        )
    first, refined = _script(ONE_QUESTION), _script("Which day suits you?")
    calls: list[dict[str, Any]] = []
    spent: list[str] = []

    async def write(brief: Any, **kwargs: Any) -> Any:
        calls.append({"brief": brief, **kwargs})
        if "edit_of" not in kwargs:
            return _answer(first)
        if refuse_refine:
            raise ProblemError.business_rule("ai_unavailable", "Not now.")
        return _answer(refined)

    async def review_pass(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            value=ask.Review(),
            capability=SimpleNamespace(disclosure=None),
            usage=None,
            model="m",
            earlier=(),
        )

    async def size(*_args: Any) -> None:
        return None

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LintContext(promo=False)

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript, **_kw: Any) -> Any:
        return script, []

    async def meter_assist(_session: Any, **kwargs: Any) -> None:
        spent.append("assist")

    async def meter_refusal(_session: Any, **kwargs: Any) -> None:
        spent.append("refusal")

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    monkeypatch.setattr(campaign_script, "draft_script", write)
    monkeypatch.setattr(campaign_script, "ask_json", review_pass)
    monkeypatch.setattr(campaign_script, "_size", size)
    monkeypatch.setattr(proposal_worker, "draft_script", write)
    monkeypatch.setattr(proposal_worker, "lint_context_for", lint_context)
    monkeypatch.setattr(proposal_worker, "_opening_repaired", openings)
    monkeypatch.setattr(crm_assist, "meter_assist", meter_assist)
    monkeypatch.setattr(crm_assist, "meter_refusal", meter_refusal)
    monkeypatch.setattr(crm_assist, "meter_earlier", nothing)
    payload = {
        "tenant_id": str(tenant_id),
        "campaign_id": str(campaign_id),
        "proposal_id": str(requested.id),
    }
    assert await campaign_script.draft_campaign_script({}, payload) == "ready"
    async with tenant_session(tenant_id) as session:
        space = await workspace.read_workspace(session, campaign_id)
    assert space.proposal is not None and space.proposal.status == "ready"
    return space.proposal, calls, spent


async def test_a_first_script_is_refined_with_the_same_ask_a_later_press_sends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a script written as the campaign is made is one pass while a later press of
    Generate is an edit of it with the ask again, so the later one reads better."""
    tenant_id, campaign_id = await _campaign()
    proposal, calls, spent = await _write_first(
        monkeypatch, tenant_id, campaign_id, refuse_refine=False
    )
    whole, refine = calls
    assert "edit_of" not in whole
    assert refine["edit_of"] == _script(ONE_QUESTION)
    # The refining edit carries the whole ask and the campaign's own words, as a press does.
    assert refine["change"].startswith(ask.CAMPAIGN_ASK + ask.REFINE_TAIL)
    assert ask.EDIT_TAIL not in refine["change"]
    assert MAIN_TASK in refine["change"] and "first month is free" in refine["change"]
    assert refine["repair_rounds"] == get_settings().campaign_script_repair_rounds
    assert refine["standby_after_answer"] is False
    assert proposal.script is not None
    assert proposal.script.stages[0].sounds_like == "Which day suits you?"
    assert spent.count("assist") == 3, "the draft, the refining edit and the review"


async def test_a_refused_refining_edit_keeps_the_paid_first_draft(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, campaign_id = await _campaign()
    proposal, calls, spent = await _write_first(
        monkeypatch, tenant_id, campaign_id, refuse_refine=True
    )
    assert len(calls) == 2
    assert proposal.script is not None
    assert proposal.script.stages[0].sounds_like == ONE_QUESTION
    assert "refusal" in spent


def test_the_ask_places_the_details_and_keeps_instructions_short() -> None:
    """FAILS IF: the writer is no longer told to ask each detail where the call reaches it
    and never what the call knows, or to keep step instructions short and free of the
    speaking rules the platform adds on every call."""
    for holder_ask in (ask.CAMPAIGN_ASK, ask.LINE_ASK):
        assert ask.DETAILS_RULE in holder_ask and ask.CONCISE_RULE in holder_ask
    assert "Never ask for what the call already knows" in ask.DETAILS_RULE
    assert "read back once" in ask.DETAILS_RULE
    assert "Say each thing once" in ask.CONCISE_RULE


def test_the_refining_edit_and_the_closing_reminder_reach_the_change() -> None:
    documents = "DOCUMENTS:\n[Offer]\nThe first month is free.\n"
    refine = ask.campaign_change("Book visits.", "", documents, edit=True, refine=True)
    assert refine.startswith(ask.CAMPAIGN_ASK + ask.REFINE_TAIL)
    assert ask.EDIT_TAIL not in refine
    # The task is said again after the long sources, never before them.
    assert refine.endswith(ask.TASK_REMINDER)
    assert refine.index(documents) < refine.index(ask.TASK_REMINDER)
    edit = ask.campaign_change("Book visits.", "", documents, edit=True)
    assert edit.startswith(ask.CAMPAIGN_ASK + ask.EDIT_TAIL) and ask.REFINE_TAIL not in edit
    # No sources: nothing comes between the ask and the end, so no reminder.
    assert ask.TASK_REMINDER not in ask.campaign_change("Book.", "", "", edit=False)
    # A one-part rewrite keeps its own ask alone.
    part = ask.PART_ASK.format(part="Opening line", language="Telugu")
    assert ask.TASK_REMINDER not in ask.campaign_change(
        "Book.", "", documents, edit=True, part_ask=part
    )


def test_the_details_to_collect_reach_the_writers_brief() -> None:
    brief = ScriptBrief(business_name="Sunrise Homes", collect=("Visit day", "Budget"))
    assert "Details to collect: Visit day; Budget" in brief.user_message()


async def test_a_first_run_draft_never_replaces_a_script_the_owner_saved_meanwhile() -> None:
    """FAILS IF: the first run's `auto_save` reads "the campaign has no script" without the
    row lock, so an owner's save that commits between that read and Pip's save is
    overwritten by the draft."""
    tenant_id, campaign_id = await _campaign()
    async with tenant_session(tenant_id) as session:
        made = await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None, auto_save=True
        )
    holder = campaign_script._campaign(tenant_id, campaign_id, made.id)
    owners, pips = _script("Which day suits you?"), _script(ONE_QUESTION)
    owner_holds_lock, release = asyncio.Event(), asyncio.Event()

    async def owner_saves() -> None:
        async with tenant_session(tenant_id) as session:
            await workspace.save_script(session, campaign_id, owners, author="owner")
            owner_holds_lock.set()
            await release.wait()

    async def pip_saves() -> None:
        async with tenant_session(tenant_id) as session:
            await campaign_script._save_if_asked(session, holder, pips)

    owner = asyncio.create_task(owner_saves())
    await owner_holds_lock.wait()
    pip = asyncio.create_task(pip_saves())
    await asyncio.sleep(0.5)
    release.set()
    await asyncio.gather(owner, pip)

    async with tenant_session(tenant_id) as session:
        saved = (
            await session.execute(
                text("SELECT script FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
    assert CallScript.model_validate(saved) == owners
