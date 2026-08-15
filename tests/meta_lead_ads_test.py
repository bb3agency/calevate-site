"""Native Meta Lead Ads ingest (SURFACES §2b): the receiver, and what it now retrieves.

Three properties are under test, and the first two pull in opposite directions on
purpose:

1. **Nothing unverified gets through.** A forged, absent, or body-swapped
   `X-Hub-Signature-256` writes nothing at all — no inbox row, no lead, no call. The
   forgery cases are the majority of this file because they are the only ones an
   attacker will ever exercise.
2. **What we cannot do is refused OUT LOUD.** Meta's leadgen notification carries no
   answers (`docs` links in `apps/api/ingest/meta.py`); the person's name and phone
   live behind a Graph read that needs a Page access token, and a deployment or a
   CLIENT without one still gets a RECORDED refusal keyed on the `leadgen_id` —
   visible in the activity view, re-claimable — never a silent 200.
3. **A lead we may not call is taken and refused, never called.** The answers now
   arrive, which means the consent question on the client's own form now has an answer,
   and it flows into the SAME gate `ingest_lead` already applied to every other source.

`tests/meta_graph_test.py` holds the vendor half: the request shape, the version pin
and the error-code mapping, driven through httpx's real plumbing.

Scope discipline: other suites hammer the same Postgres. Every tenant here carries a
`meta-` slug and every assertion is scoped to this file's own webhook ids.

Run: uv run pytest -q tests/meta_lead_ads_test.py
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.context import Principal
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.engine import reset_engine_cache
from apps.api.ingest import meta
from apps.api.ingest.recorded import RecordedLeadRetriever
from apps.api.main import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

APP_SECRET = "meta-app-secret-for-tests"

# What Meta's form asked, in the client's own wording. The mapping below translates it.
CONSENT_QUESTION = "may_we_call_you"


@pytest.fixture(autouse=True)
def _daytime(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the compliance gate's clock to 11:00 IST — the gate correctly refuses to
    dial at night, and these tests are not about the calling-hours rule."""
    fixed = datetime(2026, 8, 11, 5, 30, tzinfo=UTC) + timedelta(hours=5, minutes=30)
    monkeypatch.setattr("apps.api.compliance.service.ist_now", lambda: fixed)


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    retriever: meta.LeadRetriever | None,
    *,
    reason: str = meta.NO_RETRIEVER_REASON,
) -> None:
    """Substitute the SELECTOR, which is the only thing any surface consults.

    Not the settings and not a module-level slot: `lead_retrieval_capability` is THE
    selector by design, so a test that replaced anything else would be exercising a
    path production does not take. `retriever=None` is the unconfigured deployment, and
    `reason` says WHICH kind of unconfigured.

    The per-source question is DERIVED from `holds_credential_for` here, exactly as the
    real selector derives it, so a retriever scoped to somebody else's lead source is
    refused by the same ladder production uses rather than by a hardcoded answer.
    """

    def _capability(*, source_id: UUID) -> meta.RetrievalCapability:
        if retriever is None:
            return meta.RetrievalCapability(available=False, reason=reason)
        if not retriever.holds_credential_for(source_id):
            return meta.RetrievalCapability(available=False, reason=meta.NO_TOKEN_REASON)
        return meta.RetrievalCapability(available=True, retriever=retriever)

    monkeypatch.setattr(meta, "lead_retrieval_capability", _capability)


def _retriever(
    *,
    phone: str,
    name: str,
    consent: str | None,
    per_lead: dict[str, list[dict[str, Any]]] | None = None,
    sources: frozenset[UUID] | None = None,
) -> RecordedLeadRetriever:
    """THE SHIPPED second implementation, not a stand-in written for this file.

    `recorded.py` is selectable by config and runs the local dev box; using it here is
    what makes "the seam has two implementations" a fact rather than a claim, and it
    means the fixtures below are Meta's own `field_data` shape rather than our flat map.
    """
    return RecordedLeadRetriever(
        _field_data(phone=phone, name=name, consent=consent), per_lead=per_lead, sources=sources
    )


def _field_data(*, phone: str, name: str, consent: str | None) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = [
        {"name": "full_name", "values": [name]},
        {"name": "phone_number", "values": [phone]},
    ]
    if consent is not None:
        rows.append({"name": CONSENT_QUESTION, "values": [consent]})
    return rows


