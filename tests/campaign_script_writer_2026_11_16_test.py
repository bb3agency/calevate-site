"""Pip's campaign script, end to end through the job (D-1004).

1. The owner's tone and instruction reach the writer, and the edit is checked against the
   campaign's own sources (a figure from them is not "a figure no fact gives").
2. The review pass stores one "why" per part Pip wrote, turns a claim no source backs into a
   warning on its part, and is metered with the draft. Its failure keeps the draft.
3. A draft too long for the agent's box is shortened once, never touching the openings, and
   one still too long is offered with a warning rather than refused at Keep.
4. The route stores the tone and instruction, keeps the typed text out of the audit row and
   refuses a tone it does not offer.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the writer and the review are replaced.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents.prompt_size import PromptSize, SizePart
from apps.api.agents.script_lint import LintContext
from apps.api.campaigns import workspace
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.session import tenant_session
from apps.api.main import app
from apps.workers import campaign_script
from apps.workers import script_proposal as proposal_worker
from apps.workers.campaign_script_ask import SHORTEN_ASK, Review
from calevate_shared.call_script import CallScript
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.agent_starters_test import _tenant
from tests.campaign_script_writer_2026_11_15_test import (
    MAIN_TASK,
    ONE_QUESTION,
    _answer,
    _campaign,
    _script,
)

pytestmark = pytest.mark.rls

LINT = LintContext(promo=False)


def _review(notes: dict[str, str], unsourced: dict[str, str] | None = None) -> Any:
    return SimpleNamespace(
        value=Review(notes=notes, unsourced=unsourced or {}),
        capability=SimpleNamespace(disclosure=None),
        usage=None,
        model="gemini-2.5-flash-lite",
        earlier=(),
    )


def _size(over: int) -> PromptSize:
    return PromptSize(
        total=20_000 + over,
        limit=20_000,
        layers=(SizePart("client_script", "Your script", 9_000),),
        script_parts=(SizePart("[CONVERSATION]", "Steps", 6_000),),
    )


async def _run(
    monkeypatch: pytest.MonkeyPatch,
    tenant_id: UUID,
    campaign_id: UUID,
    answers: list[Any],
    *,
    review: Any = None,
    ask: dict[str, str] | None = None,
    sizes: list[PromptSize | None] | None = None,
) -> tuple[workspace.CampaignProposal, list[dict[str, Any]], list[str], list[str]]:
    async with tenant_session(tenant_id) as session:
        requested = await workspace.request_proposal(
            session, tenant_id=tenant_id, campaign_id=campaign_id, requested_by=None, ask=ask
        )
    calls: list[dict[str, Any]] = []
    metered: list[str] = []
    reviewed: list[str] = []

    async def write(brief: Any, **kwargs: Any) -> Any:
        calls.append({"brief": brief, **kwargs})
        return answers[min(len(calls), len(answers)) - 1]

    async def review_pass(message: str, _instruction: str, **_kwargs: Any) -> Any:
        reviewed.append(message)
        if isinstance(review, BaseException):
            raise review
        return review if review is not None else _review({})

    measured = list(sizes or [])

    async def size(_t: UUID, _a: UUID, _script: CallScript) -> PromptSize | None:
        return measured.pop(0) if measured else None

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LINT

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript) -> Any:
        return script, []

    async def meter_assist(_session: Any, **kwargs: Any) -> None:
        metered.append(kwargs["model"])

    async def meter_earlier(_session: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(campaign_script, "draft_script", write)
    monkeypatch.setattr(campaign_script, "ask_json", review_pass)
    monkeypatch.setattr(campaign_script, "_size", size)
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
    return space.proposal, calls, metered, reviewed


async def test_the_tone_and_instruction_reach_the_writer_and_the_sources_ground_an_edit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the owner's choice is dropped, or an edit is checked without the campaign's
    own sources, so a figure they give reads as invented and costs a repair."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign(_script(ONE_QUESTION))
    _, calls, _, _ = await _run(
        monkeypatch,
        tenant_id,
        campaign_id,
        [_answer(_script(ONE_QUESTION))],
        ask={"tone": "brief", "instruction": "Make the opening warmer."},
    )
    [first] = calls
    assert "TONE: every line the agent says is short and direct" in first["change"]
    assert "THE OWNER ASKS: Make the opening warmer." in first["change"]
    assert "Make the opening warmer." in first["owners_words"]
    assert "first month is free" in first["brief"].lint_context().facts
    assert MAIN_TASK in first["brief"].lint_context().facts


async def test_an_inbound_lines_draft_reads_the_tone_and_instruction_it_was_asked_with(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an Inbound line's draft drops what the owner asked for, so Pip's chat
    request (`copilot.script_actions.script_draft`) writes a draft that ignores it."""
    from apps.api.inbound import lines

    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign(_script(ONE_QUESTION))
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(
                text("SELECT agent_id FROM campaigns WHERE id = :c"), {"c": campaign_id}
            )
        ).scalar_one()
        line_id = await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Front desk",
            main_task=MAIN_TASK,
            script=_script(ONE_QUESTION),
            created_by=None,
        )
        requested = await lines.request_proposal(
            session,
            tenant_id=tenant_id,
            line_id=line_id,
            requested_by=None,
            ask={"tone": "warm", "instruction": "Ask their name before anything else."},
        )
    calls: list[dict[str, Any]] = []

    async def write(brief: Any, **kwargs: Any) -> Any:
        calls.append({"brief": brief, **kwargs})
        return _answer(_script(ONE_QUESTION))

    async def review_pass(*_args: Any, **_kwargs: Any) -> Any:
        return _review({})

    async def size(*_args: Any) -> PromptSize | None:
        return None

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LINT

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript) -> Any:
        return script, []

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(campaign_script, "draft_script", write)
    monkeypatch.setattr(campaign_script, "ask_json", review_pass)
    monkeypatch.setattr(campaign_script, "_size", size)
    monkeypatch.setattr(proposal_worker, "draft_script", write)
    monkeypatch.setattr(proposal_worker, "lint_context_for", lint_context)
    monkeypatch.setattr(proposal_worker, "_opening_repaired", openings)
    monkeypatch.setattr(crm_assist, "meter_assist", nothing)
    monkeypatch.setattr(crm_assist, "meter_earlier", nothing)
    payload = {
        "tenant_id": str(tenant_id),
        "line_id": str(line_id),
        "proposal_id": str(requested.id),
    }
    assert await campaign_script.draft_line_script({}, payload) == "ready"
    [first] = calls
    assert "TONE: every line the agent says is friendly and warm" in first["change"]
    assert "THE OWNER ASKS: Ask their name before anything else." in first["change"]


