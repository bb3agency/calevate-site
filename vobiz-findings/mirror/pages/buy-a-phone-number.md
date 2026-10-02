> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Buy a Phone Number on Vobiz – Step-by-Step Guide

> A complete, step-by-step guide to buying a phone number (DID) on Vobiz - in the console and via the API. Browse inventory, understand fees and India number series, purchase, route the number, and make your first call.

A phone number (a **DID** - Direct Inward Dialing number) is the entry point for every inbound call and the caller ID for outbound calls. This guide walks you through buying one on Vobiz two ways - in the **console** (point-and-click) and via the **API** (scriptable) - then routing it so it can take calls.

<Note>
  **You cannot port a number from another provider (including Plivo) into Vobiz.** There is no number transfer/porting flow. To run on Vobiz, **buy a new Vobiz number** from inventory using the steps below, then point your call flows at it. If you are migrating from Plivo, see the [Plivo migration guide](/docs/guides/plivo-to-vobiz).
</Note>

## Before you start

<Steps>
  <Step title="Create an account">
    Sign up at [console.vobiz.ai](https://console.vobiz.ai/app/register). New accounts get free starter credit to explore.
  </Step>

  <Step title="Find your API credentials">
    Your **Auth ID** (`MA_…`) and **Auth Token** are on the dashboard. You need them for every API request as the `X-Auth-ID` and `X-Auth-Token` headers.
  </Step>

  <Step title="Check your balance">
    Buying a number debits a **setup fee + the first monthly fee** immediately. Make sure your [balance](/docs/account/balance) covers both before you purchase.
  </Step>
</Steps>

## Option A - buy in the console

The fastest way to get a number is the dashboard.

<Steps>
  <Step title="Open the DID section">
    Sign in to [console.vobiz.ai](https://console.vobiz.ai) and open the **DID** (Numbers) section from the sidebar.

    <Frame>
      <img src="https://mintcdn.com/vobizai/cPP2drhQ7lKsmogc/images/console-new-ui/numbers.png?fit=max&auto=format&n=cPP2drhQ7lKsmogc&q=85&s=b70fce62d959e5c349cb7a841ff57533" alt="Vobiz console DID section showing available phone numbers with a country filter" width="1850" height="1388" data-path="images/console-new-ui/numbers.png" />
    </Frame>
  </Step>

  <Step title="Filter to the number you want">
    Filter by **country/region** to narrow the list. Check each number's **capabilities** (Vobiz numbers are voice-first) and its **setup fee** and **monthly fee** before you commit.
  </Step>

  <Step title="Purchase">
    Click **Buy** on the number you want. The setup fee and first monthly fee are debited from your account balance, and the number is assigned to your account immediately.
  </Step>

  <Step title="Route the number">
    A freshly purchased number is owned but **not yet routed**. Attach it to an **XML Application** (to drive call flows via your webhook) or assign it to a **SIP trunk**. See [Route your number](#route-your-number) below.
  </Step>
</Steps>

## Option B - buy via the API

Buying programmatically is a two-call flow: **browse inventory**, then **purchase by E.164**.

### 1. Browse inventory

List numbers available for purchase, filtered by country and an optional substring `search` against the E.164 number.

```bash cURL theme={null}
curl -X GET "https://api.vobiz.ai/api/v1/Account/{auth_id}/inventory/numbers?country=IN&search=80&page=1&per_page=25" \
  -H "X-Auth-ID: {auth_id}" \
  -H "X-Auth-Token: {auth_token}"
```

A response item looks like this - inspect `setup_fee`, `monthly_fee`, `currency`, and `capabilities` before buying:

```json Response (truncated) theme={null}
{
  "items": [
    {
      "id": "550e8400-e29b-41d4-a716-446655440000",
      "e164": "+918065551234",
      "country": "IN",
      "region": "Karnataka",
      "status": "active",
      "setup_fee": 100,
      "monthly_fee": 1.0,
      "currency": "INR"
    }
  ],
  "page": 1,
  "per_page": 25,
  "total": 500
}
```

See [List Inventory Numbers](/docs/account-phone-number/list-inventory-numbers) for the full parameter set. There is no separate search endpoint - use `country` + `search` here.

### 2. Purchase by E.164

Purchase a number by passing its `e164` in the request body. Keep the literal `+` (it is in the JSON body, so no URL-encoding). This debits `setup_fee + monthly_fee` immediately.

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST "https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/purchase-from-inventory" \
    -H "X-Auth-ID: {auth_id}" \
    -H "X-Auth-Token: {auth_token}" \
    -H "Content-Type: application/json" \
    -d '{"e164": "+918065551234"}'
  ```

  ```python Python theme={null}
  import requests

  auth_id = "{auth_id}"
  resp = requests.post(
      f"https://api.vobiz.ai/api/v1/Account/{auth_id}/numbers/purchase-from-inventory",
      headers={
          "X-Auth-ID": auth_id,
          "X-Auth-Token": "{auth_token}",
          "Content-Type": "application/json",
      },
      json={"e164": "+918065551234"},
  )
  resp.raise_for_status()
  print(resp.json()["number"]["e164"], "purchased")
  ```

  ```javascript Node.js theme={null}
  const authId = "{auth_id}";
  const resp = await fetch(
    `https://api.vobiz.ai/api/v1/Account/${authId}/numbers/purchase-from-inventory`,
    {
      method: "POST",
      headers: {
        "X-Auth-ID": authId,
        "X-Auth-Token": "{auth_token}",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ e164: "+918065551234" }),
    }
  );
  console.log(await resp.json());
  ```
</CodeGroup>

A successful purchase returns the number object with `account_id` set:

```json Response - 200 OK theme={null}
{
  "message": "Number purchased successfully",
  "number": {
    "id": "aabbccdd-1234-5678-90ab-cdef12345678",
    "account_id": "MA_XXXXXXXX",
    "e164": "+918065551234",
    "country": "IN",
    "region": "Karnataka",
    "capabilities": { "voice": true, "sms": false, "mms": false, "fax": false },
    "status": "active",
    "setup_fee": 100,
    "monthly_fee": 1.0,
    "currency": "INR",
    "voice_enabled": true,
    "purchased_at": "2026-03-25T10:00:00Z",
    "source": "inventory"
  }
}
```

See [Purchase from Inventory](/docs/account-phone-number/purchase-from-inventory) for every field and error case.

## Understand the fees

| Charge | When | Notes |
| - | - | - |
| **Setup fee** | Once, at purchase | One-time `setup_fee` shown on the inventory item. |
| **Monthly fee** | At purchase, then monthly | `monthly_fee` recurs to keep the number active. |

Both are debited in the number's `currency` (often **INR** for India numbers). For a **sub-account** (`SA_`) purchase, the **parent master account** (`MA_`) is charged - not the sub-account.

<Warning>
  If your balance can't cover `setup_fee + monthly_fee`, the purchase is rolled back and the number stays in inventory. A failed debit currently surfaces as a `500`; a number that isn't in inventory returns a `404`. Check your [balance](/docs/account/balance) first.
</Warning>

## India number series

India DIDs follow TRAI series rules - pick the series that matches your use case:

| Series | Use for |
| - | - |
| **140** | Promotional / outbound marketing calls. |
| **160** | Service / transactional calls (BFSI sector only). |
| **1800** | Toll-free inbound. |
| **92** | High-pickup mobile-style numbers. |

Some India numbers require Aadhaar verification (`aadhaar_verification_required` on the number object). Review [India compliance](/docs/compliance/india) before you purchase, and register on DLT where required - see [DLT registration](/docs/best-practices/dlt-registration).

## Route your number

A purchased number is owned but not yet routed. Pick one:

<Columns cols={2}>
  <Card title="Attach to an XML Application" icon="file-code" href="/docs/applications/attach-number">
    Point inbound calls at your webhook (`answer_url`) to drive call flows with VobizXML.
  </Card>

  <Card title="Assign to a SIP trunk" icon="server" href="/docs/trunks/assign-number">
    Route inbound calls to your PBX or AI platform over SIP.
  </Card>

  <Card title="Hand to a sub-account" icon="sitemap" href="/docs/account-phone-number/assign-subaccount">
    Move the DID into a sub-account's pool (mind the 15-day cool-off on unassign).
  </Card>

  <Card title="Make your first call" icon="phone-arrow-up-right" href="/docs/call/make-call">
    Use the number as the `from` on an outbound call.
  </Card>
</Columns>

## Manage and release

* **See what you own** - [List Account Phone Numbers](/docs/account-phone-number/list-account-phone-numbers).
* **Release a number** - [Unrent a Number](/docs/account-phone-number/unrent-number) stops the monthly rental fee and charges the number-release fee configured for your account. A standard release can be cancelled during its 24-hour pending window, which refunds the release fee. An immediate release cannot be cancelled, and you may not get the same digits again.
* **Sub-account 15-day cool-off** - unassigning a recently used DID from a sub-account is blocked for 15 days (`409 did_cool_off_in_effect`); see [Phone Numbers](/docs/account-phone-number).

## Troubleshooting

| Problem | Cause | Fix |
| - | - | - |
| `404 not_found` on purchase | Number already owned, released, or never stocked | Re-browse [inventory](/docs/account-phone-number/list-inventory-numbers) and pick an available `e164`. |
| `500 failed to purchase number` | Balance debit failed (`setup_fee + monthly_fee`) | Top up [balance](/docs/account/balance) and retry. |
| `401 Unauthorized` | Missing/incorrect headers or wrong path casing | Send `X-Auth-ID` + `X-Auth-Token`; use `/Account/` (capital A). |
| Number bought but calls don't arrive | Number not routed | [Attach it to an application](/docs/applications/attach-number) or [assign it to a trunk](/docs/trunks/assign-number). |

## Related

<Columns cols={2}>
  <Card title="Quick Start" icon="bolt" href="/docs/quick-start">
    The 4-step path from sign-up to your first call.
  </Card>

  <Card title="Phone Numbers API" icon="phone" href="/docs/account-phone-number">
    Full reference for listing, buying, and releasing numbers.
  </Card>

  <Card title="Migrating from Plivo?" icon="arrow-right-arrow-left" href="/docs/guides/plivo-to-vobiz">
    You can't port numbers - buy new Vobiz numbers and re-point your flows.
  </Card>

  <Card title="India compliance" icon="shield-halved" href="/docs/compliance/india">
    Number series, DLT, and KYC rules before you buy.
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.