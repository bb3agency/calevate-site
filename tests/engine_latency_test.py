"""The engine's own turn timings: stored, isolated, and free of caller speech.

Three properties:

1. **Hard rule 6 holds on BEHAVIOUR, not on a grep.** The assertions below read back the
   rows this code actually writes and look for the caller's words in them, and the database
   refuses a turn carrying text at all.
2. **The row is tenant-isolated** (hard rule 1) — the cross-tenant zero-rows proof migration
   `b7d3e91c4a05` ships with.
3. **The statistics refuse what the sample cannot support.** A p95 over ten turns is the
   maximum wearing a percentile's name, and the report says `None` instead.

Fixtures carry SPREAD on purpose: a percentile assertion over identical samples collapses
every statistic to the same number, so breaking the arithmetic changes nothing and the test
passes over the corpse of the code it was guarding.
"""

from __future__ import annotations

import json
import uuid

from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.ops.engine_latency import (
    _LEG_ORDER,
    P50_MIN_TURNS,
    P95_MIN_TURNS,
    LatencyGroup,
    LatencyLeg,
    LegSummary,
    engine_latency_report,
)
from calevate_shared.engine import (
    LATENCY_BUDGET,
    LLM_TTFT_BUDGET_MS,
    CallLatency,
    ExecutionSnapshot,
    TurnLatency,
)
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _tenant

# Words a caller might say. None of them may reach a stored row (hard rules 5 and 6).
CALLER_SPEECH = "hello who is there"

#: A measured two-turn call, as an adapter hands it to the pipeline.
SAMPLE_LATENCY = CallLatency(
    region="in",
    time_to_first_audio_ms=980.5,
    turns=[
        TurnLatency(turn=1, stt_ms=260.0, llm_ttft_ms=1633.04, tts_ttfa_ms=599),
        TurnLatency(turn=2, stt_ms=300.0, llm_ttft_ms=737.80, tts_ttfa_ms=317),
    ],
)


# ------------------------------------------------------- hard rule 6, on behaviour


async def test_the_stored_row_holds_numbers_and_nothing_else() -> None:
    """The database's own answer, read back. The CHECK constraint is the belt (a `text` key
    cannot be stored at all); this is the braces — what the pipeline actually wrote."""
    tenant = await _tenant()
    call_id = await _call_row(tenant)
    await _record(tenant, call_id, SAMPLE_LATENCY)

    async with tenant_session(tenant.tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT region, time_to_first_audio_ms, turns::text AS turns "
                    "FROM call_engine_latency WHERE call_id = :cid"
                ),
                {"cid": call_id},
            )
        ).one()
    assert row.region == "in"
    assert CALLER_SPEECH not in row.turns
    stored = json.loads(row.turns)
    assert {key for turn in stored for key in turn} == {
        "turn",
        "stt_ms",
        "llm_ttft_ms",
        "tts_ttfa_ms",
    }


async def test_the_database_refuses_a_turn_carrying_text() -> None:
    """A writer that ignores every comment in the tree still cannot store an utterance."""
    tenant = await _tenant()
    call_id = await _call_row(tenant)
    async with tenant_session(tenant.tenant_id) as session:
        try:
            await session.execute(
                text(
                    "INSERT INTO call_engine_latency "
                    "(id, tenant_id, call_id, engine, turns, created_at, updated_at) "
                    "VALUES (:id, :tid, :cid, 'fake', CAST(:turns AS jsonb), now(), now())"
                ),
                {
                    "id": uuid7(),
                    "tid": tenant.tenant_id,
                    "cid": call_id,
                    "turns": json.dumps([{"turn": 1, "text": CALLER_SPEECH}]),
                },
            )
        except Exception as exc:
            assert "turns_are_numbers" in str(exc)
        else:  # pragma: no cover — reached only if the constraint stopped working
            raise AssertionError("the CHECK constraint accepted caller speech")


# ------------------------------------------------------------------ hard rule 1


