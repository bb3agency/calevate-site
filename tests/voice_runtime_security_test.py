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

- **The allowlist is a SETTING, and it is the only one.** `BOLNA_WEBHOOK_SOURCE_IPS`
  is what both `engine_intake.verify_source` and `BolnaEngine.verify_webhook` resolve
  through (`calevate_shared.config.bolna_source_ips`), so the `source_ip_allowlist`
  fixture in `conftest.py` sets the environment variable. It used to patch a module
  constant here while the adapter matched a different hardcoded one — two allowlists
  answering one question, agreeing only until an operator used the documented recovery
  path. `engine_audit_test.py` §2e is what holds them together now.
- **The peer IP is `scope["client"]`**, which `httpx.ASGITransport` lets us set. That is
  exactly the TCP peer nginx or Cloudflare would present, so `_client(ip)` below is a
  faithful stand-in for "who actually opened the socket".
"""

from __future__ import annotations

import asyncio
import logging
import secrets
import time
import urllib.parse
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import replace
from typing import Any

import pytest
import webhook_routes
from apps.api.core.errors import ProblemError
from apps.api.core.redis import get_redis
from apps.api.core.settings import get_settings
from apps.api.db.session import get_engine, tenant_session, untenanted_session
from apps.api.reliability.service import InboxClaim, body_hash
from calevate_shared.client_address import client_ip, is_trusted_peer
from engine_intake import KNOWN_ENGINES, execution_key, verify_source
from httpx import ASGITransport, AsyncClient
from main import app as voice_app  # apps/voice-runtime is on the pytest path (D-18)
from sqlalchemy import event, text

# RFC 5737 documentation ranges: unroutable, so a copy-paste of any of these into a real
# config is inert rather than dangerous.
ENGINE_EGRESS_IP = "198.51.100.7"  # stands in for Bolna's static egress IP
ATTACKER_IP = "203.0.113.9"  # some box on the internet that found the URL
EDGE_PROXY_IP = "127.0.0.1"  # inside TRUSTED_PROXY_CIDRS — our own nginx

HOOK = "/hooks/v1/engine/bolna"


@pytest.fixture(autouse=True)
def _allowlist(source_ip_allowlist: Callable[..., None]) -> None:
    """Point the allowlist at a documentation IP for the duration of each test.

    Through the SETTING, which is what `verify_source` resolves at call time — and it
    keeps these tests from encoding a vendor's current egress IP, a value that changes
    without our permission.
    """
    source_ip_allowlist(ENGINE_EGRESS_IP)


def _client(peer_ip: str, *, tolerate_crash: bool = False) -> AsyncClient:
    """An ASGI client whose immediate TCP peer is `peer_ip`.

    `tolerate_crash=True` turns an unhandled handler exception into the 500 the real
    server would send instead of re-raising it into the test. Starlette's
    `ServerErrorMiddleware` sends the problem+json AND re-raises so uvicorn can log
    the traceback; `raise_app_exceptions=False` keeps the first half and drops the
    second, which is the half a webhook caller actually experiences. Used only by the
    hostile-payload tests, so an unexpected crash anywhere else still surfaces as a
    traceback rather than as a quiet 500.
    """
    return AsyncClient(
        transport=ASGITransport(
            app=voice_app, client=(peer_ip, 44444), raise_app_exceptions=not tolerate_crash
        ),
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
    so `untenanted_session` sees them honestly.

    The inbox key is `{execution_id}:{raw_status}`, because the unit of work is the
    TRANSITION, not the execution: Bolna fires one webhook per status change and the
    ARQ job id is keyed the same way. Counting by execution id alone would report the
    row for `queued` while asserting about `completed`.
    """
    async with untenanted_session() as session:
        inbox = (
            await session.execute(
                text(
                    "SELECT count(*) FROM webhook_inbox_events "
                    "WHERE provider = :p AND event_key = :k"
                ),
                {"p": engine, "k": f"{execution_id}:{event_type}"},
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
                "INSERT INTO agents (id, tenant_id, name, direction, disclosure_line, "
                "ai_disclosure_line, recording_notice_line, status, engine, engine_agent_ref, "
                "created_at, updated_at) VALUES (:id, :tid, 'Receptionist', 'inbound', 'Idi AI "
                "assistant. Call record avutundi.', 'Idi AI assistant. Call record avutundi.', "
                "'This call is being recorded.', 'live', 'bolna', :ref, now(), now())"
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
    # same attack wearing a hat.
    execution_id, status, body = _event()
    async with _client(ATTACKER_IP) as http:
        chained = await http.post(
            HOOK, json=body, headers={"X-Forwarded-For": f"{ENGINE_EGRESS_IP}, {ATTACKER_IP}"}
        )
    assert chained.status_code == 401
    assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)


# --- 2b. the leftmost X-Forwarded-For entry is not an address, it is a wish ----


async def test_a_leftmost_forwarded_for_entry_is_never_believed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The spoofing test. `X-Forwarded-For` is APPENDED to by every hop, so entry 0 is
    whatever the original caller typed — MDN's rule is that a security control may only
    use addresses "added by a trusted proxy", and this receiver's control is the whole
    authenticity story for an unsigned engine (D-31).

    The dangerous shape is not the untrusted-peer one above (test 2), which the old code
    also refused. It is this one: the request DOES arrive through a trusted hop — exactly
    as every genuine request does — carrying a header the hop did not write. `client_ip`
    used to prefer `CF-Connecting-IP` and fall back to XFF's leftmost entry, so anything
    that could reach nginx without Cloudflare setting the header (an on-box process, a
    relaxed origin lock, a future edge) could name its own source IP and be believed.

    Both environments are asserted, because "the fallback is unreachable in prod" is the
    argument that made the old code look safe.
    """
    settings = get_settings()
    for env in ("prod", "local"):
        monkeypatch.setattr(settings, "app_env", env)
        execution_id, status, body = _event()
        async with _client(EDGE_PROXY_IP) as http:
            forged = await http.post(
                HOOK,
                json=body,
                headers={"X-Forwarded-For": f"{ENGINE_EGRESS_IP}, {ATTACKER_IP}"},
            )
        assert forged.status_code == 401, (
            f"[{env}] an X-Forwarded-For entry no trusted hop wrote must never clear the allowlist"
        )
        assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)

        # And the single-entry form, which is what a naive leftmost parse reads as "the
        # client" without there being a list to look suspicious.
        execution_id, status, body = _event()
        async with _client(EDGE_PROXY_IP) as http:
            single = await http.post(HOOK, json=body, headers={"X-Forwarded-For": ENGINE_EGRESS_IP})
        assert single.status_code == 401, f"[{env}] XFF is not read at all"
        assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)


# --- 2c. outside local, an unestablished client IP is a refusal ---------------


async def test_outside_local_a_missing_or_unusable_edge_header_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed. In staging/prod every request arrives Cloudflare -> nginx -> here and
    nginx writes `CF-Connecting-IP` from the real-ip-restored peer (DEPLOYMENT §5,
    `infra/nginx/snippets/calevate-proxy.conf`). If that header is absent, blank or not a
    single literal IP, the deployment's one promise about who is calling has been broken —
    by a stripped header, a missing `real_ip` block, or a path into the container that does
    not pass through nginx at all.

    The only acceptable answer is 401. Attributing the request to the peer, to a default,
    or to anything the caller supplied would turn an unsigned engine's sole authenticity
    control into "we could not tell, so we accepted it". The cost of refusing is bounded
    and known: the 10-minute reconciliation poller is the guarantee of record (D-31).
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "staging")

    for label, headers in (
        ("absent", {}),
        ("blank", {"CF-Connecting-IP": "   "}),
        ("not an ip", {"CF-Connecting-IP": "not-an-ip"}),
        # CF sends exactly one address; a list here means something else wrote it.
        ("a list", {"CF-Connecting-IP": f"{ENGINE_EGRESS_IP}, {ATTACKER_IP}"}),
        ("host:port", {"CF-Connecting-IP": f"{ENGINE_EGRESS_IP}:443"}),
    ):
        execution_id, status, body = _event()
        async with _client(EDGE_PROXY_IP) as http:
            response = await http.post(HOOK, json=body, headers=headers)
        assert response.status_code == 401, f"{label}: an unestablished client IP must refuse"
        assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)

    # A peer that is not a trusted proxy cannot be the caller either: outside local,
    # nothing reaches this container except through nginx on the bridge network.
    execution_id, status, body = _event()
    async with _client(ENGINE_EGRESS_IP) as http:
        direct = await http.post(HOOK, json=body)
    assert direct.status_code == 401, (
        "a direct connection is a broken perimeter, not a credential — even from the "
        "engine's own address"
    )
    assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)

    # The genuine Cloudflare shape still gets in, which is the half that keeps this from
    # being a very secure outage.
    execution_id, status, body = _event()
    async with _client(EDGE_PROXY_IP) as http:
        genuine = await http.post(
            HOOK,
            json=body,
            # As nginx sends it: the edge header set, XFF appended and irrelevant.
            headers={
                "CF-Connecting-IP": ENGINE_EGRESS_IP,
                "X-Forwarded-For": f"{ATTACKER_IP}, {ENGINE_EGRESS_IP}",
            },
        )
    assert genuine.status_code == 202, genuine.text
    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)


async def test_the_local_path_still_works_without_an_edge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`local` is the one environment with no edge in front, so the socket peer IS the
    caller and a header from a loopback peer is a developer's own curl, not a stranger's
    claim (D-49 made `APP_ENV` explicit precisely so this branch cannot be reached by a
    production deploy that merely forgot to set the variable).

    Asserted so nobody hardens this into a state where the offline pipeline cannot be
    exercised — the pressure to add a "just for testing" bypass in production comes from
    exactly that.
    """
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "local")

    execution_id, status, body = _event()
    async with _client(EDGE_PROXY_IP) as http:
        accepted = await http.post(HOOK, json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP})
    assert accepted.status_code == 202, accepted.text
    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)

    # A peer that IS the allowlisted address needs no header at all locally.
    execution_id, status, body = _event()
    async with _client(ENGINE_EGRESS_IP) as http:
        by_peer = await http.post(HOOK, json=body)
    assert by_peer.status_code == 202, by_peer.text
    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)


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
    #
    # The key is the TRANSITION — `{engine}:{execution_id}:{raw_status}`, the same unit of
    # work the inbox claims and `job_id_for` keys the job on. It used to carry a digest of
    # the delivery body as well, which made the cache and the claim disagree about what a
    # duplicate is: a replay with one byte changed missed the cache and opened a Postgres
    # transaction every time (D-147).
    fast_path_key = f"calevate:wh:bolna:{execution_id}:{status}"
    assert await get_redis().delete(fast_path_key) == 1, (
        "the key the receiver wrote is not the one this test knows about"
    )

    async with _client(EDGE_PROXY_IP) as http:
        third = await http.post(HOOK, json=body, headers=headers)
    assert third.json()["status"] == "duplicate", "the inbox claim is the durable dedupe"

    inbox, deliveries = await _counts(execution_id=execution_id, event_type=status)
    assert inbox == 1, "one TRANSITION is one inbox row, however many deliveries arrive"
    assert deliveries == 1, "and one forensic row, so replays do not inflate the trail"
    assert len(enqueued) == 1, "a duplicate must never reach the queue at all"

    async with untenanted_session() as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, duplicate_count FROM webhook_inbox_events "
                    "WHERE provider = 'bolna' AND event_key = :k"
                ),
                {"k": f"{execution_id}:{status}"},
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


