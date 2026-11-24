"""The healer fixes a mistake on real calls in the script the call was spoken from (D-985,
D-1005, and the founder's 24 Nov 2026 rule that what Pip can fix is fixed automatically),
end to end against a real database: the fix opens with the call's mistakes, Pip's repair of
exactly the lines the checks name is saved in that call's Inbound line's or campaign's script
and metered to the client, it waits rather than write under a draft already there, and a call
on neither says plainly that there is no script to fix. A draft asked for before the repair
saved scripts itself is still reviewed or replaced. A fix the healer put live on the agent's
own script before D-1005 is settled, and the owner can still undo it.

SHARED DATABASE DISCIPLINE: every organisation is minted here and every assertion is scoped
to its own ids. The model is never called: the writer is replaced at its seam.
"""

from __future__ import annotations

import importlib.util
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from apps.api.agents import call_mistakes, mistake_fixes, script_builder
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.healer import incidents, notices, playbooks
from apps.api.healer.incidents import Incident
from apps.api.inbound import lines
from apps.api.main import app
from apps.workers import healer as healer_jobs
from apps.workers import mistake_fix
from apps.workers import script_heal as heal_job
from calevate_shared.call_script import CallScript, ConversationStage
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine, text
from tests.a2p_declaration_test import _org_headers
from tests.conftest import _owner_of, create_org_with_receptionist, turn_pip_on_for_tests

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


async def _agent(prefix: str, *, pip_on: bool = True) -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Fix Homes",
        slug=f"fix-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    if pip_on:
        await turn_pip_on_for_tests(tenant_id)
    return tenant_id, UUID(str(created["agent_id"]))


async def _line(tenant_id: UUID, agent_id: UUID, script: CallScript | None = None) -> UUID:
    async with tenant_session(tenant_id) as session:
        return await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Front desk",
            main_task="Answer questions about the flats.",
            script=script or _script(),
            created_by=None,
        )


async def _campaign(tenant_id: UUID, agent_id: UUID, script: CallScript | None = None) -> UUID:
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, script) "
                "VALUES (:id, :t, :a, 'Site visits', 'service', CAST(:s AS jsonb))"
            ),
            {
                "id": campaign_id,
                "t": tenant_id,
                "a": agent_id,
                "s": (script or _script()).model_dump_json(),
            },
        )
    return campaign_id


async def _seen(
    tenant_id: UUID,
    agent_id: UUID,
    kind: str = KIND,
    *,
    line_id: UUID | None = None,
    campaign_id: UUID | None = None,
) -> UUID:
    """A real call showing `kind`, on a line, a campaign or neither, recorded the way the
    pipeline records it."""
    started = datetime.now(UTC) - timedelta(minutes=5)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, inbound_line_id, campaign_id, created_at, updated_at) VALUES "
                "(:id, :t, :a, :e, 'inbound', 'completed', :s, :line, :campaign, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"x_{call_id.hex}",
                "s": started,
                "line": line_id,
                "campaign": campaign_id,
            },
        )
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


async def _draft_of(tenant_id: UUID, table: str, holder_id: UUID) -> dict[str, Any] | None:
    async with tenant_session(tenant_id) as session:
        found = (
            await session.execute(
                text(f"SELECT script_proposal FROM {table} WHERE id = :h"), {"h": holder_id}
            )
        ).scalar_one()
    return found  # type: ignore[no-any-return]


def _answer(script: CallScript) -> Any:
    return SimpleNamespace(
        script=script,
        capability=SimpleNamespace(disclosure=None),
        usage=None,
        model="gemini-2.5-flash-lite",
        earlier=(),
        left_out=(),
    )


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "healer_enabled", True)
    monkeypatch.setattr(settings, "healer_paused_playbooks", "")
    monkeypatch.setattr(settings, "healer_shadow_playbooks", "")
    monkeypatch.setattr(settings, "call_mistake_fix_max_attempts", 2)
    monkeypatch.setattr(settings, "call_mistake_fix_max_waits", 3)
    monkeypatch.setattr(settings, "call_mistake_fix_wait_minutes", 30)
    monkeypatch.setattr(settings, "script_mistake_repair_passes", 0)


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