async def _tenant_with_meta_source(
    *, mapping: dict[str, Any] | None = None, source: str = "meta_lead_ads"
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """(tenant_id, agent_id, webhook_id) with a published outbound agent."""
    reset_engine_cache()
    created = await admin_service.create_organization(
        name="Meta Motors",
        slug=f"meta-{uuid.uuid4().hex[:8]}",
        vertical_template="real_estate",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id, agent_id = created["id"], created["agent_id"]
    webhook_id = uuid.uuid4()
    ref = f"fakeagent_meta_{uuid.uuid4().hex[:8]}"

    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "UPDATE agents SET status = 'live', direction = 'outbound', "
                "engine_agent_ref = :r WHERE id = :a"
            ),
            {"r": ref, "a": agent_id},
        )
        await session.execute(
            text(
                "INSERT INTO inbound_webhooks (id, tenant_id, source, secret_ref, agent_id, "
                "mapping, active, created_at, updated_at) VALUES (:i, :t, :src, :s, :a, "
                "CAST(:m AS jsonb), true, now(), now())"
            ),
            {
                "i": webhook_id,
                "t": tenant_id,
                "src": source,
                "s": APP_SECRET,
                "a": agent_id,
                "m": json.dumps(
                    mapping
                    if mapping is not None
                    else {"phone": "phone_number", "name": "full_name"}
                ),
            },
        )
    async with untenanted_session() as session:
        await session.execute(
            text(
                "INSERT INTO engine_agent_routes (engine, engine_agent_ref, tenant_id, agent_id, "
                "active, created_at, updated_at) VALUES ('fake', :r, :t, :a, true, now(), now())"
            ),
            {"r": ref, "t": tenant_id, "a": agent_id},
        )
    return tenant_id, agent_id, webhook_id


def _notification(*, leadgen_id: str, page_id: str = "153125381133") -> dict[str, Any]:
    """One `leadgen` change, in the shape Meta publishes.

    Note the ids are JSON NUMBERS, exactly as Meta's own sample renders them — the
    receiver has to survive that and still key on a stable string.
    """
    return {
        "object": "page",
        "entry": [
            {
                "id": int(page_id),
                "time": 1438292065,
                "changes": [
                    {
                        "field": "leadgen",
                        "value": {
                            "leadgen_id": int(leadgen_id),
                            "page_id": int(page_id),
                            "form_id": 12312312312,
                            "adgroup_id": 12312312313,
                            "ad_id": 12312312314,
                            "created_time": 1440120384,
                        },
                    }
                ],
            }
        ],
    }


def _signed(body: dict[str, Any], *, secret: str = APP_SECRET) -> tuple[bytes, dict[str, str]]:
    """The bytes we will send, and a header signed over exactly those bytes."""
    raw = json.dumps(body).encode()
    digest = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, {
        meta.SIGNATURE_HEADER: f"{meta.SIGNATURE_PREFIX}{digest}",
        "content-type": "application/json",
    }


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://api")


async def _inbox(webhook_id: uuid.UUID) -> list[tuple[Any, ...]]:
    async with untenanted_session() as session:
        return list(
            (
                await session.execute(
                    text(
                        "SELECT event_key, status, duplicate_count, last_error, event_name "
                        "FROM webhook_inbox_events WHERE provider = :p ORDER BY created_at"
                    ),
                    {"p": meta.inbox_provider(webhook_id)},
                )
            ).all()
        )


# --- the handshake -------------------------------------------------------------


async def test_the_verification_handshake_echoes_the_challenge_and_nothing_else() -> None:
    """Meta subscribes by GETting the callback URL with `hub.mode=subscribe`, a
    `hub.verify_token` we chose, and a `hub.challenge` it wants back verbatim as plain
    text with 200."""
    _, _, webhook_id = await _tenant_with_meta_source()
    token = meta.verify_token_for(webhook_id=webhook_id, app_secret=APP_SECRET)

    async with _client() as http:
        ok = await http.get(
            f"/hooks/v1/ingest/meta/{webhook_id}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": token,
                "hub.challenge": "1158201444",
            },
        )
    assert ok.status_code == 200, ok.text
    assert ok.text == "1158201444", "the challenge, verbatim and alone"
    assert ok.headers["content-type"].startswith("text/plain")


