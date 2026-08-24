"""`call.completed` recording + transcript opt-ins (docs/WEBHOOKS.md §1.7).

The base `call.completed` webhook is summary-and-outcome only — "the summary — never the
transcript — is what leaves on a webhook". These tests pin the three per-endpoint opt-ins
that widen that, and the controls that keep the raw transcript from leaving quietly:

- **Not opted in is unchanged.** An endpoint with no opt-in gets exactly the payload it
  always got — no `recording_url`, no `transcript`, no `raw_transcript`.
- **Opted in gets the redacted transcript and a short-TTL recording link**, and the link
  is presigned with `storage.PRESIGN_TTL_S`, not a hand-picked window.
- **Raw is a second opt-in, gated and audited.** `include_raw_transcript` only carries the
  unredacted transcript, and every delivery that does writes an `audit_log` row (hard
  rule 5). The registration gate refuses raw without the redacted opt-in, and refuses a
  caller who does not hold `calls:read_raw`.
- **A recording that does not exist is omitted, never nulled.**
"""

from __future__ import annotations

import uuid

import pytest
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import service
from apps.api.integrations.routes import CreateEndpointIn, assert_may_opt_into_raw_transcript
from apps.workers import storage
from apps.workers.redaction import redact
from sqlalchemy import text
from tests.api_security_test import _make_tenant

# A number shaped like one a caller reads out; `redact()` masks all but the last two.
CALLER_NUMBER = "9876500123"
RAW_TURNS = (
    ("agent", "Namaskaram, cheppandi."),
    ("caller", f"Naa number {CALLER_NUMBER}, malli call cheyandi."),
)
RECORDING_KEY = "recordings/fake/recording.wav"


async def _endpoint(
    tenant_id: uuid.UUID,
    *,
    include_recording_url: bool = False,
    include_transcript: bool = False,
    include_raw_transcript: bool = False,
) -> uuid.UUID:
    endpoint_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "include_recording_url, include_transcript, include_raw_transcript, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, :secret, "
                ":events, :inc_rec, :inc_tx, :inc_raw, true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "url": "https://crm.example/hook",
                "secret": "whsec_test",
                "events": ["call.completed"],
                "inc_rec": include_recording_url,
                "inc_tx": include_transcript,
                "inc_raw": include_raw_transcript,
            },
        )
    return endpoint_id


async def _completed_call(tenant_id: uuid.UUID, *, recording_key: str | None) -> uuid.UUID:
    call_id = uuid.uuid4()
    async with tenant_session(tenant_id) as session:
        agent_id = (await session.execute(text("SELECT id FROM agents LIMIT 1"))).scalar()
        await session.execute(
            text(
                "INSERT INTO calls (id, tenant_id, agent_id, engine_call_id, direction, status, "
                "from_e164, summary, sentiment, outcome_tag, duration_s, recording_url, "
                "started_at, created_at, updated_at) VALUES (:id, :tid, :aid, :ecid, 'inbound', "
                "'completed', :from_e, 'A summary.', 'neutral', 'needs_follow_up', 42, :rec, "
                "now(), now(), now())"
            ),
            {
                "id": call_id,
                "tid": tenant_id,
                "aid": agent_id,
                "ecid": f"c_{call_id.hex[:10]}",
                "from_e": f"+91{CALLER_NUMBER}",
                "rec": recording_key,
            },
        )
        for idx, (speaker, raw) in enumerate(RAW_TURNS):
            await session.execute(
                text(
                    "INSERT INTO transcript_turns (id, tenant_id, call_id, idx, speaker, text, "
                    "text_redacted, lang, start_ms, created_at, updated_at) VALUES (:id, :tid, "
                    ":cid, :idx, :speaker, :raw, :red, 'te', :ms, now(), now())"
                ),
                {
                    "id": uuid.uuid4(),
                    "tid": tenant_id,
                    "cid": call_id,
                    "idx": idx,
                    "speaker": speaker,
                    "raw": raw,
                    "red": redact(raw).text,
                    "ms": idx * 1000,
                },
            )
    return call_id


async def _fan_out(tenant_id: uuid.UUID, call_id: uuid.UUID) -> list[dict]:
    """Run the real fan-out for one completed call and return the outbox `data` payloads."""
    async with tenant_session(tenant_id) as session:
        await service.enqueue_event(
            session,
            tenant_id=tenant_id,
            event="call.completed",
            data={
                "call_id": str(call_id),
                "lead_id": None,
                "direction": "inbound",
                "duration_s": 42,
                "outcome": "needs_follow_up",
                "sentiment": "neutral",
                "summary": "A summary.",
            },
        )
    async with untenanted_session() as session:
        rows = (
            await session.execute(
                text("SELECT payload FROM outbox_messages WHERE job = :job ORDER BY created_at"),
                {"job": service.OUTBOUND_WEBHOOK_JOB},
            )
        ).all()
    return [r[0]["data"] for r in rows if r[0].get("data", {}).get("call_id") == str(call_id)]


async def _audit_rows(call_id: uuid.UUID, action: str) -> int:
    async with untenanted_session() as session:
        return int(
            (
                await session.execute(
                    text("SELECT count(*) FROM audit_log WHERE object_id = :cid AND action = :a"),
                    {"cid": str(call_id), "a": action},
                )
            ).scalar()
            or 0
        )


