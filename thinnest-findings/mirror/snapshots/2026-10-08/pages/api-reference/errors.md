> ## Documentation Index
> Fetch the complete documentation index at: https://docs.thinnest.ai/llms.txt
> Use this file to discover all available pages before exploring further.

# Errors

> The status, the machine-readable code that tells refusals apart, and whether retrying will help.

Every error answers a JSON body with a sentence for a person and a code for a program:

```json theme={null}
{
  "error": "That customer has asked not to be contacted.",
  "code": "opted_out"
}
```

## Branch on `code`, never on the sentence

The status says what kind of problem it is. The **`code`** says exactly which. A `403` on
`POST /calls` can mean the customer opted out, the number is on your do-not-call list, or the key
is not a full key; those are three different codes, and what you do about each is different (an
opted-out customer is never rung again, a do-not-call number can be taken off the list, a key can
be swapped for a full one).

The sentence in `error` is for showing to a person and **may be reworded in any release**. A
`code` does not change; new ones are only ever added. So match on `code`, and treat a code you do
not recognise as the generic one for its status.

```js theme={null}
const res = await fetch("https://app.thinnest.ai/api/v1/calls", { method: "POST", headers, body });
if (res.status === 403) {
  const { code } = await res.json();
  if (code === "opted_out" || code === "do_not_call") markUncallable(lead);
  else if (code === "key_scope_build" || code === "key_scope_read") alertOps("use a full key for calls");
}
```

### Which limit a `429` hit

A `429` names the limit in `code` and sizes it in a `limit` object, next to the `Retry-After`
header (seconds to wait):

```json theme={null}
{
  "error": "Over 60 calls a minute. Slow down and retry.",
  "code": "rate_limit_calls",
  "limit": { "name": "calls", "perMinute": 60 }
}
```

`limit.perMinute` is set for the limits counted per minute; `limit.max` (and `limit.windowSeconds`
when it has a window) for the others, such as `concurrent_calls` and the codes one number may be
sent.

### A `402` on `POST /calls`

`code` is `insufficient_balance`. The existing `reason` field says which limit stopped the call:
`no balance`, `trial spent`, `overdrawn`, `too many calls`, `balance unknown` or `retry buffer`.

## Statuses

| Status | Means | What to do |
| - | - | - |
| `400` | Malformed request, or a template blank is missing | Fix and resend. Retrying unchanged fails identically |
| `401` | Key missing, wrong or revoked | Check the header. **Do not retry**. The answer is the same whichever it is, so a probe learns nothing about your keys |
| `402` | Money or the plan: the balance cannot pay, or the plan does not include it | Top up or upgrade. `code` says which |
| `403` | The key's level, or a refusal about the person or number | `code` says which. Retrying unchanged fails the same way |
| `404` | No template of that name on your account | Check the name. Names are per account, so another business's template is invisible to you |
| `409` | Template not approved, WhatsApp not connected, contact opted out, or Meta has restricted the account | Look at **Templates** or **Channels**. Retrying makes a restriction worse |
| `409` | The same idempotency key is still in flight | Retry in a moment; the first request will have answered by then |
| `429` | Rate limited | Wait for `Retry-After` |
| `503` | WhatsApp is temporarily unavailable | Ours to fix, not yours. Safe to retry with the same idempotency key |

## Every code

Generated from the same list the API uses, so it cannot drift from it. A status with no more
specific code answers its generic one: `validation_failed` (400), `unauthorized` (401),
`payment_required` (402), `forbidden` (403), `not_found` (404), `conflict` (409), `gone` (410),
`unprocessable` (422), `rate_limited` (429), `internal_error` (500) and `service_unavailable`
(502, 503, 504).

**The key and the workspace it acts in**

| `code` | Means |
| - | - |
| `unauthorized` | The key is missing, wrong or revoked. The answer is the same whichever it is. |
| `key_scope_read` | The key is read-only and the request changes something. Use a build or full key. |
| `key_scope_build` | The key is a build key and the request needs a full key: messaging customers, sending codes, placing calls, spending money or changing who has access. |
| `workspace_not_found` | The `Thinnest-Workspace` header names a workspace that is unknown, is not one of your customers, or is not an `org_` id. |
| `workspace_deleted` | The customer named in `Thinnest-Workspace` was deleted. Restore it before its erase date. |
| `workspace_not_developer` | `Thinnest-Workspace` was sent from a workspace that is not a developer workspace. |
| `workspace_header_forbidden` | A key that belongs to one customer workspace cannot act as another. |

**Limits: which one was hit (a `limit` object names it)**

| `code` | Means |
| - | - |
| `rate_limit_resources` | Over the per-minute limit on ordinary API requests for this workspace. Wait for `Retry-After`. |
| `rate_limit_family` | Over the per-minute limit across all of a developer's customers. Wait for `Retry-After`. |
| `rate_limit_calls` | Over the per-minute limit on `POST /calls`. Wait for `Retry-After`. |
| `rate_limit_messages` | Over the per-minute limit on `POST /messages`. Wait for `Retry-After`. |
| `rate_limit_codes` | Over the per-minute limit on `POST /codes`. Wait for `Retry-After`. |
| `rate_limit_code_recipient` | This number has already been sent the most codes allowed in the window. Wait for `Retry-After`. |
| `concurrent_calls` | Every line the plan allows is already on a call. Retry when one finishes. |
| `number_daily_limit` | The `from` number you chose has placed its calls for today. Use another number. |
| `rate_limited` | Too many requests of another kind. Wait for `Retry-After` when it is given. |

