"""The two client-realm buttons that make a phone ring, over HTTP (D-21).

`callback_test.py` proves `crm.service.plan_callback`'s rules and
`compliance_audit_test.py` proves no dial site skips `check_dispatch`. Neither of them
goes through the ROUTER, and the router is where three things this product promises
actually live:

- **the gate is called before `dispatch_call`, on both buttons.** Hard rule 5 has no
  bypass, and a handler that reordered those two lines would still pass every service
  test in the repo — the service functions do not know about each other;
- **a refusal is a 200 with a NAMED rule**, not an exception. SURFACES §2b asks for a
  button that renders disabled *with a reason*, so `blocked_rule` reaching the wire is
  the feature, and a 500 or a bare 422 is the bug;
- **a double-click does not ring a customer twice.** `POST /leads/{id}/call` keys on the
  caller's `Idempotency-Key`; `POST /calls/{id}/callback` keys on the CALL, so two
  browser tabs cannot each place one.

Every tenant here is created through `admin_service.create_organization` and dials the
`fake` engine. Nothing is monkeypatched except the clock (so a refusal is never the
calling-hours rule by accident) and, in one test, the object-store presigner — an
external dependency the test process has no bucket for.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta
from unittest import mock

import httpx
import pytest
from apps.api.admin import service as admin_service
from apps.api.agents.models import CALL_CAP_MAX_S
from apps.api.compliance.service import add_to_dnc
from apps.api.core.errors import ProblemError
from apps.api.crm import routes
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.engine.fake import FakeEngine
from sqlalchemy import text


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """11:00 IST — inside the platform window, so a refusal here is never the clock."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


def _no_reraise_client() -> httpx.AsyncClient:
    """A client that lets an unhandled server exception become a 500 response instead of
    re-raising it into the test — the only way to assert on the state a crashed request
    leaves behind."""
    from apps.api.main import app

    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://api",
    )


def _client() -> httpx.AsyncClient:
    from apps.api.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://api")


async def _dialable_tenant() -> tuple[uuid.UUID, uuid.UUID, str, dict[str, str]]:
    """(tenant, agent, slug, auth headers) for an owner whose agent can place calls.

    Published (`engine_agent_ref`), `live` and `outbound`: the three facts
    `dispatch_call` and `check_dispatch` between them require. The membership comes from
    `create_organization`'s own `owner_user_id` path rather than a hand-written row, so
    the session this test authenticates is the one the signup motion produces.
    """
    reset_engine_cache()
    user_id = uuid7()
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO users (id, email, created_at, updated_at) "
                "VALUES (:id, :email, now(), now())"
            ),
            {"id": user_id, "email": f"{user_id}@example.com"},
        )
    slug = f"dial-{uuid.uuid4().hex[:8]}"
    created = await admin_service.create_organization(
        name="Dial Clinic",
        slug=slug,
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
        owner_user_id=user_id,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    ref = f"fakeagent_dial_{uuid.uuid4().hex[:8]}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    # Outbound is now gated on the client's DLT PE-TM chain and a registered number bound
    # to the agent (LEGAL-OPS-PLAYBOOK §10.8), the same as campaigns — supply both so this
    # agent lawfully dials, exactly as production would before its first outbound call.
    from tests.conftest import arm_agent_for_outbound

    await arm_agent_for_outbound(tenant_id, agent_id)
    headers = {"Authorization": f"Bearer dev:client:{user_id}", "X-Org-Slug": slug}
    return tenant_id, agent_id, slug, headers


async def _lead(
    tenant_id: uuid.UUID, agent_id: uuid.UUID, phone: str | None = None
) -> tuple[uuid.UUID, str]:
    lead_id = uuid7()
    number = phone or f"+9198{uuid.uuid4().int % 100000000:08d}"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO leads (id, tenant_id, agent_id, phone_e164, name, source, status, "
                "created_at, updated_at) VALUES (:i, :t, :a, :p, 'Priya', 'inbound_call', "
                "'new', now(), now())"
            ),
            {"i": lead_id, "t": tenant_id, "a": agent_id, "p": number},
        )
    return lead_id, number


