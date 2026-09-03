"""The weekly QA spot-check queue — 5% of calls per client per week (SURFACES §1).

    GET  /v1/admin/qa-samples                    (apps/api/quality/sampling_routes.py)
    GET  /v1/admin/qa-samples/{id}
    POST /v1/admin/qa-samples/{id}/review
    cron draw_qa_samples                         (apps/workers/qa_sampling.py)

A spot-check nobody can reconstruct is a habit, not a control. These tests pin the
properties that make it one, ranked by what their absence would cost:

1. **REPRODUCIBLE.** The same week drawn twice is the same calls, and the row carries the
   seed and rank that prove it. A sample that cannot be re-derived cannot be defended to
   a client or a regulator, and `random()` would pass every other test in this file.
2. **NOT SILENTLY RE-SAMPLED.** Re-running the draw inserts nothing. The weekly tick
   retries, fires late, and gets replayed; every one of those must converge.
3. **5% OF THE RIGHT FRAME.** Completed calls, in the IST week that CLOSED — never the
   week in progress, which would sample a Monday and file it as a week.
4. **HARD RULE 5.** What a reviewer sees is `text_redacted`, through the SAME
   `crm.service.get_call(raw=False)` the client's own screen uses. There is no raw
   variant on this router, and this suite asserts the absence — not just that the
   default is redacted, but that a second path to raw does not exist.
5. **AUDITED.** Opening a sampled call writes `qa_sample.read`; recording a verdict
   writes `qa_sample.reviewed`. A redacted disclosure of one tenant's call to somebody
   outside that tenant is exactly the read an audit trail exists for (SEC-COMP §5).
6. **HARD RULE 1.** Tenant B's samples are invisible to tenant A's session, on the raw
   RLS-scoped session as well as through the route.
7. **REGISTERED.** The cron is on a real `arq.worker.Worker` schedule and carries an
   explicit `max_tries` — `cron()` defaults it to 1 and `WorkerSettings.max_tries` does
   not reach a function that sets its own.

Run: uv run pytest -q tests/qa_sampling_test.py
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import apps.workers.qa_sampling as qa_worker
import pytest
from apps.api.admin import service as admin_service
from apps.api.core.errors import ProblemError
from apps.api.core.rbac import MUTATING_PERMISSIONS, iter_api_routes, route_enforcement
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.quality import sampling
from apps.api.quality.models import QA_SAMPLE_RATE
from apps.api.quality.sampling import (
    QA_VERDICTS,
    draw_week_sample,
    ist_week_start,
    list_samples,
    record_review,
    seed_for,
)
from apps.workers.qa_sampling import closed_weeks, draw_for_tenants
from apps.workers.settings import WorkerSettings
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

pytestmark = [pytest.mark.rls]

QUEUE_PATH = "/v1/admin/qa-samples"

#: A week that is safely closed, expressed as an instant inside it.
LAST_WEEK = datetime.now(UTC) - timedelta(days=8)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "operator") -> str:
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}"


async def _tenant() -> uuid.UUID:
    created = await admin_service.create_organization(
        name=f"Sample Clinic {uuid.uuid4().hex[:6]}",
        slug=f"sample-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"]))


async def _calls(
    tenant_id: uuid.UUID, *, count: int, when: datetime, status: str = "completed"
) -> list[uuid.UUID]:
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        ids: list[uuid.UUID] = []
        for _ in range(count):
            call_id = uuid7()
            ids.append(call_id)
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, started_at, duration_s, created_at, updated_at) "
                    "VALUES (:i, :t, :a, :e, 'inbound', '+919876500001', :s, :at, 61, "
                    "now(), now())"
                ),
                {
                    "i": call_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"qa_{uuid.uuid4().hex[:12]}",
                    "s": status,
                    "at": when,
                },
            )
        return ids


async def _turn(tenant_id: uuid.UUID, call_id: uuid.UUID, raw: str, redacted: str) -> None:
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                "text_redacted, created_at, updated_at) "
                "VALUES (:i, :t, :c, 0, 'caller', :raw, :red, now(), now())"
            ),
            {"i": uuid7(), "t": tenant_id, "c": call_id, "raw": raw, "red": redacted},
        )


async def _drawn(tenant_id: uuid.UUID, *, count: int = 40, when: datetime = LAST_WEEK):
    """A tenant with `count` completed calls last week, sampled."""
    await _calls(tenant_id, count=count, when=when)
    week = ist_week_start(when)
    async with tenant_session(tenant_id) as session:
        return await draw_week_sample(session, tenant_id=tenant_id, week_start=week)


# --- 1. Reproducible --------------------------------------------------------------


async def test_the_same_week_drawn_twice_is_the_same_calls() -> None:
    """The property that makes the sample defensible: it is a function of the data, not
    of the moment somebody ran it."""
    tenant_id = await _tenant()
    await _drawn(tenant_id)
    async with tenant_session(tenant_id) as session:
        first = {row.call_id for row in await list_samples(session)}

    # Re-derive it from scratch against a second tenant holding the same call ids is not
    # possible (ids differ by design), so the check is that the draw is stable AND that
    # the stored rank matches a recomputation of the published order.
    async with tenant_session(tenant_id) as session:
        week = ist_week_start(LAST_WEEK)
        recomputed = (
            await session.execute(
                text(
                    "SELECT id FROM calls WHERE status = 'completed' "
                    "AND date_trunc('week', started_at AT TIME ZONE 'Asia/Kolkata')::date = :w "
                    "ORDER BY md5(:seed || id::text), id LIMIT :n"
                ),
                {"w": week, "seed": seed_for(tenant_id, week), "n": len(first)},
            )
        ).all()
    assert {uuid.UUID(str(r[0])) for r in recomputed} == first


async def test_every_row_carries_the_frame_and_the_seed_it_was_drawn_with() -> None:
    """Without population/target/seed on the row, "we sample 5%" is unfalsifiable."""
    tenant_id = await _tenant()
    await _drawn(tenant_id, count=40)
    async with tenant_session(tenant_id) as session:
        rows = await list_samples(session)
    week = ist_week_start(LAST_WEEK)
    assert rows, "40 completed calls must produce a sample"
    for row in rows:
        assert row.population == 40
        assert row.target == len(rows)
        assert row.selection_seed == seed_for(tenant_id, week)
        assert 1 <= row.selection_rank <= row.target


# --- 2. No silent re-sampling ------------------------------------------------------


async def test_redrawing_a_week_inserts_nothing() -> None:
    """The weekly tick retries, fires late and gets replayed. Every one of those must
    converge on the sample already taken rather than taking a second one."""
    tenant_id = await _tenant()
    first = await _drawn(tenant_id)
    assert first.inserted > 0
    week = ist_week_start(LAST_WEEK)
    async with tenant_session(tenant_id) as session:
        again = await draw_week_sample(session, tenant_id=tenant_id, week_start=week)
        rows = await list_samples(session)
    assert again.inserted == 0
    assert len(rows) == first.inserted


# --- 3. The right frame ------------------------------------------------------------


async def test_five_percent_rounded_up_with_a_floor_of_one() -> None:
    """40 calls → 2. A tenant with 3 calls still gets one looked at: a rate that rounds
    a small client down to zero means the smallest accounts are never checked, which is
    where an unnoticed defect lives longest."""
    busy = await _tenant()
    await _drawn(busy, count=40)
    async with tenant_session(busy) as session:
        assert len(await list_samples(session)) == round(40 * QA_SAMPLE_RATE)

    quiet = await _tenant()
    await _drawn(quiet, count=3)
    async with tenant_session(quiet) as session:
        rows = await list_samples(session)
    assert len(rows) == 1
    assert rows[0].population == 3


async def test_only_completed_calls_are_in_the_frame() -> None:
    """A `no_answer` row has no conversation in it, so reviewing one reviews nothing —
    and counting one inflates the denominator the 5% is taken from."""
    tenant_id = await _tenant()
    await _calls(tenant_id, count=20, when=LAST_WEEK, status="no_answer")
    await _calls(tenant_id, count=20, when=LAST_WEEK, status="completed")
    week = ist_week_start(LAST_WEEK)
    async with tenant_session(tenant_id) as session:
        drawn = await draw_week_sample(session, tenant_id=tenant_id, week_start=week)
    assert drawn.population == 20


async def test_a_completed_call_with_nothing_said_on_it_is_still_in_the_frame() -> None:
    """The frame's one honest limitation, MEASURED rather than assumed.

    `status = 'completed'` is the vendor's word for "the call connected and ended", not
    for "somebody spoke": a voicemail, an immediate hangup and a caller who says nothing
    all arrive as completed executions with zero transcript turns. So a reviewer's queue
    can contain a call whose transcript is empty, and the 5% denominator counts it.

    This test exists because the module docstring used to argue the frame the other way
    ("reviewing one reviews nothing"), which is true of these rows too. Narrowing the
    frame to calls that carry a turn is a decision about what "5% of calls" means to a
    client and to a regulator, and it belongs to whoever makes it — with this test and
    that paragraph changed together, deliberately, rather than discovered by a reviewer
    opening a blank screen.
    """
    tenant_id = await _tenant()
    silent = await _calls(tenant_id, count=20, when=LAST_WEEK)
    week = ist_week_start(LAST_WEEK)
    async with tenant_session(tenant_id) as session:
        drawn = await draw_week_sample(session, tenant_id=tenant_id, week_start=week)
        drawn_ids = {row.call_id for row in await list_samples(session)}

    assert drawn.population == 20, (
        "the frame is by STATUS: a completed call with no transcript is counted, and the "
        "module docstring says so"
    )
    assert drawn.inserted == 1, "5% of 20, and the row was filed against a blank transcript"
    assert drawn_ids <= set(silent), (
        "a silent completed call reaches a reviewer's queue — if this ever stops being "
        "true, the docstring's `WHAT THE FRAME IS` section is what has to change with it"
    )


async def test_the_job_only_ever_asks_for_weeks_that_have_closed() -> None:
    """A tick that drew the current week would sample a Monday morning and file it as a
    week — 5% of one day, presented as 5% of seven."""
    now = datetime(2026, 8, 14, 3, 0, tzinfo=UTC)  # a Friday
    weeks = closed_weeks(now)
    assert all(week < ist_week_start(now) for week in weeks)
    assert weeks == sorted(weeks, reverse=True)


async def test_a_call_from_another_week_is_not_in_this_weeks_sample() -> None:
    tenant_id = await _tenant()
    await _calls(tenant_id, count=20, when=datetime.now(UTC) - timedelta(days=30))
    week = ist_week_start(LAST_WEEK)
    async with tenant_session(tenant_id) as session:
        drawn = await draw_week_sample(session, tenant_id=tenant_id, week_start=week)
    assert drawn.population == 0
    assert drawn.inserted == 0


# --- 4 + 5. Hard rule 5, and the audit ---------------------------------------------


async def test_a_reviewer_sees_the_redacted_transcript_and_the_read_is_audited() -> None:
    tenant_id = await _tenant()
    call_ids = await _calls(tenant_id, count=20, when=LAST_WEEK)
    for call_id in call_ids:
        await _turn(tenant_id, call_id, "call me on 9876543210", "call me on [phone ••10]")
    week = ist_week_start(LAST_WEEK)
    async with tenant_session(tenant_id) as session:
        await draw_week_sample(session, tenant_id=tenant_id, week_start=week)
        sample = (await list_samples(session))[0]

    token = await _make_admin()
    async with _client() as http:
        response = await http.get(
            f"{QUEUE_PATH}/{sample.id}", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 200, response.text
    body = response.json()
    turns = body["call"]["transcript"]
    assert turns[0]["redacted"] is True
    assert "9876543210" not in response.text
    assert "[phone ••10]" in turns[0]["text"]

    async with untenanted_session() as session:
        actions = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'qa_sample.read' "
                    "AND object_id = :cid"
                ),
                {"cid": str(sample.call_id)},
            )
        ).scalar_one()
    assert actions == 1


def test_this_router_has_no_route_to_raw_transcript_text() -> None:
    """Hard rule 5 has ONE raw path in this codebase. A reviewer's convenience route
    would be a second, and the second one is always the one that rots — so its absence
    is asserted rather than assumed."""
    paths = [route.path for route in iter_api_routes(app) if route.path.startswith(QUEUE_PATH)]
    assert paths, "the queue must be mounted"
    assert not any("raw" in path for path in paths)


def test_the_queue_read_is_a_read_permission_and_the_verdict_is_a_mutating_one() -> None:
    """D-22: a GET must not be gated on a permission read-only impersonation refuses,
    and a mutation must be."""
    by_path = {
        (route.path, method): route_enforcement(route)[0]
        for route in iter_api_routes(app)
        if route.path.startswith(QUEUE_PATH)
        for method in route.methods
    }
    assert by_path[(QUEUE_PATH, "GET")] == {"org:read"}
    assert by_path[(f"{QUEUE_PATH}/{{sample_id}}", "GET")] == {"calls:read"}
    review = by_path[(f"{QUEUE_PATH}/{{sample_id}}/review", "POST")]
    assert review <= MUTATING_PERMISSIONS and review


async def test_a_verdict_is_recorded_once_audited_and_never_overwritten() -> None:
    tenant_id = await _tenant()
    await _drawn(tenant_id, count=20)
    async with tenant_session(tenant_id) as session:
        sample = (await list_samples(session))[0]

    token = await _make_admin()
    async with _client() as http:
        first = await http.post(
            f"{QUEUE_PATH}/{sample.id}/review",
            json={"verdict": "defect"},
            headers={"Authorization": f"Bearer {token}"},
        )
        second = await http.post(
            f"{QUEUE_PATH}/{sample.id}/review",
            json={"verdict": "clean"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert first.status_code == 200, first.text
    assert first.json()["verdict"] == "defect"
    # The second reviewer is REFUSED rather than silently overwriting the finding.
    assert second.status_code == 409, second.text

    async with untenanted_session() as session:
        recorded = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'qa_sample.reviewed' "
                    "AND object_id = :cid"
                ),
                {"cid": str(sample.call_id)},
            )
        ).scalar_one()
    assert recorded == 1

    # And it leaves the pending queue, which is what makes the list a work list.
    async with tenant_session(tenant_id) as session:
        pending = {row.id for row in await list_samples(session, pending_only=True)}
        every = {row.id for row in await list_samples(session, pending_only=False)}
    assert sample.id not in pending
    assert sample.id in every


async def test_an_unknown_verdict_is_refused() -> None:
    tenant_id = await _tenant()
    await _drawn(tenant_id, count=20)
    async with tenant_session(tenant_id) as session:
        sample = (await list_samples(session))[0]
        with pytest.raises(ProblemError):
            await record_review(
                session, sample_id=sample.id, verdict="looks_fine", admin_id=uuid.uuid4()
            )


async def test_a_verdict_survives_the_row_vanishing_under_the_re_read() -> None:
    """The re-read after a successful CAS answers 404 rather than returning nothing.

    Not reachable through `record_review` itself — the UPDATE matched the row inside this
    transaction, so the re-read sees it — which is exactly why the branch used to carry a
    coverage exclusion. An excluded branch is one nobody will ever watch fail, and this
    one decides whether an admin who just recorded a verdict gets a 404 they can act on or
    a `None` that becomes a 500 two frames up. So the re-read is driven directly, with
    `find_sample` made to answer the way only a torn transaction could.
    """
    tenant_id = await _tenant()
    await _drawn(tenant_id, count=20)
    async with tenant_session(tenant_id) as session:
        sample = (await list_samples(session))[0]
    # A REAL reviewer: `reviewed_by_admin_id` is a foreign key, so a random uuid makes the
    # CAS raise IntegrityError and the test would never reach the branch it is named for.
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', 'operator', now(), now())"
            ),
            {"id": admin_id},
        )

    calls: list[UUID] = []

    async def _vanishes(_session: Any, sample_id: UUID) -> None:
        # First call is the post-CAS re-read; there is no earlier one on the success path.
        calls.append(sample_id)
        return None

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(sampling, "find_sample", _vanishes)
        async with tenant_session(tenant_id) as session:
            with pytest.raises(ProblemError) as raised:
                await record_review(
                    session, sample_id=sample.id, verdict=QA_VERDICTS[0], admin_id=admin_id
                )
    assert calls == [sample.id], "the branch under test is the re-read, not the CAS miss"
    assert raised.value.status == 404


async def test_the_queue_row_carries_no_phone_number_or_transcript() -> None:
    """Hard rule 6 on the widest-read list in the console: accounts and calls, not people."""
    tenant_id = await _tenant()
    call_ids = await _calls(tenant_id, count=20, when=LAST_WEEK)
    for call_id in call_ids:
        await _turn(tenant_id, call_id, "my number is 9876543210", "my number is [phone ••10]")
    week = ist_week_start(LAST_WEEK)
    async with tenant_session(tenant_id) as session:
        await draw_week_sample(session, tenant_id=tenant_id, week_start=week)

    token = await _make_admin()
    async with _client() as http:
        body = (await http.get(QUEUE_PATH, headers={"Authorization": f"Bearer {token}"})).text
    assert "9876543210" not in body
    assert "phone" not in body
    assert "number is" not in body


# --- 6. Hard rule 1 -----------------------------------------------------------------


async def test_tenant_b_cannot_see_tenant_as_samples() -> None:
    tenant_a = await _tenant()
    tenant_b = await _tenant()
    await _drawn(tenant_a, count=20)

    async with tenant_session(tenant_b) as session:
        assert await list_samples(session) == []
        rows = (await session.execute(text("SELECT count(*) FROM qa_call_samples"))).scalar_one()
    assert rows == 0
    async with tenant_session(tenant_a) as session:
        rows = (await session.execute(text("SELECT count(*) FROM qa_call_samples"))).scalar_one()
    assert rows > 0


async def test_a_client_token_cannot_reach_the_admin_queue() -> None:
    """The realm keeps client tokens out, not the permission — client roles hold
    `org:read` too."""
    tenant_id = await _tenant()
    user_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO memberships (id, tenant_id, user_id, role, created_at, updated_at) "
                "VALUES (:id, :tid, :uid, 'owner', now(), now())"
            ),
            {"id": uuid.uuid4(), "tid": tenant_id, "uid": user_id},
        )
    async with _client() as http:
        response = await http.get(
            QUEUE_PATH, headers={"Authorization": f"Bearer dev:client:{user_id}"}
        )
    assert response.status_code in (401, 403)


# --- 7. Registered ------------------------------------------------------------------


async def test_the_tick_draws_for_every_tenant_and_a_rerun_adds_nothing() -> None:
    """The job's own loop, over an EXPLICIT tenant list.

    `draw_for_tenants` is split out of `draw_qa_samples` for the reason
    `retention.sweep_tenants` is: the resolution step and the drawing step are separately
    exercisable, so this test does not have to enumerate every organization in the shared
    test database to reach the behaviour it cares about.
    """
    first_tenant = await _tenant()
    second_tenant = await _tenant()
    await _calls(first_tenant, count=20, when=LAST_WEEK)
    await _calls(second_tenant, count=20, when=LAST_WEEK)
    weeks = [ist_week_start(LAST_WEEK)]

    totals = await draw_for_tenants([first_tenant, second_tenant], weeks)
    assert totals["tenants"] == 2
    assert totals["calls_in_frame"] == 40
    assert totals["samples_drawn"] == 2
    assert totals["tenants_failed"] == 0

    # The tick fires late, retries and gets replayed. Every one of those is a no-op.
    again = await draw_for_tenants([first_tenant, second_tenant], weeks)
    assert again["samples_drawn"] == 0


async def test_one_tenants_failure_does_not_cost_every_other_tenant_their_sample(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A tenant whose draw RAISES is counted and skipped.

    Forced with a monkeypatch rather than a made-up tenant id, because a nonexistent
    tenant does not fail — it enters an RLS scope with no calls and contributes nothing,
    which would make this test pass while proving nothing about the failure path. The
    behaviour under test is that one client's database error does not silently cancel
    every other client's spot-check for the week.
    """
    broken = await _tenant()
    healthy = await _tenant()
    await _calls(broken, count=20, when=LAST_WEEK)
    await _calls(healthy, count=20, when=LAST_WEEK)
    real_draw = qa_worker.draw_week_sample

    async def _explode(session, *, tenant_id, week_start):  # type: ignore[no-untyped-def]
        if tenant_id == broken:
            raise RuntimeError("this tenant's shard is on fire")
        return await real_draw(session, tenant_id=tenant_id, week_start=week_start)

    monkeypatch.setattr(qa_worker, "draw_week_sample", _explode)
    totals = await draw_for_tenants([broken, healthy], [ist_week_start(LAST_WEEK)])
    assert totals["tenants_failed"] == 1
    assert totals["samples_drawn"] == 1


