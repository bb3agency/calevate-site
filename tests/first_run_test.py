"""The first run, "Meet your agent" (D-855): its state, questions, answers and own-number tick.

Every case makes its own tenant. The model and speech-to-text are replaced at the worker's
own seams; what is under test is what reaches the row, the profile and the agent.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any, Final

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle
from apps.api.agents.hosted_voices import HostedVoiceRow, sold_hosted_band
from apps.api.agents.starters import (
    JOB_DIRECTION,
    JOBS_OF_DIRECTION,
    LINES_OF_JOB,
    starter_for,
)
from apps.api.agents.trial_calls import own_number_ref
from apps.api.agents.voice_pick import choose_voice, gender_of, rank_voices
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.first_run import names, questions
from apps.api.first_run import service as first_run
from apps.api.first_run.questions import ONE_THING
from apps.api.main import app
from apps.api.tenancy.business_profile import load_profile
from apps.workers import first_run as worker
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.conftest import FakeS3

LONG_BRIEF = (
    "We sell apartments and villas in Kondapur. Callers want prices and a site visit; "
    "take their budget and the BHK they want."
)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _tenant(vertical: str = "real_estate") -> uuid.UUID:
    created = await admin_service.create_organization(
        name="Madhav Homes",
        slug=f"meet-{uuid.uuid4().hex[:8]}",
        vertical_template=vertical,
        billing_email=None,
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _owner(tenant_id: uuid.UUID) -> dict[str, str]:
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :e, now(), now())"
            ),
            {"id": user_id, "e": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    return {"Authorization": f"Bearer dev:client:{user_id}"}


async def _run(tenant_id: uuid.UUID) -> Any:
    async with tenant_session(tenant_id) as session:
        return (await session.execute(text("SELECT * FROM first_runs"))).one()


def _answer(value: Any) -> SimpleNamespace:
    return SimpleNamespace(
        value=value,
        capability=SimpleNamespace(disclosure=None),
        earlier=(),
        model=None,
        usage=None,
    )


async def _no_meter(*_args: Any, **_kwargs: Any) -> None:
    return None


# ------------------------------------------------------------------ state and routing


async def test_a_new_account_is_due_and_one_with_its_own_agent_is_not() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        fresh = await http.get("/v1/first-run", headers=headers)
    assert fresh.status_code == 200, fresh.text
    body = fresh.json()
    assert body["due"] is True and body["jobs"] == [] and body["recordings_left"] == 3
    assert [step["state"] for step in body["build"]["steps"]] == ["waiting"] * 4

    async with tenant_session(tenant_id) as session:
        await lifecycle.create_agent(
            session,
            tenant_id=tenant_id,
            name="Made elsewhere",
            direction="inbound",
            language_primary="te-IN",
            starter="answer_calls",
        )
    async with _client() as http:
        later = await http.get("/v1/first-run", headers=headers)
    assert later.json()["due"] is False


async def test_putting_it_aside_stops_the_junction_sending_the_owner_back() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        dismissed = await http.post("/v1/first-run/dismiss", headers=headers)
    assert dismissed.status_code == 200
    assert dismissed.json()["due"] is False and dismissed.json()["dismissed_at"] is not None


@pytest.mark.rls
async def test_another_tenant_reads_zero_rows() -> None:
    mine = await _tenant()
    theirs = await _tenant()
    async with tenant_session(mine) as session:
        await first_run.start_recording(
            session,
            tenant_id=mine,
            recording_id=uuid7(),
            language="te-IN",
            object_key="kb-uploads/x/y/brief.webm",
            content_type="audio/webm",
        )
    async with tenant_session(theirs) as session:
        for table in ("first_runs", "first_run_recordings"):
            assert (await session.execute(text(f"SELECT count(*) FROM {table}"))).scalar() == 0
        assert (await first_run.read_state(session, tenant_id=theirs)).jobs == []
    with pytest.raises(Exception, match="row-level security"):
        async with tenant_session(theirs) as session:
            await session.execute(
                text("INSERT INTO first_runs (id, tenant_id) VALUES (:id, :t)"),
                {"id": uuid7(), "t": mine},
            )


# ------------------------------------------------------------------ job, brief, questions


async def test_a_short_brief_asks_the_profiles_own_gaps_without_a_model() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        brief = await http.put("/v1/first-run/brief", headers=headers, json={"brief": "Flats"})
    questions_out = brief.json()["questions"]
    assert questions_out["status"] == "ready"
    items = questions_out["items"]
    # The profile's gaps, then the one every owner is asked (D-945).
    # No menu of guessed offerings per business type (G2-5): what the business sells is
    # offered as choices only by the model, which read the owner's own words.
    assert [item["maps_to"] for item in items] == ["location", "offer", "hours", None]
    assert items[-1]["id"] == ONE_THING.id
    assert [item["id"] for item in items] == ["q1", "q2", "q3", ONE_THING.id]
    assert (await _run(tenant_id)).question_runs == 0


#: What a model might write for a property office: two good questions, and one each of the
#: kinds of item the gate must drop whole.
WRITTEN: Final = [
    {
        "prompt": "Which areas of Hyderabad do your projects cover?",
        "hint": "Callers often ask whether you have something near them.",
        "kind": "choices",
        "options": ["Kondapur", "Gachibowli", "Kokapet"],
        "maps_to": None,
    },
    {
        "prompt": "Do you help with home loans?",
        "hint": "",
        "kind": "single_choice",
        "options": ["Yes, we arrange them", "No"],
        "maps_to": None,
    },
    {
        "prompt": "See **our** site",
        "hint": "",
        "kind": "text",
        "options": [],
        "maps_to": None,
    },
    {
        "prompt": "Visit www.example.com?",
        "hint": "",
        "kind": "text",
        "options": [],
        "maps_to": None,
    },
    {
        "prompt": "When are you open? 😀",
        "hint": "",
        "kind": "hours",
        "options": [],
        "maps_to": "hours",
    },
    {"prompt": "Where are you?", "hint": "", "kind": "address", "options": [], "maps_to": None},
]


async def test_the_model_writes_the_questions_and_the_gate_drops_bad_ones(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        writing = await http.put("/v1/first-run/brief", headers=headers, json={"brief": LONG_BRIEF})
    assert writing.json()["questions"]["status"] == "writing"
    run = await _run(tenant_id)
    sent: list[str] = []

    async def wrote(description: str, *_args: Any, parse: Any, **_kwargs: Any) -> SimpleNamespace:
        sent.append(description)
        return _answer(parse({"questions": WRITTEN}))

    monkeypatch.setattr(worker, "ask_json", wrote)
    monkeypatch.setattr(worker, "_meter", _no_meter)
    outcome = await worker.write_first_run_questions(
        {},
        {
            "tenant_id": str(tenant_id),
            "run_id": str(run.id),
            "brief_hash": run.questions_brief_hash,
        },
    )
    assert outcome == "ready"
    assert "Kondapur" in sent[0], "the brief is what the model writes from"
    async with _client() as http:
        ready = await http.get("/v1/first-run", headers=headers)
    items = ready.json()["questions"]["items"]
    assert [(i["id"], i["kind"]) for i in items] == [
        ("q1", "choices"),
        ("q2", "single_choice"),
        (ONE_THING.id, "text"),
    ]
    assert items[0]["prompt"] == "Which areas of Hyderabad do your projects cover?"


async def test_the_questions_are_charged_in_the_transaction_that_stores_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A charge committed before a store that fails would be taken again when the queue
    retries the job, which still finds the run writing."""
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        await http.put("/v1/first-run/brief", headers=headers, json={"brief": LONG_BRIEF})
    run = await _run(tenant_id)
    sessions: dict[str, object] = {}

    async def wrote(description: str, *_args: Any, parse: Any, **_kwargs: Any) -> SimpleNamespace:
        return _answer(parse({"questions": WRITTEN}))

    real_store = worker.store_questions

    async def store(session: Any, **kwargs: Any) -> bool:
        sessions["store"] = session
        return await real_store(session, **kwargs)

    async def meter(session: Any, *_args: Any) -> None:
        sessions["meter"] = session

    monkeypatch.setattr(worker, "ask_json", wrote)
    monkeypatch.setattr(worker, "store_questions", store)
    monkeypatch.setattr(worker, "_meter", meter)
    assert (
        await worker.write_first_run_questions(
            {},
            {
                "tenant_id": str(tenant_id),
                "run_id": str(run.id),
                "brief_hash": run.questions_brief_hash,
            },
        )
        == "ready"
    )
    assert sessions["meter"] is sessions["store"]


