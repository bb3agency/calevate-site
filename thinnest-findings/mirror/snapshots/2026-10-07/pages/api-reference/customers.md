> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Customers

> Build your own product on the API: a workspace for each of your customers, reached with one key.

A **customer** is a workspace you create for one of your own customers — with its own agents,
contacts, knowledge, phone numbers and WhatsApp. Your one API key reaches any of them by adding a
header. Everything they use is billed to you.

<Note>
  Your first customer makes your workspace a **developer workspace**. A workspace that resells our
  console under its own brand (white label) cannot also have API customers.
</Note>

## Create a customer

```http theme={null}
POST /api/v1/customers
Authorization: Bearer ta_live_…
Idempotency-Key: 6f1d2c9a-…
Content-Type: application/json
```

```json theme={null}
{
  "name": "Acme Dental",
  "externalId": "acme-42",
  "metadata": { "tier": "gold", "seats": 3 },
  "timezone": "Asia/Kolkata"
}
```

`201 Created`

```json theme={null}
{
  "id": "org_1f2e…",
  "name": "Acme Dental",
  "externalId": "acme-42",
  "metadata": { "tier": "gold", "seats": 3 },
  "timezone": "Asia/Kolkata",
  "allottedCallLines": null,
  "archivedAt": null,
  "eraseAfter": null,
  "createdAt": "2026-10-06T10:00:00Z"
}
```

| Field | |
| - | - |
| `name` | Required. 1–120 characters. |
| `externalId` | Your own id for this customer: 1–128 letters, digits, `.` `_` `:` or `-`. Unique among your customers. |
| `metadata` | Up to 50 keys (1–40 characters each). Values are strings (up to 500 characters), numbers or booleans — no nested objects or lists. 8 KB in all. |
| `timezone` | An IANA time zone such as `Asia/Kolkata`. |

Send an `Idempotency-Key` so a retried request returns the same customer instead of making a
second one. Creating a customer needs a key with **full** access.

| Status | Why |
| - | - |
| `400` | A field is wrong — the message names it. |
| `402` | Your plan's customer limit is reached. |
| `409` | Another customer already has that `externalId`, or your workspace uses white label. |

## Work inside a customer

Add `Thinnest-Workspace` with the customer's `id` to **any** request. It runs inside that customer
as if the customer had sent it.

```http theme={null}
POST /api/v1/agents
Authorization: Bearer ta_live_…
Thinnest-Workspace: org_1f2e…
```

```json theme={null}
{ "name": "Front desk" }
```

| You send | You get |
| - | - |
| No header, or your own workspace | Your own workspace |
| One of your customers | That customer |
| Someone else's customer, or an id that does not exist | `404 Workspace not found.` |
| A customer you deleted | `410` — with when it was deleted and when it will be erased |
| The header from a workspace with no customers | `400` |

Your key's access level applies inside the customer too: a read-only key can only read there.

## List customers

```http theme={null}
GET /api/v1/customers?limit=50
```

Newest first. Pass `nextCursor` back as `cursor` for the next page. Filters: `externalId`,
`archived=true` (deleted, waiting to be erased), `createdAfter`, `createdBefore` (ISO 8601 times).

Manage customers from your own workspace — **without** `Thinnest-Workspace`.

## Get one customer

```http theme={null}
GET /api/v1/customers/org_1f2e…
```

The customer, plus:

```json theme={null}
{
  "counts": { "agents": 2, "phoneNumbers": 1, "contacts": 418 },
  "spendThisMonthMicro": 1840000
}
```

`spendThisMonthMicro` is what this customer's usage has cost you since the 1st of the month (UTC),
in millionths of your currency — `1840000` is ₹1.84.

## Update a customer

```http theme={null}
PATCH /api/v1/customers/org_1f2e…
```

```json theme={null}
{ "name": "Acme Dental Pvt", "metadata": { "tier": null, "region": "south" } }
```

You can change `name`, `externalId` (`null` clears it), `timezone`, `allottedCallLines` (how many of
your call lines this customer may use at once; `null` for no cap) and `metadata`. Metadata is
**merged**: keys you leave out are kept, and a key set to `null` is removed.

## Delete a customer

```http theme={null}
DELETE /api/v1/customers/org_1f2e…
```

<Warning>
  Release the customer's phone numbers and disconnect its WhatsApp number first. Deleting is
  refused (`409`, naming them) while it still holds either, because releasing a number cannot be
  undone.
</Warning>

When you delete a customer:

* requests into it answer `410`, and keys made for it stop working;
* its webhooks are switched off, its campaigns cancelled, its sequences and scheduled callbacks stopped;
* a call already in progress finishes;
* **30 days later it is erased**: every conversation, contact, recording and file.

Until then you can bring it back:

```http theme={null}
POST /api/v1/customers/org_1f2e…/restore
```

Restoring does not restart campaigns or bring back old keys — start those again yourself.

## Keys for one customer

To give a customer its own API access, or to run one customer's integration on a key that cannot
reach the others:

```http theme={null}
POST /api/v1/customers/org_1f2e…/keys
```

```json theme={null}
{ "name": "Acme's dashboard", "scope": "read" }
```

The key (`ta_live_…`) is in the response **once**. `scope` is `full`, `build` or `read`.

| | |
| - | - |
| `GET /api/v1/customers/{id}/keys` | The customer's keys — name, prefix, access level, last used. Never the key itself. |
| `DELETE /api/v1/customers/{id}/keys/{keyId}` | Revoke it, immediately. |

A key made for one customer works only in that customer.

## Billing

Everything your customers use — calls, messages, replies, phone number rental — is charged to
**your** balance at your plan's prices. Your customers have no balance of their own. When your
balance runs out, your customers stop with you until you top up.

A customer is always on your plan. Your plan decides how many customers you can have:

| Plan | Customers |
| - | - |
| Free and Pay as you go | 3 |
| Pro | 100 |
| Scale | 1,000 |
| Enterprise | 10,000 |

Need more? Write to us. A deleted customer counts until it is erased.

On the Free plan, the included replies, voice minutes and WhatsApp messages are **shared** by you and
all your customers — one trial, not one each.

### What a customer can see

Your balance stays yours. Inside a customer, `GET /api/v1/usage` returns `"billedTo": "developer"` and
no `wallet`, and its console shows no balance and nothing to pay — so a key you give a customer, or a
person you invite into it, never sees what you hold.

### Notifications

Your customers have no members of their own, so anything we would tell them — a webhook switched off,
a template rejected, a campaign in trouble — comes to **you**, with the customer's name in the title,
and is emailed according to your own notification settings. Its **Open** link takes you into that
customer's workspace, to the template or campaign it is about. So does a low-balance warning caused by
your customers' usage.

### Currency

You and your customers use one currency, fixed once you have a customer. If you have not chosen one
when you create your first customer, it is set to rupees — pick dollars before then if you bill in
dollars.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.