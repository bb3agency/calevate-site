"""The outbox dead-letter queue: what it publishes, and what a replay does.

## Part one — the confirmation that could not be sized

The step-up landed first and left a different defect behind: an operator was asked to
confirm a redelivery of unknown SIZE, unknown mix and unknown AGE, because no endpoint
published a dead-letter count. `GET /v1/ops/platform` now carries `outbox_dead_letters`
— depth, per-`job` breakdown, oldest — from `reliability.service.read_dead_letter_queue`,
which is also where the `outbox_dlq_depth` metric comes from, so the number an operator
reads before confirming and the number the alert fires on cannot disagree.

What is asserted about it: the depth counts `failed` and nothing else; the breakdown sums
to the total; the read is gated exactly like the rest of the router; and nothing derived
from a message PAYLOAD reaches the wire (hard rule 6 — `outbox_messages.payload` is JSONB
holding lead fields and phone numbers).

## Part two — the replay, and the scope it now carries

`POST /v1/ops/outbox/replay` was the only WRITE on the ops router reachable by a single
unconfirmed POST, and it is the one whose blast radius reaches furthest OUTWARD:

- **It is cross-tenant by construction.** `reliability.service.replay_dead_letters`
  selects on `status = 'failed'` with no tenant predicate — `outbox_messages` is an infra
  table and has no `tenant_id` column to have one with — so one request reaches every
  client's parked messages at once.
- **The flip is not the effect; the redelivery is.** Every row it moves back to `pending`
  gets a fresh attempt budget, and the next dispatch tick re-sends it: an HMAC-signed
  webhook into a client's own CRM, a Google Sheets append, a notification email. A
  message can dead-letter AFTER its side effect landed, so the outcome is other people's
  customer data arriving a second time in other people's systems — not undoable from
  here, and visible to the client rather than to us.

Halting all outbound calling is loud, reversible and ours; this is quiet, irreversible
and theirs. BACKEND-PATTERNS §7 asks for a confirmation bound to the specific action on
exactly this shape of control, and the console had been collecting the typed word for it
while sending no header, because the route accepted none.

What is asserted below, in the order the properties matter:

1. **The refusal happens BEFORE any row moves.** A 403 that has already replayed the
   queue is not a guard, and it is the failure mode a step-up added at the wrong end of
   the handler would have.
2. **The confirmation is bound to THIS action.** Another ops route's header — the big red
   switch's, a spend-cap recompute's — does not authorise a cross-tenant redelivery.
3. **The literal is a published ops procedure**, quoted by `runbooks/webhook-delivery-
   failures.md` and mirrored by the console, so it is pinned here rather than left to be
   reformatted quietly.
4. The confirmed path still works, is still audited, and still needs `ops:manage`.
5. **The confirmation agrees with the SCOPE**, in both directions. The replay now takes an
   optional `job`, so `replay_dead_letters` no longer describes every request it could be
   sent with: a header naming one job must not authorise a replay of everything, and a
   header naming everything must not be accepted for a request that replays one job.

CONCURRENCY. The replay is global, so this file cannot assert on "the queue" — only on
rows it created. Those rows are backdated thirty days (the house pattern from
`tests/reliability_audit_test.py`): oldest-first ordering then guarantees a small run
reaches THIS file's rows, and the module fixture deletes them the moment it is done so
they never sit at the head of another suite's dispatcher tick.

The depth assertions need the same discipline one step further: `outbox_dead_letters` is
a global aggregate, so a test that pinned a TOTAL would be asserting what every other
suite on this database happens to have left behind. Every seeded row therefore carries a
job name unique to this run, and the assertions are on THAT job's entry in the breakdown
plus the invariants that hold whatever else is in the queue (the parts sum to the total;
the queue's oldest is no later than ours). Unique job names also make a scoped replay
provably scoped: nothing another suite wrote can be in the scope under test.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.rbac import iter_api_routes
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.routes import (
    OUTBOX_REPLAY_CONFIRMATION,
    outbox_replay_confirmation,
    spend_cap_confirmation,
)
from apps.api.reliability.service import read_dead_letter_queue, record_outbox_metrics
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text

ROUTE = "/v1/ops/outbox/replay"
PLATFORM_ROUTE = "/v1/ops/platform"
# Lowercase hex only: this is interpolated into job names, which the route bounds to
# `^[a-z][a-z0-9_]*$`.
RUN = uuid.uuid4().hex[:10]


@pytest.fixture(scope="module", autouse=True)
async def _clean_up_after_ourselves() -> Any:
    """Backdated rows must not outlive this module — see the file docstring."""
    yield
    async with untenanted_session() as session:
        await session.execute(
            text("DELETE FROM outbox_messages WHERE payload->>'marker' LIKE :m"),
            {"m": f"%{RUN}"},
        )


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _make_admin(role: str = "superadmin") -> tuple[str, UUID]:
    """A real admin row plus the dev-token realm credential (`route_shape_test`'s idiom).

    The id comes back too: the replay's audit row names no tenant and no object id, so
    the actor is the only thing that identifies THIS run's entry in a shared ledger.
    """
    admin_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, name, role, created_at, updated_at) "
                "VALUES (:id, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "role": role},
        )
    return f"dev:admin:{admin_id}", admin_id


async def _replay(token: str, *, confirm: str | None = None, job: str | None = None) -> Response:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    async with _client() as http:
        return await http.post(ROUTE, headers=headers, params={} if job is None else {"job": job})


async def _read_platform(token: str) -> Response:
    async with _client() as http:
        return await http.get(PLATFORM_ROUTE, headers={"Authorization": f"Bearer {token}"})


async def _message(
    *,
    job: str = "deliver_outbound_webhook",
    status: str = "failed",
    age_days: int = 30,
    payload: dict[str, Any] | None = None,
) -> UUID:
    """One outbox row, backdated so an oldest-first run reaches it.

    ONE insert for every seeded row in this file, rather than one per status: the tests
    that assert "only `failed` counts" would otherwise be comparing rows built by two
    different literals, and a divergence between them would look like the behaviour under
    test. `age_days` is what makes the oldest-first ordering deterministic here — see the
    module docstring on why nothing in this file may assume it owns the queue.
    """
    message_id = uuid7()
    body = {"marker": f"replay-{RUN}", **(payload or {})}
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                "last_error, created_at, updated_at) VALUES (:id, 'default', :job, "
                "CAST(:p AS jsonb), :status, 5, 'exhausted after 3', "
                "now() - make_interval(days => :age), now())"
            ),
            {
                "id": message_id,
                "job": job,
                "p": json.dumps(body),
                "status": status,
                "age": age_days,
            },
        )
    return message_id


async def _dead_letter() -> UUID:
    """One dead-lettered `deliver_outbound_webhook`, the shape the runbook's §3 is about."""
    return await _message()


# The run marker with its digits mapped onto letters. Job names are logged through
# `redact_mapping`, whose `_PHONE_RE` masks any run of nine or more digits and whose
# `_HEX_ID_RE` holds hex runs — so a hex marker would make the audit assertion below fail
# on roughly one run in a hundred, for a reason that has nothing to do with the code.
JOB_RUN = "".join(c if c.isalpha() else chr(ord("g") + int(c)) for c in RUN)


def _job_name(suffix: str) -> str:
    """A job name no other suite (and no other test in this one) can have written.

    Every depth and scope assertion below is on ONE job's entry, so uniqueness is what
    makes a global aggregate assertable at all — and it must satisfy the route's own
    `^[a-z][a-z0-9_]*$` bound, because a scoped replay of it has to be a legal request.
    """
    return f"probe_{JOB_RUN}_{suffix}"


def _entry(body: dict[str, Any], job: str) -> dict[str, Any] | None:
    for entry in body["outbox_dead_letters"]["by_job"]:
        if entry["job"] == job:
            return entry
    return None


async def _status(message_id: UUID) -> tuple[str, int]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT status, attempt_count FROM outbox_messages WHERE id = :id"),
                {"id": message_id},
            )
        ).first()
    assert row is not None, "the seeded message vanished"
    return str(row[0]), int(row[1])