# --- 7. the transition is the unit of work ------------------------------------


async def test_each_status_transition_reaches_the_queue_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One call produces several webhooks — queued, then in-progress, then completed —
    all carrying the same execution id (TRD §5).

    `completed` is the ONLY one that carries cost, recording and transcript, so if the
    inbox dedupes on the execution id alone, the first transition claims the key and
    `completed` comes back `duplicate` and never reaches the queue. The post-call
    pipeline then never runs from a webhook at all: every call waits for the 10-minute
    reconciliation poller, and FLOWS §3.6's "lead + summary visible < 2 min after
    hangup" cannot be met. `pipeline.py` returning `awaiting_completion:{raw_status}`
    says out loud that it expects to be called once per transition.

    So: distinct transitions each enqueue exactly once, and a REPEAT of a transition
    still does not.
    """
    execution_id = f"exec_{uuid.uuid4().hex[:12]}"
    headers = {"CF-Connecting-IP": ENGINE_EGRESS_IP}
    transitions = [f"{name}-{uuid.uuid4().hex[:6]}" for name in ("queued", "ringing", "completed")]

    enqueued: list[str | None] = []
    real_enqueue = webhook_routes.enqueue

    async def _spy(job: str, *args: Any, **kwargs: Any) -> str | None:
        enqueued.append(str(kwargs.get("job_id")))
        return await real_enqueue(job, *args, **kwargs)

    monkeypatch.setattr(webhook_routes, "enqueue", _spy)

    async with _client(EDGE_PROXY_IP) as http:
        for raw_status in transitions:
            body = {"execution_id": execution_id, "status": raw_status}
            first = await http.post(HOOK, json=body, headers=headers)
            assert first.json()["status"] == "accepted", (
                f"{raw_status} was absorbed as a duplicate of an earlier transition"
            )
            # The same transition delivered twice is still one job.
            repeat = await http.post(HOOK, json=body, headers=headers)
            assert repeat.json()["status"] == "duplicate"

    assert len(enqueued) == len(transitions), (
        "every transition must reach the queue exactly once — the completed one most "
        f"of all: {enqueued}"
    )
    for raw_status in transitions:
        inbox, _deliveries = await _counts(execution_id=execution_id, event_type=raw_status)
        assert inbox == 1, f"{raw_status} should own exactly one inbox row"


# --- 8. the dedupe key is attacker-shaped input ------------------------------


@pytest.mark.parametrize(
    ("case", "body_of"),
    [
        # A btree index tuple caps at 2704 bytes. `event_key` is
        # `{execution_id}:{raw_status}` under a UNIQUE (provider, event_key) index, so a
        # long-enough field in EITHER position is `index row size ... exceeds btree
        # version 4 maximum` — an unhandled DataError, i.e. a 500.
        ("long status", lambda t: {"execution_id": f"exec_{t}", "status": secrets.token_hex(2000)}),
        (
            "long execution id",
            lambda t: {"execution_id": secrets.token_hex(2000), "status": "done"},
        ),
        # psycopg refuses a NUL in a text parameter outright. One byte, no size needed.
        ("nul in status", lambda t: {"execution_id": f"exec_{t}", "status": "comp\x00leted"}),
        ("nul in execution id", lambda t: {"execution_id": f"exec_{t}\x00", "status": "completed"}),
    ],
)
async def test_a_hostile_dedupe_key_is_refused_deliberately_not_with_a_500(
    case: str, body_of: Any
) -> None:
    """`webhook_routes`' own contract (docstring item 5) is that every request has a
    CHOSEN answer and "none of them is a 500". The two keyable fields break that promise:
    both are copied verbatim out of the payload into `webhook_inbox_events.event_key`,
    which is covered by a UNIQUE index, and neither is bounded or checked.

    Why a 500 here is not cosmetic. Bolna's delivery is at-most-once with no retry, so a
    5xx does not get redelivered — it LOSES the call until the 10-minute poller. And the
    receiver has no per-request isolation from its own crashes: the same POST that kills
    this request is indistinguishable, from the vendor's side, from the receiver being
    down for the real call arriving in the same second. An event we cannot key already
    has a documented answer three lines further up — ack it, alert `webhook_unkeyable`,
    let the poller be the truth (D-31). A key we cannot STORE is the same situation and
    deserves the same answer.

    Reachability, stated honestly: on a bolna deployment the source-IP allowlist stands
    in front of this, so the hostile sender is the vendor (or anything that gets to
    source-spoof past the edge). On a `fake`-engine deployment `verify_source` checks
    nothing at all, and this endpoint is reachable by anyone who learns the URL — which
    is exactly the configuration every developer machine and CI box runs.
    """
    token = uuid.uuid4().hex[:12]
    body = body_of(token)

    async with _client(EDGE_PROXY_IP, tolerate_crash=True) as http:
        response = await http.post(HOOK, json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP})

    assert response.status_code == 202, (
        f"{case}: a payload we cannot store as a key must be acked and dropped, not 500 — "
        f"got {response.status_code} {response.text[:200]}"
    )
    assert response.json()["status"] == "ignored"

    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT count(*) FROM webhook_inbox_events WHERE event_key LIKE :k"),
                {"k": f"%{token}%"},
            )
        ).scalar()
    assert rows == 0, f"{case}: an unkeyable event must not leave an inbox row"


async def test_an_oversized_agent_ref_does_not_poison_the_job_payload() -> None:
    """`engine_agent_ref` is not part of the dedupe key, so it cannot break the index —
    but it IS copied into the ARQ job args, where the worker uses it to resolve a tenant.

    A megabyte of it is a megabyte in Redis per delivery for a value that can only ever
    resolve to nobody. The event itself is still real (the execution id is fine), so the
    right answer is to keep the event and drop the ref: the worker's authenticated Get
    Execution is the truth about which agent this was (D-31), the payload was only ever
    a hint.
    """
    execution_id, status, body = _event()
    body["agent_id"] = "a" * 20_000

    captured: list[dict[str, Any]] = []
    real_enqueue = webhook_routes.enqueue

    async def _spy(job: str, *args: Any, **kwargs: Any) -> str | None:
        captured.append(dict(args[0]) if args else {})
        return await real_enqueue(job, *args, **kwargs)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(webhook_routes, "enqueue", _spy)
        async with _client(EDGE_PROXY_IP) as http:
            response = await http.post(
                HOOK, json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP}
            )

    assert response.status_code == 202
    assert response.json()["status"] == "accepted", "the event is real; only the ref is junk"
    assert captured, "the job must still be enqueued"
    assert captured[0]["engine_agent_ref"] is None, (
        "an implausible agent ref belongs in the bin, not in the job payload"
    )
    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)


# --- 9. the same execution id with DIFFERENT content --------------------------


async def test_the_same_transition_with_a_different_body_is_deduped_not_conflicted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The inbox answers 409 `webhook_payload_mismatch` when a key it already holds
    arrives with a different `payload_hash`. This receiver deliberately puts that beyond
    reach: it hashes {engine, execution_id, raw_status} — a pure function of the key
    itself — so no BODY variation can produce a mismatch.

    That is the right call and this test pins it, because the alternative is worse in
    both directions. At an unsigned endpoint (D-31) the caller controls the whole body,
    so a body hash is not evidence of authenticity; and two honest deliveries of the same
    transition genuinely can differ in body (a fuller payload the second time), which
    would fire a spoofing alarm on healthy traffic. An alarm that cries wolf is an alarm
    nobody reads.

    So the doctored replay is not refused — it is DEDUPED, which is the outcome that
    actually matters: one inbox row, one forensic row, one job, and none of the attacker's
    content anywhere near a worker.
    """
    execution_id, status, body = _event()
    headers = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

    enqueued: list[dict[str, Any]] = []
    real_enqueue = webhook_routes.enqueue

    async def _spy(job: str, *args: Any, **kwargs: Any) -> str | None:
        enqueued.append(dict(args[0]) if args else {})
        return await real_enqueue(job, *args, **kwargs)

    monkeypatch.setattr(webhook_routes, "enqueue", _spy)

    doctored = {**body, "agent_id": "attacker_agent", "total_cost": 999999, "extra": "x" * 50}

    async with _client(EDGE_PROXY_IP) as http:
        first = await http.post(HOOK, json=body, headers=headers)
        # THE FAST-PATH KEY IS DELETED ON PURPOSE, so the second delivery reaches the
        # DURABLE claim — the layer under test. It used to reach it by accident, because
        # the Redis key carried a digest of the delivery body and a doctored body missed
        # the cache. That was itself the defect (D-147): the cache and the claim disagreed
        # about what a duplicate is, so any body-varying replay opened a Postgres
        # transaction. Now the key is the transition, the cache absorbs the replay — and
        # this test would pass without ever exercising the claim if it did not do this.
        deleted = await get_redis().delete(f"calevate:wh:bolna:{execution_id}:{status}")
        assert deleted == 1, "the fast path did not settle the first delivery"
        second = await http.post(HOOK, json=doctored, headers=headers)

    assert first.json()["status"] == "accepted"
    assert second.status_code == 202, "a doctored replay must not 409 on a body difference"
    assert second.json()["status"] == "duplicate"

    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)
    assert len(enqueued) == 1, "the doctored body must not reach the queue"
    assert enqueued[0]["engine_agent_ref"] != "attacker_agent"


