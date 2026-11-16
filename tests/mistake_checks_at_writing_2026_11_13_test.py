"""The call-mistake checks run before any call can hear a mistake (D-989, founder, 13 Nov
2026: "why cant we solve this problem from the start?").

1. When Pip writes or changes a script (`script_proposal.finish_written`, every writer's
   tail), every kind's check reads the draft and the writer's repair round rewrites the
   lines it finds; what is still found is told to the owner.
2. `POST .../script/check` shows them as their own group, never a block.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the writer is replaced, as the D-985 tests do.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import script_builder, script_proposals
from apps.api.agents.mistake_lints import fixable_findings, script_mistakes
from apps.api.agents.script_lint import LintContext, script_problems
from apps.api.core.settings import get_settings
from apps.api.db.session import tenant_session
from apps.api.healer import notices
from apps.api.main import app
from apps.api.ops.config_catalog import FIELD_META
from apps.workers import script_proposal as worker
from calevate_shared.call_script import CallScript, ConversationStage
from calevate_shared.opening_notices import OpeningNotices
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.a2p_declaration_test import _org_headers
from tests.conftest import create_org_with_receptionist

LINT = LintContext(promo=False)
OPENING = "Namaste, this is Asha from Sunrise Homes. How can I help?"
THREE_QUESTIONS = "What is your name? Which area do you live in? When can you visit?"
ONE_QUESTION = "Which area do you live in?"
THIRD_PERSON = "The caller's number is saved now."


def _stage(sid: str, line: str, instruction: str = "Help them.") -> ConversationStage:
    return ConversationStage(id=sid, name=sid.title(), instruction=instruction, sounds_like=line)


def _script(*lines: str, opening: str = OPENING) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=opening,
        stages=[
            *(_stage(f"s{i}", line) for i, line in enumerate(lines)),
            _stage("close", "Thank you, have a good day.", "Thank them and end the call."),
        ],
    )


# --- the checks ---------------------------------------------------------------------------------


def test_the_founders_three_questions_are_a_mistake_finding() -> None:
    found = script_mistakes(_script(THREE_QUESTIONS), LINT)
    assert [p.partition(": ")[0] for p in found] == ["stages.0.sounds_like"]
    assert script_mistakes(_script(ONE_QUESTION), LINT) == []


def test_the_opening_and_its_notices_are_never_a_writing_time_finding() -> None:
    """FAILS IF: a check's finding on the opening (where the notices are woven, D-971) is
    handed to the writer, which would rewrite the line the notice writer owns."""
    claim = _script(ONE_QUESTION, opening="Hello, you enquired about our flats, can we talk now?")
    assert fixable_findings(claim, LINT, "false_history") == []
    assert script_mistakes(claim, LINT) == []


def test_a_screen_counts_a_line_once_beside_the_script_check() -> None:
    script = _script(THREE_QUESTIONS)
    found = script_problems(script, LINT)
    beside = script_mistakes(script, LINT, beside=found)
    named = {p.partition(": ")[0] for p in found}
    assert all(m.partition(": ")[0] not in named for m in beside)


# --- 1. at writing time ---------------------------------------------------------------------------


async def _org(prefix: str, language: str = "en-IN") -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Sunrise Homes",
        slug=f"wc-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language=language,
        created_by=None,
    )
    return UUID(str(created["id"])), UUID(str(created["agent_id"]))


def _answer(script: CallScript) -> Any:
    return SimpleNamespace(
        script=script,
        capability=SimpleNamespace(disclosure=None),
        usage=None,
        model="gemini-2.5-flash-lite",
        earlier=(),
        left_out=(),
    )


async def _write(
    monkeypatch: pytest.MonkeyPatch, base: CallScript, answers: list[CallScript]
) -> tuple[worker.Finished, list[str]]:
    """`answers[0]` is what Pip drafted; each repair the checks ask for answers the next."""
    tenant_id, agent_id = await _org("draft")
    changes: list[str] = []

    async def write(_brief: Any, **kwargs: Any) -> Any:
        changes.append(kwargs["change"])
        return _answer(answers[min(len(changes), len(answers) - 1)])

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LINT

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript) -> Any:
        return script, []

    monkeypatch.setattr(worker, "draft_script", write)
    monkeypatch.setattr(worker, "lint_context_for", lint_context)
    monkeypatch.setattr(worker, "_opening_repaired", openings)
    request = script_proposals.ScriptProposal(
        id=uuid.uuid4(),
        mode="change",
        status="drafting",
        request="Add a step that asks where they live and when they can visit.",
        answers={},
        base_script=base,
        requested_by=None,
        requested_at=datetime.now(UTC),
    )
    finished = await worker.finish_written(
        tenant_id, agent_id, request, answers[0], time.monotonic()
    )
    return finished, changes


@pytest.mark.rls
async def test_a_draft_packing_three_questions_is_repaired_before_it_is_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: Pip's draft reaches the owner with a step line that makes the agent ask three
    questions in one turn, or the repair round is not handed back to be metered (hard rule
    7)."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 2)
    base = _script()
    drafted = _script(THREE_QUESTIONS)
    # The repair also tries to rewrite the opening and its notice record: neither is a path
    # the check named, so neither is taken.
    repaired = _script(ONE_QUESTION, opening="Hello! Asha here from a new opening.").model_copy(
        update={"opening_notices": OpeningNotices(line="Hello! Asha here.", ai="Asha")}
    )
    finished, changes = await _write(monkeypatch, base, [drafted, repaired])
    assert finished.script.stages[0].sounds_like == ONE_QUESTION
    assert script_mistakes(finished.script, LINT) == []
    assert (finished.script.opening_line, finished.script.opening_notices) == (
        drafted.opening_line,
        drafted.opening_notices,
    )
    assert len(changes) == 1 and len(finished.repairs) == 1
    # The repair names only the line the check found, at its real place.
    assert "stages.0.sounds_like" in changes[0] and "opening_line" not in changes[0]
    assert finished.left_out == []


@pytest.mark.rls
async def test_what_the_capped_repairs_leave_is_told_to_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a line still found after the console's repair rounds is offered without a
    word, or more rounds are spent than the console allows."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 1)
    still = "What is your name? Which area is it? When do you visit?"
    finished, changes = await _write(
        monkeypatch, _script(), [_script(THREE_QUESTIONS), _script(still)]
    )
    assert len(changes) == 1 and len(finished.repairs) == 1
    [left] = finished.left_out
    assert left.unfixed and left.part == "stages.s0"
    assert left.rule.startswith("Still to fix:")


@pytest.mark.rls
async def test_no_round_is_spent_when_the_console_allows_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    finished, changes = await _write(monkeypatch, _script(), [_script(THREE_QUESTIONS)])
    assert changes == []
    assert [part.unfixed for part in finished.left_out] == [True]


@pytest.mark.rls
async def test_an_owners_own_finding_in_an_edit_is_not_pips_to_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an edit asked for one thing spends the allowance rewriting a line the owner
    already had."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 2)
    base = _script(THIRD_PERSON)
    finished, changes = await _write(monkeypatch, base, [_script(THIRD_PERSON, ONE_QUESTION)])
    assert changes == []
    assert finished.left_out == []


# --- 2. on save: the script check -----------------------------------------------------------------


async def _agent(prefix: str, script: CallScript, *, status: str = "live") -> tuple[UUID, UUID]:
    tenant_id, agent_id = await _org(prefix)
    async with tenant_session(tenant_id) as session:
        await script_builder.clear_draft(session, agent_id)
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script,
            notes="test script",
            created_by=None,
        )
        await session.execute(
            text("UPDATE agents SET status = :s WHERE id = :a"), {"s": status, "a": agent_id}
        )
    return tenant_id, agent_id


@pytest.mark.rls
async def test_the_card_and_put_it_live_show_the_lines_without_blocking() -> None:
    tenant_id, agent_id = await _agent("card", _script(THIRD_PERSON))
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        checked = await http.post(
            f"/v1/agents/{agent_id}/script/check",
            json={"script": _script(THIRD_PERSON).model_dump(mode="json")},
            headers=headers,
        )
    assert checked.status_code == 200, checked.text
    body = checked.json()
    # The agent's own lint context finds other things in this bare test script; the
    # mistake line is its own group and is not among them.
    assert [m.split(": ")[0] for m in body["mistakes"]] == ["Step 1"]
    assert all(not w.startswith("Step 1:") for w in body["warnings"])


def test_the_repair_rounds_are_on_the_console() -> None:
    assert "script_mistake_repair_passes" in FIELD_META


def test_the_owner_is_told_it_was_found_before_any_call() -> None:
    """The notices of fixes the sweep of agent scripts opened before D-1005 still read."""
    early = notices.script_fix_notice(kind="script_check_fixed", name="Asha", state="open")
    seen = notices.script_fix_notice(kind="script_fixed", name="Asha", state="open")
    assert "before any call" in early.what_happened
    assert "On real calls" in seen.what_happened
    waiting = notices.script_fix_notice(kind="script_check_waiting", name="Asha", state="open")
    assert waiting.must_act and "before any call" in waiting.what_happened
    assert replace(early, what_happened="") == replace(seen, what_happened="")
