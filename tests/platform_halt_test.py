"""The big red switch: why it was pulled, and a confirmation that names which pull.

Two defects, one surface, one file — they are the same surface because they are the
same 3am question. An operator who finds outbound calling stopped asks *why*, and then
asks *may I lift it*, and until now the platform answered neither on the row it shows
them:

1. **`platform_state.halt_reason` was never written** (found by `scripts/check_wiring`,
   which carried it in `UNWIRED_BASELINE`). The reason went to `write_audit`'s
   `summary`, and `audit_log` HAS NO SUMMARY COLUMN — the sanitiser sends it to the log
   stream keyed by entry id (`compliance/audit.py`). So the dashboard read NULL, and
   `runbooks/campaign-stall.md` §1's "check `audit_log` for who and why" could only ever
   deliver the *who*. The reason existed in a log line and nowhere queryable.
2. **One confirmation string covered three different actions.** `halt_outbound` for a
   halt, and `set_platform_state` for BOTH releasing the switch and a routine load-shed
   tweak. BACKEND-PATTERNS §7 asks for a step-up bound to the SPECIFIC action; a header
   captured while changing the load-shed mode would release a global outbound halt.
   `billing/cap_routes.py` (via `ops.routes.spend_cap_confirmation`) already shows the
   shape that works — action AND target.

WHAT IS ASSERTED, AND WHY EACH ONE IS A REGRESSION IF IT FLIPS

* the reason is REQUIRED to halt and lands on the row, not only in a log line;
* it is CLEARED on release — a reason beside `outbound_halted = false` reads as
  current, and an operator acting on last week's reason is worse off than one who sees
  nothing;
* a load-shed change does NOT touch it, so tightening shedding during an incident
  cannot erase why the incident halted dialling;
* every confirmation is bound to its transition, in both directions and per mode;
* each transition writes its OWN audit action, so `audit_log` can be searched for
  halts without matching load-shed edits.

CONCURRENCY. `platform_state` is ONE global row shared with every other suite, and a
halt left behind stops their dialling. Exactly one test here moves the switch, for as
few statements as possible, and restores it in `finally` — the pattern
`platform_audit_test` established. Every other test asserts a REFUSAL, so it never
moves anything.
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.db.session import untenanted_session
from apps.api.main import app
from apps.api.ops import routes as ops_routes
from apps.api.ops.routes import platform_confirmation
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from tests.admin_security_test import _make_admin


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _halt_row() -> tuple[bool, str | None]:
    async with untenanted_session() as session:
        row = (
            await session.execute(
                text("SELECT outbound_halted, halt_reason FROM platform_state WHERE id = 1")
            )
        ).first()
    assert row is not None, "the singleton is seeded by migration 769a9152cb06"
    return bool(row[0]), row[1]


async def _audit_actions(since: str) -> list[str]:
    """Every `ops.*` audit action written after the given entry id.

    Keyed off an id rather than a timestamp because uuid7 is time-ordered and two
    entries can share a millisecond; and scoped to this window because other suites
    write to the same append-only table.
    """
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text(
                    "SELECT action FROM audit_log WHERE id > :since AND action LIKE 'ops.%' "
                    "ORDER BY id"
                ),
                {"since": since},
            )
        ).all()
    return [str(r[0]) for r in rows]


async def _last_audit_id() -> str:
    async with untenanted_session() as session:
        row = (
            await session.execute(text("SELECT id FROM audit_log ORDER BY id DESC LIMIT 1"))
        ).first()
    return str(row[0]) if row else str(uuid.UUID(int=0))


# --------------------------------------------------------------------------------
# 1. The confirmation string is a published ops procedure, not an implementation detail
# --------------------------------------------------------------------------------


def test_the_confirmation_names_the_exact_transition() -> None:
    """Pinned as literals because the runbooks PRINT them.

    `runbooks/calls-stopped.md` §1 and `runbooks/campaign-stall.md` §1 tell an operator
    mid-incident exactly what to type. A quiet reformat here would leave both runbooks
    instructing them to send a header the API refuses — the failure mode
    `spend_cap_confirmation` was given a named function to prevent.
    """
    assert platform_confirmation(outbound_halted=True, load_shed_mode=None) == "halt_outbound"
    assert platform_confirmation(outbound_halted=False, load_shed_mode=None) == "release_outbound"
    assert (
        platform_confirmation(outbound_halted=None, load_shed_mode="maintenance")
        == "set_load_shed:maintenance"
    )
    # Both in one request: deterministic order, halt first, because that is the half an
    # operator must read before they send it.
    assert (
        platform_confirmation(outbound_halted=True, load_shed_mode="maintenance")
        == "halt_outbound+set_load_shed:maintenance"
    )


async def test_a_confirmation_for_one_transition_does_not_authorise_another() -> None:
    """The property §7 asks for, and the one this route did not have.

    Refusals only — nothing below moves the switch, so this runs beside every other
    suite. The load-shed cases matter most: `reduced` is a routine Tuesday change and
    `halt_outbound` is not, and until now one header satisfied both.
    """
    token = await _make_admin()
    auth = {"Authorization": f"Bearer {token}"}

    async with _client() as http:
        # The old generic string, which is what an operator's muscle memory and every
        # copy-pasted curl still carries. It authorises nothing now, in either direction.
        stale_on_halt = await http.post(
            "/v1/ops/platform",
            headers={**auth, "X-Confirm-Action": "set_platform_state"},
            json={"outbound_halted": True, "reason": "stale header"},
        )
        stale_on_release = await http.post(
            "/v1/ops/platform",
            headers={**auth, "X-Confirm-Action": "set_platform_state"},
            json={"outbound_halted": False, "reason": "stale header"},
        )
        # A header captured for a load-shed tweak must not release a global halt.
        shed_header_on_release = await http.post(
            "/v1/ops/platform",
            headers={**auth, "X-Confirm-Action": "set_load_shed:reduced"},
            json={"outbound_halted": False, "reason": "replayed from a load-shed change"},
        )
        # And the reverse: a halt confirmation is not a licence to release.
        halt_header_on_release = await http.post(
            "/v1/ops/platform",
            headers={**auth, "X-Confirm-Action": "halt_outbound"},
            json={"outbound_halted": False, "reason": "replayed from the halt"},
        )
        # Bound to the TARGET mode too, exactly as the spend-cap confirmation is bound
        # to the tenant: `reduced` is not consent to `maintenance`, which sheds reads.
        wrong_mode = await http.post(
            "/v1/ops/platform",
            headers={**auth, "X-Confirm-Action": "set_load_shed:reduced"},
            json={"load_shed_mode": "maintenance", "reason": "replayed from a milder change"},
        )
        # A combined request needs the combined confirmation; half of it is not enough.
        half_of_a_pair = await http.post(
            "/v1/ops/platform",
            headers={**auth, "X-Confirm-Action": "halt_outbound"},
            json={
                "outbound_halted": True,
                "load_shed_mode": "maintenance",
                "reason": "halt confirmed, the maintenance half is not",
            },
        )

    for name, response in (
        ("stale_on_halt", stale_on_halt),
        ("stale_on_release", stale_on_release),
        ("shed_header_on_release", shed_header_on_release),
        ("halt_header_on_release", halt_header_on_release),
        ("wrong_mode", wrong_mode),
        ("half_of_a_pair", half_of_a_pair),
    ):
        assert response.status_code == 403, f"{name}: {response.text}"
        assert response.json()["type"].endswith("/step_up_required"), name

    # The break is self-healing at the terminal: the refusal names the header to send,
    # so an operator with the old curl is one paste away rather than one grep away.
    assert "release_outbound" in stale_on_release.json()["remediation"]
    assert "set_load_shed:maintenance" in wrong_mode.json()["remediation"]

    assert (await _halt_row())[0] is False, "a refused step-up must not have moved the switch"


async def test_a_post_that_changes_nothing_is_refused_rather_than_audited() -> None:
    """`{"reason": "..."}` alone used to reach `set_platform_status`, change nothing,
    and still write an audit row.

    It has no transition, so it has no confirmation string to be bound to — the
    honest answer is a 422 naming the two fields, not a green 200 that logged a
    platform change nobody made.
    """
    token = await _make_admin()
    async with _client() as http:
        response = await http.post(
            "/v1/ops/platform",
            headers={"Authorization": f"Bearer {token}", "X-Confirm-Action": "halt_outbound"},
            json={"reason": "changing nothing at all"},
        )
    assert response.status_code == 422, response.text
    assert response.json()["type"].endswith("/platform_state_no_change")


async def test_halting_without_saying_why_is_refused() -> None:
    """A halt nobody explained is a halt nobody can safely lift.

    The reason is the operational half of the switch, not decoration: whoever finds it
    at 3am has to decide whether the condition still holds, and "someone stopped all
    outbound calling on Tuesday" is not a basis for that decision. Enforced at the
    boundary (min_length), so the column cannot be NULL while `outbound_halted` is true
    through this route.
    """
    token = await _make_admin()
    auth = {"Authorization": f"Bearer {token}", "X-Confirm-Action": "halt_outbound"}
    async with _client() as http:
        missing = await http.post("/v1/ops/platform", headers=auth, json={"outbound_halted": True})
        blank = await http.post(
            "/v1/ops/platform", headers=auth, json={"outbound_halted": True, "reason": "    "}
        )
    assert missing.status_code == 422, missing.text
    # Long enough to pass a naive `min_length`, and still not a reason.
    assert blank.status_code == 422, "whitespace is not a reason"
    assert (await _halt_row())[0] is False


# --------------------------------------------------------------------------------
# 2. The reason reaches the row, and leaves it again
# --------------------------------------------------------------------------------


async def test_the_halt_records_its_reason_and_the_release_clears_it() -> None:
    """The whole lifecycle, in one test, because it is one property.

    THE ORDER IS THE POINT. Halt with a reason → the row and the dashboard carry it →
    a load-shed change while halted leaves it alone → release clears it. Splitting
    these would need four tests each moving the shared global switch; this moves it
    once and restores it in `finally`.

    The load-shed step is the subtle one: an operator tightening shedding during the
    same incident must not erase why dialling stopped. The write only touches
    `halt_reason` when `outbound_halted` is part of the request.
    """
    token = await _make_admin()
    auth = {"Authorization": f"Bearer {token}"}
    reason = "Bolna outage — every dial failing (INC-2031)"
    watermark = await _last_audit_id()

    try:
        async with _client() as http:
            halted = await http.post(
                "/v1/ops/platform",
                headers={**auth, "X-Confirm-Action": "halt_outbound"},
                json={"outbound_halted": True, "reason": reason},
            )
            assert halted.status_code == 200, halted.text
            assert halted.json()["halt_reason"] == reason
            assert await _halt_row() == (True, reason), "the durable row, not just the response"

            # The dashboard read — the one `runbooks/calls-stopped.md` §1 sends an
            # operator to. It must answer the "why" in the same request as the "what".
            read = await http.get("/v1/ops/platform", headers=auth)
            assert read.json()["outbound_halted"] is True
            assert read.json()["halt_reason"] == reason

            shed = await http.post(
                "/v1/ops/platform",
                headers={**auth, "X-Confirm-Action": "set_load_shed:reduced"},
                json={"load_shed_mode": "reduced", "reason": "shedding writes too"},
            )
            assert shed.status_code == 200, shed.text
            assert shed.json()["halt_reason"] == reason, "a load-shed edit must not erase it"
            assert await _halt_row() == (True, reason)

            # Release, over the same audited path an operator uses — and note the
            # confirmation for a request that does BOTH halves carries both.
            released = await http.post(
                "/v1/ops/platform",
                headers={**auth, "X-Confirm-Action": "release_outbound+set_load_shed:normal"},
                json={
                    "outbound_halted": False,
                    "load_shed_mode": "normal",
                    "reason": "engine recovered, dialling resumed",
                },
            )
            assert released.status_code == 200, released.text
            # Cleared, not kept. A reason beside `outbound_halted = false` reads as
            # current to everyone who has not read this file, and the history it would
            # preserve is already in `audit_log` — where it cannot be mistaken for the
            # state of the platform right now.
            assert released.json()["halt_reason"] is None
            assert released.json()["load_shed_mode"] == "normal"
            assert await _halt_row() == (False, None)
    finally:
        # The shared row is restored whatever failed above — including a failure in the
        # release request itself. Idempotent, and it is the only statement in this file
        # allowed to bypass the audited path: leaving another suite's dialling halted
        # because an assertion tripped is not an acceptable way to fail.
        from apps.api.core.loadshed import set_platform_status

        await set_platform_status(
            mode="normal", outbound_halted=False, halt_reason=None, actor_id=None
        )

    # Each transition is its own audit action, so "when did we last halt everyone" is a
    # query rather than a full-text hunt through one generic action name.
    actions = await _audit_actions(watermark)
    assert "ops.halt_outbound" in actions
    assert "ops.set_load_shed" in actions
    assert "ops.release_outbound" in actions
    assert "ops.set_platform_state" not in actions, "the generic action is gone in both halves"


async def test_the_halt_queues_the_recall_and_the_release_does_not(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D-432: the switch has a second arm, and it must fire on the halt and nowhere else.

    Until D-432 `outbound_halted` stopped this platform PLACING dials and recalled none
    the vendor had already accepted — and the vendor accepts more than it runs, queueing
    the surplus over the account's concurrency ceiling in a queue we cannot see or scrub.
    `recall_queued_dials` is that arm; this asserts the WIRING, which is the half a route
    can silently lose (`scripts/check_job_wiring` shape 3: an enqueue succeeds against any
    string, and a name no worker answers to fails with every screen green).

    THE RELEASE MUST NOT FIRE IT. Recalling queued dials the moment an operator resumes
    dialling would cancel the campaign they just restarted, and the job's own halt re-read
    is the second line of that defence rather than the first.
    """
    queued: list[str] = []

    async def _record(job: str, *args: object, **kwargs: object) -> str:
        queued.append(job)
        return "job-id"

    monkeypatch.setattr(ops_routes, "enqueue", _record)
    token = await _make_admin()
    auth = {"Authorization": f"Bearer {token}"}

    try:
        async with _client() as http:
            halted = await http.post(
                "/v1/ops/platform",
                headers={**auth, "X-Confirm-Action": "halt_outbound"},
                json={"outbound_halted": True, "reason": "recall wiring"},
            )
            assert halted.status_code == 200, halted.text
            assert queued == [ops_routes.DIAL_RECALL_JOB]

            queued.clear()
            released = await http.post(
                "/v1/ops/platform",
                headers={**auth, "X-Confirm-Action": "release_outbound"},
                json={"outbound_halted": False, "reason": "done"},
            )
            assert released.status_code == 200, released.text
            assert queued == []
    finally:
        from apps.api.core.loadshed import set_platform_status

        await set_platform_status(
            mode="normal", outbound_halted=False, halt_reason=None, actor_id=None
        )


