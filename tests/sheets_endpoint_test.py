"""The Google Sheets endpoint a client can actually configure, and the seam that decides
whether offering it is honest.

The previous wave shipped the sheets DELIVERY path (`apps/workers/sheets_sync.py`) and
deliberately shipped no route to create an endpoint, on the grounds that offering the
checkbox before a credential path exists recreates the "silently never delivers" defect
the whole feature was fixing. That reasoning was right, and it turned on something the
codebase could not express: transport selection keyed off `app_env == "local"`, which is
not a statement about Google Sheets at all. You cannot gate a client-facing feature on
"are we on a laptop".

`GOOGLE_SHEETS_PROVIDER` is that missing statement, so these tests hold the route to the
rule the previous agent's refusal implies rather than to their conclusion:

1. **The seam decides, not the environment.** A named provider with no adapter refuses
   loudly; the dev sink is refused outside local; unset falls back explicitly.
2. **The route refuses where delivery does not exist.** No provider ⇒ no endpoint, and
   the refusal is RFC-9457 with the machine code as the LAST SEGMENT of `type`.
3. **Nothing this route creates can be silent.** It never accepts and never returns a
   credential, it reports whether one is attached, and every refusal downstream is
   already visible on the client's own delivery screen.
4. **The endpoint stops being invisible.** `list_endpoints` used to filter
   `kind = 'webhook'`, so a sheets row a human had provisioned could fan out, fail and
   alert while the client's own integrations screen showed nothing at all.
5. **Hard rule 1.** An endpoint belongs to a tenant and the RLS-scoped session is what
   proves it — not the principal the handler was handed.
6. **The secret is an opaque `sm://` reference.** Never resolved, never logged, never
   in a response.
7. **The gate is PUBLISHED and is still not the check.**
   `EndpointOptionsOut.sheets_delivery_available` exists so a console does not have to
   learn the refusal by attempting the create, and the route refuses anyway — including
   for a client that read `true` a moment before an operator turned Sheets off.

CONCURRENCY: every test mints its own tenant and touches no global row, so this file can
run beside the other suites on the shared Postgres.
"""

from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest
from apps.api.admin import service as admin_service
from apps.api.core.context import Principal
from apps.api.core.errors import ProblemError
from apps.api.core.logging import JsonFormatter
from apps.api.core.settings import get_settings
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import service
from apps.api.integrations.routes import (
    CreateSheetEndpointIn,
    EndpointOptionsOut,
    SheetEndpointOut,
    create_sheets_endpoint,
    deactivate_endpoint,
    endpoint_options,
    list_deliveries,
    list_endpoints,
)
from apps.api.main import app
from apps.workers import outbound_webhooks, sheets_sync
from apps.workers.outbound_webhooks import deliver_outbound_webhook
from apps.workers.sheets_sync import (
    ConsoleSheetsTransport,
    SheetAppend,
    UnconfiguredSheetsTransport,
    get_sheets_transport,
    sheets_delivery_available,
)
from calevate_shared.config import Settings
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from starlette.requests import Request

# A real-shaped Google spreadsheet id (44 url-safe chars). Names a document nobody owns.
SHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"

# A secrets-manager REFERENCE, which is all `secret_ref` may ever hold (DATA-MODEL §6).
# It is not a credential and cannot be turned into one — that is the point of the column.
CREDENTIAL_REF = "sm://calevate/local/tenants/test/google-service-account"

REPO_ROOT = Path(__file__).resolve().parent.parent


# --------------------------------------------------------------------------------
# Seeding
# --------------------------------------------------------------------------------


async def _tenant() -> UUID:
    created = await admin_service.create_organization(
        name="Sheet Desk",
        slug=f"sheetcfg-{uuid.uuid4().hex[:8]}",
        vertical_template="clinic",
        billing_email=None,
        language="te-IN",
        created_by=None,
    )
    return UUID(str(created["id"]))


def _request() -> Request:
    """The audit row's `ip` comes off the request, so the route now takes one. Built
    rather than faked: `write_audit` reads `request.client`, and a stub that happened to
    have the attribute would stop matching the day it reads another."""
    return Request(
        {
            "type": "http",
            "method": "DELETE",
            "path": "/v1/integrations/endpoints",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
        }
    )


