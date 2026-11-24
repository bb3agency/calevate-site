"""The account-wide Improve page (founder, 24-25 Nov 2026): each section's aggregate on fixture
calls, another account reading none of it, money as NUMERIC rupees, and the weekly summary
written once per week from counts, never from what was said on a call.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.campaigns import account_improve as acct
from apps.api.campaigns import weekly_summary
from apps.api.campaigns.account_improve_routes import account_improve
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.workers import chat
from apps.workers import weekly_summary as worker
from apps.workers.background_leg import background_leg
from sqlalchemy import text
from tests.dispatch_budget_test import _tenant
from tests.holder_diagnosis_test import _line, _mistake
from tests.step_outcomes_test import _campaign

pytestmark = pytest.mark.anyio

OUR_NUMBER = "+918000000001"
#: Words that stand for what a caller said; no prompt or stored figure may carry them.
SPOKEN = "SPOKEN-WORDS-NEVER-SENT"


async def _calls(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    n: int,
    *,
    campaign_id: uuid.UUID | None = None,
    line_id: uuid.UUID | None = None,
    outcome: str | None = "answered",
    goal: str | None = None,
    from_e164: str | None = OUR_NUMBER,
    to_e164: str | None = None,
    started: datetime | None = None,
    duration_s: int = 90,
    charge: Decimal | None = None,
) -> list[uuid.UUID]:
    made = []
    async with tenant_session(tenant_id) as session:
        for _ in range(n):
            call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, campaign_id, inbound_line_id, outcome_tag, goal_reached, duration_s, "
                    "from_e164, to_e164, summary, headline, started_at, created_at, updated_at) "
                    "VALUES (:id, :t, :a, :e, :d, 'completed', :g, :l, :o, :goal, :dur, :f, :to, "
                    ":words, :words, :s, now(), now())"
                ),
                {
                    "id": call_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"exec_{uuid.uuid4().hex[:12]}",
                    "d": "inbound" if line_id else "outbound",
                    "g": campaign_id,
                    "l": line_id,
                    "o": outcome,
                    "goal": goal,
                    "dur": duration_s,
                    "f": from_e164,
                    "to": to_e164,
                    "words": SPOKEN,
                    "s": started or datetime.now(UTC),
                },
            )
            if charge is not None:
                await session.execute(
                    text(
                        "INSERT INTO credit_ledger (id, tenant_id, delta, reason, ref, "
                        "balance_after, occurred_at, created_at) VALUES (gen_random_uuid(), :t, "
                        ":d, 'usage', :ref, 0, now(), now())"
                    ),
                    {"t": tenant_id, "d": -charge, "ref": str(call_id)},
                )
            made.append(call_id)
    return made


async def _script(tenant_id: uuid.UUID, campaign_id: uuid.UUID, words: int, steps: int) -> None:
    script = {
        "opening_line": " ".join(["word"] * words),
        "steps": [{"title": f"Step {n}", "goal": "", "instructions": ""} for n in range(steps)],
    }
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script = CAST(:s AS jsonb) WHERE id = :c"),
            {"s": json.dumps(script), "c": campaign_id},
        )


async def _read(tenant_id: uuid.UUID, *, spend: bool = True) -> Any:
    async with tenant_session(tenant_id) as session:
        return await account_improve(session, include_spend=spend)


# --- 1. Number health ----------------------------------------------------------------------


async def test_a_number_whose_answer_rate_falls_sharply_is_flagged() -> None:
    """FAILS IF: a calling number answered half the time for a month and a tenth of the time
    last week is not flagged, or one with too few calls is judged at all."""
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    earlier = datetime.now(UTC) - timedelta(days=14)
    await _calls(tenant_id, agent_id, 40, campaign_id=campaign_id, started=earlier)
    await _calls(
        tenant_id, agent_id, 40, campaign_id=campaign_id, outcome="missed", started=earlier
    )
    await _calls(tenant_id, agent_id, 3, campaign_id=campaign_id)
    await _calls(tenant_id, agent_id, 30, campaign_id=campaign_id, outcome="missed")
    quiet = "+918000000002"
    await _calls(tenant_id, agent_id, 5, campaign_id=campaign_id, from_e164=quiet)

    found = {n.e164: n for n in (await _read(tenant_id)).numbers.numbers}
    ours = found[OUR_NUMBER]
    assert ours.baseline_rate == 0.5 and ours.recent_rate == round(3 / 33, 4)
    assert ours.dropped is True
    assert sum(w.placed for w in ours.weeks) == 113
    assert found[quiet].recent_rate is None and found[quiet].dropped is False


async def test_a_steady_number_is_not_flagged() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    earlier = datetime.now(UTC) - timedelta(days=14)
    await _calls(tenant_id, agent_id, 35, campaign_id=campaign_id, started=earlier)
    await _calls(
        tenant_id, agent_id, 35, campaign_id=campaign_id, outcome="missed", started=earlier
    )
    await _calls(tenant_id, agent_id, 16, campaign_id=campaign_id)
    await _calls(tenant_id, agent_id, 16, campaign_id=campaign_id, outcome="missed")
    (ours,) = (await _read(tenant_id)).numbers.numbers
    assert ours.dropped is False


# --- 3 and 8. Compare, best, what is different, cost per goal ------------------------------


async def test_the_best_campaign_is_named_with_what_is_measurably_different() -> None:
    """FAILS IF: the best campaign is not the one reaching its goal most often, or a
    difference is claimed that its script does not show."""
    tenant_id, agent_id = await _tenant()
    best = await _campaign(tenant_id, agent_id)
    other = await _campaign(tenant_id, agent_id)
    await _script(tenant_id, best, words=8, steps=3)
    await _script(tenant_id, other, words=30, steps=3)
    await _calls(tenant_id, agent_id, 12, campaign_id=best, goal="yes", charge=Decimal("4.50"))
    await _calls(tenant_id, agent_id, 12, campaign_id=best, goal="no", charge=Decimal("4.50"))
    await _calls(tenant_id, agent_id, 4, campaign_id=other, goal="yes", charge=Decimal("2.25"))
    await _calls(tenant_id, agent_id, 20, campaign_id=other, goal="no", charge=Decimal("2.25"))

    compare = (await _read(tenant_id)).compare
    assert compare.best_id == best
    rows = {h.id: h for h in compare.holders}
    assert rows[best].goal_rate == 0.5 and rows[other].goal_rate == round(4 / 24, 4)
    kinds = {d.kind: d for d in compare.differences}
    assert set(kinds) == {"opening_length"}, "the step counts are equal, so not a difference"
    assert kinds["opening_length"].best == "8 words"
    assert "about 8 words" in (kinds["opening_length"].instruction or "")
    assert "notices" in (kinds["opening_length"].instruction or "")


async def test_cost_per_goal_is_numeric_rupees_and_hidden_without_billing() -> None:
    """FAILS IF: money is a float, is rounded off the paisa, or reaches a role that may not
    see billing."""
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _calls(
        tenant_id, agent_id, 3, campaign_id=campaign_id, goal="yes", charge=Decimal("3.33")
    )
    await _calls(tenant_id, agent_id, 1, campaign_id=campaign_id, goal="no", charge=Decimal("0.01"))

    compare = (await _read(tenant_id)).compare
    (row,) = compare.holders
    assert isinstance(row.spend_inr, Decimal) and row.spend_inr == Decimal("10.00")
    assert row.cost_per_goal_inr == Decimal("3.33")
    assert compare.total_spend_inr == Decimal("10.00")
    assert compare.total_cost_per_goal_inr == Decimal("3.33")
    payload = (await _read(tenant_id)).model_dump(mode="json")["compare"]["holders"][0]
    assert payload["spend_inr"] == "10.00", "money leaves as a decimal string, never a float"

    hidden = (await _read(tenant_id, spend=False)).compare
    assert hidden.holders[0].spend_inr is None and hidden.holders[0].cost_per_goal_inr is None
    assert hidden.total_spend_inr is None


async def test_one_measured_holder_has_no_best() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _calls(tenant_id, agent_id, 25, campaign_id=campaign_id, goal="yes")
    assert (await _read(tenant_id)).compare.best_id is None


# --- 4. Mistakes across holders ------------------------------------------------------------


async def test_a_mistake_on_two_holders_is_a_pattern_and_on_one_is_not() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    line_id = await _line(tenant_id, agent_id)
    now = datetime.now(UTC)
    (on_campaign,) = await _calls(tenant_id, agent_id, 1, campaign_id=campaign_id)
    (on_line,) = await _calls(tenant_id, agent_id, 1, line_id=line_id)
    (only_here,) = await _calls(tenant_id, agent_id, 1, campaign_id=campaign_id)
    await _mistake(tenant_id, agent_id, on_campaign, "said_again", now)
    await _mistake(tenant_id, agent_id, on_line, "said_again", now)
    await _mistake(tenant_id, agent_id, only_here, "asked_again", now)

    (pattern,) = (await _read(tenant_id)).patterns.patterns
    assert pattern.kind == "said_again" and pattern.holders == 2 and pattern.calls == 2
    assert [a.id for a in pattern.agents] == [agent_id]


# --- 6, 7, 9. Follow-ups, contact list, Pip's fixes ----------------------------------------


async def test_follow_ups_contacts_and_fixes_are_counted() -> None:
    tenant_id, agent_id = await _tenant()
    first = await _campaign(tenant_id, agent_id)
    second = await _campaign(tenant_id, agent_id)
    person = "+919811100001"
    (call_id,) = await _calls(tenant_id, agent_id, 1, campaign_id=first, to_e164=person)
    await _calls(tenant_id, agent_id, 1, campaign_id=second, to_e164=person)
    async with tenant_session(tenant_id) as session:
        lead_id = uuid7()
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, source, status, data, "
                "created_at, updated_at) VALUES (:id, :t, :a, :p, 'inbound_call', 'hot', "
                "'{}'::jsonb, now(), now())"
            ),
            {"id": lead_id, "t": tenant_id, "a": agent_id, "p": person},
        )
        await session.execute(
            text(
                "INSERT INTO scheduled_callbacks (id, tenant_id, agent_id, source_call_id, "
                "source_execution_id, lead_id, phone_e164, requested_at, booked_at) "
                "VALUES (:id, :t, :a, :c, :ex, :l, :p, now() + interval '1 day', now())"
            ),
            {
                "id": uuid.uuid4(),
                "t": tenant_id,
                "a": agent_id,
                "c": call_id,
                "ex": f"ex-{uuid.uuid4().hex}",
                "l": lead_id,
                "p": person,
            },
        )
        for phone, status in (("+919811100002", "dnc_blocked"), ("+919811100003", "failed")):
            await session.execute(
                text(
                    "INSERT INTO campaign_contacts (id, tenant_id, campaign_id, phone_e164, "
                    "status, created_at, updated_at) VALUES (:id, :t, :c, :p, :s, now(), now())"
                ),
                {"id": uuid7(), "t": tenant_id, "c": first, "p": phone, "s": status},
            )
        await session.execute(
            text(
                "INSERT INTO script_versions (id, tenant_id, campaign_id, script, author, "
                "owner_made, reason) VALUES (:id, :t, :c, '{}'::jsonb, 'pip_repair', false, "
                "'Pip repaired lines the script checks found.')"
            ),
            {"id": uuid7(), "t": tenant_id, "c": first},
        )

    page = await _read(tenant_id)
    assert (page.follow_ups.hot_leads, page.follow_ups.callbacks_due) == (1, 1)
    assert (page.contacts.on_dnc, page.contacts.unreachable) == (1, 1)
    assert page.contacts.called_too_often == 1
    (fix,) = page.fixes
    assert (fix.kind, fix.holder_id) == ("pip_repair", first)


async def test_a_call_that_never_rang_is_not_counted_as_calling_someone() -> None:
    """FAILS IF: a person rung by one campaign and only HELD by a second (`not_placed_reason`,
    the call never rang) is counted as called by two campaigns."""
    tenant_id, agent_id = await _tenant()
    first = await _campaign(tenant_id, agent_id)
    second = await _campaign(tenant_id, agent_id)
    person = "+919811100004"
    await _calls(tenant_id, agent_id, 1, campaign_id=first, to_e164=person)
    (held,) = await _calls(tenant_id, agent_id, 1, campaign_id=second, to_e164=person, outcome=None)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET not_placed_reason = 'lines_full', status = 'failed', "
                "started_at = NULL WHERE id = :c"
            ),
            {"c": held},
        )

    assert (await _read(tenant_id)).contacts.called_too_often == 0


# --- Another account -----------------------------------------------------------------------


async def test_another_account_reads_none_of_it() -> None:
    """FAILS IF: any section of one account's page counts another account's rows (hard rule
    1: the guarantee is the FORCEd policy on every table read, not the queries)."""
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    line_id = await _line(tenant_id, agent_id)
    calls = await _calls(
        tenant_id,
        agent_id,
        25,
        campaign_id=campaign_id,
        goal="yes",
        to_e164="+919811100009",
        charge=Decimal("1.00"),
    )
    other_calls = await _calls(tenant_id, agent_id, 1, line_id=line_id)
    now = datetime.now(UTC)
    await _mistake(tenant_id, agent_id, calls[0], "said_again", now)
    await _mistake(tenant_id, agent_id, other_calls[0], "said_again", now)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO weekly_summaries (id, tenant_id, week_start, summary, figures, model) "
                "VALUES (:id, :t, '2026-11-16', 'A good week.', '{}'::jsonb, 'm')"
            ),
            {"id": uuid7(), "t": tenant_id},
        )
    mine = await _read(tenant_id)
    assert mine.numbers.numbers and mine.compare.holders and mine.patterns.patterns

    stranger, _ = await _tenant()
    theirs = await _read(stranger)
    assert theirs.numbers.numbers == [] and theirs.compare.holders == []
    assert theirs.patterns.patterns == [] and theirs.fixes == []
    assert theirs.compare.total_spend_inr == Decimal("0.00")
    assert (theirs.follow_ups.hot_leads, theirs.contacts.called_too_often) == (0, 0)
    async with tenant_session(stranger) as session:
        assert await weekly_summary.list_summaries(session, limit=5) == []
        rows = (await session.execute(text("SELECT count(*) FROM weekly_summaries"))).scalar()
    assert rows == 0


# --- 2. The weekly summary -----------------------------------------------------------------


class _Model:
    def __init__(self, content: str = "Your agents answered more people this week.") -> None:
        self.content = content
        self.prompts: list[str] = []

    async def complete(self, leg: Any, messages: Any, **kwargs: Any) -> chat.ChatOutcome:
        self.prompts.append("\n".join(str(m.get("content", "")) for m in messages))
        return chat.ChatOutcome(
            content=self.content,
            finish_reason="stop",
            usage=chat.TokenUsage(prompt_tokens=300, output_tokens=60),
        )


@pytest.fixture
def model(monkeypatch: pytest.MonkeyPatch) -> _Model:
    stub = _Model()
    monkeypatch.setattr(chat, "complete", stub.complete)

    async def pip_on(*_: Any, **__: Any) -> bool:
        return True

    monkeypatch.setattr(worker, "account_content_may_reach_models", pip_on)
    return stub


async def _last_week_calls(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> datetime:
    moment = datetime.now(UTC)
    _, since, _ = weekly_summary.closed_week(moment)
    campaign_id = await _campaign(tenant_id, agent_id)
    started = since + timedelta(days=2)
    await _calls(tenant_id, agent_id, 6, campaign_id=campaign_id, goal="yes", started=started)
    await _calls(tenant_id, agent_id, 4, campaign_id=campaign_id, outcome="missed", started=started)
    return moment


async def test_the_weekly_summary_is_written_once_per_week_and_metered(model: _Model) -> None:
    """FAILS IF: a second run of the same week pays for a second paragraph, the spend is not
    on the ledger, or a call's own words reach the model or the stored figures."""
    tenant_id, agent_id = await _tenant()
    moment = await _last_week_calls(tenant_id, agent_id)
    leg = background_leg(("res", "key", "dep"), call="weekly_summary")
    assert leg is not None

    assert await worker.summarise_tenant(tenant_id, leg=leg, moment=moment) == "written"
    assert await worker.summarise_tenant(tenant_id, leg=leg, moment=moment) == "done"
    assert len(model.prompts) == 1
    assert SPOKEN not in model.prompts[0]

    async with tenant_session(tenant_id) as session:
        (stored,) = await weekly_summary.list_summaries(session, limit=5)
        metered = (
            await session.execute(
                text(
                    "SELECT count(DISTINCT ref) FROM usage_events "
                    "WHERE meta ->> 'feature' = 'weekly_summary'"
                )
            )
        ).scalar_one()
    assert stored.summary == model.content
    assert stored.figures["calls"] == 10 and stored.figures["goals"] == 6
    assert SPOKEN not in json.dumps(stored.figures)
    assert stored.week_start == weekly_summary.closed_week(moment)[0]
    assert metered == 1