async def test_a_wrong_verify_token_is_403_and_never_echoes_the_challenge() -> None:
    _, _, webhook_id = await _tenant_with_meta_source()
    async with _client() as http:
        wrong = await http.get(
            f"/hooks/v1/ingest/meta/{webhook_id}",
            params={
                "hub.mode": "subscribe",
                "hub.verify_token": "not-the-token",
                "hub.challenge": "1158201444",
            },
        )
        wrong_mode = await http.get(
            f"/hooks/v1/ingest/meta/{webhook_id}",
            params={
                "hub.mode": "unsubscribe",
                "hub.verify_token": meta.verify_token_for(
                    webhook_id=webhook_id, app_secret=APP_SECRET
                ),
                "hub.challenge": "1158201444",
            },
        )
    assert wrong.status_code == 403, wrong.text
    assert "1158201444" not in wrong.text
    assert wrong_mode.status_code == 403, "only `subscribe` completes a subscription"


# --- the forgeries -------------------------------------------------------------


async def test_a_forged_signature_writes_nothing_at_all() -> None:
    _, _, webhook_id = await _tenant_with_meta_source()
    body = _notification(leadgen_id="900000000000001")
    raw, headers = _signed(body, secret="not-the-app-secret")

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert response.status_code == 401, response.text
    assert await _inbox(webhook_id) == [], "a forgery must not even be recorded as seen"


async def test_an_absent_signature_is_refused() -> None:
    _, _, webhook_id = await _tenant_with_meta_source()
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}",
            content=json.dumps(_notification(leadgen_id="900000000000002")).encode(),
            headers={"content-type": "application/json"},
        )
    assert response.status_code == 401
    assert await _inbox(webhook_id) == []


async def test_a_signature_over_a_different_body_is_refused() -> None:
    """The classic replay-with-substitution: a genuine header from delivery A, moved
    onto body B. It fails only if we hash the bytes we actually received."""
    _, _, webhook_id = await _tenant_with_meta_source()
    _, headers = _signed(_notification(leadgen_id="900000000000003"))
    other = json.dumps(_notification(leadgen_id="900000000000004")).encode()

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=other, headers=headers
        )
    assert response.status_code == 401
    assert await _inbox(webhook_id) == []


async def test_a_signature_over_the_reserialized_body_is_refused() -> None:
    """Meta signs the bytes on the wire, and its serializer is not ours: it escapes
    non-ASCII and uses no spaces. A receiver that verified `json.dumps(parsed)` would
    accept this; one that verifies the raw bytes cannot."""
    _, _, webhook_id = await _tenant_with_meta_source()
    body = _notification(leadgen_id="900000000000005")
    on_the_wire = json.dumps(body, separators=(",", ":")).encode()
    reserialized = json.dumps(body, indent=2, sort_keys=True).encode()
    digest = hmac.new(APP_SECRET.encode(), reserialized, hashlib.sha256).hexdigest()

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}",
            content=on_the_wire,
            headers={
                meta.SIGNATURE_HEADER: f"{meta.SIGNATURE_PREFIX}{digest}",
                "content-type": "application/json",
            },
        )
    assert response.status_code == 401
    assert await _inbox(webhook_id) == []


async def test_a_website_form_source_is_not_a_meta_endpoint() -> None:
    """The app secret and a shared ingest secret are different credentials. A source
    that is not `meta_lead_ads` has no Meta endpoint — 404, like any other unknown."""
    _, _, webhook_id = await _tenant_with_meta_source(source="website_form")
    raw, headers = _signed(_notification(leadgen_id="900000000000006"))
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert response.status_code == 404


# --- the honest refusal --------------------------------------------------------
#
# These run on the SETTINGS THIS SUITE INHERITS, with `META_LEAD_RETRIEVER` unset —
# which is the correct value for local and CI and is not a broken configuration. That
# makes them the regression test for the state every deployment starts in: an adapter
# exists in the tree, and this deployment still cannot read a lead, and says so.


