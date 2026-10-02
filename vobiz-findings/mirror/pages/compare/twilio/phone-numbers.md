> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Twilio → Vobiz: Phone Numbers & DID

> Migrate Twilio's AvailablePhoneNumber search and IncomingPhoneNumber provisioning to Vobiz phone_numbers.*: browse inventory, purchase by E.164, list owned numbers, route inbound to a trunk/app, and release. Side-by-side Python and Node.

Twilio splits number management into two resources: `AvailablePhoneNumber` (search the carrier catalog) and `IncomingPhoneNumber` (provision and configure a number you own). Vobiz folds both into a single `phone_numbers` resource backed by an **inventory** model - you browse pre-provisioned stock, buy by E.164, then point inbound calls at a **trunk or app**. This page maps every Twilio number operation to its Vobiz equivalent, with copy-paste code.

<Note>
  Set your credentials once. `AUTH_ID` is your Vobiz Auth ID (`MA_…`) and `AUTH_TOKEN` is your Auth Token. In the Vobiz SDK, `api_key` **is** the Auth ID (sent as the `X-Auth-ID` header), and every account-scoped method takes that `auth_id` explicitly - the counterpart to Twilio's `AccountSid` in the URL path.
</Note>

## Twilio → Vobiz mapping

| Operation | Twilio (REST · twilio-python) | Vobiz (REST · Vobiz Python) |
| - | - | - |
| Client init | `Client(account_sid, auth_token)` | `Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)` |
| Search available local numbers | `GET /2010-04-01/Accounts/{Sid}/AvailablePhoneNumbers/US/Local.json` · `client.available_phone_numbers('US').local.list(area_code=, contains=, limit=)` | `GET /api/v1/Account/{auth_id}/inventory/numbers` · `client.phone_numbers.list_inventory_numbers(auth_id, country=, search=)` |
| Buy / provision a number | `POST /IncomingPhoneNumbers.json` · `client.incoming_phone_numbers.create(phone_number=)` | `POST /api/v1/Account/{auth_id}/numbers/purchase-from-inventory` · `client.phone_numbers.purchase_from_inventory(auth_id, e164=)` |
| List owned numbers | `GET /IncomingPhoneNumbers.json` · `client.incoming_phone_numbers.list(phone_number=, friendly_name=, limit=)` | `GET /api/v1/Account/{auth_id}/numbers` · `client.phone_numbers.list_numbers(auth_id)` |
| Route inbound to a voice app / trunk | `client.incoming_phone_numbers(sid).update(voice_url=)` or `update(trunk_sid=)` / `update(voice_application_sid=)` | `POST /api/v1/Account/{auth_id}/numbers/{number}/assign` · `client.phone_numbers.assign_number_to_trunk(auth_id, phone_number=, trunk_group_id=)` |
| Change the answering URL for a number | `update(voice_url=, voice_method=)` on the number | Set the `answer_url` on the trunk/app the number is assigned to (Vobiz fetches your VobizXML from there) |
| Assign a number to a sub-account | `update(sid, ...)` on a subaccount-scoped client | `POST /api/v1/account/{auth_id}/numbers/{e164}/assign-subaccount` · `client.phone_numbers.assign_did_to_subaccount(auth_id, e164=, sub_account_id=)` |
| Release / delete a number | `DELETE /IncomingPhoneNumbers/{Sid}.json` · `client.incoming_phone_numbers(sid).delete()` | `DELETE /api/v1/Account/{auth_id}/numbers/{e164}` · `client.phone_numbers.unrent_number(auth_id, e164=)` |
| Number identity | Opaque `PNxxxx…` SID | The E.164 number itself (`+14155551234`) is the key |
| Webhook signing on inbound | `X-Twilio-Signature` (HMAC-SHA1, Auth Token) | `X-Vobiz-Signature` on the request to your `answer_url` |

## Before / after: search inventory and buy

Twilio searches the live carrier catalog with `available_phone_numbers('US').local.list(...)`, reads `.phone_number` off each result, then provisions it with `incoming_phone_numbers.create(phone_number=...)`. Vobiz browses inventory with `list_inventory_numbers(...)` and buys by E.164 with `purchase_from_inventory(...)` - a single, predictable two-step flow.