def test_the_gate_drops_an_item_rather_than_repairing_it() -> None:
    from apps.api.tenancy.business_profile import Profile

    profile = Profile(tenant_id=uuid.uuid4())
    good = dict(WRITTEN[0])
    cases: list[dict[str, Any]] = [
        {**good, "prompt": "x" * 91},
        {**good, "hint": "y" * 141},
        {**good, "options": ["Only one"]},
        {**good, "options": [f"Area {n}" for n in range(9)]},
        {**good, "options": ["Kondapur", "kondapur"]},
        {**good, "options": ["A" * 41, "B"]},
        {**good, "prompt": " Leading space?"},
        {**good, "prompt": "Mee shop ekkada undi? ఎక్కడ"},
        {**good, "prompt": "Email us at owner@example.in?"},
        {**good, "prompt": "# Heading?"},
        {**good, "kind": "text"},
        {**good, "kind": "address", "options": [], "maps_to": None},
        {**good, "kind": "services", "options": [], "maps_to": "offer", "prompt": "1234?"},
        {**good, "maps_to": "location"},
        {**good, "maps_to": "staff"},
        "not an object",
    ]
    for case in cases:
        assert questions.written_questions([case], profile) == [], case
    assert len(questions.written_questions([good] * 6, profile)) == 1, "the same prompt once"
    many = [{**good, "prompt": f"Question number {n}?"} for n in range(6)]
    assert [q.id for q in questions.written_questions(many, profile)] == ["q1", "q2", "q3"]


