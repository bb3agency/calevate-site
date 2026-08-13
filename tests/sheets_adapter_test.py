"""The Google Sheets ADAPTER — the vendor half of D-23 (`apps/workers/google_sheets.py`).

`tests/sheets_sync_test.py` holds the seam: one delivery log, one ladder, one definition
of "delivered", proven against a recording stand-in. This file holds the thing that
actually talks to Google, and it exists to pin four claims the seam cannot make:

1. **An append is not idempotent and we do not pretend otherwise.** Sheets v4 has no
   request key, so a retry that follows an accepted-but-uncommitted append MUST look
   before it writes. The load-bearing test is `test_retry_finds_its_own_row_and_does_not
   _append_again`: sabotage the probe and a lead appears twice in a document a human
   reads.
2. **A failed probe is a refusal, not a shrug.** If we cannot read the sheet we do not
   append — delaying a lead is recoverable, duplicating one is not.
3. **Errors are part of the interface.** Every Google status maps to ONE authored reason
   code (never vendor prose), the permanent ones do not climb the retry ladder, and the
   reason reaches the client's own needs-attention queue as a sentence they can act on.
4. **Hard rules 1 and 6.** A neighbour tenant sees none of it, and no cell, header,
   spreadsheet id, credential or token reaches a log line.

Everything runs against `httpx.MockTransport`, so the URL, the query parameters and the
JSON body are the real ones httpx would have put on the wire — a hand-written stand-in
cannot get a range wrong, and getting the range wrong is the failure mode here.

NO NETWORK, NO GOOGLE PROJECT, NO REAL KEY: the RSA key below is generated in-process
and exists only to prove the assertion is signed with the key we were handed.

CONCURRENCY: every test mints its own tenant, so this file runs beside the other suites.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import parse_qs, unquote
from uuid import UUID

import httpx
import jwt
import pytest
from apps.api.admin import service as admin_service
from apps.api.core.logging import JsonFormatter, configure_logging
from apps.api.core.settings import get_settings
from apps.api.crm import attention
from apps.api.db.base import uuid7
from apps.api.db.session import tenant_session
from apps.api.integrations import service
from apps.workers import google_sheets, outbound_webhooks, sheets_sync
from apps.workers.google_sheets import (
    AUTH_FAILED_REASON,
    CREDENTIAL_REF_PREFIX,
    CREDENTIAL_REF_UNKNOWN_REASON,
    CREDENTIAL_UNRESOLVABLE_REASON,
    DEPLOYMENT_CREDENTIAL_NAME,
    PROBE_FAILED_REASON,
    RATE_LIMITED_REASON,
    SCOPE,
    SHEET_NOT_SHARED_REASON,
    SPREADSHEET_NOT_FOUND_REASON,
    UNAVAILABLE_REASON,
    WORKSHEET_REJECTED_REASON,
    GoogleSheetsTransport,
    a1_sheet,
    column_letter,
    credential_name,
    parse_service_account,
)
from apps.workers.sheets_sync import AppendStatus, SheetAppend
from arq import Retry
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import text

SHEET_ID = "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgvE2upms"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=0"
# The ONE reference this deployment can resolve. Anything else is an operator error and
# is refused rather than quietly served by "the only key we have".
CREDENTIAL_REF = f"{CREDENTIAL_REF_PREFIX}{DEPLOYMENT_CREDENTIAL_NAME}"

SERVICE_ACCOUNT_EMAIL = "calevate-sheets@calevate-test.iam.gserviceaccount.com"


# --------------------------------------------------------------------------------
# A key, and a Google
# --------------------------------------------------------------------------------


def _key_pair() -> tuple[str, Any]:
    """A throwaway RSA key. 2048 bits because that is what Google issues, and because a
    test that signed with something Google would reject would prove nothing."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    return pem, key.public_key()


_PRIVATE_PEM, _PUBLIC_KEY = _key_pair()


def _credential_json(**over: Any) -> str:
    payload: dict[str, Any] = {
        "type": "service_account",
        "client_email": SERVICE_ACCOUNT_EMAIL,
        "private_key": _PRIVATE_PEM,
        "private_key_id": "kid-1",
        "token_uri": google_sheets.TOKEN_URL,
    }
    payload.update(over)
    return json.dumps(payload)


