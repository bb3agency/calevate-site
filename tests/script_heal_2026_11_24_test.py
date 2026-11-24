"""Pip repairs the faulted lines of an existing line's or campaign's script (founder's call of
24 Nov 2026, 12:15: a script written before the 23 Nov checks kept "is now a good time?" in
step 1, one reaction opening every line and a repeat in brackets, and the call page said "Our
team has been told" instead of repairing it).

The bracket check is pure. The repair pass runs against a real database with Pip's writer
replaced at its seam, so no model is called. Every organisation is minted here and every
assertion is scoped to its own ids.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from apps.api.agents import call_mistakes, script_heal
from apps.api.agents.mistake_lints import mistake_findings
from apps.api.agents.script_lint import LintContext, bracket_problems, flow_problems
from apps.api.campaigns import workspace
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from apps.api.main import app
from apps.workers import script_heal as heal_job
from calevate_shared.call_script import CallScript, ConversationStage, ProcedureStep
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.a2p_declaration_test import _org_headers
from tests.conftest import create_org_with_receptionist, turn_pip_on_for_tests

OPENING = "Hello, this is Asha from Sunrise Homes. Can we talk for a minute now?"
BRACKETED = "Tap Add to Home screen (Add to Home screen) and tell me when it shows."
PLAIN = "Tap Add to Home screen and say when the icon shows."


def _stage(sid: str, line: str, **extra: Any) -> ConversationStage:
    return ConversationStage.model_validate(
        {"id": sid, "name": sid, "instruction": "Help them.", "sounds_like": line, **extra}
    )


def _script(first: str = BRACKETED) -> CallScript:
    return CallScript(
        schema_version=2,
        opening_line=OPENING,
        stages=[
            _stage("install", first),
            _stage("close", "Thank you for your time, have a good day.", mode="say"),
        ],
    )


# --- the bracket check ---------------------------------------------------------------------


def test_a_bracketed_repeat_in_a_spoken_line_is_a_flow_finding() -> None:
    script = _script()
    assert [f.partition(": ")[0] for f in bracket_problems(script)] == ["stages.0.sounds_like"]
    assert any(f.startswith('stages.0.sounds_like: has "(Add') for f in flow_problems(script))
    assert bracket_problems(_script(PLAIN)) == []


def test_brackets_are_found_in_a_language_line_and_a_small_step() -> None:
    stage = _stage(
        "install",
        PLAIN,
        scripts={"te-IN": "Open the menu [the three dots] now."},
        procedure=[ProcedureStep(action="Press Install (bottom right).", wait_for="it installs")],
    )
    script = CallScript(schema_version=2, opening_line=OPENING, stages=[stage])
    assert {f.partition(": ")[0] for f in bracket_problems(script)} == {
        "stages.0.scripts.te-IN",
        "stages.0.procedure.0.action",
    }


def test_a_merge_field_is_not_a_bracket() -> None:
    assert bracket_problems(_script("Is this {{lead_name}} speaking, the one who signed up?")) == []


def test_a_call_showing_brackets_routes_to_the_line_that_carries_them() -> None:
    assert mistake_findings(_script(), LintContext(), "brackets") == bracket_problems(_script())
    assert mistake_findings(_script(PLAIN), LintContext(), "brackets") == []


# --- what a repair may clear ---------------------------------------------------------------


def test_the_repair_names_the_faulted_lines_and_never_the_opening() -> None:
    script = CallScript(
        schema_version=2,
        opening_line="Hello (Asha here), can we talk for a minute now?",
        stages=[
            _stage("ask", "Can we talk for a minute now, is it a good time for you?"),
            _stage("install", BRACKETED),
            _stage("close", "Thank you for your time, have a good day.", mode="say"),
        ],
    )
    paths = {f.partition(": ")[0] for f in script_heal.heal_findings(script, LintContext())}
    assert "stages.1.sounds_like" in paths
    assert "stages.0.sounds_like" in paths
    assert "opening_line" not in paths
    assert not any(p.startswith("step_outcomes") for p in paths)


def test_a_clean_or_hand_written_script_has_nothing_to_repair() -> None:
    assert script_heal.heal_findings(None, LintContext()) == []
    raw = CallScript(schema_version=2, raw_override="Say (this) to them.")
    assert script_heal.heal_findings(raw, LintContext()) == []


# --- the pass, against the database --------------------------------------------------------


async def _account(prefix: str, *, pip_on: bool = True) -> tuple[UUID, UUID]:
    created = await create_org_with_receptionist(
        name="Heal Homes",
        slug=f"heal-{prefix}-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="en-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    if pip_on:
        await turn_pip_on_for_tests(tenant_id)
    return tenant_id, UUID(str(created["agent_id"]))


async def _line(tenant_id: UUID, agent_id: UUID, script: CallScript) -> UUID:
    async with tenant_session(tenant_id) as session:
        return await lines.create_line(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            name="Front desk",
            main_task="Help people install the app.",
            script=script,
            created_by=None,
        )


async def _campaign(tenant_id: UUID, agent_id: UUID, script: CallScript) -> UUID:
    campaign_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, script) "
                "VALUES (:id, :t, :a, 'Installs', 'service', CAST(:s AS jsonb))"
            ),
            {"id": campaign_id, "t": tenant_id, "a": agent_id, "s": script.model_dump_json()},
        )
    return campaign_id


async def _row(tenant_id: UUID, table: str, holder_id: UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (
            await session.execute(
                text(
                    f"SELECT script, script_heal_state, script_heal_inputs, script_heal_fixed, "
                    f"script_heal_at FROM {table} WHERE id = :h"
                ),
                {"h": holder_id},
            )
        ).first()


async def _queue(tenant_id: UUID, kind: script_heal.HolderKind, holder_id: UUID) -> None:
    async with tenant_session(tenant_id) as session:
        await script_heal.queue_now(session, kind, holder_id, tenant_id=tenant_id)
        # Past the debounce, so the pass runs now.
        await session.execute(
            text(
                f"UPDATE {script_heal.table_of(kind)} SET script_heal_at = now() - "
                "interval '5 minutes' WHERE id = :h"
            ),
            {"h": holder_id},
        )


def _writer(monkeypatch: pytest.MonkeyPatch, written: CallScript | None) -> dict[str, Any]:
    seen: dict[str, Any] = {"changes": [], "metered": 0}

    async def write(_brief: Any, **kwargs: Any) -> Any:
        if written is None:
            raise AssertionError("no model may be asked")
        seen["changes"].append(kwargs["change"])
        return SimpleNamespace(
            script=written,
            capability=SimpleNamespace(disclosure=None),
            usage=None,
            model="gemini-2.5-flash-lite",
            earlier=(),
        )

    async def meter(*_args: Any, **_kwargs: Any) -> None:
        seen["metered"] += 1

    async def nothing(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(heal_job, "draft_script", write)
    monkeypatch.setattr(heal_job.crm_assist, "meter_assist", meter)
    monkeypatch.setattr(heal_job.crm_assist, "meter_earlier", nothing)
    monkeypatch.setattr(heal_job.crm_assist, "meter_refusal", meter)
    return seen


@pytest.fixture(autouse=True)
def _no_extra_rounds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(get_settings(), "script_mistake_repair_passes", 0)


def _payload(tenant_id: UUID, kind: str, holder_id: UUID) -> dict[str, str]:
    key = "campaign_id" if kind == "campaign" else "line_id"
    return {"tenant_id": str(tenant_id), key: str(holder_id)}


async def test_a_lines_bracketed_line_is_repaired_saved_and_metered(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _account("line")
    line_id = await _line(tenant_id, agent_id, _script())
    async with tenant_session(tenant_id) as session:
        before = await lines.read_line(session, line_id)
    seen = _writer(monkeypatch, _script(PLAIN))
    await _queue(tenant_id, "line", line_id)
    called_before = datetime.now(UTC) - timedelta(minutes=1)

    outcome = await heal_job.repair_holder_script({}, _payload(tenant_id, "line", line_id))

    assert outcome == "repaired"
    assert "stages.0.sounds_like" in seen["changes"][0]
    assert seen["metered"] == 1
    row = await _row(tenant_id, "inbound_lines", line_id)
    assert CallScript.model_validate(row.script).stages[0].sounds_like == PLAIN
    assert row.script_heal_state == "done"
    assert "brackets" in row.script_heal_fixed
    async with tenant_session(tenant_id) as session:
        after = await lines.read_line(session, line_id)
        states = await script_heal.call_fix_states(
            session,
            campaign_id=None,
            inbound_line_id=line_id,
            call_started_at=called_before,
            kinds=["brackets", "said_again"],
        )
    assert after.version == before.version + 1
    # The call page: the script that call was on is repaired of its brackets since.
    assert states == {"brackets": "repaired"}


async def test_a_campaign_changed_mid_pass_is_never_written_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _account("cas")
    campaign_id = await _campaign(tenant_id, agent_id, _script())
    owners = _script("Open the browser and tell me which page shows (any one).")

    async def write(_brief: Any, **_kwargs: Any) -> Any:
        # The owner (or the step-outcomes pass) saves while Pip writes.
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c"),
                {"s": owners.model_dump_json(), "c": campaign_id},
            )
        return SimpleNamespace(
            script=_script(PLAIN),
            capability=SimpleNamespace(disclosure=None),
            usage=None,
            model="gemini-2.5-flash-lite",
            earlier=(),
        )

    _writer(monkeypatch, _script(PLAIN))
    monkeypatch.setattr(heal_job, "draft_script", write)
    await _queue(tenant_id, "campaign", campaign_id)

    outcome = await heal_job.repair_holder_script({}, _payload(tenant_id, "campaign", campaign_id))

    assert outcome == "moved"
    row = await _row(tenant_id, "campaigns", campaign_id)
    assert CallScript.model_validate(row.script) == owners
    # It asks again, so the new script is read rather than overwritten.
    assert row.script_heal_state == "queued"


async def test_a_clean_script_asks_no_model_and_is_not_read_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _account("clean")
    clean = _script(PLAIN)
    assert script_heal.heal_findings(clean, LintContext(language="en-IN")) == []
    line_id = await _line(tenant_id, agent_id, clean)
    _writer(monkeypatch, None)
    await _queue(tenant_id, "line", line_id)

    assert await heal_job.repair_holder_script({}, _payload(tenant_id, "line", line_id)) == "clean"
    row = await _row(tenant_id, "inbound_lines", line_id)
    assert row.script_heal_state == "done" and row.script_heal_inputs


async def test_with_pip_off_it_is_skipped_and_nothing_is_asked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _account("off", pip_on=False)
    line_id = await _line(tenant_id, agent_id, _script())
    _writer(monkeypatch, None)
    await _queue(tenant_id, "line", line_id)

    assert (
        await heal_job.repair_holder_script({}, _payload(tenant_id, "line", line_id)) == "skipped"
    )
    assert CallScript.model_validate((await _row(tenant_id, "inbound_lines", line_id)).script) == (
        _script()
    )


async def test_a_pip_draft_waiting_on_the_holder_is_never_written_under(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _account("draft")
    line_id = await _line(tenant_id, agent_id, _script())
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET script_proposal = CAST(:p AS jsonb) WHERE id = :h"),
            {
                "p": json.dumps(
                    {
                        "id": str(uuid7()),
                        "status": "drafting",
                        "requested_at": datetime.now(UTC).isoformat(),
                    }
                ),
                "h": line_id,
            },
        )
    _writer(monkeypatch, None)
    await _queue(tenant_id, "line", line_id)

    assert await heal_job.repair_holder_script({}, _payload(tenant_id, "line", line_id)) == (
        "draft_open"
    )


async def test_the_owners_save_queues_one_debounced_pass() -> None:
    tenant_id, agent_id = await _account("save")
    line_id = await _line(tenant_id, agent_id, _script(PLAIN))
    campaign_id = await _campaign(tenant_id, agent_id, _script(PLAIN))
    async with tenant_session(tenant_id) as session:
        await lines.save_script(session, line_id, _script(), author="owner")
        await workspace.save_script(session, campaign_id, _script(), author="owner")
    line = await _row(tenant_id, "inbound_lines", line_id)
    campaign = await _row(tenant_id, "campaigns", campaign_id)
    assert line.script_heal_state == "queued" and campaign.script_heal_state == "queued"
    # Inside the debounce the pass defers itself rather than read a script still being saved.
    assert await heal_job._due(tenant_id, "line", line_id) is not None


async def test_the_sweep_queues_an_unchecked_script_and_leaves_a_checked_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _account("sweep")
    unchecked = await _line(tenant_id, agent_id, _script())
    checked = await _line(tenant_id, agent_id, _script(PLAIN))
    _writer(monkeypatch, None)
    await _queue(tenant_id, "line", checked)
    assert await heal_job.repair_holder_script({}, _payload(tenant_id, "line", checked)) == "clean"
    monkeypatch.setattr(heal_job, "HOLDERS_PER_TICK", 10_000)

    await heal_job.sweep_script_heal({})

    assert (await _row(tenant_id, "inbound_lines", unchecked)).script_heal_state == "queued"
    assert (await _row(tenant_id, "inbound_lines", checked)).script_heal_state == "done"


async def test_the_call_page_says_the_script_was_repaired_instead_of_our_team_told() -> None:
    """FAILS IF: "What went wrong" says "Our team has been told" for a mistake the script the
    call was on has since been repaired of, or is being repaired of."""
    tenant_id, agent_id = await _account("page")
    line_id = await _line(tenant_id, agent_id, _script())
    started = datetime.now(UTC) - timedelta(minutes=5)
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, inbound_line_id, created_at, updated_at) VALUES (:id, :t, :a, :e, "
                "'inbound', 'completed', :s, :l, now(), now())"
            ),
            {
                "id": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"x_{call_id.hex}",
                "s": started,
                "l": line_id,
            },
        )
    await call_mistakes.record_call_mistakes(
        tenant_id=tenant_id,
        agent_id=agent_id,
        call_id=call_id,
        call_started_at=started,
        found={"said_again": 0, "same_opening": 1},
    )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE inbound_lines SET script_heal_state = 'done' WHERE id = :h"),
            {"h": line_id},
        )
    headers = await _org_headers(tenant_id)
    path = f"/v1/calls/{call_id}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://api") as http:
        before = (await http.get(path, headers=headers)).json()["mistakes"]
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text(
                    "UPDATE inbound_lines SET script_heal_fixed = CAST(:f AS jsonb), "
                    "script_heal_state = 'queued', script_heal_at = now() WHERE id = :h"
                ),
                {"f": json.dumps({"said_again": datetime.now(UTC).isoformat()}), "h": line_id},
            )
        after = (await http.get(path, headers=headers)).json()["mistakes"]
    assert {m["kind"]: m["fix"] for m in after} == {
        "said_again": "repaired",
        "same_opening": "repairing",
    }
    assert {m["fix"] for m in before} == {"told"}


async def test_a_tenant_never_reads_another_tenants_repair_state() -> None:
    tenant_id, agent_id = await _account("rls-a")
    other_id, _ = await _account("rls-b")
    line_id = await _line(tenant_id, agent_id, _script())
    async with tenant_session(other_id) as session:
        states = await script_heal.call_fix_states(
            session,
            campaign_id=None,
            inbound_line_id=line_id,
            call_started_at=None,
            kinds=["brackets"],
        )
        assert states == {}
        assert not await script_heal.pending(session, "line", line_id)