async def test_no_fix_opens_while_the_owner_has_pip_off() -> None:
    """FAILS IF: the healer asks a model to rewrite a line's script, unasked, on an account
    whose owner has not turned Pip on. The mistake still shows; once Pip is on, the next
    call showing it opens the fix."""
    tenant_id, agent_id = await _agent("nopip", pip_on=False)
    line_id = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
    async with tenant_session(tenant_id) as session:
        opened = (
            await session.execute(
                text("SELECT count(*) FROM agent_mistake_fixes WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar_one()
        mistakes = await call_mistakes.agent_mistakes(session, agent_id)
    assert opened == 0
    assert [m.kind for m in mistakes] == [KIND]
    assert await _draft_of(tenant_id, "inbound_lines", line_id) is None

    await turn_pip_on_for_tests(tenant_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
    assert (await _fix(tenant_id, agent_id)).state == "fixing"


async def test_a_fix_whose_owner_turned_pip_off_waits_rather_than_ask_a_model() -> None:
    from apps.api.copilot.consent import withdraw_consent

    tenant_id, agent_id = await _agent("pipoff")
    line_id = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
    async with tenant_session(tenant_id) as session:
        await withdraw_consent(
            session, tenant_id=tenant_id, user_id=await _owner_of(tenant_id), ip=None
        )
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.proposal_id, fix.waits) == ("fixing", None, 1)
    assert await _draft_of(tenant_id, "inbound_lines", line_id) is None


# --- where the fix goes -------------------------------------------------------------------------


async def test_a_mistake_on_a_lines_call_is_asked_for_on_that_line_for_the_named_lines() -> None:
    """FAILS IF: the fix is written anywhere but the line the call was on, or may change more
    than the lines the mistake's check names."""
    tenant_id, agent_id = await _agent("line")
    line_id = await _line(tenant_id, agent_id)
    other = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
    fix = await _step(tenant_id, agent_id)
    assert (fix.inbound_line_id, fix.campaign_id, fix.attempts) == (line_id, None, 1)
    assert fix.proposal_id is None
    # The repair pass is asked for on that line and nowhere else; no draft is left for review.
    assert await _repair_queued(tenant_id, "line", line_id)
    assert not await _repair_queued(tenant_id, "line", other)
    assert await _draft_of(tenant_id, "inbound_lines", line_id) is None
    assert (await _incident(fix)).last_outcome == "fix_requested"


async def test_a_mistake_on_a_campaigns_call_is_asked_for_on_that_campaign() -> None:
    tenant_id, agent_id = await _agent("campaign")
    campaign_id = await _campaign(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, campaign_id=campaign_id)
    fix = await _step(tenant_id, agent_id)
    assert (fix.campaign_id, fix.inbound_line_id) == (campaign_id, None)
    assert await _repair_queued(tenant_id, "campaign", campaign_id)


async def test_a_call_on_no_line_or_campaign_says_there_is_no_script_to_fix() -> None:
    """FAILS IF: a mistake on a call with no line or campaign is written onto the agent, or
    handed to our team as if a script could be fixed."""
    tenant_id, agent_id = await _agent("nojob")
    await _seen(tenant_id, agent_id)
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.ended_because, fix.proposal_id) == ("needs_person", "no_job", None)
    incident = await _incident(fix)
    assert (incident.state, incident.last_outcome) == ("resolved", "no_job")
    async with tenant_session(tenant_id) as session:
        mistakes = await call_mistakes.agent_mistakes(session, agent_id)
    assert [(m.kind, m.state) for m in mistakes] == [(KIND, "no_job")]
    headers = await _org_headers(tenant_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        listed = (await http.get(f"/v1/agents/{agent_id}/call-mistakes", headers=headers)).json()
    assert [(i["state"], i["fix_holder"]) for i in listed["items"]] == [("no_job", None)]


async def test_a_line_with_no_script_has_nothing_to_fix() -> None:
    tenant_id, agent_id = await _agent("noscript")
    async with tenant_session(tenant_id) as session:
        line_id = await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, created_by=None
        )
    await _seen(tenant_id, agent_id, line_id=line_id)
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.ended_because) == ("needs_person", "no_job")


# --- waits --------------------------------------------------------------------------------------


async def test_it_waits_rather_than_write_over_a_draft_already_on_the_line() -> None:
    tenant_id, agent_id = await _agent("waits")
    line_id = await _line(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET script_proposal = CAST(:p AS jsonb) WHERE id = :h"),
            {
                "h": line_id,
                "p": json.dumps(
                    {
                        "id": str(uuid7()),
                        "status": "ready",
                        "requested_at": datetime.now(UTC).isoformat(),
                        "base_script": None,
                    }
                ),
            },
        )
    await _seen(tenant_id, agent_id, line_id=line_id)
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.waits, fix.attempts, fix.proposal_id) == ("fixing", 1, 0, None)
    assert (await _incident(fix)).last_outcome == "waiting"
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
    line_id = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
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
    line_id = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, kind="wrong_language", line_id=line_id)
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


