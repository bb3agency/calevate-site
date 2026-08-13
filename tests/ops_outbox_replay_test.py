"""The outbox dead-letter replay, and the step-up it was missing.

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

CONCURRENCY. The replay is global, so this file cannot assert on "the queue" — only on
rows it created. Those rows are backdated thirty days (the house pattern from
`tests/reliability_audit_test.py`): oldest-first ordering then guarantees a small run
reaches THIS file's rows, and the module fixture deletes them the moment it is done so
they never sit at the head of another suite's dispatcher tick.
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.core.rbac import iter_api_routes
from apps.api.db.base import uuid7
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops.routes import OUTBOX_REPLAY_CONFIRMATION, spend_cap_confirmation
from httpx import ASGITransport, AsyncClient, Response
from sqlalchemy import text

ROUTE = "/v1/ops/outbox/replay"
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
    clerk_id = f"admin_{uuid.uuid4().hex[:12]}"
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO admin_users (id, clerk_user_id, name, role, created_at, updated_at) "
                "VALUES (:id, :cid, 'Ops', :role, now(), now())"
            ),
            {"id": admin_id, "cid": clerk_id, "role": role},
        )
    return f"dev:admin:{clerk_id}", admin_id


async def _replay(token: str, *, confirm: str | None = None) -> Response:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    async with _client() as http:
        return await http.post(ROUTE, headers=headers)


async def _dead_letter() -> UUID:
    """One dead-lettered message, backdated so an oldest-first run reaches it."""
    message_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO outbox_messages (id, queue, job, payload, status, attempt_count, "
                "last_error, created_at, updated_at) VALUES (:id, 'default', "
                "'deliver_outbound_webhook', CAST(:p AS jsonb), 'failed', 5, "
                "'exhausted after 3', now() - interval '30 days', now())"
            ),
            {"id": message_id, "p": json.dumps({"marker": f"replay-{RUN}"})},
        )
    return message_id


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
    runbook telling operators to send a header the API refuses."""
    assert OUTBOX_REPLAY_CONFIRMATION == "replay_dead_letters"


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
