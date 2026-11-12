"""The healer fixes a mistake on real calls in the agent's own script (D-985), end to end
against a real database: the fix opens with the call's mistakes, Pip's fix is asked for the
lines the script check names and metered, it waits rather than write over the owner, it is
checked and put live with a version check, the next calls settle it or put the old script
back, and the owner can undo it.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: Pip's written fix is stored directly, the way the
job stores it (`script_proposals.store_ready`).
"""

from __future__ import annotations

import importlib.util
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents import call_mistakes, mistake_fixes, script_builder, script_proposals
from apps.api.agents.capability_manifest import lint_context_for
from apps.api.agents.mistake_lints import mistake_findings
from apps.api.agents.script_lint import LintContext
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.healer import incidents, notices, playbooks
from apps.api.healer.incidents import Incident
from apps.api.main import app
from apps.workers import healer as healer_jobs
from apps.workers import mistake_fix
from apps.workers import script_proposal as proposal_job
from calevate_shared.call_script import CallScript, ConversationStage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from tests.a2p_declaration_test import _org_headers
from tests.conftest import create_org_with_receptionist

pytestmark = [pytest.mark.rls]

KIND = "opened_again"
GREETS = "Greet the caller warmly and ask what they need today."
FIXED = "Ask what they need today, in one short question."


def _script(first: str = GREETS) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line="Namaste, this is Asha from Sunrise Homes.",
        stages=[
            ConversationStage(id="need", name="Their need", instruction=first),
            ConversationStage(id="close", name="Close", instruction="Thank them and end the call."),
        ],
    )


async def _agent(prefix: str, script: CallScript | None = None) -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Fix Homes",
        slug=f"fix-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id, agent_id = UUID(str(created["id"])), UUID(str(created["agent_id"]))
    async with tenant_session(tenant_id) as session:
        await script_builder.clear_draft(session, agent_id)
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=script or _script(),
            notes="test script",
            created_by=None,
        )
    return tenant_id, agent_id


async def _call(
    tenant_id: UUID, agent_id: UUID, *, started: datetime, kinds: tuple[str, ...] = ()
) -> UUID:
    """A checked call: a transcript, and its mistake rows."""
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
        for kind in kinds:
            await session.execute(
                text(
                    "INSERT INTO call_mistakes (id, tenant_id, agent_id, call_id, kind, turn_idx, "
                    "call_started_at) VALUES (:id, :t, :a, :c, :k, 0, :s)"
                ),
                {
                    "id": uuid7(),
                    "t": tenant_id,
                    "a": agent_id,
                    "c": call_id,
                    "k": kind,
                    "s": started,
                },
            )
    return call_id


async def _seen(tenant_id: UUID, agent_id: UUID, kind: str = KIND) -> UUID:
    """A real call showing `kind`, recorded the way the pipeline records it."""
    started = datetime.now(UTC) - timedelta(minutes=5)
    call_id = await _call(tenant_id, agent_id, started=started)
    await call_mistakes.record_call_mistakes(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        call_started_at=started,
        found={kind: 0},
    )
    return call_id


async def _fix(tenant_id: UUID, agent_id: UUID, kind: str = KIND) -> mistake_fixes.MistakeFix:
    async with tenant_session(tenant_id) as session:
        found = await mistake_fixes.latest_fixes(session, agent_id, [kind])
    return found[kind]


async def _incident(fix: mistake_fixes.MistakeFix) -> Incident:
    assert fix.incident_id is not None
    async with untenanted_session() as session:
        found = await incidents.read_incident(session, fix.incident_id)
    assert found is not None
    return found


async def _step(tenant_id: UUID, agent_id: UUID, kind: str = KIND) -> mistake_fixes.MistakeFix:
    await mistake_fix.call_mistake_fix(await _incident(await _fix(tenant_id, agent_id, kind)))
    return await _fix(tenant_id, agent_id, kind)


async def _written(tenant_id: UUID, agent_id: UUID, script: CallScript) -> None:
    """Pip's fix, stored as the job stores it."""
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
        assert proposal is not None and proposal.status == "drafting"
        assert await script_proposals.store_ready(
            session,
            agent_id=agent_id,
            proposal_id=proposal.id,
            script=script,
            unplaced=[],
            disclosure=None,
        )