def test_pip_has_words_for_every_state_a_mistake_can_be_in() -> None:
    from typing import get_args

    from apps.api.copilot.agent_reads import _MISTAKE_STATES

    assert set(_MISTAKE_STATES) == set(get_args(call_mistakes.AgentState))


# --- the repair, saved in the script ------------------------------------------------------------


async def _repair_queued(tenant_id: UUID, kind: str, holder_id: UUID) -> bool:
    table = "campaigns" if kind == "campaign" else "inbound_lines"
    async with tenant_session(tenant_id) as session:
        state = (
            await session.execute(
                text(f"SELECT script_heal_state FROM {table} WHERE id = :h"), {"h": holder_id}
            )
        ).scalar_one()
    return state == "queued"


def _heal_writer(
    monkeypatch: pytest.MonkeyPatch, written: CallScript | Exception
) -> dict[str, Any]:
    """Pip's writer in the repair pass replaced, and the meter counted."""
    seen: dict[str, Any] = {"changes": [], "metered": [], "refused": []}

    async def write(_brief: Any, **kwargs: Any) -> Any:
        seen["changes"].append(kwargs["change"])
        if isinstance(written, Exception):
            raise written
        return _answer(written)

    async def meter(_session: Any, *, tenant_id: UUID, **_kwargs: Any) -> None:
        seen["metered"].append(tenant_id)

    async def refusal(_session: Any, *, tenant_id: UUID, **_kwargs: Any) -> None:
        seen["refused"].append(tenant_id)

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(heal_job, "draft_script", write)
    monkeypatch.setattr(heal_job.crm_assist, "meter_earlier", nothing)
    monkeypatch.setattr(heal_job.crm_assist, "meter_assist", meter)
    monkeypatch.setattr(heal_job.crm_assist, "meter_refusal", refusal)
    return seen


async def _run_repair(tenant_id: UUID, line_id: UUID) -> str:
    """The queued repair pass, run past its debounce."""
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE inbound_lines SET script_heal_at = now() - interval '5 minutes' "
                "WHERE id = :h"
            ),
            {"h": line_id},
        )
    return await heal_job.repair_holder_script(
        {}, {"tenant_id": str(tenant_id), "line_id": str(line_id)}
    )