class FakeGoogle:
    """Google, as far as httpx is concerned. Records what we actually sent.

    Deliberately NOT a spreadsheet simulator: it holds the two facts an append depends
    on — what is in row 1 and what is in the delivery-id column — and answers with the
    statuses the real API answers with. Anything more would be testing the fake.
    """

    def __init__(self) -> None:
        self.token_requests: list[dict[str, list[str]]] = []
        self.appends: list[httpx.Request] = []
        self.header_writes: list[httpx.Request] = []
        self.reads: list[str] = []
        self.row_one: list[str] = []
        self.delivery_column: list[str] = []
        self.token_status = 200
        self.append_status = 200
        self.read_status = 200
        self.write_status = 200

    def handler(self, request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            self.token_requests.append(parse_qs(request.content.decode()))
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "ya29.test-token", "expires_in": 3599})

        path = unquote(str(request.url.path))
        if request.method == "POST" and path.endswith(":append"):
            self.appends.append(request)
            if self.append_status != 200:
                return httpx.Response(self.append_status, json={"error": {"message": "no"}})
            body = json.loads(request.content)
            for row in body["values"]:
                self.delivery_column.append(str(row[-1]))
            return httpx.Response(
                200,
                json={
                    "spreadsheetId": SHEET_ID,
                    "tableRange": "Leads!A1:F1",
                    "updates": {"updatedRange": "Leads!A2:F2", "updatedRows": 1},
                },
            )

        if request.method == "PUT":
            self.header_writes.append(request)
            if self.write_status != 200:
                return httpx.Response(self.write_status, json={"error": {"message": "no"}})
            self.row_one = list(json.loads(request.content)["values"][0])
            self.delivery_column = [self.row_one[-1], *self.delivery_column]
            return httpx.Response(200, json={"updatedRange": "Leads!A1:F1", "updatedCells": 6})

        if request.method == "GET":
            a1 = path.rsplit("/values/", 1)[-1]
            self.reads.append(a1)
            if self.read_status != 200:
                return httpx.Response(self.read_status, json={"error": {"message": "no"}})
            if a1.endswith("!1:1"):
                return httpx.Response(200, json={"values": [self.row_one]} if self.row_one else {})
            return httpx.Response(
                200,
                json={"values": [self.delivery_column]} if self.delivery_column else {},
            )

        raise AssertionError(f"unexpected call to Google: {request.method} {path}")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


@pytest.fixture(autouse=True)
def _clean_caches() -> Any:
    """The token and header caches are process-level on purpose (one token an hour, not
    one a lead). That makes them shared state between tests, so every test starts from
    cold — otherwise the second test in this file would silently skip the header path."""
    google_sheets.reset_caches()
    yield
    google_sheets.reset_caches()


def _request(**over: Any) -> SheetAppend:
    fields: dict[str, Any] = {
        "spreadsheet_id": SHEET_ID,
        "worksheet": "Leads",
        "header": ("Lead", "Name", "Phone", "Source", "Status", service.SHEET_DELIVERY_HEADER),
        "values": ("lead-1", "Ravi Kumar", "+91 98765 ****", "webhook", "new", str(uuid7())),
        "credential_ref": CREDENTIAL_REF,
    }
    fields.update(over)
    return SheetAppend(**fields)


async def _append(fake: FakeGoogle, request: SheetAppend | None = None) -> Any:
    async with fake.client() as client:
        transport = GoogleSheetsTransport(_credential_json(), client=client)
        return await transport.append(request or _request())


# --------------------------------------------------------------------------------
# 1. Auth: the assertion is a real RS256 JWT, and it is minted once
# --------------------------------------------------------------------------------


async def test_the_assertion_is_signed_with_our_key_and_scoped_to_sheets() -> None:
    fake = FakeGoogle()
    await _append(fake)

    form = fake.token_requests[0]
    assert form["grant_type"] == [google_sheets.JWT_BEARER_GRANT], (
        "RFC 7523's JWT-bearer grant is what Google's server-to-server flow is"
    )
    claims = jwt.decode(
        form["assertion"][0],
        _PUBLIC_KEY,
        algorithms=["RS256"],
        audience=google_sheets.TOKEN_URL,
    )
    assert claims["iss"] == SERVICE_ACCOUNT_EMAIL
    assert claims["scope"] == SCOPE
    # `aud` is the TOKEN endpoint, not the Sheets API: a captured assertion must not be
    # replayable against anything but the exchange it was minted for.
    assert claims["aud"] == google_sheets.TOKEN_URL
    assert 0 < claims["exp"] - claims["iat"] <= 3600, "Google caps the assertion at one hour"
    header = jwt.get_unverified_header(form["assertion"][0])
    assert header["alg"] == "RS256"
    assert header["kid"] == "kid-1"