async def test_a_verified_delivery_we_cannot_read_is_recorded_not_swallowed() -> None:
    """No Page access token in this deployment ⇒ no answers ⇒ no lead. The delivery
    still becomes a durable, keyed, visible row carrying the reason."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    raw, headers = _signed(_notification(leadgen_id="900000000000010"))

    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert response.status_code == 200, response.text
    assert response.json() == {"received": 1, "accepted": 0, "duplicate": 0, "refused": 1}

    rows = await _inbox(webhook_id)
    assert len(rows) == 1
    event_key, status, duplicates, error, event_name = rows[0]
    assert event_key == "900000000000010", "keyed on the lead, not on the batch"
    assert status == "failed"
    assert duplicates == 0
    assert error == meta.NO_RETRIEVER_REASON
    assert event_name == meta.LEADGEN_FIELD

    async with tenant_session(tenant_id) as session:
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
    assert (leads, calls) == (0, 0), "we invented no lead out of metadata we cannot read"


async def test_a_replayed_delivery_of_a_completed_lead_rings_the_customer_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Meta retries with exponential backoff for hours and guarantees no ordering, so
    the same lead arrives repeatedly — and may arrive re-batched. The unit of work is
    one lead, so a second copy in a differently shaped envelope is still a duplicate and
    the phone rings exactly once."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source(
        mapping={"phone": "phone_number", "name": "full_name", "consent_field": CONSENT_QUESTION}
    )
    _wire(
        monkeypatch,
        _retriever(
            phone="9876504044",
            name="Rang Once",
            consent="yes",
            # A different leadgen_id is a different person, and the fixture says so —
            # otherwise "one ring" would be proved by a coincidence in the fixture.
            per_lead={
                "900000000000021": _field_data(
                    phone="9876504045", name="Their Neighbour", consent="yes"
                )
            },
        ),
    )
    first = _notification(leadgen_id="900000000000020")
    rebatched = {
        "object": "page",
        "entry": [first["entry"][0], _notification(leadgen_id="900000000000021")["entry"][0]],
    }

    async with _client() as http:
        raw, headers = _signed(first)
        await http.post(f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers)
        raw, headers = _signed(first)
        again = await http.post(f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers)
        raw, headers = _signed(rebatched)
        batched = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )

    assert again.json()["duplicate"] == 1
    assert batched.json() == {"received": 2, "accepted": 1, "duplicate": 1, "refused": 0}, (
        "the repeat is absorbed, its new sibling is processed on its own merits"
    )
    rows = {r[0]: (r[1], r[2]) for r in await _inbox(webhook_id)}
    assert rows["900000000000020"] == ("processed", 2), "two replays counted, one row"
    assert rows["900000000000021"][0] == "processed"

    async with tenant_session(tenant_id) as session:
        rang = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE to_e164 = :p"), {"p": "+919876504044"}
            )
        ).scalar()
    assert rang == 1, "three deliveries, one lead, one ring"


async def test_a_replayed_refusal_is_retried_not_absorbed() -> None:
    """The mirror image, and the reason it is NOT symmetric with the case above.

    A refused delivery is a claim nobody completed, so `claim_inbox_event` re-claims it
    by CAS and Meta's next retry gets a fresh attempt at the same verdict — cheap
    (no lead, no dial) and the only thing that makes the lead recoverable the moment a
    credential is attached. What must never change is the row count: one lead, one row,
    one `leadgen_id`, however many times Meta sends it.
    """
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    body = _notification(leadgen_id="900000000000022")

    async with _client() as http:
        for _ in range(3):
            raw, headers = _signed(body)
            response = await http.post(
                f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
            )
            assert response.json()["refused"] == 1

    rows = await _inbox(webhook_id)
    assert [(r[0], r[1]) for r in rows] == [("900000000000022", "failed")]
    async with tenant_session(tenant_id) as session:
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
    assert leads == 0


async def test_the_refusal_is_resumable_once_a_credential_is_attached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of recording the refusal against the `leadgen_id`: it is not a
    dropped lead, it is a claim nobody could complete. `claim_inbox_event` re-claims a
    `failed` row by CAS, so the same delivery replayed later lands for real."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    body = _notification(leadgen_id="900000000000030")

    async with _client() as http:
        raw, headers = _signed(body)
        await http.post(f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers)

        retriever = _retriever(phone="9876504040", name="Anitha Rao", consent=None)
        _wire(monkeypatch, retriever)
        raw, headers = _signed(body)
        second = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )

    assert second.json() == {"received": 1, "accepted": 1, "duplicate": 0, "refused": 0}
    assert retriever.calls == ["900000000000030"]
    rows = await _inbox(webhook_id)
    assert [(r[0], r[1]) for r in rows] == [("900000000000030", "processed")]

    async with tenant_session(tenant_id) as session:
        lead = (await session.execute(text("SELECT phone_e164, name, data FROM leads"))).first()
    assert lead is not None
    assert lead[0] == "+919876504040"
    assert lead[1] == "Anitha Rao"
    assert lead[2]["meta_lead_ads"]["form_id"] == "12312312312", (
        "which ad and which form produced this lead is provenance, and it is ours to keep"
    )


# --- the per-tenant seam -------------------------------------------------------


async def test_a_client_with_no_token_is_unavailable_even_where_the_adapter_is_wired(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ "This deployment can retrieve leads" is not a fact about any client.

    The adapter is selected and holds credentials for SOMEBODY — just not for this lead
    source. That must land as its own reason, distinct from "nobody wired this up": one
    is fixed by attaching a token for this client, the other by configuring the
    deployment, and a support thread that cannot tell them apart burns a day.
    """
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    # A retriever holding a credential for a DIFFERENT lead source, and answers ready to
    # hand over if anything ever asks it. `holds_credential_for` is the retriever
    # answering about itself, which is what keeps the capability and the read from ever
    # disagreeing — and it is what must stop these answers reaching this tenant.
    other_source = _retriever(
        phone="9876504060", name="Somebody Else", consent="yes", sources=frozenset({uuid.uuid4()})
    )
    _wire(monkeypatch, other_source)

    raw, headers = _signed(_notification(leadgen_id="900000000000060"))
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert response.status_code == 200
    assert response.json()["refused"] == 1

    rows = await _inbox(webhook_id)
    assert [(r[0], r[1], r[3]) for r in rows] == [
        ("900000000000060", "failed", meta.NO_TOKEN_REASON)
    ], "the reason names the client's missing credential, not the deployment's"
    assert other_source.calls == [], "and the other client's retriever was never asked"
    async with tenant_session(tenant_id) as session:
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
    assert leads == 0


