"""Outbound CRM sync — us → the client's tools (D-23).

Three properties this module exists to guarantee, in the order they matter:

**Nothing is delivered that the domain write did not commit.** Every event goes out
through the transactional outbox (BACKEND-PATTERNS §4): `enqueue_event` writes the
outbox row in the CALLER's transaction, so "lead created but the CRM never heard" and
"CRM told about a lead that rolled back" are both impossible.

**Every request is signed, and the signature covers the timestamp.** HMAC-SHA256 over
`{timestamp}.{body}` in `X-Calevate-Signature`, the scheme SEC-COMP §5 requires of our
inbound partners and therefore the one we owe ours. Signing the body alone would let a
captured request be replayed forever; the timestamp gives the receiver a window to
reject.

**Payloads are redacted by the same rule as everything else.** A lead's phone number is
PII whether it is in a log line or an HTTP body, so the envelope carries the masked form
unless the endpoint is explicitly configured otherwise — an opt-in the client makes
about their own data, recorded in the config row rather than assumed.

Delivery outcomes land in `webhook_deliveries(direction='out')`, which is the forensic
half of SEC-COMP §5 and the data the "webhook activity" screen reads.

**WHAT THAT TABLE CAN AND CANNOT ANSWER, because two documents send an investigator to
it and one of them overstates it (R-9).** The OUT direction is complete: `record_delivery`
upserts a row per delivery id whatever the outcome, so every attempt we made — delivered,
failed, skipped — is on file with its status, its attempts and its `payload_ref`. The IN
direction is NOT a record of what arrived, and must not be read as one:
`apps/voice-runtime/webhook_routes.py` writes its row inside `if claimed:`, so a delivery
refused at the source-IP check, refused as unkeyable, refused over the size cap, timed out
reading its body, or answered `duplicate` by the inbox leaves NOTHING here. That is
deliberate — a row per hostile POST on an unauthenticated public endpoint is a write
amplifier an attacker controls — and it means the population an intrusion investigation
most wants (SEC-COMP §4 / OPERATIONS §7's "scope via audit_log/webhook_deliveries") is
exactly the population absent from the table. What carries that signal instead is the
alert stream: the source rejection, the size cap and the unkeyable payload each fire a
coded `alert()` (`webhook_source_rejected`, `webhook_payload_too_large`,
`webhook_unkeyable`) carrying the source IP where it exists, and `duplicate` is deliberately
silent because it is ordinary traffic rather than an incident. Those alerts and the
receiver's own log lines are what an investigator should be pointed at for inbound scope,
NOT this table's `direction='in'` rows. Closing the gap properly needs a bounded,
aggregated counter rather than a row per refusal, which needs the metrics pipeline
`DEPLOYMENT.md` §8 defers.

**Two endpoint kinds, ONE definition of "delivered".** D-23 promises webhooks *and*
Google Sheets. They differ only in the transport at the very end: the fan-out, the
per-endpoint redaction, the delivery id, the forensic row and the retry ladder are
shared, because a client asking "did my lead arrive?" must get an answer built the same
way whichever box they ticked. The sheets-specific pieces live below under
`# --- google sheets ---` and are used by `apps/workers/sheets_sync.py`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.errors import ProblemError
from apps.api.core.logging import get_logger, redact_mapping
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.spreadsheet_safety import disarm_for_sheets
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
from apps.api.integrations.egress_guard import EgressRefusedError, assert_public_http_url
from apps.api.reliability.service import enqueue_outbox

log = get_logger(__name__)

# The events a client endpoint may subscribe to (DATA-MODEL §6). Deliberately small:
# each one is a promise about payload shape we have to keep across versions.
EVENT_TYPES: tuple[str, ...] = (
    "lead.created",
    "lead.updated",
    "call.completed",
    "campaign.completed",
)

# The endpoint kinds in `outbound_webhooks.kind`.
WEBHOOK_KIND = "webhook"
SHEET_KIND = "google_sheets"

# Kinds `enqueue_event` will fan out to. Deliberately NOT `models.OUTBOUND_KINDS`: that
# tuple is the CHECK constraint — what may EXIST — and a kind added there must not start
# queueing deliveries into a worker that has no branch for it. A kind joins this tuple
# when it has a delivery path, and `tests/sheets_sync_test.py` asserts the two sets match
# so the reverse (a kind a client can configure and nothing delivers) cannot come back.
DELIVERABLE_KINDS: tuple[str, ...] = (WEBHOOK_KIND, SHEET_KIND)


def subscribed_endpoint_sql(alias: str) -> str:
    """The predicate for "which endpoints does this event fan out to", spelled ONCE.

    Binds `:event` and `:kinds` — pass `{"event": ..., "kinds": list(DELIVERABLE_KINDS)}`.

    EXPORTED BECAUSE IT WAS RESTATED, and the restatement was already wrong.
    `workers/pipeline._pipeline_settled` probes "was a CRM fan-out owed for this call"
    and its own docstring says it mirrors this predicate; it asked `active = true AND
    'call.completed' = ANY(events)` and left the `kind` half out. The two agree today
    only because `ck_outbound_webhooks_kind_enum` happens to allow exactly
    `DELIVERABLE_KINDS` — so the day a third kind lands in the CHECK ahead of its
    delivery worker (the ordinary way a third kind arrives), `enqueue_event` writes zero
    outbox rows for that tenant while the probe expects the artefact anyway, and every
    completed call becomes a permanent `unfinished_pipeline` the poller re-drives once an
    hour WITH A BILLED EXTRACTION. Two spellings of one rule is a defect while they still
    agree; this is the same move `billing.caps.over_cap_sql` and
    `pipeline.EXTRACTION_OWED_SQL` already make.

    `alias` is required rather than defaulted: both call sites sit in a query with other
    tables in scope, and an unqualified `events`/`kind` resolving to somebody else's
    column is precisely the silent wrong answer this function exists to stop.
    """
    return f"{alias}.active = true AND {alias}.kind = ANY(:kinds) AND :event = ANY({alias}.events)"


#: The arq job this module fans out to, promoted from a bare literal (P6.9). A job name
#: passed inline is invisible to `tests/job_registration_test.py`, whose entire purpose is
#: noticing a name no worker answers to — and the outbox publishes an unrecognised name
#: straight into arq's void while every screen above reports the message as queued.
#:
#: Spelled here rather than imported from `apps/workers/outbound_webhooks.py`, following
#: `compliance/deletion.DELETION_JOB`: the constant lives with the ENQUEUER so `apps/api`
#: never imports a worker module to name a job. `apps/workers/pipeline.py` declares the
#: same name as `OUTBOUND_WEBHOOK_JOB` for its own call site, and the registration guard
#: is what keeps the two agreeing with `settings.FUNCTIONS`.
OUTBOUND_WEBHOOK_JOB = "deliver_outbound_webhook"

SIGNATURE_HEADER = "X-Calevate-Signature"
TIMESTAMP_HEADER = "X-Calevate-Timestamp"
EVENT_HEADER = "X-Calevate-Event"
DELIVERY_HEADER = "X-Calevate-Delivery"

# Receivers are third-party endpoints on Indian SMB infrastructure; slow is normal,
# hanging is not. The retry ladder is ARQ's, so the exhaustion threshold MUST be
# ARQ's budget — a local number larger than the real one means the last try does not
# know it is the last, and the exhausted alert never fires (found by the runbook
# audit, pinned by a test).
DELIVERY_TIMEOUT_S = 10.0
MAX_ATTEMPTS = WORKER_MAX_TRIES


@dataclass(frozen=True, slots=True)
class DeliveryResult:
    """The outcome of ONE attempt at one endpoint, whatever the transport was."""

    delivered: bool
    status_code: int | None
    error: str | None = None
    # Which transport produced this. Written into the forensic row's `source`, so a
    # delivery log read six months later says how the lead was supposed to travel.
    channel: str = "http"
    # Whether another attempt could plausibly change the answer. `None` means "decide
    # from the HTTP status" — the webhook path's rules, which are the only ones a status
    # code can express. A transport with no status codes (the sheets append) MUST say,
    # because "no status" would otherwise read as a transport blip and a permanent
    # refusal would climb the ladder three times to reach the same no.
    transient: bool | None = None
    # EXACTLY what went on the wire, for the delivery-body retention (D-23). Reported by
    # the transport rather than rebuilt by the caller, because a body rebuilt from the
    # same inputs is a body that agrees with the mapping and the serializer we HAPPEN to
    # run today — and the whole value of the artifact is that it is what the client's
    # endpoint actually received, mapping renames and all.
    #
    # `repr=False`: this field is personal data, and a dataclass repr is one careless
    # `log.info(..., extra={"result": result})` away from a hard rule 6 violation.
    # Nothing that formats a `DeliveryResult` can print it by accident.
    sent_body: str | None = field(default=None, repr=False)


def secret_fingerprint(secret: str) -> str:
    """First 8 hex of the digest — enough to tell two secrets apart in a support call,
    useless for forging one.

    Lives here rather than beside either config screen because BOTH webhook directions
    need it: outbound endpoints show it for a signing secret they issued, inbound lead
    sources for a shared secret they accept. Two copies would be two answers to "is the
    value in my form vendor the one you hold" the first time somebody changed the
    length.
    """
    return hashlib.sha256(secret.encode()).hexdigest()[:8]


def sign_payload(secret: str, *, timestamp: str, body: str) -> str:
    """`t={ts},v1={hex}` — the timestamp is INSIDE the signed string.

    A signature over the body alone is a bearer token for that body forever. With the
    timestamp signed, a receiver that rejects old timestamps also rejects replays, and
    an attacker cannot move a valid signature onto a fresh timestamp.
    """
    mac = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return f"t={timestamp},v1={mac.hexdigest()}"


def verify_signature(secret: str, *, header: str, body: str, tolerance_s: int = 300) -> bool:
    """The receiver's side, shipped so our docs can point at real code (and so the
    tests assert the scheme rather than our implementation of it)."""
    parts = dict(piece.split("=", 1) for piece in header.split(",") if "=" in piece)
    timestamp, provided = parts.get("t"), parts.get("v1")
    if not timestamp or not provided:
        return False
    try:
        age = abs(int(datetime.now(UTC).timestamp()) - int(timestamp))
    except ValueError:
        return False
    if age > tolerance_s:
        return False
    expected = hmac.new(secret.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256)
    return hmac.compare_digest(expected.hexdigest(), provided)


def build_envelope(
    *, event: str, tenant_id: UUID, delivery_id: UUID, data: dict[str, Any]
) -> dict[str, Any]:
    """OUR envelope, stable across event types (D-23).

    `id` is the delivery id, not the object id, so a receiver deduplicating on it
    deduplicates RETRIES rather than collapsing two genuine updates to one lead.
    """
    return {
        "id": str(delivery_id),
        "event": event,
        "account_id": str(tenant_id),
        "created_at": datetime.now(UTC).isoformat(),
        "data": data,
    }


async def enqueue_event(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    event: str,
    data: dict[str, Any],
) -> int:
    """One object's event, fanned out. The single-row case of `enqueue_events`.

    Kept as the name every producer already calls, and implemented in terms of the
    plural rather than beside it: two fan-outs would be two answers to "which endpoints
    is this event for" and the second one is where `include_raw_phone` gets forgotten.
    """
    return await enqueue_events(session, tenant_id=tenant_id, event=event, rows=(data,))


async def enqueue_events(
    session: AsyncSession,
    *,
    tenant_id: UUID,
    event: str,
    rows: Sequence[dict[str, Any]],
) -> int:
    """Fan ONE event type over n objects out to every active endpoint subscribed to it —
    one outbox row per (object, endpoint), in the caller's transaction.

    One row per endpoint rather than one per event: endpoints fail independently, and a
    shared row would make a dead endpoint retry deliveries that already succeeded
    elsewhere.

    **Plural because a bulk edit is one transaction and n events.** `crm.service`'s bulk
    action moves up to `MAX_BULK_LEADS` leads in a single request, and calling the
    singular form per lead would re-run the endpoint SELECT once per lead — 500 identical
    queries inside one transaction for a set of endpoints that cannot change while it is
    open. The endpoints are read ONCE here and the loop is pure INSERTs.

    **Redaction happens HERE, per endpoint, because the fan-out is the last point that
    still knows which endpoint a payload is for.** The raw phone is a per-endpoint
    opt-in (docs/WEBHOOKS.md §1.2, recorded as `mapping.include_raw_phone`), and a
    caller that masked once before this call could not express it — every endpoint got
    the same body, so the opt-in was documented and unreachable. Masking on this side
    of the fan-out also means a caller that simply passes the domain row cannot leak:
    an endpoint that did not ask never gets a raw number in its outbox row.

    Returns the number of OUTBOX ROWS written, which for a single object is the number of
    endpoints — the meaning `enqueue_event`'s callers already assert on.
    """
    if event not in EVENT_TYPES:
        raise ValueError(f"unknown outbound event: {event}")
    if not rows:
        # No objects changed, so no endpoint is told anything. Returning before the
        # SELECT keeps a bulk action that moved nothing free of a query as well as of
        # deliveries.
        return 0

    # Every kind we can actually deliver, not just `webhook`: a client who picked
    # Google Sheets subscribed to the same events and gets the same fan-out. The kind
    # is NOT copied into the payload — the worker reads it off the endpoint row, which
    # is the only place it can change.
    endpoints = (
        await session.execute(
            text(
                "SELECT w.id, w.mapping FROM outbound_webhooks w WHERE "
                + subscribed_endpoint_sql("w")
            ),
            {"event": event, "kinds": list(DELIVERABLE_KINDS)},
        )
    ).all()

    written = 0
    for endpoint_id, mapping in endpoints:
        opted_in = bool((mapping or {}).get("include_raw_phone"))
        for data in rows:
            await enqueue_outbox(
                session,
                job=OUTBOUND_WEBHOOK_JOB,
                payload={
                    "tenant_id": str(tenant_id),
                    "endpoint_id": str(endpoint_id),
                    "event": event,
                    "data": lead_payload(data, include_raw_phone=opted_in),
                    # Minted HERE, not in the worker: ARQ replays the same payload on
                    # retry, so a worker-side id would mint a new one per attempt and the
                    # "one forensic row per delivery" claim would be false — and a
                    # receiver deduplicating on it would treat every retry as a new event.
                    "delivery_id": str(uuid7()),
                },
            )
            written += 1
    return written


async def load_endpoint(session: AsyncSession, endpoint_id: UUID) -> dict[str, Any] | None:
    """The endpoint as the worker sees it. MUST run inside a `tenant_session`: this is a
    plain select and RLS on `outbound_webhooks` is the whole of its tenant scoping, so a
    neighbour's endpoint id returns None rather than a row (hard rule 1)."""
    row = (
        await session.execute(
            text(
                "SELECT id, url, secret_ref, mapping, active, kind "
                "FROM outbound_webhooks WHERE id = :id"
            ),
            {"id": endpoint_id},
        )
    ).first()
    if row is None or not row[4]:
        return None
    # `secret` is the raw signing secret for a webhook and a secrets-manager REFERENCE
    # for a sheet (DATA-MODEL §6) — the column holds whichever the kind implies, and
    # neither is ever logged.
    return {"id": row[0], "url": row[1], "secret": row[2], "mapping": row[3] or {}, "kind": row[5]}