async def _live_script(tenant_id: UUID, agent_id: UUID) -> tuple[CallScript, int | None]:
    async with tenant_session(tenant_id) as session:
        loaded = await script_builder.load_agent_script(session, agent_id, applied=True)
        if loaded.version is None:
            loaded = await script_builder.load_agent_script(session, agent_id)
    return loaded.script, loaded.version


async def _live_fix(tenant_id: UUID, agent_id: UUID) -> mistake_fixes.MistakeFix:
    await _seen(tenant_id, agent_id)
    await _step(tenant_id, agent_id)
    await _written(tenant_id, agent_id, _script(FIXED))
    fix = await _step(tenant_id, agent_id)
    assert fix.state == "live"
    return fix


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "healer_enabled", True)
    monkeypatch.setattr(settings, "healer_paused_playbooks", "")
    monkeypatch.setattr(settings, "call_mistake_fix_clean_calls", 2)
    monkeypatch.setattr(settings, "call_mistake_fix_compare_calls", 2)
    monkeypatch.setattr(settings, "call_mistake_fix_max_attempts", 2)
    monkeypatch.setattr(settings, "call_mistake_fix_max_waits", 3)
    monkeypatch.setattr(settings, "call_mistake_fix_wait_minutes", 30)
    monkeypatch.setattr(settings, "call_mistake_fix_worse_per_100_calls", 50)


# --- open ---------------------------------------------------------------------------------------