def test_a_section_already_known_is_not_asked_about_again() -> None:
    from apps.api.tenancy.business_profile import Branch, Profile

    profile = Profile(tenant_id=uuid.uuid4(), branches=[Branch(label="Main", address="X")])
    where = {"prompt": "Where are you?", "hint": "", "kind": "address", "options": []}
    assert questions.written_questions([{**where, "maps_to": "location"}], profile) == []
    hours = {"prompt": "When are you open?", "hint": "", "kind": "hours", "options": []}
    twice = [{**hours, "maps_to": "hours"}, {**hours, "maps_to": "hours", "prompt": "Hours?"}]
    assert len(questions.written_questions(twice, Profile(tenant_id=uuid.uuid4()))) == 1


async def test_with_no_model_the_questions_are_the_profiles_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.errors import ProblemError

    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await first_run.save_brief(session, tenant_id=tenant_id, brief=LONG_BRIEF)
    run = await _run(tenant_id)

    async def refused(*_args: Any, **_kwargs: Any) -> None:
        raise ProblemError.business_rule("assist_unavailable", "No model.")

    monkeypatch.setattr(worker, "ask_json", refused)
    await worker.write_first_run_questions(
        {},
        {
            "tenant_id": str(tenant_id),
            "run_id": str(run.id),
            "brief_hash": run.questions_brief_hash,
        },
    )
    stored = (await _run(tenant_id)).questions
    assert [q["maps_to"] for q in stored] == ["location", "offer", "hours", None]


async def test_a_run_from_before_d863_reads_its_keys_as_the_fixed_questions() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO first_runs (id, tenant_id, questions_status, questions) "
                "VALUES (:id, :t, 'ready', CAST(:q AS jsonb))"
            ),
            {"id": uuid7(), "t": tenant_id, "q": '[{"key": "hours"}, {"key": "booking"}]'},
        )
    async with _client() as http:
        read = await http.get("/v1/first-run", headers=headers)
    items = read.json()["questions"]["items"]
    assert [(i["id"], i["maps_to"]) for i in items] == [("q1", "hours"), ("q2", "booking")]
    assert items[1]["prompt"] == "How does someone book a site visit?"


