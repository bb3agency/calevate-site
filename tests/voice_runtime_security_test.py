"""Security-critical voice-runtime behaviour: webhook authenticity, dedupe, deferral.

These are the tests that would have to fail before a forged engine event, a
double-metered call or a synchronous pipeline in the ack path could ship. Suffix
`_security_test` per BACKEND-PATTERNS §9.

The receiver is the only unauthenticated write surface Calevate exposes to the public
internet, and D-31 chose an engine that signs NOTHING. That makes the whole authenticity
story two facts: the packet came from the engine's static egress IP, and the execution id
has not been seen before. Everything below is a test of one of those two facts, or of
hard rule 3's promise that nothing else happens on this path.

Notes for whoever reads this next:

- **The allowlist is a module constant, not a setting.** `engine_intake.BOLNA_SOURCE_IPS`
  is a hard-coded `frozenset`, so these tests monkeypatch the module attribute rather
  than an env var. If it ever moves into `Settings`, this fixture is the one thing to
  rewrite.
- **The peer IP is `scope["client"]`**, which `httpx.ASGITransport` lets us set. That is
  exactly the TCP peer nginx or Cloudflare would present, so `_client(ip)` below is a
  faithful stand-in for "who actually opened the socket".
"""

from __future__ import annotations

import uuid
from typing import Any

import engine_intake
import pytest
import webhook_routes
from apps.api.core.redis import get_redis
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.reliability.service import body_hash
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import text

# RFC 5737 documentation ranges: unroutable, so a copy-paste of any of these into a real
# config is inert rather than dangerous.
ENGINE_EGRESS_IP = "198.51.100.7"  # stands in for Bolna's static egress IP
ATTACKER_IP = "203.0.113.9"  # some box on the internet that found the URL
EDGE_PROXY_IP = "127.0.0.1"  # inside TRUSTED_PROXY_CIDRS — our own nginx

HOOK = "/hooks/v1/engine/bolna"


