"""What maintenance looks like from OUTSIDE: the refusal, the door, and the campaigns.

`maintenance_drain_test.py` covers the state machine. This covers what everybody else
sees — the client whose request is refused, the client whose banner is polled, the
operator whose console drives it, and the campaign that has to come back exactly where it
stopped.

FOUR PROPERTIES, and each is a promise made somewhere a user can read it:

1. **The refusal is a 503 that says what is happening and when it ends**, with its own
   `code` so the console can tell it from a load shed, and a `Retry-After` computed from
   the window rather than a constant. RFC 9110 §15.6.4 names scheduled maintenance as one
   of the two conditions 503 exists for; §10.2.3 is `Retry-After`.
2. **A drain stops new work without shutting the portal.** This is the two-state model
   from the outside: `accepting_new_work` goes false at `draining`, the dial gate refuses
   with its own rule name, and nothing is shed.
3. **Operators are not locked out.** `/v1/ops` and `/v1/admin` survive `maintenance`,
   which is what makes the window endable.
4. **A campaign paused by a window resumes where it was**, and a campaign paused by
   somebody else does not resume at all.

Refusals and pure functions dominate deliberately: almost nothing here moves global state,
so this file runs beside every other suite (`platform_halt_test`'s discipline).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from apps.api.campaigns.service import (
    pause_campaigns_for_maintenance,
    resume_campaigns_after_maintenance,
)
from apps.api.compliance.service import MAINTENANCE_DRAIN_RULE, PERSON_LEVEL_REFUSALS
from apps.api.core.loadshed import (
    ALWAYS_ALLOWED_PATHS,
    ALWAYS_ALLOWED_PREFIXES,
    PlatformStatus,
    is_shed,
)
from apps.api.core.middleware import (
    _RETRY_AFTER_CEILING_S,
    _RETRY_AFTER_FLOOR_S,
    _retry_after_s,
    _shed_problem,
)
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.main import app
from apps.api.ops.maintenance_routes import maintenance_confirmation
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin

pytestmark = pytest.mark.asyncio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


def _active(ends_in: timedelta = timedelta(hours=1)) -> PlatformStatus:
    return PlatformStatus(
        mode="maintenance",
        outbound_halted=False,
        maintenance="active",
        maintenance_ends_at=datetime.now(UTC) + ends_in,
        maintenance_reason="Upgrading the telephony stack. Nothing is deleted.",
    )


# ---------------------------------------------------------------- 1. the refusal


async def test_the_maintenance_refusal_is_not_the_load_shed_refusal() -> None:
    """A shed is us failing to keep up; a window is us having told them. They share a
    status code and mean opposite things, and the console switches on `code`.

    Before this split, a client who had read the banner, planned around the window and
    come back at the stated time was told "we are managing a spike in load" with a
    `Retry-After` of thirty seconds that was wrong by hours.
    """
    maintenance = _shed_problem(_active())
    assert maintenance.status == 503
    assert maintenance.code == "platform_maintenance"
    # The operator's own sentence, verbatim — this is the whole point of carrying the
    # reason on the hot path.
    assert maintenance.detail == "Upgrading the telephony stack. Nothing is deleted."

    shed = _shed_problem(PlatformStatus(mode="emergency", outbound_halted=False))
    assert shed.status == 503
    assert shed.code == "service_load_shed"
    assert shed.headers["Retry-After"] == str(_RETRY_AFTER_FLOOR_S)


async def test_retry_after_is_computed_from_the_window_and_clamped() -> None:
    """RFC 9110 §10.2.3's delay-seconds form, bounded at both ends.

    The FLOOR stops a client being invited back three seconds before the door opens — the
    request would fail and a browser honouring the header would hammer it. The CEILING
    stops a long window turning into a client who never comes back: the header is advisory,
    a window can end early, and an hour is longer than any window we intend to run.
    """
    assert _retry_after_s(None) == _RETRY_AFTER_FLOOR_S, "an unknown end must not guess long"
    soon = datetime.now(UTC) + timedelta(seconds=3)
    assert _retry_after_s(soon) == _RETRY_AFTER_FLOOR_S
    later = datetime.now(UTC) + timedelta(minutes=20)
    assert 1100 < _retry_after_s(later) <= 1200
    far = datetime.now(UTC) + timedelta(days=1)
    assert _retry_after_s(far) == _RETRY_AFTER_CEILING_S


async def test_a_manually_shed_maintenance_mode_is_still_called_maintenance() -> None:
    """THE BLUNT INSTRUMENT THAT PREDATES THE WINDOW. An operator can set
    `load_shed_mode = 'maintenance'` by hand from the ops switchboard, with no window and
    no reason on file. That is still "we are deliberately shut", and telling those clients
    we are managing a spike in load is the same wrong sentence — so it gets the maintenance
    refusal with the fallback wording."""
    manual = PlatformStatus(mode="maintenance", outbound_halted=False)
    assert manual.maintenance == "none"
    problem = _shed_problem(manual)
    assert problem.code == "platform_maintenance"
    assert "planned maintenance" in problem.detail


async def test_a_maintenance_refusal_with_no_reason_still_says_something_useful() -> None:
    """The reason is NOT NULL on the row and required at the boundary, so this is only
    reachable through a cache entry an older process wrote. The fallback still tells a
    client the two things that stop them ringing us: it is planned, and nothing is lost."""
    problem = _shed_problem(
        PlatformStatus(
            mode="maintenance",
            outbound_halted=False,
            maintenance="active",
            maintenance_ends_at=None,
            maintenance_reason=None,
        )
    )
    assert "planned maintenance" in problem.detail
    assert "untouched" in problem.detail or "will be here" in problem.detail


# ---------------------------------------------------------------- 2. draining ≠ active


async def test_draining_stops_new_work_without_shedding_anything() -> None:
    """THE TWO-STATE MODEL, FROM OUTSIDE. During a drain the portal is open — a client can
    read their leads and finish what they were doing — and the platform starts nothing new.

    If `accepting_new_work` read the load-shed mode instead, the platform would keep
    dialling for the whole drain, and every new call would restart the clock the drain is
    waiting on. A drain like that never finishes.
    """
    draining = PlatformStatus(
        mode="normal",
        outbound_halted=False,
        maintenance="draining",
        maintenance_ends_at=datetime.now(UTC) + timedelta(hours=1),
        maintenance_reason="Upgrading the telephony stack.",
    )
    assert draining.accepting_new_work is False
    assert is_shed(draining, path="/v1/leads", method="GET") is False
    assert is_shed(draining, path="/v1/leads", method="POST") is False

    assert _active().accepting_new_work is False
    assert is_shed(_active(), path="/v1/leads", method="GET") is True

    normal = PlatformStatus(mode="normal", outbound_halted=False)
    assert normal.accepting_new_work is True


async def test_the_drain_refusal_is_not_person_level() -> None:
    """A contact refused during a drain must go back on the retry ladder, not be settled.

    `PERSON_LEVEL_REFUSALS` is what the batch dialler consults to decide whether a refused
    contact is DONE. A maintenance refusal is a fact about the clock — it becomes false by
    waiting — so a campaign stopped by a window resumes through the same contacts it was
    working. Membership here would silently mean every contact refused during the drain was
    terminally finished and the campaign completed having never rung them.
    """
    assert MAINTENANCE_DRAIN_RULE not in PERSON_LEVEL_REFUSALS


# ---------------------------------------------------------------- 3. the operator's door


async def test_the_operator_surface_survives_an_active_window() -> None:
    """The window shuts clients out and must never shut the operator out — this surface is
    the one that ENDS the outage. Asserted against the same status a client is refused on,
    so the two answers provably come from one decision."""
    status = _active()
    for path, method in (
        ("/v1/ops/maintenance", "GET"),
        ("/v1/ops/maintenance/x/end", "POST"),
        ("/v1/admin/tenants", "GET"),
        ("/healthz/live", "GET"),
        ("/hooks/v1/engine/bolna", "POST"),
    ):
        assert not is_shed(status, path=path, method=method), f"{method} {path} was shed"
    # The maintenance routes are covered by an EXISTING prefix rather than a new
    # exemption — that is why they were mounted under `/v1/ops`.
    assert "/v1/ops" in ALWAYS_ALLOWED_PREFIXES
    # And an operator with no live session can still sign in to reach them.
    assert "/v1/auth/admin/login" in ALWAYS_ALLOWED_PATHS


async def test_the_client_banner_route_is_shed_like_everything_else() -> None:
    """DELIBERATELY NOT EXEMPT. During an ACTIVE window `/v1/maintenance` answers the same
    503 as every other client route — carrying the reason, the code and the `Retry-After` —
    and the console renders the lockout page from that refusal.

    Exempting it would be a second way to learn one fact, and the 503 is the one that
    reaches every screen rather than the one screen that thought to ask.
    """
    assert is_shed(_active(), path="/v1/maintenance", method="GET") is True
    # ...and it is open in the states where there is no 503 to carry the news.
    draining = PlatformStatus(mode="normal", outbound_halted=False, maintenance="draining")
    assert is_shed(draining, path="/v1/maintenance", method="GET") is False


async def test_the_confirmations_are_bound_to_the_action_and_the_window() -> None:
    """Pinned as literals because `runbooks/maintenance-window.md` prints them, and bound
    to the target for the reason the spend-cap confirmation is: an operator who confirmed
    "end the Tuesday window" must not thereby end the one that replaced it."""
    window_id = uuid.UUID("0199a0b0-0000-7000-8000-0000000000ff")
    assert maintenance_confirmation("schedule_maintenance") == "schedule_maintenance"
    assert maintenance_confirmation("end_maintenance", window_id) == f"end_maintenance:{window_id}"
    assert (
        maintenance_confirmation("cancel_maintenance", window_id)
        == f"cancel_maintenance:{window_id}"
    )
    assert (
        maintenance_confirmation("amend_maintenance", window_id) == f"amend_maintenance:{window_id}"
    )
    # No two verbs share a string, which is what stops a confirmation captured for the
    # smallest action authorising the largest.
    strings = {
        maintenance_confirmation(action, window_id)
        for action in ("amend_maintenance", "cancel_maintenance", "end_maintenance")
    }
    assert len(strings) == 3


async def test_a_stale_or_wrong_confirmation_authorises_nothing() -> None:
    """Refusals only — nothing here schedules anything, so it runs beside every suite."""
    token = await _make_admin()
    auth = {"Authorization": f"Bearer {token}"}
    body = {
        "starts_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "ends_at": (datetime.now(UTC) + timedelta(days=1, hours=1)).isoformat(),
        "reason": "A window nobody confirmed, which must not be created.",
    }
    async with _client() as http:
        missing = await http.post("/v1/ops/maintenance", headers=auth, json=body)
        borrowed = await http.post(
            "/v1/ops/maintenance",
            headers={**auth, "X-Confirm-Action": "set_load_shed:maintenance"},
            json=body,
        )
    assert missing.status_code == 403, missing.text
    assert borrowed.status_code == 403, borrowed.text
    assert "schedule_maintenance" in borrowed.json()["remediation"]

    async with untenanted_session() as session:
        count = (
            await session.execute(text("SELECT count(*) FROM platform_maintenance_windows"))
        ).scalar()
    assert count == 0, "a refused schedule created a window anyway"


async def test_the_client_read_needs_a_session() -> None:
    """The banner is behind `org:read`. It says which clients are affected by an outage and
    when — not a fact for an unauthenticated caller, and not a route on the public
    surface `check_public_routes` enumerates."""
    async with _client() as http:
        anonymous = await http.get("/v1/maintenance")
    assert anonymous.status_code in (401, 403), anonymous.text


# ---------------------------------------------------------------- 4. campaigns come back


async def _campaign(tenant_id: uuid.UUID, agent_id: uuid.UUID, *, status: str) -> uuid.UUID:
    campaign_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO campaigns (id, tenant_id, agent_id, name, classification, "
                "status, concurrency, created_at, updated_at) VALUES "
                "(:id, :t, :a, :n, 'service', :s, 3, now(), now())"
            ),
            {
                "id": campaign_id,
                "t": tenant_id,
                "a": agent_id,
                "n": f"drain-{campaign_id.hex[:6]}",
                "s": status,
            },
        )
    return campaign_id


async def _status(tenant_id: uuid.UUID, campaign_id: uuid.UUID) -> tuple[str, uuid.UUID | None]:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text("SELECT status, paused_by_maintenance_id FROM campaigns WHERE id = :id"),
                {"id": campaign_id},
            )
        ).one()
    return str(row[0]), row[1]


async def test_a_campaign_paused_by_a_window_comes_back_and_others_do_not() -> None:
    """THE FOUNDER'S "MUST COME BACK WHERE IT WAS", AND ITS CONVERSE.

    Three campaigns and three different fates, because the converse is the half a naive
    implementation gets wrong: resuming everything paused would restart the campaign a
    client stopped on purpose and the one `complaint_spike` stopped for a TCCCPR reason.

    The pause is the ordinary status transition, so `campaign_contacts` and every attempt
    count is untouched — "where it was" is a property of not having moved them, and this
    asserts the bookkeeping that decides WHICH rows move.
    """
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Drain Motors",
        slug=f"drain-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    window_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_maintenance_windows (id, reason, starts_at, ends_at) "
                "VALUES (:id, 'A window that pauses and resumes.', now(), "
                "now() + interval '1 hour')"
            ),
            {"id": window_id},
        )
    try:
        running = await _campaign(tenant_id, agent_id, status="running")
        client_paused = await _campaign(tenant_id, agent_id, status="paused")
        draft = await _campaign(tenant_id, agent_id, status="draft")

        async with tenant_session(tenant_id) as session:
            paused = await pause_campaigns_for_maintenance(session, window_id=window_id)
        assert paused == [running], "the window paused something it should not have"
        assert await _status(tenant_id, running) == ("paused", window_id)
        # The client's own pause is untouched and, crucially, unmarked — so the resume
        # below has no claim on it.
        assert await _status(tenant_id, client_paused) == ("paused", None)
        assert await _status(tenant_id, draft) == ("draft", None)

        async with tenant_session(tenant_id) as session:
            resumed = await resume_campaigns_after_maintenance(session, window_id=window_id)
        assert resumed == [running]
        assert await _status(tenant_id, running) == ("running", None)
        assert await _status(tenant_id, client_paused) == ("paused", None)
        assert await _status(tenant_id, draft) == ("draft", None)
    finally:
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM platform_maintenance_windows WHERE id = :id"),
                {"id": window_id},
            )


async def test_a_campaign_cancelled_during_the_window_is_not_dragged_back() -> None:
    """Between the two edges a client can cancel a campaign the window paused. The status
    must NOT move — but the marker must still be cleared, or the column becomes history and
    the next window's resume sweep looks at a row it has no business touching."""
    from apps.api.admin import service as admin_service

    created = await admin_service.create_organization(
        name="Cancelled Motors",
        slug=f"canc-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    window_id = uuid.uuid4()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO platform_maintenance_windows (id, reason, starts_at, ends_at) "
                "VALUES (:id, 'A window whose campaign was cancelled under it.', now(), "
                "now() + interval '1 hour')"
            ),
            {"id": window_id},
        )
    try:
        campaign_id = await _campaign(tenant_id, agent_id, status="running")
        async with tenant_session(tenant_id) as session:
            await pause_campaigns_for_maintenance(session, window_id=window_id)
            await session.execute(
                text("UPDATE campaigns SET status = 'cancelled' WHERE id = :id"),
                {"id": campaign_id},
            )
        async with tenant_session(tenant_id) as session:
            resumed = await resume_campaigns_after_maintenance(session, window_id=window_id)
        assert resumed == [], "a cancelled campaign was restarted by the window's end"
        assert await _status(tenant_id, campaign_id) == ("cancelled", None)
    finally:
        async with untenanted_session() as session:
            await session.execute(
                text("DELETE FROM platform_maintenance_windows WHERE id = :id"),
                {"id": window_id},
            )