async def test_a_call_showing_a_mistake_opens_one_fix_and_one_incident() -> None:
    tenant_id, agent_id = await _agent("open")
    await _seen(tenant_id, agent_id)
    await _seen(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT state, incident_id FROM agent_mistake_fixes WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).all()
    assert len(rows) == 1 and rows[0][0] == "fixing"
    incident = await _incident(await _fix(tenant_id, agent_id))
    assert (incident.playbook, incident.trigger_code, incident.scope) == (
        "call_mistake_fix",
        "call_mistake_seen",
        "agent",
    )
    assert (incident.tenant_id, incident.agent_id) == (tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        mistakes = await call_mistakes.agent_mistakes(session, agent_id)
    assert [(m.kind, m.state) for m in mistakes] == [(KIND, "script_fixing")]


# --- act ----------------------------------------------------------------------------------------


async def test_the_fix_is_asked_for_exactly_the_lines_the_check_names() -> None:
    tenant_id, agent_id = await _agent("act")
    _, version = await _live_script(tenant_id, agent_id)
    await _seen(tenant_id, agent_id)
    fix = await _step(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
        queued = (
            await session.execute(
                text(
                    "SELECT count(*) FROM outbox_messages WHERE job = :j "
                    "AND payload->>'proposal_id' = :p"
                ),
                {"j": script_proposals.PROPOSAL_JOB, "p": str(fix.proposal_id)},
            )
        ).scalar_one()
    assert proposal is not None and proposal.id == fix.proposal_id
    assert (proposal.mode, proposal.requested_by, proposal.mistake_kind) == ("change", None, KIND)
    assert proposal.paths == ["stages.0.instruction"]
    assert queued == 1
    assert (fix.attempts, fix.version_base, fix.version_before) == (1, version, version)
    assert (await _incident(fix)).last_outcome == "fix_requested"


async def test_the_job_writes_the_fix_for_the_mistake_and_meters_it_to_the_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _agent("meter")
    await _seen(tenant_id, agent_id)
    fix = await _step(tenant_id, agent_id)
    asked: dict[str, Any] = {}
    metered: list[UUID] = []

    async def drafted(_t: UUID, _a: UUID, proposal: Any, _trace: Any, change: Any) -> Any:
        asked["change"] = change
        return SimpleNamespace(
            script=_script(FIXED),
            earlier=(),
            model="gemini-2.5-flash-lite",
            capability=SimpleNamespace(disclosure=None),
        )

    async def meter(_session: Any, *, tenant_id: UUID, **_kwargs: Any) -> None:
        metered.append(tenant_id)

    async def openings(_t: UUID, _a: UUID, _p: Any, script: CallScript) -> Any:
        return script, []

    monkeypatch.setattr(proposal_job, "_draft", drafted)
    monkeypatch.setattr(proposal_job, "_opening_repaired", openings)
    monkeypatch.setattr(proposal_job.crm_assist, "meter_earlier", meter)
    monkeypatch.setattr(proposal_job.crm_assist, "meter_assist", meter)
    payload = {
        "tenant_id": str(tenant_id),
        "agent_id": str(agent_id),
        "proposal_id": str(fix.proposal_id),
    }
    assert await proposal_job.draft_script_proposal({}, payload) == "ready"
    # The finding is the mistake's own check's, at its real path.
    assert "stages.0.instruction" in asked["change"]
    assert "greets" in asked["change"]
    assert metered and set(metered) == {tenant_id}
    async with tenant_session(tenant_id) as session:
        stored = await script_proposals.read_proposal(session, agent_id)
    assert stored is not None and stored.status == "ready"
    assert stored.script is not None and stored.script.stages[0].instruction == FIXED
    # The healer is nudged rather than left to its next look.
    incident = await _incident(fix)
    assert incident.next_attempt_at is not None
    assert incident.next_attempt_at <= datetime.now(UTC) + timedelta(seconds=5)


async def test_it_waits_rather_than_write_over_the_owners_draft() -> None:
    tenant_id, agent_id = await _agent("draft")
    async with tenant_session(tenant_id) as session:
        await script_builder.save_draft(session, agent_id, _script("Ask their budget first."))
    await _seen(tenant_id, agent_id)
    fix = await _step(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
        draft = await script_builder.read_draft(session, agent_id)
    assert proposal is None and fix.proposal_id is None
    assert (fix.state, fix.waits, fix.attempts) == ("fixing", 1, 0)
    assert draft is not None and draft.script.stages[0].instruction == "Ask their budget first."
    assert (await _incident(fix)).last_outcome == "waiting"
    # After the last look a person is asked.
    await _step(tenant_id, agent_id)
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.ended_because) == ("needs_person", "waited_too_long")
    assert (await _incident(fix)).state == "escalated"


async def test_an_empty_ai_allowance_waits_and_tells_the_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def used_up(_session: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(at_ceiling=True, platform_paused=False)

    monkeypatch.setattr(mistake_fix, "read_ai_quota", used_up)
    tenant_id, agent_id = await _agent("quota")
    await _seen(tenant_id, agent_id)
    fix = await _step(tenant_id, agent_id)
    assert (fix.proposal_id, fix.waits) == (None, 1)
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT kind, must_act FROM heal_client_incidents WHERE incident_id = :i"),
                {"i": fix.incident_id},
            )
        ).one()
    assert (row[0], row[1]) == ("script_fix_waiting", True)


async def test_a_kind_no_line_causes_is_handed_to_our_team() -> None:
    tenant_id, agent_id = await _agent("platform")
    await _seen(tenant_id, agent_id, kind="wrong_language")
    fix = await _step(tenant_id, agent_id, kind="wrong_language")
    assert (fix.state, fix.ended_because, fix.proposal_id) == (
        "needs_person",
        "no_script_cause",
        None,
    )
    assert (await _incident(fix)).state == "escalated"
    async with tenant_session(tenant_id) as session:
        mistakes = await call_mistakes.agent_mistakes(session, agent_id)
    assert [(m.kind, m.state) for m in mistakes] == [("wrong_language", "with_team")]


def test_a_fix_never_names_the_openings_or_their_notices() -> None:
    findings = [
        "opening_line: says nearly what step 2 says",
        "outbound_opening_line: x",
        "opening_notices.ai: x",
        "outbound_opening_notices: x",
        "stages.1.instruction: greets",
    ]
    assert mistake_fixes.fix_paths(findings) == ["stages.1.instruction"]
    base = _script()
    for part, value in (
        ("opening_line", "Hello there, Sunrise Homes calling."),
        ("raw_override", "Say hello."),
    ):
        changed = base.model_copy(update={part: value, "stages": _script(FIXED).stages})
        why = mistake_fix.verify_candidate(base, changed, LintContext(), KIND)
        assert why is not None and part in why
    assert mistake_fix.verify_candidate(base, _script(FIXED), LintContext(), KIND) is None


# --- verify and put live ------------------------------------------------------------------------


async def test_a_checked_fix_goes_live_and_the_owner_is_told() -> None:
    tenant_id, agent_id = await _agent("live")
    _, before = await _live_script(tenant_id, agent_id)
    fix = await _live_fix(tenant_id, agent_id)
    script, version = await _live_script(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        lint = await lint_context_for(session, tenant_id=tenant_id, agent_id=agent_id)
        proposal = await script_proposals.read_proposal(session, agent_id)
        notice = (
            await session.execute(
                text("SELECT kind, must_act FROM heal_client_incidents WHERE incident_id = :i"),
                {"i": fix.incident_id},
            )
        ).one()
        mistakes = await call_mistakes.agent_mistakes(session, agent_id)
    assert mistake_findings(script, lint, KIND) == []
    assert script.stages[0].instruction == FIXED
    assert script.opening_line == _script().opening_line
    assert (fix.version_before, fix.version_after) == (before, version)
    assert proposal is None
    assert (notice[0], notice[1]) == ("script_fixed", False)
    assert [(m.state, m.can_undo) for m in mistakes] == [("script_live", True)]
    assert (await _incident(fix)).last_outcome == "fix_live"


async def test_a_fix_that_still_has_the_cause_is_not_put_live() -> None:
    tenant_id, agent_id = await _agent("unverified")
    _, before = await _live_script(tenant_id, agent_id)
    await _seen(tenant_id, agent_id)
    await _step(tenant_id, agent_id)
    await _written(tenant_id, agent_id, _script("Greet them again and ask their need."))
    fix = await _step(tenant_id, agent_id)
    _, now = await _live_script(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
    assert now == before and proposal is None
    assert (fix.state, fix.proposal_id, fix.attempts) == ("fixing", None, 1)
    # The second attempt is asked from the live script; when it fails too, a person is.
    fix = await _step(tenant_id, agent_id)
    assert fix.attempts == 2 and fix.proposal_id is not None
    await _written(tenant_id, agent_id, _script("Greet them and ask."))
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.ended_because) == ("needs_person", "attempts_spent")


async def test_a_script_changed_after_the_fix_was_asked_is_not_overwritten() -> None:
    tenant_id, agent_id = await _agent("cas")
    await _seen(tenant_id, agent_id)
    await _step(tenant_id, agent_id)
    await _written(tenant_id, agent_id, _script(FIXED))
    owner = _script("Ask whether they want to buy or rent.")
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=owner,
            notes="owner edit",
            created_by=None,
        )
    fix = await _step(tenant_id, agent_id)
    script, _ = await _live_script(tenant_id, agent_id)
    assert script.stages[0].instruction == owner.stages[0].instruction
    assert fix.state == "fixing" and fix.proposal_id is None


# --- watch --------------------------------------------------------------------------------------


async def test_clean_calls_after_the_fix_settle_it() -> None:
    tenant_id, agent_id = await _agent("settle")
    fix = await _live_fix(tenant_id, agent_id)
    assert fix.live_at is not None
    for n in (1, 2):
        await _call(tenant_id, agent_id, started=fix.live_at + timedelta(seconds=n))
    fix = await _step(tenant_id, agent_id)
    assert fix.state == "fixed" and fix.settled_at is not None
    incident = await _incident(fix)
    assert (incident.state, incident.last_outcome) == ("resolved", "verified")
    async with tenant_session(tenant_id) as session:
        mistakes = await call_mistakes.agent_mistakes(session, agent_id)
    assert [(m.state, m.clean_calls) for m in mistakes] == [("script_fixed", 2)]


async def test_the_mistake_back_is_fixed_again_from_the_live_script(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _agent("back")
    fix = await _live_fix(tenant_id, agent_id)
    assert fix.live_at is not None
    await _call(tenant_id, agent_id, started=fix.live_at + timedelta(seconds=1), kinds=(KIND,))
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.live_at) == ("fixing", None)

    def still(_script: CallScript, _lint: Any, _kind: str) -> list[str]:
        return ["stages.1.instruction: greets again"]

    monkeypatch.setattr(mistake_fix, "mistake_findings", still)
    fix = await _step(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        proposal = await script_proposals.read_proposal(session, agent_id)
    # The second fix is asked from the live script, which holds the first.
    assert proposal is not None and proposal.base_script.stages[0].instruction == FIXED
    assert proposal.paths == ["stages.1.instruction"]
    assert fix.attempts == 2


async def test_a_mistake_back_with_no_cause_left_puts_the_old_script_back() -> None:
    tenant_id, agent_id = await _agent("back-nocause")
    original, _ = await _live_script(tenant_id, agent_id)
    fix = await _live_fix(tenant_id, agent_id)
    assert fix.live_at is not None
    await _call(tenant_id, agent_id, started=fix.live_at + timedelta(seconds=1), kinds=(KIND,))
    await _step(tenant_id, agent_id)
    fix = await _step(tenant_id, agent_id)
    script, _ = await _live_script(tenant_id, agent_id)
    assert (fix.state, fix.ended_because) == ("rolled_back", "came_back")
    assert script.stages[0].instruction == original.stages[0].instruction


async def test_after_the_last_attempt_a_mistake_back_puts_the_old_script_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "call_mistake_fix_max_attempts", 1)
    tenant_id, agent_id = await _agent("rollback")
    original, before = await _live_script(tenant_id, agent_id)
    fix = await _live_fix(tenant_id, agent_id)
    assert fix.live_at is not None
    await _call(tenant_id, agent_id, started=fix.live_at + timedelta(seconds=1), kinds=(KIND,))
    fix = await _step(tenant_id, agent_id)
    script, version = await _live_script(tenant_id, agent_id)
    assert (fix.state, fix.ended_because) == ("rolled_back", "came_back")
    assert script.stages[0].instruction == original.stages[0].instruction
    assert version is not None and before is not None and version > before
    incident = await _incident(fix)
    assert (incident.state, incident.last_outcome) == ("escalated", "rolled_back")
    # A later call showing it does not start a fix while a person has it.
    await _seen(tenant_id, agent_id)
    assert (await _fix(tenant_id, agent_id)).id == fix.id


async def test_more_other_mistakes_after_the_fix_put_the_old_script_back() -> None:
    tenant_id, agent_id = await _agent("worse")
    original, _ = await _live_script(tenant_id, agent_id)
    fix = await _live_fix(tenant_id, agent_id)
    assert fix.live_at is not None
    for n in (1, 2):
        await _call(
            tenant_id,
            agent_id,
            started=fix.live_at + timedelta(seconds=n),
            kinds=("said_again", "too_long"),
        )
    fix = await _step(tenant_id, agent_id)
    script, _ = await _live_script(tenant_id, agent_id)
    assert (fix.state, fix.ended_because) == ("rolled_back", "worse")
    assert script.stages[0].instruction == original.stages[0].instruction


# --- the owner's Undo ---------------------------------------------------------------------------


async def test_the_owner_undoes_the_fix_and_the_healer_does_not_redo_it() -> None:
    tenant_id, agent_id = await _agent("undo")
    original, _ = await _live_script(tenant_id, agent_id)
    fix = await _live_fix(tenant_id, agent_id)
    headers = await _org_headers(tenant_id)
    path = f"/v1/agents/{agent_id}/call-mistakes/{KIND}/undo"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        listed = (await http.get(f"/v1/agents/{agent_id}/call-mistakes", headers=headers)).json()
        assert [(i["state"], i["can_undo"]) for i in listed["items"]] == [("script_live", True)]
        done = await http.post(path, headers=headers)
        assert done.status_code == 200, done.text
        again = await http.post(path, headers=headers)
        assert again.status_code == 404
        listed = (await http.get(f"/v1/agents/{agent_id}/call-mistakes", headers=headers)).json()
    assert [(i["state"], i["can_undo"]) for i in listed["items"]] == [("script_undone", False)]
    script, version = await _live_script(tenant_id, agent_id)
    assert script.stages[0].instruction == original.stages[0].instruction
    assert done.json() == {"kind": KIND, "version": version}
    undone = await _fix(tenant_id, agent_id)
    assert (undone.state, undone.ended_because) == ("rolled_back", "owner")
    assert (await _incident(fix)).state == "resolved"
    async with tenant_session(tenant_id) as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'agent.mistake_fix_undone' "
                    "AND object_id = :a"
                ),
                {"a": str(agent_id)},
            )
        ).scalar_one()
    assert audited == 1
    await _seen(tenant_id, agent_id)
    assert (await _fix(tenant_id, agent_id)).id == undone.id