def _principal(tenant_id: UUID) -> Principal:
    return Principal(
        realm="client",
        user_id=uuid.uuid4(),
        clerk_user_id="u",
        tenant_id=tenant_id,
        role="owner",
        impersonating=False,
    )


def _sheets_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """A deployment where Sheets delivery exists. The dev sink is the only transport
    that does today, so `local` + `console` is what "the provider is configured" means
    until an adapter lands."""
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "local")
    monkeypatch.setattr(settings, "google_sheets_provider", "console")


def _sheets_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "google_sheets_provider", None)


async def _endpoint_rows(tenant_id: UUID) -> list[tuple[Any, ...]]:
    async with tenant_session(tenant_id) as session:
        rows = (
            await session.execute(
                text(
                    "SELECT id, kind, url, secret_ref, events, mapping, active "
                    "FROM outbound_webhooks ORDER BY created_at"
                )
            )
        ).all()
    return [tuple(row) for row in rows]


async def _seed_webhook(tenant_id: UUID) -> UUID:
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "active, created_at, updated_at) VALUES (:id, :tid, 'webhook', :url, :secret, "
                ":events, true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "url": "https://crm.example/hook",
                "secret": "whsec_test_secret_value",
                "events": ["lead.created"],
            },
        )
    return endpoint_id


async def _seed_sheet(tenant_id: UUID, *, secret_ref: str | None = CREDENTIAL_REF) -> UUID:
    """A sheets endpoint as an OPERATOR provisions one today — by hand, with a
    secrets-manager reference the client could never supply."""
    endpoint_id = uuid7()
    async with tenant_session(tenant_id) as session:
        await session.execute(
            text(
                "INSERT INTO outbound_webhooks (id, tenant_id, kind, url, secret_ref, events, "
                "mapping, active, created_at, updated_at) VALUES (:id, :tid, 'google_sheets', "
                ":url, :secret, :events, CAST(:mapping AS jsonb), true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "url": SHEET_ID,
                "secret": secret_ref,
                "events": ["lead.created"],
                "mapping": json.dumps({"worksheet": "Leads"}),
            },
        )
    return endpoint_id


# --------------------------------------------------------------------------------
# 1. The provider seam — the setting the route is allowed to gate on
# --------------------------------------------------------------------------------


def test_the_provider_is_a_settings_field_and_env_example_declares_it() -> None:
    """`Settings` is `extra="forbid"`: a key in `.env.example` with no field crashes
    every process that loads a `.env`, and a field with no key is config nobody knows
    to set. `scripts/check_env_parity.py` is the guardrail; this names the key so the
    failure reads as a decision rather than a mystery.

    WHERE THE DECLARATION LIVES CHANGED (PLATFORM-CONFIG §4, D-95): `.env.example` is
    now the 8-key bootstrap set and this key is one of the 50 an operator sets at
    `admin.calevate.tech/ops`. The assertion follows the declaration rather than the
    file — same question, current answer."""
    from apps.api.core.platform_config import managed_fields

    assert "google_sheets_provider" in Settings.model_fields
    assert "google_sheets_provider" in managed_fields()


def test_local_without_a_provider_still_uses_the_dev_sink(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The fallback is now EXPLICIT rather than the whole rule."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_sheets_provider", None)
    monkeypatch.setattr(settings, "app_env", "local")
    assert isinstance(get_sheets_transport(), ConsoleSheetsTransport)


async def test_a_named_provider_refuses_rather_than_pretending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No Google service account exists and no adapter was written against one. Naming
    one in config must fail loudly — a silent no-op looks exactly like a working
    integration, which is the failure this whole module exists to prevent."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_sheets_provider", "gspread")
    monkeypatch.setattr(settings, "app_env", "prod")
    transport = get_sheets_transport()
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
    assert result.reason.startswith("provider_not_implemented")
    assert result.retryable is False, "a missing adapter is not a blip"


async def test_a_named_provider_is_refused_in_local_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The behaviour change that makes the setting worth having: selection reads the
    PROVIDER, and `app_env` is only the fallback. Before this, `local` meant "sheets
    work" no matter what the config said."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_sheets_provider", "gspread")
    monkeypatch.setattr(settings, "app_env", "local")
    transport = get_sheets_transport()
    assert isinstance(transport, UnconfiguredSheetsTransport)