async def test_the_token_is_minted_once_and_reused() -> None:
    """One token an hour, not one a lead. The quota that matters is per-minute, and a
    signature plus a round-trip per row would spend it on authentication."""
    fake = FakeGoogle()
    async with fake.client() as client:
        transport = GoogleSheetsTransport(_credential_json(), client=client)
        for _ in range(3):
            assert (await transport.append(_request())).appended is True
    assert len(fake.token_requests) == 1
    assert len(fake.appends) == 3


async def test_a_refused_token_exchange_is_transient_not_a_verdict() -> None:
    fake = FakeGoogle()
    fake.token_status = 400
    result = await _append(fake)
    assert result.status is AppendStatus.TRANSPORT_FAILED
    assert result.reason == AUTH_FAILED_REASON
    assert fake.appends == [], "nothing may be written with no token"


async def test_a_malformed_key_refuses_permanently_without_calling_google() -> None:
    async with FakeGoogle().client() as client:
        transport = GoogleSheetsTransport("{not json", client=client)
        result = await transport.append(_request())
    assert result.status is AppendStatus.REJECTED
    assert result.reason == CREDENTIAL_UNRESOLVABLE_REASON


async def test_an_endpoint_naming_an_unknown_credential_is_refused() -> None:
    """`secret_ref` is written by an operator. A resolver that fell back to the only key
    it holds would make a typo indistinguishable from a correct configuration."""
    fake = FakeGoogle()
    result = await _append(fake, _request(credential_ref="sm://google-sheets/other-tenant"))
    assert result.status is AppendStatus.REJECTED
    assert result.reason == CREDENTIAL_REF_UNKNOWN_REASON
    assert fake.token_requests == []


def test_a_credential_reference_cannot_escape_its_namespace() -> None:
    """The value comes off a database row. The namespace is what stops a row naming key
    material that has nothing to do with Google Sheets."""
    assert credential_name(CREDENTIAL_REF) == DEPLOYMENT_CREDENTIAL_NAME
    assert credential_name("sm://clerk/admin") is None
    assert credential_name("sm://google-sheets/") is None
    assert credential_name("sm://google-sheets/a/b") is None
    assert credential_name(f"x{CREDENTIAL_REF}") is None


def test_a_key_without_the_fields_the_flow_needs_is_not_a_key() -> None:
    assert parse_service_account(_credential_json()) is not None
    assert parse_service_account(json.dumps({"client_email": "a@b.c"})) is None
    assert parse_service_account(json.dumps({"private_key": "x"})) is None
    assert parse_service_account("[]") is None


# --------------------------------------------------------------------------------
# 2. The append itself: RAW, INSERT_ROWS, and the client's own tab
# --------------------------------------------------------------------------------


async def test_the_append_is_raw_and_inserts_rows() -> None:
    fake = FakeGoogle()
    request = _request()
    assert (await _append(fake, request)).status is AppendStatus.APPENDED

    call = fake.appends[0]
    params = dict(call.url.params)
    # RAW, not USER_ENTERED: a caller-supplied lead name must never become a formula.
    assert params["valueInputOption"] == "RAW"
    # INSERT_ROWS, not the OVERWRITE default: a client with a totals block below their
    # leads must not have it silently overwritten by a lead.
    assert params["insertDataOption"] == "INSERT_ROWS"
    assert json.loads(call.content) == {"values": [list(request.values)]}
    assert unquote(str(call.url.path)).endswith("/values/'Leads':append")


async def test_a_tab_name_with_an_apostrophe_is_escaped_not_mangled() -> None:
    """`Ravi's leads` is an ordinary thing to call a tab. An unquoted range comes back
    as 'unable to parse', which we would report to the client as 'your tab does not
    exist' — a lie about their own document."""
    fake = FakeGoogle()
    await _append(fake, _request(worksheet="Ravi's leads"))
    assert unquote(str(fake.appends[0].url.path)).endswith("/values/'Ravi''s leads':append")


def test_a1_helpers() -> None:
    assert a1_sheet("Leads") == "'Leads'"
    assert a1_sheet("Ravi's leads") == "'Ravi''s leads'"
    # Bijective base-26: there is no zero digit, so 26 is AA and not BA.
    assert column_letter(0) == "A"
    assert column_letter(25) == "Z"
    assert column_letter(26) == "AA"
    assert column_letter(51) == "AZ"
    assert column_letter(52) == "BA"


