"""An in-call opt-out reaches `dnc_list`, and the next dispatch tick refuses the dial.

The gap this suite closes is the one `eval_known_gaps_test.py` pinned as Gap 5: a
caller could say "remove my number", the agent could confirm it politely, and nothing in
`apps/workers` or `apps/voice-runtime` ever wrote a suppression. `dnc.SOURCES` carried
`call_optout` from the beginning and only TESTS wrote it.

What is asserted here, in the order a regulator would ask it:

1. **the detector reads the caller, in three languages** — and refuses to read the
   AGENT, whose acknowledgement contains every keyword in the list;
2. **it agrees with the golden fixtures**, all 96 of them, in both directions: every
   case marked `requires_dnc` is detected and no other case is. That is the assertion
   that keeps the phrase list honest as the fixture set grows, and it is the same set
   the eval harness now scores (`scripts/eval.py::_check_compliance`);
3. **a completed call with an opt-out suppresses the number BEFORE THE NEXT TICK** —
   proven by running the real campaign dispatcher afterwards and asserting the contact
   comes back `dnc_blocked`, not by finding a row in a table;
4. **the evidence is written once**, however many times the pipeline replays (D-31
   makes a replay normal) and whichever of the two detectors got there first;
5. **the in-call tool endpoint** verifies its source, acks fast, writes nothing, and
   queues the job the worker actually registers;
6. **hard rule 6** — no phone number appears in a log line on any of these paths.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import engine_intake
import pytest
import tool_routes
from apps.api.campaigns import service as campaigns_service
from apps.api.compliance.optout import (
    CALL_OPTOUT_SOURCE,
    DETECTED_POST_CALL,
    OPTOUT_PURPOSE,
    detect_opt_out,
    record_call_optout,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from apps.workers import campaign_dispatch
from apps.workers.campaign_dispatch import dispatch_campaign_tick
from apps.workers.optout import OPTOUT_JOB, record_in_call_optout, tool_signal
from apps.workers.pipeline import ingest_engine_event, run_post_call_pipeline
from calevate_shared.engine import ExecutionSnapshot
from calevate_shared.events import TranscriptTurn
from httpx import ASGITransport, AsyncClient
from main import app as voice_app
from sqlalchemy import text

# The campaign harness, reused rather than rebuilt: a launch-ready campaign needs a PE
# registration, a registered number, an approved DLT template and consent provenance,
# and a second copy of that setup would drift from the gate it is supposed to satisfy.
from tests.campaigns_test import _quiesce, _ready_campaign

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST. Same fixture, same reason, as `campaigns_test`: the dispatch tick
    refuses outside calling hours, and this suite is about the DNC rule, not that one."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


@pytest.fixture(autouse=True)
def _roomy_platform_pool(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the platform-wide outbound pool above anything this module dials — same
    fixture, same reason, as `campaigns_test`: a second pytest process holding lines
    would starve the tick and this suite would fail on the contact it never reached,
    which is the dispatcher obeying FLOWS §5 rule 1 rather than a DNC defect."""
    monkeypatch.setattr(campaign_dispatch, "PLATFORM_LINES_TOTAL", 10_000)


class _Turn:
    """The two fields `detect_opt_out` reads (it takes a Protocol, not our model)."""

    def __init__(self, speaker: str, text_: str) -> None:
        self.speaker = speaker
        self.text = text_


# --- 1. the detector ---------------------------------------------------------


@pytest.mark.parametrize(
    ("utterance", "language"),
    [
        ("Naaku inka call cheyakandi.", "te"),
        ("Call cheyyoddu, naa number teeseyandi.", "te"),
        ("నా నంబర్ తీసేయండి", "te"),
        ("Mujhe aage se call mat kijiye.", "hi"),
        ("Meri number list se hata do.", "hi"),
        ("कॉल मत करो", "hi"),
        ("Stop calling me.", "en"),
        ("Please remove my number from your list.", "en"),
        ("Put me on your do not call list.", "en"),
    ],
)
def test_an_opt_out_is_recognised_in_the_language_it_was_spoken_in(
    utterance: str, language: str
) -> None:
    """TCCCPR gives the consumer the opt-out in whatever language they speak it — an
    opt-out recognised only in English is an opt-out most of Hyderabad does not have."""
    signal = detect_opt_out([_Turn("caller", utterance)])
    assert signal is not None, utterance
    assert signal.language == language