def test_the_dev_sink_is_refused_outside_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """`GOOGLE_SHEETS_PROVIDER=console` in staging would report every lead appended
    forever, to a terminal nobody reads. Operator error, but the kind that hides the
    failure it causes."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_sheets_provider", "console")
    monkeypatch.setattr(settings, "app_env", "staging")
    transport = get_sheets_transport()
    assert isinstance(transport, UnconfiguredSheetsTransport)
    assert sheets_delivery_available() is False


def test_a_real_environment_without_a_provider_reports_no_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sheets_absent(monkeypatch)
    assert isinstance(get_sheets_transport(), UnconfiguredSheetsTransport)
    assert sheets_delivery_available() is False


def test_availability_is_the_answer_the_worker_would_get(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One selector, asked twice. A config surface that decided for itself whether
    sheets work would eventually disagree with the worker, and the disagreement would
    be "the screen says configured and the sheet stays empty"."""
    _sheets_enabled(monkeypatch)
    assert sheets_delivery_available() is True
    assert isinstance(get_sheets_transport(), ConsoleSheetsTransport)


# --------------------------------------------------------------------------------
# 2. The gate: no delivery path, no endpoint
# --------------------------------------------------------------------------------


async def test_a_deployment_with_no_sheets_provider_refuses_to_create_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The previous agent's argument, kept — and made executable. Creating an endpoint
    where nothing can ever append to it is the checkbox that lies; the client is told
    so at the moment they ask, not by an empty spreadsheet a week later."""
    _sheets_absent(monkeypatch)
    tenant_id = await _tenant()

    with pytest.raises(ProblemError) as excinfo:
        async with tenant_session(tenant_id) as session:
            await create_sheets_endpoint(
                CreateSheetEndpointIn(spreadsheet=SHEET_URL, events=["lead.created"]),
                session,
                _principal(tenant_id),
            )

    problem = excinfo.value.as_problem()
    assert problem["status"] == 422
    assert problem["type"].rsplit("/", 1)[-1] == "sheets_delivery_unavailable", problem["type"]
    assert "code" not in problem, "RFC-9457 has no `code` key — the code is the last segment"
    assert problem["remediation"], "a refusal a client can act on names the next step"
    assert await _endpoint_rows(tenant_id) == [], "a refused create writes nothing"


async def test_the_refusal_never_names_the_provider_or_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`detail` is user-facing (RFC-9457, user-safe messages). Which provider we have
    not integrated and which environment this is are internals."""
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "prod")
    monkeypatch.setattr(settings, "google_sheets_provider", "some-vendor")
    tenant_id = await _tenant()

    with pytest.raises(ProblemError) as excinfo:
        async with tenant_session(tenant_id) as session:
            await create_sheets_endpoint(
                CreateSheetEndpointIn(spreadsheet=SHEET_URL, events=["lead.created"]),
                session,
                _principal(tenant_id),
            )
    body = json.dumps(excinfo.value.as_problem())
    assert "some-vendor" not in body and "prod" not in body


# --------------------------------------------------------------------------------
# 3. What the route creates when delivery does exist
# --------------------------------------------------------------------------------


async def test_a_client_can_configure_a_sheet_where_delivery_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        created = await create_sheets_endpoint(
            CreateSheetEndpointIn(
                spreadsheet=SHEET_URL,
                events=["lead.created", "call.completed"],
                worksheet="Enquiries",
            ),
            session,
            _principal(tenant_id),
        )

    assert created.kind == service.SHEET_KIND
    assert created.spreadsheet_id == SHEET_ID, "the url is normalised to the document id"
    assert created.worksheet == "Enquiries"
    assert created.events == ["lead.created", "call.completed"]
    assert created.active is True

    rows = await _endpoint_rows(tenant_id)
    assert len(rows) == 1
    _id, kind, url, secret_ref, events, mapping, active = rows[0]
    assert kind == "google_sheets"
    assert url == SHEET_ID, "stored canonical — a #gid fragment must not read as a tab"
    assert secret_ref is None
    assert list(events) == ["lead.created", "call.completed"]
    assert mapping == {"worksheet": "Enquiries"}
    assert active is True