async def deactivate_endpoint(session: AsyncSession, *, endpoint_id: UUID) -> bool:
    """CAS on the flag (BACKEND-PATTERNS §5); True when THIS call is what changed it.

    Same shape as the inbound twin, `ingest.service.set_active`, deliberately: the two
    directions of D-23 are one surface to a client and answering "disabled" one way and
    "not found" the other for the identical second click is a difference nobody asked
    for. This used to be the route's single UPDATE, whose CAS predicate (`active = true`)
    and existence check were the same statement — so `rowcount == 0` meant either "no
    such endpoint" or "already off", and the second click of Disable was told the
    endpoint did not exist. DELETE is required to be idempotent (RFC 9110 §9.2.2: the
    side effects of N > 1 identical requests are the same as for one), and it was also
    simply a false statement about a row we can see.

    The CAS still runs FIRST and unconditionally, so two concurrent disables both reach
    the database and exactly one of them reports the transition; the SELECT below only
    ever runs after the write lost, and only to name which of the two zero-row facts it
    was. It cannot reintroduce a read-then-write race because it writes nothing.

    MUST run inside a `tenant_session`: both statements are scoped by RLS alone, so a
    neighbour's endpoint id disables nothing and then reads no row — it 404s exactly
    like an id that never existed, which is the answer `ProblemError.not_found`
    documents as deliberate (hard rule 1).
    """
    result = await session.execute(
        text(
            "UPDATE outbound_webhooks SET active = false, updated_at = now() "
            "WHERE id = :id AND active = true"
        ),
        {"id": endpoint_id},
    )
    if rowcount_of(result) == 1:
        return True
    exists = (
        await session.execute(
            text("SELECT 1 FROM outbound_webhooks WHERE id = :id"), {"id": endpoint_id}
        )
    ).first()
    if exists is None:
        raise ProblemError.not_found("Endpoint")
    return False