@pytest.mark.parametrize(
    "utterance",
    [
        # The agent's own acknowledgement, which contains every keyword there is.
        "Ardhamayindi, mee number ni do-not-call list lo pettanu.",
        "Ji, aapka number do-not-call list mein daal diya hai.",
    ],
)
def test_the_agent_saying_it_is_not_the_caller_asking_for_it(utterance: str) -> None:
    """If an agent turn could trigger a suppression, one prompt regression would
    suppress a client's entire contact list, one call at a time."""
    assert detect_opt_out([_Turn("agent", utterance)]) is None


@pytest.mark.parametrize(
    "utterance",
    [
        # Telugu's negative suffix is the whole meaning: `cheyandi` is "please DO call".
        "Repu maruntha call cheyandi.",
        "Naaku callback kavali, saayantram call cheyyandi.",
        # Annoyance is not an opt-out (`re_bargein_angry_about_repeat_calls`).
        "Ninna kuda chesaru kada! Enni sarlu chestaru?",
        # An erasure demand is a DPDP §12 request with its own surface, not a DNC entry.
        "Naa data motham delete cheyandi.",
        # A denial about something else entirely.
        "Naa appointment cancel cheyakandi.",
    ],
)
def test_what_is_not_an_opt_out_does_not_become_one(utterance: str) -> None:
    """The false-positive direction is the SAFE one (see `compliance/optout.py`), which
    is not a licence to be sloppy: suppressing the caller who just asked to be rung back
    is a lead the client paid for and a promise we then break."""
    assert detect_opt_out([_Turn("caller", utterance)]) is None


def test_the_detector_and_the_golden_fixtures_agree_in_both_directions() -> None:
    """Every `requires_dnc` case is detected; no other case is.

    96 fixtures' worth of coverage for a phrase list, and the assertion that catches a
    pattern widened until it fires on ordinary speech — which is the failure mode a
    recall-first list has. `scripts/eval.py` scores the same property on every run, so
    a new fixture cannot land in one place and be forgotten in the other.
    """
    payload = json.loads((REPO / "tests" / "fixtures" / "golden_transcripts.json").read_text())
    disagreed: list[str] = []
    for case in payload["cases"]:
        turns = [
            _Turn(
                "caller" if line.lower().startswith(("caller:", "customer:", "user:")) else "agent",
                line.split(":", 1)[1] if ":" in line else line,
            )
            for line in case["transcript"]
        ]
        detected = detect_opt_out(turns) is not None
        expected = bool(case.get("requires_dnc"))
        if detected != expected:
            disagreed.append(f"{case['id']}: detected={detected} requires_dnc={expected}")
    assert not disagreed, "detector disagrees with the fixtures:\n" + "\n".join(disagreed)


# --- 2. the call path --------------------------------------------------------

OPT_OUT_TURNS: tuple[tuple[str, str], ...] = (
    ("agent", "Namaskaram, idi Skyline Ventures AI assistant. Ee call record avutundi."),
    ("caller", "Naaku ee flats vaddu, inka call cheyakandi. Remove my number."),
    ("agent", "Ardhamayindi, mee number ni do-not-call list lo pettanu."),
)

QUIET_TURNS: tuple[tuple[str, str], ...] = (
    ("agent", "Namaskaram, idi Skyline Ventures AI assistant. Ee call record avutundi."),
    ("caller", "Ippudu time ledu, tarvata matladatanu."),
)