# --------------------------------------------------------------------------------
# 3. The header: written once, by an idempotent write, and never over the client's own
# --------------------------------------------------------------------------------


async def test_an_empty_sheet_gets_its_header_from_an_idempotent_update() -> None:
    fake = FakeGoogle()
    request = _request()
    await _append(fake, request)

    assert len(fake.header_writes) == 1
    write = fake.header_writes[0]
    # A `values.update` at a FIXED range, not an append: two workers racing on a new
    # sheet both write the same cells, so no header can be duplicated.
    assert write.method == "PUT"
    assert unquote(str(write.url.path)).endswith("/values/'Leads'!A1:F1")
    assert json.loads(write.content) == {"values": [list(request.header)]}
    assert dict(write.url.params)["valueInputOption"] == "RAW"
    # And the delivery id is the LAST column, which is what makes the document
    # reconcilable against the delivery log — by the probe and by a human.
    assert request.header[-1] == service.SHEET_DELIVERY_HEADER


async def test_a_sheet_the_client_already_uses_keeps_its_own_first_row() -> None:
    fake = FakeGoogle()
    fake.row_one = ["Name", "Number", "Notes"]
    await _append(fake)
    assert fake.header_writes == [], "it is their document; we do not restyle it"
    assert len(fake.appends) == 1


async def test_the_header_is_checked_once_per_process_not_once_per_lead() -> None:
    fake = FakeGoogle()
    async with fake.client() as client:
        transport = GoogleSheetsTransport(_credential_json(), client=client)
        for _ in range(3):
            await transport.append(_request())
    assert len(fake.header_writes) == 1
    assert len([r for r in fake.reads if r.endswith("!1:1")]) == 1


# --------------------------------------------------------------------------------
# 4. THE HARD PART: a retry must not duplicate a row
# --------------------------------------------------------------------------------


async def test_a_first_attempt_never_reads_before_writing() -> None:
    """The probe is not free and the first attempt cannot need it: a duplicate requires
    an earlier append, and an earlier append requires an earlier attempt."""
    fake = FakeGoogle()
    fake.row_one = ["already", "has", "a", "header", "here", "too"]
    await _append(fake, _request(dedupe_probe=False))
    # The header check is a read and happens once per process; the DEDUPE probe is the
    # per-delivery one, and it must not fire here — that is the cost this design avoids.
    assert [r for r in fake.reads if not r.endswith("!1:1")] == []
    assert len(fake.appends) == 1


async def test_retry_finds_its_own_row_and_does_not_append_again() -> None:
    """THE test this adapter exists for.

    Sheets v4 has no request key, so the only thing standing between an arq replay and a
    duplicate row in a document a human is reading is this read. Sabotage
    `dedupe_probe=attempt > 1` in `sheets_sync.append_event`, or the `ALREADY_PRESENT`
    branch in the adapter, and this test fails with two rows for one lead.
    """
    fake = FakeGoogle()
    request = _request()
    # Attempt 1: accepted by Google. (Imagine the worker crashing here, before commit.)
    assert (await _append(fake, request)).status is AppendStatus.APPENDED
    assert len(fake.appends) == 1

    # Attempt 2 of the SAME delivery: same id, and now a probe.
    result = await _append(fake, _request(**{"values": request.values, "dedupe_probe": True}))
    assert result.status is AppendStatus.ALREADY_PRESENT
    assert result.appended is True, "the lead IS in their sheet — this is not a failure"
    assert len(fake.appends) == 1, "the row must not be written twice"
    assert fake.delivery_column.count(request.values[-1]) == 1


async def test_the_probe_reads_only_the_delivery_id_column() -> None:
    fake = FakeGoogle()
    await _append(fake, _request(dedupe_probe=True))
    # Six columns, so the delivery id is F. Reading the whole sheet to find one id would
    # pull every lead's name and number back over the wire for nothing.
    assert "'Leads'!F:F" in fake.reads
    assert dict(fake.appends[0].url.params)  # and it still appended: id was not there


async def test_a_retry_for_a_different_delivery_still_appends() -> None:
    """The probe must dedupe RETRIES, not collapse two genuine leads. The id it looks
    for is the delivery id, which is minted once per fan-out and reused across attempts.
    """
    fake = FakeGoogle()
    first = _request()
    await _append(fake, first)
    second = _request(dedupe_probe=True)  # a different delivery id
    assert (await _append(fake, second)).status is AppendStatus.APPENDED
    assert len(fake.appends) == 2


