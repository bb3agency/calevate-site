"""Zoho CRM and HubSpot: create or update the caller's record, and look a caller up (D-700).

Both connect by OAuth (`oauth.py`); the refresh token is the client's `integration_credentials`
row (`zoho_crm` / `hubspot`). The record is matched on the caller's phone number, which is
OUR record of who is on the line, never a model argument.

VERIFIED-VENDOR-DOCS, read 9 Oct 2026:

Zoho CRM v8 (zoho.com/crm/developer/docs/api/v8/…):
* `POST {api_domain}/crm/v8/{module}/upsert` with `{"data": [record],
  "duplicate_check_fields": ["Phone"]}` and `Authorization: Zoho-oauthtoken <token>`; each
  `data[i]` answers `code` `SUCCESS`, `action` `insert`|`update` and `details.id`
  (…/upsert-records.html). `Last_Name` is mandatory on Leads and Contacts
  (…/insert-records.html). `api_domain` comes from the token response (…/access-refresh.html).
* `GET {api_domain}/crm/v8/{module}/search?phone=…` searches every phone field and needs
  `ZohoSearch.securesearch.READ` besides the module scope (…/search-records.html). An empty
  result is HTTP 204, read as "not found".

HubSpot (developers.hubspot.com/docs/api-reference/…):
* Search: `POST https://api.hubapi.com/crm/objects/2026-09/contacts/search` with
  `filterGroups[].filters[] {propertyName, operator: "EQ", value}`, `properties`, `limit`;
  phone values are matched WITHOUT the country code because HubSpot normalises numbers
  (…/latest/crm/search-the-crm). 5 search requests a second per account.
* Create: `POST https://api.hubapi.com/crm/v3/objects/contacts` with `{properties}`
  (…/crm-contacts-v3/guide; v1 to v4 are supported until September 2027,
  …/legacy/migration-guide).
* Update: `POST /crm/objects/2026-09/contacts/batch/upsert` with `inputs: [{id,
  properties}]` (…/latest/crm/objects/contacts/batch/upsert-contacts). ⚠ Which property
  `id` is matched against when `idProperty` is left out is not stated; we send
  `idProperty: "hs_object_id"` with the id search returned, and OPERATIONS gate A-4 proves it
  on a real portal before the first client relies on an update.
"""

from __future__ import annotations

from typing import Any, Final
from urllib.parse import quote, urlsplit

from apps.api.actions.schema import PreparedRequest

HUBSPOT_API: Final = "https://api.hubapi.com"
HUBSPOT_SEARCH_PROPERTIES: Final = ("firstname", "lastname", "email", "lifecyclestage")
ZOHO_NAME_FIELDS: Final = ("Full_Name", "First_Name", "Last_Name")
#: The Zoho fields a lookup hands the model: a name to greet by and a little context.
ZOHO_LOOKUP_FIELDS: Final = ("Full_Name", "First_Name", "Last_Name", "Lead_Status", "Description")
#: What a Zoho record's mandatory `Last_Name` holds when the caller gave no name.
UNNAMED_CALLER: Final = "Phone caller"

#: Zoho's API hosts (the `api_domain` a token response names). Checked before a token is
#: sent anywhere, as `oauth.ZOHO_ACCOUNTS_HOSTS` is for the accounts server. Only
#: `www.zohoapis.in` is printed by a page we read (access-refresh.html's sample); the rest
#: follow the data-centre suffixes of multi-dc.html and are UNVERIFIED until a client in
#: that data centre connects (OPERATIONS gate A-2). An unlisted host is refused, which
#: fails closed: that client sees "could not connect", never a token sent elsewhere.
ZOHO_API_HOSTS: Final = frozenset(
    {
        "www.zohoapis.com",
        "www.zohoapis.in",
        "www.zohoapis.eu",
        "www.zohoapis.com.au",
        "www.zohoapis.jp",
        "www.zohoapis.uk",
        "www.zohoapis.sa",
        "www.zohoapis.ca",
    }
)


def zoho_api_domain(raw: object) -> str | None:
    if not isinstance(raw, str):
        return None
    parts = urlsplit(raw.strip())
    if parts.scheme != "https" or (parts.hostname or "") not in ZOHO_API_HOSTS:
        return None
    return f"https://{parts.hostname}"


def zoho_upsert(
    *, api_domain: str, token: str, module: str, record: dict[str, str]
) -> PreparedRequest:
    return PreparedRequest(
        method="POST",
        url=f"{api_domain}/crm/v8/{module}/upsert",
        headers={"Authorization": f"Zoho-oauthtoken {token}", "Content-Type": "application/json"},
        json_body={"data": [record], "duplicate_check_fields": ["Phone"]},
    )


def zoho_search(*, api_domain: str, token: str, module: str, phone_e164: str) -> PreparedRequest:
    return PreparedRequest(
        method="GET",
        url=f"{api_domain}/crm/v8/{module}/search?phone={quote(phone_e164, safe='')}&per_page=1",
        headers={"Authorization": f"Zoho-oauthtoken {token}"},
    )


def zoho_first_record(body: object) -> dict[str, Any] | None:
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, list) and data and isinstance(data[0], dict):
        return data[0]
    return None


def zoho_upsert_ok(body: object) -> bool:
    record = zoho_first_record(body)
    return record is not None and record.get("code") == "SUCCESS"


def national_number(phone_e164: str) -> str:
    """The number without `+91`, which is how HubSpot's search wants it."""
    digits = phone_e164.lstrip("+")
    return digits[2:] if digits.startswith("91") and len(digits) == 12 else digits


def hubspot_search(*, token: str, phone_e164: str) -> PreparedRequest:
    return PreparedRequest(
        method="POST",
        url=f"{HUBSPOT_API}/crm/objects/2026-09/contacts/search",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json_body={
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": "phone",
                            "operator": "EQ",
                            "value": national_number(phone_e164),
                        }
                    ]
                }
            ],
            "properties": list(HUBSPOT_SEARCH_PROPERTIES),
            "limit": 1,
        },
    )


def hubspot_first_result(body: object) -> dict[str, Any] | None:
    results = body.get("results") if isinstance(body, dict) else None
    if isinstance(results, list) and results and isinstance(results[0], dict):
        return results[0]
    return None


def hubspot_create(*, token: str, properties: dict[str, str]) -> PreparedRequest:
    return PreparedRequest(
        method="POST",
        url=f"{HUBSPOT_API}/crm/v3/objects/contacts",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json_body={"properties": properties},
    )


def hubspot_update(*, token: str, record_id: str, properties: dict[str, str]) -> PreparedRequest:
    return PreparedRequest(
        method="POST",
        url=f"{HUBSPOT_API}/crm/objects/2026-09/contacts/batch/upsert",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json_body={
            "inputs": [{"id": record_id, "idProperty": "hs_object_id", "properties": properties}]
        },
    )


__all__ = [
    "HUBSPOT_SEARCH_PROPERTIES",
    "UNNAMED_CALLER",
    "ZOHO_API_HOSTS",
    "ZOHO_LOOKUP_FIELDS",
    "hubspot_create",
    "hubspot_first_result",
    "hubspot_search",
    "hubspot_update",
    "national_number",
    "zoho_api_domain",
    "zoho_first_record",
    "zoho_search",
    "zoho_upsert",
    "zoho_upsert_ok",
]