# ============================================================================
# 1. The refusal, and the fact that it happens before anything moves
# ============================================================================


async def test_the_replay_refuses_without_the_step_up_header() -> None:
    token, _ = await _make_admin()

    response = await _replay(token)

    assert response.status_code == 403, response.text
    problem = response.json()
    assert problem["kind"] == "permission"
    assert problem["type"].rsplit("/", 1)[-1] == "step_up_required"
    assert OUTBOX_REPLAY_CONFIRMATION in problem["remediation"], (
        "the remediation must name the exact header to send — an operator reading it "
        "mid-incident should not have to guess the string"
    )


async def test_a_refused_replay_moves_no_message() -> None:
    """THE property, not a corollary of it.

    A step-up checked after the work is a receipt, not a guard: the messages are already
    on their way back out to clients' systems by the time the 403 is rendered. So the
    assertion is on the ROW, not on the status code.
    """
    message_id = await _dead_letter()
    token, _ = await _make_admin()

    response = await _replay(token)

    assert response.status_code == 403, response.text
    assert await _status(message_id) == ("failed", 5), (
        "a refused step-up replayed the dead letter anyway — the guard is in the wrong "
        "place, and every message it moved is being delivered a second time"
    )


@pytest.mark.parametrize(
    "borrowed",
    [
        "halt_outbound",
        "release_outbound",
        "set_load_shed:maintenance",
        "record_tm_registration",
        # The one an operator most plausibly has in their shell history from the same
        # incident: `runbooks/calls-stopped.md` §2's recompute for the client who
        # complained about the missing webhook.
        spend_cap_confirmation(UUID("0192f0aa-7777-7000-8000-0000000000c1")),
        # The retired blanket string. It authorised the big red switch once (D-45); it
        # must never quietly acquire a second meaning here.
        "set_platform_state",
        # Near-misses of this route's own string.
        "replay_dead_letter",
        "REPLAY_DEAD_LETTERS",
        "replay_dead_letters:all",
    ],
)
async def test_another_actions_confirmation_does_not_authorise_the_replay(borrowed: str) -> None:
    """§7's actual requirement: bound to the SPECIFIC action.

    Every string here is one an operator could have on their clipboard from a real
    procedure on this same router. None of them is consent to redeliver every client's
    parked messages.
    """
    message_id = await _dead_letter()
    token, _ = await _make_admin()

    response = await _replay(token, confirm=borrowed)

    assert response.status_code == 403, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "step_up_required"
    assert (await _status(message_id))[0] == "failed"