async def test_an_inbox_payload_mismatch_surfaces_as_409_not_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of the previous test: unreachable from a body difference is not the
    same as unreachable full stop. `webhook_inbox_events` is shared — the Clerk receiver,
    the payments receiver and the lead-ingest endpoint all claim keys in it — so a
    provider/key collision from anywhere, or a future change to what this receiver hashes,
    can still raise `ProblemError.conflict`.

    It must leave as a 409 problem+json. It is raised INSIDE the `async with
    untenanted_session()` block, so a handler that swallowed it (or let it become a 500)
    would either lose the signal entirely or tell an at-most-once vendor "we are broken"
    about an event that is in fact already recorded.
    """
    execution_id, status, body = _event()

    async def _mismatch(*_args: Any, **_kwargs: Any) -> InboxClaim:
        raise ProblemError.conflict(
            "webhook_payload_mismatch",
            "This event id was already received with different content.",
        )

    monkeypatch.setattr(webhook_routes, "claim_inbox_event", _mismatch)

    async with _client(EDGE_PROXY_IP) as http:
        response = await http.post(HOOK, json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP})

    assert response.status_code == 409, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    problem = response.json()
    assert problem["kind"] == "conflict"
    assert problem["type"].endswith("/webhook_payload_mismatch")
    assert problem["retryable"] is False

    # Nothing was written and nothing was remembered: a conflicted claim rolls back with
    # the transaction, and the fast-path key is only ever written past the commit.
    assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)
    assert await get_redis().get(f"calevate:wh:bolna:{execution_id}:{body_hash(body)[:16]}") is None


# --- 10. the fake engine's open door stays shut where it matters --------------


async def test_the_fake_engine_hook_is_closed_on_a_deployment_that_runs_bolna(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/hooks/v1/engine/fake` verifies NOTHING by design — that is how the pipeline runs
    offline. The route table is identical in every environment, so the only thing standing
    between a stranger and an inbox claim on a prod box is `settings.engine != "fake"`.

    This test is the guard on that one comparison. It runs from an IP on no allowlist,
    which is precisely the caller the gate exists for.
    """
    settings = get_settings()
    execution_id, status, body = _event()

    monkeypatch.setattr(settings, "engine", "bolna")
    async with _client(ATTACKER_IP) as http:
        refused = await http.post("/hooks/v1/engine/fake", json=body)
    assert refused.status_code == 401, "the fake hook must be shut on a bolna deployment"
    assert await _counts(execution_id=execution_id, event_type=status, engine="fake") == (0, 0)

    # And the mirror, so the offline pipeline is proven to still work rather than merely
    # assumed: where `fake` IS the engine, the same request is accepted.
    monkeypatch.setattr(settings, "engine", "fake")
    async with _client(ATTACKER_IP) as http:
        accepted = await http.post("/hooks/v1/engine/fake", json=body)
    assert accepted.status_code == 202, accepted.text
    assert accepted.json()["status"] == "accepted"
    assert await _counts(execution_id=execution_id, event_type=status, engine="fake") == (1, 1)


