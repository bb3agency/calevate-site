"""The call-mistake checks run before any call can hear a mistake (D-989, founder, 13 Nov
2026: "why cant we solve this problem from the start?").

1. When Pip writes or changes a script, every kind's check reads the draft and the writer's
   repair round rewrites the lines it finds; what is still found is told to the owner.
2. Put it live and the readiness card show them as their own group, never a block, and
   "Fix them first" fixes them.
3. A sweep of live scripts opens the healer's fix (D-985) for each kind it finds, once per
   live version, under the healer's switches and the console's caps.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the writer is replaced, as the D-985 tests do.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import call_mistakes, mistake_fixes, script_builder, script_proposals
from apps.api.agents.mistake_lints import SCRIPT_FIXABLE_KINDS, fixable_findings, script_mistakes
from apps.api.agents.script_lint import LintContext, script_problems
from apps.api.core.settings import get_settings
from apps.api.crm import assist as crm_assist
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.healer import incidents, notices, playbooks
from apps.api.main import app
from apps.api.ops.config_catalog import FIELD_META
from apps.workers import mistake_fix
from apps.workers import script_proposal as worker
from calevate_shared.call_script import CallScript, ConversationStage
from calevate_shared.calling_window import IST
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
SECOND_PERSON = "Your number is saved now."
#: The real list, kept before a test narrows the sweep to its own agents (`_only`).
CHECKS_DUE = mistake_fixes.checks_due


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


async def _change_requested(base: CallScript) -> tuple[UUID, UUID, UUID]:
    tenant_id, agent_id = await _org("draft")
    async with tenant_session(tenant_id) as session:
        await script_builder.save_draft(session, agent_id, base)
        proposal = await script_proposals.request_proposal(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            mode="change",
            change="Add a step that asks where they live and when they can visit.",
            answers={},
            requested_by=uuid.uuid4(),
        )
    return tenant_id, agent_id, proposal.id


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
) -> tuple[script_proposals.ScriptProposal, list[str], list[str]]:
    tenant_id, agent_id, proposal_id = await _change_requested(base)
    changes: list[str] = []
    metered: list[str] = []

    async def write(_brief: Any, **kwargs: Any) -> Any:
        changes.append(kwargs["change"])
        return _answer(answers[min(len(changes), len(answers)) - 1])

    async def lint_context(*_args: Any, **_kwargs: Any) -> LintContext:
        return LINT

    async def meter_assist(_session: Any, **kwargs: Any) -> None:
        metered.append(kwargs["model"])

    async def meter_earlier(_session: Any, **_kwargs: Any) -> None:
        return None

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript) -> Any:
        return script, []

    monkeypatch.setattr(worker, "draft_script", write)
    monkeypatch.setattr(worker, "lint_context_for", lint_context)
    monkeypatch.setattr(worker, "_opening_repaired", openings)
    monkeypatch.setattr(crm_assist, "meter_assist", meter_assist)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter_earlier)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal_id),
    }
    assert await worker.draft_script_proposal({}, payload) == "ready"
    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.read_proposal(session, agent_id)
    assert stored is not None and stored.status == "ready" and stored.script is not None
    return stored, changes, metered


@pytest.mark.rls
async def test_a_draft_packing_three_questions_is_repaired_before_it_is_offered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: Pip's draft reaches the owner with a step line that makes the agent ask three
    questions in one turn, or the repair round is not metered (hard rule 7)."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 2)
    base = _script()
    drafted = _script(THREE_QUESTIONS)
    # The repair also tries to rewrite the opening and its notice record: neither is a path
    # the check named, so neither is taken.
    repaired = _script(ONE_QUESTION, opening="Hello! Asha here from a new opening.").model_copy(
        update={"opening_notices": OpeningNotices(line="Hello! Asha here.", ai="Asha")}
    )
    stored, changes, metered = await _write(monkeypatch, base, [drafted, repaired])
    assert stored.script is not None
    assert stored.script.stages[0].sounds_like == ONE_QUESTION
    assert script_mistakes(stored.script, LINT) == []
    assert (stored.script.opening_line, stored.script.opening_notices) == (
        drafted.opening_line,
        drafted.opening_notices,
    )
    assert len(changes) == 2 and len(metered) == 2
    # The repair names only the line the check found, at its real place.
    assert "stages.0.sounds_like" in changes[1] and "opening_line" not in changes[1]
    assert stored.left_out == []


@pytest.mark.rls
async def test_what_the_capped_repairs_leave_is_told_to_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a line still found after the console's repair rounds is offered without a
    word, or more rounds are spent than the console allows."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 1)
    still = "What is your name? Which area is it? When do you visit?"
    stored, changes, metered = await _write(
        monkeypatch, _script(), [_script(THREE_QUESTIONS), _script(still)]
    )
    assert len(changes) == 2 and len(metered) == 2
    [left] = stored.left_out
    assert left.unfixed and left.part == "stages.s0"
    assert left.rule.startswith("Still to fix:")


@pytest.mark.rls
async def test_no_round_is_spent_when_the_console_allows_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)
    stored, changes, _ = await _write(monkeypatch, _script(), [_script(THREE_QUESTIONS)])
    assert len(changes) == 1
    assert [part.unfixed for part in stored.left_out] == [True]


@pytest.mark.rls
async def test_an_owners_own_finding_in_an_edit_is_not_pips_to_rewrite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: an edit asked for one thing spends the allowance rewriting a line the owner
    already had."""
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 2)
    base = _script(THIRD_PERSON)
    stored, changes, _ = await _write(monkeypatch, base, [_script(THIRD_PERSON, ONE_QUESTION)])
    assert len(changes) == 1
    assert stored.left_out == []