async def test_the_route_reports_that_no_credential_is_attached_yet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The honest state, stated at the moment of configuring rather than discovered
    from an empty spreadsheet. A client cannot supply a secrets-manager reference —
    only an operator can — so every endpoint this route creates comes back with
    `credential_attached: false`, computed from what was written to `secret_ref` rather
    than hardcoded, so the day the route can attach one the answer changes with it."""
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        created = await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_ID, events=["lead.created"]),
            session,
            _principal(tenant_id),
        )
    assert created.credential_attached is False


async def test_the_default_worksheet_is_the_one_the_worker_would_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        created = await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_ID, events=["lead.created"]),
            session,
            _principal(tenant_id),
        )
        # A tab name that is only whitespace is the same as not naming one — storing it
        # would leave a config row whose mapping disagrees with the tab we append to.
        blank = await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_ID, events=["lead.created"], worksheet="   "),
            session,
            _principal(tenant_id),
        )
    assert created.worksheet == service.DEFAULT_WORKSHEET
    assert blank.worksheet == service.DEFAULT_WORKSHEET
    rows = await _endpoint_rows(tenant_id)
    assert [row[5] for row in rows] == [None, None], (
        "an unconfigured worksheet stores nothing, not a copy of the default"
    )


async def test_a_url_that_is_not_a_spreadsheet_is_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Appending a client's leads into a document we guessed the identity of is worse
    than not delivering. The same parser the worker uses decides."""
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()

    for candidate in ("https://evil.example/steal", "not-a-sheet", "1234"):
        with pytest.raises(ProblemError) as excinfo:
            async with tenant_session(tenant_id) as session:
                await create_sheets_endpoint(
                    CreateSheetEndpointIn(spreadsheet=candidate, events=["lead.created"]),
                    session,
                    _principal(tenant_id),
                )
        assert excinfo.value.as_problem()["type"].rsplit("/", 1)[-1] == "invalid_spreadsheet_ref"
    assert await _endpoint_rows(tenant_id) == []


async def test_an_event_with_no_column_order_is_refused_at_configuration_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`sheet_columns` refuses at DELIVERY time rather than guessing an order. Asking
    the same question at configuration time turns a per-lead failed delivery into one
    answer at the moment the client can still choose a different event.

    THE COLUMN ORDER IS MONKEYPATCHED AWAY rather than named from `EVENT_TYPES`, and
    that is the change `campaign.completed` forced. It was the one subscribable event
    with no layout, so this test used it as the specimen — and giving it a producer meant
    giving it a layout, which left the refusal reachable by no event at all. Deleting the
    test would delete the guard on the next event somebody adds without one; monkeypatch
    keeps `create_sheets_endpoint`'s real refusal under test with a real event name and
    an empty layout, which is exactly the state that next event will arrive in.
    """
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()
    monkeypatch.delitem(service.DEFAULT_SHEET_COLUMNS, "campaign.completed")

    with pytest.raises(ProblemError) as excinfo:
        async with tenant_session(tenant_id) as session:
            await create_sheets_endpoint(
                CreateSheetEndpointIn(
                    spreadsheet=SHEET_ID, events=["lead.created", "campaign.completed"]
                ),
                session,
                _principal(tenant_id),
            )
    problem = excinfo.value.as_problem()
    assert problem["type"].rsplit("/", 1)[-1] == "sheet_column_order_unknown"
    assert "campaign.completed" in problem["detail"], "it says WHICH event it cannot write"
    assert await _endpoint_rows(tenant_id) == []


async def test_the_route_neither_accepts_nor_returns_a_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A client cannot be allowed to name a secrets-manager path: `sm://` references
    are a namespace over OUR secrets, so accepting one from a request body is a
    tenancy hole wearing a config field's clothes. And nothing this route returns is
    ever key material — there is no field for it."""
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()

    assert "secret" not in CreateSheetEndpointIn.model_fields
    assert "secret_ref" not in CreateSheetEndpointIn.model_fields
    with pytest.raises(ValidationError):
        CreateSheetEndpointIn(
            spreadsheet=SHEET_ID, events=["lead.created"], secret_ref=CREDENTIAL_REF
        )

    async with tenant_session(tenant_id) as session:
        created = await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_ID, events=["lead.created"]),
            session,
            _principal(tenant_id),
        )
    body = created.model_dump_json()
    assert "sm://" not in body
    assert not [name for name in SheetEndpointOut.model_fields if "secret" in name]