# --- 11. a peer the socket cannot name ----------------------------------------


async def test_a_delivery_whose_peer_we_cannot_see_is_refused_however_good_its_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No peer address, no trusted hop — and therefore no caller we can vouch for.

    ASGI omits `client` when the connection has no address to report: a unix-socket
    upstream is the shape that does it in production (uvicorn sets `client` to None on a
    UDS), and `is_trusted_peer` is then asked about the empty string. It must answer
    False rather than raise, because the alternative on this path is a 500 out of the
    authenticity check on the only unauthenticated endpoint we expose.

    The header is deliberately PERFECT here — `CF-Connecting-IP` naming the allowlisted
    egress address, exactly what a genuine delivery carries. It still must not get in:
    the header means something only because a trusted hop wrote it, and a connection
    with no visible peer is a connection where nothing proved that hop exists. Believing
    it would turn the header into a password that anyone who read DEPLOYMENT §5 knows.
    """
    monkeypatch.setattr(get_settings(), "app_env", "staging")

    # The unit answer first, so a regression says which half moved.
    assert client_ip(None, {"cf-connecting-ip": ENGINE_EGRESS_IP}, app_env="staging") is None
    assert is_trusted_peer("") is False, "an unparseable peer is not a trusted proxy"
    assert is_trusted_peer("not-an-ip") is False

    execution_id, status, body = _event()
    peerless = AsyncClient(
        transport=ASGITransport(app=voice_app, client=None),
        base_url="http://runtime",
    )
    async with peerless as http:
        response = await http.post(HOOK, json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP})

    assert response.status_code == 401, response.text
    assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)


# --- 12. the engine name decides the METHOD, and two of them are refusals ------


def test_an_engine_that_signs_is_refused_until_a_verifier_exists_not_waved_through() -> None:
    """`WEBHOOK_AUTH_BY_ENGINE` is the one table this receiver reads (D-93), and it now
    carries an engine that SIGNS — Cartesia Line, whose scheme is unsourced.

    The failure this pins is the tempting one: an engine whose declared method is `hmac`
    arriving at a receiver that implements no signature check, and the check falling
    through to "well, the IP looked fine" or to a bare accept. Either would record a
    delivery we never authenticated as one we did — `signature_valid` in the forensic
    row is derived from `verdict.method == "hmac"`, so a wave-through does not merely
    accept a forgery, it FILES it as signed.

    So the verdict must be a refusal, and it must say which work is missing rather than
    which caller was wrong: "signature verification not implemented" is a message about
    us, and the operator reading it needs to know the deliveries are being dropped
    deliberately (the poller is still the guarantee of record, D-31).
    """
    verdict = verify_source("cartesia", ENGINE_EGRESS_IP)
    assert verdict.ok is False
    assert verdict.method == "hmac"
    assert verdict.reason == "signature verification not implemented"

    # The declaration is what makes it hmac — not the engine's name — so the fixture
    # adapter that declares the same method gets the same answer.
    assert verify_source("fake-restricted", ENGINE_EGRESS_IP).ok is False
    # And an allowlisted source address does not rescue it: source-IP evidence is not
    # signature evidence, and treating one as the other is the whole point of the table.
    assert verify_source("cartesia", ENGINE_EGRESS_IP) == verify_source("cartesia", ATTACKER_IP)


def test_an_engine_this_deployment_never_heard_of_is_refused_and_never_labelled() -> None:
    """`{engine}` is a path segment, so on the refusal path it is a stranger's string.

    Two properties, and the second is why the first is not enough. It must REFUSE — an
    engine we do not run has no authenticity story at all, so there is nothing to check
    and nothing to accept. And the string must not reach the metrics pipeline as a
    label: `_refuse` bounds it to `KNOWN_ENGINES` precisely so that anyone who found the
    URL cannot mint unbounded label cardinality and blind the monitoring of the service
    they are probing.
    """
    verdict = verify_source("twilio", ENGINE_EGRESS_IP)
    assert verdict.ok is False
    assert verdict.method == "none"
    assert verdict.reason == "unknown engine"

    assert "twilio" not in KNOWN_ENGINES
    labels: list[str] = []
    # Through a spy METER rather than by patching the module's recorder: which series an
    # ack lands in is now a property of the `AckMeter` the endpoint carries (the receiver's
    # `webhook_ack_ms`, the in-call tool endpoint's `tool_ack_ms`), so the meter is the
    # seam that decides and therefore the seam a test must drive.
    spy = replace(
        webhook_routes.WEBHOOK_ACK,
        record=lambda elapsed, *, provider: labels.append(provider),
    )
    webhook_routes._refuse(time.perf_counter(), "twilio", meter=spy)
    webhook_routes._refuse(time.perf_counter(), "bolna", meter=spy)
    assert labels == ["unknown", "bolna"], "a stranger's engine name must not become a label"


async def test_a_strangers_engine_name_reaches_no_alert_field_either(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The half the clause above measured and the code did not (D-243).

    `_refuse` bounds the value before it becomes a METRIC label and spends a paragraph on
    why. The `alert()` on the same refusal path — twenty lines above it in
    `webhook_routes._receive`, and its twin in `tool_routes._opt_out` — passed the raw
    path segment through into a structured log field, on EVERY request rather than on
    every fifteenth minute, and into the alert email body. Measured before the fix: 414
    characters of attacker-chosen text with an embedded newline on `calevate.alert`'s
    record, from an unauthenticated caller at any source address, while the metric label
    beside it correctly read `unknown`.

    Both endpoints, because they are the same shape and a fix to one is how the other
    becomes the survivor. Nothing about the OPERATOR's information is lost: the reason
    string and the source address are both still on the record, and a stranger's spelling
    of a name we do not answer for is not evidence about anything.
    """
    hostile = "A" * 400 + "\ninjected: yes"
    quoted = urllib.parse.quote(hostile)
    async with _client(EDGE_PROXY_IP) as http:
        with caplog.at_level(logging.DEBUG):
            webhook = await http.post(
                f"/hooks/v1/engine/{quoted}",
                json={},
                headers={"CF-Connecting-IP": ENGINE_EGRESS_IP},
            )
            tool = await http.post(
                f"/tools/v1/{quoted}/opt-out",
                json={},
                headers={"CF-Connecting-IP": ENGINE_EGRESS_IP},
            )

    assert (webhook.status_code, tool.status_code) == (401, 401)
    rejections = [
        record
        for record in caplog.records
        if getattr(record, "code", None) in {"webhook_source_rejected", "tool_source_rejected"}
    ]
    assert len(rejections) == 2, "both refusals must have alerted; nothing here is measured yet"
    for record in rejections:
        engine = str(getattr(record, "engine", ""))
        assert engine == "unknown", (
            f"{record.code}: an unauthenticated stranger put {len(engine)} characters of "
            "their own text into an alert field — the same value the metric label beside "
            "it bounds, for the same reason"
        )
        assert getattr(record, "detail", None) == "unknown engine", (
            "the operator still needs the REASON; bounding the name must not cost it"
        )