# ============================================================================
# 2. The confirmed path still does the work, and is still audited
# ============================================================================


async def test_the_confirmed_replay_moves_the_dead_letter_back_to_pending() -> None:
    """The other direction of the guard, so a future change cannot satisfy the refusal
    tests by refusing everything."""
    message_id = await _dead_letter()
    token, _ = await _make_admin()

    response = await _replay(token, confirm=OUTBOX_REPLAY_CONFIRMATION)

    assert response.status_code == 200, response.text
    assert response.json()["replayed"] >= 1
    # Attempts reset: the message gets a fresh budget, which is what makes the replay a
    # replay rather than a status edit.
    assert await _status(message_id) == ("pending", 0)


async def test_the_confirmed_replay_writes_one_audit_row_naming_who_asked() -> None:
    """BACKEND-PATTERNS §4: a message delivered twice needs a record of who asked for the
    second attempt. The row carries no tenant — the action is cross-tenant — so the ACTOR
    is what identifies it, and that is what is asserted."""
    await _dead_letter()
    token, admin_id = await _make_admin()

    response = await _replay(token, confirm=OUTBOX_REPLAY_CONFIRMATION)
    assert response.status_code == 200, response.text

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action, object_type, actor_type FROM audit_log "
                    "WHERE actor_id = :aid ORDER BY at DESC"
                ),
                {"aid": admin_id},
            )
        ).all()

    assert [row[0] for row in rows] == ["ops.outbox_replay"], (
        f"expected exactly one audit row for this operator, got {[row[0] for row in rows]}"
    )
    assert rows[0][1] == "outbox_messages"
    assert rows[0][2] == "admin"


async def test_a_refused_replay_writes_no_audit_row() -> None:
    """An audit row for a replay that did not happen would put a redelivery nobody made
    into the ledger that hard rule 4 forbids correcting."""
    token, admin_id = await _make_admin()

    assert (await _replay(token)).status_code == 403

    async with untenanted_session() as session:
        count = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE actor_id = :aid"), {"aid": admin_id}
            )
        ).scalar()
    assert count == 0, "a refused step-up recorded an action nobody performed"


