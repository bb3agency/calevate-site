"""Lead sources that push to a URL: IndiaMART, the property portals and LeadSquared (D-942).

These senders share one constraint the shared-secret receiver cannot meet: the client
pastes a URL into IndiaMART's Lead Manager, or emails it to a 99acres account manager, and
nobody can make the sender add our `X-Ingest-Secret` header. So the secret travels in the
URL's `token` query parameter (the parameter name nginx's `calevate_redacted` access-log
format already strips), and everything else — the inbox dedupe, the mapping, the compliance
gate, the dial — is `ingest_lead`'s, unchanged. This module only knows each sender's SHAPE:
where the lead sits in the body, which field is the sender's own id for it, the preset
mapping a new source starts with, and whether the record is the person's own enquiry.

What each shape rests on:

* **IndiaMART** — VERIFIED-VENDOR-DOCS, help.indiamart.com "Integration of IndiaMART's Lead
  Manager CRM Push API with Third Party CRMs" (updated 1 Jun 2026, read 30 Oct 2026): a JSON
  POST of `{CODE, STATUS, RESPONSE: {UNIQUE_QUERY_ID, QUERY_TYPE, QUERY_TIME, SENDER_NAME,
  SENDER_MOBILE, SENDER_EMAIL, SENDER_CITY, QUERY_PRODUCT_NAME, QUERY_MESSAGE, ...}}`, no
  signature, HTTP 200 is success, retried until accepted, and the push is DEACTIVATED after
  48 hours of refusals. `SENDER_NAME` defaults to "IndiaMART Buyer". QUERY_TYPE: W direct
  enquiry, B buy-lead, P call to the seller's number, BIZ catalogue view, WA WhatsApp
  enquiry. The time zone of `QUERY_TIME` (`2024-04-10 11:17:14`) is NOT stated.
* **99acres, MagicBricks, Housing.com** — UNKNOWN: no public push specification exists. The
  portal pushes to a URL and format the receiving CRM names (99acres to ANAROCK posts
  name/email/phone/country_code; to Sell.Do it posts XML), so the preset below is OUR
  published contract, adjustable per client in the mapping screen and checked with the
  dry-run tester against whatever the account manager actually sends.
* **LeadSquared** — VERIFIED-VENDOR-DOCS, apidocs.leadsquared.com/create-a-webhook (read
  30 Oct 2026): webhooks may carry up to ten custom headers, so this sender CAN present the
  header as well as the token; lead create is event 3. The body of a lead webhook is
  `{"After": {...}, "Current": {...}}` with `ProspectID`, `FirstName`, `LastName`,
  `EmailAddress`, `Phone`, `Mobile`, `DoNotCall`, `mx_*` fields
  (help.leadsquared.com/data-posted-by-automation-triggers, updated 23 Jan 2025).

THE CONSENT DECISION (D-942). A portal enquiry is the buyer writing to THIS seller and
asking to be contacted: a written, digital inquiry by the recipient, kept by the portal in
verifiable form under an id. TCCCPR cl.2(bb)(ii) as amended (Regulation 18 Sep 2026)
counts that as a "relationship" for seven days, so the receiver records a `portal_enquiry`
grant carrying the portal's enquiry id that expires seven days after the enquiry, and the
lead is dialled without a consent question on a form the client does not control. This is
the opposite of the Meta decision, deliberately: a lead-ad fill hands a number to META
inside an ad unit, an IndiaMART enquiry is addressed to the seller by name. Only the
QUERY_TYPEs that ARE such an enquiry qualify: a buy-lead (a requirement posted to every
seller and bought by this one) and a catalogue view (no message at all) land in the CRM and
are never dialled. LeadSquared is the client's OWN system posting a lead it chose to send,
the shared-secret doctrine (`ingest_lead`'s `require_form_consent=False`), with its
`DoNotCall` flag honoured.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

from calevate_shared.calling_window import IST

#: The query parameter a push URL carries its secret in.
TOKEN_PARAM: Final = "token"

#: Our keys an `ingest_lead` mapping may fill beyond phone and name, for these senders.
ENQUIRY_ID_KEY: Final = "enquiry_id"
ENQUIRY_TYPE_KEY: Final = "enquiry_type"
ENQUIRY_AT_KEY: Final = "enquiry_at"
DO_NOT_CALL_KEY: Final = "do_not_call"

#: The lead is saved and not dialled: the portal record is not the person's own enquiry.
NOT_AN_ENQUIRY_RULE: Final = "not_a_direct_enquiry"
#: The lead is saved and not dialled: the enquiry is older than the seven-day window.
ENQUIRY_WINDOW_RULE: Final = "enquiry_window_closed"
#: The lead is saved and not dialled: the client's own CRM marks this person do-not-call.
CRM_DO_NOT_CALL_RULE: Final = "marked_do_not_call"

#: The most records one push may carry. IndiaMART sends one lead per POST; the bound is for
#: a sender that batches, so one request cannot hold a worker for an unbounded loop.
MAX_RECORDS_PER_PUSH: Final = 50

_TRUTHY: Final = frozenset({"1", "true", "yes", "y", "on"})


@dataclass(frozen=True, slots=True)
class PortalSpec:
    source: str
    #: Keys to descend into, the first present wins; empty when the lead is the body.
    envelope: tuple[str, ...] = ()
    #: The preset `inbound_webhooks.mapping` a new source of this kind starts with.
    preset: dict[str, str] = field(default_factory=dict)
    #: Whether the record is the person's own enquiry to this business (the consent ground).
    enquiry_ground: bool = False
    #: The enquiry types that are such an enquiry; None means every record is one.
    callable_enquiry_types: frozenset[str] | None = None
    #: Names the sender fills in when the person gave none, never a real name.
    placeholder_names: frozenset[str] = frozenset()


_PORTAL_PRESET: Final[dict[str, str]] = {
    "phone": "phone",
    "name": "name",
    "email": "email",
    "city": "city",
    "project": "project",
    "query": "message",
    ENQUIRY_ID_KEY: "lead_id",
}

SPECS: Final[dict[str, PortalSpec]] = {
    "indiamart": PortalSpec(
        source="indiamart",
        envelope=("RESPONSE",),
        preset={
            "phone": "SENDER_MOBILE",
            "name": "SENDER_NAME",
            "email": "SENDER_EMAIL",
            "city": "SENDER_CITY",
            "company": "SENDER_COMPANY",
            "product": "QUERY_PRODUCT_NAME",
            "query": "QUERY_MESSAGE",
            ENQUIRY_ID_KEY: "UNIQUE_QUERY_ID",
            ENQUIRY_TYPE_KEY: "QUERY_TYPE",
            ENQUIRY_AT_KEY: "QUERY_TIME",
        },
        enquiry_ground=True,
        callable_enquiry_types=frozenset({"W", "P", "WA"}),
        placeholder_names=frozenset({"indiamart buyer"}),
    ),
    "99acres": PortalSpec(source="99acres", preset=dict(_PORTAL_PRESET), enquiry_ground=True),
    "magicbricks": PortalSpec(
        source="magicbricks", preset=dict(_PORTAL_PRESET), enquiry_ground=True
    ),
    "housing": PortalSpec(source="housing", preset=dict(_PORTAL_PRESET), enquiry_ground=True),
    "leadsquared": PortalSpec(
        source="leadsquared",
        envelope=("Current", "After"),
        preset={
            "phone": "Phone",
            # Read only when `Phone` is empty (`ingest_lead` takes `phone` first).
            "phone_number": "Mobile",
            "name": "FirstName",
            "last_name": "LastName",
            "email": "EmailAddress",
            ENQUIRY_ID_KEY: "ProspectID",
            DO_NOT_CALL_KEY: "DoNotCall",
        },
    ),
}

#: Every source this module receives, in the order a client is offered them.
PUSH_SOURCES: Final = tuple(SPECS)


def is_push_source(source: str) -> bool:
    return source in SPECS


def preset_mapping(source: str) -> dict[str, str]:
    spec = SPECS.get(source)
    return dict(spec.preset) if spec else {}


def records(source: str, body: Any) -> list[dict[str, Any]]:
    """The lead records one push carries, unwrapped from the sender's envelope.

    A body this module cannot read as records yields `[]`, which the receiver records as
    a refusal rather than a 4xx: IndiaMART switches the push off after 48 hours of
    non-200 answers, and a shape we do not understand will not change on retry.
    """
    spec = SPECS.get(source)
    if spec is None:
        return []
    inner: Any = body
    if spec.envelope and isinstance(body, dict):
        inner = next((body[key] for key in spec.envelope if body.get(key)), None)
    items = inner if isinstance(inner, list) else [inner]
    return [item for item in items[:MAX_RECORDS_PER_PUSH] if isinstance(item, dict)]


def without_placeholder_name(
    source: str, record: dict[str, Any], name_field: str
) -> dict[str, Any]:
    """The record with a sender-invented name removed, so the agent never greets a person
    as "IndiaMART Buyer"."""
    spec = SPECS.get(source)
    value = record.get(name_field)
    if spec and isinstance(value, str) and value.strip().lower() in spec.placeholder_names:
        return {key: val for key, val in record.items() if key != name_field}
    return record


def record_key(mapped: dict[str, Any]) -> str | None:
    """The sender's own id for this lead, when the mapping names one: the dedupe unit.

    IndiaMART retries until it gets a 200 and says to dedupe on `UNIQUE_QUERY_ID`; keying
    on the body instead would read a retry whose `STATUS` text changed as a new lead.
    """
    raw = mapped.get(ENQUIRY_ID_KEY)
    if raw is None or isinstance(raw, (dict, list, bool)):
        return None
    text = str(raw).strip()
    return text[:200] if text else None


@dataclass(frozen=True, slots=True)
class EnquiryGround:
    """What the receiver knows about the enquiry a portal lead rests on."""

    source: str
    enquiry_id: str | None
    enquiry_type: str | None
    #: The enquiry instant, or None when the sender did not say in a form we can read.
    enquiry_at: datetime | None

    def is_enquiry(self) -> bool:
        spec = SPECS.get(self.source)
        if spec is None or not spec.enquiry_ground:
            return False
        allowed = spec.callable_enquiry_types
        if allowed is None:
            return True
        return (self.enquiry_type or "").strip().upper() in allowed

    def expires_at(self, *, received_at: datetime, window: timedelta) -> datetime:
        """The end of the seven-day window, from the enquiry or, failing that, receipt.

        Never from a FUTURE enquiry instant: a sender's clock running fast must not
        lengthen the window.
        """
        start = received_at if self.enquiry_at is None else min(self.enquiry_at, received_at)
        return start + window

    def evidence(self, *, lead_source_id: str) -> dict[str, str]:
        return {
            "lead_source": self.source,
            "lead_source_id": lead_source_id,
            "enquiry_id": self.enquiry_id or "",
            "enquiry_type": self.enquiry_type or "",
            "enquiry_at": self.enquiry_at.isoformat() if self.enquiry_at else "",
        }


def enquiry_instant(raw: Any) -> datetime | None:
    """The enquiry instant for the seven-day window.

    A timestamp with an offset is taken as written. IndiaMART's `QUERY_TIME` has none and
    its zone is undocumented, so a naive `YYYY-MM-DD HH:MM:SS` is read as IST: if the
    sender meant UTC, that reading is five and a half hours EARLIER than the truth, which
    shortens the window rather than stretching it. The same reading is NOT used for the
    thirty-minute transactional check (`service.submission_instant`), where the early
    reading would refuse every lead.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    text = raw.strip()
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return (parsed - IST).replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def enquiry_ground(source: str, mapped: dict[str, Any]) -> EnquiryGround | None:
    spec = SPECS.get(source)
    if spec is None or not spec.enquiry_ground:
        return None
    raw_type = mapped.get(ENQUIRY_TYPE_KEY)
    return EnquiryGround(
        source=source,
        enquiry_id=record_key(mapped),
        enquiry_type=str(raw_type).strip() if raw_type not in (None, "") else None,
        enquiry_at=enquiry_instant(mapped.get(ENQUIRY_AT_KEY)),
    )


def marked_do_not_call(mapped: dict[str, Any]) -> bool:
    value = mapped.get(DO_NOT_CALL_KEY)
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    return isinstance(value, str) and value.strip().lower() in _TRUTHY


__all__ = [
    "CRM_DO_NOT_CALL_RULE",
    "ENQUIRY_WINDOW_RULE",
    "MAX_RECORDS_PER_PUSH",
    "NOT_AN_ENQUIRY_RULE",
    "PUSH_SOURCES",
    "SPECS",
    "TOKEN_PARAM",
    "EnquiryGround",
    "enquiry_ground",
    "enquiry_instant",
    "is_push_source",
    "marked_do_not_call",
    "preset_mapping",
    "record_key",
    "records",
    "without_placeholder_name",
]