async def test_a_stale_questions_job_writes_nothing_over_a_newer_brief(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await first_run.save_brief(session, tenant_id=tenant_id, brief=LONG_BRIEF)
    old = await _run(tenant_id)
    async with tenant_session(tenant_id) as session:
        await first_run.save_brief(session, tenant_id=tenant_id, brief=LONG_BRIEF + " Also plots.")
    monkeypatch.setattr(worker, "ask_json", None)
    outcome = await worker.write_first_run_questions(
        {},
        {
            "tenant_id": str(tenant_id),
            "run_id": str(old.id),
            "brief_hash": old.questions_brief_hash,
        },
    )
    assert outcome == "not_pending"


async def test_questions_whose_job_died_read_as_failed_and_the_brief_can_ask_again() -> None:
    """A questions job killed by a database error or `job_timeout` is not retried by arq.
    The row stayed `writing`, the screen read the brief for ever, and saving the same brief
    returned early instead of asking again."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        state = await first_run.save_brief(session, tenant_id=tenant_id, brief=LONG_BRIEF)
    assert state.questions_status == "writing"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE first_runs SET updated_at = now() - interval '11 minutes'")
        )
    async with tenant_session(tenant_id) as session:
        state = await first_run.read_state(session, tenant_id=tenant_id)
    assert state.questions_status == "failed"

    async with tenant_session(tenant_id) as session:
        state = await first_run.save_brief(session, tenant_id=tenant_id, brief=LONG_BRIEF)
    assert state.questions_status == "writing"
    assert (await _run(tenant_id)).question_runs == 2, "the same brief was asked again"


async def _asked(tenant_id: uuid.UUID, items: list[questions.Question]) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO first_runs (id, tenant_id, questions_status, questions) "
                "VALUES (:id, :t, 'ready', CAST(:q AS jsonb))"
            ),
            {"id": uuid7(), "t": tenant_id, "q": json.dumps([q.stored() for q in items])},
        )


async def test_the_answers_land_in_the_business_profile_merged() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    # A trade question as the model writes one (the fixed set asks none, G2-5).
    trade = questions.Question(
        "q1",
        "What do you sell or rent?",
        "Pick all that apply.",
        "choices",
        options=("Apartments", "Villas", "Plots"),
        maps_to="trade",
    )
    fixed = [trade] + [
        questions.fixed_question(topic, "real_estate", question_id=f"q{n}")
        for n, topic in enumerate(questions.PROFILE_TOPICS, 1)
        if topic != "trade"
    ]
    loans = questions.Question("q6", "Do you help with loans?", "", "single_choice", ("Yes", "No"))
    await _asked(tenant_id, [q for q in fixed if q is not None] + [loans])
    async with _client() as http:
        saved = await http.post(
            "/v1/first-run/answers",
            headers=headers,
            json={
                "answers": [
                    {"id": "q1", "choices": ["Apartments", "Villas"]},
                    {"id": "q2", "text": "Plot 4, Kondapur, Hyderabad"},
                    {"id": "q3", "services": [{"name": "Villas", "price_inr": "9500000"}]},
                    {"id": "q4", "hours": {"opens": "09:30", "closes": "19:00", "closed": ["sun"]}},
                ]
            },
        )
        later = await http.post(
            "/v1/first-run/answers",
            headers=headers,
            json={
                "answers": [
                    {"id": "q5", "text": "We confirm site visits on WhatsApp within an hour."},
                    {"id": "q6", "choices": ["Yes"]},
                ]
            },
        )
        refusals = [
            await http.post("/v1/first-run/answers", headers=headers, json={"answers": [bad]})
            for bad in (
                {"id": "q1", "choices": ["Spaceships"]},
                {"id": "q6", "choices": ["Yes", "No"]},
                {"id": "q2", "choices": ["Kondapur"]},
                {"id": "q4", "text": "nine to five"},
                {"id": "q9", "text": "no such question"},
            )
        ]
    assert saved.status_code == 200, saved.text
    assert later.status_code == 200, later.text
    for refused in refusals:
        assert refused.status_code == 422, refused.text
        assert refused.json()["type"].endswith("/first_run_answer_mismatch")
    stored = (await _run(tenant_id)).answers
    assert [a["id"] for a in stored] == ["q1", "q2", "q3", "q4", "q5", "q6"]
    assert stored[5]["choices"] == ["Yes"] and stored[5]["maps_to"] is None
    async with tenant_session(tenant_id) as session:
        profile = await load_profile(session, tenant_id=tenant_id)
    assert [(s.name, s.price_inr) for s in profile.services] == [
        ("Apartments", None),
        ("Villas", "9500000"),
    ]
    assert profile.branches[0].label == first_run.MAIN_BRANCH_LABEL
    assert profile.hours["sun"] is None and profile.hours["mon"] == {
        "opens": "09:30",
        "closes": "19:00",
    }
    assert profile.booking_rules == "We confirm site visits on WhatsApp within an hour."


async def test_a_facts_answer_becomes_one_faq_however_often_it_is_sent() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    area = questions.Question("q1", "Which areas do you serve?", "", "text", maps_to="facts")
    await _asked(tenant_id, [area])
    async with _client() as http:
        for said in ("Kondapur and Gachibowli.", "Kondapur, Gachibowli and Madhapur."):
            sent = await http.post(
                "/v1/first-run/answers",
                headers=headers,
                json={"answers": [{"id": "q1", "text": said}]},
            )
            assert sent.status_code == 200, sent.text
        too_long = await http.post(
            "/v1/first-run/answers",
            headers=headers,
            json={"answers": [{"id": "q1", "text": "x" * 1001}]},
        )
    assert too_long.status_code == 422, too_long.text
    async with tenant_session(tenant_id) as session:
        profile = await load_profile(session, tenant_id=tenant_id)
    assert [(f.question, f.answer) for f in profile.faqs] == [
        ("Which areas do you serve?", "Kondapur, Gachibowli and Madhapur.")
    ]


async def test_the_address_answer_sent_again_keeps_one_main_branch() -> None:
    """The screen sends the answers again whenever "Build my agent" is pressed again (after a
    refused build) or the questions are answered again after Back. Each send used to append
    another "Main branch", so the agent had the same address on file twice; a corrected
    address now replaces the first."""
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    where = questions.fixed_question("location", "real_estate", question_id="q1")
    assert where is not None
    await _asked(tenant_id, [where])
    async with _client() as http:
        for address in (
            "Plot 4, Kondapur, Hyderabad",
            "Plot 4, Kondapur, Hyderabad",
            "Plot 9, Kondapur, Hyderabad",
        ):
            sent = await http.post(
                "/v1/first-run/answers",
                headers=headers,
                json={"answers": [{"id": "q1", "text": address}]},
            )
            assert sent.status_code == 200, sent.text
    async with tenant_session(tenant_id) as session:
        profile = await load_profile(session, tenant_id=tenant_id)
    assert [(b.label, b.address) for b in profile.branches] == [
        (first_run.MAIN_BRANCH_LABEL, "Plot 9, Kondapur, Hyderabad")
    ]


# ------------------------------------------------------------------ the spoken brief


async def test_a_recording_whose_worker_died_reads_failed_and_frees_its_slot(
    s3: FakeS3,
) -> None:
    """A job cancelled while transcribing is not retried and its claim is spent, so
    `hearing` would keep the screen waiting forever and hold one of the recording slots."""
    from apps.api.first_run import service as first_run_service

    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        posted = await http.post(
            "/v1/first-run/recordings",
            headers=headers,
            files={"file": ("brief.webm", b"opus-bytes", "audio/webm")},
            data={"language": "te-IN"},
        )
    recording_id = posted.json()["id"]
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE first_run_recordings SET status = 'hearing', "
                "updated_at = now() - make_interval(mins => :m) WHERE id = :id"
            ),
            {"id": recording_id, "m": first_run_service.HEARING_STALE_MINUTES + 1},
        )
        run_id = (
            await session.execute(
                text("SELECT first_run_id FROM first_run_recordings WHERE id = :id"),
                {"id": recording_id},
            )
        ).scalar_one()
        assert await first_run_service._recordings_used(session, run_id) == 0
    async with _client() as http:
        read = await http.get(f"/v1/first-run/recordings/{recording_id}", headers=headers)
    assert read.json()["status"] == "failed"
    assert read.json()["error_code"] == "crashed"


async def test_a_recording_is_heard_and_its_audio_deleted(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        posted = await http.post(
            "/v1/first-run/recordings",
            headers=headers,
            files={"file": ("brief.webm", b"opus-bytes", "audio/webm")},
            data={"language": "te-IN"},
        )
    assert posted.status_code == 201, posted.text
    recording_id = posted.json()["id"]
    async with tenant_session(tenant_id) as session:
        key = (
            await session.execute(
                text("SELECT object_key FROM first_run_recordings WHERE id = :id"),
                {"id": recording_id},
            )
        ).scalar_one()
    hints: list[str | None] = []

    async def heard(_data: bytes, _ctype: str, *, language: str | None = None) -> str:
        hints.append(language)
        return "  We sell flats  in Kondapur "

    monkeypatch.setattr(worker, "transcribe", heard)
    monkeypatch.setattr(worker, "meter_clip", _no_meter)
    assert (
        await worker.hear_first_run_recording(
            {}, {"tenant_id": str(tenant_id), "recording_id": recording_id}
        )
        == "heard"
    )
    async with _client() as http:
        read = await http.get(f"/v1/first-run/recordings/{recording_id}", headers=headers)
    assert read.json()["status"] == "heard" and read.json()["words"] == "We sell flats in Kondapur"
    assert hints == ["te-IN"]
    assert key not in s3.objects
    async with tenant_session(tenant_id) as session:
        assert (
            await session.execute(
                text("SELECT object_key FROM first_run_recordings WHERE id = :id"),
                {"id": recording_id},
            )
        ).scalar_one() is None


async def _posted_clip(tenant_id: uuid.UUID) -> tuple[str, str]:
    """(recording id, object key) of one clip posted by the owner."""
    headers = await _owner(tenant_id)
    async with _client() as http:
        posted = await http.post(
            "/v1/first-run/recordings",
            headers=headers,
            files={"file": ("brief.webm", b"opus-bytes", "audio/webm")},
            data={"language": "te-IN"},
        )
    assert posted.status_code == 201, posted.text
    recording_id = posted.json()["id"]
    async with tenant_session(tenant_id) as session:
        key = (
            await session.execute(
                text("SELECT object_key FROM first_run_recordings WHERE id = :id"),
                {"id": recording_id},
            )
        ).scalar_one()
    return recording_id, str(key)


async def test_a_clip_whose_audio_could_not_be_deleted_keeps_its_key(
    monkeypatch: pytest.MonkeyPatch, s3: FakeS3
) -> None:
    """The store went down between hearing and deleting. Clearing the key would leave the
    owner's voice in the bucket with nothing pointing at it."""
    tenant_id = await _tenant()
    recording_id, key = await _posted_clip(tenant_id)

    async def unheard(_data: bytes, _ctype: str, *, language: str | None = None) -> str:
        s3.fail = True
        raise httpx.ConnectError("stt down")

    monkeypatch.setattr(worker, "transcribe", unheard)
    result = await worker.hear_first_run_recording(
        {}, {"tenant_id": str(tenant_id), "recording_id": recording_id}
    )

    assert result == "failed"
    assert key in s3.objects
    async with tenant_session(tenant_id) as session:
        status, kept = (
            await session.execute(
                text("SELECT status, object_key FROM first_run_recordings WHERE id = :id"),
                {"id": recording_id},
            )
        ).one()
    assert status == "failed" and kept == key


async def test_the_account_erasure_deletes_brief_clips_with_no_knowledge_uploads(
    s3: FakeS3,
) -> None:
    """The clips sit under the knowledge-upload folder with no `kb_uploads` row."""
    from apps.api.compliance import tenant_erasure
    from apps.workers.retention import execute_tenant_erasure

    tenant_id = await _tenant()
    _recording_id, key = await _posted_clip(tenant_id)
    assert key in s3.objects
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE organizations SET status = 'churned' WHERE id = :tid"),
            {"tid": tenant_id},
        )
        record = await tenant_erasure.request_tenant_erasure(
            session, tenant_id=tenant_id, reason="offboarding"
        )

    await execute_tenant_erasure({}, {"tenant_id": str(tenant_id), "request_id": str(record.id)})

    assert key not in s3.objects