async def test_tenant_b_cannot_see_tenant_as_latency_row() -> None:
    """The cross-tenant zero-rows proof this table ships with (migration b7d3e91c4a05)."""
    a = await _tenant()
    b = await _tenant()
    call_id = await _call_row(a)
    await _record(a, call_id, SAMPLE_LATENCY)

    async with tenant_session(b.tenant_id) as session:
        visible = (
            await session.execute(text("SELECT count(*) FROM call_engine_latency"))
        ).scalar_one()
    assert visible == 0

    # And the policy is doing the work rather than a WHERE clause somewhere: with no GUC
    # set at all the table is empty too.
    async with untenanted_session() as session:
        assert (
            await session.execute(text("SELECT count(*) FROM call_engine_latency"))
        ).scalar_one() == 0


async def test_a_re_drive_replaces_the_measurement_rather_than_doubling_it() -> None:
    """The post-call pipeline re-runs; a second row would double-weight this call in every
    distribution, silently and only for the calls that had trouble."""
    tenant = await _tenant()
    call_id = await _call_row(tenant)
    await _record(tenant, call_id, SAMPLE_LATENCY)
    await _record(tenant, call_id, SAMPLE_LATENCY.model_copy(update={"region": "us"}))

    async with tenant_session(tenant.tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT region FROM call_engine_latency WHERE call_id = :cid"),
                {"cid": call_id},
            )
        ).all()
    assert [row.region for row in rows] == ["us"]


# --------------------------------------------------------------- the report


def _leg(group: LatencyGroup, leg: LatencyLeg) -> LegSummary:
    """One leg's summary off a group, by name rather than by position."""
    return next(summary for summary in group.legs if summary.leg == leg)


async def test_the_report_groups_by_region_and_that_is_the_gate_4_answer() -> None:
    """Two deployments, two rows, one number between them.

    This is the shape of the evidence gate 4 asks for: the same agent, the same script,
    two engine regions, and a difference in the median that is the geography and nothing
    else.
    """
    tenant = await _tenant()
    india_region, us_region = _region(), _region()
    await _measured_call(
        tenant, region=india_region, ttfts=[280.0 + n for n in range(P50_MIN_TURNS)]
    )
    await _measured_call(tenant, region=us_region, ttfts=[520.0 + n for n in range(P50_MIN_TURNS)])

    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)

    groups = {g.region: g for g in report.groups if g.region in {india_region, us_region}}
    assert set(groups) == {india_region, us_region}
    india, america = _leg(groups[india_region], "llm_ttft"), _leg(groups[us_region], "llm_ttft")
    assert india.basis == "measured" and america.basis == "measured"
    assert india.p50_ms is not None and america.p50_ms is not None
    assert america.p50_ms > india.p50_ms
    # The LLM leg is still reachable by name off the group, because it is the one whose
    # geography D-410/D-449 chose and the one the alarm is about.
    assert groups[us_region].llm_ttft.p50_ms == america.p50_ms


async def test_the_whole_budget_is_on_the_wire_and_the_composed_total_is_derived() -> None:
    """A report that published one leg's target let a console print it as the budget.

    Every figure TRD §4 declares now travels with the report, including the stages nothing
    here can measure — and the composed turn budget is the SUM of the three legs the engine
    times, so no consumer adds them up itself. `pipeline_ms` adds the endpointing wait to
    that turn: the stage TRD §4 had no line for until 27 Aug 2026, and the one the engine
    reports no figure for.
    """
    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)

    assert report.budget.llm_ttft_ms == LLM_TTFT_BUDGET_MS
    assert report.budget == LATENCY_BUDGET
    assert report.budget.turn_ms == (
        report.budget.stt_ms + report.budget.llm_ttft_ms + report.budget.tts_ttfa_ms
    )
    assert report.budget.pipeline_ms == (
        report.budget.endpointing_ms + report.budget.turn_ms + report.budget.retrieval_ms
    )
    assert report.budget.voice_to_voice_floor_ms == (
        report.budget.pipeline_ms + report.budget.india_us_transit_floor_ms
    )
    # And it survives serialization, which is the only form the console ever sees.
    wire = report.model_dump()["budget"]
    assert wire["turn_ms"] == LATENCY_BUDGET.turn_ms
    assert wire["voice_to_voice_p50_ms"] == LATENCY_BUDGET.voice_to_voice_p50_ms


