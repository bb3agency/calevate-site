"""A call's per-turn timings (D-902): fetched by `workers/call_timeline` after the call, kept
on `calls.engine_timeline`, and shown to an operator only."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from apps.api.core.errors import ProblemError
from apps.api.crm import service as crm_service
from apps.api.db.session import tenant_session
from apps.api.engine.thinnest import parse_quality, parse_timeline
from apps.workers import call_timeline
from arq import Retry
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import CallQuality, CallTimeline, TurnTiming
from sqlalchemy import text
from tests.lead_columns_test import Tenant, _tenant

_TIMELINE = CallTimeline(
    turns=[
        TurnTiming(
            turn=1,
            first_sound_ms=700,
            first_sound_kind="filler",
            answer_ms=1900,
            answer_estimated=True,
            wait_before_decision_ms=300,
            recogniser_ms=200,
            ear_check_ms=100,
            model_first_sentence_ms=1200,
            voice_ms=400,
            model_asked_ms=-50,
        )
    ]
)


class _Engine:
    """Answers `get_call_timeline` from a script of results, one per try."""

    def __init__(self, *answers: CallTimeline | ProblemError | None) -> None:
        self.answers = list(answers)
        self.asked: list[str] = []

    async def get_call_timeline(self, call_id: str) -> CallTimeline | None:
        self.asked.append(call_id)
        answer = self.answers.pop(0)
        if isinstance(answer, ProblemError):
            raise answer
        return answer


async def _call_row(tenant: Tenant) -> tuple[uuid.UUID, str]:
    from apps.workers.pipeline import _upsert_call_row

    ecid = f"tl-{uuid.uuid4().hex}"
    snapshot = ExecutionSnapshot(
        engine_call_id=ecid,
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        engine="fake",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        ended_at=datetime.now(UTC),
        quality=CallQuality(turns=1, answer_ms_median=1900, reply_ms_median=700),
    )
    return await _upsert_call_row(tenant.tenant_id, tenant.agent_id, snapshot, None), ecid


def _payload(tenant: Tenant, call_id: uuid.UUID, ecid: str) -> dict[str, Any]:
    return {"tenant_id": str(tenant.tenant_id), "call_id": str(call_id), "execution_id": ecid}


async def _stored(tenant: Tenant, call_id: uuid.UUID) -> Any:
    async with tenant_session(tenant.tenant_id) as session:
        return (
            await session.execute(
                text("SELECT engine_timeline FROM calls WHERE id = :id"), {"id": call_id}
            )
        ).scalar_one()


async def test_an_empty_answer_is_retried_then_the_timeline_is_kept_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = await _tenant()
    call_id, ecid = await _call_row(tenant)
    engine = _Engine(None, _TIMELINE)
    monkeypatch.setattr(call_timeline, "get_engine", lambda: engine)

    with pytest.raises(Retry):
        await call_timeline.fetch_call_timeline({"job_try": 1}, _payload(tenant, call_id, ecid))
    assert await _stored(tenant, call_id) is None

    outcome = await call_timeline.fetch_call_timeline(
        {"job_try": 2}, _payload(tenant, call_id, ecid)
    )
    assert outcome == "stored:1"
    assert CallTimeline.model_validate(await _stored(tenant, call_id)) == _TIMELINE

    again = await call_timeline.fetch_call_timeline({"job_try": 1}, _payload(tenant, call_id, ecid))
    assert again == "already_stored" and engine.asked == [ecid, ecid]


async def test_the_last_try_stores_nothing_and_a_refusal_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = await _tenant()
    call_id, ecid = await _call_row(tenant)
    refused = ProblemError(
        kind="dependency",
        code="engine_rejected",
        title="Voice engine rejected the request",
        detail="The voice platform could not complete this operation.",
        failure_stage="CORE_LOGIC",
    )
    engine = _Engine(None, refused)
    monkeypatch.setattr(call_timeline, "get_engine", lambda: engine)

    last = await call_timeline.fetch_call_timeline({"job_try": 3}, _payload(tenant, call_id, ecid))
    assert last == "none_recorded"
    first = await call_timeline.fetch_call_timeline({"job_try": 1}, _payload(tenant, call_id, ecid))
    assert first == "refused:engine_rejected"
    assert await _stored(tenant, call_id) is None


def test_only_a_connected_call_an_agent_took_is_asked_about() -> None:
    def snapshot(**kw: Any) -> ExecutionSnapshot:
        base: dict[str, Any] = {
            "engine_call_id": "x",
            "status": "completed",
            "raw_status": "completed",
            "terminal": True,
            "billable_ready": True,
            "engine": "fake",
        }
        return ExecutionSnapshot(**(base | kw))

    assert call_timeline.timeline_expected(snapshot())
    assert call_timeline.timeline_expected(snapshot(quality=CallQuality(turns=3)))
    assert not call_timeline.timeline_expected(snapshot(quality=CallQuality(turns=0)))
    assert not call_timeline.timeline_expected(snapshot(forwarded=True))
    assert not call_timeline.timeline_expected(snapshot(status="no_answer"))


async def test_the_split_reaches_an_operator_and_never_a_client() -> None:
    tenant = await _tenant()
    call_id, _ = await _call_row(tenant)
    async with tenant_session(tenant.tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET engine_timeline = CAST(:t AS jsonb) WHERE id = :cid"),
            {"t": _TIMELINE.model_dump_json(), "cid": call_id},
        )
        client = await crm_service.get_call(session, call_id)
        operator = await crm_service.get_call(session, call_id, operator=True)

    assert client.timeline is None
    assert client.quality is not None and client.quality.answer_ms_median == 1900
    assert operator.timeline is not None
    (turn,) = operator.timeline
    assert (turn.answer_ms, turn.answer_estimated, turn.model_asked_ms) == (1900, True, -50)


async def test_a_quality_record_from_before_d902_still_reads() -> None:
    """D-901 stored `filler_turns` inside `engine_quality`; the call view ignores it."""
    tenant = await _tenant()
    call_id, _ = await _call_row(tenant)
    async with tenant_session(tenant.tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET engine_quality = engine_quality || '{\"filler_turns\": 2}' "
                "WHERE id = :cid"
            ),
            {"cid": call_id},
        )
        detail = await crm_service.get_call(session, call_id)
    assert detail.quality is not None and detail.quality.reply_ms_median == 700


# ------------------------------------------------- the adapter's reading of the wire shapes


def test_answer_time_and_knowledge_turns_are_read_and_old_calls_have_no_answer() -> None:
    """`CallQuality` of https://app.thinnest.ai/openapi.json, read 27 Oct 2026."""
    quality = parse_quality(
        {
            "turns": 4,
            "responseMs": {"median": 900, "p90": 1200, "max": 1500},
            "answerMs": {"median": 1400, "p90": 2100, "max": 2600},
            "knowledgeTurns": 2,
        }
    )
    assert quality is not None
    assert (quality.answer_ms_median, quality.answer_ms_p90, quality.answer_ms_max) == (
        1400,
        2100,
        2600,
    )
    assert quality.reply_ms_median == 900 and quality.knowledge_turns == 2

    before = parse_quality({"turns": 4, "responseMs": {"median": 900}, "answerMs": None})
    assert before is not None and before.answer_ms_median is None
    assert before.knowledge_turns is None