async def test_the_repair_changes_only_the_named_line_saves_it_and_meters_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the repair changes more than the named line, is not charged to the client
    (hard rule 7), waits for the owner, or the fix is not settled once the line is fixed."""
    tenant_id, agent_id = await _agent("job")
    line_id = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
    fix = await _step(tenant_id, agent_id)
    # The model also rewrites the opening: never a line a repair may change.
    rewritten = _script(FIXED).model_copy(update={"opening_line": "Hi, new opening here."})
    seen = _heal_writer(monkeypatch, rewritten)
    # While the pass waits, the fix keeps waiting for it.
    waiting = await _step(tenant_id, agent_id)
    assert (waiting.state, waiting.attempts) == ("fixing", 1)
    assert await _run_repair(tenant_id, line_id) == "repaired"
    [change] = seen["changes"]
    assert "stages.0.instruction" in change and "greets" in change
    assert seen["metered"] == [tenant_id]
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert line.script is not None
    assert line.script.stages[0].instruction == FIXED
    assert line.script.opening_line == _script().opening_line
    assert line.proposal is None, "nothing waits for the owner to keep"
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.live_at is not None) == ("fixed", True)
    assert (await _incident(fix)).state == "resolved"
    async with tenant_session(tenant_id) as session:
        [mistake] = await call_mistakes.agent_mistakes(session, agent_id)
    assert mistake.state == "script_fixed"


async def test_a_repair_that_could_not_be_written_is_asked_again_then_handed_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.errors import ProblemError

    tenant_id, agent_id = await _agent("retry")
    line_id = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
    await _step(tenant_id, agent_id)
    seen = _heal_writer(monkeypatch, ProblemError.business_rule("provider_unavailable", "No."))
    assert await _run_repair(tenant_id, line_id) == "refused"
    assert seen["refused"] == [tenant_id], "a refusal is metered like any Pip write"
    # Asked again, refused again, and after the last attempt our team is told.
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.attempts) == ("fixing", 2)
    assert await _repair_queued(tenant_id, "line", line_id)
    assert await _run_repair(tenant_id, line_id) == "refused"
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.ended_because) == ("needs_person", "attempts_spent")
    async with tenant_session(tenant_id) as session:
        line = await lines.read_line(session, line_id)
    assert line.script == _script()


async def _legacy_draft(
    tenant_id: UUID, agent_id: UUID, line_id: UUID, status: str
) -> mistake_fixes.MistakeFix:
    """A fix whose draft was asked for before the repair saved scripts itself."""
    await _seen(tenant_id, agent_id, line_id=line_id)
    fix = await _fix(tenant_id, agent_id)
    proposal_id = uuid7()
    record = {
        "id": str(proposal_id),
        "status": status,
        "requested_at": datetime.now(UTC).isoformat(),
        "base_script": _script().model_dump(mode="json"),
        "script": _script(FIXED).model_dump(mode="json") if status == "ready" else None,
        "fix_kind": KIND,
        "fix_label": call_mistakes.LESSONS[KIND].label,
    }
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET script_proposal = CAST(:p AS jsonb) WHERE id = :h"),
            {"p": json.dumps(record), "h": line_id},
        )
        await session.execute(
            text(
                "UPDATE agent_mistake_fixes SET proposal_id = :p, attempts = 1, "
                "inbound_line_id = :h WHERE id = :id"
            ),
            {"p": proposal_id, "h": line_id, "id": fix.id},
        )
    return await _fix(tenant_id, agent_id)


async def test_a_draft_written_before_waits_for_the_owner_who_is_told() -> None:
    tenant_id, agent_id = await _agent("review")
    line_id = await _line(tenant_id, agent_id)
    fix = await _legacy_draft(tenant_id, agent_id, line_id, "ready")
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.inbound_line_id) == ("proposed", line_id)
    async with tenant_session(tenant_id) as session:
        told = (
            await session.execute(
                text("SELECT kind, state FROM heal_client_incidents WHERE incident_id = :i"),
                {"i": fix.incident_id},
            )
        ).one()
    assert (told[0], told[1]) == ("script_fix_proposed", "open")
    fix = await _step(tenant_id, agent_id)
    assert (await _incident(fix)).state == "mitigated"
    assert fix.proposal_id is not None
    async with tenant_session(tenant_id) as session:
        await lines.clear_proposal(session, line_id, fix.proposal_id)
    fix = await _step(tenant_id, agent_id)
    assert (await _incident(fix)).state == "resolved"


async def test_a_draft_asked_for_before_and_never_written_is_repaired_instead() -> None:
    """FAILS IF: a draft no job will ever write keeps the fix waiting for good."""
    tenant_id, agent_id = await _agent("unwritten")
    line_id = await _line(tenant_id, agent_id)
    await _legacy_draft(tenant_id, agent_id, line_id, "drafting")
    fix = await _step(tenant_id, agent_id)
    assert fix.proposal_id is None
    assert await _draft_of(tenant_id, "inbound_lines", line_id) is None
    fix = await _step(tenant_id, agent_id)
    assert fix.attempts == 2 and await _repair_queued(tenant_id, "line", line_id)


# --- fixes made before D-1005 -------------------------------------------------------------------


async def _legacy_live_fix(tenant_id: UUID, agent_id: UUID) -> tuple[mistake_fixes.MistakeFix, int]:
    """A fix the healer put live on the agent's own script before D-1005: two versions."""
    async with tenant_session(tenant_id) as session:
        await script_builder.clear_draft(session, agent_id)
        before = await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=_script(),
            notes="before",
            created_by=None,
        )
        after = await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=_script(FIXED),
            notes="the fix",
            created_by=None,
        )
    await _seen(tenant_id, agent_id)
    fix = await _fix(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agent_mistake_fixes SET state = 'live', live_at = now(), attempts = 1, "
                "version_before = :b, version_base = :b, version_after = :a WHERE id = :id"
            ),
            {"b": before.version, "a": after.version, "id": fix.id},
        )
    return await _fix(tenant_id, agent_id), before.version


