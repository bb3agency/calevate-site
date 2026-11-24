"""Which calls alert after they end belongs to each campaign and inbound line (D-1040).

What a call notes is its job's list (D-1028), so an answer alerts only on the calls of the job
whose rule ticked it: the same key on another campaign can mean something else. The agent keeps
only its in-call switch, which reaches every engine agent its jobs hold (D-1019).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.errors import ProblemError
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.reliability import engine_actions
from apps.api.team_alerts import service
from apps.api.team_alerts.service import FieldTrigger, HolderRef, Rule
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _tenant
from tests.team_alerts_test import _alert_payloads, _verified_contact

pytestmark = pytest.mark.rls

VISIT_DAY: dict[str, Any] = {
    "key": "visit_day",
    "label": "Visit day",
    "type": "enum",
    "enum_values": ["saturday", "sunday"],
    "reason": "when they can come",
}
BUDGET: dict[str, Any] = {
    "key": "budget_band",
    "label": "Budget band",
    "type": "enum",
    "enum_values": ["under_20l", "20l_50l", "over_50l"],
    "reason": "what they can spend",
}


async def _campaign(t: Tenant, fields: list[dict[str, Any]], name: str = "Site visits") -> UUID:
    campaign_id = uuid7()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, status, "
                "extraction_fields) VALUES (:id, :t, :a, :n, 'service', 'draft', "
                "CAST(:f AS jsonb))"
            ),
            {
                "id": campaign_id,
                "t": t.tenant_id,
                "a": t.agent_id,
                "n": name,
                "f": json.dumps(fields),
            },
        )
    return campaign_id


async def _line(t: Tenant, fields: list[dict[str, Any]]) -> UUID:
    line_id = uuid7()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO inbound_lines (id, tenant_id, agent_id, name, extraction_fields, "
                "created_at, updated_at) VALUES (:id, :t, :a, 'Front desk', CAST(:f AS jsonb), "
                "now(), now())"
            ),
            {"id": line_id, "t": t.tenant_id, "a": t.agent_id, "f": json.dumps(fields)},
        )
    return line_id


async def _call(
    t: Tenant, *, campaign_id: UUID | None = None, inbound_line_id: UUID | None = None
) -> UUID:
    call_id = uuid7()
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, campaign_id, inbound_line_id, "
                "engine_call_id, direction, status, from_e164, to_e164, started_at, created_at, "
                "updated_at) VALUES (:id, :t, :a, :g, :l, :e, 'outbound', 'completed', "
                "'+914000000000', '+919812345678', now(), now(), now())"
            ),
            {
                "id": call_id,
                "t": t.tenant_id,
                "a": t.agent_id,
                "g": campaign_id,
                "l": inbound_line_id,
                "e": f"tah-{call_id.hex}",
            },
        )
    return call_id


async def _after(t: Tenant, call_id: UUID, data: dict[str, Any]) -> str:
    async with tenant_session(t.tenant_id) as session:
        return await service.queue_after_call(
            session,
            tenant_id=t.tenant_id,
            agent_id=t.agent_id,
            call_id=call_id,
            lead_id=None,
            hot=False,
            outcome_key=None,
            outcome_label=None,
            data=data,
            labels={"visit_day": "Visit day", "budget_band": "Budget band"},
        )


async def _save(t: Tenant, job: HolderRef, rule: Rule) -> service.JobRuleView:
    async with tenant_session(t.tenant_id) as session:
        return await service.save_job_rule(session, job, rule)


async def test_a_campaigns_answer_alerts_on_its_calls_and_not_on_another_campaigns() -> None:
    """End to end through `queue_after_call`, the post-call pipeline's step 6."""
    t = await _tenant(with_line=False)
    await _verified_contact(t)
    visits = await _campaign(t, [VISIT_DAY])
    other = await _campaign(t, [VISIT_DAY], name="Open house")
    view = await _save(
        t,
        HolderRef("campaign", visits),
        Rule(on_fields=(FieldTrigger("visit_day", ("saturday",)),)),
    )
    assert view.saved and [(f.key, f.values) for f in view.fields] == [
        ("visit_day", ("saturday", "sunday"))
    ]
    # The other campaign never saved a rule: every positive outcome, and no answer.
    async with tenant_session(t.tenant_id) as session:
        untouched = await service.read_job_rule(session, HolderRef("campaign", other))
    assert not untouched.saved and untouched.rule.on_fields == ()

    on_visits = await _call(t, campaign_id=visits)
    assert await _after(t, on_visits, {"visit_day": "sunday"}) == "not_worth_telling"
    assert await _after(t, on_visits, {"visit_day": "saturday"}) == "queued"
    on_other = await _call(t, campaign_id=other)
    assert await _after(t, on_other, {"visit_day": "saturday"}) == "not_worth_telling", (
        "the same key and answer on another campaign is that campaign's rule, not this one's"
    )
    async with tenant_session(t.tenant_id) as session:
        reasons = (
            await session.execute(
                text("SELECT reasons FROM team_alerts WHERE call_id = :c"), {"c": on_visits}
            )
        ).scalar_one()
    assert reasons == [
        {"kind": "field", "key": "visit_day", "label": "Visit day", "values": ["saturday"]}
    ]
    assert len(await _alert_payloads(t.tenant_id)) == 1