async def test_the_shortfall_reaches_the_console_as_a_field_and_not_only_as_a_red_ci_job() -> None:
    """THE 500ms TARGET, AND THE ANSWER TO IT, ON THE WIRE.

    The founder set voice-to-voice at 500ms on 27 Aug 2026 and the declared stages floor at
    600ms, so `composes` is False and the headroom is negative. Both travel with every
    report: a shortfall only CI can see is a shortfall the operator reading this console
    mid-incident never learns about, and this endpoint is what the runbook opens first.
    """
    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)

    wire = report.model_dump()["budget"]
    assert wire["composes"] is False
    assert wire["voice_to_voice_headroom_p50_ms"] == -100.0
    assert wire["voice_to_voice_floor_ms"] > wire["voice_to_voice_p50_ms"]
    # The shipped turn-detection configuration is published beside the budget it misses —
    # 250ms endpointing + 400ms linear delay, both vendor defaults we never overrode.
    assert wire["inherited_turn_detection_ms"] == 650.0
    assert wire["inherited_turn_detection_ms"] > wire["endpointing_ms"]


async def test_every_leg_is_judged_against_its_own_target_and_retrieval_is_not_faked() -> None:
    """Four summaries per group, each carrying the budget it was compared with.

    `retrieval` is DELIBERATELY not among them: TRD §4 budgets it at 100ms, the report
    publishes that target on `budget`, and `call_engine_latency` holds no sample for it —
    the in-call RAG endpoint is ours and is not instrumented here. A fifth leg with an
    empty distribution would invite the reader to conclude retrieval is fast.
    """
    tenant = await _tenant()
    region = _region()
    await _measured_call(
        tenant,
        region=region,
        ttfts=[300.0 + n for n in range(P50_MIN_TURNS)],
        stts=[200.0 + n for n in range(P50_MIN_TURNS)],
        ttfas=[250.0 + n for n in range(P50_MIN_TURNS)],
    )

    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)
    group = next(g for g in report.groups if g.region == region)

    assert [summary.leg for summary in group.legs] == list(_LEG_ORDER)
    assert "retrieval" not in {summary.leg for summary in group.legs}
    assert _leg(group, "stt").budget_ms == LATENCY_BUDGET.stt_ms
    assert _leg(group, "llm_ttft").budget_ms == LATENCY_BUDGET.llm_ttft_ms
    assert _leg(group, "tts_ttfa").budget_ms == LATENCY_BUDGET.tts_ttfa_ms
    assert _leg(group, "turn").budget_ms == LATENCY_BUDGET.turn_ms
    # The composed leg is the per-turn sum, so its median is the sum of the medians here
    # (the three fixtures rise together, one sample per turn).
    composed = _leg(group, "turn")
    assert composed.p50_ms is not None
    assert composed.p50_ms == (_leg(group, "stt").p50_ms or 0.0) + (
        _leg(group, "llm_ttft").p50_ms or 0.0
    ) + (_leg(group, "tts_ttfa").p50_ms or 0.0)
    # The STT leg's unit is not confirmed against the vendor's docs, and the composed leg
    # inherits that doubt because it contains it.
    assert _leg(group, "stt").unit_verified is False
    assert _leg(group, "llm_ttft").unit_verified is True
    assert composed.unit_verified is False