async def _probe_against_a_warm_sheet(read_status: int) -> tuple[Any, FakeGoogle]:
    """One delivered append (which warms the header cache), then a retry whose probe
    hits `read_status`. Warming matters: it isolates the PROBE read from the header
    read, so the assertion below is about the write being withheld and not about which
    of two reads failed first.
    """
    fake = FakeGoogle()
    async with fake.client() as client:
        transport = GoogleSheetsTransport(_credential_json(), client=client)
        await transport.append(_request())
        fake.read_status = read_status
        result = await transport.append(_request(dedupe_probe=True))
    return result, fake


async def test_a_probe_that_cannot_read_refuses_to_write() -> None:
    """Blind-appending after a failed check is exactly the duplicate the probe exists to
    prevent. A late lead is recoverable; a duplicate row is not."""
    result, fake = await _probe_against_a_warm_sheet(503)
    assert result.status is AppendStatus.TRANSPORT_FAILED
    assert result.reason == PROBE_FAILED_REASON
    assert result.retryable is True
    assert len(fake.appends) == 1, "nothing may be written when the check failed"


async def test_a_probe_refused_permanently_reports_the_permanent_reason() -> None:
    """A 403 on the read is not 'we could not check', it is 'you unshared the sheet'.
    Reporting it as transient would spend the ladder to reach the same answer and would
    hide the one sentence the client can act on."""
    result, fake = await _probe_against_a_warm_sheet(403)
    assert result.status is AppendStatus.REJECTED
    assert result.reason == SHEET_NOT_SHARED_REASON
    assert len(fake.appends) == 1


# --------------------------------------------------------------------------------
# 5. Errors are part of the interface
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "expected_status", "reason"),
    [
        (429, AppendStatus.TRANSPORT_FAILED, RATE_LIMITED_REASON),
        (500, AppendStatus.TRANSPORT_FAILED, UNAVAILABLE_REASON),
        (503, AppendStatus.TRANSPORT_FAILED, UNAVAILABLE_REASON),
        (401, AppendStatus.REJECTED, AUTH_FAILED_REASON),
        (403, AppendStatus.REJECTED, SHEET_NOT_SHARED_REASON),
        (404, AppendStatus.REJECTED, SPREADSHEET_NOT_FOUND_REASON),
        (400, AppendStatus.REJECTED, WORKSHEET_REJECTED_REASON),
    ],
)
async def test_every_google_status_maps_to_one_authored_reason(
    status: int, expected_status: AppendStatus, reason: str
) -> None:
    """One status, one code we wrote ourselves. Never vendor prose: a Google error body
    can quote the row we just handed it, and these strings land in an alert and on a
    client's screen (hard rule 6)."""
    fake = FakeGoogle()
    fake.append_status = status
    result = await _append(fake)
    assert result.status is expected_status
    assert result.reason == reason
    # And the transient/permanent split is stated, never inferred from a missing status.
    assert result.retryable is (expected_status is AppendStatus.TRANSPORT_FAILED)


async def test_a_network_failure_is_transient_and_names_only_the_exception_type() -> None:
    def _boom(request: httpx.Request) -> httpx.Response:
        if request.url.host == "oauth2.googleapis.com":
            return httpx.Response(200, json={"access_token": "t", "expires_in": 3599})
        raise httpx.ConnectError("refused")

    async with httpx.AsyncClient(transport=httpx.MockTransport(_boom)) as client:
        transport = GoogleSheetsTransport(_credential_json(), client=client)
        result = await transport.append(_request())
    assert result.status is AppendStatus.TRANSPORT_FAILED
    assert result.reason == "ConnectError", "the type, never the message — it may quote a URL"


# --------------------------------------------------------------------------------
# 6. Hard rule 6: none of it reaches a log line
# --------------------------------------------------------------------------------


async def test_no_cell_credential_or_token_is_ever_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeGoogle()
    request = _request()
    with caplog.at_level(logging.INFO):
        await _append(fake, request)
        fake.append_status = 403
        await _append(fake, request)

    formatter = JsonFormatter()
    # OUR records. httpx's own `HTTP Request: <method> <full url>` line is excluded here
    # because production never emits it — `configure_logging` puts that logger at
    # WARNING, and the test below is what holds that. Writing this file first is how the
    # leak was found: the spreadsheet id, which is the capability naming a client's
    # document, was being printed by the HTTP library on every single append.
    rendered = " ".join(
        formatter.format(record) for record in caplog.records if record.name != "httpx"
    )
    for forbidden in (
        "Ravi Kumar",  # a cell
        "+91 98765",  # a cell that is a phone number
        SHEET_ID,  # the document id is a capability
        CREDENTIAL_REF,  # so is the credential reference
        "ya29.test-token",  # and so, very much, is the token
        _PRIVATE_PEM.splitlines()[1],
        service.SHEET_DELIVERY_HEADER,  # a header value is the client's own wording
    ):
        assert forbidden not in rendered, f"{forbidden!r} reached a log line"
    assert "sheet_append_ok" in rendered, "the shape IS logged — this is not a blanket ban"