async def test_a_fourth_recording_is_refused(s3: FakeS3) -> None:
    del s3
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        for _ in range(3):
            ok = await http.post(
                "/v1/first-run/recordings",
                headers=headers,
                files={"file": ("brief.webm", b"opus", "audio/webm")},
                data={"language": "te-IN"},
            )
            assert ok.status_code == 201
        fourth = await http.post(
            "/v1/first-run/recordings",
            headers=headers,
            files={"file": ("brief.webm", b"opus", "audio/webm")},
            data={"language": "te-IN"},
        )
    assert fourth.json()["type"].endswith("/first_run_recordings_used")


# ------------------------------------------------------------------ "this number is mine"


async def test_the_own_number_tick_is_audited_by_reference_only() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        await http.post(
            "/v1/trial/calls",
            headers={**headers, "Idempotency-Key": uuid.uuid4().hex},
            json={"agent_id": str(uuid.uuid4()), "number": "+919876543210", "number_is_mine": True},
        )
    async with tenant_session(tenant_id) as session:
        actions = (
            await session.execute(
                text("SELECT action FROM audit_log WHERE tenant_id = :t AND action = :a"),
                {"t": tenant_id, "a": "trial.number_attested"},
            )
        ).all()
    assert len(actions) == 1
    ref = own_number_ref(tenant_id, "+919876543210")
    assert len(ref) == 64 and "9876543210" not in ref
    assert own_number_ref(tenant_id, "+919876543210") == ref