async def _finished_call(
    tenant_id: uuid.UUID,
    agent_id: uuid.UUID,
    lead_id: uuid.UUID,
    phone: str,
    *,
    outcome: str = "needs_follow_up",
) -> uuid.UUID:
    """One ended call on a lead, in the state `plan_callback` says may be followed up."""
    call_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, to_e164, "
                "status, outcome_tag, summary, lead_id, created_at, updated_at) VALUES "
                "(:i, :t, :a, :e, 'outbound', :p, 'completed', :out, "
                "'Wanted a quote and had to hang up.', :lid, now(), now())"
            ),
            {
                "i": call_id,
                "t": tenant_id,
                "a": agent_id,
                "e": f"exec_{uuid.uuid4().hex[:12]}",
                "p": phone,
                "out": outcome,
                "lid": lead_id,
            },
        )
    return call_id


async def _outbound_calls(tenant_id: uuid.UUID) -> list[tuple[str, str]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT to_e164, status FROM calls WHERE direction = 'outbound' "
                    "ORDER BY created_at"
                )
            )
        ).all()
    return [(str(r[0]), str(r[1])) for r in rows]


# ------------------------------------------------------- POST /v1/leads/{id}/call


async def test_the_lead_button_places_exactly_one_call_and_records_who_pressed_it() -> None:
    """The queued path end to end: a `queued` call row for THIS lead's number, and an
    `lead.call_dispatched` audit row naming the actor.

    The call row is the thing that must exist — `dispatch_call` writes it before the
    engine answers so a dispatch that succeeds at the vendor and fails on our side is
    visible rather than an invisible charge — and the audit row is what makes "who
    called this customer" answerable, which is the question a complaint starts with.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)

    async with _client() as http:
        response = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id), "context_note": "Asked about braces"},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued", body
    assert body["call_handle"], "the engine handle is what the UI polls the call by"
    assert body["blocked_rule"] is None
    assert await _outbound_calls(tenant_id) == [(phone, "queued")], (
        "one press, one call row, to this lead's own number"
    )

    async with untenanted_session() as session:
        actions = (
            await session.execute(
                text("SELECT count(*) FROM audit_log WHERE action = 'lead.call_dispatched' "),
            )
        ).scalar()
        mine = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'lead.call_dispatched' "
                    "AND object_id = :lid"
                ),
                {"lid": str(lead_id)},
            )
        ).scalar()
    assert int(mine or 0) == 1, f"one audit row for this dispatch (total in table: {actions})"


async def test_a_number_on_the_dnc_list_is_refused_by_the_button_with_the_rule_named() -> None:
    """Hard rule 5 at the D-21 button. The refusal is a 200 carrying `blocked_rule`
    rather than an exception, because SURFACES §2b asks the screen to say WHY — and the
    property that matters more is the one asserted last: no call row exists. A handler
    that rendered the reason and dialled anyway would look identical on screen.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="test")

    async with _client() as http:
        response = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "blocked"
    assert body["blocked_rule"] == "dnc", body
    assert body["blocked_reason"], "a refusal the client cannot read is a silent failure"
    assert body["call_handle"] is None
    assert await _outbound_calls(tenant_id) == [], "a DNC number is not dialled"


async def test_two_presses_with_one_idempotency_key_ring_the_customer_once() -> None:
    """A double-click is one dial. The second request replays the stored response —
    same handle, same call row count — because the side effect here is a real phone
    ringing and the reliability triad (BACKEND-PATTERNS §4) asks for a key exactly
    where a repeat cannot be undone.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    key = f"press-{uuid.uuid4().hex[:12]}"

    async with _client() as http:
        first = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={**headers, "Idempotency-Key": key},
        )
        second = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={**headers, "Idempotency-Key": key},
        )

    assert first.status_code == 200 and second.status_code == 200, second.text
    assert first.json()["status"] == "queued"
    assert second.json() == first.json(), "the replay is the FIRST answer, not a new dial"
    assert await _outbound_calls(tenant_id) == [(phone, "queued")], "one ring, not two"


async def test_a_blocked_press_is_replayed_as_blocked_rather_than_dialled_on_retry() -> None:
    """The refusal is stored under the key too. Otherwise the retry a client's browser
    makes after a blocked answer would be a fresh trip through the gate — and would
    dial the moment the block cleared, without anybody pressing anything.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="test")
    key = f"press-{uuid.uuid4().hex[:12]}"

    async with _client() as http:
        first = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={**headers, "Idempotency-Key": key},
        )
        second = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={**headers, "Idempotency-Key": key},
        )

    assert first.json()["blocked_rule"] == "dnc", first.text
    assert second.json() == first.json()
    assert await _outbound_calls(tenant_id) == []


