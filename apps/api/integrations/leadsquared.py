"""LeadSquared: the client's own CRM, written to through its Lead.Capture API (D-942).

The inbound half — a LeadSquared webhook posting new leads to us — is a lead source like any
other (`ingest/portals.py`). This module is the outbound half: an `outbound_webhooks` row of
kind `leadsquared` that the D-23 fan-out delivers `lead.created` and call outcomes to.

VERIFIED-VENDOR-DOCS, read 30 Oct 2026:

* `POST https://{host}/v2/LeadManagement.svc/Lead.Capture?accessKey=…&secretKey=…`, body a
  JSON array of `{"Attribute", "Value"}`; matched on ProspectID, then EmailAddress, then
  Phone, or as `SearchBy` names; success is 200 with `{"Status": "Success", "Message":
  {"Id", "RelatedId", "IsCreated"}}`; 401 bad keys, 429 above 25 calls per 5 seconds
  (apidocs.leadsquared.com/capture-lead). An upsert, so a retried delivery updates the
  same lead rather than creating a second one.
* The host is the account's region (help.leadsquared.com/how-do-i-obtain-api-access-keys-
  in-leadsquared, updated 10 Apr 2025): `api` (Singapore), `api-us11`, `api-in21` (Mumbai),
  `api-in22` (Hyderabad), `api-ir31`, `api-ca12`, all `.leadsquared.com`. Keys and host are
  under My Profile → Settings → API and Webhooks.
* Leads changed through the Update Lead API do not fire update-based webhooks or automations
  unless the call carries `postUpdatedLead=true` (apidocs.leadsquared.com/update-a-lead).
  We write with Lead.Capture, not Lead.Update, and subscribe to nothing but lead create, so
  the client's own LeadSquared automations on lead UPDATE do not see our writes — said on
  the set-up screen rather than worked around.

UNVERIFIED: the Phone format LeadSquared stores and matches on. The capture page's sample is
a bare ten digits and no page states the stored form; we send `+91-` and the ten digits (the
form IndiaMART's push uses for Indian numbers), and OPERATIONS gate A-13 confirms a match on
a real account before a client relies on updates landing on the existing lead.

The access key and the secret key are BOTH credentials (the vendor page calls them
confidential), so both are sealed in the one `integration_credentials` row; only the host
is kept in the clear.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

#: The documented API hosts. A host outside this set is refused before a key is sent.
API_HOSTS: Final = frozenset(
    {
        "api.leadsquared.com",
        "api-us11.leadsquared.com",
        "api-in21.leadsquared.com",
        "api-in22.leadsquared.com",
        "api-ir31.leadsquared.com",
        "api-ca12.leadsquared.com",
    }
)
CAPTURE_PATH: Final = "/v2/LeadManagement.svc/Lead.Capture"
CHANNEL: Final = "leadsquared"
KIND: Final = "leadsquared"

#: Authored refusal codes, rendered by the delivery screen and never vendor prose.
AUTH_FAILED_REASON: Final = "leadsquared_auth_failed"
REJECTED_REASON: Final = "leadsquared_rejected"
NO_CREDENTIAL_REASON: Final = "leadsquared_not_connected"
NO_PHONE_REASON: Final = "leadsquared_no_phone"
NOTHING_TO_WRITE_REASON: Final = "leadsquared_nothing_to_write"

#: A LeadSquared schema name: `FirstName`, `mx_Call_Outcome`.
_ATTRIBUTE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

#: Which of OUR event fields fill which LeadSquared attribute when the client chose none.
DEFAULT_FIELDS: Final[dict[str, dict[str, str]]] = {
    "lead.created": {"FirstName": "name"},
    "lead.updated": {"FirstName": "name"},
}
#: The events a LeadSquared destination may carry: a lead, and what a call to it decided.
EVENTS: Final = ("lead.created", "lead.updated", "call.completed", "call.updated")


def host_of(raw: object) -> str | None:
    """The API host named by what the client pasted (`https://api-in21.leadsquared.com/v2/`
    or the bare host), or None when it is not a documented one."""
    if not isinstance(raw, str):
        return None
    text = raw.strip().lower()
    text = re.sub(r"^https?://", "", text).split("/", 1)[0]
    return text if text in API_HOSTS else None


def valid_attribute(name: str) -> bool:
    return bool(_ATTRIBUTE.match(name))


def seal_keys(access_key: str, secret_key: str) -> str:
    """The one sealed value. The secret key is LAST, so the credential list's last four
    characters are the secret key's, which is what the client sees in LeadSquared."""
    return f"{access_key.strip()}\n{secret_key.strip()}"


@dataclass(frozen=True, slots=True)
class Keys:
    access_key: str
    secret_key: str


def open_keys(sealed: str) -> Keys | None:
    access, sep, secret = sealed.partition("\n")
    if not sep or not access or not secret:
        return None
    return Keys(access_key=access, secret_key=secret)


def phone_value(phone_e164: str) -> str:
    """`+91-` and the ten digits for an Indian number; any other number as E.164."""
    if phone_e164.startswith("+91") and len(phone_e164) == 13:
        return f"+91-{phone_e164[3:]}"
    return phone_e164


def capture_body(
    *, event: str, data: dict[str, Any], phone_e164: str, fields: dict[str, str]
) -> list[dict[str, str]] | None:
    """The Lead.Capture body for one event, or None when it would write nothing but the
    match key (a call event the client mapped no attribute for)."""
    chosen = fields or DEFAULT_FIELDS.get(event, {})
    attributes: list[dict[str, str]] = []
    for attribute, ours in chosen.items():
        value = data.get(ours)
        if value is None or value == "" or not valid_attribute(attribute):
            continue
        attributes.append({"Attribute": attribute, "Value": str(value)})
    if not attributes and not event.startswith("lead."):
        return None
    return [
        {"Attribute": "Phone", "Value": phone_value(phone_e164)},
        *attributes,
        {"Attribute": "SearchBy", "Value": "Phone"},
    ]


def capture_ok(body: object) -> bool:
    return isinstance(body, dict) and body.get("Status") == "Success"


__all__ = [
    "API_HOSTS",
    "AUTH_FAILED_REASON",
    "CAPTURE_PATH",
    "CHANNEL",
    "DEFAULT_FIELDS",
    "EVENTS",
    "KIND",
    "NOTHING_TO_WRITE_REASON",
    "NO_CREDENTIAL_REASON",
    "NO_PHONE_REASON",
    "REJECTED_REASON",
    "Keys",
    "capture_body",
    "capture_ok",
    "host_of",
    "open_keys",
    "phone_value",
    "seal_keys",
    "valid_attribute",
]