async def delivery_status(session: AsyncSession, delivery_id: UUID) -> str | None:
    """The recorded status of one delivery, or None if this tenant has no such row.

    Scoped THROUGH `outbound_webhooks` rather than read by primary key, for the same
    reason the client-facing delivery screen is: `webhook_deliveries` carries no RLS
    policy (engine webhooks arrive before a tenant is resolved), so a bare
    `WHERE id = :id` would let one tenant's delivered row answer for another's — and
    for the sheets path that answer SUPPRESSES an append.
    """
    row = (
        await session.execute(
            text(
                "SELECT status FROM webhook_deliveries WHERE id = :id "
                "AND endpoint_id IN (SELECT id FROM outbound_webhooks)"
            ),
            {"id": delivery_id},
        )
    ).first()
    if row is None or row[0] is None:
        return None
    return str(row[0])


async def delivery_body_ref(session: AsyncSession, delivery_id: UUID) -> tuple[str | None, str]:
    """`(payload_ref, event_type)` for one of THIS tenant's deliveries.

    Scoped THROUGH `outbound_webhooks` for the reason `delivery_status` is: this table
    carries no RLS policy, so a bare `WHERE id = :id` would hand one tenant the object
    key of another tenant's CRM payload — and that key is all a reader needs, because
    the object behind it is the personal data. A delivery belonging to somebody else is
    404, indistinguishable from one that never existed (hard rule 1).
    """
    row = (
        await session.execute(
            text(
                "SELECT payload_ref, event_type FROM webhook_deliveries WHERE id = :id "
                "AND direction = 'out' AND endpoint_id IN (SELECT id FROM outbound_webhooks)"
            ),
            {"id": delivery_id},
        )
    ).first()
    if row is None:
        raise ProblemError.not_found("Delivery")
    return (str(row[0]) if row[0] else None), str(row[1] or "")