async def test_a_quiet_week_gets_no_summary_and_costs_nothing(model: _Model) -> None:
    tenant_id, _ = await _tenant()
    leg = background_leg(("res", "key", "dep"), call="weekly_summary")
    assert leg is not None
    moment = datetime.now(UTC)
    assert await worker.summarise_tenant(tenant_id, leg=leg, moment=moment) == "quiet"
    assert model.prompts == []


async def test_the_summary_waits_for_pip_to_be_turned_on(
    model: _Model, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def pip_off(*_: Any, **__: Any) -> bool:
        return False

    monkeypatch.setattr(worker, "account_content_may_reach_models", pip_off)
    tenant_id, agent_id = await _tenant()
    moment = await _last_week_calls(tenant_id, agent_id)
    leg = background_leg(("res", "key", "dep"), call="weekly_summary")
    assert leg is not None
    assert await worker.summarise_tenant(tenant_id, leg=leg, moment=moment) == "pip_off"
    assert model.prompts == []


def test_the_closed_week_is_the_ist_week_before_the_firing_instant() -> None:
    # Monday 23 Nov 2026 02:20 UTC is 07:50 IST: the week that closed began Monday 16 Nov,
    # at IST midnight, which is 18:30 UTC the day before.
    monday, since, until = weekly_summary.closed_week(datetime(2026, 11, 23, 2, 20, tzinfo=UTC))
    assert monday.isoformat() == "2026-11-16"
    assert since == datetime(2026, 11, 15, 18, 30, tzinfo=UTC)
    assert until - since == timedelta(days=7)


def test_the_paragraph_is_one_plain_line() -> None:
    assert weekly_summary.clean_summary("**Good** week.\n\n# Done") == "Good week. Done"
    assert len(weekly_summary.clean_summary("a " * 2000)) <= 1200
    assert acct.SPAM_DROP_RATIO < 1