def _snapshot(
    execution_id: str, agent_ref: str, to_e164: str, turns: tuple[tuple[str, str], ...]
) -> ExecutionSnapshot:
    """A completed OUTBOUND call. `cost=None` and no recording on purpose: metering and
    the object store are other suites' subjects, and a test that needs a bucket to prove
    a compliance rule is a test that will be skipped."""
    now = datetime.now(UTC)
    return ExecutionSnapshot(
        engine_call_id=execution_id,
        engine_agent_ref=agent_ref,
        direction="outbound",
        status="completed",
        raw_status="completed",
        terminal=True,
        billable_ready=True,
        started_at=now - timedelta(seconds=60),
        ended_at=now,
        duration_s=60,
        from_e164="+911140000000",
        to_e164=to_e164,
        recording_url=None,
        transcript=[
            TranscriptTurn(call_id=execution_id, idx=i, speaker=speaker, text=text_)  # type: ignore[arg-type]
            for i, (speaker, text_) in enumerate(turns)
        ],
        cost=None,
        engine="fake",
    )


def _stage(monkeypatch: pytest.MonkeyPatch, snapshots: dict[str, ExecutionSnapshot]) -> None:
    """Make the fake engine answer `get_execution` with our transcripts."""

    async def _get(self: FakeEngine, call_id: str) -> ExecutionSnapshot:
        return snapshots[call_id]

    monkeypatch.setattr(FakeEngine, "get_execution", _get)


async def _agent_ref(tenant_id: uuid.UUID, agent_id: uuid.UUID) -> str:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT engine_agent_ref FROM engine_agent_routes "
                    "WHERE tenant_id = :t AND agent_id = :a AND active"
                ),
                {"t": tenant_id, "a": agent_id},
            )
        ).first()
    assert row is not None, "the campaign fixture publishes a route for its agent"
    return str(row[0])


async def _run_pipeline(tenant_id: uuid.UUID, execution_id: str) -> uuid.UUID:
    await ingest_engine_event({}, {"engine": "fake", "execution_id": execution_id})
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT id FROM calls WHERE engine_call_id = :e"), {"e": execution_id}
            )
        ).first()
    assert row is not None, "ingest must have upserted the call row"
    call_id = uuid.UUID(str(row[0]))
    await run_post_call_pipeline(
        {},
        {
            "tenant_id": str(tenant_id),
            "call_id": str(call_id),
            "engine": "fake",
            "execution_id": execution_id,
        },
    )
    return call_id


async def test_an_opt_out_on_one_call_stops_the_next_dispatch_tick(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE assertion this whole change exists for (hard rule 5).

    Not "a row appeared in `dnc_list`" — the real campaign dispatcher runs afterwards,
    against the real compliance gate, and the contact that opted out is refused while
    the one that did not is dialled. A row nobody enforces is what the gap looked like
    from the outside for the whole life of `dnc.SOURCES`.
    """
    reset_engine_cache()
    opted_out, still_dialable = "9876500002", "9876500001"
    tenant_id, agent_id, campaign_id = await _ready_campaign(phones=(still_dialable, opted_out))
    async with tenant_session(tenant_id) as session:
        launched = await campaigns_service.launch_campaign(
            session, tenant_id=tenant_id, campaign_id=campaign_id
        )
    assert launched["dnc_scrubbed"] == 0, "clean at launch — the suppression happens below"

    ref = await _agent_ref(tenant_id, agent_id)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    _stage(
        monkeypatch,
        {execution_id: _snapshot(execution_id, ref, f"+91{opted_out}", OPT_OUT_TURNS)},
    )
    await _run_pipeline(tenant_id, execution_id)

    await _quiesce(campaign_id)
    await dispatch_campaign_tick({})

    async with tenant_session(tenant_id) as session:
        statuses = dict(
            (
                await session.execute(
                    text("SELECT phone_e164, status FROM campaign_contacts WHERE campaign_id = :c"),
                    {"c": campaign_id},
                )
            ).all()
        )
        # Excluding the call the opt-out was SPOKEN on, which is itself an outbound
        # call to this number — the one dial that was lawful, because it happened
        # before the request existed.
        dialled = (
            (
                await session.execute(
                    text(
                        "SELECT to_e164 FROM calls WHERE direction = 'outbound' "
                        "AND engine_call_id <> :e"
                    ),
                    {"e": execution_id},
                )
            )
            .scalars()
            .all()
        )

    assert statuses[f"+91{opted_out}"] == "dnc_blocked", "the opt-out did not reach the gate"
    assert f"+91{opted_out}" not in dialled, "we dialled someone who asked us to stop"
    assert statuses[f"+91{still_dialable}"] == "dialing", "the other contact must be unaffected"


async def test_a_call_with_no_opt_out_suppresses_nobody(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The negative control the positive one is worthless without: a pipeline that
    suppressed every caller would pass the test above."""
    reset_engine_cache()
    tenant_id, agent_id, _campaign = await _ready_campaign(phones=("9876500003",))
    ref = await _agent_ref(tenant_id, agent_id)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    _stage(
        monkeypatch,
        {execution_id: _snapshot(execution_id, ref, "+919876500003", QUIET_TURNS)},
    )
    await _run_pipeline(tenant_id, execution_id)

    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM dnc_list WHERE phone_e164 = '+919876500003'")
            )
        ).scalar()
    assert rows == 0