def apply_mapping(data: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    """Rename our field names to the client's, if they asked us to.

    Absent mapping means our names. A mapping that names a field we did not send drops
    out silently rather than sending a null — a CRM column set to null on every sync is
    worse than a column that is simply not written.
    """
    if not mapping:
        return data
    renamed: dict[str, Any] = {}
    for ours, theirs in mapping.items():
        if ours in data:
            renamed[str(theirs)] = data[ours]
    return renamed


# WHOSE DATA A DELIVERED BODY IS — the question that decides whether we may keep it.
#
# A retained body is personal data with an erasure duty (SEC-COMP §4), and the DPDP
# worker locates a subject through `calls` and `leads`. So the rule is: we retain a body
# only when we can name a row the erasure will find. `call_id` first, because that is
# how a `call.completed` body is located (the erasure matches calls on `from_e164` /
# `to_e164`); `lead_id` otherwise, which is how a `lead.*` body is located.
#
# An event with NEITHER — `campaign.completed`, whose payload is campaign aggregates —
# is not retained at all. That is not an oversight: an object nobody can enumerate for a
# data principal is exactly the breach this store is designed not to become, and
# refusing to write it is stronger than writing it and hoping. The cost is that the one
# event carrying no person's data is also the one with no forensic body, which is the
# right way round.
BODY_SUBJECT_FIELDS: tuple[tuple[str, str], ...] = (("call", "call_id"), ("lead", "lead_id"))


def body_subject(data: dict[str, Any]) -> tuple[str, str] | None:
    """`(subject_type, subject_id)` for a delivered body, or None if we cannot name one.

    Read from OUR field names, so it must run on the payload BEFORE `apply_mapping`
    renames them to the client's — after the rename `lead_id` may be called `Lead Ref`
    and the subject would silently become unnameable for every mapped endpoint.
    """
    for subject_type, key in BODY_SUBJECT_FIELDS:
        value = data.get(key)
        if value not in (None, ""):
            return subject_type, str(value)
    return None


async def record_delivery(
    session: AsyncSession,
    *,
    delivery_id: UUID,
    endpoint_id: UUID,
    event: str,
    status: str,
    attempts: int,
    status_code: int | None,
    channel: str = "http",
    reason: str | None = None,
    payload_ref: str | None = None,
) -> None:
    """Forensic log, upserted by delivery id so retries update one row (SEC-COMP §5).

    `payload_ref` is the object-storage key of the body we sent, and it is the only
    personal data this row reaches — the table itself still holds none. It used to hold
    no reference either, on the argument that the body is reconstructible from the
    domain row; it is not. The domain row is what the lead looks like NOW, after the
    mapping, the masking and any later edit, so "you sent us the wrong lead" was
    answerable with a reconstruction rather than with evidence. The object it names
    carries the retention clock and the erasure duty that come with saying so
    (`workers/storage.delivery_body_key`).

    `COALESCE` on the ref, not assignment: a retry whose body could not be stored must
    not WIPE the reference an earlier attempt succeeded in writing. Best-effort storage
    means the reference can only ever be gained by an attempt, never lost by one.

    `channel` is the transport (`http`, `sheets`). It is the only thing that differs
    between the two endpoint kinds here — ONE log, one row per delivery, one vocabulary
    of statuses (`delivered` / `failed` / `skipped`, WEBHOOKS §1.5) — so the delivery
    screen a client reads does not care which box they ticked.

    `reason` is WHY a failed delivery failed, in OUR vocabulary — an authored refusal
    code (`sheet_not_shared`, `no_credential_ref`) or an exception TYPE, never vendor
    prose and never anything off the payload. It exists because `source` cannot carry
    it: for a webhook `source` is `http_404` and says enough, but for a sheet there is
    no status code, so the column read `sheets` and the client-facing queue could only
    say "an error". A failure a client can fix is worth a column.
    """
    source = f"{channel}_{status_code}" if status_code else channel
    result = await session.execute(
        text(
            "UPDATE webhook_deliveries SET attempts = :attempts, status = :status, "
            "source = :src, reason = :reason, payload_ref = COALESCE(:ref, payload_ref), "
            "last_at = now() WHERE id = :id"
        ),
        {
            "attempts": attempts,
            "status": status,
            "src": source,
            "reason": reason,
            "ref": payload_ref,
            "id": delivery_id,
        },
    )
    if rowcount_of(result) == 0:
        await session.execute(
            text(
                "INSERT INTO webhook_deliveries (id, direction, source, event_type, status, "
                "attempts, endpoint_id, reason, payload_ref, first_at, last_at, created_at) "
                "VALUES (:id, 'out', :src, :event, :status, :attempts, :endpoint, :reason, "
                ":ref, now(), now(), now())"
            ),
            {
                "id": delivery_id,
                "src": source,
                "event": event,
                "status": status,
                "attempts": attempts,
                "endpoint": endpoint_id,
                "reason": reason,
                "ref": payload_ref,
            },
        )


async def deliver(
    *,
    url: str,
    secret: str,
    event: str,
    envelope: dict[str, Any],
    client: httpx.AsyncClient | None = None,
) -> DeliveryResult:
    """One signed POST. Raises nothing — the caller decides what a failure means.

    2xx is success. Everything else (including 3xx: a redirect to an unknown host is
    not a delivery we should follow with a signed body) is a failure the outbox retries.

    `follow_redirects=False` is set on the REQUEST, not only on the client we build:
    a 307 re-sends the body and our signature headers to whatever host the `Location`
    names, and the promise in docs/WEBHOOKS.md §1.5 must not depend on how a caller
    happened to construct the client it passed in.

    **The destination is re-vetted HERE, on every attempt.** `egress_guard` also runs at
    registration, and that check alone is worth little: the endpoint row can be months
    old and the tenant owns the DNS for the name in it, so a record that answered
    publicly when it was registered can answer `127.0.0.1` now (DNS rebinding — the
    time-of-check/time-of-use half that the module docstring argues). This is the last
    line before a lead's name and number go on a socket, so it is where the answer has
    to be current. It runs even when the CALLER supplied the client, because a guard
    with a caller-shaped hole in it is not a guard.

    A refusal is a `DeliveryResult`, never an exception: the worker's contract is that
    this function raises nothing, and the refusal has to land on the client's own
    delivery screen with a reason they can act on. `transient=False` — a destination
    that resolves inside a private network resolves there again in thirty seconds, and
    the retry ladder would only delay the alert.
    """
    try:
        vetted = await assert_public_http_url(url)
    except EgressRefusedError as exc:
        # `exc.code` is one of OUR authored refusal codes (`record_delivery`'s rule for
        # `reason`), never vendor prose and never anything off the payload.
        return DeliveryResult(delivered=False, status_code=None, error=exc.code, transient=False)

    body = json.dumps(envelope, separators=(",", ":"), default=str)
    timestamp = str(int(datetime.now(UTC).timestamp()))
    headers = {
        "Content-Type": "application/json",
        SIGNATURE_HEADER: sign_payload(secret, timestamp=timestamp, body=body),
        TIMESTAMP_HEADER: timestamp,
        EVENT_HEADER: event,
        DELIVERY_HEADER: str(envelope["id"]),
        "User-Agent": "Calevate-Webhooks/1",
    }
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=DELIVERY_TIMEOUT_S, follow_redirects=False)
    try:
        # `vetted.url`, not `url`: the guard parsed and judged the trimmed string, and
        # posting to the untrimmed one would send somewhere it never looked at.
        response = await http.post(
            vetted.url, content=body, headers=headers, follow_redirects=False
        )
        ok = 200 <= response.status_code < 300
        return DeliveryResult(
            delivered=ok,
            status_code=response.status_code,
            error=None if ok else f"HTTP {response.status_code}",
            sent_body=body,
        )
    except httpx.HTTPError as exc:
        # The URL and the error TYPE are safe to log; the body never is.
        #
        # `sent_body` is reported on the FAILURE path too. "You sent us the wrong lead"
        # and "your POST never arrived" are asked about the same delivery, and a record
        # that only exists when the receiver said 200 is missing on exactly the
        # deliveries anybody investigates. The bytes were composed and handed to the
        # socket either way.
        return DeliveryResult(
            delivered=False, status_code=None, error=type(exc).__name__, sent_body=body
        )
    finally:
        if owns_client:
            await http.aclose()