<CodeGroup>
  ```python Twilio · Python theme={null}
  from twilio.rest import Client

  client = Client(ACCOUNT_SID, AUTH_TOKEN)

  # 1. Search the catalog for a local number
  available = client.available_phone_numbers('US').local.list(
      area_code=415,
      sms_enabled=True,
      voice_enabled=True,
      limit=20,
  )
  number = available[0].phone_number   # e.g. '+14155551234'

  # 2. Provision it onto your account
  incoming = client.incoming_phone_numbers.create(phone_number=number)
  print(incoming.sid, incoming.phone_number)
  ```

  ```python Vobiz · Python theme={null}
  from vobiz import Vobiz

  client = Vobiz(api_key=AUTH_ID, auth_token=AUTH_TOKEN)

  # 1. Browse available inventory
  available = client.phone_numbers.list_inventory_numbers(
      AUTH_ID,
      country='US',
      search='415',            # match on a prefix / pattern
  )
  number = available.numbers[0].e164   # e.g. '+14155551234'

  # 2. Purchase it by E.164 (with the leading +)
  bought = client.phone_numbers.purchase_from_inventory(AUTH_ID, e164=number)
  print(bought)
  ```

  ```javascript Twilio · Node theme={null}
  const twilio = require('twilio');
  const client = twilio(ACCOUNT_SID, AUTH_TOKEN);

  const available = await client.availablePhoneNumbers('US').local.list({
    areaCode: 415,
    smsEnabled: true,
    voiceEnabled: true,
    limit: 20,
  });
  const number = available[0].phoneNumber;

  const incoming = await client.incomingPhoneNumbers.create({ phoneNumber: number });
  console.log(incoming.sid, incoming.phoneNumber);
  ```

  ```javascript Vobiz · Node theme={null}
  import { VobizClient } from '@vobiz/sdk';
  const client = new VobizClient({ apiKey: AUTH_ID, authToken: AUTH_TOKEN });

  const available = await client.phoneNumbers.listInventoryNumbers(AUTH_ID, {
    country: 'US',
    search: '415',
  });
  const number = available.numbers[0].e164;

  const bought = await client.phoneNumbers.purchaseFromInventory(AUTH_ID, { e164: number });
  console.log(bought);
  ```
</CodeGroup>

## Before / after: route inbound calls

On Twilio you attach the answering logic **to the number** - set `voice_url` (a TwiML endpoint), or point the number at a Trunk (`trunk_sid`) or a TwiML App (`voice_application_sid`). On Vobiz, inbound routing is a first-class **assignment to a trunk**: `assign_number_to_trunk(...)` binds the DID to a `trunk_group_id`, and the trunk's `answer_url` returns your [VobizXML](/docs/xml/gather) when a call arrives. This keeps routing config in one place and lets many numbers share one flow.

<CodeGroup>
  ```python Twilio · Python theme={null}
  # Point the number's voice webhook at your TwiML endpoint
  client.incoming_phone_numbers(NUMBER_SID).update(
      voice_url='https://example.com/answer',
      voice_method='POST',
  )

  # ...or hand inbound calls to an Elastic SIP Trunk
  client.incoming_phone_numbers(NUMBER_SID).update(
      trunk_sid='TKxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx',
  )
  ```

  ```python Vobiz · Python theme={null}
  # Bind the DID to a trunk; the trunk's answer_url returns your VobizXML
  client.phone_numbers.assign_number_to_trunk(
      AUTH_ID,
      phone_number='%2B14155551234',   # E.164, URL-encoded (%2B = +)
      trunk_group_id='e3e55a78-1234-5678-90ab-cdef12345678',
  )
  ```

  ```javascript Twilio · Node theme={null}
  await client.incomingPhoneNumbers(NUMBER_SID).update({
    voiceUrl: 'https://example.com/answer',
    voiceMethod: 'POST',
  });
  ```

  ```javascript Vobiz · Node theme={null}
  await client.phoneNumbers.assignNumberToTrunk(AUTH_ID, {
    phone_number: '%2B14155551234',
    trunk_group_id: 'e3e55a78-1234-5678-90ab-cdef12345678',
  });
  ```
</CodeGroup>