# --------------------------------------------- GET /v1/calls/{id}/callback (why not)


async def test_callback_eligibility_answers_yes_with_the_follow_up_number() -> None:
    """The button renders enabled, and it says which follow-up this would be — the
    chain depth is bounded (`plan_callback`), so the number is what tells the client
    they are near the end of it."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)

    async with _client() as http:
        response = await http.get(f"/v1/calls/{call_id}/callback", headers=headers)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "eligible": True,
        "reason": None,
        "rule": None,
        "follow_up_number": 1,
    }


async def test_callback_eligibility_reports_a_compliance_block_rather_than_a_bare_no() -> None:
    """A call our own rules say may be followed up can still be un-dialable right now.
    The endpoint runs the SAME gate the POST runs, so the greyed-out button carries the
    rule that greyed it — "the button is disabled and I do not know why" is the failure
    SURFACES §2b exists to prevent."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="test")

    async with _client() as http:
        response = await http.get(f"/v1/calls/{call_id}/callback", headers=headers)

    body = response.json()
    assert body["eligible"] is False
    assert body["rule"] == "dnc", body
    assert body["reason"], "the disabled button has to explain itself"


async def test_callback_eligibility_explains_an_ineligible_call_instead_of_erroring() -> None:
    """A resolved call is a BUSINESS RULE refusal, and the route turns it into an
    answer (`eligible: false` + the rule) rather than letting the ProblemError reach the
    browser as a 422. The screen renders the disabled button from this body."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone, outcome="resolved")

    async with _client() as http:
        response = await http.get(f"/v1/calls/{call_id}/callback", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["eligible"] is False
    assert body["rule"] == "callback_not_needed", body


async def test_callback_eligibility_for_an_unknown_call_is_a_404_not_a_false() -> None:
    """The `except` clause re-raises anything that is not a business rule, and that is
    the load-bearing half of it: a mistyped or another tenant's call id must not come
    back as "this call is not eligible", which reads as a fact about a call we hold."""
    _tenant_id, _agent_id, _slug, headers = await _dialable_tenant()

    async with _client() as http:
        response = await http.get(f"/v1/calls/{uuid7()}/callback", headers=headers)

    assert response.status_code == 404, response.text
    assert response.headers["content-type"].startswith("application/problem+json")


# -------------------------------------------- POST /v1/calls/{id}/callback (dial it)


async def test_the_callback_dials_the_same_lead_and_records_the_chain() -> None:
    """The follow-up is a real outbound call linked to the call it follows
    (`callback_of_call_id`), which is what bounds the chain: `plan_callback` counts
    depth through that column, so a callback that did not record its parent would let
    a client ring somebody forever, one button press at a time."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    parent = await _finished_call(tenant_id, agent_id, lead_id, phone)

    async with _client() as http:
        response = await http.post(f"/v1/calls/{parent}/callback", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "queued", body
    assert body["follow_up_number"] == 1
    handle = body["call_handle"]
    assert handle

    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT to_e164, status, callback_of_call_id FROM calls "
                    "WHERE engine_call_id = :h"
                ),
                {"h": handle},
            )
        ).first()
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'call.callback_dispatched' "
                    "AND object_id = :cid"
                ),
                {"cid": str(parent)},
            )
        ).scalar()
    assert row is not None, "the callback wrote a call row"
    assert (str(row[0]), str(row[1])) == (phone, "queued")
    assert uuid.UUID(str(row[2])) == parent, "the new call names the call it follows"
    assert int(audited or 0) == 1