async def test_an_operator_without_ops_manage_cannot_replay() -> None:
    """`ops:manage` is superadmin-only (core/rbac.py). The permission is checked in the
    dependency, so it refuses before the confirmation is even looked at — a correct
    header must not become a way past the role."""
    message_id = await _dead_letter()
    token, _ = await _make_admin(role="operator")

    response = await _replay(token, confirm=OUTBOX_REPLAY_CONFIRMATION)

    assert response.status_code == 403, response.text
    assert (await _status(message_id))[0] == "failed"


# ============================================================================
# 3. The literal, and the surface
# ============================================================================


def test_the_confirmation_literal_is_the_published_ops_procedure() -> None:
    """`runbooks/webhook-delivery-failures.md` prints this string for the curl fallback
    and `lib/api/admin.ts` mirrors it for the console. Pinned here so changing the shape
    has to be a deliberate edit that fails a test, rather than a reformat that leaves the
    runbook telling operators to send a header the API refuses.

    The unscoped run keeps the bare literal for exactly that reason: the runbook's curl
    sends no `job`, so it must go on working unchanged now that a scope exists.
    """
    assert OUTBOX_REPLAY_CONFIRMATION == "replay_dead_letters"
    assert outbox_replay_confirmation(None) == "replay_dead_letters"
    assert outbox_replay_confirmation("deliver_outbound_webhook") == (
        "replay_dead_letters:deliver_outbound_webhook"
    )


def test_the_route_is_mounted_and_takes_the_confirmation_header() -> None:
    """A guard nobody wired is not a guard. The header parameter is asserted on the
    route's own dependant, so deleting it fails here even if the handler body still
    compiles."""
    routes = {route.path: route for route in iter_api_routes(app)}
    assert ROUTE in routes, f"{ROUTE} is not mounted"
    assert "POST" in (routes[ROUTE].methods or set())
    headers = {param.name for param in routes[ROUTE].dependant.header_params}
    assert "x_confirm_action" in headers, (
        "the replay route stopped declaring X-Confirm-Action — the console would go on "
        "sending a header nothing reads"
    )
    query = {param.name for param in routes[ROUTE].dependant.query_params}
    assert "job" in query, (
        "the scope stopped being a query parameter — the console would send `?job=` to a "
        "route that ignores it and replay every job under a header that says otherwise"
    )


# ============================================================================
# 4. The depth the confirmation is sized by
# ============================================================================


async def test_the_depth_counts_dead_letters_and_nothing_else() -> None:
    """`pending` is a message waiting its turn and `published` is one already handed to
    ARQ. Counting either would tell an operator they are about to re-send messages that
    are not in the DLQ at all — and would inflate the number they are confirming."""
    job = _job_name("mixed")
    for _ in range(3):
        await _message(job=job, status="failed")
    await _message(job=job, status="pending")
    await _message(job=job, status="published")
    token, _ = await _make_admin()

    response = await _read_platform(token)

    assert response.status_code == 200, response.text
    entry = _entry(response.json(), job)
    assert entry is not None, "the seeded job is missing from the breakdown"
    assert entry["depth"] == 3, (
        "the depth counted rows that are not dead letters — an operator would confirm a "
        f"redelivery larger than the queue: {entry}"
    )


async def test_the_breakdown_sums_to_the_total() -> None:
    """A total that does not equal its parts is worse than either alone: an operator
    reading `142` beside jobs adding to `130` cannot tell which number to believe.

    Held BY CONSTRUCTION — one grouped aggregate, so no dispatcher tick can land between
    the total and the parts — and asserted anyway, because that construction is exactly
    what a well-meaning refactor into two queries would undo.
    """
    first, second = _job_name("sum_a"), _job_name("sum_b")
    for _ in range(2):
        await _message(job=first)
    await _message(job=second)
    token, _ = await _make_admin()

    body = (await _read_platform(token)).json()["outbox_dead_letters"]

    assert sum(entry["depth"] for entry in body["by_job"]) == body["depth"]
    assert _entry({"outbox_dead_letters": body}, first) is not None
    assert {entry["job"] for entry in body["by_job"]} >= {first, second}


