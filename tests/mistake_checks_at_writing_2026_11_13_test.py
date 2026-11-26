"""The call-mistake checks run before any call can hear a mistake (D-989, founder, 13 Nov
2026: "why cant we solve this problem from the start?").

When Pip writes or changes a script (`script_proposal.finish_written`, every writer's
tail), every kind's check reads the draft and the writer's repair round rewrites the
lines it finds; what is still found is told to the owner.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the writer is replaced, as the D-985 tests do.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from apps.api.agents.mistake_lints import fixable_findings, script_mistakes
from apps.api.agents.script_lint import LintContext, script_problems
from apps.api.healer import notices
from apps.api.ops.config_catalog import FIELD_META
from calevate_shared.call_script import CallScript, ConversationStage
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