async def test_two_tabs_pressing_callback_on_one_call_place_one_call() -> None:
    """The idempotency key is the CALL id, not a header the client supplies — so two
    browser tabs, which would each mint their own key, still cannot ring the customer
    twice."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    parent = await _finished_call(tenant_id, agent_id, lead_id, phone)

    async with _client() as http:
        first = await http.post(f"/v1/calls/{parent}/callback", headers=headers)
        second = await http.post(f"/v1/calls/{parent}/callback", headers=headers)

    assert first.json()["status"] == "queued", first.text
    assert second.json() == first.json(), "the second tab replays the first answer"
    async with tenant_session(tenant_id) as session:
        dialled = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE status = 'queued' AND to_e164 = :p"),
                {"p": phone},
            )
        ).scalar()
    assert int(dialled or 0) == 1, "one follow-up call row for two presses"


async def test_the_callback_button_refuses_a_number_that_joined_the_dnc_list() -> None:
    """Same gate, same vocabulary, and — the part only the POST can prove — no call.
    A customer who opted out after the first call must not be rung by the follow-up
    button, and the eligibility GET saying so is not what stops it."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    parent = await _finished_call(tenant_id, agent_id, lead_id, phone)
    async with tenant_session(tenant_id) as session:
        await add_to_dnc(session, tenant_id=tenant_id, phone_e164=phone, source="test")

    async with _client() as http:
        response = await http.post(f"/v1/calls/{parent}/callback", headers=headers)

    body = response.json()
    assert body["status"] == "blocked"
    assert body["blocked_rule"] == "dnc", body
    assert body["call_handle"] is None
    async with tenant_session(tenant_id) as session:
        queued = (
            await session.execute(text("SELECT count(*) FROM calls WHERE status = 'queued'"))
        ).scalar()
    assert int(queued or 0) == 0, "an opted-out lead is not called back"


# ------------------------------------------------------- the two plain reads nearby


async def test_the_lead_detail_route_answers_with_the_dialable_number() -> None:
    """`GET /v1/leads/{id}` is the screen the call button sits on, and it now carries
    the number that button dials.

    THIS TEST ASSERTED THE OPPOSITE (`phone_masked.startswith("•")`, and `phone not in
    response.text`). That was hard rule 6 misapplied to a response body: the rule is
    about LOG LINES, and what it produced here was a CRM detail screen that could not
    tell a receptionist who to ring back. D-436 reversed it, and the assertion is
    reversed with it rather than deleted, so the new behaviour is pinned as deliberately
    as the old one was.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)

    async with _client() as http:
        response = await http.get(f"/v1/leads/{lead_id}", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["id"] == str(lead_id)
    assert body["phone_e164"] == phone, "the row is only actionable if the number is on it"
    assert "•" not in response.text, "no dots survive anywhere in the body"


async def test_a_recording_link_is_presigned_and_the_read_is_audited() -> None:
    """The recording is call audio — the most sensitive artefact after the transcript.
    The route hands back a SHORT-LIVED link to OUR copy and writes the audit row in the
    same transaction, so "who listened to this call" is answerable."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET recording_url = :k WHERE id = :i"),
            {"k": f"recordings/{tenant_id}/{call_id}.mp3", "i": call_id},
        )

    # THE CREDENTIALS ARE DECLARED HERE, not inherited from the machine. Presigning is
    # local computation — no object store need exist — but botocore still refuses
    # without a key pair, and `NoCredentialsError` is a `BotoCoreError`, so
    # `presigned_url` returns None and the route correctly answers 502. This test used
    # to pass only where a developer happened to have `AWS_*` exported or a `~/.aws`
    # profile on disk, and failed in CI, which has neither. A test that needs a
    # credential must state it; borrowing one asserts about the machine.
    with mock.patch.dict(
        os.environ,
        {"AWS_ACCESS_KEY_ID": "test-access-key", "AWS_SECRET_ACCESS_KEY": "test-secret-key"},
    ):
        async with _client() as http:
            response = await http.get(f"/v1/calls/{call_id}/recording", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    url = body["url"]
    # `startswith("http")` was the whole assertion here, and a sabotage that returned the
    # literal string "http://sabotage" passed it. A link is only useful if it names OUR
    # object and carries a signature, so assert both: the bucket and the exact key, and
    # the SigV4 parameters that make it presigned rather than merely a URL. Without the
    # signature the link is either a 403 for the client or — far worse, on a bucket
    # someone later makes public — a permanent unauthenticated one.
    assert f"recordings/{tenant_id}/{call_id}.mp3" in url, url
    assert "X-Amz-Signature=" in url, "not a signed link — the client would get a 403"
    assert "X-Amz-Expires=" in url, "an unexpiring link is a permanent leak"
    assert body["expires_in_s"] > 0, "an unexpiring link is a permanent leak"
    async with untenanted_session() as session:
        audited = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'recording.read' "
                    "AND object_id = :cid"
                ),
                {"cid": str(call_id)},
            )
        ).scalar()
    assert int(audited or 0) == 1, "an unaudited listen is a rule-5 violation"