def test_the_http_library_is_not_allowed_to_print_our_urls() -> None:
    """Found by the test above, and it was never only a sheets problem.

    httpx logs `HTTP Request: POST <full url>` at INFO for every outbound call. On the
    webhook half of D-23 that URL is a client's own endpoint — catch hooks from Zapier
    and Make carry their auth token in the query string — and on the storage path it is
    a presigned URL, which IS the credential. None of it can be caught by
    `redact_mapping`, because it arrives as prose in `msg` rather than as an extra.
    """
    logging.getLogger("httpx").setLevel(logging.NOTSET)
    configure_logging()
    assert logging.getLogger("httpx").level == logging.WARNING
    assert not logging.getLogger("httpx").isEnabledFor(logging.INFO)


# --------------------------------------------------------------------------------
# 7. End to end: the same outbox, the same ladder, the same log — and a reason
# --------------------------------------------------------------------------------


async def _tenant_with_sheet_endpoint(secret_ref: str = CREDENTIAL_REF) -> tuple[UUID, UUID]:
    created = await admin_service.create_organization(
        name="Sheet Clinic",
        slug=f"sheetadp-{uuid.uuid4().hex[:8]}",
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
                "active, created_at, updated_at) VALUES (:id, :tid, 'google_sheets', :url, "
                ":secret, :events, true, now(), now())"
            ),
            {
                "id": endpoint_id,
                "tid": tenant_id,
                "url": SHEET_ID,
                "secret": secret_ref,
                "events": ["lead.created"],
            },
        )
    return tenant_id, endpoint_id


def _payload(tenant_id: UUID, endpoint_id: UUID, delivery_id: UUID) -> dict[str, Any]:
    return {
        "tenant_id": str(tenant_id),
        "endpoint_id": str(endpoint_id),
        "event": "lead.created",
        "data": {
            "lead_id": str(uuid7()),
            "name": "Ravi Kumar",
            "phone": "[redacted]",
            "source": "webhook",
            "status": "new",
        },
        "delivery_id": str(delivery_id),
    }


def _install(monkeypatch: pytest.MonkeyPatch, fake: FakeGoogle, client: httpx.AsyncClient) -> None:
    """Run the REAL adapter inside the real worker — only the socket is a fake."""
    monkeypatch.setattr(
        sheets_sync,
        "get_sheets_transport",
        lambda: GoogleSheetsTransport(_credential_json(), client=client),
    )


async def _delivery_row(tenant_id: UUID, delivery_id: UUID) -> tuple[Any, ...] | None:
    async with tenant_session(tenant_id) as session:
        row = (
            await session.execute(
                text(
                    "SELECT status, attempts, source, reason FROM webhook_deliveries "
                    "WHERE id = :id AND endpoint_id IN (SELECT id FROM outbound_webhooks)"
                ),
                {"id": delivery_id},
            )
        ).first()
    return tuple(row) if row is not None else None