async def test_a_fix_live_from_before_is_settled_and_can_still_be_undone() -> None:
    tenant_id, agent_id = await _agent("legacy")
    fix, before = await _legacy_live_fix(tenant_id, agent_id)
    settled = await _step(tenant_id, agent_id)
    assert settled.state == "fixed"
    assert (await _incident(fix)).state == "resolved"
    headers = await _org_headers(tenant_id)
    path = f"/v1/agents/{agent_id}/call-mistakes/{KIND}/undo"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        listed = (await http.get(f"/v1/agents/{agent_id}/call-mistakes", headers=headers)).json()
        assert [(i["state"], i["can_undo"]) for i in listed["items"]] == [("script_fixed", True)]
        done = await http.post(path, headers=headers)
    assert done.status_code == 200, done.text
    async with tenant_session(tenant_id) as session:
        script = (await script_builder.load_agent_script(session, agent_id)).script
    assert script.stages[0].instruction == GREETS
    undone = await _fix(tenant_id, agent_id)
    assert (undone.state, undone.ended_because, undone.version_before) == (
        "rolled_back",
        "owner",
        before,
    )


async def test_a_fix_asked_of_the_agents_own_script_is_asked_again_where_the_call_was() -> None:
    tenant_id, agent_id = await _agent("moved")
    line_id = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
    fix = await _fix(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agent_mistake_fixes SET proposal_id = :p, attempts = 1 WHERE id = :id"),
            {"p": uuid7(), "id": fix.id},
        )
    fix = await _step(tenant_id, agent_id)
    assert (fix.state, fix.proposal_id) == ("fixing", None)
    fix = await _step(tenant_id, agent_id)
    assert fix.inbound_line_id == line_id and fix.proposal_id is None
    assert await _repair_queued(tenant_id, "line", line_id)


# --- switches, notices, isolation, schema -------------------------------------------------------