def lead_payload(row: dict[str, Any], *, include_raw_phone: bool) -> dict[str, Any]:
    """What an event carries once the endpoint's own choice is applied.

    `include_raw_phone` is a per-endpoint opt-in, not a default: hard rule 6 is about
    logs, but the same reasoning applies to anything leaving our boundary. A client who
    needs the number in their CRM says so once, in the config row, and that choice is
    auditable. Everyone else gets the masked form the dashboard shows.

    An event with no `phone` at all (every `call.*` event) comes back unchanged — a
    masking pass must not ADD a field the published payload schema never declared.
    """
    payload = dict(row)
    if "phone" in payload and not include_raw_phone:
        masked = redact_mapping({"phone": payload["phone"]})
        payload["phone"] = masked.get("phone")
    return payload


# --- google sheets -------------------------------------------------------------
# The config row is the SAME row a webhook uses (DATA-MODEL §6): `url` names the
# spreadsheet, `secret_ref` is the secrets-manager reference to the service account,
# `mapping` carries the sheet-shaped extras. Nothing here needs a migration.
#
#     {"worksheet": "Leads",
#      "columns":  ["lead_id", "name", "phone", "status"],   <- ORDER LIVES IN A LIST
#      "headers":  {"lead_id": "Lead Ref"},
#      "include_raw_phone": false}