async def test_undo_is_refused_once_the_script_changed_after_the_fix() -> None:
    tenant_id, agent_id = await _agent("undo-moved")
    await _live_fix(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=_script("Ask whether they want to buy or rent."),
            notes="owner edit",
            created_by=None,
        )
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        refused = await http.post(
            f"/v1/agents/{agent_id}/call-mistakes/{KIND}/undo", headers=headers
        )
    assert refused.status_code == 409
    assert refused.json()["type"].endswith(f"/{mistake_fixes.SCRIPT_CHANGED_CODE}")


# --- switches, isolation, schema ----------------------------------------------------------------


def test_the_kill_switches_stop_it(monkeypatch: pytest.MonkeyPatch) -> None:
    assert playbooks.may_run("call_mistake_fix")
    monkeypatch.setattr(get_settings(), "healer_paused_playbooks", "call_mistake_fix")
    assert not playbooks.may_run("call_mistake_fix")
    monkeypatch.setattr(get_settings(), "healer_paused_playbooks", "")
    monkeypatch.setattr(get_settings(), "healer_enabled", False)
    assert not playbooks.may_run("call_mistake_fix")
    assert healer_jobs._STEPS["call_mistake_fix"] is mistake_fix.call_mistake_fix
    assert "call_mistake_seen" in healer_jobs.SELF_OPENED


