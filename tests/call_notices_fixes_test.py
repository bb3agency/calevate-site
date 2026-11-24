"""D-1021's account notice switches, where the first build left a gap.

- Switching a notice on measures every first words a call can speak, not only each agent's
  answering opening: a "both" agent's placed-call opening, each Inbound line's openings and
  each campaign's openings A and B, and the refusal names the one to fix.
- One line or campaign the platform refuses does not hold back its agent's other holders.
- A call we place says the first words our rows compose now, not the greeting the engine
  still holds from before a flip.
- The holder re-weave saves under the holder's row lock, in the campaign's own language.
- Each flip queues fresh rewrites (off, on, off is three flips), and a weave no model
  answered is retried.
- The repair job `f2477c8d623d` queues puts a restored switch on the calls and records it.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.agents import script_builder
from apps.api.agents import service as agents_service
from apps.api.agents.engine_limits import NOTICE_NEEDS_ROOM
from apps.api.agents.publishing import set_account_notices
from apps.api.campaigns import service as campaigns
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.inbound import lines as inbound_lines
from apps.workers import campaign_dispatch, opening_line
from apps.workers import opening_notices as weave_worker
from arq import Retry
from calevate_shared.call_script import SCRIPT_SCHEMA_VERSION, CallScript
from calevate_shared.invisible_text import plain_joins
from calevate_shared.opening_notices import NONE_SAID
from sqlalchemy import text
from tests.call_notices_holders_test import PLAIN as HOLDER_PLAIN
from tests.call_notices_holders_test import _campaign, _jobs, _line, _script, _switch
from tests.campaign_second_opening_dispatch_test import _RecordingEngine
from tests.dispatch_budget_test import (
    _daytime,  # noqa: F401  (autouse: the dial runs inside calling hours)
    _dlt_rows,
    _launched_campaign,
    _settle_what_this_module_started,  # noqa: F401  (autouse: leaves no running campaign)
    _tenant,
)
from tests.opening_notices_test import PLAIN, _agent, _on_thinnest, _weave_jobs

pytestmark = pytest.mark.anyio


def _script_json(opening: str, placed: str = "") -> str:
    return CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION,
        opening_line=opening,
        outbound_opening_line=placed,
        goal="Confirm the booking.",
    ).model_dump_json()


async def _set(tenant_id: uuid.UUID, sql: str, **params: Any) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(text(sql), params)


async def _account_ai(tenant_id: uuid.UUID) -> bool:
    async with tenant_session(tenant_id) as session:
        return bool(
            (
                await session.execute(
                    text("SELECT notice_ai_enabled FROM organizations WHERE id = :t"),
                    {"t": tenant_id},
                )
            ).scalar_one()
        )


async def _refusal(tenant_id: uuid.UUID) -> Any:
    with _on_thinnest(), pytest.raises(ProblemError) as refused:
        await set_account_notices(
            tenant_id=tenant_id, ai_disclosure_enabled=True, recording_notice_enabled=None
        )
    assert refused.value.code == NOTICE_NEEDS_ROOM
    assert await _account_ai(tenant_id) is False, "nothing was switched"
    return refused.value.extensions


# --- every first words is measured -------------------------------------------------------


async def test_switching_on_is_refused_naming_the_line_whose_opening_has_no_room() -> None:
    tenant_id, agent_id = await _tenant()
    await _switch(tenant_id, ai=False)
    line_id = await _line(tenant_id, agent_id)
    await _set(
        tenant_id,
        "UPDATE inbound_lines SET script = CAST(:s AS jsonb) WHERE id = :l",
        s=_script_json("a" * 195),
        l=line_id,
    )
    named = await _refusal(tenant_id)
    assert (named.line_id, named.line_name, named.campaign_id) == (line_id, "Bookings", None)
    assert named.agent_id == agent_id


async def test_a_lines_placed_call_opening_is_measured_too() -> None:
    tenant_id, agent_id = await _tenant()
    await _switch(tenant_id, ai=False)
    line_id = await _line(tenant_id, agent_id)
    await _set(
        tenant_id,
        "UPDATE inbound_lines SET script = CAST(:s AS jsonb) WHERE id = :l",
        s=_script_json("Namaskaram.", placed="p" * 295),
        l=line_id,
    )
    assert (await _refusal(tenant_id)).line_id == line_id


async def test_switching_on_is_refused_naming_the_campaign_and_which_opening() -> None:
    tenant_id, agent_id = await _tenant()
    await _switch(tenant_id, ai=False)
    campaign_id = await _campaign(tenant_id, agent_id)
    await _set(
        tenant_id,
        "UPDATE campaigns SET script = CAST(:s AS jsonb), opening_b = NULL WHERE id = :c",
        s=_script_json("a" * 195),
        c=campaign_id,
    )
    named = await _refusal(tenant_id)
    assert (named.campaign_id, named.campaign_opening) == (campaign_id, "a")
    assert named.campaign_name == "Booking reminders" and named.line_id is None

    await _set(
        tenant_id,
        "UPDATE campaigns SET script = CAST(:s AS jsonb), opening_b = :b WHERE id = :c",
        s=_script_json("Namaskaram."),
        b="b" * 295,
        c=campaign_id,
    )
    named = await _refusal(tenant_id)
    assert (named.campaign_id, named.campaign_opening) == (campaign_id, "b")


async def test_a_both_agents_placed_call_opening_is_measured() -> None:
    tenant_id, agent_id = await _agent(PLAIN)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE agents SET direction = 'both' WHERE id = :a"), {"a": agent_id}
        )
        await script_builder.save_agent_script(
            session,
            tenant_id=tenant_id,
            agent_id=agent_id,
            script=CallScript(
                schema_version=SCRIPT_SCHEMA_VERSION,
                opening_line=PLAIN,
                outbound_opening_line="p" * 295,
                goal="Take the order.",
            ),
            notes=None,
            created_by=None,
        )
    named = await _refusal(tenant_id)
    assert named.agent_id == agent_id and named.line_id is None and named.campaign_id is None


# --- one holder's refusal stays its own --------------------------------------------------


async def test_one_line_the_platform_refuses_does_not_hold_back_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    refused_line, kept_line = await _line(tenant_id, agent_id), await _line(tenant_id, agent_id)
    await _set(
        tenant_id,
        "UPDATE inbound_lines SET engine_agent_ref = 'ref-' || id::text, published_at = now() "
        "WHERE agent_id = :a",
        a=agent_id,
    )
    published: list[uuid.UUID] = []
    alarms: list[tuple[str, dict[str, str]]] = []

    async def publish_line(_session: Any, *, tenant_id: uuid.UUID, line_id: uuid.UUID) -> str:
        if line_id == refused_line:
            raise ProblemError.business_rule("engine_greeting_too_long", "Too long.")
        published.append(line_id)
        return "ref"

    monkeypatch.setattr(agents_service, "publish_line", publish_line)
    monkeypatch.setattr(
        agents_service, "alert", lambda _stage, code, **kw: alarms.append((code, kw))
    )
    async with tenant_session(tenant_id) as session:
        count = await agents_service.republish_lines(
            session, tenant_id=tenant_id, agent_id=agent_id
        )
    assert (count, published) == (1, [kept_line])
    assert [(code, kw["holder_id"]) for code, kw in alarms] == [
        ("holder_republish_failed", str(refused_line))
    ]


async def test_one_campaign_the_platform_refuses_does_not_hold_back_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    refused, kept = await _campaign(tenant_id, agent_id), await _campaign(tenant_id, agent_id)
    await _set(
        tenant_id,
        "UPDATE campaigns SET engine_agent_ref = 'ref-' || id::text, status = 'paused' "
        "WHERE agent_id = :a",
        a=agent_id,
    )
    published: list[uuid.UUID] = []

    async def publish(_session: Any, *, tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> str:
        if campaign_id == refused:
            raise RuntimeError("platform down")
        published.append(campaign_id)
        return "ref"

    monkeypatch.setattr(agents_service, "publish_campaign_agent", publish)
    monkeypatch.setattr(agents_service, "alert", lambda *_a, **_k: None)
    try:
        async with tenant_session(tenant_id) as session:
            count = await agents_service.republish_campaign_agents(
                session, tenant_id=tenant_id, agent_id=agent_id
            )
        assert (count, published) == (1, [kept])
    finally:
        await _set(
            tenant_id,
            "UPDATE campaigns SET status = 'cancelled', engine_agent_ref = NULL "
            "WHERE agent_id = :a",
            a=agent_id,
        )


# --- a placed call says what our rows say --------------------------------------------------


async def test_a_campaign_call_says_the_first_words_our_rows_compose_now(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: a dial with no first words of its own leaves the engine to speak the greeting
    it holds, which after a flip is the old notice until the live apply reaches it."""
    tenant_id, agent_id = await _tenant()
    number_id, template_id = await _dlt_rows(tenant_id, agent_id)
    campaign_id = await _launched_campaign(
        tenant_id, agent_id, number_id, template_id, name="Held greeting", phones=("9876690031",)
    )
    await _set(
        tenant_id,
        "UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c",
        s=_script_json("Namaskaram, a quick call about your booking."),
        c=campaign_id,
    )
    await _switch(tenant_id, ai=True)
    engine = _RecordingEngine()
    monkeypatch.setattr("apps.api.agents.service.get_engine", lambda: engine)
    monkeypatch.setattr(campaign_dispatch, "opening_variant", lambda _c, _b: None)

    async def composed() -> tuple[str | None, str]:
        async with tenant_session(tenant_id) as session:
            agent = await agents_service._load_agent(session, tenant_id, agent_id)
            words = await agents_service.held_greeting(
                session, tenant_id=tenant_id, agent=agent, campaign_id=campaign_id
            )
        return words, plain_joins(str(agent["ai_disclosure_line"]).strip())

    result = await campaign_dispatch._dispatch_for_campaign(
        tenant_id, campaign_id, 3, campaigns.DEFAULT_RETRY_POLICY
    )
    assert result["dialled"] == 1, result
    words, ai_line = await composed()
    assert engine.openings == [words]
    assert words is not None and ai_line in words
    # Switched off and not yet republished: the next dial's words no longer say it.
    await _switch(tenant_id, ai=False)
    words, ai_line = await composed()
    assert words is not None and ai_line not in words