async def test_the_evidence_is_written_once_however_often_the_pipeline_replays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A webhook that arrives after the poller already resolved the call re-enters the
    pipeline (D-31), so a replay is NORMAL. `consent_ledger` is append-only (hard rule
    4), which means the guard has to be a pre-check — and an un-guarded write would file
    the same consumer request three times and make the ledger unreadable as evidence."""
    reset_engine_cache()
    tenant_id, agent_id, _campaign = await _ready_campaign(phones=("9876500004",))
    ref = await _agent_ref(tenant_id, agent_id)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    _stage(
        monkeypatch,
        {execution_id: _snapshot(execution_id, ref, "+919876500004", OPT_OUT_TURNS)},
    )
    call_id = await _run_pipeline(tenant_id, execution_id)
    await _run_pipeline(tenant_id, execution_id)
    await _run_pipeline(tenant_id, execution_id)

    async with tenant_session(tenant_id) as session:
        suppressions = (
            await session.execute(
                text("SELECT source FROM dnc_list WHERE phone_e164 = '+919876500004'")
            )
        ).all()
        ledger = (
            await session.execute(
                text(
                    "SELECT status, consent_source, call_id, evidence FROM consent_ledger "
                    "WHERE phone_e164 = '+919876500004' AND purpose = :p"
                ),
                {"p": OPTOUT_PURPOSE},
            )
        ).all()
    async with untenanted_session() as session:
        audits = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE tenant_id = :t "
                    "AND action = 'compliance.call_optout_recorded'"
                ),
                {"t": tenant_id},
            )
        ).scalar()

    assert [row[0] for row in suppressions] == [CALL_OPTOUT_SOURCE]
    assert len(ledger) == 1, "three replays wrote three withdrawals"
    status, consent_source, ledger_call, evidence = ledger[0]
    assert status == "withdrawn"
    assert consent_source == "inbound_call_verbal"
    assert uuid.UUID(str(ledger_call)) == call_id, "the evidence must name the call it came from"
    assert evidence["detected_by"] == DETECTED_POST_CALL
    assert evidence["matched"], "a withdrawal with no words behind it is not evidence"
    assert audits == 1, "the audit chain records the request, not the replays"


async def test_a_number_suppressed_by_the_caller_cannot_be_deleted_by_the_client() -> None:
    """The 90-day rule, from the other end (TCCCPR: a sender may not re-solicit an
    opted-out customer for ninety days). `dnc.REMOVABLE_SOURCES` already refuses it —
    this asserts the source this path writes is inside that refusal, which is the only
    reason the refusal applies."""
    from apps.api.compliance.dnc import SOURCES, is_removable

    assert CALL_OPTOUT_SOURCE in SOURCES
    assert not is_removable(scope="tenant", source=CALL_OPTOUT_SOURCE)


# --- 3. the in-call tool endpoint --------------------------------------------

ENGINE_EGRESS_IP = "198.51.100.7"
ATTACKER_IP = "203.0.113.9"
EDGE_PROXY_IP = "127.0.0.1"
TOOL = "/tools/v1/bolna/opt-out"
HEADERS = {"CF-Connecting-IP": ENGINE_EGRESS_IP}


@pytest.fixture
def _allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine_intake, "BOLNA_SOURCE_IPS", frozenset({ENGINE_EGRESS_IP}))


def _tool_client(peer_ip: str = EDGE_PROXY_IP) -> AsyncClient:
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444)),
        base_url="http://runtime",
    )


def test_the_endpoint_and_the_worker_name_the_same_job() -> None:
    """`tool_routes` cannot import `apps.workers` (hard rule 3, and the import-surface
    test enforces it), so the job name is spelled twice. This is what stops the two
    spellings drifting into an ack for a job nobody runs."""
    assert tool_routes.OPTOUT_JOB == OPTOUT_JOB


async def test_a_stranger_cannot_suppress_a_clients_number(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The endpoint is unsigned, so the source check is the whole authenticity control.
    An open one would be a denial-of-service against a client's own contact list,
    dressed as compliance."""
    enqueued: list[str] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        # Awaitable, so a bypassed source check fails on the ASSERTION below rather than
        # on a TypeError — a refusal that regresses should say what it was.
        enqueued.append(job)
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    async with _tool_client() as http:
        response = await http.post(
            TOOL,
            json={"execution_id": "exec_x"},
            headers={"CF-Connecting-IP": ATTACKER_IP},
        )
    assert response.status_code == 401
    assert enqueued == []
    assert "X-Ack-Ms" in response.headers, "a refusal is measured too"