# --- 2. on save: the readiness card, Put it live and "Fix them first" -----------------------------


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
        readiness = await http.get(f"/v1/agents/{agent_id}/readiness", headers=headers)
    assert checked.status_code == 200, checked.text
    body = checked.json()
    # The agent's own lint context finds other things in this bare test script; the
    # mistake line is its own group and is not among them.
    assert [m.split(": ")[0] for m in body["mistakes"]] == ["Step 1"]
    assert all(not w.startswith("Step 1:") for w in body["warnings"])
    assert readiness.status_code == 200, readiness.text
    advice = [a for a in readiness.json()["advice"] if a["kind"] == "script_mistake"]
    assert len(advice) == 1 and advice[0]["href"].endswith("?section=script")
    # Shown, never counted: nothing about the score or the blockers names it.
    assert "script_mistake" not in str(readiness.json()["fixes"])


@pytest.mark.rls
async def test_fix_them_first_fixes_the_mistake_lines_too(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _agent("fixfirst", _script(THIRD_PERSON))
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        asked = await http.post(
            f"/v1/agents/{agent_id}/script/fix-lines",
            json={"script": _script(THIRD_PERSON).model_dump(mode="json")},
            headers=headers,
        )
    assert asked.status_code == 202, asked.text
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
    assert proposal is not None and "stages.0.sounds_like" in proposal.paths
    changes: list[str] = []

    async def write(_brief: Any, **kwargs: Any) -> Any:
        changes.append(kwargs["change"])
        return _answer(_script(SECOND_PERSON))

    async def meter(_session: Any, **_kwargs: Any) -> None:
        return None

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript) -> Any:
        return script, []

    monkeypatch.setattr(worker, "draft_script", write)
    monkeypatch.setattr(worker, "_opening_repaired", openings)
    monkeypatch.setattr(crm_assist, "meter_assist", meter)
    monkeypatch.setattr(crm_assist, "meter_earlier", meter)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(proposal.id),
    }
    assert await worker.draft_script_proposal({}, payload) == "ready"
    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.read_proposal(session, agent_id)
    assert stored is not None and stored.script is not None
    assert stored.script.stages[0].sounds_like == SECOND_PERSON
    # The writer was asked for the mistake's line by its real place, beside the rest.
    assert "stages.0.sounds_like" in changes[0] and "talks about the person" in changes[0]
    assert all(not part.part.startswith("stages.s0") for part in stored.left_out)


# --- 3. the sweep of live scripts ---------------------------------------------------------------