# --- the holder re-weave --------------------------------------------------------------------


def _stub_writer(monkeypatch: pytest.MonkeyPatch, line: str) -> list[Any]:
    briefs: list[Any] = []

    async def fake_write(brief: Any, **_kw: Any) -> Any:
        briefs.append(brief)
        value = opening_line.WrittenOpening(line=line, said=NONE_SAID)
        return SimpleNamespace(value=value, capability=None, earlier=(), model=None)

    async def no_meter(_tenant_id: uuid.UUID, _spends: Any) -> None:
        return None

    monkeypatch.setattr(weave_worker, "write_opening", fake_write)
    monkeypatch.setattr(weave_worker, "_meter", no_meter)
    return briefs


async def test_an_owners_save_during_the_holder_reweave_is_never_written_over(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """FAILS IF: the re-weave reads the holder's stamp outside its row lock. The owner holds
    the line's lock and saves while the job runs; the job waits, then reads the owner's
    script and stands down rather than saving the old line's rewrite over it."""
    tenant_id, agent_id = await _tenant()
    await _switch(tenant_id, ai=True)
    line_id = await _line(tenant_id, agent_id)
    await set_account_notices(
        tenant_id=tenant_id, ai_disclosure_enabled=False, recording_notice_enabled=None
    )
    [job] = [j for j in await _jobs(tenant_id) if j["kind"] == "line"]
    _stub_writer(monkeypatch, HOLDER_PLAIN)
    owners = CallScript(
        schema_version=SCRIPT_SCHEMA_VERSION, opening_line="The owner's own words.", goal="Own."
    )
    locked, release = asyncio.Event(), asyncio.Event()

    async def owner_saves() -> None:
        async with tenant_session(tenant_id) as session:
            await session.execute(
                text("SELECT 1 FROM inbound_lines WHERE id = :l FOR UPDATE"), {"l": line_id}
            )
            locked.set()
            await release.wait()
            await inbound_lines.save_script(session, line_id, owners, author="owner")

    owner = asyncio.create_task(owner_saves())
    await locked.wait()
    weave = asyncio.create_task(weave_worker.weave_holder_opening_notices({}, job))
    await asyncio.sleep(0.5)
    release.set()
    await owner
    assert await weave == "stale"
    assert (await _script(tenant_id, "inbound_lines", line_id)).opening_line == (
        "The owner's own words."
    )


async def test_a_campaign_in_its_own_language_is_rewoven_in_that_language(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, agent_id = await _tenant()
    await _switch(tenant_id, ai=True)
    campaign_id = await _campaign(tenant_id, agent_id)
    await _set(
        tenant_id,
        "UPDATE campaigns SET settings_overrides = CAST(:o AS jsonb) WHERE id = :c",
        o=json.dumps({"language_primary": "hi-IN"}),
        c=campaign_id,
    )
    await set_account_notices(
        tenant_id=tenant_id, ai_disclosure_enabled=False, recording_notice_enabled=None
    )
    [job] = [j for j in await _jobs(tenant_id) if j["kind"] == "campaign"]
    briefs = _stub_writer(monkeypatch, HOLDER_PLAIN)
    assert await weave_worker.weave_holder_opening_notices({}, job) == "woven"
    assert briefs[0].language == "hi-IN"


# --- each flip is new work; a silent writer is asked again ----------------------------------


async def test_on_off_on_queues_the_rewrite_again_on_the_second_on() -> None:
    """FAILS IF: the rewrite key is once per switch STATE, so the second "on" dedupes against
    the first and the opening never says the notice again."""
    with _on_thinnest():
        tenant_id, agent_id = await _agent(PLAIN)
        for on in (True, False, True):
            await set_account_notices(
                tenant_id=tenant_id, ai_disclosure_enabled=on, recording_notice_enabled=None
            )
        assert len(await _weave_jobs(tenant_id, agent_id)) == 2


async def test_a_weave_no_model_answered_is_retried_and_then_left(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with _on_thinnest():
        tenant_id, agent_id = await _agent(PLAIN)
        await set_account_notices(
            tenant_id=tenant_id, ai_disclosure_enabled=True, recording_notice_enabled=None
        )
        [job] = await _weave_jobs(tenant_id, agent_id)

        async def silent(_brief: Any, **_kw: Any) -> Any:
            raise ProblemError(
                kind="dependency",
                code="assist_provider_unavailable",
                title="AI assistance is not available",
                detail="No model answered.",
            )

        async def no_meter(_tenant_id: uuid.UUID, _spends: Any) -> None:
            return None

        monkeypatch.setattr(weave_worker, "write_opening", silent)
        monkeypatch.setattr(weave_worker, "_meter", no_meter)
        with pytest.raises(Retry):
            await weave_worker.weave_opening_notices({"job_try": 1}, job)
        assert await weave_worker.weave_opening_notices({"job_try": 3}, job) == "unwritten"


# --- the repair job -----------------------------------------------------------------------


async def _audit(tenant_id: uuid.UUID) -> list[tuple[str, str | None]]:
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT action, object_id FROM audit_log WHERE tenant_id = :t ORDER BY at"),
                {"t": str(tenant_id)},
            )
        ).all()
    return [(str(r[0]), r[1]) for r in rows]


async def test_the_repair_job_puts_a_restored_switch_on_the_calls_and_records_it() -> None:
    tenant_id, _agent_id = await _tenant()
    await _switch(tenant_id, ai=True)
    payload = {"tenant_id": str(tenant_id), "ai": True, "recording": False}
    assert await weave_worker.refresh_account_notices({}, payload) == "queued"
    async with untenanted_session() as session:
        reasons = (
            (
                await session.execute(
                    text("SELECT reasons FROM live_apply_runs WHERE tenant_id = :t"),
                    {"t": tenant_id},
                )
            )
            .scalars()
            .all()
        )
    assert any("call_notices_repair" in list(r) for r in reasons)
    assert ("organization.ai_disclosure_enabled", str(tenant_id)) in await _audit(tenant_id)

    # The owner switched it off before the job ran: their choice stands, nothing is queued.
    await _switch(tenant_id, ai=False)
    assert await weave_worker.refresh_account_notices({}, payload) == "switched_off_since"