# ------------------------------------------------------------------ pure rules


def test_every_job_has_a_starter_and_the_outbound_pair_shares_its_line_set() -> None:
    assert JOB_DIRECTION["call_new_leads"] == "outbound"
    assert set(JOBS_OF_DIRECTION["outbound"]) == {"call_new_leads", "call_leads"}
    assert LINES_OF_JOB["call_new_leads"] == "call_leads"
    fresh = starter_for("real_estate", "call_new_leads")
    listed = starter_for("real_estate", "call_leads")
    assert len(fresh.steps) == len(listed.steps)
    assert "enquiry you just made" in fresh.opening_line


def test_every_combination_of_jobs_is_one_valid_script_for_every_trade() -> None:
    from itertools import combinations

    from apps.api.agents.starters import (
        STARTER_JOBS,
        TRADES,
        direction_of_jobs,
        jobs_label,
        starter_script,
    )

    for size in (1, 2, 3):
        for jobs in combinations(STARTER_JOBS, size):
            for vertical in TRADES:
                script = starter_script(vertical, jobs, business="Sri Estates", language="te-IN")
                assert len(script.stages) <= 12, (vertical, jobs)
    assert direction_of_jobs(["call_leads"]) == "outbound"
    assert direction_of_jobs(["call_leads", "call_new_leads"]) == "outbound"
    assert direction_of_jobs(["answer_calls"]) == "inbound"
    assert direction_of_jobs(["call_leads", "answer_calls"]) == "both"
    assert jobs_label(["call_leads", "answer_calls"]) == "Answer my calls + Run calling campaigns"