async def test_an_engine_tool_call_queues_the_work_and_writes_nothing(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Hard rule 3: ack fast, defer everything. The endpoint may not resolve a tenant,
    may not touch the database, and may not answer "done" for work a worker has not
    done — `accepted` is the honest word."""
    captured: list[tuple[str, dict[str, Any]]] = []

    async def _spy(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        captured.append((job, payload))
        return "job-1"

    monkeypatch.setattr(tool_routes, "enqueue", _spy)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    async with _tool_client() as http:
        response = await http.post(
            TOOL,
            json={"execution_id": execution_id, "reason": "caller asked to be removed"},
            headers=HEADERS,
        )
    assert response.status_code == 202
    assert response.json()["status"] == "accepted"
    assert float(response.headers["X-Ack-Ms"]) < 500.0
    assert captured and captured[0][0] == OPTOUT_JOB
    # The payload carries the execution id and hints — never a phone number, which the
    # worker reads back from the authenticated fetch instead (D-31).
    assert captured[0][1]["execution_id"] == execution_id
    assert "phone" not in json.dumps(captured[0][1])


async def test_a_tool_call_that_names_no_execution_is_refused_not_acked(
    _allowlist: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The one place this endpoint deliberately differs from the webhook receiver: an
    unkeyable webhook is acked because the poller recovers it, and an unkeyable TOOL
    call has no poller behind it. Acking would tell the agent the caller's request was
    registered when nothing was."""

    async def _never(job: str, payload: dict[str, Any], **kwargs: Any) -> str:
        raise AssertionError("an unkeyable tool call must not queue anything")

    monkeypatch.setattr(tool_routes, "enqueue", _never)
    async with _tool_client() as http:
        response = await http.post(TOOL, json={"reason": "remove me"}, headers=HEADERS)
    assert response.status_code == 422
    # RFC-9457: the machine-readable code lives in `type`, not a `code` member.
    assert response.json()["type"].endswith("/tool_call_unkeyable")


async def test_the_in_call_job_suppresses_the_number_the_engine_reports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The belt half, end to end: only an execution id crosses the queue, and the
    number, direction and tenant are read back from the engine and our routing table."""
    reset_engine_cache()
    tenant_id, agent_id, _campaign = await _ready_campaign(phones=("9876500005",))
    ref = await _agent_ref(tenant_id, agent_id)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    _stage(
        monkeypatch,
        {execution_id: _snapshot(execution_id, ref, "+919876500005", OPT_OUT_TURNS)},
    )

    outcome = await record_in_call_optout(
        {}, {"engine": "fake", "execution_id": execution_id, "reason": "remove my number"}
    )
    assert outcome == "recorded"

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT source FROM dnc_list WHERE phone_e164 = '+919876500005' "
                    "AND tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
        evidence = (
            await session.execute(
                text(
                    "SELECT evidence FROM consent_ledger WHERE phone_e164 = '+919876500005' "
                    "AND purpose = :p"
                ),
                {"p": OPTOUT_PURPOSE},
            )
        ).scalar()
    assert row is not None and row[0] == CALL_OPTOUT_SOURCE
    assert evidence["detected_by"] == "in_call_tool"
    assert evidence["rule"] == "engine_tool_call", "a model's judgement is labelled as one"


async def test_the_tool_and_the_transcript_pass_do_not_double_file_one_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Belt AND braces, one record. Both detectors see the same call: the tool fires
    mid-call and the transcript pass fires minutes later, and the consumer made ONE
    request."""
    reset_engine_cache()
    tenant_id, agent_id, _campaign = await _ready_campaign(phones=("9876500006",))
    ref = await _agent_ref(tenant_id, agent_id)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    _stage(
        monkeypatch,
        {execution_id: _snapshot(execution_id, ref, "+919876500006", OPT_OUT_TURNS)},
    )
    # The call row first (the status webhook always precedes an in-call tool call), so
    # the tool path can name the call it belongs to — which is what makes the two
    # detectors dedupe against each other rather than merely against themselves.
    await ingest_engine_event({}, {"engine": "fake", "execution_id": execution_id})
    await record_in_call_optout({}, {"engine": "fake", "execution_id": execution_id})
    await _run_pipeline(tenant_id, execution_id)

    async with tenant_session(tenant_id) as session:
        ledger = (
            await session.execute(
                text(
                    "SELECT evidence FROM consent_ledger WHERE phone_e164 = '+919876500006' "
                    "AND purpose = :p"
                ),
                {"p": OPTOUT_PURPOSE},
            )
        ).all()
    assert len(ledger) == 1, "one request, one withdrawal row"
    assert ledger[0][0]["detected_by"] == "in_call_tool", "the first detector wins"


# --- 4. hard rule 6 ----------------------------------------------------------


async def test_no_path_here_logs_a_phone_number(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Ids, rules and counts. The number is the one thing every line here is about and
    the one thing none of them may contain."""
    reset_engine_cache()
    subject = "9876500007"
    tenant_id, agent_id, _campaign = await _ready_campaign(phones=(subject,))
    ref = await _agent_ref(tenant_id, agent_id)
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    _stage(
        monkeypatch,
        {execution_id: _snapshot(execution_id, ref, f"+91{subject}", OPT_OUT_TURNS)},
    )
    with caplog.at_level(logging.DEBUG):
        await _run_pipeline(tenant_id, execution_id)
    emitted = "\n".join(record.getMessage() + str(record.__dict__) for record in caplog.records)
    assert subject not in emitted, "a phone number reached the logs (hard rule 6)"


async def test_an_unusable_number_is_refused_rather_than_suppressed_under_a_bad_key() -> None:
    """A suppression stored under a string the dispatch gate will never match looks like
    protection and blocks nothing — worse than no row, because it stops anyone looking
    further."""
    from apps.api.core.errors import ProblemError

    tenant_id, _agent, _campaign = await _ready_campaign(phones=())
    async with tenant_session(tenant_id) as session:
        with pytest.raises(ProblemError) as raised:
            await record_call_optout(
                session,
                tenant_id=tenant_id,
                raw_phone="not-a-number",
                call_id=None,
                detected_by=DETECTED_POST_CALL,
                signal=tool_signal(reason="remove me", language="en"),
            )
    assert raised.value.code == "optout_phone_invalid"