@pytest.fixture(autouse=True)
def _allowlist(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the allowlist at a documentation IP for the duration of each test.

    `verify_source` reads the module global at call time, so patching the attribute is
    enough — and it keeps these tests from encoding a vendor's current egress IP, which
    is a value that changes without our permission.
    """
    monkeypatch.setattr(engine_intake, "BOLNA_SOURCE_IPS", frozenset({ENGINE_EGRESS_IP}))


def _client(peer_ip: str) -> AsyncClient:
    """An ASGI client whose immediate TCP peer is `peer_ip`."""
    return AsyncClient(
        transport=ASGITransport(app=voice_app, client=(peer_ip, 44444)),
        base_url="http://runtime",
    )


def _event() -> tuple[str, str, dict[str, Any]]:
    """A unique (execution_id, status, payload). The status doubles as a per-test tag so
    the forensic `webhook_deliveries` row — which has no execution id column — can still
    be counted precisely."""
    token = uuid.uuid4().hex[:12]
    execution_id = f"exec_{token}"
    status = f"completed-{token}"
    return execution_id, status, {"execution_id": execution_id, "status": status}


async def _counts(*, execution_id: str, event_type: str, engine: str = "bolna") -> tuple[int, int]:
    """(inbox rows, forensic delivery rows) — both infra tables, neither tenant-scoped,
    so `untenanted_session` sees them honestly."""
    async with untenanted_session() as session:
        inbox = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_inbox_events "
                    "WHERE provider = :p AND event_key = :k"
                ),
                {"p": engine, "k": execution_id},
            )
        ).scalar()
        deliveries = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_deliveries "
                    "WHERE source = :p AND event_type = :e AND direction = 'in'"
                ),
                {"p": engine, "e": event_type},
            )
        ).scalar()
    return int(inbox or 0), int(deliveries or 0)


async def _seed_route(engine_agent_ref: str) -> uuid.UUID:
    """An org + agent + the routing row, exactly as the publish path writes them. Needed
    only so that a test can prove the receiver did NOT resolve a tenant it could have."""
    tenant_id = uuid.uuid4()
    agent_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO organizations (id, name, slug, status, created_at, updated_at) "
                "VALUES (:id, 'Sunrise Clinic', :slug, 'active', now(), now())"
            ),
            {"id": tenant_id, "slug": f"vr-{tenant_id.hex[:10]}"},
        )
        await session.execute(
            text(
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, status, "
                "engine, engine_agent_ref, created_at, updated_at) VALUES (:id, :tid, "
                "'Receptionist', 'inbound', 'Idi AI assistant. Call record avutundi.', 'live', "
                "'bolna', :ref, now(), now())"
            ),
            {"id": agent_id, "tid": tenant_id, "ref": engine_agent_ref},
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('bolna', :ref, :tid, :aid, true, now(), "
                "now())"
            ),
            {"ref": engine_agent_ref, "tid": tenant_id, "aid": agent_id},
        )
    return tenant_id


# --- 1. the allowlist ---------------------------------------------------------


async def test_a_caller_outside_the_allowlist_is_rejected_and_writes_nothing() -> None:
    """Bolna signs nothing (D-31), so the source-IP allowlist is the ENTIRE authenticity
    control. A stranger who guesses the URL must get a 401 and must not leave a row —
    otherwise the inbox becomes an attacker-controlled table and the `webhook_deliveries`
    forensic trail becomes noise the moment someone runs a scanner at us.
    """
    execution_id, status, body = _event()

    async with _client(ATTACKER_IP) as http:
        response = await http.post(HOOK, json=body)

    assert response.status_code == 401, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["kind"] == "auth"
    assert problem["retryable"] is False
    # User-safe message: no allowlist contents, no peer IP, no internals leaked back.
    assert ENGINE_EGRESS_IP not in response.text

    inbox, deliveries = await _counts(execution_id=execution_id, event_type=status)
    assert inbox == 0, "a rejected caller must not be able to claim an inbox key"
    assert deliveries == 0, "nor to write a forensic row"


# --- 2. the forged forwarded header (D-27's real_ip point) --------------------


async def test_a_forged_forwarded_header_from_an_untrusted_peer_does_not_get_through() -> None:
    """THE test in this file. `CF-Connecting-IP` is a plain request header: anyone can
    type it. If the receiver believed it unconditionally, the allowlist would be a
    one-line bypass — `curl -H 'CF-Connecting-IP: <engine ip>'` and every downstream
    guarantee (dedupe, metering, the tenant a call gets attributed to) is attacker
    input.

    So the rule is: a forwarded header is believed ONLY when the immediate peer is
    itself a trusted proxy. Here the peer is a stranger, so the header is ignored and
    the real peer decides — 401 both times.
    """
    for header in ("CF-Connecting-IP", "X-Forwarded-For"):
        execution_id, status, body = _event()

        async with _client(ATTACKER_IP) as http:
            response = await http.post(HOOK, json=body, headers={header: ENGINE_EGRESS_IP})

        assert response.status_code == 401, f"{header} was believed from an untrusted peer"
        assert response.json()["kind"] == "auth"

        inbox, deliveries = await _counts(execution_id=execution_id, event_type=status)
        assert (inbox, deliveries) == (0, 0), f"a spoofed {header} left a row behind"

    # The chained form too: an attacker prepending the engine's IP to a list is the
    # same attack wearing a hat, and `client_ip` takes the FIRST element.
    execution_id, status, body = _event()
    async with _client(ATTACKER_IP) as http:
        chained = await http.post(
            HOOK, json=body, headers={"X-Forwarded-For": f"{ENGINE_EGRESS_IP}, {ATTACKER_IP}"}
        )
    assert chained.status_code == 401
    assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)


# --- 3. the other half: a real edge proxy must still work ---------------------


async def test_a_trusted_proxy_forwarded_header_is_honoured() -> None:
    """The mirror of the test above, and the reason it cannot simply be "ignore all
    forwarded headers": in production the socket is opened by our own nginx (or
    Cloudflare), so `request.client.host` is ALWAYS an edge address. Without honouring
    the forwarded header from a trusted peer the allowlist would reject 100% of real
    engine traffic — a total outage with no error anyone would think to look for.

    Two halves, both required:
      - trusted peer + allowlisted forwarded IP  -> accepted;
      - trusted peer + NON-allowlisted forwarded IP -> still rejected, i.e. being behind
        the edge is not itself a credential.
    """
    execution_id, status, body = _event()
    async with _client(EDGE_PROXY_IP) as http:
        accepted = await http.post(HOOK, json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP})
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)

    other_id, other_status, other_body = _event()
    async with _client(EDGE_PROXY_IP) as http:
        relayed_stranger = await http.post(
            HOOK, json=other_body, headers={"CF-Connecting-IP": ATTACKER_IP}
        )
    assert relayed_stranger.status_code == 401, "the edge relays traffic, it does not vouch for it"
    assert await _counts(execution_id=other_id, event_type=other_status) == (0, 0)

    # And a trusted peer with no forwarded header at all falls back to the peer itself,
    # which is not on the allowlist. Nothing about being local is a credential either.
    bare_id, bare_status, bare_body = _event()
    async with _client(EDGE_PROXY_IP) as http:
        bare = await http.post(HOOK, json=bare_body)
    assert bare.status_code == 401
    assert await _counts(execution_id=bare_id, event_type=bare_status) == (0, 0)


# --- 4. dedupe ----------------------------------------------------------------


async def test_a_repeated_delivery_yields_one_inbox_row_and_one_job(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`usage_events` is append-only (hard rule 4), so a call processed twice is a
    double charge that no UPDATE can undo. The execution id is therefore the unit of
    work, and it must collapse deliveries at BOTH layers:

      - Redis SETNX, the fast path, so a burst never touches Postgres;
      - the inbox claim, the durable truth, which is what still holds after a Redis
        flush or a Redis outage.

    The third delivery below runs with the fast-path key deleted precisely to exercise
    that second layer on its own — the layer that actually carries the guarantee.
    """
    enqueued: list[str | None] = []
    real_enqueue = webhook_routes.enqueue

    async def _spy(job: str, *args: Any, **kwargs: Any) -> str | None:
        enqueued.append(str(kwargs.get("job_id")))
        return await real_enqueue(job, *args, **kwargs)

    monkeypatch.setattr(webhook_routes, "enqueue", _spy)

    execution_id, status, body = _event()
    headers = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

    async with _client(EDGE_PROXY_IP) as http:
        first = await http.post(HOOK, json=body, headers=headers)
        second = await http.post(HOOK, json=body, headers=headers)

    assert first.json()["status"] == "accepted"
    assert second.json()["status"] == "duplicate", "the Redis fast path must absorb a retry"

    # Now take the fast path away and prove the durable claim stands on its own.
    fast_path_key = f"calevate:wh:bolna:{execution_id}:{body_hash(body)[:16]}"
    await get_redis().delete(fast_path_key)

    async with _client(EDGE_PROXY_IP) as http:
        third = await http.post(HOOK, json=body, headers=headers)
    assert third.json()["status"] == "duplicate", "the inbox claim is the durable dedupe"

    inbox, deliveries = await _counts(execution_id=execution_id, event_type=status)
    assert inbox == 1, "one execution id is one inbox row, however many deliveries arrive"
    assert deliveries == 1, "and one forensic row, so replays do not inflate the trail"
    assert len(enqueued) == 1, "a duplicate must never reach the queue at all"

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, duplicate_count FROM webhook_inbox_events "
                    "WHERE provider = 'bolna' AND event_key = :k"
                ),
                {"k": execution_id},
            )
        ).first()
    assert row is not None
    assert row[0] == "enqueued"
    assert row[1] >= 1, "the retry is counted, not silently swallowed"