async def test_the_real_selector_reports_the_per_source_credential_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The selector itself, unmonkeypatched — the one every surface actually calls.

    Everything else in this file substitutes it, so without this the per-tenant ladder
    would be asserted only against a stand-in. Four states, four reasons, one function.
    """
    from apps.api.core.settings import get_settings

    settings = get_settings()
    mine, theirs = uuid.uuid4(), uuid.uuid4()

    monkeypatch.setattr(settings, "meta_lead_retriever", None)
    assert meta.lead_retrieval_capability(source_id=mine).reason == meta.NO_RETRIEVER_REASON

    monkeypatch.setattr(settings, "meta_lead_retriever", "leadsbridge")
    unknown = meta.lead_retrieval_capability(source_id=mine)
    assert unknown.available is False
    assert unknown.reason == f"{meta.PROVIDER_NOT_IMPLEMENTED_REASON}:leadsbridge", (
        "a provider with nothing behind it fails loudly rather than looking configured"
    )

    monkeypatch.setattr(settings, "meta_lead_retriever", meta.GRAPH_PROVIDER)
    monkeypatch.setattr(settings, "meta_page_access_tokens", json.dumps({str(theirs): "EAAG-x"}))
    assert meta.lead_retrieval_capability(source_id=mine).reason == meta.NO_TOKEN_REASON

    monkeypatch.setattr(
        settings,
        "meta_page_access_tokens",
        json.dumps({str(mine): "EAAG-mine", str(theirs): "EAAG-theirs"}),
    )
    available = meta.lead_retrieval_capability(source_id=mine)
    assert available.available is True
    assert available.reason is None
    assert available.retriever is not None, "the capability carries what it authorises"
    assert available.retriever.holds_credential_for(mine) is True
    assert available.retriever.holds_credential_for(uuid.uuid4()) is False, (
        "one map, many clients — a source not in it holds nothing, and borrows nothing"
    )


async def test_the_recorded_retriever_is_refused_outside_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """It would fabricate a person and hand them to the compliance gate, which has no
    way to doubt they exist. A staging box gets a named refusal, not a fake lead."""
    from apps.api.core.settings import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "meta_lead_retriever", meta.RECORDED_PROVIDER)
    monkeypatch.setattr(settings, "app_env", "prod")
    refused = meta.lead_retrieval_capability(source_id=uuid.uuid4())
    assert refused.available is False
    assert refused.reason == meta.RECORDED_OUTSIDE_LOCAL_REASON

    monkeypatch.setattr(settings, "app_env", "local")
    assert meta.lead_retrieval_capability(source_id=uuid.uuid4()).available is True


# --- transient vs verdict ------------------------------------------------------


async def test_a_transient_graph_failure_is_deferred_to_metas_own_retry_ladder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The failure mode this slice exists to avoid: a 30-second Graph blip losing a lead.

    A verdict is acked 200 (Meta unsubscribes a Page it cannot deliver to). A transient
    is NOT a verdict, so it answers 503 and Meta's own at-least-once ladder redelivers —
    and the claim is left `failed`, which is what makes the redelivery re-claimable
    rather than absorbed as a duplicate.
    """
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    from apps.api.ingest.graph import UNAVAILABLE_REASON

    _wire(
        monkeypatch,
        RecordedLeadRetriever(
            answers_with=meta.RetrievedLead(
                status=meta.RetrievalStatus.TRANSIENT, reason=UNAVAILABLE_REASON
            )
        ),
    )
    raw, headers = _signed(_notification(leadgen_id="900000000000070"))
    async with _client() as http:
        deferred = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert deferred.status_code == 503, deferred.text
    assert deferred.json()["retryable"] is True
    rows = await _inbox(webhook_id)
    assert [(r[0], r[1], r[3]) for r in rows] == [("900000000000070", "failed", UNAVAILABLE_REASON)]

    # ...and the redelivery, once Graph is back, lands the lead for real.
    _wire(monkeypatch, _retriever(phone="9876504070", name="Late But Landed", consent=None))
    async with _client() as http:
        raw, headers = _signed(_notification(leadgen_id="900000000000070"))
        landed = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert landed.json() == {"received": 1, "accepted": 1, "duplicate": 0, "refused": 0}
    async with tenant_session(tenant_id) as session:
        phone = (await session.execute(text("SELECT phone_e164 FROM leads"))).scalar()
    assert phone == "+919876504070", "the deferred lead was not lost, only late"