@pytest.fixture
def sweep(monkeypatch: pytest.MonkeyPatch) -> pytest.MonkeyPatch:
    settings = get_settings()
    monkeypatch.setattr(settings, "healer_enabled", True)
    monkeypatch.setattr(settings, "healer_paused_playbooks", "")
    monkeypatch.setattr(settings, "script_check_sweep_minutes", 60)
    monkeypatch.setattr(settings, "script_check_sweep_agents", 50)
    monkeypatch.setattr(settings, "script_check_sweep_max_fixes", 20)
    monkeypatch.setattr(settings, "call_mistake_fix_clean_calls", 2)
    monkeypatch.setattr(settings, "call_mistake_fix_compare_calls", 2)
    monkeypatch.setattr(mistake_fix, "sweep_due", lambda _now, _every: True)
    return monkeypatch


async def _due(tenant_id: UUID, agent_id: UUID) -> mistake_fixes.DueCheck:
    async with tenant_session(tenant_id) as session:
        version, _ = await mistake_fixes.live_version(session, agent_id)
    assert version is not None
    return mistake_fixes.DueCheck(tenant_id=tenant_id, agent_id=agent_id, live_version=version)


def _only(monkeypatch: pytest.MonkeyPatch, due: list[mistake_fixes.DueCheck]) -> list[int]:
    """The sweep's list is this test's agents: the lane database holds other tests' agents."""
    limits: list[int] = []

    async def listed(_session: Any, *, limit: int) -> list[mistake_fixes.DueCheck]:
        limits.append(limit)
        return due[:limit]

    monkeypatch.setattr(mistake_fixes, "checks_due", listed)
    return limits


async def _fixes(tenant_id: UUID, agent_id: UUID) -> list[tuple[str, str, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT kind, found_by, state FROM agent_mistake_fixes WHERE agent_id = :a "
                    "ORDER BY kind, created_at"
                ),
                {"a": agent_id},
            )
        ).all()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


async def _checked_version(tenant_id: UUID, agent_id: UUID) -> int | None:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text("SELECT script_checked_version FROM agents WHERE id = :a"), {"a": agent_id}
            )
        ).scalar_one()


