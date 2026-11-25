"""A first script is held to the main task's numbered list as exactly as to an owner's own
step list (founder, 26 Nov 2026).

A main task written as plain numbered sentences ("1. Find out whether it is installed ...")
gives `owner_plan` no names or outcomes, so the first draft at creation had only the items as
guidance and no check. One small pass now reads the list as steps, one per item:

1. The answer becomes a plan only when it keeps one step per item, in order.
2. A first draft is written and checked against that plan, and the owner reads how Pip read
   their main task beside the step outcomes; the main task itself is unchanged.
3. An answer that changes the count, or that cannot be read, leaves the draft as it was.
4. No pass runs when the main task already lays out a plan, or for an edit of a script.

The model is never called: the writer and the reading are replaced.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.owner_plan import numbered_items, owner_plan
from apps.api.campaigns import workspace
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.workers import campaign_script
from apps.workers import script_proposal as proposal_worker
from apps.workers.campaign_script_ask import (
    PLAN_HEAD,
    TASK_STEPS_INSTRUCTION,
    Review,
    task_steps_note,
    task_steps_text,
)
from calevate_shared.call_script import CallScript, ConversationStage
from scripts import eval_script_writer as ev
from tests.campaign_script_writer_2026_11_15_test import LINT, _answer, _campaign

RYTU = ev.load_cases(["rytu_khata_install"])[0]

#: Six steps for the case's six numbered items, in their order.
SIX: list[dict[str, Any]] = [
    {
        "name": "Check the app",
        "does": "Ask whether it is installed as an app; if not, explain why the app is better.",
        "outcome": "They say whether the app is installed.",
        "ways_out": [{"when": "Already installed", "to": "Set up farms"}],
    },
    {
        "name": "Install the app",
        "does": "Help them install it on Android or iPhone, screen by screen, and set the "
        "language.",
        "outcome": "The app is installed in their language.",
        "ways_out": [{"when": "Cannot install it", "to": "call_back"}],
    },
    {
        "name": "Open the dashboard",
        "does": "Confirm it is installed and take them to the dashboard.",
        "outcome": "They see the dashboard.",
        "ways_out": [],
    },
    {
        "name": "Set up farms",
        "does": "Help them set up their farms.",
        "outcome": "Their farm is added.",
        "ways_out": [],
    },
    {
        "name": "Enter expenses",
        "does": "Help them enter their expenses.",
        "outcome": "An expense is entered.",
        "ways_out": [],
    },
    {
        "name": "Enter sales",
        "does": "Help them enter their sales and show the dashboard totals.",
        "outcome": "A sale is entered and they saw the totals.",
        "ways_out": [],
    },
]


def test_the_answer_becomes_a_plan_with_one_step_per_item_and_its_ways_out() -> None:
    items = numbered_items(RYTU.main_task)
    assert len(items) == 6 and items[0].startswith("Find out whether it is installed")
    # Plain numbered sentences are not a plan of their own.
    assert owner_plan(RYTU.main_task) is None
    text = task_steps_text({"steps": SIX})
    assert text is not None
    plan = owner_plan(text)
    assert plan is not None
    assert [s.name for s in plan.steps] == [step["name"] for step in SIX]
    assert plan.steps[0].outcome == "They say whether the app is installed."
    assert [(b.when, b.goes_to) for b in plan.steps[0].branches] == [
        ("Already installed", "Set up farms")
    ]
    assert [(b.when, b.goes_to) for b in plan.steps[1].branches] == [
        ("Cannot install it", "call_back")
    ]
    assert task_steps_note(plan).startswith(
        "Pip read your main task as these steps: 1. Check the app: They say whether"
    )
    # A colon in the model's words cannot start a label of its own.
    odd = task_steps_text({"steps": [{**SIX[0], "does": "Ask: is it installed?"}, *SIX[1:]]})
    assert odd is not None and len(owner_plan(odd).steps) == 6  # type: ignore[union-attr]
    assert task_steps_text({"steps": []}) is None
    assert task_steps_text({"steps": [{"name": "A", "does": "", "outcome": "x"}]}) is None


async def _first_draft(
    monkeypatch: pytest.MonkeyPatch,
    *,
    main_task: str,
    reading: dict[str, Any] | None,
    script: CallScript | None = None,
    drafted: CallScript | None = None,
) -> tuple[workspace.CampaignProposal, list[dict[str, Any]], list[str]]:
    """Run the campaign job on a campaign with `main_task` (and `script`, for an edit), the
    writer answering `drafted` and the main task's reading answering `reading`; the proposal,
    the writer's calls and the instruction of every other pass asked."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign(script)
    async with tenant_session(tenant_id) as session:
        await workspace.save_main_task(session, campaign_id, main_task)
        requested = await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None
        )
    calls: list[dict[str, Any]] = []
    passes: list[str] = []
    answer = drafted or CallScript(
        schema_version=2,
        stages=[ConversationStage(id="s1", name="Talk", instruction="Talk to them.")],
    )

    async def write(brief: Any, **kwargs: Any) -> Any:
        calls.append({"brief": brief, **kwargs})
        return _answer(answer)

    async def asked(request: str, instruction: str, *, parse: Any, **_kw: Any) -> Any:
        passes.append(instruction)
        value = parse(reading) if instruction == TASK_STEPS_INSTRUCTION else Review()
        return SimpleNamespace(
            value=value,
            capability=SimpleNamespace(disclosure=None),
            usage=None,
            model="gemini-test",
            earlier=(),
        )

    async def lint_context(*_args: Any, **_kwargs: Any) -> Any:
        return LINT

    async def openings(_t: UUID, _a: UUID, _p: Any, drafted: CallScript, **_kw: Any) -> Any:
        return drafted, []

    async def quiet(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(campaign_script, "draft_script", write)
    monkeypatch.setattr(campaign_script, "ask_json", asked)
    monkeypatch.setattr(proposal_worker, "draft_script", write)
    monkeypatch.setattr(proposal_worker, "lint_context_for", lint_context)
    monkeypatch.setattr(proposal_worker, "_opening_repaired", openings)
    monkeypatch.setattr(campaign_script.crm_assist, "meter_assist", quiet)
    monkeypatch.setattr(campaign_script.crm_assist, "meter_earlier", quiet)
    monkeypatch.setattr(campaign_script.crm_assist, "meter_refusal", quiet)
    payload = {
        "tenant_id": str(tenant_id),
        "campaign_id": str(campaign_id),
        "proposal_id": str(requested.id),
    }
    assert await campaign_script.draft_campaign_script({}, payload) == "ready"
    async with tenant_session(tenant_id) as session:
        space = await workspace.read_workspace(session, campaign_id)
        assert space.main_task == main_task
    assert space.proposal is not None
    return space.proposal, calls, passes


@pytest.mark.rls
async def test_a_numbered_main_task_is_read_as_steps_and_the_first_draft_held_to_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a first draft from a plain numbered main task is not given the plan read
    from it, a draft that departs from it is not named, or the owner is not shown how Pip read
    their main task."""
    proposal, calls, passes = await _first_draft(
        monkeypatch, main_task=RYTU.main_task, reading={"steps": SIX}
    )
    assert passes.count(TASK_STEPS_INSTRUCTION) == 1
    plan = owner_plan(task_steps_text({"steps": SIX}))
    assert all(call["brief"].owner_plan == plan for call in calls)
    assert PLAN_HEAD in calls[0]["brief"].description
    assert "THE MAIN TASK'S ITEMS" not in calls[0]["brief"].description
    # The one-step draft departs from the six steps, and is told so.
    assert any('"Install the app" is missing' in part.rule for part in proposal.left_out)
    assert proposal.why["step_outcomes"].startswith("Pip read your main task as these steps:")


@pytest.mark.rls
@pytest.mark.parametrize(
    "reading",
    [{"steps": SIX[:5]}, {"steps": [*SIX, SIX[0]]}, {"nothing": True}],
    ids=["fewer", "more", "unreadable"],
)
async def test_a_reading_that_does_not_keep_the_count_leaves_the_draft_as_it_was(
    monkeypatch: pytest.MonkeyPatch, reading: dict[str, Any]
) -> None:
    proposal, calls, _ = await _first_draft(monkeypatch, main_task=RYTU.main_task, reading=reading)
    assert calls[0]["brief"].owner_plan is None
    assert "THE MAIN TASK'S ITEMS" in calls[0]["brief"].description
    assert "step_outcomes" not in proposal.why


@pytest.mark.rls
async def test_no_reading_for_a_main_task_with_its_own_plan_or_for_an_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a main task that already lays out the steps, or an edit of an existing
    script with no plan in the request, spends a pass reading the main task."""
    own = (
        "1. Welcome: say why we call. Outcome: They agreed to talk.\n"
        "2. Close: thank them and end the call. Outcome: The call is finished."
    )
    _, calls, passes = await _first_draft(monkeypatch, main_task=own, reading={"steps": SIX})
    assert TASK_STEPS_INSTRUCTION not in passes
    assert calls[0]["brief"].owner_plan == owner_plan(own)

    script = CallScript(
        schema_version=2,
        stages=[ConversationStage(id="s1", name="Talk", instruction="Talk to them.")],
    )
    _, calls, passes = await _first_draft(
        monkeypatch, main_task=RYTU.main_task, reading={"steps": SIX}, script=script
    )
    assert TASK_STEPS_INSTRUCTION not in passes
    assert calls[0]["edit_of"] == script and calls[0]["brief"].owner_plan is None