async def test_a_deferred_sibling_does_not_undo_the_leads_that_landed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One 503 for a batch, and the redelivery must not ring the healthy lead twice.

    This is the load-bearing half of the 503: Meta redelivers the WHOLE notification,
    so the siblings that already committed have to absorb as duplicates. They do,
    because the unit of work is the `leadgen_id` and not the body.
    """
    tenant_id, _, webhook_id = await _tenant_with_meta_source()

    class _OneSickLead:
        """Answers for one lead and fails transiently for the other."""

        name = "test"

        def holds_credential_for(self, source_id: UUID) -> bool:
            return True

        async def fetch_answers(self, *, source_id: UUID, leadgen_id: str) -> meta.RetrievedLead:
            if leadgen_id == "900000000000081":
                return meta.RetrievedLead(
                    status=meta.RetrievalStatus.TRANSIENT, reason="meta_graph_unavailable"
                )
            return meta.RetrievedLead(
                status=meta.RetrievalStatus.RETRIEVED,
                answers=meta.flatten_field_data(
                    _field_data(phone="9876504080", name="Healthy", consent=None)
                ),
            )

    _wire(monkeypatch, _OneSickLead())
    batch = {
        "object": "page",
        "entry": [
            _notification(leadgen_id="900000000000080")["entry"][0],
            _notification(leadgen_id="900000000000081")["entry"][0],
        ],
    }
    async with _client() as http:
        raw, headers = _signed(batch)
        first = await http.post(f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers)
        raw, headers = _signed(batch)
        second = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )

    assert (first.status_code, second.status_code) == (503, 503), "still one sick lead"
    rows = {r[0]: (r[1], r[2]) for r in await _inbox(webhook_id)}
    assert rows["900000000000080"] == ("processed", 1), "the healthy lead: one row, one replay"
    assert rows["900000000000081"][0] == "failed"
    async with tenant_session(tenant_id) as session:
        rang = (
            await session.execute(
                text("SELECT count(*) FROM calls WHERE to_e164 = :p"), {"p": "+919876504080"}
            )
        ).scalar()
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
    assert (rang, leads) == (0, 1), "no consent question on the form, so saved and not dialled"


async def test_a_dead_page_token_is_a_verdict_and_is_acked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A revoked or invalidated token will not fix itself in 36 hours.

    Retrying it is how a client's Page gets unsubscribed while nobody is told why, so
    it is acked 200, recorded with OUR code, and the alert is what carries the urgency.
    """
    _, _, webhook_id = await _tenant_with_meta_source()
    from apps.api.ingest.graph import TOKEN_INVALID_REASON

    _wire(
        monkeypatch,
        RecordedLeadRetriever(
            answers_with=meta.RetrievedLead(
                status=meta.RetrievalStatus.PERMANENT, reason=TOKEN_INVALID_REASON
            )
        ),
    )
    raw, headers = _signed(_notification(leadgen_id="900000000000090"))
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert response.status_code == 200, "a verdict must never make Meta retry for 36 hours"
    assert response.json()["refused"] == 1
    rows = await _inbox(webhook_id)
    assert rows[0][3] == TOKEN_INVALID_REASON


# --- consent (hard rule 5) -----------------------------------------------------