async def test_a_lines_answer_alerts_on_its_calls() -> None:
    t = await _tenant(with_line=False)
    await _verified_contact(t)
    line_id = await _line(t, [VISIT_DAY])
    await _save(
        t, HolderRef("line", line_id), Rule(on_fields=(FieldTrigger("visit_day", ("sunday",)),))
    )
    assert await _after(t, await _call(t, inbound_line_id=line_id), {"visit_day": "sunday"}) == (
        "queued"
    )


async def test_an_agent_level_leftover_no_longer_alerts() -> None:
    """A rule row from before D-1040 still holds the agent's outcomes and answers; nothing
    reads them, and a call with no job alerts on no answer."""
    t = await _tenant(with_line=False)
    await _verified_contact(t)
    campaign_id = await _campaign(t, [BUDGET])
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO team_alert_rules (id, tenant_id, agent_id, on_outcomes, on_fields, "
                "created_at, updated_at) VALUES (:id, :t, :a, '[]'::jsonb, CAST(:f AS jsonb), "
                "now(), now())"
            ),
            {
                "id": uuid7(),
                "t": t.tenant_id,
                "a": t.agent_id,
                "f": json.dumps([{"key": "budget_band", "values": ["over_50l"]}]),
            },
        )
    assert await _after(t, await _call(t), {"budget_band": "over_50l"}) == "not_worth_telling"
    held = await _call(t, campaign_id=campaign_id)
    assert await _after(t, held, {"budget_band": "over_50l"}) == "not_worth_telling", (
        "the campaign never ticked it, so the agent's old tick does not alert its calls"
    )
    async with tenant_session(t.tenant_id) as session:
        agent = await service.read_agent_alerts(session, agent_id=t.agent_id)
    assert not agent.in_call
    assert [(j.ref, j.name) for j in agent.jobs] == [
        (HolderRef("campaign", campaign_id), "Site visits")
    ]


async def test_a_choice_off_the_jobs_list_is_refused_and_a_dropped_one_is_not_shown() -> None:
    t = await _tenant(with_line=False)
    campaign_id = await _campaign(t, [VISIT_DAY])
    job = HolderRef("campaign", campaign_id)
    for wrong in (
        FieldTrigger("visit_day", ("monday",)),
        FieldTrigger("budget_band", ("over_50l",)),
    ):
        with pytest.raises(ProblemError) as refused:
            await _save(t, job, Rule(on_fields=(wrong,)))
        assert refused.value.code == "team_alert_choice_unknown"

    await _save(t, job, Rule(on_fields=(FieldTrigger("visit_day", ("saturday",)),)))
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET extraction_fields = '[]'::jsonb WHERE id = :c"),
            {"c": campaign_id},
        )
        view = await service.read_job_rule(session, job)
    assert view.saved and view.rule.on_fields == (), "a detail no longer noted is not offered"