def test_the_kill_switches_stop_it(monkeypatch: pytest.MonkeyPatch) -> None:
    assert playbooks.may_run("call_mistake_fix")
    monkeypatch.setattr(get_settings(), "healer_paused_playbooks", "call_mistake_fix")
    assert not playbooks.may_run("call_mistake_fix")
    monkeypatch.setattr(get_settings(), "healer_paused_playbooks", "")
    monkeypatch.setattr(get_settings(), "healer_enabled", False)
    assert not playbooks.may_run("call_mistake_fix")
    assert healer_jobs._STEPS["call_mistake_fix"] is mistake_fix.call_mistake_fix
    assert "call_mistake_seen" in healer_jobs.SELF_OPENED


async def test_a_dry_run_names_the_lines_and_leaves_no_fix_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from collections import Counter

    monkeypatch.setattr(get_settings(), "healer_shadow_playbooks", "call_mistake_fix")
    tenant_id, agent_id = await _agent("shadow")
    line_id = await _line(tenant_id, agent_id)
    await _seen(tenant_id, agent_id, line_id=line_id)
    incident = await _incident(await _fix(tenant_id, agent_id))

    async def claim(*_: Any, **__: Any) -> list[Incident]:
        return [incident]

    async def quiet(*_: Any) -> int:
        return 0  # the other tests' actions share this ledger

    monkeypatch.setattr(healer_jobs.incidents, "claim_due", claim)
    monkeypatch.setattr(healer_jobs.healer_watch, "actions_recent", quiet)
    await healer_jobs._advance_due(Counter())
    async with untenanted_session() as session:
        closed = await incidents.read_incident(session, incident.id)
        detail = (
            await session.execute(
                text(
                    "SELECT detail FROM heal_actions WHERE incident_id = :i AND outcome = 'shadow'"
                ),
                {"i": incident.id},
            )
        ).scalar_one()
    assert closed is not None and closed.state == "resolved" and closed.last_outcome == "shadow"
    assert "stages.0.instruction" in detail
    async with tenant_session(tenant_id) as session:
        left = (
            await session.execute(
                text("SELECT count(*) FROM agent_mistake_fixes WHERE agent_id = :a"),
                {"a": agent_id},
            )
        ).scalar_one()
    assert left == 0
    assert await _draft_of(tenant_id, "inbound_lines", line_id) is None


def test_its_limits_are_the_console_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    playbook = playbooks.PLAYBOOK_BY_KEY["call_mistake_fix"]
    monkeypatch.setattr(get_settings(), "call_mistake_fix_max_attempts", 7)
    monkeypatch.setattr(get_settings(), "call_mistake_fix_wait_minutes", 11)
    assert playbooks.effective_limits(playbook) == (7, 11 * 60)


@pytest.mark.parametrize("outcome", [None, "rolled_back", "undone"])
@pytest.mark.parametrize("kind", ["script_fixed", "script_fix_waiting", "script_fix_proposed"])
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


STEM = "f3b8d1a6c2e9_mistake_fixes_on_lines_and_campaigns"


def _revision(stem: str = STEM) -> ModuleType:
    path = Path(__file__).resolve().parent.parent / "alembic" / "versions" / f"{stem}.py"
    spec = importlib.util.spec_from_file_location(f"_revision_{stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_migration_goes_down_and_up() -> None:
    revision = _revision()
    url = (get_settings().alembic_database_url or get_settings().database_url).replace(
        "+asyncpg", "+psycopg"
    )
    holders = text(
        "SELECT count(*) FROM information_schema.columns WHERE table_name = "
        "'agent_mistake_fixes' AND column_name IN ('inbound_line_id', 'campaign_id')"
    )
    sync = create_engine(url)
    try:
        with sync.connect() as connection:
            transaction = connection.begin()
            try:
                with Operations.context(MigrationContext.configure(connection)):
                    revision.downgrade()
                    assert connection.execute(holders).scalar() == 0
                    revision.upgrade()
                    assert connection.execute(holders).scalar() == 2
            finally:
                transaction.rollback()
    finally:
        sync.dispose()