async def test_the_depth_names_the_age_of_the_oldest_dead_letter() -> None:
    """Age is what separates a retry from an intrusion: re-sending a ten-minute-old
    webhook is a retry, and re-sending a nine-day-old lead is a client's CRM receiving
    something they have already worked and closed."""
    job = _job_name("aged")
    await _message(job=job, age_days=9)
    await _message(job=job, age_days=1)
    token, _ = await _make_admin()

    body = (await _read_platform(token)).json()["outbox_dead_letters"]
    entry = _entry({"outbox_dead_letters": body}, job)

    assert entry is not None
    oldest = datetime.fromisoformat(entry["oldest_at"])
    age = datetime.now(UTC) - oldest
    assert timedelta(days=8) < age < timedelta(days=10), (
        f"the per-job oldest is not the oldest of that job's rows: {entry['oldest_at']}"
    )
    # The queue's own oldest can only be older than any one job's — it is the min over
    # all of them, including whatever else this database holds.
    assert datetime.fromisoformat(body["oldest_at"]) <= oldest


async def test_a_job_with_no_dead_letters_is_absent_rather_than_a_zero_row() -> None:
    """The breakdown is what the queue HOLDS, not a roster of every job that exists.

    A zero row would be a job an operator could select and replay to no effect, and it
    would arrive from a definition of "the jobs" that this module does not have and must
    not invent (ARQ's registry lives in `apps/workers`, which the API may not import).
    The pairing below is the same rule one level up: a depth of 0 has no oldest, so
    `oldest_at` is null rather than a sentinel instant a console would have to decode.
    """
    await _message(job=_job_name("present"))
    token, _ = await _make_admin()

    body = (await _read_platform(token)).json()["outbox_dead_letters"]

    assert _entry({"outbox_dead_letters": body}, _job_name("never_enqueued")) is None
    assert (body["depth"] == 0) == (body["oldest_at"] is None)


async def test_the_metric_and_the_console_read_one_definition() -> None:
    """The number the alert fires on and the number an operator confirms against are the
    same number.

    `record_outbox_metrics` used to run its own `count(*)`. Two definitions of "how deep
    is the DLQ" are correct on the day they are written and disagree the first time
    either grows a predicate — and the disagreement is invisible, because one of them is
    only ever seen in a metrics dashboard and the other only ever on a console.
    """
    await _message(job=_job_name("metric"))
    recorded: list[int] = []

    import apps.api.reliability.service as reliability

    original = reliability.record_outbox_dlq_depth
    reliability.record_outbox_dlq_depth = recorded.append  # type: ignore[assignment]
    try:
        async with untenanted_session() as session:
            await record_outbox_metrics(session)
            expected = (await read_dead_letter_queue(session)).depth
    finally:
        reliability.record_outbox_dlq_depth = original  # type: ignore[assignment]

    assert recorded == [expected], (
        "the DLQ-depth metric and the ops read disagree about the depth of one queue"
    )


async def test_the_depth_publishes_counts_and_job_names_but_never_a_payload() -> None:
    """Hard rule 6, at the one place this slice could have broken it.

    `outbox_messages.payload` is JSONB and a `deliver_outbound_webhook` row's payload is a
    lead envelope: phone number, name, extraction fields. A breakdown that grew a "recent
    errors" or "sample payload" convenience would put all of it on an admin screen and in
    the API's response log. The aggregate selects `job`, `count(*)` and `min(created_at)`
    and there is nothing else it is allowed to select.
    """
    phone = "+919876500042"
    await _message(
        job=_job_name("pii"),
        payload={"phone": phone, "name": "Rekha", "transcript": "she asked about the 2BHK"},
    )
    token, _ = await _make_admin()

    body = (await _read_platform(token)).text

    assert phone not in body
    assert "Rekha" not in body
    assert "2BHK" not in body


async def test_the_platform_read_still_needs_ops_manage() -> None:
    """The depth rides the platform read, so it inherits that route's gate rather than
    acquiring one of its own — `ops:manage`, superadmin only (core/rbac.py)."""
    token, _ = await _make_admin(role="operator")

    assert (await _read_platform(token)).status_code == 403


# ============================================================================
# 5. The scope, and the confirmation that has to agree with it
# ============================================================================