async def test_a_turn_inside_the_llm_budget_can_still_blow_the_whole_turn() -> None:
    """THE DEFECT THIS MODULE'S SECOND VERSION EXISTS FOR.

    A turn that spends 120ms in the model and 900ms in the transcriber was reported as
    comfortably within target, because the only budget the report knew was the LLM one. The
    language leg must still say "within" — it IS within — and the composed turn must say
    the caller waited too long.
    """
    tenant = await _tenant()
    region = _region()
    await _measured_call(
        tenant,
        region=region,
        ttfts=[120.0 + n for n in range(P50_MIN_TURNS)],
        stts=[900.0 + n for n in range(P50_MIN_TURNS)],
        ttfas=[250.0 + n for n in range(P50_MIN_TURNS)],
    )

    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)
    group = next(g for g in report.groups if g.region == region)

    assert _leg(group, "llm_ttft").budget_breached is False, "the model leg really is fine"
    assert _leg(group, "stt").budget_breached is True
    assert _leg(group, "turn").budget_breached is True, (
        "a turn over 950ms is over budget however fast the model was"
    )
    assert _leg(group, "turn").turns_over_budget == P50_MIN_TURNS


async def test_a_turn_missing_a_leg_is_a_sample_for_the_legs_it_reported_and_no_others() -> None:
    """`TurnLatency.component_sum_ms`'s rule, applied to the aggregate.

    A partial sum is a smaller number that is not a smaller latency, so a turn with no
    transcriber block contributes to the LLM distribution and to NOTHING composed.
    """
    tenant = await _tenant()
    region = _region()
    # LLM only — exactly the shape the old single-leg reader produced.
    await _measured_call(tenant, region=region, ttfts=[300.0 + n for n in range(P50_MIN_TURNS)])

    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)
    group = next(g for g in report.groups if g.region == region)

    assert _leg(group, "llm_ttft").turns == P50_MIN_TURNS
    assert _leg(group, "stt").turns == 0
    assert _leg(group, "turn").turns == 0
    assert _leg(group, "turn").p50_ms is None
    assert _leg(group, "turn").max_ms is None
    assert _leg(group, "turn").basis == "insufficient_samples"
    # The GROUP still counts the turn: it was timed, just not on every leg.
    assert group.turns == P50_MIN_TURNS


async def test_a_soft_deleted_tenants_turns_are_not_walked() -> None:
    """The directory enumerates tenants by `deleted_at IS NULL` — the predicate
    `admin/health.client_health` and `core/auth._load_admin_principal` both walk by.

    A soft-deleted account is one being erased (`organizations.deleted_at`, the only thing
    in the product that sets it); its calls must not surface in a fleet ops report. The
    filter was `status <> 'deleted'` — a value `ORG_STATUSES` does not contain and the
    `status_enum` CHECK refuses — so it excluded NOTHING, and a soft-deleted tenant's turns
    landed in the distribution.

    A CHURNED-but-not-deleted tenant is kept IN: its recent calls are real engine
    measurements, and `deleted_at IS NULL` is the whole predicate — so this also pins that
    the fix keys on `deleted_at` (as `_load_admin_principal` does) rather than on churning,
    and does not silently drop live data.
    """
    live, gone, churned = await _tenant(), await _tenant(), await _tenant()
    live_region, gone_region, churned_region = _region(), _region(), _region()
    await _measured_call(live, region=live_region, ttfts=[300.0 + n for n in range(P50_MIN_TURNS)])
    await _measured_call(gone, region=gone_region, ttfts=[300.0 + n for n in range(P50_MIN_TURNS)])
    await _measured_call(
        churned, region=churned_region, ttfts=[300.0 + n for n in range(P50_MIN_TURNS)]
    )
    # `deleted_at` implies `churned` (ck_organizations_deleted_implies_churned), so the
    # erased account carries both; the churned-only account carries the status alone. A
    # tenant session may soft-delete its own organization (organizations_delete_rls_test).
    async with tenant_session(gone.tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned', deleted_at = now() WHERE id = :id"),
            {"id": gone.tenant_id},
        )
    async with tenant_session(churned.tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :id"),
            {"id": churned.tenant_id},
        )

    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)

    regions = {g.region for g in report.groups}
    assert live_region in regions, "a live tenant's turns must be reported"
    assert churned_region in regions, "a churned-but-not-erased tenant's turns are real data"
    assert gone_region not in regions, "a soft-deleted tenant's turns must not be walked"