def test_the_identity_is_never_stacked() -> None:
    assert gender_of("Female") == "female" and gender_of("woman") == "female"
    assert gender_of("male") == "male" and gender_of(None) is None
    once = names.identity_with_name("You answer the phone.", "Anjali")
    twice = names.identity_with_name(once, "Priya")
    assert twice == "Your name is Priya. You answer the phone."


def test_questions_already_answered_are_not_asked() -> None:
    from apps.api.tenancy.business_profile import Branch, Profile, ServiceItem

    profile = Profile(
        tenant_id=uuid.uuid4(),
        branches=[Branch(label="Main", address="Kondapur")],
        services=[ServiceItem(name="Villas", price_inr="100")],
    )

    def topics(p: Profile, vertical: str) -> list[str | None]:
        return [q.maps_to for q in questions.fallback_questions(p, vertical, limit=4)]

    assert topics(profile, "real_estate") == ["hours", "booking"]
    assert topics(Profile(tenant_id=uuid.uuid4()), "custom") == [
        "location",
        "offer",
        "hours",
        "booking",
    ]


def test_hours_are_asked_only_where_they_mean_something() -> None:
    """FAILS IF: a helpline or an app's support line (no place to come to, nothing to book or
    order) is asked "When are you open?", or a business with no premises that does take
    bookings is asked about a door it does not have."""
    from apps.api.tenancy.business_profile import Profile

    empty = Profile(tenant_id=uuid.uuid4())
    helpline = questions.QuestionWords(has_premises=False, goes_ahead=False)
    assert "hours" in questions.closed_topics(empty, helpline)
    asked = questions.fallback_questions(empty, "custom", limit=5, words=helpline)
    assert "hours" not in [q.maps_to for q in asked]
    assert questions.fixed_question("hours", "custom", question_id="q1", words=helpline) is None

    field_team = questions.QuestionWords(has_premises=False)
    hours = questions.fixed_question("hours", "custom", question_id="q1", words=field_team)
    assert hours is not None and hours.prompt == "What are your working hours?"
    assert "hours" not in questions.closed_topics(empty, field_team)

    shop = questions.fixed_question("hours", "retail", question_id="q1")
    assert shop is not None and shop.prompt == "When are you open?"


def test_other_facts_have_a_section_the_model_may_ask_more_than_once() -> None:
    from apps.api.tenancy.business_profile import Profile

    def item(prompt: str, kind: str = "text") -> dict[str, object]:
        return {"prompt": prompt, "hint": "", "kind": kind, "options": [], "maps_to": "facts"}

    written = questions.written_questions(
        [item("Which areas do you serve?"), item("Who can apply?"), item("Pick", "hours")],
        Profile(tenant_id=uuid.uuid4()),
    )
    assert [(q.prompt, q.maps_to) for q in written] == [
        ("Which areas do you serve?", "facts"),
        ("Who can apply?", "facts"),
    ]
    assert questions.fixed_question("facts", "custom", question_id="q1") is None


def _voice(
    voice_id: str,
    *,
    accent: str | None,
    label: str,
    source: str = "engine",
    gender: str | None = "female",
) -> HostedVoiceRow:
    return HostedVoiceRow(
        voice_id=voice_id,
        source=source,  # type: ignore[arg-type]
        vendor_id=voice_id,
        label=label,
        vendor_label=label,
        display_label=None,
        provider="thinnest",
        accent=accent,
        description=None,
        language_note="",
        is_custom=False,
        state="enabled",
        origin="operator",
        synced_at=datetime.now(UTC),
        curated_at=None,
        withdrawn_at=None,
        preview_available=True,
        preview_source=None,
        clone_id=None,
        band=sold_hosted_band() if source == "engine" else None,
        gender=gender,
        languages=("te-IN", "hi-IN", "en-IN"),
        person_clone=False,
        consent=None,
    )


def _ranked(rows: list[HostedVoiceRow], rung: str, attested: set[str]) -> list[str]:
    return [
        row.label
        for row in rank_voices(
            rows,
            rung=rung,  # type: ignore[arg-type]
            engine="thinnest",
            language="te-IN",
            attested=attested,
            platform="the platform",
            voice_key_priced=True,
        )
    ]


def test_each_rung_ranks_voices_that_speak_the_language_with_its_accent_first() -> None:
    rows = [
        _voice("engine:a", accent="en-IN", label="Asha"),
        _voice("engine:b", accent="te-IN", label="Bindu"),
        _voice("byok:c", accent="te-IN", label="Chitra", source="byok"),
        _voice("byok:d", accent="en-IN", label="Deepa", source="byok"),
    ]
    attested = {rows[0].rate_key, rows[2].rate_key}
    assert _ranked(rows, "clear", attested) == ["Bindu", "Asha"]
    assert _ranked(rows, "studio", attested) == ["Chitra", "Deepa"]
    assert _ranked(rows, "clear", set()) == [] and _ranked(rows, "studio", set()) == []


