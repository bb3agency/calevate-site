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
from typing import Literal

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


# The call variables a `lead_var` binding may name, mapped to the Bolna system variable the
# engine substitutes (VERIFIED-VENDOR-DOCS, custom-function-calls.md:581-586 — the four
# auto-injected into function parameters). `caller_phone` is the synthetic one the
# declaration resolves per agent direction (see `actions/service.declare`), because "the
# other party on the call" is `from_number` inbound and `to_number` outbound.
CALL_VARS: dict[str, str] = {
    "caller_phone": "",  # resolved per direction at declaration; placeholder here
    "from_number": "{from_number}",
    "to_number": "{to_number}",
    "call_sid": "{call_sid}",
}


class ParamSpec(BaseModel):
    """One named binding. `config` references it by `name`."""

    model_config = ConfigDict(extra="forbid")

    # No leading underscore: those are RESERVED for values the executor injects itself
    # (e.g. `_agent_ref`, the Bolna `{agent_id}` used to resolve the tenant), so a client
    # cannot define a param that shadows one.
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

    @model_validator(mode="after")
    def _operation_fields(self) -> CalendarConfig:
        if self.start_param is None:
            raise ValueError("a calendar action needs a start-time parameter")
        if self.operation == "check" and self.end_param is None:
            raise ValueError("a calendar availability check needs an end-time parameter")
        if self.operation == "book" and self.end_param is None and self.duration_min is None:
            raise ValueError("a calendar booking needs an end time or a duration")
        return self


__all__ = [
    "CALL_VARS",
    "CalendarConfig",
    "CustomApiConfig",
    "KeyedField",
    "ParamSource",
    "ParamSpec",
    "PreparedRequest",
    "WhatsAppConfig",
]