@pytest.mark.rls
async def test_the_sweep_opens_a_fix_for_a_live_script_once_per_version(
    sweep: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _agent("sweep", _script(THIRD_PERSON))
    due = await _due(tenant_id, agent_id)
    async with admin_session() as session:
        listed = await CHECKS_DUE(session, limit=100_000)
    assert due in listed
    _only(sweep, [due])
    assert await mistake_fix.check_live_scripts({}) == "checked:1 opened:1"
    assert await _fixes(tenant_id, agent_id) == [("third_person", "script_check", "fixing")]
    assert await _checked_version(tenant_id, agent_id) == due.live_version
    async with tenant_session(tenant_id) as session:
        fix = (await mistake_fixes.latest_fixes(session, agent_id, ["third_person"]))[
            "third_person"
        ]
    assert fix.incident_id is not None
    async with untenanted_session() as session:
        incident = await incidents.read_incident(session, fix.incident_id)
    assert incident is not None
    assert (incident.playbook, incident.trigger_code) == ("call_mistake_fix", "script_check_found")
    # The same version is not listed, nor fixed, again.
    async with admin_session() as session:
        listed = await CHECKS_DUE(session, limit=100_000)
    assert all(d.agent_id != agent_id for d in listed)
    assert await mistake_fix.check_live_scripts({}) == "checked:1 opened:0"
    assert await _fixes(tenant_id, agent_id) == [("third_person", "script_check", "fixing")]


@pytest.mark.rls
async def test_the_kill_switches_stop_the_sweep(sweep: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _agent("paused", _script(THIRD_PERSON))
    _only(sweep, [await _due(tenant_id, agent_id)])
    sweep.setattr(get_settings(), "healer_paused_playbooks", playbooks.CALL_MISTAKE_FIX)
    assert await mistake_fix.check_live_scripts({}) == "paused"
    sweep.setattr(get_settings(), "healer_paused_playbooks", "")
    sweep.setattr(get_settings(), "healer_enabled", False)
    assert await mistake_fix.check_live_scripts({}) == "paused"
    assert await _fixes(tenant_id, agent_id) == []
    assert await _checked_version(tenant_id, agent_id) is None


@pytest.mark.rls
async def test_the_caps_hold_and_an_agent_cut_short_is_checked_again(
    sweep: pytest.MonkeyPatch,
) -> None:
    """Two kinds in one script, one fix per sweep: the second sweep opens the other."""
    script = _script("What is your name?", ONE_QUESTION, "And your name, please?", THIRD_PERSON)
    tenant_id, agent_id = await _agent("caps", script)
    kinds = sorted(k for k in SCRIPT_FIXABLE_KINDS if fixable_findings(script, LINT, k))
    assert len(kinds) >= 2
    due = await _due(tenant_id, agent_id)
    limits = _only(sweep, [due])
    sweep.setattr(get_settings(), "script_check_sweep_max_fixes", 1)
    sweep.setattr(get_settings(), "script_check_sweep_agents", 7)
    assert await mistake_fix.check_live_scripts({}) == "checked:0 opened:1"
    assert limits == [7]
    assert await _checked_version(tenant_id, agent_id) is None
    sweep.setattr(get_settings(), "script_check_sweep_max_fixes", 20)
    assert await mistake_fix.check_live_scripts({}) == "checked:1 opened:" + str(len(kinds) - 1)
    assert [k for k, by, _ in await _fixes(tenant_id, agent_id) if by == "script_check"] == kinds
    assert await _checked_version(tenant_id, agent_id) == due.live_version


@pytest.mark.rls
async def test_a_draft_agent_is_not_swept(sweep: pytest.MonkeyPatch) -> None:
    _tenant_id, agent_id = await _agent("drafty", _script(THIRD_PERSON), status="draft")
    async with admin_session() as session:
        listed = await CHECKS_DUE(session, limit=100_000)
    assert all(d.agent_id != agent_id for d in listed)


def test_the_console_cadence_decides_the_minute() -> None:
    at = datetime(2026, 11, 13, 9, 0, tzinfo=IST)
    assert mistake_fix.sweep_due(at, 60)
    assert not mistake_fix.sweep_due(at + timedelta(minutes=30), 60)
    assert mistake_fix.sweep_due(at + timedelta(minutes=30), 15)
    # Counted from midnight IST, whatever zone the clock is read in.
    assert mistake_fix.sweep_due(at.astimezone(UTC), 60)


async def test_off_the_cadence_the_sweep_does_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mistake_fix, "sweep_due", lambda _now, _every: False)

    async def never(*_a: Any, **_k: Any) -> list[Any]:
        raise AssertionError("listed off the cadence")

    monkeypatch.setattr(mistake_fixes, "checks_due", never)
    assert await mistake_fix.check_live_scripts({}) == "not_due"


def test_every_new_setting_is_on_the_console() -> None:
    for key in (
        "script_mistake_repair_passes",
        "script_check_sweep_minutes",
        "script_check_sweep_agents",
        "script_check_sweep_max_fixes",
    ):
        assert key in FIELD_META


# --- the sweep's fix runs the D-985 steps, and the owner reads where it came from ---------------


async def _step(tenant_id: UUID, agent_id: UUID, kind: str) -> mistake_fixes.MistakeFix:
    async with tenant_session(tenant_id) as session:
        fix = (await mistake_fixes.latest_fixes(session, agent_id, [kind]))[kind]
    assert fix.incident_id is not None
    async with untenanted_session() as session:
        incident = await incidents.read_incident(session, fix.incident_id)
    assert incident is not None
    await mistake_fix.call_mistake_fix(incident)
    async with tenant_session(tenant_id) as session:
        return (await mistake_fixes.latest_fixes(session, agent_id, [kind]))[kind]


async def _clean_call(tenant_id: UUID, agent_id: UUID, started: datetime) -> None:
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :t, :a, :e, 'inbound', "
                "'completed', :s, now(), now())"
            ),
            {"id": call_id, "t": tenant_id, "a": agent_id, "e": f"x_{call_id.hex}", "s": started},
        )
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text) "
                "VALUES (:id, :t, :c, 0, 'agent', 'Hello')"
            ),
            {"id": uuid7(), "t": tenant_id, "c": call_id},
        )