def test_a_timeline_is_read_in_turn_order_with_missing_steps_null() -> None:
    split = {
        "waitBeforeDecisionMs": 600,
        "recogniserMs": None,
        "earCheckMs": None,
        "modelFirstSentenceMs": 1500,
        "voiceMs": 380,
    }
    row = {
        "turn": 2,
        "callerStoppedAtMs": 9000,
        "modelAskedMs": -120,
        "firstAudioMs": 1200,
        "firstAudioKind": "filler",
        "answerAudioMs": 2400,
        "answerAudioEstimated": True,
        "split": split,
    }
    timeline = parse_timeline(
        {
            "v": 1,
            "turns": [
                row,
                {**row, "turn": 1, "firstAudioKind": "speech", "answerAudioEstimated": None},
                {"turn": None},
            ],
        }
    )
    assert timeline is not None
    assert [t.turn for t in timeline.turns] == [1, 2]
    second = timeline.turns[1]
    assert second.model_asked_ms == -120 and second.answer_estimated
    assert second.recogniser_ms is None and second.ear_check_ms is None
    assert second.wait_before_decision_ms == 600
    first = timeline.turns[0]
    assert first.first_sound_kind is None and first.answer_estimated is False
    assert parse_timeline(None) is None


def test_the_moments_behind_the_split_are_read_and_null_off_ear() -> None:
    """`CallTimelineTurn`'s moments (snapshots/2026-10-28/openapi.json, D-911): the three Ear
    ones are null on a timer turn; the turn decided and the answer text are on every turn."""
    ear = {
        "turn": 1,
        "earPausedMs": 480,
        "transcriptMs": 520,
        "judgeDecidedMs": 730,
        "turnDecidedMs": 735,
        "modelAskedMs": -40,
        "answerTextMs": 1600,
    }
    timer = {**ear, "turn": 2, "earPausedMs": None, "transcriptMs": None, "judgeDecidedMs": None}
    timeline = parse_timeline({"v": 1, "turns": [ear, timer]})
    assert timeline is not None
    first, second = timeline.turns
    assert (
        first.pause_called_ms,
        first.final_words_ms,
        first.check_decided_ms,
        first.turn_decided_ms,
        first.answer_text_ms,
    ) == (480, 520, 730, 735, 1600)
    assert (second.pause_called_ms, second.final_words_ms, second.check_decided_ms) == (
        None,
        None,
        None,
    )
    assert (second.turn_decided_ms, second.answer_text_ms) == (735, 1600)