async def test_a_scoped_replay_moves_only_its_own_job() -> None:
    """The bound the queue's shape allows. Per-TENANT is impossible without a migration —
    `outbox_messages` has no `tenant_id` and the ids live unindexed inside the JSONB — so
    `job` is the only scope available, and it is the one the runbook's own diagnosis step
    already groups by."""
    wanted, spared = _job_name("scope_hit"), _job_name("scope_miss")
    replayed = await _message(job=wanted)
    untouched = await _message(job=spared)
    token, _ = await _make_admin()

    response = await _replay(token, job=wanted, confirm=outbox_replay_confirmation(wanted))

    assert response.status_code == 200, response.text
    assert response.json() == {"replayed": 1, "job": wanted}
    assert await _status(replayed) == ("pending", 0)
    assert (await _status(untouched))[0] == "failed", (
        "a scoped replay moved a message outside its scope — the confirmation named one "
        "job and the request re-sent another"
    )


async def test_the_unscoped_confirmation_does_not_authorise_a_scoped_replay() -> None:
    """A header that says "replay everything" on a request that replays one job describes
    an action other than the one being performed. It is refused in that direction too, not
    only in the dangerous one, because a confirmation an operator can be sloppy about in
    either direction is a habit rather than a control."""
    job = _job_name("hdr_broad")
    message_id = await _message(job=job)
    token, _ = await _make_admin()

    response = await _replay(token, job=job, confirm=OUTBOX_REPLAY_CONFIRMATION)

    assert response.status_code == 403, response.text
    assert response.json()["type"].rsplit("/", 1)[-1] == "step_up_required"
    assert (await _status(message_id))[0] == "failed"


async def test_a_scoped_confirmation_does_not_authorise_the_unscoped_replay() -> None:
    """THE dangerous direction: a header captured for one job must never authorise a
    redelivery of every job, for every tenant, at once."""
    job = _job_name("hdr_narrow")
    message_id = await _message(job=job)
    token, _ = await _make_admin()

    response = await _replay(token, confirm=outbox_replay_confirmation(job))

    assert response.status_code == 403, response.text
    assert (await _status(message_id))[0] == "failed", (
        "a confirmation naming ONE job replayed the whole queue — every client's parked "
        "messages are on their way out again"
    )


async def test_a_malformed_scope_is_refused_rather_than_replaying_everything() -> None:
    """The failure mode a permissive parameter would have.

    An unparsable `job` must not degrade to "no scope" — that is the one bug where a
    typo in a bounded request becomes the unbounded one, with a header the operator
    believes named a single job. FastAPI validates the parameter before the handler runs,
    so the refusal lands before the step-up and long before any row moves.
    """
    message_id = await _message(job=_job_name("malformed"))
    token, _ = await _make_admin()

    response = await _replay(
        token, job="Deliver Outbound Webhook", confirm=OUTBOX_REPLAY_CONFIRMATION
    )

    assert response.status_code == 422, response.text
    assert response.json()["kind"] == "validation"
    assert (await _status(message_id))[0] == "failed"


async def test_the_scoped_replay_records_which_queue_it_emptied(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ "Who replayed 100 messages" and "which 100" are different questions, and the record
    could only answer the first.

    Asserted on the LOG STREAM rather than on a column, because `audit_log` has none:
    `compliance/audit.py` hashes the row into the chain and sends the sanitised summary to
    the log keyed by `entry_id` (BACKEND-PATTERNS §7). So the row proves who and when, and
    this proves the scope travelled with it — `audit_log` is INSERT-only (hard rule 4), so
    a scope left out at write time is not recoverable by a later correction.
    """
    job = _job_name("audited")
    await _message(job=job)
    token, admin_id = await _make_admin()

    with caplog.at_level(logging.INFO, logger="apps.api.compliance.audit"):
        response = await _replay(token, job=job, confirm=outbox_replay_confirmation(job))
    assert response.status_code == 200, response.text

    async with untenanted_session() as session:
        actions = (
            (
                await session.execute(
                    text("SELECT action FROM audit_log WHERE actor_id = :aid"), {"aid": admin_id}
                )
            )
            .scalars()
            .all()
        )
    assert list(actions) == ["ops.outbox_replay"]

    summaries = [record for record in caplog.records if getattr(record, "job", None) == job]
    assert summaries, (
        "the replay's audit summary did not name the job it replayed — the ledger records "
        f"a redelivery of unknown scope. Records seen: {[r.getMessage() for r in caplog.records]}"
    )
    assert summaries[0].replayed == 1
