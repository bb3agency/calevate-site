"""The first run, "Meet your agent" (D-855): its state, questions, build and own-number tick.

Every case makes its own tenant. The model and speech-to-text are replaced at the worker's
own seams; what is under test is what reaches the row, the profile and the agent.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.agents import lifecycle
from apps.api.agents.hosted_voices import HostedVoiceRow, sold_hosted_band
from apps.api.agents.starters import (
    CATALOGUE,
    JOB_DIRECTION,
    JOBS_OF_DIRECTION,
    LINES_OF_JOB,
    starter_for,
)
from apps.api.agents.trial_calls import own_number_ref
from apps.api.agents.voice_pick import choose_voice, rank_voices
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.first_run import names, questions
from apps.api.first_run import service as first_run
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
    assert body["due"] is True and body["job"] is None and body["recordings_left"] == 3
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
        await first_run.save_job(
            session, tenant_id=mine, job="call_leads", language_primary="te-IN", languages_extra=[]
        )
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
        assert (await first_run.read_state(session, tenant_id=theirs)).job is None
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
        job = await http.put(
            "/v1/first-run/job",
            headers=headers,
            json={
                "job": "call_new_leads",
                "language_primary": "te-IN",
                "languages_extra": ["en-IN"],
            },
        )
        assert job.status_code == 200, job.text
        assert job.json()["job"] == "call_new_leads"
        assert job.json()["languages_extra"] == ["en-IN"]
        brief = await http.put("/v1/first-run/brief", headers=headers, json={"brief": "Flats"})
    questions_out = brief.json()["questions"]
    assert questions_out["status"] == "ready"
    assert [item["key"] for item in questions_out["items"]] == ["trade", "location", "offer"]
    trade = questions_out["items"][0]
    assert trade["kind"] == "choices" and "Villas" in trade["options"]
    assert (await _run(tenant_id)).question_runs == 0


async def test_a_long_brief_lets_the_model_choose_only_from_the_fixed_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        await http.put(
            "/v1/first-run/job",
            headers=headers,
            json={"job": "answer_calls", "language_primary": "te-IN"},
        )
        writing = await http.put("/v1/first-run/brief", headers=headers, json={"brief": LONG_BRIEF})
    assert writing.json()["questions"]["status"] == "writing"
    run = await _run(tenant_id)

    async def chose(*_args: Any, parse: Any, **_kwargs: Any) -> SimpleNamespace:
        # The model names a key it was not offered and repeats one: both are dropped.
        return _answer(parse({"questions": ["hours", "staff", "hours", "booking"]}))

    monkeypatch.setattr(worker, "ask_json", chose)
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
    async with _client() as http:
        ready = await http.get("/v1/first-run", headers=headers)
    assert [item["key"] for item in ready.json()["questions"]["items"]] == ["hours", "booking"]
    booking = ready.json()["questions"]["items"][1]
    assert booking["prompt"] == "How does someone book a site visit?"


async def test_with_no_model_the_questions_are_the_profiles_gaps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from apps.api.core.errors import ProblemError

    tenant_id = await _tenant()
    async with tenant_session(tenant_id) as session:
        await first_run.save_job(
            session,
            tenant_id=tenant_id,
            job="answer_calls",
            language_primary="te-IN",
            languages_extra=[],
        )
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
    assert [q["key"] for q in (await _run(tenant_id)).questions] == ["trade", "location", "offer"]


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


async def test_the_answers_land_in_the_business_profile_merged() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        saved = await http.post(
            "/v1/first-run/answers",
            headers=headers,
            json={
                "trade": ["Apartments", "Villas"],
                "location": "Plot 4, Kondapur, Hyderabad",
                "offer": [{"name": "Villas", "price_inr": "9500000"}],
                "hours": {"opens": "09:30", "closes": "19:00", "closed": ["sun"]},
                "booking": "We confirm site visits on WhatsApp within an hour.",
            },
        )
        refused = await http.post(
            "/v1/first-run/answers", headers=headers, json={"trade": ["Spaceships"]}
        )
    assert saved.status_code == 200, saved.text
    assert refused.status_code == 422 and refused.json()["type"].endswith("/first_run_trade_choice")
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


# ------------------------------------------------------------------ the spoken brief


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


# ------------------------------------------------------------------ the build


async def _ready_to_build(tenant_id: uuid.UUID, brief: str) -> None:
    async with tenant_session(tenant_id) as session:
        await first_run.save_job(
            session,
            tenant_id=tenant_id,
            job="answer_calls",
            language_primary="en-IN",
            languages_extra=[],
        )
        await first_run.save_brief(session, tenant_id=tenant_id, brief=brief)
        await first_run.request_build(session, tenant_id=tenant_id, user_id=None)


async def _no_voice(_tenant_id: uuid.UUID, _language: str) -> None:
    return None


async def test_the_build_writes_the_script_from_the_brief_and_names_the_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    await _ready_to_build(tenant_id, LONG_BRIEF)
    run = await _run(tenant_id)
    written = (
        CATALOGUE[("real_estate", "answer_calls")]
        .call_script(business="Madhav Homes", language="en-IN")
        .model_copy(
            update={
                "identity": "You answer the phone for Madhav Homes.",
                "opening_line": "Hello, Madhav Homes. Are you looking for a flat or a villa?",
            }
        )
    )
    briefs: list[str] = []

    async def drafted(brief: Any, **_kwargs: Any) -> SimpleNamespace:
        briefs.append(brief.description)
        return SimpleNamespace(
            script=written,
            capability=SimpleNamespace(disclosure=None),
            earlier=(),
            model=None,
            usage=None,
        )

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", drafted)
    monkeypatch.setattr(worker, "_meter", _no_meter)
    payload = {"tenant_id": str(tenant_id), "run_id": str(run.id), "build": 1}
    assert await worker.build_first_agent({}, payload) == "built"
    assert await worker.build_first_agent({}, payload) == "not_pending"

    after = await _run(tenant_id)
    assert after.build_status == "built"
    assert {k: v["state"] for k, v in after.build_steps.items() if k != "claimed"} == {
        "voice": "none",
        "script": "done",
        "greeting": "done",
        "notice": "done",
    }
    assert "Kondapur" in briefs[0] and "Kiran" in briefs[0]
    async with tenant_session(tenant_id) as session:
        agent = (
            await session.execute(
                text("SELECT name, direction, status FROM agents WHERE id = :aid"),
                {"aid": after.agent_id},
            )
        ).one()
        from apps.api.agents.script_builder import load_agent_script

        script = (await load_agent_script(session, after.agent_id)).script
    assert tuple(agent) == ("Kiran", "inbound", "draft")
    assert script.identity.startswith("Your name is Kiran. You answer the phone")
    assert script.opening_line == "Hello, Madhav Homes. Are you looking for a flat or a villa?"


async def test_a_short_brief_keeps_the_ready_made_script_and_still_names_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id = await _tenant()
    await _ready_to_build(tenant_id, "Flats")
    run = await _run(tenant_id)

    async def never(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("no model for a short brief")

    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    monkeypatch.setattr(worker, "draft_script", never)
    await worker.build_first_agent(
        {}, {"tenant_id": str(tenant_id), "run_id": str(run.id), "build": 1}
    )
    after = await _run(tenant_id)
    assert after.build_steps["script"]["state"] == "ready_made"
    async with tenant_session(tenant_id) as session:
        from apps.api.agents.script_builder import load_agent_script

        script = (await load_agent_script(session, after.agent_id)).script
    assert script.identity.startswith("Your name is Kiran.")


async def test_the_job_is_locked_once_the_agent_is_built(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    await _ready_to_build(tenant_id, "Flats")
    run = await _run(tenant_id)
    monkeypatch.setattr(worker, "pick_voice", _no_voice)
    await worker.build_first_agent(
        {}, {"tenant_id": str(tenant_id), "run_id": str(run.id), "build": 1}
    )
    async with _client() as http:
        moved = await http.put(
            "/v1/first-run/job",
            headers=headers,
            json={"job": "call_leads", "language_primary": "en-IN"},
        )
        renamed = await http.put("/v1/first-run/name", headers=headers, json={"name": "Lakshmi"})
    assert moved.status_code == 409 and moved.json()["type"].endswith("/first_run_job_locked")
    assert renamed.status_code == 200, renamed.text
    async with tenant_session(tenant_id) as session:
        from apps.api.agents.script_builder import load_agent_script

        script = (await load_agent_script(session, (await _run(tenant_id)).agent_id)).script
    assert script.identity.startswith("Your name is Lakshmi.")
    assert "Kiran" not in script.identity


async def test_building_without_a_job_is_refused() -> None:
    tenant_id = await _tenant()
    headers = await _owner(tenant_id)
    async with _client() as http:
        refused = await http.post("/v1/first-run/build", headers=headers)
    assert refused.json()["type"].endswith("/first_run_not_ready")


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


def test_the_name_suits_the_voice_and_the_identity_is_never_stacked() -> None:
    assert names.suggested_name("te-IN", names.gender_of("Female")) == "Sravani"
    assert names.suggested_name("hi-IN", names.gender_of("male")) == "Arjun"
    assert names.suggested_name("en-IN", names.gender_of(None)) == "Kiran"
    once = names.identity_with_name("You answer the phone.", "Kiran")
    twice = names.identity_with_name(once, "Priya")
    assert twice == "Your name is Priya. You answer the phone."


def test_greeting_rule_is_the_first_agent_rule() -> None:
    assert worker.greeting_fits("Hello, how can I help you today?", "en-IN")
    assert not worker.greeting_fits("Hello, welcome.", "en-IN")
    assert not worker.greeting_fits("x" * 120 + "?", "en-IN")


def test_questions_already_answered_are_not_asked() -> None:
    from apps.api.tenancy.business_profile import Branch, Profile, ServiceItem

    profile = Profile(
        tenant_id=uuid.uuid4(),
        branches=[Branch(label="Main", address="Kondapur")],
        services=[ServiceItem(name="Villas", price_inr="100")],
    )
    assert questions.askable(profile, "real_estate") == ("hours", "booking")
    assert questions.askable(Profile(tenant_id=uuid.uuid4()), "custom") == (
        "location",
        "offer",
        "hours",
        "booking",
    )


def _voice(
    voice_id: str, *, accent: str | None, label: str, source: str = "engine"
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
        gender="female",
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


async def test_a_build_lost_for_ten_minutes_reads_as_failed_and_can_be_tried_again() -> None:
    tenant_id = await _tenant()
    await _ready_to_build(tenant_id, "Flats")
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE first_runs SET build_requested_at = now() - interval '11 minutes'")
        )
    async with tenant_session(tenant_id) as session:
        assert (await first_run.read_state(session, tenant_id=tenant_id)).build_status == "failed"
        again = await first_run.request_build(session, tenant_id=tenant_id, user_id=None)
    assert again.build_status == "building" and again.build_runs == 2