async def test_an_unknown_engine_delivery_is_refused_over_http_and_writes_nothing() -> None:
    """The same verdict through the whole stack, because a unit-level refusal that the
    route does not honour is not a refusal."""
    execution_id, status, body = _event()
    async with _client(EDGE_PROXY_IP) as http:
        response = await http.post(
            "/hooks/v1/engine/twilio", json=body, headers={"CF-Connecting-IP": ENGINE_EGRESS_IP}
        )
    assert response.status_code == 401, response.text
    assert await _counts(execution_id=execution_id, event_type=status, engine="twilio") == (0, 0)


# --- 13. the body cap holds even when the caller declares nothing --------------


async def test_a_body_with_no_declared_length_is_still_cut_off_at_the_cap() -> None:
    """The declared `Content-Length` is a hint from the same stranger who sent the body.

    A chunked POST declares nothing, so the only thing standing between an
    unauthenticated caller and an unbounded allocation on the latency-critical service
    is the running total inside the stream loop. This sends two megabytes with no
    declared length — the length check cannot fire, and the stream must be abandoned at
    the megabyte rather than buffered to the end.

    The answer is the same named 413 the declared case gets: the payload is only a hint
    (D-31), so refusing costs one poller cycle, while buffering whatever arrives costs
    the service. Nothing is claimed and nothing is queued, so the execution is still the
    poller's to recover.
    """

    async def _two_megabytes() -> AsyncIterator[bytes]:
        for _ in range(32):
            yield b"x" * 65_536

    execution_id, status, _ = _event()
    async with _client(EDGE_PROXY_IP) as http:
        response = await http.post(
            HOOK,
            content=_two_megabytes(),
            headers={"CF-Connecting-IP": ENGINE_EGRESS_IP, "content-type": "application/json"},
        )

    assert "content-length" not in {k.lower() for k in response.request.headers}, (
        "this test only means something while the request is chunked"
    )
    assert response.status_code == 413, response.text
    assert response.json()["type"].endswith("/payload_too_large")
    assert "X-Ack-Ms" in response.headers
    assert await _counts(execution_id=execution_id, event_type=status) == (0, 0)