async def test_what_the_route_creates_is_a_real_subscriber(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Not a decoration: the row it writes is the row `enqueue_event` fans out to, so
    a configured sheet is on the same footing as a webhook from the first lead."""
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_ID, events=["lead.created"]),
            session,
            _principal(tenant_id),
        )
    async with tenant_session(tenant_id) as session:
        fanned = await service.enqueue_event(
            session, tenant_id=tenant_id, event="lead.created", data={"lead_id": "1"}
        )
    assert fanned == 1


# --------------------------------------------------------------------------------
# 4. The endpoints screen stops hiding half the schema
# --------------------------------------------------------------------------------


async def test_a_sheets_endpoint_is_visible_on_the_clients_integrations_screen() -> None:
    """The defect the hardcoded `kind = 'webhook'` filter caused: an operator-provisioned
    sheets row fanned out, failed, and alerted, while the screen the client opens to
    understand their integrations showed nothing at all — so they could not even see
    the thing producing the failures, let alone turn it off."""
    tenant_id = await _tenant()
    webhook_id = await _seed_webhook(tenant_id)
    sheet_id = await _seed_sheet(tenant_id)

    async with tenant_session(tenant_id) as session:
        listed = await list_endpoints(session, _=None)  # type: ignore[arg-type]

    by_id = {row.id: row for row in listed}
    assert set(by_id) == {webhook_id, sheet_id}
    assert by_id[webhook_id].kind == "webhook"
    assert by_id[sheet_id].kind == "google_sheets"


async def test_the_client_can_turn_off_what_they_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other half of being visible. `DELETE` never filtered by kind, but the id it
    needs was only discoverable through a list that hid sheets rows — so a client could
    configure a sheet and then have no way to reach it again."""
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        created = await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_ID, events=["lead.created"]),
            session,
            _principal(tenant_id),
        )
    async with tenant_session(tenant_id) as session:
        await deactivate_endpoint(created.id, session, _request(), _principal(tenant_id))

    async with tenant_session(tenant_id) as session:
        listed = await list_endpoints(session, _=None)  # type: ignore[arg-type]
        fanned = await service.enqueue_event(
            session, tenant_id=tenant_id, event="lead.created", data={"lead_id": "1"}
        )
    assert [row.active for row in listed] == [False]
    assert fanned == 0, "a deactivated sheet stops being a subscriber"