@pytest.mark.rls
async def test_a_sweep_fix_is_written_put_live_told_and_settled_by_clean_calls(
    sweep: pytest.MonkeyPatch,
) -> None:
    kind = "third_person"
    tenant_id, agent_id = await _agent("live", _script(THIRD_PERSON))
    _only(sweep, [await _due(tenant_id, agent_id)])
    await mistake_fix.check_live_scripts({})
    fix = await _step(tenant_id, agent_id, kind)
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
    assert proposal is not None and proposal.mistake_kind == kind
    assert proposal.paths == ["stages.0.sounds_like"]
    assert "script check found" in (proposal.request or "")
    async with tenant_session(tenant_id) as session:
        assert await script_proposals.store_ready(
            session,
            agent_id=agent_id,
            proposal_id=proposal.id,
            script=_script(SECOND_PERSON),
            unplaced=[],
            disclosure=None,
        )
    fix = await _step(tenant_id, agent_id, kind)
    assert fix.state == "live" and fix.found_by == "script_check"
    async with tenant_session(tenant_id) as session:
        told = (
            await session.execute(
                text("SELECT kind FROM heal_client_incidents WHERE incident_id = :i"),
                {"i": fix.incident_id},
            )
        ).scalar_one()
        listed = await call_mistakes.agent_mistakes(session, agent_id)
        summary = (
            await session.execute(
                text(
                    "SELECT v.notes FROM prompt_versions v JOIN agents a ON "
                    "v.id = COALESCE(a.live_prompt_id, a.system_prompt_id) WHERE a.id = :a"
                ),
                {"a": agent_id},
            )
        ).scalar_one_or_none()
    assert told == "script_check_fixed"
    assert [(m.kind, m.state, m.found_in_script, m.calls, m.can_undo) for m in listed] == [
        (kind, "script_live", True, 0, True)
    ]
    assert summary is not None and summary.startswith("Fixed a line that could cause a mistake")
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        shown = (await http.get(f"/v1/agents/{agent_id}/call-mistakes", headers=headers)).json()
    [item] = shown["items"]
    assert item["found_in_script"] is True
    assert (item["last_call_id"], item["last_seen_at"]) == (None, None)
    # No call has shown it; the D-985 clean-calls rule settles it as usual.
    assert fix.live_at is not None
    for minutes in (1, 2):
        await _clean_call(tenant_id, agent_id, fix.live_at + timedelta(minutes=minutes))
    fix = await _step(tenant_id, agent_id, kind)
    assert fix.state == "fixed"


@pytest.mark.rls
async def test_a_sweep_fix_whose_cause_is_gone_settles_without_a_rewrite(
    sweep: pytest.MonkeyPatch,
) -> None:
    kind = "third_person"
    tenant_id, agent_id = await _agent("moot", _script(THIRD_PERSON))
    _only(sweep, [await _due(tenant_id, agent_id)])
    await mistake_fix.check_live_scripts({})
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=_script(SECOND_PERSON),
            notes="the owner's own change",
            created_by=None,
        )
    fix = await _step(tenant_id, agent_id, kind)
    assert (fix.state, fix.ended_because, fix.attempts) == ("fixed", None, 0)
    async with tenant_session(tenant_id) as session:
        listed = await call_mistakes.agent_mistakes(session, agent_id)
    assert listed == []


@pytest.mark.rls
async def test_a_fix_put_back_is_not_redone_by_the_sweep(sweep: pytest.MonkeyPatch) -> None:
    """FAILS IF: the sweep reopens a kind whose fix was put back, on the very version the
    rollback wrote, so the fix and its rollback loop."""
    kind = "third_person"
    tenant_id, agent_id = await _agent("loop", _script(THIRD_PERSON))
    _only(sweep, [await _due(tenant_id, agent_id)])
    await mistake_fix.check_live_scripts({})
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agent_mistake_fixes SET state = 'rolled_back', ended_because = 'worse', "
                "settled_at = now() WHERE agent_id = :a"
            ),
            {"a": agent_id},
        )
        await session.execute(
            text("UPDATE agents SET script_checked_version = NULL WHERE id = :a"), {"a": agent_id}
        )
    assert await mistake_fix.check_live_scripts({}) == "checked:1 opened:0"
    assert [s for k, _b, s in await _fixes(tenant_id, agent_id) if k == kind] == ["rolled_back"]