@pytest.mark.parametrize(
    ("duration_s", "expected"),
    [
        # A call the poller never resolved: no metered length, so the floor. Guessing
        # long on audio of unknown size is the wrong direction to be generous in.
        (None, routes.RECORDING_LINK_FLOOR_S),
        (0, routes.RECORDING_LINK_FLOOR_S),
        # Shorter than the floor: the floor still wins, because a 12-second recording
        # still has to survive a slow first byte.
        (12, routes.RECORDING_LINK_FLOOR_S),
        # THE CASE THAT WAS BROKEN. 20 minutes of audio behind a 5-minute signature: the
        # link died at 300s and the browser reported it as a bare media error, so the
        # owner's reasonable conclusion was that we recorded only the first five minutes.
        (1200, 2400),
        # A maximal call (`CALL_CAP_MAX_S`), which is what the ceiling is sized for.
        (3600, 7200),
    ],
)
def test_a_recording_link_outlives_the_audio_it_points_at(
    duration_s: int | None, expected: int
) -> None:
    """The link's life is DERIVED from the call's length, and the derivation is the fix.

    Asserted as a pure function rather than through the route because the property is
    arithmetic — the route test below proves the number actually reaches the wire and
    the signature. Both halves are needed: a correct function nobody calls, and a route
    that calls a wrong one, fail in ways the other test cannot see.
    """
    assert routes.recording_link_ttl_s(duration_s) == expected


def test_no_recording_link_can_be_minted_for_longer_than_the_stated_ceiling() -> None:
    """The widest credential window this route can ever open, pinned.

    The signature IS the credential, so "how long can a leaked link stay useful?" must
    have an answer a reviewer can read off a constant rather than derive. A duration
    beyond any call this platform will run — a corrupt row, a future cap raise made
    without revisiting this file — must still be bounded.
    """
    absurd = routes.recording_link_ttl_s(10**9)
    assert absurd == routes.RECORDING_LINK_CEILING_S
    assert absurd <= 2 * CALL_CAP_MAX_S + routes.RECORDING_LINK_FLOOR_S


