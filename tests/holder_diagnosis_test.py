"""The Improve tab's readings of a campaign's or Inbound line's calls (founder, 24 Nov 2026):
where people drop off in the script, which mistakes recur and whether they are fixed, how many
hang up in the opening seconds against the account's other holders, and why people said no.

Each reading is asserted on fixture calls, on a campaign and on a line, with the owner's test
calls and other holders' calls kept out, and read by another account as nothing at all.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.agents.mistake_fixes import Holder
from apps.api.campaigns import diagnose
from apps.api.campaigns.workspace_routes import holder_diagnosis
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.inbound import lines
from sqlalchemy import text
from tests.dispatch_budget_test import _tenant
from tests.inbound_lines_test import _call
from tests.step_outcomes_test import _campaign

pytestmark = pytest.mark.anyio

NAMES = {1: "Remembers the app", 2: "Installs it", 3: "Logs in"}


def _progress(furthest: int, *, steps: int = 3) -> dict[str, Any]:
    """A judged call that reached every step up to `furthest` and none after."""
    return {
        "steps": [
            {
                "step": n,
                "name": NAMES[n],
                "state": "reached" if n <= furthest else "not_reached",
                "turn_idx": None,
                "moved_on_turn": None,
            }
            for n in range(1, steps + 1)
        ],
        "fields": {},
    }


async def _calls(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    n: int,
    *,
    campaign_id: uuid.UUID | None = None,
    line_id: uuid.UUID | None = None,
    test_call: bool = False,
    outcome: str | None = "answered",
    duration_s: int | None = 90,
    progress: dict[str, Any] | None = None,
    reason: str | None = None,
    started: datetime | None = None,
) -> list[uuid.UUID]:
    made = []
    async with tenant_session(tenant_id) as session:
        for _ in range(n):
            call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "status, campaign_id, inbound_line_id, trial_call, outcome_tag, duration_s, "
                    "step_progress, refusal_reason, started_at, created_at, updated_at) VALUES "
                    "(:id, :t, :a, :e, :d, 'completed', :g, :l, :trial, :o, :dur, "
                    "CAST(:p AS jsonb), :r, :s, now(), now())"
                ),
                {
                    "id": call_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"exec_{uuid.uuid4().hex[:12]}",
                    "d": "outbound" if campaign_id else "inbound",
                    "g": campaign_id,
                    "l": line_id,
                    "trial": test_call,
                    "o": outcome,
                    "dur": duration_s,
                    "p": json.dumps(progress) if progress is not None else None,
                    "r": reason,
                    "s": started or datetime.now(UTC),
                },
            )
            made.append(call_id)
    return made


async def _mistake(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, call_id: uuid.UUID, kind: str, at: datetime
) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO call_mistakes (id, tenant_id, agent_id, call_id, kind, turn_idx, "
                "call_started_at) VALUES (:id, :t, :a, :c, :k, 1, :s)"
            ),
            {"id": uuid7(), "t": tenant_id, "a": agent_id, "c": call_id, "k": kind, "s": at},
        )


async def _line(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> uuid.UUID:
    async with tenant_session(tenant_id) as session:
        return await lines.create_line(
            session, tenant_id=tenant_id, agent_id=agent_id, name="Front desk", created_by=None
        )


async def _read(tenant_id: uuid.UUID, holder: Holder) -> Any:
    async with tenant_session(tenant_id) as session:
        return await holder_diagnosis(session, holder)


# --- Where people drop off -----------------------------------------------------------------


def test_each_step_owns_only_the_people_it_lost() -> None:
    steps = diagnose.with_losses(
        [
            diagnose.StepCount(1, "a", reached=12, not_reached=0, unclear=0),
            diagnose.StepCount(2, "b", reached=6, not_reached=6, unclear=0),
            diagnose.StepCount(3, "c", reached=4, not_reached=8, unclear=0),
        ]
    )
    assert [s.lost_here for s in steps] == [0, 6, 2]


async def test_the_step_that_loses_most_people_is_named() -> None:
    """FAILS IF: step 3, which most calls did not reach, is blamed for the people step 2 lost."""
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    await _calls(tenant_id, agent_id, 6, campaign_id=campaign_id, progress=_progress(1))
    await _calls(tenant_id, agent_id, 2, campaign_id=campaign_id, progress=_progress(2))
    await _calls(tenant_id, agent_id, 4, campaign_id=campaign_id, progress=_progress(3))
    # Not judged, a test call, and one older than the window: none is read.
    await _calls(tenant_id, agent_id, 3, campaign_id=campaign_id)
    old = datetime.now(UTC) - timedelta(days=diagnose.WINDOW_DAYS + 1)
    await _calls(
        tenant_id, agent_id, 5, campaign_id=campaign_id, progress=_progress(1), started=old
    )

    got = (await _read(tenant_id, Holder("campaign", campaign_id))).drop_off

    assert got.judged_calls == 12
    assert [(s.step, s.name, s.reached, s.not_reached, s.lost_here) for s in got.steps] == [
        (1, NAMES[1], 12, 0, 0),
        (2, NAMES[2], 6, 6, 6),
        (3, NAMES[3], 4, 8, 2),
    ]
    assert got.worst_step == 2


async def test_too_few_judged_calls_name_no_step() -> None:
    tenant_id, agent_id = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    await _calls(
        tenant_id, agent_id, diagnose.MIN_JUDGED_CALLS - 1, line_id=line_id, progress=_progress(1)
    )
    # The owner's test calls on the line are not its calls.
    await _calls(tenant_id, agent_id, 5, line_id=line_id, test_call=True, progress=_progress(1))

    got = (await _read(tenant_id, Holder("inbound_line", line_id))).drop_off

    assert got.judged_calls == diagnose.MIN_JUDGED_CALLS - 1
    assert got.worst_step is None
    assert got.min_calls == diagnose.MIN_JUDGED_CALLS


# --- Mistakes on this holder's calls -------------------------------------------------------


async def test_mistakes_count_this_holders_calls_with_the_latest_and_its_fix() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    other_id = await _campaign(tenant_id, agent_id)
    now = datetime.now(UTC)
    calls = await _calls(tenant_id, agent_id, 3, campaign_id=campaign_id)
    elsewhere = await _calls(tenant_id, agent_id, 1, campaign_id=other_id)
    for offset, call_id in enumerate(calls):
        await _mistake(
            tenant_id, agent_id, call_id, "said_again", now - timedelta(hours=3 - offset)
        )
    await _mistake(tenant_id, agent_id, calls[0], "asked_again", now - timedelta(hours=5))
    await _mistake(tenant_id, agent_id, elsewhere[0], "asked_again", now)
    # The script was repaired of "said_again" after its latest call.
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE campaigns SET script_heal_fixed = CAST(:f AS jsonb) WHERE id = :c"),
            {"f": json.dumps({"said_again": now.isoformat()}), "c": campaign_id},
        )

    got = (await _read(tenant_id, Holder("campaign", campaign_id))).mistakes

    assert [(m.kind, m.calls, m.last_call_id, m.status) for m in got] == [
        ("said_again", 3, calls[2], "repaired"),
        ("asked_again", 1, calls[0], "told"),
    ]
    assert got[0].label == "Said the same line again"


# --- Openings that lose people -------------------------------------------------------------


async def test_early_hang_ups_are_compared_with_the_accounts_other_campaigns() -> None:
    tenant_id, agent_id = await _tenant()
    campaign_id = await _campaign(tenant_id, agent_id)
    other_id = await _campaign(tenant_id, agent_id)
    await _calls(tenant_id, agent_id, 15, campaign_id=campaign_id)
    await _calls(
        tenant_id, agent_id, 5, campaign_id=campaign_id, outcome="hung_up_early", duration_s=8
    )
    # Too long to be the opening, and never answered: neither is an early hang-up.
    await _calls(
        tenant_id, agent_id, 1, campaign_id=campaign_id, outcome="hung_up_early", duration_s=45
    )
    await _calls(tenant_id, agent_id, 4, campaign_id=campaign_id, outcome="missed", duration_s=0)
    await _calls(tenant_id, agent_id, 18, campaign_id=other_id)
    await _calls(
        tenant_id, agent_id, 2, campaign_id=other_id, outcome="hung_up_early", duration_s=5
    )

    got = (await _read(tenant_id, Holder("campaign", campaign_id))).early_hang_ups

    assert (got.answered, got.early, got.others_answered) == (21, 5, 20)
    assert got.rate == round(5 / 21, 4)
    assert got.others_rate == 0.1
    assert got.early_seconds == diagnose.EARLY_HANG_UP_S


async def test_too_few_answered_calls_show_no_rate() -> None:
    tenant_id, agent_id = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    await _calls(tenant_id, agent_id, 3, line_id=line_id, outcome="hung_up_early", duration_s=4)

    got = (await _read(tenant_id, Holder("inbound_line", line_id))).early_hang_ups

    assert (got.answered, got.early, got.rate, got.others_rate) == (3, 3, None, None)


# --- Why people said no --------------------------------------------------------------------


async def test_refusal_reasons_are_counted_most_first() -> None:
    tenant_id, agent_id = await _tenant()
    line_id = await _line(tenant_id, agent_id)
    await _calls(tenant_id, agent_id, 3, line_id=line_id, reason="price")
    await _calls(tenant_id, agent_id, 1, line_id=line_id, reason="busy_now")
    await _calls(tenant_id, agent_id, 4, line_id=line_id)
    await _calls(tenant_id, agent_id, 2, line_id=line_id, test_call=True, reason="no_trust")

    got = (await _read(tenant_id, Holder("inbound_line", line_id))).refusal_reasons

    assert [(r.reason, r.calls) for r in got] == [("price", 3), ("busy_now", 1)]


async def test_the_column_takes_only_a_listed_reason() -> None:
    tenant_id, agent_id = await _tenant()
    with pytest.raises(Exception, match="ck_calls_refusal_reason_enum"):
        await _calls(tenant_id, agent_id, 1, reason="the caller said it costs too much")


# --- Tenancy and the routes ----------------------------------------------------------------


async def test_another_account_reads_nothing_of_a_holders_calls() -> None:
    tenant_a, agent_a = await _tenant()
    tenant_b, _agent_b = await _tenant()
    campaign_id = await _campaign(tenant_a, agent_a)
    calls = await _calls(
        tenant_a,
        agent_a,
        12,
        campaign_id=campaign_id,
        progress=_progress(1),
        reason="price",
        outcome="hung_up_early",
        duration_s=3,
    )
    await _mistake(tenant_a, agent_a, calls[0], "said_again", datetime.now(UTC))

    got = await _read(tenant_b, Holder("campaign", campaign_id))

    assert got.drop_off.steps == [] and got.drop_off.judged_calls == 0
    assert got.mistakes == [] and got.refusal_reasons == []
    assert (got.early_hang_ups.answered, got.early_hang_ups.others_answered) == (0, 0)


async def test_the_line_routes_read_and_ask_pip_with_an_instruction() -> None:
    from tests.agent_lifecycle_test import _tenant as _owner

    tenant_id, agent_id, token = await _owner()
    line_id = await _line(tenant_id, agent_id)
    code, body = await _call(token, "GET", f"/{line_id}/diagnosis")
    assert code == 200, body
    assert body["window_days"] == diagnose.WINDOW_DAYS
    assert body["drop_off"]["steps"] == [] and body["mistakes"] == []

    code, _ = await _call(token, "PATCH", f"/{line_id}", json={"main_task": "Book visits."})
    assert code == 200
    code, made = await _call(
        token, "POST", f"/{line_id}/proposal", json={"instruction": "Rewrite step 2,  Installs it."}
    )
    assert code == 202, made
    async with tenant_session(tenant_id) as session:
        record = (
            await session.execute(
                text("SELECT script_proposal FROM inbound_lines WHERE id = :l"), {"l": line_id}
            )
        ).scalar_one()
    assert record["ask"] == {"instruction": "Rewrite step 2, Installs it."}

    code, _ = await _call(token, "GET", f"/{uuid.uuid4()}/diagnosis")
    assert code == 404