@pytest.fixture
def _presign(monkeypatch: pytest.MonkeyPatch) -> list[int]:
    """Replace the S3 presigner with one that records the TTL it was asked for.

    FakeS3 has no `generate_presigned_url`, and signing needs credentials CI does not
    carry — so the builder's contract (it asks for a SHORT-TTL link, `PRESIGN_TTL_S`) is
    pinned by capturing the argument rather than by reaching a store.
    """
    seen: list[int] = []

    def fake(key: str, *, ttl_s: int = storage.PRESIGN_TTL_S) -> str:
        seen.append(ttl_s)
        return f"https://store.example/{key}?X-Amz-Expires={ttl_s}"

    monkeypatch.setattr(storage, "presigned_url", fake)
    return seen


# --- 1. not opted in is unchanged ---------------------------------------------


async def test_not_opted_in_is_unchanged() -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id)
    call_id = await _completed_call(tenant_id, recording_key=RECORDING_KEY)

    (data,) = await _fan_out(tenant_id, call_id)

    assert "recording_url" not in data
    assert "transcript" not in data
    assert "raw_transcript" not in data
    # The base fields still travel.
    assert data["summary"] == "A summary."
    assert data["outcome"] == "needs_follow_up"


# --- 2. recording + redacted transcript when opted in -------------------------


async def test_recording_and_redacted_transcript(_presign: list[int]) -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, include_recording_url=True, include_transcript=True)
    call_id = await _completed_call(tenant_id, recording_key=RECORDING_KEY)

    (data,) = await _fan_out(tenant_id, call_id)

    # A signed, short-TTL link to OUR key — never the audio, never the raw column.
    assert data["recording_url"].startswith("https://store.example/")
    assert _presign == [storage.PRESIGN_TTL_S]

    # The redacted transcript, as an ordered array of turns matching the dashboard's read.
    turns = data["transcript"]
    assert [t["speaker"] for t in turns] == ["agent", "caller"]
    assert [t["start_ms"] for t in turns] == [0, 1000]
    caller = turns[1]["text"]
    assert CALLER_NUMBER not in caller  # masked
    assert caller == redact(RAW_TURNS[1][1]).text

    # Redacted only — raw is a separate opt-in, and no raw audit was written.
    assert "raw_transcript" not in data
    assert await _audit_rows(call_id, service.RAW_TRANSCRIPT_INCLUDED_ACTION) == 0


# --- 3. raw transcript is carried AND audited ---------------------------------


async def test_raw_transcript_included_and_audited(_presign: list[int]) -> None:
    tenant_id, _, _ = await _make_tenant()
    endpoint_id = await _endpoint(tenant_id, include_transcript=True, include_raw_transcript=True)
    call_id = await _completed_call(tenant_id, recording_key=RECORDING_KEY)

    (data,) = await _fan_out(tenant_id, call_id)

    raw_turns = data["raw_transcript"]
    # The raw column, verbatim — the caller's number is present in the clear.
    assert CALLER_NUMBER in raw_turns[1]["text"]
    assert raw_turns[1]["text"] == RAW_TURNS[1][1]
    # The redacted transcript rides alongside it (raw is layered on it).
    assert CALLER_NUMBER not in data["transcript"][1]["text"]

    # Exactly one audit row for this delivery's raw egress (hard rule 5).
    assert await _audit_rows(call_id, service.RAW_TRANSCRIPT_INCLUDED_ACTION) == 1
    async with untenanted_session() as session:
        actor_type = (
            await session.execute(
                text("SELECT actor_type FROM audit_log WHERE object_id = :cid AND action = :a"),
                {"cid": str(call_id), "a": service.RAW_TRANSCRIPT_INCLUDED_ACTION},
            )
        ).scalar()
    # No user principal on the pipeline — the config-time opt-in passed the role gate, so
    # the per-delivery record is a system actor.
    assert actor_type == "system"
    assert endpoint_id  # sanity: the fixture created a distinct endpoint


# --- 4. a recording that does not exist is omitted, not nulled ----------------


async def test_recording_omitted_when_absent(_presign: list[int]) -> None:
    tenant_id, _, _ = await _make_tenant()
    await _endpoint(tenant_id, include_recording_url=True)
    call_id = await _completed_call(tenant_id, recording_key=None)

    (data,) = await _fan_out(tenant_id, call_id)

    assert "recording_url" not in data
    # No key means the presigner is never even asked.
    assert _presign == []


# --- 5. the registration gate (unit, no live request) -------------------------


def _principal(role: str) -> Principal:
    return Principal(realm="client", user_id=uuid.uuid4(), tenant_id=uuid.uuid4(), role=role)


def _body(**kw: bool) -> CreateEndpointIn:
    return CreateEndpointIn(url="https://crm.example/hook", events=["call.completed"], **kw)


def test_raw_optin_requires_transcript_optin() -> None:
    with pytest.raises(ProblemError) as exc:
        assert_may_opt_into_raw_transcript(_body(include_raw_transcript=True), _principal("owner"))
    assert exc.value.code == "raw_transcript_requires_transcript"


def test_raw_optin_requires_calls_read_raw() -> None:
    # `staff` holds neither `org:manage` nor `calls:read_raw`; here it stands in for any
    # future role that reaches the route without the raw permission.
    with pytest.raises(ProblemError) as exc:
        assert_may_opt_into_raw_transcript(
            _body(include_transcript=True, include_raw_transcript=True), _principal("staff")
        )
    assert exc.value.status == 403


def test_owner_may_opt_into_raw() -> None:
    # `owner` holds `calls:read_raw`; the well-formed opt-in passes without raising.
    assert_may_opt_into_raw_transcript(
        _body(include_transcript=True, include_raw_transcript=True), _principal("owner")
    )


def test_no_raw_optin_is_always_allowed() -> None:
    # Nothing to gate when raw is off, whatever the role.
    assert_may_opt_into_raw_transcript(_body(include_transcript=True), _principal("staff"))