# Google's own id shape: url-safe base64-ish, 44 chars in practice. The floor of 20
# exists so a stray word in the url column cannot be mistaken for a document id.
_SHEET_URL_RE = re.compile(r"/spreadsheets/d/([A-Za-z0-9_-]{20,})")
_SHEET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,}$")

DEFAULT_WORKSHEET = "Leads"

# Appended to every row and named in every header. It is the same id as the envelope's
# `id` and the forensic row's, which is what makes a sheet reconcilable against the
# delivery log by a human — and what a future adapter can read back to close the crash
# window described in `apps/workers/sheets_sync.py`.
SHEET_DELIVERY_HEADER = "Calevate Delivery ID"

# Column ORDER per event, for endpoints that did not choose their own. Only the events
# whose payload shape is published (WEBHOOKS §1.2) appear here: an event with no entry
# and no configured `columns` is REFUSED rather than guessed, because inferring the
# order from one row's keys silently shifts every value the first time a field is
# absent — and a spreadsheet has no per-row schema to catch it.
DEFAULT_SHEET_COLUMNS: dict[str, tuple[str, ...]] = {
    "lead.created": ("lead_id", "name", "phone", "source", "status"),
    "lead.updated": ("lead_id", "name", "phone", "source", "status"),
    "call.completed": (
        "call_id",
        "lead_id",
        "direction",
        "duration_s",
        "outcome",
        "sentiment",
        "summary",
    ),
    # AGGREGATES AND THE CAMPAIGN'S NAME — the one layout here with no person in it.
    # `name` is the CAMPAIGN's, and it sits second for the reason `lead.*` puts the
    # lead's name second: the id identifies the row, the name is what a human scanning
    # the sheet reads. Produced by `apps.workers.campaign_dispatch.emit_campaign_completed`,
    # which is the only writer of these keys.
    "campaign.completed": (
        "campaign_id",
        "name",
        "contacts_total",
        "contacts_reached",
        "completed_at",
    ),
}