async def test_the_row_the_route_writes_is_the_row_the_worker_reads(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam between the two halves of this feature, exercised rather than assumed.

    A create route that stored a shape the delivery worker could not parse would look
    perfect from either side alone. So: configure through the route, deliver through
    the worker, and assert the refusal is the CREDENTIAL one — which means the
    spreadsheet reference, the worksheet and the column order all resolved, and the one
    thing missing is the one thing a client cannot supply.
    """
    _sheets_enabled(monkeypatch)
    fired: list[str] = []
    monkeypatch.setattr(outbound_webhooks, "alert", lambda stage, code, **kw: fired.append(code))
    tenant_id = await _tenant()

    async with tenant_session(tenant_id) as session:
        created = await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_URL, events=["lead.created"]),
            session,
            _principal(tenant_id),
        )

    delivery_id = uuid7()
    outcome = await deliver_outbound_webhook(
        {"job_try": 1},
        {
            "tenant_id": str(tenant_id),
            "endpoint_id": str(created.id),
            "event": "lead.created",
            "data": {"lead_id": "1", "name": "Ravi Kumar", "phone": "[redacted]"},
            "delivery_id": str(delivery_id),
        },
    )
    assert outcome == f"rejected {sheets_sync.NO_CREDENTIAL_REF_REASON}"
    assert fired == ["outbound_webhook_exhausted"], "un-deliverable is never silent"

    async with tenant_session(tenant_id) as session:
        visible = await list_deliveries(session, limit=50, _=None)  # type: ignore[arg-type]
    mine = [row for row in visible if row.id == delivery_id]
    assert [row.status for row in mine] == ["failed"], "and the client can see it"


async def test_the_listed_sheet_says_a_credential_is_attached_without_disclosing_it() -> None:
    """`secret_ref` on a sheets row is a secrets-manager REFERENCE, not a signing
    secret. The fingerprint therefore answers exactly one question — is a credential
    attached — and the reference itself never leaves the database."""
    tenant_id = await _tenant()
    attached = await _seed_sheet(tenant_id)
    bare = await _seed_sheet(tenant_id, secret_ref=None)

    async with tenant_session(tenant_id) as session:
        listed = await list_endpoints(session, _=None)  # type: ignore[arg-type]

    by_id = {row.id: row for row in listed}
    assert by_id[attached].secret_fingerprint is not None
    assert by_id[bare].secret_fingerprint is None
    body = json.dumps([row.model_dump(mode="json") for row in listed])
    assert "sm://" not in body and CREDENTIAL_REF not in body


async def test_no_credential_reference_reaches_a_log_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Asserted through the real `JsonFormatter`, because that is what production
    writes: a record whose extras look clean can still stringify a row into `msg`."""
    tenant_id = await _tenant()
    await _seed_sheet(tenant_id)
    formatter = JsonFormatter()

    with caplog.at_level(logging.DEBUG):
        async with tenant_session(tenant_id) as session:
            await list_endpoints(session, _=None)  # type: ignore[arg-type]

    rendered = "\n".join(formatter.format(record) for record in caplog.records)
    assert CREDENTIAL_REF not in rendered
    assert SHEET_ID not in rendered, "the spreadsheet id is a capability, not a log field"


# --------------------------------------------------------------------------------
# 5. Hard rule 1 — the RLS-scoped session is what proves ownership
# --------------------------------------------------------------------------------


@pytest.mark.rls
async def test_another_tenants_endpoints_are_zero_rows_on_this_screen(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sheets_enabled(monkeypatch)
    owner = await _tenant()
    neighbour = await _tenant()

    async with tenant_session(owner) as session:
        created = await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_ID, events=["lead.created"]),
            session,
            _principal(owner),
        )

    async with tenant_session(owner) as session:
        mine = await list_endpoints(session, _=None)  # type: ignore[arg-type]
    async with tenant_session(neighbour) as session:
        theirs = await list_endpoints(session, _=None)  # type: ignore[arg-type]

    assert [row.id for row in mine] == [created.id]
    assert created.id not in {row.id for row in theirs}
    assert theirs == [], "zero rows, not a filtered view of someone else's config"


@pytest.mark.rls
async def test_the_session_not_the_principal_decides_whose_endpoint_this_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The handler writes `principal.tenant_id`, and that alone would make a forged or
    stale principal enough to plant an endpoint in someone else's account. It is not:
    the INSERT runs under the session's GUC and the FORCEd policy on
    `outbound_webhooks` refuses a row whose tenant is not the session's."""
    _sheets_enabled(monkeypatch)
    victim = await _tenant()
    attacker = await _tenant()

    with pytest.raises(DBAPIError) as excinfo:
        async with tenant_session(attacker) as session:
            await create_sheets_endpoint(
                CreateSheetEndpointIn(spreadsheet=SHEET_ID, events=["lead.created"]),
                session,
                _principal(victim),
            )
    assert "row-level security" in str(excinfo.value).lower(), str(excinfo.value)
    assert await _endpoint_rows(victim) == []
    assert await _endpoint_rows(attacker) == []


# --------------------------------------------------------------------------------
# 6. The capability the console renders from — published, and still not the check
# --------------------------------------------------------------------------------
#
# Two defects the integrations screen found and correctly refused to fix from the
# frontend:
#
# AD1. `GET /v1/integrations/events` returned `dict[str, list[str]]`, so
#      `openapi-typescript` produced a bare index signature and `events` was not a NAMED
#      field — the one read on that screen `tsc` could not check. The fix is a declared
#      model, exactly as `SubjectExportOut` replaced a free-form dict.
# AD2. Nothing published `sheets_delivery_available()`, so a screen could only discover
#      the deployment's refusal BY ATTEMPTING the create. The fix follows
#      `KycRecordOut.number_purchase_available`: a boolean on the read the screen already
#      makes, computed from the SAME selector the write route asks.
#
# The third test in this section is the one that matters most, and it is what a sabotage
# of the screen has to trip: publishing a capability does not move the decision. The
# route refuses on its own, from its own read, no matter what any client believes.