async def test_the_link_the_wire_carries_expires_with_the_call_not_with_a_constant() -> None:
    """The route hands down the DERIVED lifetime, and S3 signs for that same number.

    Two separate assertions on purpose. `expires_in_s` is what the screen reads; the
    `X-Amz-Expires` parameter is what S3 enforces. A route that reported one and signed
    the other would show a player promising thirty minutes and cut out after five —
    which is the defect in a new costume rather than the defect fixed.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET recording_url = :k, duration_s = 1200 WHERE id = :i"),
            {"k": f"recordings/{tenant_id}/{call_id}.mp3", "i": call_id},
        )

    with mock.patch.dict(
        os.environ,
        {"AWS_ACCESS_KEY_ID": "test-access-key", "AWS_SECRET_ACCESS_KEY": "test-secret-key"},
    ):
        async with _client() as http:
            response = await http.get(f"/v1/calls/{call_id}/recording", headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["expires_in_s"] == 2400, "the reported life is not the derived one"
    assert body["duration_s"] == 1200, "the player draws its seek bar from this"
    assert "X-Amz-Expires=2400" in body["url"], (
        "S3 signed for a different window than the response advertises — the player "
        f"would stop early and say nothing. url={body['url']}"
    )


async def test_a_call_that_was_never_recorded_says_so_rather_than_naming_the_call() -> None:
    """Two 404s, and which one you get is the whole point (the D-65 discriminator on a
    read): a mistyped call id is "Call", and a real call with no audio — never recorded,
    or destroyed by a retention sweep once its 90 days elapsed — is "Recording".

    An owner who mistyped a URL goes back to the list. An owner whose retention window
    closed needs to know the audio is gone and not coming back. One message cannot send
    both of them to the right place.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)
    # `_finished_call` leaves `recording_url` NULL, which IS the "never recorded" state.

    async with _client() as http:
        missing_audio = await http.get(f"/v1/calls/{call_id}/recording", headers=headers)
        missing_call = await http.get(f"/v1/calls/{uuid.uuid4()}/recording", headers=headers)

    assert missing_audio.status_code == 404, missing_audio.text
    assert missing_call.status_code == 404, missing_call.text
    assert "Recording" in missing_audio.json()["title"], missing_audio.json()
    assert "Call" in missing_call.json()["title"], missing_call.json()
    assert missing_audio.json()["title"] != missing_call.json()["title"], (
        "both 404s read identically, so the screen cannot tell an owner whether to go "
        "back to the list or stop looking"
    )


