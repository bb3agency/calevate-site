"""The engine's own turn timings: captured, stored, isolated, and free of caller speech.

Four properties, and each one is a thing that was true of this system yesterday and is not
today:

1. **The adapter reads `latency_data`.** It used to drop it, and said so in its docstring.
   The payload here is the vendor's own documented shape
   (`bolna-findings/mirror/pages/concepts/call-latencies.md:22-45,57-155`), caller speech
   included — because the point is not that the reader ignores text, it is that text has
   nowhere to go.
2. **Hard rule 6 holds on BEHAVIOUR, not on a grep.** The assertions below take the objects
   and rows this code actually emits and look for the caller's words in them. A test that
   grepped the source for `["text"]` would pass over a payload dumped whole into a log.
3. **The row is tenant-isolated** (hard rule 1) — the cross-tenant zero-rows proof migration
   `b7d3e91c4a05` ships with.
4. **The statistics refuse what the sample cannot support.** A p95 over ten turns is the
   maximum wearing a percentile's name, and the report says `None` instead.

Fixtures carry SPREAD on purpose: a percentile assertion over identical samples collapses
every statistic to the same number, so breaking the arithmetic changes nothing and the test
passes over the corpse of the code it was guarding.
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any

import httpx
from apps.api.db.base import uuid7
from apps.api.db.session import admin_session, tenant_session, untenanted_session
from apps.api.engine import bolna as bolna_module
from apps.api.engine.bolna import BASE_URL, BolnaEngine, parse_latency_data
from apps.api.ops.engine_latency import (
    P50_MIN_TURNS,
    P95_MIN_TURNS,
    engine_latency_report,
)
from calevate_shared.engine import LLM_TTFT_BUDGET_MS, CallLatency, ExecutionSnapshot, TurnLatency
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _tenant

# The caller's own words, exactly as the vendor nests them beside the timings
# (`call-latencies.md:73`). If any of this reaches a model, a row or a log line, hard rules
# 5 and 6 are broken.
CALLER_SPEECH = "hello who is there"
SECOND_UTTERANCE = "book cheyandi naa peru Ravi"

RAW_LATENCY_DATA: dict[str, Any] = {
    "stream_id": 129.56,
    "time_to_first_audio": 980.5,
    "region": "in",
    "transcriber": {
        "time_to_connect": 226,
        "turns": [
            {
                "turn": 1,
                "turn_latency": [
                    {"sequence_id": 1, "audio_to_text_latency": 240.5, "text": CALLER_SPEECH},
                    {"sequence_id": 2, "audio_to_text_latency": 260.0, "text": "hello who is this"},
                ],
            },
            {
                "turn": 2,
                "turn_latency": [
                    {"sequence_id": 1, "audio_to_text_latency": 300.0, "text": SECOND_UTTERANCE}
                ],
            },
        ],
    },
    "llm": {
        "time_to_connect": None,
        "turns": [
            {"turn": 1, "time_to_first_token": 1633.04, "time_to_last_token": 1691.53},
            {"turn": 2, "time_to_first_token": 737.80, "time_to_last_token": 777.49},
        ],
    },
    "synthesizer": {
        "time_to_connect": 271,
        "turns": [
            {"turn": 1, "time_to_first_token": 599, "time_to_last_token": 800},
            {"turn": 2, "time_to_first_token": 317, "time_to_last_token": 518},
        ],
    },
}


# ---------------------------------------------------------------- the adapter reads it


def test_the_adapter_reads_every_documented_component() -> None:
    parsed = parse_latency_data(RAW_LATENCY_DATA)
    assert parsed is not None
    assert parsed.region == "in"
    assert parsed.time_to_first_audio_ms == 980.5
    by_turn = {turn.turn: turn for turn in parsed.turns}
    # The LAST transcriber sequence is the one the orchestrator acted on; the earlier ones
    # are guesses the recogniser itself revised (`call-latencies.md:87`).
    assert by_turn[1].stt_ms == 260.0
    assert by_turn[1].llm_ttft_ms == 1633.04
    assert by_turn[1].tts_ttfa_ms == 599
    assert by_turn[2].llm_ttft_ms == 737.80
    assert parsed.parse_warnings == []


def test_no_latency_object_is_none_and_an_unreadable_one_is_not() -> None:
    """`None` and "an object I could read nothing out of" are different facts.

    A listing row carries no `latency_data` at all and must write no row; a payload whose
    blocks moved must write a row that SAYS so, because "the engine reported nothing" and
    "we stopped understanding the engine" call for opposite responses.
    """
    assert parse_latency_data(None) is None
    assert parse_latency_data("nonsense") is None

    parsed = parse_latency_data({"llm": {"turns": "not a list"}})
    assert parsed is not None
    assert parsed.turns == []
    assert any("llm.turns" in warning for warning in parsed.parse_warnings)
    assert any("transcriber block absent" in warning for warning in parsed.parse_warnings)


def test_absent_is_absent_and_never_zero() -> None:
    """A component the payload did not carry is None. A zero would read as instant and
    would drag a median down without anyone being able to see why."""
    parsed = parse_latency_data(
        {"llm": {"turns": [{"turn": 1, "time_to_first_token": 320}]}, "synthesizer": {"turns": []}}
    )
    assert parsed is not None
    turn = parsed.turns[0]
    assert turn.stt_ms is None
    assert turn.tts_ttfa_ms is None
    assert turn.component_sum_ms is None, "a two-of-three sum is a different quantity"


def test_a_free_form_region_is_refused_rather_than_stored() -> None:
    """The column is grouped by, never rendered — so anything that is not an identifier is
    a liability with no use. It is refused WITH a warning, not silently dropped."""
    parsed = parse_latency_data({"region": "somewhere near the caller, 9876543210"})
    assert parsed is not None
    assert parsed.region is None
    assert any("region" in warning for warning in parsed.parse_warnings)


# ------------------------------------------------------- hard rule 6, on behaviour


def test_recognised_caller_speech_reaches_no_object_this_code_emits() -> None:
    """Asserted against the SERIALIZED model, which is what a span, a job payload or a log
    line would carry — not against a source grep, which a `json.dumps(payload)` defeats."""
    parsed = parse_latency_data(RAW_LATENCY_DATA)
    assert parsed is not None
    blob = parsed.model_dump_json()
    assert CALLER_SPEECH not in blob
    assert SECOND_UTTERANCE not in blob
    assert "Ravi" not in blob


async def test_the_stored_row_holds_numbers_and_nothing_else() -> None:
    """The database's own answer, read back. The CHECK constraint is the belt (a `text` key
    cannot be stored at all); this is the braces — what the pipeline actually wrote."""
    tenant = await _tenant()
    call_id = await _call_row(tenant)
    await _record(tenant, call_id, parse_latency_data(RAW_LATENCY_DATA))

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
    assert "Ravi" not in row.turns
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
                    "VALUES (:id, :tid, :cid, 'bolna', CAST(:turns AS jsonb), now(), now())"
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
    await _record(a, call_id, parse_latency_data(RAW_LATENCY_DATA))

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
    await _record(tenant, call_id, parse_latency_data(RAW_LATENCY_DATA))
    await _record(tenant, call_id, parse_latency_data({**RAW_LATENCY_DATA, "region": "us"}))

    async with tenant_session(tenant.tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT region FROM call_engine_latency WHERE call_id = :cid"),
                {"cid": call_id},
            )
        ).all()
    assert [row.region for row in rows] == ["us"]


async def test_get_execution_carries_the_timings_through_the_port() -> None:
    """THE WIRING, not the reader — and this test exists because cutting the wire was
    invisible to every other test in this file.

    `parse_latency_data` can be perfect and `_snapshot` can still drop its result on the
    floor, which is exactly what the adapter did before today. So this drives the real
    `GET /executions/{id}` path against a mocked transport and asserts the measurement
    arrives on `ExecutionSnapshot` — the seam the pipeline reads.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "exec-wired",
                "status": "completed",
                "agent_id": "agent-1",
                "telephony_data": {"call_type": "inbound"},
                "latency_data": RAW_LATENCY_DATA,
            },
        )

    engine = BolnaEngine(
        api_key="k",
        fx_rate=Decimal("88.00"),
        client=httpx.AsyncClient(base_url=BASE_URL, transport=httpx.MockTransport(handler)),
    )
    snapshot = await engine.get_execution("exec-wired")
    assert snapshot.latency is not None
    assert snapshot.latency.region == "in"
    assert [turn.llm_ttft_ms for turn in snapshot.latency.turns] == [1633.04, 737.80]
    # And the document that rides beside it still carries no readable field for anyone
    # above the adapter — the archive is bytes, the measurement is typed (hard rule 2).
    assert isinstance(snapshot.raw_document, bytes)


