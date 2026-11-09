"""A fix ("Fix them first") that takes a step's reworded instruction but keeps its "sounds like"
line must not build a step over the 600-character step detail.

`kept_to_paths` takes only the lines the check named from the written script. A step's
instruction and its "sounds like" line share one budget (`ConversationStage._detail_fits_a_step`),
so a longer instruction (the usual way a fix asks one more question) beside the line it kept
from the owner's script failed validation: the job crashed after the model was paid, the
spend never reached the ledger (hard rule 7) and the owner's screen waited on "drafting" until
the ten-minute stale note."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_builder, script_proposals
from apps.api.agents.script_lint import LintContext
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.workers import script_proposal as worker
from calevate_shared.call_script import STAGE_DETAIL_MAX, CallScript, ConversationStage
from tests.conftest import create_org_with_receptionist

LINE = "Signing up takes two minutes on the app, and the first season is free for every farmer."
#: Fits beside LINE (the owner's script), and does not once it is longer by the fix.
SHORT = "Explain how they can sign up. " * 15
LONG = "Explain how they can sign up and ask whether they use the app today. " * 8


def _script(instruction: str, line: str) -> CallScript:
    return CallScript(
        schema_version=2,
        stages=[
            ConversationStage(id="signup", name="Signup", instruction=instruction, sounds_like=line),
            ConversationStage(id="close", name="Close", instruction="Thank them and end the call."),
        ],
    )


BASE = _script(SHORT.strip(), LINE)
WRITTEN = _script(LONG.strip(), "")


def test_the_fixture_is_the_overflow() -> None:
    assert len(LONG.strip()) + len(LINE) > STAGE_DETAIL_MAX - 20
    assert len(LONG.strip()) <= STAGE_DETAIL_MAX


def test_a_longer_instruction_beside_the_kept_line_is_not_a_crash() -> None:
    """FAILS IF: `kept_to_paths` raises a validation error for a step whose instruction and
    "sounds like" line no longer fit together."""
    kept = script_proposals.kept_to_paths(WRITTEN, BASE, ["stages.0.instruction"])
    stage = kept.stages[0]
    # The written step fits as a whole, so its pair is taken together.
    assert stage.instruction == LONG.strip()
    assert stage.sounds_like == ""
    ConversationStage.model_validate(stage.model_dump(mode="json"))


def test_a_pair_that_cannot_fit_keeps_the_owners_step() -> None:
    """FAILS IF: a step that cannot hold the named line even with the written step's own
    pair (the owner's step is spoken word for word, so its detail is wrapped in "Say:") is
    built anyway, a crash, instead of left as the owner wrote it."""
    base = BASE.model_copy(
        update={"stages": [BASE.stages[0].model_copy(update={"mode": "say"}), BASE.stages[1]]}
    )
    longest = (LONG.strip() + " Ask for the village name and the crop they grow.")[:598]
    written = _script(longest, "")
    kept = script_proposals.kept_to_paths(written, base, ["stages.0.instruction"])
    assert kept.stages[0] == base.stages[0]


@pytest.mark.rls
async def test_the_job_stores_the_fix_and_meters_it(monkeypatch: pytest.MonkeyPatch) -> None:
    """FAILS IF: the job crashes after the model answered, leaving the proposal `drafting`
    and the paid draft with no meter row."""
    created = await create_org_with_receptionist(
        name="Rytu Khata",
        slug=f"fixfit-{uuid.uuid4().hex[:8]}",
        vertical_template="retail",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, agent_id = uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await script_builder.save_draft(session, agent_id, BASE)
        proposal = await script_proposals.request_proposal(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            mode="change",
            change="Fix only these problems the script check found.",
            answers={},
            requested_by=uuid.uuid4(),
            paths=["stages.0.instruction"],
        )
    metered: list[str] = []

    async def write(_brief: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(
            script=WRITTEN,
            capability=SimpleNamespace(disclosure=None),
            usage=None,
            model="gemini-2.5-flash-lite",
            earlier=(),
            left_out=(),
        )

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LintContext(collect=(), promo=False)

    async def meter_assist(_session: Any, **kwargs: Any) -> None:
        metered.append(kwargs["model"])

    async def meter_earlier(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(worker, "draft_script", write)
    monkeypatch.setattr(worker, "lint_context_for", lint_context)
    monkeypatch.setattr(crm_assist, "meter_assist", meter_assist)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter_earlier)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal.id),
    }
    assert await worker.draft_script_proposal({}, payload) == "ready"
    assert metered == ["gemini-2.5-flash-lite"]
    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.read_proposal(session, agent_id)
    assert stored is not None and stored.status == "ready"