async def test_a_queue_that_cannot_be_reached_does_not_refuse_the_halt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The halt is the thing that matters, and it has already landed by then.

    Raising here would tell an operator mid-incident that the switch did not throw when
    it did, and their next move is to throw it again. So the failure is an ALARM with a
    runbook row (`dial_recall_not_queued`) and a 200 that truthfully reports the halt.
    """
    fired: list[str] = []

    async def _explode(job: str, *args: object, **kwargs: object) -> str:
        raise RuntimeError("redis is gone")

    monkeypatch.setattr(ops_routes, "enqueue", _explode)
    monkeypatch.setattr(ops_routes, "alert", lambda stage, code, **kw: fired.append(code))
    token = await _make_admin()

    try:
        async with _client() as http:
            halted = await http.post(
                "/v1/ops/platform",
                headers={"Authorization": f"Bearer {token}", "X-Confirm-Action": "halt_outbound"},
                json={"outbound_halted": True, "reason": "queue down"},
            )
            assert halted.status_code == 200, halted.text
            assert halted.json()["outbound_halted"] is True
            assert fired == ["dial_recall_not_queued"]
    finally:
        from apps.api.core.loadshed import set_platform_status

        await set_platform_status(
            mode="normal", outbound_halted=False, halt_reason=None, actor_id=None
        )
