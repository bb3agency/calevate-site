"""Trial periods (D-536) — the ADMIN BOUNDARY, and the arithmetic at both ends of one.

`trial_period_test.py` argues the semantics against the service functions: the gate arm,
the meter, the boundary, what is not exempt. This file covers the surface an operator
actually touches and the edges the service refuses at, because both are places where the
founder's sentence — *"any client can be given any no.of days ... and when the trail is
lifted or over or stopped by calevate the numbers should start form 0 again"* — is turned
into an HTTP contract that a console and a curl both have to obey.

What is pinned here, and why each one is its own test:

- **Opening one is double-keyed on the DAYS.** There is no spend ceiling by the founder's
  explicit choice, so the number of days is the ENTIRE bound on what the act can cost; a
  confirmation that did not carry it would let an operator who meant 14 and typed 140
  through on one keystroke.
- **`expired` is not a human outcome.** The clock's own verdict must not be sayable by a
  person, or a trial we stopped is recorded as one that ran its course — a different fact
  about the same client, and the one an operator reads when they ask why a client left.
- **The reason is required in words, not whitespace.** A client carried for free with no
  stated reason is the ticket nobody can close.
- **Ending it through the route really does zero the live counters and really does leave
  the audit row**, including the date this client's data becomes erasable. Hard rule 4 is
  not weakened to do it: `spend_state` is a derived counter and is not append-only, and the
  ledgers keep every row (asserted in `trial_period_test.py`).
- **The read publishes what the trial has cost US**, from `usage_events.unit_cost_paid`
  summed in NUMERIC (hard rule 7). "No ceiling" plus "no visibility" is how this becomes
  expensive silently, so the figure is the whole reason that route exists.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from apps.api.admin import service as admin_service
from apps.api.billing.trial_routes import router as trial_router
from apps.api.billing.trial_routes import start_trial_confirmation
from apps.api.billing.trials import (
    end_trial,
    mark_erasure_filed,
    read_trial,
    start_trial,
    trial_cost_to_us_inr,
)
from apps.api.core.errors import ProblemError, install_error_handlers
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text


def _app() -> FastAPI:
    application = FastAPI()
    install_error_handlers(application)
    application.include_router(trial_router)
    return application


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=_app()), base_url="http://api")


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


async def _tenant() -> tuple[uuid.UUID, uuid.UUID]:
    created = await admin_service.create_organization(
        name="Trial Edge Clinic",
        slug=f"trialedge-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return uuid.UUID(str(created["id"])), uuid.UUID(str(created["agent_id"]))


def _headers(token: str, confirm: str | None = None) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {token}"}
    if confirm is not None:
        headers["X-Confirm-Action"] = confirm
    return headers


async def _audit_rows(tenant_id: uuid.UUID, action: str) -> list[Any]:
    """Audit entries for one tenant (audit_log is not tenant-RLS'd), oldest first.

    `summary` is deliberately not selected: it has no column. `compliance/audit.py` hashes
    the row it stores and sends the summary to the log stream instead, so what the DB can
    prove is that the act was recorded against this object — which is the property that
    makes "a client carried for free by nobody" unreachable.
    """
    async with untenanted_session() as session:
        return (
            await session.execute(
                text(
                    "SELECT object_type, object_id, actor_type FROM audit_log "
                    "WHERE action = :a AND tenant_id = :t ORDER BY at ASC, id ASC"
                ),
                {"a": action, "t": tenant_id},
            )
        ).all()


async def _open_through_the_route(
    token: str, tenant_id: uuid.UUID, days: int = 14, **extra: Any
) -> dict[str, Any]:
    body = {"days": days, "reason": "Founder promised a fortnight on us.", **extra}
    async with _client() as http:
        posted = await http.post(
            f"/v1/admin/tenants/{tenant_id}/trial",
            headers=_headers(token, start_trial_confirmation(tenant_id, days)),
            json=body,
        )
    assert posted.status_code == 201, posted.text
    payload: dict[str, Any] = posted.json()
    return payload


# --- opening one -------------------------------------------------------------------


async def test_opening_a_trial_publishes_it_and_leaves_an_audit_row() -> None:
    """The happy path an operator takes, end to end through the real router.

    The audit row shares the trial's transaction, because a client being carried for free
    with no entry saying who agreed to it is not a reachable state.
    """
    token = await _make_admin()
    tenant_id, _ = await _tenant()

    body = await _open_through_the_route(token, tenant_id, days=14)

    assert body["status"] == "active"
    assert body["active"] is True
    assert body["days"] == 14
    assert body["days_remaining"] == 14
    assert body["ended_at"] is None and body["ended_reason"] is None
    assert body["erasure_filed_at"] is None
    assert uuid.UUID(body["tenant_id"]) == tenant_id

    rows = await _audit_rows(tenant_id, "trial.started")
    assert len(rows) == 1, "a trial with no audit row is a client carried for free by nobody"
    assert rows[0][0] == "tenant_trials"
    assert rows[0][1] == body["trial_id"]
    assert rows[0][2] == "admin"


async def test_opening_a_trial_is_double_keyed_on_the_days() -> None:
    """The days are the ONLY bound this arrangement has — the founder chose no spend
    ceiling — so a confirmation for 14 days must not open a 140-day trial."""
    token = await _make_admin()
    tenant_id, _ = await _tenant()

    async with _client() as http:
        refused = await http.post(
            f"/v1/admin/tenants/{tenant_id}/trial",
            headers=_headers(token, start_trial_confirmation(tenant_id, 14)),
            json={"days": 140, "reason": "Slipped a zero."},
        )

    assert refused.status_code == 403, refused.text
    assert "step_up_required" in refused.text
    assert f"start_trial:{tenant_id}:140" in refused.text, (
        "the refusal prints the string the operator must key, on purpose"
    )
    async with tenant_session(tenant_id) as session:
        assert await read_trial(session, tenant_id=tenant_id) is None


async def test_a_trial_may_not_be_opened_without_saying_why() -> None:
    """Whitespace is not a reason. The field is what a later reviewer reads when they ask
    why this account was on us for a month."""
    token = await _make_admin()
    tenant_id, _ = await _tenant()

    async with _client() as http:
        refused = await http.post(
            f"/v1/admin/tenants/{tenant_id}/trial",
            headers=_headers(token, start_trial_confirmation(tenant_id, 7)),
            json={"days": 7, "reason": "   "},
        )

    assert refused.status_code == 422, refused.text
    assert "why this client is being given a trial" in refused.text.lower()
    async with tenant_session(tenant_id) as session:
        assert await read_trial(session, tenant_id=tenant_id) is None


# --- ending one --------------------------------------------------------------------


async def test_ending_a_trial_restarts_the_counters_and_records_the_erasure_date() -> None:
    """The founder's own second clause, taken through the route: the numbers start from 0
    again, and the consequence — when this client's data becomes erasable — is in the
    audit row and not only on a screen.

    `spend_state` is the LIVE counter no epoch can filter, and zeroing it is exactly what
    its own month-roll does on the 1st. No ledger is touched (hard rule 4) — that property
    is asserted against `credit_ledger` in `trial_period_test.py`.
    """
    token = await _make_admin()
    tenant_id, _ = await _tenant()
    await _open_through_the_route(token, tenant_id, days=30)

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO spend_state (tenant_id, month, minutes_used, spend_used, "
                "billed_inr, capped) VALUES (:t, '2026-09', 90, 180, 450, true)"
            ),
            {"t": tenant_id},
        )

    async with _client() as http:
        ended = await http.post(
            f"/v1/admin/tenants/{tenant_id}/trial/end",
            headers=_headers(token),
            json={"outcome": "stopped", "reason": "Client went quiet."},
        )

    assert ended.status_code == 200, ended.text
    body = ended.json()
    assert body["status"] == "stopped"
    assert body["active"] is False
    assert body["days_remaining"] is None, "a trial that has ended has no days left to show"
    assert body["ended_at"] is not None
    assert body["erase_after"] is not None, "a non-converting client is scheduled for erasure"

    async with tenant_session(tenant_id) as session:
        counters = (
            await session.execute(
                text(
                    "SELECT minutes_used, spend_used, billed_inr, capped FROM spend_state "
                    "WHERE tenant_id = :t"
                ),
                {"t": tenant_id},
            )
        ).first()
    assert counters is not None
    assert tuple(counters) == (Decimal("0"), Decimal("0"), Decimal("0"), False)

    rows = await _audit_rows(tenant_id, "trial.ended")
    assert len(rows) == 1
    assert rows[0][1] == body["trial_id"]
    assert rows[0][0] == "tenant_trials"


async def test_expired_is_the_clocks_verdict_and_a_person_may_not_claim_it() -> None:
    """Accepting it here would let a trial WE stopped be recorded as one that ran its
    course. An operator who wants `expired` can let the clock run."""
    token = await _make_admin()
    tenant_id, _ = await _tenant()
    await _open_through_the_route(token, tenant_id, days=7)

    async with _client() as http:
        refused = await http.post(
            f"/v1/admin/tenants/{tenant_id}/trial/end",
            headers=_headers(token),
            json={"outcome": "expired", "reason": "It ran out, I think."},
        )

    assert refused.status_code == 422, refused.text
    assert "Outcome is one of converted, stopped." in refused.text
    async with tenant_session(tenant_id) as session:
        still = await read_trial(session, tenant_id=tenant_id)
    assert still is not None and still.status == "active"


async def test_ending_a_trial_may_not_be_done_wordlessly() -> None:
    token = await _make_admin()
    tenant_id, _ = await _tenant()
    await _open_through_the_route(token, tenant_id, days=7)

    async with _client() as http:
        refused = await http.post(
            f"/v1/admin/tenants/{tenant_id}/trial/end",
            headers=_headers(token),
            json={"outcome": "converted", "reason": " \t "},
        )

    assert refused.status_code == 422, refused.text
    assert "Say why this trial is ending." in refused.text


# --- the read ----------------------------------------------------------------------


async def test_the_read_is_null_for_a_client_who_never_had_a_trial() -> None:
    """`null`, not a 404 and not an empty object: "this client has never been on a trial"
    is a real answer a screen has to render."""
    token = await _make_admin()
    tenant_id, _ = await _tenant()

    async with _client() as http:
        read = await http.get(f"/v1/admin/tenants/{tenant_id}/trial", headers=_headers(token))

    assert read.status_code == 200, read.text
    assert read.json() is None


async def test_the_read_publishes_what_the_trial_has_cost_us_in_numeric_rupees() -> None:
    """The other half of "no spend ceiling". The figure is OUR supplier cost, summed over
    the trial's OWN window rather than a billing month, in NUMERIC (hard rule 7) — and a
    minute metered BEFORE the trial opened is not part of what the trial cost.
    """
    token = await _make_admin()
    tenant_id, agent_id = await _tenant()
    started = datetime.now(UTC) - timedelta(days=2)

    async with tenant_session(tenant_id) as session:
        trial = await start_trial(
            session, tenant_id=tenant_id, days=30, actor_user_id=None, at=started
        )
        for occurred, qty, cost in (
            (started - timedelta(days=1), "60", "0.0300"),  # before the trial opened
            (started + timedelta(hours=1), "120", "0.0300"),
            (started + timedelta(days=1), "60", "0.0500"),
        ):
            # One call per usage event: `ux_usage_events_tenant_call_unit` allows a single
            # `telephony_s` row per call, which is the meter's own idempotency.
            call_id = uuid7()
            await session.execute(
                text(
                    "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, "
                    "to_e164, status, created_at, updated_at) VALUES (:i, :t, :a, :e, "
                    "'outbound', '+919876500002', 'completed', now(), now())"
                ),
                {
                    "i": call_id,
                    "t": tenant_id,
                    "a": agent_id,
                    "e": f"exec_{uuid.uuid4().hex[:12]}",
                },
            )
            await session.execute(
                text(
                    "INSERT INTO usage_events (id, tenant_id, call_id, unit_type, qty, "
                    "unit_cost_paid, occurred_at, created_at) VALUES (:i, :t, :c, "
                    "'telephony_s', :q, :u, :o, now())"
                ),
                {
                    "i": uuid7(),
                    "t": tenant_id,
                    "c": call_id,
                    "q": Decimal(qty),
                    "u": Decimal(cost),
                    "o": occurred,
                },
            )
        summed = await trial_cost_to_us_inr(session, tenant_id=tenant_id, trial=trial)

    # 120 * 0.03 + 60 * 0.05 = 6.60. The pre-trial minute is not ours to count here.
    assert isinstance(summed, Decimal), "our supplier cost is never a float"
    assert summed == Decimal("6.6000")

    async with _client() as http:
        read = await http.get(f"/v1/admin/tenants/{tenant_id}/trial", headers=_headers(token))

    assert read.status_code == 200, read.text
    body = read.json()
    assert body["status"] == "active" and body["active"] is True
    assert Decimal(str(body["cost_to_us_inr"])) == Decimal("6.60")

    rows = await _audit_rows(tenant_id, "admin.tenant_read")
    assert len(rows) == 1, "a direct-admin read of one client's commercial state is audited"


# --- what the service refuses ------------------------------------------------------


async def test_days_remaining_rounds_up_while_it_runs_and_vanishes_once_it_is_over() -> None:
    """CEILING, not floor: a client with four hours left has "1 day", because the number is
    how many more days they may call and rounding it down tells someone with a working
    service that it has already stopped."""
    tenant_id, _ = await _tenant()
    now = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        state = await start_trial(
            session,
            tenant_id=tenant_id,
            days=7,
            actor_user_id=None,
            at=now - timedelta(days=6, hours=20),
        )
        assert state.days_remaining(at=now) == 1, "four hours left is one more day of calling"
        # Five days earlier there are 5 days 4 hours left, which is 6 days of calling.
        assert state.days_remaining(at=now - timedelta(days=5)) == 6

        ended = await end_trial(
            session, tenant_id=tenant_id, outcome="converted", reason="They bought.", at=now
        )

    assert ended.days_remaining(at=now) is None
    # An `active` row past its end date is the state between the end instant and the daily
    # sweep. It reads 0 days left, which with `is_active` False is the honest pair.
    assert state.days_remaining(at=now + timedelta(days=1)) is None


async def test_a_trial_shorter_than_a_day_or_longer_than_a_year_is_refused_by_name() -> None:
    """Zero days is a trial nobody got; past a year the word for the arrangement is a plan.
    Refused in the service and not only at the route, because a script does not go through
    the route."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        for days in (0, -3, 366):
            with pytest.raises(ProblemError) as exc:
                await start_trial(session, tenant_id=tenant_id, days=days, actor_user_id=None)
            assert exc.value.code == "invalid_trial_days"
        assert await read_trial(session, tenant_id=tenant_id) is None


async def test_an_out_of_range_erasure_grace_is_refused_by_name() -> None:
    """The grace is a data-protection promise frozen onto the row, so the bound on it is
    enforced where the row is written."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        for grace in (0, 181):
            with pytest.raises(ProblemError) as exc:
                await start_trial(
                    session,
                    tenant_id=tenant_id,
                    days=7,
                    actor_user_id=None,
                    erasure_grace_days=grace,
                )
            assert exc.value.code == "invalid_erasure_grace"
        assert await read_trial(session, tenant_id=tenant_id) is None


async def test_a_trial_cannot_end_as_something_nobody_defined() -> None:
    """The status is read by the erasure sweep and by every screen. An unknown word there
    is a row no reader has a branch for."""
    tenant_id, _ = await _tenant()
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        with pytest.raises(ProblemError) as exc:
            await end_trial(
                session, tenant_id=tenant_id, outcome="abandoned", reason="Gave up on them."
            )
        assert exc.value.code == "invalid_trial_outcome"
        still = await read_trial(session, tenant_id=tenant_id)
    assert still is not None and still.status == "active"


async def test_filing_the_erasure_is_stamped_so_the_sweep_asks_only_once() -> None:
    """This column is the whole of the sweep's idempotency. `compliance/tenant_erasure.py`
    does the erasing; nothing here erases anything."""
    tenant_id, _ = await _tenant()
    filed_at = datetime.now(UTC)
    async with tenant_session(tenant_id) as session:
        await start_trial(session, tenant_id=tenant_id, days=7, actor_user_id=None)
        ended = await end_trial(
            session, tenant_id=tenant_id, outcome="stopped", reason="No response."
        )
        assert ended.erasure_filed_at is None
        await mark_erasure_filed(session, trial_id=ended.id, at=filed_at)
        after = await read_trial(session, tenant_id=tenant_id)

    assert after is not None and after.erasure_filed_at is not None
    assert abs((after.erasure_filed_at - filed_at).total_seconds()) < 1