async def test_the_review_writes_why_notes_and_warns_of_an_unsourced_claim(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign()
    proposal, _, metered, reviewed = await _run(
        monkeypatch,
        tenant_id,
        campaign_id,
        [_answer(_script(ONE_QUESTION))],
        review=_review(
            {"opening_line": "Says who calls first.", "stages.s0": "Asks what the task needs."},
            {"stages.s0": "a free gift"},
        ),
    )
    assert proposal.why == {
        "opening_line": "Says who calls first.",
        "stages.s0": "Asks what the task needs.",
    }
    [warning] = [part for part in proposal.left_out if part.part == "stages.s0"]
    assert warning.unfixed and "a free gift" in warning.rule and warning.name == "S0"
    # The review read what the script was written from, and was paid for with the draft.
    [message] = reviewed
    assert MAIN_TASK in message and "first month is free" in message
    assert "first year is free" not in message
    assert len(metered) == 2


async def test_a_review_that_fails_keeps_the_draft_without_notes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign()
    proposal, _, metered, _ = await _run(
        monkeypatch,
        tenant_id,
        campaign_id,
        [_answer(_script(ONE_QUESTION))],
        review=RuntimeError("the review leg broke"),
    )
    assert proposal.script is not None and proposal.why == {}
    assert len(metered) == 1


async def test_a_draft_too_long_is_shortened_once_and_its_openings_never_change(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a draft that would be refused at Keep is offered as it is, or the shortening
    pass rewrites the line the call opens with (hard rule 5)."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign()
    long = _script(ONE_QUESTION)
    short = _script(ONE_QUESTION).model_copy(update={"opening_line": "A different opening?"})
    proposal, calls, metered, _ = await _run(
        monkeypatch,
        tenant_id,
        campaign_id,
        [_answer(long), _answer(short)],
        # The room at the start, the draft, then the script as offered.
        sizes=[None, _size(1_200), _size(0)],
    )
    assert len(calls) == 2
    assert calls[1]["edit_of"] == long
    assert calls[1]["change"] == SHORTEN_ASK.format(over=1_200, parts="Steps")
    assert proposal.script is not None
    assert proposal.script.opening_line == long.opening_line
    assert not [part for part in proposal.left_out if part.part == "script"]
    # The draft, the shortening and the review: each paid for.
    assert len(metered) == 3


async def test_a_draft_still_too_long_is_offered_with_a_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    tenant_id, campaign_id = await _campaign()
    proposal, _, _, _ = await _run(
        monkeypatch,
        tenant_id,
        campaign_id,
        [_answer(_script(ONE_QUESTION))],
        sizes=[None, _size(800), _size(300)],
    )
    [warning] = [part for part in proposal.left_out if part.part == "script"]
    assert warning.unfixed and "300 characters" in warning.rule and "Steps" in warning.rule


async def _route_campaign() -> tuple[UUID, UUID, str]:
    tenant_id, token = await _tenant("real_estate", "Sunrise Homes")
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (
            await session.execute(text("SELECT id FROM agents ORDER BY created_at LIMIT 1"))
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification) "
                "VALUES (:id, :t, :a, 'Visits', 'service')"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id},
        )
        await workspace.save_main_task(session, campaign_id, MAIN_TASK)
    return tenant_id, campaign_id, token