def test_studio_is_picked_first_and_clear_stands_in_with_the_reason() -> None:
    studio = [_voice("byok:c", accent="te-IN", label="Chitra", source="byok")]
    clear = [_voice("engine:b", accent="te-IN", label="Bindu")]
    first = choose_voice(studio, clear, None)
    assert first is not None and (first.row.label, first.rung, first.fallback) == (
        "Chitra",
        "studio",
        None,
    )
    used = choose_voice(studio, clear, "studio_minutes_used")
    assert used is not None and (used.row.label, used.rung, used.fallback) == (
        "Bindu",
        "clear",
        "studio_minutes_used",
    )
    none_listed = choose_voice([], clear, None)
    assert none_listed is not None and none_listed.fallback == "no_studio_voice"
    assert choose_voice([], [], None) is None


def test_anjali_gets_a_womans_voice_studio_first_then_clear_then_the_best_flagged() -> None:
    ravi = _voice("byok:r", accent="te-IN", label="Ravi", source="byok", gender="male")
    sita = _voice("byok:s", accent="en-IN", label="Sita", source="byok")
    gopal = _voice("engine:g", accent="te-IN", label="Gopal", gender="male")
    bindu = _voice("engine:b", accent="te-IN", label="Bindu", gender="Female")
    unsaid = _voice("engine:u", accent="te-IN", label="Uma", gender=None)

    def picked(studio: list[HostedVoiceRow], clear: list[HostedVoiceRow], hindrance: Any) -> Any:
        got = choose_voice(studio, clear, hindrance)
        assert got is not None
        return (got.row.label, got.rung, got.fallback, got.not_female)

    # A woman's Studio voice wins over a better-ranked man's.
    assert picked([ravi, sita], [bindu], None) == ("Sita", "studio", None, False)
    # Studio has no woman's voice for the language: a woman's Clear voice, and why.
    assert picked([ravi], [gopal, bindu], None) == (
        "Bindu",
        "clear",
        "no_female_studio_voice",
        False,
    )
    # Studio cannot be used here: the hindrance stays the reason.
    assert picked([sita], [bindu], "studio_minutes_used") == (
        "Bindu",
        "clear",
        "studio_minutes_used",
        False,
    )
    # No woman's voice anywhere (an unstated gender is not counted as one): the best, flagged.
    assert picked([ravi], [gopal, unsaid], None) == ("Ravi", "studio", None, True)
    # The best kept is one whose gender nobody stated: it may be a woman's, so it is not
    # flagged as not one (C8-a, 28 Nov 2026).
    assert picked([unsaid], [gopal], None) == ("Uma", "studio", None, False)
    assert picked([], [unsaid, gopal], None) == ("Uma", "clear", "no_studio_voice", False)
    assert picked([], [gopal], None) == ("Gopal", "clear", "no_studio_voice", True)
    assert picked([sita], [unsaid], "studio_unavailable") == (
        "Uma",
        "clear",
        "studio_unavailable",
        False,
    )


async def test_a_trial_whose_studio_minutes_are_used_gets_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.agents import voice_pick
    from apps.api.billing.trials import start_new_account_trial

    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await start_new_account_trial(
            session, tenant_id=tenant_id, actor=None, ip=None, reason="test"
        )

    async def open_to(_session: Any, *, tenant_id: uuid.UUID | None) -> bool:
        return True

    async def used_all(_session: Any, *, tenant_id: uuid.UUID, trial: Any) -> int:
        return 10_000

    monkeypatch.setattr(voice_pick, "studio_open_to", open_to)
    assert await voice_pick.studio_hindrance(tenant_id) is None
    monkeypatch.setattr(voice_pick, "trial_studio_seconds_used", used_all)
    assert await voice_pick.studio_hindrance(tenant_id) == "studio_minutes_used"

    async def closed(_session: Any, *, tenant_id: uuid.UUID | None) -> bool:
        return False

    monkeypatch.setattr(voice_pick, "studio_open_to", closed)
    assert await voice_pick.studio_hindrance(tenant_id) == "studio_unavailable"


async def test_a_build_lost_for_ten_minutes_reads_as_failed() -> None:
    """A run whose build was started before the build was removed never finishes; its
    screen must not tick for ever."""
    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO first_runs (id, tenant_id, build_status, build_requested_at) "
                "VALUES (:id, :t, 'building', now() - interval '11 minutes')"
            ),
            {"id": uuid7(), "t": tenant_id},
        )
        assert (await first_run.read_state(session, tenant_id=tenant_id)).build_status == "failed"