# ------------------------------------------------------------------- the alarm


def test_one_slow_turn_does_not_page_and_a_broken_call_does(monkeypatch) -> None:
    """The split the alarm exists for.

    The vendor's own worked example opens at 1633.04ms and settles at 737.80ms
    (`call-latencies.md:99-108`) — a cold start, over OUR budget and not an incident. An
    alarm that fired on it would fire on every call and would be muted within a week.
    """
    fired: list[tuple[str, str]] = []
    monkeypatch.setattr(
        bolna_module, "alert", lambda stage, code, **kw: fired.append((stage, code))
    )

    # The documented sample, plus a third healthy turn so the minimum sample is met.
    cold_start = CallLatency(
        turns=[
            TurnLatency(turn=1, llm_ttft_ms=1633.04),
            TurnLatency(turn=2, llm_ttft_ms=737.80),
            TurnLatency(turn=3, llm_ttft_ms=690.0),
        ]
    )
    bolna_module._check_llm_ttft(cold_start, engine_call_id="exec-1")
    assert fired == [], "a cold first turn is not an incident"

    broken = CallLatency(
        region="us",
        turns=[
            TurnLatency(turn=1, llm_ttft_ms=1800.0),
            TurnLatency(turn=2, llm_ttft_ms=1500.0),
            TurnLatency(turn=3, llm_ttft_ms=1400.0),
        ],
    )
    bolna_module._check_llm_ttft(broken, engine_call_id="exec-2")
    assert fired == [("CORE_LOGIC", "engine_llm_ttft_degraded")]