When the call lands, Vobiz fetches the trunk's `answer_url` and expects VobizXML back - the same request/response webhook pattern you used with Twilio's `voice_url`, just returning `<Response>…</Response>` built with the `vobizxml` helper:

```python Vobiz · answer_url (Flask) theme={null}
from flask import Flask, Response
from vobiz import vobizxml

app = Flask(__name__)

@app.post('/answer')
def answer():
    resp = vobizxml.ResponseElement()
    menu = resp.add_gather(action='https://example.com/menu', method='POST',
                           input_type='dtmf', num_digits=1)
    menu.add_speak('Press 1 for sales, 2 for support.')
    return Response(resp.to_string(), mimetype='application/xml')
```

## Before / after: list, then release

Twilio lists provisioned numbers with `incoming_phone_numbers.list(...)` and releases one with `.delete()` on its SID. Vobiz lists owned numbers with `list_numbers(...)` and releases by E.164 with `unrent_number(...)`.

<CodeGroup>
  ```python Twilio · Python theme={null}
  # List owned numbers (optionally filtered)
  for n in client.incoming_phone_numbers.list(limit=50):
      print(n.sid, n.phone_number, n.voice_url)

  # Filter to one number
  matches = client.incoming_phone_numbers.list(phone_number='+14155551234')

  # Release it back to Twilio
  client.incoming_phone_numbers(NUMBER_SID).delete()
  ```

  ```python Vobiz · Python theme={null}
  # List owned numbers
  owned = client.phone_numbers.list_numbers(AUTH_ID)
  for n in owned.numbers:
      print(n.e164)

  # Release a number by E.164 (no leading +, in the path)
  client.phone_numbers.unrent_number(AUTH_ID, e164='14155551234')
  ```

  ```javascript Twilio · Node theme={null}
  const owned = await client.incomingPhoneNumbers.list({ limit: 50 });
  owned.forEach((n) => console.log(n.sid, n.phoneNumber, n.voiceUrl));

  await client.incomingPhoneNumbers(NUMBER_SID).remove();
  ```

  ```javascript Vobiz · Node theme={null}
  const owned = await client.phoneNumbers.listNumbers(AUTH_ID);
  owned.numbers.forEach((n) => console.log(n.e164));

  await client.phoneNumbers.unrentNumber(AUTH_ID, { e164: '14155551234' });
  ```
</CodeGroup>

## Key differences

* **The E.164 number is the key.** Twilio identifies a provisioned number by an opaque `PNxxxx…` SID; Vobiz uses the phone number itself (`+14155551234`). Store the E.164 and you can search, buy, route, and release without a lookup round-trip.
* **Inventory instead of a live catalog search.** `list_inventory_numbers` returns Vobiz's ready-to-buy stock, so search results are exactly what you can `purchase_from_inventory` in the next call - a deterministic two-step buy.
* **Routing lives on the trunk/app.** Where Twilio sets `voice_url` per number, Vobiz assigns the DID to a `trunk_group_id` and the trunk carries the `answer_url`. Many numbers can share one flow, and re-pointing a whole product is a single trunk edit rather than an update per number. Twilio's `trunk_sid`/`voice_application_sid` patterns map cleanly onto this model.
* **Same webhook contract.** Vobiz fetches your `answer_url` and expects XML back - identical to Twilio's `voice_url` request/response cycle. Swap the TwiML builder for [`vobizxml`](/docs/xml/gather) and the handler is a near tab-swap. Inbound requests carry an `X-Vobiz-Signature` you validate the same way you validated `X-Twilio-Signature`.
* **E.164 formatting is endpoint-specific.** `purchase_from_inventory` takes the number **with** the leading `+` in the body; `unrent_number` takes it **without** the `+` in the path; assignment endpoints take it **URL-encoded** (`%2B14155551234`). The SDK handles this for you.
* **Sub-account DID assignment is first-class.** `assign_did_to_subaccount(auth_id, e164=, sub_account_id=)` moves a DID to a child account in one call - handy for reseller and multi-tenant setups, alongside Vobiz's India KYC tooling.

See the rest of the [Twilio → Vobiz migration](/docs/compare/twilio/overview) for calls, recordings, SIP trunking, and webhooks.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.