async def test_a_percentile_the_sample_cannot_support_is_withheld() -> None:
    """`None`, not the maximum wearing a p95's name."""
    tenant = await _tenant()
    assert P50_MIN_TURNS < P95_MIN_TURNS, "the two thresholds must differ for this to mean anything"
    region = _region()
    await _measured_call(tenant, region=region, ttfts=[300.0 + n * 5 for n in range(P50_MIN_TURNS)])

    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)
    group = next(g for g in report.groups if g.region == region)
    llm = _leg(group, "llm_ttft")
    assert llm.p50_ms is not None, "a median IS supported at this size"
    assert llm.p95_ms is None
    assert llm.max_ms is not None, "the maximum is an observation, honest at n=1"


async def test_the_breach_is_named_rather_than_left_to_the_reader() -> None:
    """A distribution with no verdict beside it is how a target becomes whatever the fleet
    currently does. `budget_breached` is that verdict, and it is `None` — never `False` —
    when the sample cannot support one."""
    tenant = await _tenant()
    over = LLM_TTFT_BUDGET_MS + 200
    breached_region, tiny_region = _region(), _region()
    await _measured_call(
        tenant, region=breached_region, ttfts=[over + n for n in range(P50_MIN_TURNS)]
    )
    await _measured_call(tenant, region=tiny_region, ttfts=[over, over])

    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)
    breached = _leg(next(g for g in report.groups if g.region == breached_region), "llm_ttft")
    assert breached.budget_breached is True
    assert breached.turns_over_budget == P50_MIN_TURNS

    unknown = _leg(next(g for g in report.groups if g.region == tiny_region), "llm_ttft")
    assert unknown.budget_breached is None, "'we do not know' must not render as 'within budget'"
    assert unknown.basis == "insufficient_samples"


def _region() -> str:
    """A region code unique to this run.

    NOT a cosmetic detail: this table is keyed by call and the development database is not
    reset between runs, so a fixed code like `"us"` accumulates every previous run's turns
    into the group under test and the assertion drifts upward until somebody deletes rows.
    Sixteen characters is the CHECK constraint's ceiling; nine keeps room under it.
    """
    return f"r{uuid.uuid4().hex[:8]}"


# ------------------------------------------------------------------- helpers


async def _call_row(tenant: Tenant) -> uuid.UUID:
    call_id = uuid7()
    async with tenant_session(tenant.tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
                "'completed', now(), now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant.tenant_id,
                "aid": tenant.agent_id,
                "ecid": f"lat-{uuid.uuid4().hex}",
            },
        )
    return call_id


async def _record(tenant: Tenant, call_id: uuid.UUID, latency: CallLatency | None) -> str:
    """Drive the real pipeline stage, not a hand-written INSERT — the row under test must
    be the one production writes."""
    from apps.workers.pipeline import _record_engine_latency

    snapshot = ExecutionSnapshot(
        engine_call_id="exec",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        engine="fake",
        latency=latency,
    )
    return await _record_engine_latency(tenant.tenant_id, call_id, snapshot)


async def _measured_call(
    tenant: Tenant,
    *,
    region: str,
    ttfts: list[float],
    stts: list[float] | None = None,
    ttfas: list[float] | None = None,
) -> uuid.UUID:
    """One call whose turns carry the legs named, and ONLY those.

    `stts`/`ttfas` default to absent rather than to a plausible number: a turn that
    reported no transcriber block is the commonest real shape (it is what the reader
    produced before today), and a fixture that quietly filled it in would test a payload
    the engine does not send.
    """
    call_id = await _call_row(tenant)
    await _record(
        tenant,
        call_id,
        CallLatency(
            region=region,
            turns=[
                TurnLatency(
                    turn=i + 1,
                    llm_ttft_ms=v,
                    stt_ms=None if stts is None else stts[i],
                    tts_ttfa_ms=None if ttfas is None else ttfas[i],
                )
                for i, v in enumerate(ttfts)
            ],
        ),
    )
    return call_id