async def test_another_tenants_campaign_is_neither_read_nor_written() -> None:
    t, other = await _tenant(with_line=False), await _tenant(with_line=False)
    theirs = HolderRef("campaign", await _campaign(t, [VISIT_DAY]))
    await _save(t, theirs, Rule(on_fields=(FieldTrigger("visit_day", ("saturday",)),)))
    async with tenant_session(other.tenant_id) as session:
        with pytest.raises(ProblemError) as unread:
            await service.read_job_rule(session, theirs)
        assert unread.value.code == "not_found"
        with pytest.raises(ProblemError):
            await service.save_job_rule(session, theirs, Rule())
        for table in ("campaigns", "inbound_lines"):
            count = (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar()
            assert count == 0, table
    async with tenant_session(t.tenant_id) as session:
        kept = await service.read_job_rule(session, theirs)
    assert kept.rule.on_fields == (FieldTrigger("visit_day", ("saturday",)),)


async def test_the_in_call_switch_reaches_every_engine_agent_its_jobs_hold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Since D-1019 each campaign and line holds its own engine agent; switching the agent's
    in-call action on must reach all of them, not the newest only."""
    t = await _tenant(with_line=False)
    await _verified_contact(t)
    campaign_id = await _campaign(t, [VISIT_DAY])
    line_id = await _line(t, [VISIT_DAY])
    refs = {f"ag_c_{campaign_id.hex[:8]}": campaign_id, f"ag_l_{line_id.hex[:8]}": line_id}
    async with tenant_session(t.tenant_id) as session:
        for ref, holder in refs.items():
            await session.execute(
                text(
                    "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, "
                    "agent_id, campaign_id, inbound_line_id, active) VALUES ('thinnest', :r, :t, "
                    ":a, :g, :l, true)"
                ),
                {
                    "r": ref,
                    "t": t.tenant_id,
                    "a": t.agent_id,
                    "g": holder if holder == campaign_id else None,
                    "l": holder if holder == line_id else None,
                },
            )
    synced: list[str] = []

    async def _ensure(session: Any, *, engine: str, engine_agent_ref: str, **_: Any) -> None:
        names = [
            d.name
            for d in await engine_actions.client_definitions(
                session, engine, engine_agent_ref, t.agent_id
            )
        ]
        assert service.TEAM_ACTION_NAME in names, engine_agent_ref
        synced.append(engine_agent_ref)

    monkeypatch.setattr(engine_actions, "ensure_agent_actions", _ensure)
    async with tenant_session(t.tenant_id) as session:
        view = await service.save_in_call(
            session, tenant_id=t.tenant_id, agent_id=t.agent_id, in_call=True
        )
    assert view.in_call_live
    assert sorted(synced) == sorted(refs), "every campaign's and line's engine agent"


def _migration() -> ModuleType:
    versions = Path(__file__).resolve().parents[1] / "alembic" / "versions"
    path = next(versions.glob("b8e3f1c6d2a4_*.py"))
    spec = importlib.util.spec_from_file_location("_alerts_per_job", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def test_the_migration_copies_each_agents_ticks_onto_its_jobs() -> None:
    """An agent-level answer lands on every job whose list has it, with the same values; a
    D-1007 answer lands on its own job alone; the outcomes on every job; nothing ticked is
    lost. Rows are read and written with the migration's own statements."""
    migration = _migration()
    t = await _tenant(with_line=False)
    both = await _campaign(t, [BUDGET, VISIT_DAY])
    budget_only = await _campaign(t, [BUDGET], name="Loans")
    line_id = await _line(t, [VISIT_DAY])
    async with tenant_session(t.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO team_alert_rules (id, tenant_id, agent_id, on_outcomes, on_fields, "
                "in_call, created_at, updated_at) VALUES (:id, :t, :a, '[\"interested\"]'::jsonb, "
                "CAST(:f AS jsonb), true, now(), now())"
            ),
            {
                "id": uuid7(),
                "t": t.tenant_id,
                "a": t.agent_id,
                "f": json.dumps(
                    [
                        {"key": "budget_band", "values": ["over_50l", "no_longer_offered"]},
                        {"key": "visit_day", "values": ["sunday"], "campaign_id": str(both)},
                        {
                            "key": "visit_day",
                            "values": ["saturday"],
                            "inbound_line_id": str(line_id),
                        },
                    ]
                ),
            },
        )
        rules = (await session.execute(migration._RULES)).all()
        for key, read, write in (
            ("campaign_id", migration._CAMPAIGNS, migration._SET_CAMPAIGN),
            ("inbound_line_id", migration._LINES, migration._SET_LINE),
        ):
            jobs = (await session.execute(read)).all()
            for job_id, rule in migration.planned(rules, jobs, key):
                await session.execute(write, {"rule": json.dumps(rule), "id": job_id})

    async def _rule(job: HolderRef) -> service.JobRuleView:
        async with tenant_session(t.tenant_id) as session:
            return await service.read_job_rule(session, job)

    on_both = await _rule(HolderRef("campaign", both))
    assert on_both.saved and on_both.rule == Rule(
        on_outcomes=("interested",),
        on_fields=(
            FieldTrigger("budget_band", ("over_50l",)),
            FieldTrigger("visit_day", ("sunday",)),
        ),
    )
    assert (await _rule(HolderRef("campaign", budget_only))).rule == Rule(
        on_outcomes=("interested",), on_fields=(FieldTrigger("budget_band", ("over_50l",)),)
    )
    assert (await _rule(HolderRef("line", line_id))).rule == Rule(
        on_outcomes=("interested",), on_fields=(FieldTrigger("visit_day", ("saturday",)),)
    )
    async with tenant_session(t.tenant_id) as session:
        assert await service.load_in_call(session, t.agent_id), "the in-call switch stays"
        again = (await session.execute(migration._CAMPAIGNS)).all()
    assert again == [], "a job with a rule is not copied onto twice"