def test_the_weekly_draw_is_on_a_real_worker_schedule_with_an_explicit_max_tries() -> None:
    """Verified against `arq.worker.Worker`, not against `WorkerSettings`.

    `cron()` defaults `max_tries` to 1 and `WorkerSettings.max_tries` does NOT reach a
    function carrying its own — a previous slice was bitten by exactly this. So the
    assertion is made on the schedule a real Worker builds, where the effective value is
    whatever the job will actually run with.
    """
    from arq.worker import Worker

    worker = Worker(
        functions=WorkerSettings.functions,
        cron_jobs=WorkerSettings.cron_jobs,
        redis_settings=WorkerSettings.redis_settings,
        max_tries=WorkerSettings.max_tries,
        burst=True,
        ctx={},
    )
    # arq names a cron job `cron:<function>` — the same prefix a producer would never
    # enqueue by, which is why this is read off the Worker rather than guessed.
    jobs = {job.name: job for job in worker.cron_jobs}
    assert "cron:draw_qa_samples" in jobs, "the weekly QA draw must be registered"
    job = jobs["cron:draw_qa_samples"]
    # The negative control, in the same breath: a cron that does NOT pass max_tries
    # comes back as 1 even though `WorkerSettings.max_tries` is 3. That is the trap this
    # assertion exists for, and asserting it here keeps the claim honest if arq changes.
    assert jobs["cron:dispatch_outbox"].max_tries == 1
    assert job.max_tries is not None and job.max_tries > 1, (
        "cron() defaults max_tries to 1; a sampling tick that gives up on its first "
        "failure leaves a week undrawn with every screen still green"
    )
    assert job.weekday == {0}, "weekly, on a Monday"