# Characters that make a spreadsheet treat a cell as an expression. `=` and `@` are
# Sheets formulas; `+` and `-` are Excel's, which matters the moment the client exports
# to CSV. A lead's name is written by a caller or a web form, so this is untrusted text
# landing in a document a human opens.


def parse_spreadsheet_ref(url: str | None) -> str | None:
    """The spreadsheet id from what the client configured, or None if it is not one.

    Accepts the url they copy out of the browser and a bare id. Refuses everything else:
    appending a client's leads into a document we guessed the identity of is worse than
    not delivering, and the refusal is visible on their delivery screen.
    """
    if not url:
        return None
    candidate = url.strip()
    match = _SHEET_URL_RE.search(candidate)
    if match:
        return match.group(1)
    return candidate if _SHEET_ID_RE.match(candidate) else None


def sheet_worksheet(mapping: dict[str, Any]) -> str:
    """The tab to append to. One default, so an endpoint configured with no worksheet
    lands somewhere predictable rather than wherever the API considers first."""
    worksheet = mapping.get("worksheet")
    if isinstance(worksheet, str) and worksheet.strip():
        return worksheet.strip()
    return DEFAULT_WORKSHEET


def sheet_columns(event: str, mapping: dict[str, Any]) -> tuple[str, ...]:
    """OUR field names, in the order they become columns.

    Read from a JSON **array**, never from object keys: `mapping` is JSONB and Postgres
    stores object keys sorted by length then bytes, so a column order expressed as keys
    comes back scrambled and every row would land under different headings than the
    last. An empty result means "we do not know the order" and the caller must refuse.
    """
    configured = mapping.get("columns")
    if isinstance(configured, list):
        names = tuple(name for name in configured if isinstance(name, str) and name)
        if names:
            return names
    return DEFAULT_SHEET_COLUMNS.get(event, ())


