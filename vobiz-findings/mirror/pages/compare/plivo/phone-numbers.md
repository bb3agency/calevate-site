> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Plivo vs Vobiz: Phone Numbers & DID API

> Migrate Plivo's PhoneNumber/Number API to Vobiz phone_numbers.*: search inventory, buy, release, list owned numbers, attach to trunks/sub-accounts, and what to do about porting.

Plivo splits number management across `PhoneNumber` (search the carrier catalog and buy) and `Number` (manage numbers you own); Vobiz folds both into a single `phone_numbers` resource backed by an **inventory** model - you buy by E.164 from Vobiz's pre-provisioned stock. A **15-day DID cool-off** applies on sub-account moves.

## Plivo → Vobiz mapping

| Operation | Plivo (endpoint / Python SDK) | Vobiz (endpoint / Python SDK) |
| - | - | - |
| Search available numbers | `GET /v1/Account/{auth_id}/PhoneNumber/` · `client.numbers.search(country_iso, type, pattern, ...)` | `GET /api/v1/Account/{auth_id}/inventory/numbers` · `client.phone_numbers.list_inventory_numbers(auth_id, country=, search=)` |
| Buy / rent a number | `POST /v1/Account/{auth_id}/PhoneNumber/{number}/` · `client.numbers.buy(number, app_id, ...)` | `POST /api/v1/Account/{auth_id}/numbers/purchase-from-inventory` · `client.phone_numbers.purchase_from_inventory(auth_id, e164, currency=)` |
| List owned numbers | `GET /v1/Account/{auth_id}/Number/` · `client.numbers.list(...)` | `GET /api/v1/Account/{auth_id}/numbers` · `client.phone_numbers.list_numbers(auth_id, limit=, offset=)` |
| Update a number (app, alias, subaccount) | `POST /v1/Account/{auth_id}/Number/{number}/` · `client.numbers.update(number, app_id=, subaccount=, alias=)` | Per-action endpoints - `assign_number_to_trunk` / `assign_did_to_subaccount` |
| Release / unrent a number | `DELETE /v1/Account/{auth_id}/Number/{number}/` · `client.numbers.delete(number)` | `DELETE /api/v1/Account/{auth_id}/numbers/{e164}` · `client.phone_numbers.unrent_number(auth_id, e164)` |
| Attach number to an app / route inbound | `update(number, app_id=...)` (Plivo Application) | `POST /api/v1/Account/{auth_id}/numbers/{phone_number}/assign` · `client.phone_numbers.assign_number_to_trunk(auth_id, phone_number, trunk_group_id)` |
| Detach inbound routing | `update(number, app_id="")` | `DELETE /api/v1/Account/{auth_id}/numbers/{phone_number}/assign` · `client.phone_numbers.unassign_number_from_trunk(auth_id, phone_number)` |
| Assign a number to a sub-account | `update(number, subaccount=...)` | `POST /api/v1/account/{auth_id}/numbers/{e164}/assign-subaccount` · `client.phone_numbers.assign_did_to_subaccount(auth_id, e164, sub_account_id)` |
| Remove a number from a sub-account | `update(number, subaccount="")` | `DELETE /api/v1/account/{auth_id}/numbers/{e164}/assign-subaccount` · `client.phone_numbers.unassign_did_from_subaccount(auth_id, e164, force=)` |

## Before / after: buy a number

Plivo POSTs to the specific `{number}` path and can attach a Plivo Application at buy time. Vobiz POSTs the E.164 (with the leading `+`) to a single `purchase-from-inventory` endpoint, which debits `setup_fee` + `monthly_fee` from your balance (for an `SA_` sub-account, the parent `MA_` is charged). After purchase the number is owned - assign it to a trunk to take inbound calls.

```python Plivo theme={null}
client.numbers.buy(
    number="14155551234",
    app_id="2087965050567",   # attach to a Plivo Application at buy time
)
```

```python Vobiz theme={null}
client.phone_numbers.purchase_from_inventory(
    auth_id="MA_XXXXXX",
    e164="+14155551234",
    currency="USD",            # defaults to the number's currency or USD
)
```

## Key differences & gotchas

* **E.164 formatting varies by endpoint.** `purchase_from_inventory` takes the number **with** the leading `+` in the body; `unrent_number` takes it **without** the `+` in the path; trunk/sub-account assignment endpoints take it **URL-encoded** (`%2B14155551234`).
* **Routing is by trunk.** Vobiz routes inbound by an explicit `assign`/`unassign` to a `trunk_group_id` (a UUID); assign a freshly purchased number to a trunk to route it.
* **15-day DID cool-off on sub-account moves.** `unassign_did_from_subaccount` returns `409 did_cool_off_in_effect` if the DID took a call in the last 15 days; never-used DIDs move immediately, and admins can bypass with `force=true`.
* **Sub-account assignment uses a lowercase `account` path** (`/api/v1/account/...`), unlike the capital-`Account` of every other number endpoint - the SDK hides this, but raw HTTP callers must match the casing.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.