async def test_a_lead_ad_fill_is_never_by_itself_permission_to_dial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Somebody tapping a lead ad gave Meta their number. That is not consent to be
    telephoned by a voice agent, and this path must never record it as if it were."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    _wire(monkeypatch, _retriever(phone="9876504041", name="Unconsented", consent=None))
    raw, headers = _signed(_notification(leadgen_id="900000000000040"))
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert response.json()["accepted"] == 1

    async with tenant_session(tenant_id) as session:
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
        note = (
            await session.execute(
                text("SELECT payload FROM lead_events ORDER BY created_at DESC LIMIT 1")
            )
        ).scalar()
    assert leads == 1, "the enquiry is the client's either way"
    assert calls == 0, "and nobody was dialled on an assumption"
    assert note["kind"] == "blocked"
    assert note["rule"] == meta.NO_CONSENT_FIELD_RULE


async def test_a_form_that_asked_permission_gets_the_instant_callback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lawful case: the client's own lead form carried an opt-in question, the
    person answered yes, and the answer travels with the lead."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source(
        mapping={
            "phone": "phone_number",
            "name": "full_name",
            "consent_field": CONSENT_QUESTION,
        }
    )
    _wire(monkeypatch, _retriever(phone="9876504042", name="Consented", consent="yes"))
    raw, headers = _signed(_notification(leadgen_id="900000000000041"))
    async with _client() as http:
        response = await http.post(
            f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers
        )
    assert response.json()["accepted"] == 1

    async with tenant_session(tenant_id) as session:
        calls = (await session.execute(text("SELECT direction, to_e164 FROM calls"))).all()
    assert calls == [("outbound", "+919876504042")]


async def test_a_form_that_asked_and_was_told_no_saves_the_lead_and_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, _, webhook_id = await _tenant_with_meta_source(
        mapping={
            "phone": "phone_number",
            "name": "full_name",
            "consent_field": CONSENT_QUESTION,
        }
    )
    _wire(monkeypatch, _retriever(phone="9876504043", name="Said No", consent="no"))
    raw, headers = _signed(_notification(leadgen_id="900000000000042"))
    async with _client() as http:
        await http.post(f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers)

    async with tenant_session(tenant_id) as session:
        leads = (await session.execute(text("SELECT count(*) FROM leads"))).scalar()
        calls = (await session.execute(text("SELECT count(*) FROM calls"))).scalar()
    assert (leads, calls) == (1, 0)


# --- the surfaces the client sees ----------------------------------------------


async def test_the_activity_view_shows_the_meta_refusal_as_a_rejection() -> None:
    """A refusal nobody can see is a silent drop with extra steps (SURFACES §2b)."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    raw, headers = _signed(_notification(leadgen_id="900000000000050"))
    async with _client() as http:
        await http.post(f"/hooks/v1/ingest/meta/{webhook_id}", content=raw, headers=headers)

    from apps.api.ingest.routes import ingest_activity

    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        clerk_user_id="u",
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )
    async with tenant_session(tenant_id) as session:
        activity = await ingest_activity(session, 50, principal)

    item = next(i for i in activity.items if i.source == "meta_lead_ads")
    assert item.outcome == "rejected"
    assert item.error == meta.NO_RETRIEVER_REASON


async def test_the_setup_view_states_the_capability_and_hands_over_the_token() -> None:
    """A client cannot subscribe a webhook they cannot configure: they need the
    callback path and the verify token. They also deserve to be told, before they
    wire it up, that lead retrieval is not available in this deployment."""
    tenant_id, _, webhook_id = await _tenant_with_meta_source()
    from apps.api.ingest.routes import meta_setup

    principal = Principal(
        realm="client",
        user_id=uuid.uuid4(),
        clerk_user_id="u",
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )
    async with tenant_session(tenant_id) as session:
        setup = await meta_setup(webhook_id, session, principal)

    assert setup.callback_path == f"/hooks/v1/ingest/meta/{webhook_id}"
    assert setup.verify_token == meta.verify_token_for(webhook_id=webhook_id, app_secret=APP_SECRET)
    assert setup.subscribe_field == meta.LEADGEN_FIELD
    assert setup.lead_retrieval_available is False
    assert setup.lead_retrieval_reason == meta.NO_RETRIEVER_REASON


async def test_the_setup_view_answers_for_this_source_and_not_for_the_deployment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two lead sources, one deployment, two different answers.

    The card is what a client reads before spending twenty minutes in the Meta App
    Dashboard, so it has to be about THEIR source. A deployment-wide "yes" would send
    the client whose token nobody attached into that dashboard to configure something
    that refuses every delivery.
    """
    wired_tenant, _, wired = await _tenant_with_meta_source()
    bare_tenant, _, bare = await _tenant_with_meta_source()
    _wire(
        monkeypatch,
        _retriever(phone="9876504100", name="Wired", consent="yes", sources=frozenset({wired})),
    )
    from apps.api.ingest.routes import meta_setup

    def _principal(tenant_id: uuid.UUID) -> Principal:
        return Principal(
            realm="client",
            user_id=uuid.uuid4(),
            clerk_user_id="u",
            tenant_id=tenant_id,
            role="owner",
            impersonating=False,
        )

    async with tenant_session(wired_tenant) as session:
        ready = await meta_setup(wired, session, _principal(wired_tenant))
    assert (ready.lead_retrieval_available, ready.lead_retrieval_reason) == (True, None)

    # The neighbour's source, read under its OWN tenant session — RLS is what makes the
    # second `meta_setup` resolve at all, and the capability is what makes it honest.
    async with tenant_session(bare_tenant) as session:
        unconfigured = await meta_setup(bare, session, _principal(bare_tenant))
    assert unconfigured.lead_retrieval_available is False
    assert unconfigured.lead_retrieval_reason == meta.NO_TOKEN_REASON