def test_its_limits_are_the_console_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    playbook = playbooks.PLAYBOOK_BY_KEY["call_mistake_fix"]
    monkeypatch.setattr(get_settings(), "call_mistake_fix_max_attempts", 7)
    monkeypatch.setattr(get_settings(), "call_mistake_fix_wait_minutes", 11)
    assert playbooks.effective_limits(playbook) == (7, 11 * 60)


@pytest.mark.parametrize("outcome", [None, "rolled_back", "undone"])
@pytest.mark.parametrize("kind", ["script_fixed", "script_fix_waiting"])
@pytest.mark.parametrize("state", ["open", "resolved"])
def test_the_owners_notices_name_nothing_internal(
    kind: str, state: str, outcome: str | None
) -> None:
    notice = notices.line_notice(
        kind=kind,
        protection="none",
        agent_name="Reception",
        campaigns_paused=0,
        fallback_phone=None,
        state=state,
        missed_calls=0,
        requeued=0,
        worst_signal=outcome,
    )
    for words in (notice.headline, notice.what_happened, notice.what_we_did, notice.your_part):
        assert words and "_" not in words
        assert not any(w in words.lower() for w in ("incident", "playbook", "healer", "pip"))


async def test_a_tenant_reads_only_its_own_fixes() -> None:
    first, first_agent = await _agent("rls-a")
    second, second_agent = await _agent("rls-b")
    await _seen(first, first_agent)
    await _seen(second, second_agent)
    async with tenant_session(first) as session:
        mine = (await session.execute(text("SELECT count(*) FROM agent_mistake_fixes"))).scalar()
        theirs = (
            await session.execute(
                text("SELECT count(*) FROM agent_mistake_fixes WHERE tenant_id = :t"),
                {"t": second},
            )
        ).scalar()
    assert mine == 1 and theirs == 0
    async with untenanted_session() as session:
        unscoped = (
            await session.execute(
                text("SELECT count(*) FROM agent_mistake_fixes WHERE tenant_id = ANY(:t)"),
                {"t": [first, second]},
            )
        ).scalar()
    assert unscoped == 0


STEM = "c4e8a2f6d1b9_agent_mistake_fixes"


def _revision() -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{STEM}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{STEM}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_goes_down_and_up() -> None:
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    exists = text("SELECT to_regclass('agent_mistake_fixes') IS NOT NULL")
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    assert connection.execute(exists).scalar() is False
                    revision.upgrade()
                    assert connection.execute(exists).scalar() is True
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