def test_the_events_response_is_a_named_model_not_an_index_signature() -> None:
    """AD1, pinned where it actually bites: the generated OpenAPI.

    An inline `{"additionalProperties": {...}}` schema is what produced a TypeScript
    index signature, and a client cannot name a field an index signature does not have.
    Asserting the `$ref` and its properties fails the moment somebody returns a bare
    dict from this route again — which is the only way the defect comes back.
    """
    schema = app.openapi()
    media = schema["paths"]["/v1/integrations/events"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert "$ref" in media, f"an inline schema is an index signature downstream: {media}"

    model = schema["components"]["schemas"][media["$ref"].rsplit("/", 1)[-1]]
    assert set(model["properties"]) == {"events", "sheets_delivery_available"}
    # Both REQUIRED: an optional field is `T | undefined` in the generated client, which
    # hands every caller back the same "is it missing or is it false" question the index
    # signature created.
    assert set(model["required"]) == {"events", "sheets_delivery_available"}
    assert model["properties"]["events"]["items"] == {"type": "string"}, (
        "the catalogue is the RUNNING deployment's list; narrowing it to this build's "
        "literal union would make a console unable to report an event it cannot offer"
    )


async def test_the_catalogue_is_the_list_the_create_routes_validate_against(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _sheets_enabled(monkeypatch)
    options = await endpoint_options(_principal(await _tenant()))
    assert isinstance(options, EndpointOptionsOut)
    assert options.events == list(service.EVENT_TYPES)


async def test_the_capability_is_true_exactly_where_the_create_route_succeeds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The two halves of "can I use this form" agree, because they are one selector.

    Asserting the boolean alone would pass just as well against a hardcoded `True`; the
    create in the same test is what makes it a statement about the route.
    """
    _sheets_enabled(monkeypatch)
    tenant_id = await _tenant()

    options = await endpoint_options(_principal(tenant_id))
    assert options.sheets_delivery_available is True

    async with tenant_session(tenant_id) as session:
        created = await create_sheets_endpoint(
            CreateSheetEndpointIn(spreadsheet=SHEET_URL, events=["lead.created"]),
            session,
            _principal(tenant_id),
        )
    assert isinstance(created, SheetEndpointOut)


async def test_the_capability_is_false_exactly_where_the_create_route_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The state EVERY deployment is in today, and the reason the field exists: the
    screen can now say so before someone fills a form in, instead of learning it from a
    refusal."""
    _sheets_absent(monkeypatch)
    tenant_id = await _tenant()

    options = await endpoint_options(_principal(tenant_id))
    assert options.sheets_delivery_available is False
    # The catalogue is unaffected — the webhook form the refusal recommends is built
    # from it, so a false capability must not empty it.
    assert options.events == list(service.EVENT_TYPES)

    with pytest.raises(ProblemError) as excinfo:
        async with tenant_session(tenant_id) as session:
            await create_sheets_endpoint(
                CreateSheetEndpointIn(spreadsheet=SHEET_URL, events=["lead.created"]),
                session,
                _principal(tenant_id),
            )
    assert excinfo.value.as_problem()["type"].rsplit("/", 1)[-1] == "sheets_delivery_unavailable"


async def test_a_client_that_believes_sheets_are_available_is_still_refused(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE invariant the published capability must not weaken.

    A console reads this once and caches it for half an hour (it is a deployment
    constant, not an account fact). If an operator turns Sheets off inside that window,
    the screen is optimistic and WRONG — and the create still has to be refused, from
    the route's own read, writing nothing. The capability is a hint for rendering; it
    never becomes the check.
    """
    tenant_id = await _tenant()
    _sheets_enabled(monkeypatch)
    believed = await endpoint_options(_principal(tenant_id))
    assert believed.sheets_delivery_available is True

    _sheets_absent(monkeypatch)
    with pytest.raises(ProblemError) as excinfo:
        async with tenant_session(tenant_id) as session:
            await create_sheets_endpoint(
                CreateSheetEndpointIn(spreadsheet=SHEET_URL, events=["lead.created"]),
                session,
                _principal(tenant_id),
            )
    assert excinfo.value.as_problem()["type"].rsplit("/", 1)[-1] == "sheets_delivery_unavailable"
    assert await _endpoint_rows(tenant_id) == [], "a refused create writes nothing"