# --- 5. the ack is an ack, not the pipeline -----------------------------------


async def test_the_ack_is_measured_and_carries_no_pipeline_work() -> None:
    """Hard rule 3 puts a number on this path — ack < 500ms — because Bolna's delivery
    is at-most-once with no retries: a slow receiver does not get retried, it LOSES the
    call. `X-Ack-Ms` is how a regression shows up as a number rather than as a mystery.

    Deliberately NOT asserted: a hard millisecond bound. A CI box under load would make
    that flaky, and flaky latency assertions get deleted, which is worse than not having
    them. What IS asserted is the structural property that makes the budget achievable —
    the handler returned before any domain work happened. The tenant here is fully
    resolvable (org + agent + routing row all exist), so an empty `calls` table is
    evidence of deferral rather than of a lookup that could not have succeeded.
    """
    agent_ref = f"bolna_agent_{uuid.uuid4().hex[:8]}"
    tenant_id = await _seed_route(agent_ref)
    execution_id, status, body = _event()
    body["agent_id"] = agent_ref

    async with _client(EDGE_PROXY_IP) as http:
        response = await http.post(HOOK, json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP})

    assert response.status_code == 202, response.text
    # NOTE: the header is set on the accepted path only; the `duplicate` and `ignored`
    # early returns record the metric but ship no header. Widen this if that changes.
    assert "X-Ack-Ms" in response.headers, "hard rule 3's budget must be observable per request"
    ack_ms = float(response.headers["X-Ack-Ms"])  # must parse as a number
    assert ack_ms >= 0

    # Queried under the tenant's own RLS context on purpose: an untenanted session sees
    # zero tenant rows by policy, which would make this assertion vacuous.
    async with tenant_session(tenant_id) as session:
        calls = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
        leads = (
            await session.execute(
                text("SELECT count(*) FROM leads WHERE tenant_id = :t"), {"t": tenant_id}
            )
        ).scalar()
    assert calls == 0, "the receiver must not create a call row; the worker does that"
    assert leads == 0, "and certainly not a lead"

    inbox, deliveries = await _counts(execution_id=execution_id, event_type=status)
    assert (inbox, deliveries) == (1, 1), "exactly the two minimal infra rules-3 allows"