async def _post(token: str, campaign_id: UUID, body: dict[str, Any]) -> Any:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        return await http.post(
            f"/v1/campaigns/{campaign_id}/script/proposal",
            json=body,
            headers={"Authorization": f"Bearer {token}"},
        )


async def test_the_route_stores_the_ask_and_keeps_the_typed_words_out_of_the_audit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.campaigns import workspace_routes

    summaries: list[dict[str, Any]] = []
    written = workspace_routes.write_audit

    async def write_audit(session: Any, **kwargs: Any) -> Any:
        summaries.append(kwargs.get("summary") or {})
        return await written(session, **kwargs)

    monkeypatch.setattr(workspace_routes, "write_audit", write_audit)
    tenant_id, campaign_id, token = await _route_campaign()
    refused = await _post(token, campaign_id, {"tone": "shouty"})
    assert refused.status_code == 422, refused.text
    too_long = await _post(token, campaign_id, {"instruction": "x" * 1001})
    assert too_long.status_code == 422, too_long.text
    assert too_long.json()["detail"] == "Keep the note for Pip to 1,000 characters or fewer."
    response = await _post(
        token, campaign_id, {"tone": "warm", "instruction": "  Say   our name slowly. "}
    )
    assert response.status_code == 202, response.text
    assert response.json()["why"] == {}
    async with tenant_session(tenant_id) as session:
        asked = (
            await session.execute(
                text("SELECT script_proposal->'ask' FROM campaigns WHERE id = :c"),
                {"c": campaign_id},
            )
        ).scalar_one()
    assert asked == {"tone": "warm", "instruction": "Say our name slowly."}
    [audit] = summaries
    assert audit["tone"] == "warm" and audit["instructed"] is True
    assert "slowly" not in str(audit)