async def test_an_unpresignable_recording_is_a_named_dependency_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Object storage being down is OUR problem, and the client gets a problem+json
    saying the recording is unavailable — not a signed link to nothing and not a
    stack trace. `presigned_url` returns None on any boto failure, and this is the only
    branch that reads it."""
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET recording_url = :k WHERE id = :i"),
            {"k": f"recordings/{tenant_id}/{call_id}.mp3", "i": call_id},
        )

    from apps.workers import storage

    monkeypatch.setattr(storage, "presigned_url", lambda *_a, **_k: None)

    async with _client() as http:
        response = await http.get(f"/v1/calls/{call_id}/recording", headers=headers)

    assert response.status_code == 502, response.text
    body = response.json()
    assert body["type"].endswith("recording_unavailable"), body
    assert body["retryable"] is True, "storage being down is worth retrying; the client is told so"
    assert response.headers["content-type"].startswith("application/problem+json")


async def _settle_calls(tenant_id: uuid.UUID) -> None:
    """Leave no live call row behind.

    A `queued` row spends a line out of the PLATFORM-WIDE outbound pool (FLOWS §5 rule 1)
    for a full hour, and this repo's tests share one Postgres with other suites and other
    pytest processes — `campaign_dispatch_audit_test` carries the same teardown for the
    same reason. The two tests below deliberately create rows for calls that were never
    answered, so they are the ones that would strand.
    """
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE calls SET status = 'completed', updated_at = now() "
                "WHERE status IN ('queued', 'ringing', 'in_progress')"
            )
        )


# --------------------------------- the two failure paths the buttons must survive
#
# Both are D-181. They drive a raise through the middle of a request that has already
# had a side effect the world can see — a vendor that may have started dialling, and an
# audit write that fails after the customer's phone has rung — because the success path
# says nothing about either.


async def test_a_dial_the_engine_may_have_started_leaves_a_call_row_and_refuses_to_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The engine is asked, and the answer is lost (a read timeout, a reset, a proxy 502
    after the vendor committed). The button cannot claim the call was placed and must not
    invite a second press that rings the customer again.

    The row is the whole point: `dispatch_call` commits it BEFORE the vendor can seize a
    line, so the call the client may have been charged for is on their own call log
    rather than nowhere. The old ordering could not write one — the row's key was the
    answer that never came.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)

    async def lost_response(self: object, ref: str, to: str, ctx: object) -> str:
        raise ProblemError(
            kind="dependency",
            code="engine_unreachable",
            title="Voice engine unreachable",
            detail="The voice platform did not respond.",
        )

    monkeypatch.setattr(FakeEngine, "start_outbound_call", lost_response)
    async with _client() as http:
        response = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={**headers, "Idempotency-Key": str(uuid.uuid4())},
        )

    assert response.status_code >= 500, response.text
    body = response.json()
    assert body["type"].endswith("/dial_unconfirmed"), body
    assert "ring them twice" in body["remediation"], (
        "the person reading this is about to press the button again"
    )
    assert await _outbound_calls(tenant_id) == [(phone, "queued")], (
        "a dial the vendor may have accepted must not be an invisible charge"
    )
    await _settle_calls(tenant_id)


async def test_a_callback_the_engine_may_have_started_says_so_and_does_not_offer_a_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The same D-181 third outcome, on the OTHER button — and the two buttons had only
    one of them tested.

    The callback is the sharper case. Its idempotency key is derived from the parent
    call rather than supplied by the client, so "press it again" is not a new request
    the server can tell apart: the claim taken before the dial is deliberately LEFT
    `processing` when the vendor's answer is lost, which is what stops a second press
    from ringing somebody whose phone may already be ringing. A claim completed here —
    or rolled back — would each, in opposite ways, hand the customer a second call.

    So this pins three things at once: the client is told the truth in words they can
    act on, the possible charge is on the client's own call log as a `queued` row, and
    the button cannot be used to try again.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    parent = await _finished_call(tenant_id, agent_id, lead_id, phone)

    async def lost_response(self: object, ref: str, to: str, ctx: object) -> str:
        raise ProblemError(
            kind="dependency",
            code="engine_unreachable",
            title="Voice engine unreachable",
            detail="The voice platform did not respond.",
        )

    original = FakeEngine.start_outbound_call
    monkeypatch.setattr(FakeEngine, "start_outbound_call", lost_response)
    async with _client() as http:
        response = await http.post(f"/v1/calls/{parent}/callback", headers=headers)

    assert response.status_code >= 500, response.text
    body = response.json()
    assert body["type"].endswith("/dial_unconfirmed"), body
    assert "ring them twice" in body["remediation"], (
        "the person reading this is about to press the button again"
    )
    assert await _outbound_calls(tenant_id) == [(phone, "completed"), (phone, "queued")], (
        "the parent call and ONE unconfirmed follow-up — the possible charge is on record"
    )

    # The second press, with the engine working again: the claim left `processing` is
    # what has to refuse it, because nothing else on this route can. Restored BY NAME
    # rather than through `monkeypatch.undo()`, which is per-test and would also revert
    # the autouse `_daytime` pin — the retry would then meet the calling-hours gate
    # instead of the claim, and pass for a reason this test is not about.
    monkeypatch.setattr(FakeEngine, "start_outbound_call", original)
    async with _no_reraise_client() as http:
        again = await http.post(f"/v1/calls/{parent}/callback", headers=headers)
    assert again.status_code == 409, again.text
    assert again.json()["type"].endswith("/idempotent_request_in_flight"), again.text
    assert await _outbound_calls(tenant_id) == [(phone, "completed"), (phone, "queued")], (
        "the second press rang a customer whose phone may already have been ringing"
    )
    await _settle_calls(tenant_id)


async def test_a_failure_after_the_phone_rang_does_not_let_the_same_key_dial_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """CORRECTNESS 1, on the button whose side effect is a person's phone.

    The claim used to be INSERTed into the request's own transaction, which
    `core/deps.db` rolls back on any exception. So a raise anywhere after the dial — the
    audit chain refusing to write, a statement timeout, a severed connection — erased the
    claim while the customer had already been called, and the retry the
    `Idempotency-Key` exists to answer placed a SECOND call.

    Driven with the audit write raising, because that is the failure the audit report
    names and because it sits exactly between the dial and the response.
    """
    tenant_id, agent_id, _slug, headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    key = str(uuid.uuid4())

    async def refuse_to_audit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("audit chain unavailable")

    # Patched and restored BY HAND rather than through `monkeypatch.undo()`: undo() is
    # per-test, not per-call, so it would also revert the autouse `_daytime` clock pin —
    # and the retry below would then be refused by the calling-hours gate instead of
    # dialling, i.e. a green test that proves nothing.
    original_write_audit = routes.write_audit
    routes.write_audit = refuse_to_audit  # type: ignore[assignment]
    # `raise_app_exceptions=False`: this failure is deliberately NOT one the error ladder
    # has a rung for — an unhandled exception is exactly what the audit report names —
    # and the test is about what the SERVER is left holding, not about the 500.
    async with _no_reraise_client() as http:
        first = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={**headers, "Idempotency-Key": key},
        )
    assert first.status_code >= 500, first.text
    assert await _outbound_calls(tenant_id) == [(phone, "queued")], "one press, one call"

    # THE RETRY, same key, with the audit write working again — i.e. the client doing
    # exactly what an Idempotency-Key is for.
    routes.write_audit = original_write_audit  # type: ignore[assignment]
    async with _client() as http:
        second = await http.post(
            f"/v1/leads/{lead_id}/call",
            json={"agent_id": str(agent_id)},
            headers={**headers, "Idempotency-Key": key},
        )
    assert second.status_code != 200 or second.json()["status"] != "queued", second.text
    assert await _outbound_calls(tenant_id) == [(phone, "queued")], (
        "the retry rang the customer a second time — the claim did not survive the failure"
    )
    await _settle_calls(tenant_id)


async def test_staff_cannot_reach_the_recording_audio(monkeypatch: pytest.MonkeyPatch) -> None:
    """S-1 / D-181. THE AUDIO IS THE SOURCE OF THE TEXT the redaction apparatus protects.

    A caller who reads out an Aadhaar number, a card number or an OTP is masked in
    `text_redacted` and audible in the `.wav`. SEC-COMP §5 and DATA-MODEL §2 both say
    `staff` never sees unredacted call content, the raw transcript route is
    `calls:read_raw` + audit, and the CSV export was MOVED to `calls:read_raw` for
    exactly this reason — while this route stayed on `calls:read`, which `core/rbac.py`
    grants to staff. It was audited unredacted access: the audit half of hard rule 5
    without the role half.

    The owner arm is the positive control: the route still works for the role that may
    hear it, so this is a gate rather than a route that broke.
    """
    tenant_id, agent_id, slug, owner_headers = await _dialable_tenant()
    lead_id, phone = await _lead(tenant_id, agent_id)
    call_id = await _finished_call(tenant_id, agent_id, lead_id, phone)
    key = f"recordings/{tenant_id}/{call_id}.mp3"
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text("UPDATE calls SET recording_url = :k WHERE id = :i"),
            {"k": key, "i": call_id},
        )
    staff_headers = await _staff_of(tenant_id, slug)

    # The presigner is never reached on the staff arm — the point is that the gate
    # refuses before anything is minted — so it is stubbed only for the owner control.
    monkeypatch.setattr("apps.workers.storage.presigned_url", lambda k, ttl_s: f"https://s3/{k}")

    async with _client() as http:
        refused = await http.get(f"/v1/calls/{call_id}/recording", headers=staff_headers)
        allowed = await http.get(f"/v1/calls/{call_id}/recording", headers=owner_headers)

    assert refused.status_code == 403, refused.text
    assert refused.json()["kind"] == "permission"
    assert key not in refused.text, "a refusal must not name the object it refused"
    assert allowed.status_code == 200, allowed.text
    assert key in allowed.json()["url"]

    async with untenanted_session() as session:
        reads = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE action = 'recording.read' "
                    "AND object_id = :oid"
                ),
                {"oid": str(call_id)},
            )
        ).scalar()
    assert int(reads or 0) == 1, "the read that was allowed is the only one recorded"


async def _staff_of(tenant_id: uuid.UUID, slug: str) -> dict[str, str]:
    """A second member of the SAME org, holding `staff` — the role a client hands a
    junior telecaller."""
    user_id = uuid7()
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
                "VALUES (:id, :tid, :uid, 'staff', now(), now())"
            ),
            {"id": uuid7(), "tid": tenant_id, "uid": user_id},
        )
    return {"Authorization": f"Bearer dev:client:{user_id}", "X-Org-Slug": slug}