def sheet_header(columns: Sequence[str], mapping: dict[str, Any]) -> list[str]:
    """The header row: the client's own column names where they gave us one.

    Order comes from `columns` (a list); `headers` only renames, so a jsonb object is
    the right shape for it and its key order is irrelevant.

    DISARMED, like every other cell. Both halves of a heading are free strings off the
    endpoint's `mapping` JSONB — `headers` renames, and `columns` supplies the name when
    it does not (`sheet_columns` filters for "a non-empty string", not for a field we
    recognise). Those are operator-configured today rather than client-typed (WEBHOOKS
    §1.2: "ask us to set this up"), which is a smaller blast radius than the data rows
    and not a zero one, and a JSONB column reached by a human editor is precisely the
    one that becomes a self-serve form without anyone re-reading this function.
    `valueInputOption=RAW` on the header write
    (`workers/google_sheets._ensure_header`) already stops Sheets PARSING it, exactly as
    it does for the data rows; `_disarm` is the same belt-and-braces those rows get, and
    it is what survives the client exporting their sheet to CSV and double-clicking it.
    The CSV export states this rule as shared doctrine — "EVERY CELL GOES THROUGH THE
    GUARD, HEADER INCLUDED — the Sheets writer's rule" — and cited this function for it
    while this function was the one exception to it.
    """
    raw = mapping.get("headers")
    headers = raw if isinstance(raw, dict) else {}
    # `SHEET_DELIVERY_HEADER` is ours and cannot lead a formula, but it goes through the
    # same call rather than being appended raw: a renderer applied to "the interesting
    # cells" is how `crm.service.export_leads_csv` left `name` unguarded for a release.
    return [_cell(headers.get(name, name)) for name in columns] + [_cell(SHEET_DELIVERY_HEADER)]


def sheet_row(data: dict[str, Any], columns: Sequence[str], delivery_id: UUID | str) -> list[str]:
    """One row of cells, in column order, ending with the delivery id.

    A field the event did not carry is an EMPTY cell, never `None` — the same reasoning
    as `apply_mapping` not inventing nulls, except that here a missing value would print
    the word "None" into a document a client shows their staff.
    """
    return [_cell(data.get(name)) for name in columns] + [str(delivery_id)]


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):  # bool before int — it is a subclass
        return "true" if value else "false"
    if isinstance(value, str):
        rendered = value
    elif isinstance(value, int | float | Decimal):
        rendered = str(value)
    else:
        rendered = json.dumps(value, separators=(",", ":"), default=str)
    return _disarm(rendered)


def _disarm(rendered: str) -> str:
    """Neutralise spreadsheet formula injection for the SHEETS consumer.

    The leader set is shared with the CSV export (`core.spreadsheet_safety`) so a newly
    discovered dangerous character is added in one place; the RENDERING is not shared,
    because Sheets' apostrophe marker is invisible there and visible in a CSV. That
    module carries the argument and the OWASP sources.
    """
    return disarm_for_sheets(rendered)


__all__ = [
    "BODY_SUBJECT_FIELDS",
    "DEFAULT_SHEET_COLUMNS",
    "DEFAULT_WORKSHEET",
    "DELIVERABLE_KINDS",
    "DELIVERY_HEADER",
    "EVENT_HEADER",
    "EVENT_TYPES",
    "MAX_ATTEMPTS",
    "SHEET_DELIVERY_HEADER",
    "SHEET_KIND",
    "SIGNATURE_HEADER",
    "TIMESTAMP_HEADER",
    "WEBHOOK_KIND",
    "DeliveryResult",
    "apply_mapping",
    "body_subject",
    "build_envelope",
    "deactivate_endpoint",
    "deliver",
    "delivery_body_ref",
    "delivery_status",
    "enqueue_event",
    "enqueue_events",
    "lead_payload",
    "load_endpoint",
    "parse_spreadsheet_ref",
    "record_delivery",
    "secret_fingerprint",
    "sheet_columns",
    "sheet_header",
    "sheet_row",
    "sheet_worksheet",
    "sign_payload",
    "subscribed_endpoint_sql",
    "verify_signature",
]