def test_a_two_turn_call_is_never_judged(monkeypatch) -> None:
    """Two turns is a cold start with a witness, not a distribution."""
    fired: list[str] = []
    monkeypatch.setattr(bolna_module, "alert", lambda stage, code, **kw: fired.append(code))
    bolna_module._check_llm_ttft(
        CallLatency(
            turns=[
                TurnLatency(turn=1, llm_ttft_ms=9000.0),
                TurnLatency(turn=2, llm_ttft_ms=9000.0),
            ]
        ),
        engine_call_id="exec-3",
    )
    assert fired == []


def test_the_alarm_detail_carries_no_identifier_but_the_execution_id(monkeypatch) -> None:
    """Hard rule 6 on the alert path: numbers, a region code, and an id."""
    captured: dict[str, Any] = {}
    monkeypatch.setattr(
        bolna_module,
        "alert",
        lambda stage, code, **kw: captured.update({"detail": kw.get("detail"), "ids": kw}),
    )
    bolna_module._check_llm_ttft(
        CallLatency(
            region="us",
            turns=[TurnLatency(turn=n, llm_ttft_ms=2000.0) for n in range(1, 5)],
        ),
        engine_call_id="exec-4",
    )
    assert set(captured["ids"]) == {"detail", "engine_call_id"}
    assert "2000ms" in captured["detail"]


# --------------------------------------------------------------- the report


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
    india, america = groups[india_region], groups[us_region]
    assert india.basis == "measured" and america.basis == "measured"
    assert india.llm_ttft_p50_ms is not None and america.llm_ttft_p50_ms is not None
    assert america.llm_ttft_p50_ms > india.llm_ttft_p50_ms
    assert report.llm_ttft_budget_ms == LLM_TTFT_BUDGET_MS


async def test_a_percentile_the_sample_cannot_support_is_withheld() -> None:
    """`None`, not the maximum wearing a p95's name."""
    tenant = await _tenant()
    assert P50_MIN_TURNS < P95_MIN_TURNS, "the two thresholds must differ for this to mean anything"
    region = _region()
    await _measured_call(tenant, region=region, ttfts=[300.0 + n * 5 for n in range(P50_MIN_TURNS)])

    async with admin_session() as session:
        report = await engine_latency_report(session, days=1)
    group = next(g for g in report.groups if g.region == region)
    assert group.llm_ttft_p50_ms is not None, "a median IS supported at this size"
    assert group.llm_ttft_p95_ms is None
    assert group.llm_ttft_max_ms is not None, "the maximum is an observation, honest at n=1"


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
    breached = next(g for g in report.groups if g.region == breached_region)
    assert breached.budget_breached is True
    assert breached.turns_over_budget == P50_MIN_TURNS

    unknown = next(g for g in report.groups if g.region == tiny_region)
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
        engine="bolna",
        latency=latency,
    )
    return await _record_engine_latency(tenant.tenant_id, call_id, snapshot)


async def _measured_call(tenant: Tenant, *, region: str, ttfts: list[float]) -> uuid.UUID:
    call_id = await _call_row(tenant)
    await _record(
        tenant,
        call_id,
        CallLatency(
            region=region,
            turns=[TurnLatency(turn=i + 1, llm_ttft_ms=v) for i, v in enumerate(ttfts)],
        ),
    )
    return call_id