# --- 6. an unresolvable event is dropped, not fatal ---------------------------


async def test_an_unknown_engine_agent_ref_is_still_acked() -> None:
    """The resolver may never invent a tenant (hard rule 1), so an `engine_agent_ref`
    that maps to no routing row has exactly one correct outcome: record the event and
    drop it. What it must NOT do is 500.

    The receiver does not resolve tenants at all, and that is the point — a 500 here
    would make an offboarded agent, a stale engine-side config or a typo look like an
    outage to the vendor, and Bolna does not retry. Every OTHER call arriving in that
    window would be lost with it.
    """
    orphan_ref = f"bolna_agent_nobody_{uuid.uuid4().hex[:8]}"
    execution_id, status, body = _event()
    body["agent_id"] = orphan_ref

    async with untenanted_session() as session:
        routes = (
            await session.execute(
                text("SELECT count(*) FROM engine_agent_routes WHERE engine_agent_ref = :r"),
                {"r": orphan_ref},
            )
        ).scalar()
    assert routes == 0, "the premise: this ref resolves to nobody"

    async with _client(EDGE_PROXY_IP) as http:
        response = await http.post(HOOK, json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP})

    assert response.status_code == 202, response.text
    assert response.json()["status"] == "accepted"

    inbox, deliveries = await _counts(execution_id=execution_id, event_type=status)
    assert (inbox, deliveries) == (1, 1), "an unroutable event is still evidence; keep it"

    # A payload with no execution id at all is the same doctrine one step further: it
    # cannot be keyed, so it cannot be deduped — acked and left to the poller (D-31).
    async with _client(EDGE_PROXY_IP) as http:
        unkeyable = await http.post(
            HOOK, json={"status": "completed"}, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP}
        )
    assert unkeyable.status_code == 202
    assert unkeyable.json()["status"] == "ignored"