@pytest.mark.rls
async def test_the_board_says_what_opened_each_fix(sweep: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _agent("board", _script(THIRD_PERSON))
    _only(sweep, [await _due(tenant_id, agent_id)])
    await mistake_fix.check_live_scripts({})
    async with admin_session() as session:
        board = await mistake_fixes.fleet_fixes(
            session, since=datetime.now(UTC) - timedelta(days=1), limit=200
        )
    mine = [f for f in board if f.agent_id == agent_id]
    assert [(f.kind, f.found_by) for f in mine] == [("third_person", "script_check")]


def test_the_owner_is_told_it_was_found_before_any_call() -> None:
    early = notices.script_fix_notice(kind="script_check_fixed", name="Asha", state="open")
    seen = notices.script_fix_notice(kind="script_fixed", name="Asha", state="open")
    assert "before any call" in early.what_happened
    assert "On real calls" in seen.what_happened
    waiting = notices.script_fix_notice(kind="script_check_waiting", name="Asha", state="open")
    assert waiting.must_act and "before any call" in waiting.what_happened
    assert replace(early, what_happened="") == replace(seen, what_happened="")


# --- mistakes calls showed before any fix existed (D-985 went live after them) ------------------


async def _old_mistake(tenant_id: UUID, agent_id: UUID, kind: str) -> None:
    """A call_mistakes row as the pipeline wrote it before D-985: no fix was opened."""
    started = datetime.now(UTC) - timedelta(days=3)
    await _clean_call(tenant_id, agent_id, started)
    async with tenant_session(tenant_id) as session:
        call_id = (
            await session.execute(
                text("SELECT id FROM calls WHERE agent_id = :a ORDER BY created_at DESC LIMIT 1"),
                {"a": agent_id},
            )
        ).scalar_one()
        await session.execute(
            text(
                "INSERT INTO call_mistakes (id, tenant_id, agent_id, call_id, kind, turn_idx, "
                "call_started_at) VALUES (:id, :t, :a, :c, :k, 0, :s)"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "c": call_id, "k": kind, "s": started},
        )


@pytest.mark.rls
async def test_a_kind_calls_showed_before_any_fix_gets_one_call_fix(
    sweep: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a mistake real calls showed before fixes existed stays at "Not fixed yet"
    for ever because no call has shown it since (the founder's Varsha agent)."""
    tenant_id, agent_id = await _agent("backlog", _script(ONE_QUESTION))
    await _old_mistake(tenant_id, agent_id, "too_long")
    _only(sweep, [await _due(tenant_id, agent_id)])
    assert await mistake_fix.check_live_scripts({}) == "checked:1 opened:1"
    assert await _fixes(tenant_id, agent_id) == [("too_long", "call", "fixing")]
    async with tenant_session(tenant_id) as session:
        fix = (await mistake_fixes.latest_fixes(session, agent_id, ["too_long"]))["too_long"]
    assert fix.incident_id is not None
    async with untenanted_session() as session:
        incident = await incidents.read_incident(session, fix.incident_id)
    assert incident is not None and incident.trigger_code == "call_mistake_seen"
    # A second sweep, even of a version marked unchecked again, opens none.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET script_checked_version = NULL WHERE id = :a"), {"a": agent_id}
        )
    assert await mistake_fix.check_live_scripts({}) == "checked:1 opened:0"
    assert await _fixes(tenant_id, agent_id) == [("too_long", "call", "fixing")]


@pytest.mark.rls
async def test_a_kind_with_a_fix_in_any_state_is_left_alone(sweep: pytest.MonkeyPatch) -> None:
    tenant_id, agent_id = await _agent("settled", _script(THIRD_PERSON))
    await _old_mistake(tenant_id, agent_id, "third_person")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO agent_mistake_fixes (id, tenant_id, agent_id, kind, state, "
                "ended_because, settled_at) VALUES (:id, :t, :a, 'third_person', "
                "'needs_person', 'no_script_cause', now())"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id},
        )
    _only(sweep, [await _due(tenant_id, agent_id)])
    # Neither the call backlog nor the script check reopens it.
    assert await mistake_fix.check_live_scripts({}) == "checked:1 opened:0"
    assert await _fixes(tenant_id, agent_id) == [("third_person", "call", "needs_person")]


@pytest.mark.rls
async def test_one_kind_seen_on_calls_and_found_in_the_script_gets_one_fix(
    sweep: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _agent("both", _script(THIRD_PERSON))
    await _old_mistake(tenant_id, agent_id, "third_person")
    _only(sweep, [await _due(tenant_id, agent_id)])
    assert await mistake_fix.check_live_scripts({}) == "checked:1 opened:1"
    assert await _fixes(tenant_id, agent_id) == [("third_person", "call", "fixing")]
