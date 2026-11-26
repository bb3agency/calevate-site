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
from typing import Any

import pytest
from apps.api.campaigns import workspace
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.workers import campaign_script, script_context
from apps.workers.script_assist import ScriptBrief
from calevate_shared.call_script import CallScript
from sqlalchemy import text
from tests.campaign_script_writer_2026_11_15_test import (
    MAIN_TASK,
    ONE_QUESTION,
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
        inputs.asked_from,
        inputs.words,
        inputs.brief.user_message(),
        inputs.brief.collect,
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
    at_creation = await script_context.holder_context(tenant_id, "campaign", campaign_id)
    part_ask = at_creation.part
    async with tenant_session(tenant_id) as session:
        assert await workspace.clear_proposal(session, campaign_id, made.id)
        await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None
        )
    later = await script_context.holder_context(tenant_id, "campaign", campaign_id)

    assert _seen(at_creation) == _seen(later) and part_ask is None
    assert at_creation.main_task == MAIN_TASK
    assert [name for name, _words in at_creation.words] == ["Offer"]
    assert "Why these people are called: They asked about plots last month" in (
        at_creation.situation
    )
    # A placed call has the contact's name, so its steps never ask it (`JobDetails.placed`).
    placed = ASKED[1:]
    assert at_creation.brief.collect == placed
    assert "Details to collect: " + "; ".join(placed) in (at_creation.brief.user_message())


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
    at_creation = await script_context.holder_context(tenant_id, "line", line_id)
    async with tenant_session(tenant_id) as session:
        await lines.clear_proposal(session, line_id, made.id)
        await lines.request_proposal(
            session, tenant_id=tenant_id, line_id=line_id, requested_by=None
        )
    later = await script_context.holder_context(tenant_id, "line", line_id)

    assert _seen(at_creation) == _seen(later)
    assert at_creation.brief.collect == ASKED
    assert at_creation.brief.direction in ("inbound", "both")


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