**Placing a call**

| `code` | Means |
| - | - |
| `opted_out` | The customer asked not to be contacted. Nothing you change in the request makes it allowed. |
| `do_not_call` | The number is on the workspace's do-not-call list. Remove it from the list to call it. |
| `stop_list_unknown` | The opt-out and do-not-call lists could not be read, so the call was not placed. Safe to retry shortly. |
| `insufficient_balance` | The balance cannot pay for a call. `reason` says which limit stopped it: `no balance`, `trial spent`, `overdrawn`, `too many calls`, `balance unknown` or `retry buffer`. |
| `outside_calling_hours` | It is outside the calling hours and the request said `ifOutsideHours: refuse`. `nextOpening` says when. |
| `number_never_callable` | The calling hours never open for this number on the days given, in its own time zone. |
| `call_in_progress` | The person is on a call with this agent right now. |
| `call_already_scheduled` | A call to this number is already scheduled on this agent. Its `id` and `scheduledFor` come back. |
| `calling_not_set_up` | The workspace has no agent that answers the phone, or its phone provider is not connected. |
| `carrier_unavailable` | The phone provider would not place the call. 503 is worth retrying; 502 is this number. |
| `agent_not_found` | No agent of that name or id answers the phone in this workspace. |
| `agent_ambiguous` | More than one agent answers the phone. Name one in `agent`. |
| `from_number_invalid` | `from` is not a number this agent can call from. |

**Numbers**

| `code` | Means |
| - | - |
| `invalid_number` | The phone number could not be read. |
| `number_required` | Connect a WhatsApp number first; this needs one. |
| `number_claimed_elsewhere` | That number is already registered here. Get in touch if it is yours. |
| `needs_own_carrier_keys` | The number is on your own carrier account; add that account's API credentials to place calls from it. |

**Messages and codes**

| `code` | Means |
| - | - |
| `template_not_found` | No template of that name in this workspace. |
| `template_not_approved` | The template is not approved yet. |
| `template_language_missing` | The template is not approved in that language. `available` lists the ones it is. |
| `template_unsendable` | The template carries something no send can fill. Edit the template. |
| `code_template_not_found` | There is no approved one-time-code template matching the request. |
| `code_template_ambiguous` | More than one code template is approved; name one with `template` or `language`. |
| `whatsapp_not_connected` | The workspace has no connected WhatsApp number. |
| `whatsapp_blocked` | The WhatsApp account is restricted. Retrying makes a restriction worse. |
| `whatsapp_not_configured` | WhatsApp is not available on this deployment. |
| `free_allowance_used` | The free plan's monthly WhatsApp allowance is used. Pay as you go lifts it. |
| `send_failed` | The message provider would not take the message. Safe to retry with the same idempotency key. |

**Plan and money**

| `code` | Means |
| - | - |
| `plan_required` | The plan does not include this. Upgrade to use it. |
| `plan_limit` | The plan's allowance of this is used (for example customers). Upgrade, or remove one. |
| `payment_required` | Another 402: money or a plan upgrade is needed. Read `error`. |

**Idempotency**

| `code` | Means |
| - | - |
| `idempotency_in_progress` | That `Idempotency-Key` is still being processed. Retry in a moment for its answer. |

**The generic code for a status that has no specific one**

| `code` | Means |
| - | - |
| `validation_failed` | The request was malformed or a value is out of range. Retrying unchanged fails the same way. |
| `forbidden` | Not allowed, for a reason with no more specific code. |
| `not_found` | No such resource in this workspace. |
| `conflict` | The request clashes with the resource's current state. |
| `gone` | It existed and has been deleted or has expired. |
| `unprocessable` | The request is well formed but cannot be acted on in the state things are in. |
| `internal_error` | Something failed on our side. Safe to retry; if it persists, tell us. |
| `service_unavailable` | A dependency is unavailable. Safe to retry shortly. |

## On 409 in particular

<Warning>
  When Meta restricts an account, every refused request is a signal that the
  business has not noticed. **A retry loop against a restriction extends it.**

  The console shows the reason and when it lifts. Go and look rather than
  retrying.
</Warning>

`409` also covers the correct-behaviour cases: a **marketing** template
addressed to somebody who opted out is refused. That is not a bug to work
around.

## Retry policy that will not hurt you

```js theme={null}
const RETRYABLE = new Set([429, 500, 502, 503, 504]);

async function send(payload, key, attempt = 0) {
  const res = await post(payload, key);

  if (res.ok) return res.json();

  if (!RETRYABLE.has(res.status) || attempt >= 4) {
    // 400, 401, 404 and 409 never succeed on a retry. Surface them.
    throw new Error(`${res.status}: ${await res.text()}`);
  }

  const after = Number(res.headers.get("Retry-After") ?? 0);
  const backoff = after > 0 ? after * 1000 : 2 ** attempt * 1000;

  await sleep(backoff);
  // Same idempotency key on every attempt — that is what makes this safe.
  return send(payload, key, attempt + 1);
}
```

The important line is the last one: **the same idempotency key on every
attempt**. Generating a fresh key per retry turns a safe retry into a duplicate
message.

Keys are honoured for 24 hours, so a backoff that runs for minutes is well
inside the window. A job parked overnight and released the next morning is not —
it will send.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.