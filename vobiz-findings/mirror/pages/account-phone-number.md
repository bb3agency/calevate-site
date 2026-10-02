> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Phone Numbers API – Buy, Manage & Release DIDs Globally

> Buy, manage, and release virtual phone numbers globally via the Vobiz API - covering India DIDs, 160 series, 140 series, E.164 numbers across 130+ countries with INR billing.

Use the Phone Numbers API to list owned numbers, browse inventory, purchase numbers, and release numbers back to inventory.

<Info>
  **Key Features**

  * List all phone numbers owned by your account with pagination support
  * Browse available phone numbers in inventory
  * Purchase numbers from inventory and assign to your account
  * Release numbers back to inventory when no longer needed
  * Master accounts (MA\_) can include numbers from sub-accounts
  * View detailed number information including capabilities, pricing, and status
</Info>

## Base URL

```text Base URL theme={null}
https://api.vobiz.ai/api
```

## Authentication

All Phone Number API endpoints require authentication via `X-Auth-ID` and `X-Auth-Token` headers.

<Info>
  **Required Headers:**

  * `X-Auth-ID` - Your Auth ID (e.g., `{auth_id}`)
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

## Available Operations

* [The PhoneNumber Object](/docs/account-phone-number/account-phone-number-object) - View the complete structure and attributes of a PhoneNumber object including number details, capabilities, billing information, and provider settings.
* [List Account Phone Numbers](/docs/account-phone-number/list-account-phone-numbers) - GET request to retrieve all phone numbers owned by your account with pagination support. Master accounts can include numbers from sub-accounts.
* [List Inventory Numbers](/docs/account-phone-number/list-inventory-numbers) - GET request to browse available phone numbers in inventory (not assigned to any account) that are available for purchase.
* [Purchase from Inventory](/docs/account-phone-number/purchase-from-inventory) - POST request to purchase a number from inventory and assign it to your account. Debits balance for setup and monthly fees.
* [Unrent a Number](/docs/account-phone-number/unrent-number) - DELETE request to release a phone number for an account-specific release fee. The number will be unassigned from your account and trunk group; cancelling a pending standard release refunds the fee.
* [Assign DID to Sub-Account](/docs/account-phone-number/assign-subaccount) - POST request to assign a parent-pool DID to one of your sub-accounts.
* [Unassign DID from Sub-Account](/docs/account-phone-number/unassign-subaccount) - DELETE request to move a DID back to the parent pool, subject to a 15-day cool-off.

## DID 15-day cool-off

When you move a DID back to the parent pool from a sub-account, a **15-day cool-off** prevents a recently active number from being reassigned to another customer too quickly:

* If the DID had a call within the last 15 days, [unassignment](/docs/account-phone-number/unassign-subaccount) is rejected with `409 did_cool_off_in_effect` (the response includes `cool_off_until` and `cool_off_remaining_seconds`).
* A DID that was never used moves back immediately.
* Admins can override the cool-off with `?force=true` (writes an audit record).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.