async def test_a_sheet_a_client_never_shared_lands_on_their_own_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole point of the reason column. Before it, this delivery said `sheets` and
    the client's queue said "your endpoint answered an error… check it returns 2xx" —
    advice about an HTTP server they do not have, for a problem they fix in one click.
    """
    tenant_id, endpoint_id = await _tenant_with_sheet_endpoint()
    delivery_id = uuid7()
    fake = FakeGoogle()
    fake.append_status = 403
    alerts: list[tuple[str, str, Any]] = []
    monkeypatch.setattr(
        outbound_webhooks,
        "alert",
        lambda stage, code, **kw: alerts.append((stage, code, kw.get("detail"))),
    )

    async with fake.client() as client:
        _install(monkeypatch, fake, client)
        outcome = await outbound_webhooks.deliver_outbound_webhook(
            {"job_try": 1}, _payload(tenant_id, endpoint_id, delivery_id)
        )

    # Permanent: three attempts cannot share a document on the client's behalf.
    assert outcome.startswith("rejected")
    status, _attempts, source, reason = await _delivery_row(tenant_id, delivery_id) or ()
    assert (status, source, reason) == ("failed", "sheets", SHEET_NOT_SHARED_REASON)
    # An operator hears about it too — one alert code, one runbook, both kinds.
    assert alerts and alerts[0][1] == "outbound_webhook_exhausted"
    assert "permanent" in str(alerts[0][2])

    async with tenant_session(tenant_id) as session:
        # A source answers a page AND the true size of the set it came from; the count
        # is the badge's number, so it is asserted here too.
        source_page = await attention.failed_deliveries(session)
    items = source_page.items
    assert (len(items), source_page.total) == (1, 1)
    assert "spreadsheet" in items[0].title
    assert "Share" in items[0].detail and "Editor" in items[0].detail
    assert items[0].rule == SHEET_NOT_SHARED_REASON
    assert "2xx" not in items[0].detail, "that is webhook advice; this client has no server"
    assert items[0].href == "/integrations"


async def test_google_being_busy_climbs_the_same_ladder_as_a_webhook(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, endpoint_id = await _tenant_with_sheet_endpoint()
    delivery_id = uuid7()
    fake = FakeGoogle()
    fake.append_status = 429

    async with fake.client() as client:
        _install(monkeypatch, fake, client)
        with pytest.raises(Retry) as raised:
            await outbound_webhooks.deliver_outbound_webhook(
                {"job_try": 1}, _payload(tenant_id, endpoint_id, delivery_id)
            )
    # The SHARED ladder, not a second backoff loop inside the adapter.
    assert raised.value.defer_score == int(outbound_webhooks.RETRY_BACKOFF_S[0] * 1000)
    status, attempts, _source, reason = await _delivery_row(tenant_id, delivery_id) or ()
    assert (status, attempts, reason) == ("failed", 1, RATE_LIMITED_REASON)


async def test_a_retried_job_probes_the_sheet_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The seam and the adapter, joined: `job_try` reaches `dedupe_probe`.

    Sabotage `dedupe_probe=attempt > 1` in `sheets_sync.append_event` and this fails —
    the worker appends a second row for a lead already in the client's spreadsheet.
    """
    tenant_id, endpoint_id = await _tenant_with_sheet_endpoint()
    delivery_id = uuid7()
    fake = FakeGoogle()

    async with fake.client() as client:
        _install(monkeypatch, fake, client)
        payload = _payload(tenant_id, endpoint_id, delivery_id)
        # Attempt 1 reaches Google, then the process dies before the delivery row commits.
        await sheets_sync.append_event(
            endpoint={"url": SHEET_ID, "secret": CREDENTIAL_REF, "mapping": {}},
            event="lead.created",
            data=payload["data"],
            delivery_id=delivery_id,
            attempt=1,
        )
        assert len(fake.appends) == 1
        # arq replays it. The delivery log has nothing, so only the probe can save us.
        outcome = await outbound_webhooks.deliver_outbound_webhook({"job_try": 2}, payload)

    assert outcome == "delivered via sheets"
    assert len(fake.appends) == 1, "one lead, one row"
    assert fake.delivery_column.count(str(delivery_id)) == 1
    status, attempts, _source, reason = await _delivery_row(tenant_id, delivery_id) or ()
    assert (status, attempts, reason) == ("delivered", 2, None)


async def test_a_delivered_row_is_never_appended_twice_even_with_the_probe_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Layer 1 still stands on its own: a committed `delivered` row stops the job before
    the transport is reached, so the probe is a second line of defence and not a
    replacement for the log."""
    tenant_id, endpoint_id = await _tenant_with_sheet_endpoint()
    delivery_id = uuid7()
    fake = FakeGoogle()

    async with fake.client() as client:
        _install(monkeypatch, fake, client)
        payload = _payload(tenant_id, endpoint_id, delivery_id)
        assert await outbound_webhooks.deliver_outbound_webhook({"job_try": 1}, payload)
        assert await outbound_webhooks.deliver_outbound_webhook({"job_try": 2}, payload) == (
            "duplicate"
        )
    assert len(fake.appends) == 1


# --------------------------------------------------------------------------------
# 8. Hard rule 1: a neighbour sees none of it
# --------------------------------------------------------------------------------


@pytest.mark.rls
async def test_a_neighbour_tenant_sees_no_row_of_this_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`webhook_deliveries` has no RLS policy by design (engine webhooks arrive before a
    tenant is resolved), so every client-facing read is scoped THROUGH `outbound_webhooks`
    — which is FORCEd-RLS'd. The new `reason` column rides that same join, and this is
    the zero-rows test that says so.
    """
    victim, endpoint_id = await _tenant_with_sheet_endpoint()
    neighbour, _ = await _tenant_with_sheet_endpoint()
    delivery_id = uuid7()
    fake = FakeGoogle()
    fake.append_status = 403

    async with fake.client() as client:
        _install(monkeypatch, fake, client)
        monkeypatch.setattr(outbound_webhooks, "alert", lambda *a, **k: None)
        await outbound_webhooks.deliver_outbound_webhook(
            {"job_try": 1}, _payload(victim, endpoint_id, delivery_id)
        )

    assert (await _delivery_row(victim, delivery_id))[3] == SHEET_NOT_SHARED_REASON
    # The same query, from next door.
    assert await _delivery_row(neighbour, delivery_id) is None
    async with tenant_session(neighbour) as session:
        neighbours_queue = await attention.failed_deliveries(session)
        assert (neighbours_queue.items, neighbours_queue.total) == ([], 0)
        assert await service.delivery_status(session, delivery_id) is None
        # And the endpoint itself is invisible, which is what the join depends on.
        assert await service.load_endpoint(session, endpoint_id) is None