# --- the pure functions --------------------------------------------------------


def test_field_data_flattens_to_one_answer_per_question() -> None:
    """Meta's `field_data` is a list of `{name, values[]}`; ours is a flat map so the
    per-source field mapping can rename it like any other form."""
    flat = meta.flatten_field_data(
        [
            {"name": "full_name", "values": ["Ravi Kumar"]},
            {"name": "phone_number", "values": ["+919876543210"]},
            {"name": "preferred_time", "values": []},
            {"name": "interests", "values": ["2bhk", "3bhk"]},
            {"name": "", "values": ["nameless"]},
            "not a field at all",
        ]
    )
    assert flat == {
        "full_name": "Ravi Kumar",
        "phone_number": "+919876543210",
        "interests": "2bhk, 3bhk",
    }, "empty answers and nameless rows are dropped, multi-select is joined"


def test_only_leadgen_changes_are_treated_as_leads() -> None:
    notifications = meta.extract_lead_notifications(
        {
            "object": "page",
            "entry": [
                {
                    "id": 1,
                    "changes": [
                        {"field": "feed", "value": {"post_id": "1_2"}},
                        {"field": "leadgen", "value": {"leadgen_id": 7, "form_id": 9}},
                        {"field": "leadgen", "value": {"form_id": 9}},
                    ],
                }
            ],
        }
    )
    assert [n.leadgen_id for n in notifications] == ["7"], (
        "a page's other activity is not a lead, and a change with no lead id is not one either"
    )


def test_a_notification_for_another_object_type_is_not_a_page_lead() -> None:
    assert meta.extract_lead_notifications({"object": "user", "entry": []}) == []
    assert meta.extract_lead_notifications({"entry": "not a list"}) == []
    assert meta.extract_lead_notifications([]) == []


def test_the_signature_check_is_shape_strict_and_case_insensitive() -> None:
    body = b'{"object":"page"}'
    digest = hmac.new(APP_SECRET.encode(), body, hashlib.sha256).hexdigest()
    ok = meta.verify_signature
    assert ok(app_secret=APP_SECRET, body=body, header=f"sha256={digest}")
    assert ok(app_secret=APP_SECRET, body=body, header=f"sha256={digest.upper()}")
    assert not ok(app_secret=APP_SECRET, body=body, header=digest), "the prefix is required"
    assert not ok(app_secret=APP_SECRET, body=body, header=f"sha1={digest}")
    assert not ok(app_secret=APP_SECRET, body=body, header=None)
    assert not ok(app_secret=APP_SECRET, body=body, header="sha256=")
    assert not ok(app_secret="", body=body, header=f"sha256={digest}"), "no secret, no trust"
    assert not ok(app_secret=APP_SECRET, body=body + b" ", header=f"sha256={digest}")


def test_the_verify_token_is_per_endpoint_and_leaks_no_secret() -> None:
    one = meta.verify_token_for(webhook_id=uuid.UUID(int=1), app_secret=APP_SECRET)
    two = meta.verify_token_for(webhook_id=uuid.UUID(int=2), app_secret=APP_SECRET)
    other_secret = meta.verify_token_for(webhook_id=uuid.UUID(int=1), app_secret="other")
    assert one != two, "one endpoint's token cannot subscribe another's"
    assert one != other_secret, "and it rotates with the secret it is derived from"
    assert APP_SECRET not in one and len(one) == 64
