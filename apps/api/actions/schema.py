"""The validated shape of an action's parameter spec and kind-specific config.

These Pydantic models are the ONE definition of what a tool's `params` and `config` JSONB
columns hold. They are validated on every write (so a malformed tool cannot reach the
database) and re-parsed on read (so the engine declaration and the executor read a typed
value, never a raw dict). Keeping them here — separate from the ORM and the service — lets
the voice-runtime executor import the shapes without importing the route layer.

PARAMETER BINDING (the founder's spec: each value is static, a call/lead variable, or
AI-inferred). `params` is the authoritative registry of bindings, each with a stable
`name`; `config` references bindings BY NAME rather than embedding them, so there is one
source of truth for "how is this value filled" and the request template is pure structure.

  - static   a fixed value applied on OUR side; never sent to the engine.
  - lead_var a call variable (the caller's number, the call id) Bolna substitutes at call
             time and sends to us, OR that we resolve from call context.
  - ai       an argument the LLM extracts from the conversation, declared to the engine.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal
from uuid import UUID

from calevate_shared.engine import ActionParamType
from pydantic import BaseModel, ConfigDict, Field, model_validator

ParamSource = Literal["static", "lead_var", "ai"]


@dataclass(frozen=True, slots=True)
class PreparedRequest:
    """One outbound HTTP request an adapter has assembled, transport-agnostic. The executor
    puts it on the wire (through the egress guard). `json_body` None means no body."""

    method: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)
    json_body: dict[str, object] | None = None
    #: Form-encoded body (application/x-www-form-urlencoded), for endpoints that want it —
    #: Google's OAuth token endpoint. Mutually exclusive with `json_body`.
    form_body: dict[str, str] | None = None


# The call variables a `lead_var` binding may name. They are the call's own data, applied by
# our executor from our record of the call and never declared to a runtime (`service._to_spec`).
# `caller_phone` is "the other party on the call": `from_number` inbound, `to_number` outbound.
CALL_VARS: frozenset[str] = frozenset({"caller_phone", "from_number", "to_number", "call_sid"})


class ParamSpec(BaseModel):
    """One named binding. `config` references it by `name`."""

    model_config = ConfigDict(extra="forbid")

    # No leading underscore: those are RESERVED for values the executor injects itself, so
    # a client cannot define a param that shadows one.
    name: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z][a-zA-Z0-9_]*$")
    source: ParamSource
    # static
    value: str | None = None
    # lead_var — a key of CALL_VARS
    lead_var: str | None = None
    # ai
    type: ActionParamType = "string"
    description: str = ""
    required: bool = False

    @model_validator(mode="after")
    def _coherent(self) -> ParamSpec:
        if self.source == "static" and self.value is None:
            raise ValueError(f"static param {self.name!r} needs a value")
        if self.source == "lead_var" and self.lead_var not in CALL_VARS:
            raise ValueError(f"lead_var param {self.name!r} must name one of {sorted(CALL_VARS)}")
        if self.source == "ai" and not self.description.strip():
            # The description is what the LLM reads to fill the argument — an empty one is
            # an argument the model cannot reliably collect (custom-function-calls.md).
            raise ValueError(f"ai param {self.name!r} needs a description for the model")
        return self


class KeyedField(BaseModel):
    """A header/query/body entry: a literal key whose value is the named binding."""

    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=256)
    param: str = Field(min_length=1, max_length=64)


class CustomApiConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST"] = "POST"
    # The client's external endpoint. Vetted by the egress guard on write and on execute.
    url: str = Field(min_length=1, max_length=2048)
    headers: list[KeyedField] = Field(default_factory=list)
    query: list[KeyedField] = Field(default_factory=list)
    body: list[KeyedField] = Field(default_factory=list)
    # AUTH goes through the saved credential, never a static param — a static value is
    # stored plaintext in our DB and is for non-secret fixed values only (a store id, a
    # region), so a bearer token or api key belongs in `integration_credentials`. When the
    # tool has a credential, the executor sets `auth_header` to `auth_scheme + <secret>`.
    # Defaults suit the common `Authorization: Bearer <token>` case; a header-key api key
    # is `auth_header="X-Api-Key"`, `auth_scheme=""`.
    auth_header: str = Field(default="Authorization", max_length=128)
    auth_scheme: str = Field(default="Bearer ", max_length=32)

    @model_validator(mode="after")
    def _body_only_for_post(self) -> CustomApiConfig:
        if self.method == "GET" and self.body:
            raise ValueError("a GET action cannot carry a JSON body")
        # HTTPS only: the request carries the client's sealed credential and, on a call,
        # the caller's details. The egress guard admits http for webhooks; this does not.
        if not self.url.lower().startswith("https://"):
            raise ValueError("the address must start with https://")
        return self


class WhatsAppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # The binding naming the recipient's number — normally the `caller_phone` lead var.
    recipient_param: str = Field(min_length=1, max_length=64)
    # AiSensy: the API-campaign name (which IS the template reference). Meta/Interakt: the
    # WhatsApp template name.
    template: str = Field(min_length=1, max_length=512)
    # Meta Cloud / Interakt need the template language; AiSensy does not.
    language: str | None = Field(default=None, max_length=16)
    # Meta Cloud only: the WABA phone number id the send goes out on.
    phone_number_id: str | None = Field(default=None, max_length=64)
    # Optional header variable (Meta/Interakt), a binding name.
    header_param: str | None = Field(default=None, max_length=64)
    # Ordered body variables ({{1}}, {{2}}...), each a binding name.
    body_params: list[str] = Field(default_factory=list)
    # Interakt splits the recipient into country code + local number; this is the country
    # code to strip. Defaults to +91 — this is an India-only product (CLAUDE.md).
    country_code: str = Field(default="+91", max_length=8)


#: A 24-hour clock time, zero-padded, so two values compare correctly as strings.
HHMM_PATTERN = r"^([01][0-9]|2[0-3]):[0-5][0-9]$"


class CalendarConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["book", "check"]
    calendar_id: str = Field(default="primary", min_length=1, max_length=256)
    # book: start + duration + summary; check: start + end window. All are binding names,
    # so the LLM (or a lead var) fills the times from the conversation.
    start_param: str | None = Field(default=None, max_length=64)
    end_param: str | None = Field(default=None, max_length=64)
    duration_min: int | None = Field(default=None, ge=1, le=1440)
    summary_param: str | None = Field(default=None, max_length=64)
    # The hours this business takes bookings, India time. The executor refuses a booking
    # outside them and offers only free times inside them, so the rule holds whatever the
    # agent says. Absent means any time of day, as before.
    opens: str | None = Field(default=None, pattern=HHMM_PATTERN)
    closes: str | None = Field(default=None, pattern=HHMM_PATTERN)
    #: ISO weekdays it takes bookings on (1 = Monday … 7 = Sunday); absent means every day.
    open_days: list[int] | None = Field(default=None, min_length=1, max_length=7)

    @model_validator(mode="after")
    def _operation_fields(self) -> CalendarConfig:
        if (self.opens is None) != (self.closes is None):
            raise ValueError("booking hours need both an opening and a closing time")
        if self.opens is not None and self.closes is not None and self.opens >= self.closes:
            raise ValueError("booking hours must open before they close")
        if self.open_days is not None and (
            len(set(self.open_days)) != len(self.open_days)
            or any(day < 1 or day > 7 for day in self.open_days)
        ):
            raise ValueError("booking days are weekdays 1 (Monday) to 7 (Sunday), each once")
        if self.start_param is None:
            raise ValueError("a calendar action needs a start-time parameter")
        if self.operation == "check" and self.end_param is None:
            raise ValueError("a calendar availability check needs an end-time parameter")
        if self.operation == "book" and self.end_param is None and self.duration_min is None:
            raise ValueError("a calendar booking needs an end time or a duration")
        return self


# --------------------------------------------------------------- D-700 kinds ----
#
# Every new kind reads the caller's number from OUR record of the call (the voice platform's
# `phone` on `GET /calls/{id}`), never from a model argument: a caller cannot talk the agent
# into writing, messaging or looking up somebody else.

#: A Google spreadsheet id as it appears in the sheet's URL (`/spreadsheets/d/<id>/`).
SPREADSHEET_ID_PATTERN = r"^[A-Za-z0-9_-]{20,128}$"
#: Field names the two CRMs use on the wire: Zoho `Last_Name`, HubSpot `firstname`.
CRM_FIELD_PATTERN = r"^[A-Za-z][A-Za-z0-9_]{0,99}$"


class SheetColumn(BaseModel):
    """One column a `sheets` record action fills: the header text in row 1 and the binding."""

    model_config = ConfigDict(extra="forbid")

    header: str = Field(min_length=1, max_length=100)
    param: str = Field(min_length=1, max_length=64)


class SheetsConfig(BaseModel):
    """Write the call into the client's sheet, or answer from it.

    `record`: one row per call, keyed by the call reference in a column we own; a second
    invocation on the same call UPDATES that row, so answers can be written as they arrive.
    `lookup`: find the row whose `match_header` column holds the caller's number and hand
    the model the `return_headers` cells. The match is on the caller's number only — a
    lookup by a model-supplied value would let a stranger read any row by guessing.
    """

    model_config = ConfigDict(extra="forbid")

    operation: Literal["record", "lookup"]
    spreadsheet_id: str = Field(pattern=SPREADSHEET_ID_PATTERN)
    #: The name the owner saw in Google's picker, shown back to them; never sent to Google.
    spreadsheet_name: str | None = Field(default=None, max_length=200)
    worksheet: str = Field(min_length=1, max_length=100)
    columns: list[SheetColumn] = Field(default_factory=list, max_length=20)
    match_header: str | None = Field(default=None, max_length=100)
    return_headers: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def _operation_fields(self) -> SheetsConfig:
        if self.operation == "record" and not self.columns:
            raise ValueError("a sheet record action needs at least one column")
        if self.operation == "lookup" and (not self.match_header or not self.return_headers):
            raise ValueError("a sheet lookup needs the phone column and the columns to read")
        return self


class PaymentMessage(BaseModel):
    """The WhatsApp template that carries a payment link to the caller.

    `body_values` names, in template order, what fills `{{1}}`, `{{2}}`…: the link, the
    amount in rupees, or the link's description. Never free text from the model.
    """

    model_config = ConfigDict(extra="forbid")

    provider: Literal["aisensy", "meta_cloud", "interakt"]
    credential_id: UUID
    template: str = Field(min_length=1, max_length=512)
    language: str | None = Field(default=None, max_length=16)
    phone_number_id: str | None = Field(default=None, max_length=64)
    body_values: list[Literal["link", "amount", "description"]] = Field(min_length=1, max_length=3)
    country_code: str = Field(default="+91", max_length=8)

    @model_validator(mode="after")
    def _carries_the_link(self) -> PaymentMessage:
        if "link" not in self.body_values:
            raise ValueError("the payment message template must carry the link")
        return self


class PaymentLinkConfig(BaseModel):
    """A Razorpay Payment Link on the CLIENT's own account, sent to the caller on WhatsApp.

    The amount is either fixed here or named by the model within `min_amount_inr`..
    `max_amount_inr`, which are the client's rules; anything outside is refused before
    Razorpay is called. Rupees as decimal strings (hard rule 7); converted to whole paise.
    """

    model_config = ConfigDict(extra="forbid")

    fixed_amount_inr: Decimal | None = Field(default=None, gt=0, max_digits=10, decimal_places=2)
    amount_param: str | None = Field(default=None, max_length=64)
    min_amount_inr: Decimal = Field(default=Decimal("1"), ge=Decimal("1"), decimal_places=2)
    max_amount_inr: Decimal = Field(le=Decimal("500000"), gt=0, decimal_places=2)
    description: str = Field(min_length=1, max_length=200)
    expire_minutes: int = Field(default=1440, ge=20, le=10080)
    message: PaymentMessage

    @model_validator(mode="after")
    def _one_amount_source(self) -> PaymentLinkConfig:
        if (self.fixed_amount_inr is None) == (self.amount_param is None):
            raise ValueError("a payment link needs either a fixed amount or an amount parameter")
        if self.min_amount_inr > self.max_amount_inr:
            raise ValueError("the smallest amount is above the largest")
        if self.fixed_amount_inr is not None and not (
            self.min_amount_inr <= self.fixed_amount_inr <= self.max_amount_inr
        ):
            raise ValueError("the fixed amount is outside the allowed range")
        return self


class CrmField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crm_field: str = Field(pattern=CRM_FIELD_PATTERN)
    param: str = Field(min_length=1, max_length=64)


class CrmConfig(BaseModel):
    """Create or update the caller's lead/contact in the client's CRM.

    The record is matched on the caller's phone number, which we fill; `fields` maps the
    other answers. Zoho modules are `Leads` or `Contacts`; HubSpot has `contacts`.
    """

    model_config = ConfigDict(extra="forbid")

    module: Literal["Leads", "Contacts", "contacts"]
    fields: list[CrmField] = Field(default_factory=list, max_length=30)


class CallerLookupConfig(BaseModel):
    """Who is calling, read from the client's CRM, sheet or API by the caller's number.

    Per source: `zoho` reads `module`; `hubspot` reads contacts; `sheet` reads
    `spreadsheet_id`/`worksheet`/`match_header`/`return_headers`; `api` makes a GET to
    `url` with the number in the `phone_query_key` query parameter.
    """

    model_config = ConfigDict(extra="forbid")

    module: Literal["Leads", "Contacts"] = "Leads"
    spreadsheet_id: str | None = Field(default=None, pattern=SPREADSHEET_ID_PATTERN)
    spreadsheet_name: str | None = Field(default=None, max_length=200)
    worksheet: str | None = Field(default=None, max_length=100)
    match_header: str | None = Field(default=None, max_length=100)
    return_headers: list[str] = Field(default_factory=list, max_length=10)
    url: str | None = Field(default=None, max_length=2048)
    phone_query_key: str = Field(default="phone", min_length=1, max_length=64)
    auth_header: str = Field(default="Authorization", max_length=128)
    auth_scheme: str = Field(default="Bearer ", max_length=32)


__all__ = [
    "CALL_VARS",
    "CRM_FIELD_PATTERN",
    "SPREADSHEET_ID_PATTERN",
    "CalendarConfig",
    "CallerLookupConfig",
    "CrmConfig",
    "CrmField",
    "CustomApiConfig",
    "KeyedField",
    "ParamSource",
    "ParamSpec",
    "PaymentLinkConfig",
    "PaymentMessage",
    "PreparedRequest",
    "SheetColumn",
    "SheetsConfig",
    "WhatsAppConfig",
]