# --- 14. the dedupe key is the TRANSITION, in both layers ----------------------


async def test_a_replay_whose_body_changed_is_absorbed_without_touching_postgres(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The Redis fast path exists so a burst of duplicates never reaches Postgres. It only
    did that for BYTE-IDENTICAL duplicates, and that is not the duplicate population.

    The key used to be `{engine}:{execution_id}:{body_hash(payload)[:16]}` while the inbox
    claim keyed on `{execution_id}:{raw_status}` and hashed only that. `_claim_and_enqueue`
    already argues why the durable hash must be a pure function of the key — "two
    deliveries of the SAME transition can still differ in body (a retry with a fuller
    payload)" — and the cache was left hashing the delivery. So the two layers disagreed
    about what a duplicate IS: every replay whose body moved by one byte missed the cache
    and opened a transaction.

    At an unsigned endpoint (D-31) the caller controls the whole body, so that is a
    Postgres-round-trip amplifier available to anyone past the source check — and on a
    `fake`-engine deployment, which every developer machine and CI box runs, the source
    check is nothing at all.

    Asserted as a COUNT OF STATEMENTS, which is exact on any machine at any speed. Measured
    before the fix: 15 statements for the five replays below. After: zero.

    AND THE DIVERGENCE IS STILL SEEN, which is the half that makes this an improvement
    rather than a trade. The cache absorbs the replay AND counts that its bytes differed
    (`webhook_replay_divergence`), so an unsigned endpoint gains the replay signal it never
    had — the old body-keyed version merely spent three statements arriving at an inbox
    whose `payload_hash` is a pure function of the key and therefore had nothing to say.
    Both directions are asserted: a rewritten replay counts, an identical one does not.
    """
    statements: list[str] = []
    divergences: list[str] = []
    engine = get_engine().sync_engine

    def _on_execute(_conn: Any, _cursor: Any, statement: str, *_rest: Any) -> None:
        statements.append(statement.split(None, 1)[0].upper())

    monkeypatch.setattr(
        webhook_routes,
        "record_webhook_replay_divergence",
        lambda *, provider: divergences.append(provider),
    )

    execution_id, status, body = _event()
    headers = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

    async with _client(EDGE_PROXY_IP) as http:
        first = await http.post(HOOK, json=body, headers=headers)
        assert first.json()["status"] == "accepted", first.text
        event.listen(engine, "before_cursor_execute", _on_execute)
        try:
            # The control first: a byte-identical replay is a duplicate and NOT a
            # divergence. Without it, a counter that fired on every cache hit would pass
            # the assertion below and be worthless.
            identical = await http.post(HOOK, json=body, headers=headers)
            assert identical.json()["status"] == "duplicate", identical.text
            assert divergences == [], "an identical replay is not a divergence"

            for attempt in range(5):
                # One ignored field, a different value each time — the cheapest possible
                # way to make a replay look like a new delivery to a body-keyed cache.
                replay = await http.post(HOOK, json={**body, "junk": attempt}, headers=headers)
                assert replay.json()["status"] == "duplicate", replay.text
        finally:
            event.remove(engine, "before_cursor_execute", _on_execute)

    assert statements == [], (
        "a settled transition must be answered from Redis however the body varies; these "
        f"replays reached Postgres {len(statements)} times: {statements}"
    )
    assert divergences == ["bolna"] * 5, (
        "each rewritten replay must be counted where it is absorbed; a cache that hides "
        f"the divergence is worse than the round trip it saves: {divergences}"
    )
    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)


async def test_a_padded_execution_id_is_the_same_unit_of_work_not_a_second_one() -> None:
    """`"exec_1 "` and `"exec_1"` are one call, and they must be one inbox row.

    Both fields are concatenated verbatim into `webhook_inbox_events.event_key` and into
    the ARQ job id, so surrounding whitespace used to buy a second unit of work for the
    same transition: two claims, two jobs, and the post-call pipeline running twice on a
    call whose `usage_events` are append-only (hard rule 4 — a double charge there is
    uncorrectable by construction, which is the whole reason the execution id is the unit
    of work).

    `raw_status` was already half-normalised — `extract` lowercases it — and a
    half-normalisation is exactly what leaves this behind. Padding costs an attacker
    nothing to produce at an unsigned endpoint, so stripping is a control, not a courtesy.
    """
    execution_id, status, body = _event()
    headers = {"CF-Connecting-IP": ENGINE_EGRESS_IP}

    async with _client(EDGE_PROXY_IP) as http:
        first = await http.post(HOOK, json=body, headers=headers)
        assert first.json()["status"] == "accepted", first.text
        padded = await http.post(
            HOOK,
            json={"execution_id": f"  {execution_id}\t", "status": f" {status.upper()} "},
            headers=headers,
        )

    assert padded.status_code == 202, padded.text
    assert padded.json()["status"] == "duplicate", (
        "whitespace around a key field bought a second claim on one transition"
    )
    assert padded.json()["execution_id"] == execution_id, "the ack must echo the stored key"
    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)


async def test_the_same_transition_from_many_connections_at_once_enqueues_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The race the fast path cannot cover, run as a race.

    Every dedupe test in this file delivers sequentially, so all of them are satisfied by
    the Redis key alone — the layer that is explicitly NOT the guarantee. Deliveries that
    arrive while the first one's transaction is still open all miss that key (it is written
    past the commit, deliberately) and land on the durable claim together. That is the only
    moment the `ON CONFLICT (provider, event_key) DO NOTHING` in `claim_inbox_event` is
    load-bearing, and a double claim there is a double-metered call.

    Released at one event-loop tick through an `asyncio.Barrier`, for the reason
    `webhook_storm_test.py` records: without it each task reaches its first await before
    the next begins and nothing ever contends.
    """
    enqueued: list[str] = []
    real_enqueue = webhook_routes.enqueue

    async def _spy(job: str, *args: Any, **kwargs: Any) -> str | None:
        enqueued.append(str(kwargs.get("job_id")))
        return await real_enqueue(job, *args, **kwargs)

    monkeypatch.setattr(webhook_routes, "enqueue", _spy)

    execution_id, status, body = _event()
    headers = {"CF-Connecting-IP": ENGINE_EGRESS_IP}
    width = 8
    gate = asyncio.Barrier(width)
    outcomes: list[str] = []

    async def _one() -> None:
        async with _client(EDGE_PROXY_IP) as http:
            await gate.wait()
            response = await http.post(HOOK, json=body, headers=headers)
            assert response.status_code == 202, response.text
            outcomes.append(response.json()["status"])

    async with asyncio.TaskGroup() as group:
        for _ in range(width):
            group.create_task(_one())

    assert sorted(outcomes) == ["accepted"] + ["duplicate"] * (width - 1), outcomes
    assert len(enqueued) == 1, f"a concurrent burst enqueued {len(enqueued)} jobs: {enqueued}"
    assert await _counts(execution_id=execution_id, event_type=status) == (1, 1)


def test_every_spelling_of_the_execution_id_is_tried_not_just_the_first_truthy_one() -> None:
    """The tool payload's shape is an ASSUMPTION about the engine's custom-function
    mechanism (OPERATIONS §2 gate 8), not a verified contract — which is why three
    spellings are accepted at all. The fallback then has to survive the case it exists for.

    It did not. `payload.get("execution_id") or payload.get("id") or payload.get("call_id")`
    stops at the first TRUTHY value and only then checks it is a string, so a vendor that
    numbers its executions in one field and names them in another was answered `unkeyable`
    with a usable key sitting one field to the right. On the webhook path that is a call
    handed to the 10-minute poller; on the TOOL path it is a 422 at a caller who just asked
    to be removed from the list, and there is no poller behind that one.

    Whitespace is stripped rather than rejected for the reason the padded-transition test
    above gives: the value becomes a durable key, and `"exec_1 "` must not be a second unit
    of work. `"   "` is not an id at all and stays unkeyable.
    """
    # The regression: a truthy non-string first, a usable id second.
    assert execution_key({"execution_id": 12345, "call_id": "exec_from_call_id"}) == (
        "exec_from_call_id"
    )
    assert execution_key({"execution_id": {"nested": 1}, "id": "exec_from_id"}) == "exec_from_id"
    # A first field we refuse to STORE also falls through, not just a mistyped one.
    assert execution_key({"execution_id": "bad\x00id", "call_id": "exec_ok"}) == "exec_ok"
    assert execution_key({"execution_id": "e" * 200, "call_id": "exec_ok"}) == "exec_ok"

    # Order is preference, not merely presence.
    three = {"execution_id": "exec_a", "id": "exec_b", "call_id": "exec_c"}
    assert execution_key(three) == "exec_a"
    assert execution_key({"id": "exec_b", "call_id": "exec_c"}) == "exec_b"

    # Trimmed, and nothing else is.
    assert execution_key({"execution_id": "  exec_pad\t"}) == "exec_pad"
    assert execution_key({"execution_id": "exec mid space"}) == "exec mid space"

    # And the shapes that genuinely name nothing.
    for empty in ({}, {"execution_id": ""}, {"execution_id": "   "}, {"execution_id": None}):
        assert execution_key(empty) is None, empty
    assert execution_key({"id": ["exec_a"]}) is None, "a list is not an id"