# --------------------------------------------------------------------------------
# 9. The deployment gate: a provider with no key is not a transport
# --------------------------------------------------------------------------------


async def test_the_provider_selects_the_real_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "google_sheets_provider", sheets_sync.SERVICE_ACCOUNT_PROVIDER)
    monkeypatch.setattr(settings, "google_sheets_service_account_json", _credential_json())
    assert isinstance(sheets_sync.get_sheets_transport(), GoogleSheetsTransport)
    assert sheets_sync.sheets_delivery_available() is True


async def test_the_provider_without_a_key_offers_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Naming a provider with no credential behind it must not make the API start
    offering Google Sheets endpoints. `sheets_delivery_available()` IS that gate, and it
    is the same selector the worker calls — one answer, so the config screen and the
    spreadsheet cannot disagree."""
    settings = get_settings()
    monkeypatch.setattr(settings, "google_sheets_provider", sheets_sync.SERVICE_ACCOUNT_PROVIDER)
    monkeypatch.setattr(settings, "google_sheets_service_account_json", None)
    transport = sheets_sync.get_sheets_transport()
    assert isinstance(transport, sheets_sync.UnconfiguredSheetsTransport)
    assert sheets_sync.sheets_delivery_available() is False
    result = await transport.append(_request())
    assert result.status is AppendStatus.REJECTED
    assert result.reason == sheets_sync.NO_CREDENTIALS_REASON


def test_every_sheets_refusal_has_a_sentence_for_the_client() -> None:
    """A reason code with no copy shows the fallback, which is honest but generic. This
    asserts we wrote the specific sentence for every code the two modules can produce —
    the failure mode being a new refusal that reaches a client as "contact support"."""
    produced = {
        sheets_sync.NO_CREDENTIAL_REF_REASON,
        sheets_sync.NO_SPREADSHEET_REASON,
        sheets_sync.DEV_SINK_OUTSIDE_LOCAL_REASON,
        google_sheets.AUTH_FAILED_REASON,
        google_sheets.CREDENTIAL_REF_UNKNOWN_REASON,
        google_sheets.CREDENTIAL_UNRESOLVABLE_REASON,
        google_sheets.PROBE_FAILED_REASON,
        google_sheets.RATE_LIMITED_REASON,
        google_sheets.SHEET_NOT_SHARED_REASON,
        google_sheets.SPREADSHEET_NOT_FOUND_REASON,
        google_sheets.UNAVAILABLE_REASON,
        google_sheets.WORKSHEET_REJECTED_REASON,
    }
    missing = produced - set(attention.SHEET_FAILURE_REMEDIES)
    assert not missing, f"no client-facing sentence for: {sorted(missing)}"


def test_the_delivery_log_is_still_the_one_definition_of_delivered() -> None:
    """A guard against the drift this whole slice is organised to prevent: the sheets
    path must never grow a status vocabulary of its own."""
    assert sheets_sync.CHANNEL == "sheets"
    assert service.SHEET_KIND in service.DELIVERABLE_KINDS
    # `ALREADY_PRESENT` is an ADAPTER outcome, not a delivery status: it collapses into
    # `delivered` before it reaches the log, because the client's lead is in their sheet.
    assert AppendStatus.ALREADY_PRESENT.value not in ("delivered", "failed", "skipped")
