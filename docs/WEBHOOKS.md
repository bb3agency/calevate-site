# Calevate Webhooks — Integration Contract

This is the contract between Calevate and your systems, in both directions:

1. **Events we send you** — signed POSTs from Calevate to your endpoint when a lead
   lands or a call finishes.
2. **Sending leads to us** — your forms/CRM POSTing leads into Calevate for the
   instant-callback flow.

Everything below is generated against the shipping code. Where a feature exists in the
schema but nothing emits it yet, we say so.

---

## 1. Events we send you

### 1.1 Event types

| Event                | Fires when                                                                 | Status |
| -------------------- | -------------------------------------------------------------------------- | ------ |
| `lead.created`       | A lead lands via your ingest webhook — in the same transaction as the lead row, before any call is attempted. | Live |
| `call.completed`     | The post-call pipeline finishes for a call whose final status is `completed` (summary and extraction already exist when you hear about it). | Live |
| `lead.updated`       | — | Reserved, not yet emitted |
| `campaign.completed` | — | Reserved, not yet emitted |

All four names are accepted when you register an endpoint; the two reserved ones simply
never fire today. `GET /v1/integrations/events` returns the live list.

### 1.2 The envelope

Every delivery is one JSON object with the same five top-level keys, regardless of event
type:

```json
{
  "id": "0198c9a4-3f0e-7d21-9b4a-8c2e51d0af37",
  "event": "lead.created",
  "account_id": "0198c2b1-77aa-7b90-8d13-402f9e6c1b55",
  "created_at": "2026-08-11T09:14:03.512345+00:00",
  "data": {
    "lead_id": "0198c9a4-3ef1-7c02-a5d6-1f7b30c88e21",
    "phone": "[redacted]",
    "name": "Ravi Kumar",
    "source": "webhook",
    "status": "new"
  }
}
```

- **`id` is the delivery id, not the object id.** If we retry, the retry carries the
  *same* `id`. Deduplicate on `id` and you deduplicate retries — while two genuine
  updates to the same lead keep distinct ids and both get through. Do not deduplicate
  on `data.lead_id`.
- **`phone` is masked by default** — the literal string `"[redacted]"`. Receiving the
  raw E.164 number is a per-endpoint opt-in you make explicitly with us; it is recorded
  in your endpoint config, not assumed.
- `created_at` is UTC, ISO-8601.

A `call.completed` envelope carries in `data`: `call_id`, `lead_id` (may be null),
`direction`, `duration_s`, `outcome`, `sentiment`, `summary`. The summary — never the
transcript — is what leaves on a webhook.

An optional per-endpoint field mapping can rename our `data` keys to yours (e.g.
`lead_id` → `LeadRef`). When a mapping is configured, **only mapped fields are sent**,
and a mapped field absent from a given event is omitted rather than sent as `null`.
Ask us to set this up if your CRM needs fixed column names.

### 1.3 Headers on every delivery

| Header                 | Value |
| ---------------------- | ----- |
| `Content-Type`         | `application/json` |
| `X-Calevate-Signature` | `t={timestamp},v1={hmac_hex}` — see §1.4 |
| `X-Calevate-Timestamp` | Unix seconds, same value as `t` in the signature |
| `X-Calevate-Event`     | The event type, e.g. `lead.created` |
| `X-Calevate-Delivery`  | The delivery id (same as the envelope `id`) |
| `User-Agent`           | `Calevate-Webhooks/1` |

### 1.4 Verifying the signature

The signature is HMAC-SHA256, keyed with your endpoint's secret, over the string
`"{timestamp}.{body}"` — the Unix timestamp, a literal dot, then the **raw request body
bytes exactly as received**. Do not re-serialize the JSON before verifying (we send it
compact, with no spaces after separators).

```python
import hashlib, hmac, time


def verify(secret: str, signature_header: str, raw_body: bytes) -> bool:
    parts = dict(p.split("=", 1) for p in signature_header.split(",") if "=" in p)
    ts, provided = parts.get("t"), parts.get("v1")
    if not ts or not provided:
        return False
    if abs(int(time.time()) - int(ts)) > 300:  # reject > 5 min skew
        return False
    signed = ts.encode() + b"." + raw_body
    expected = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)  # constant-time compare
```

Three rules that matter:

- **Reject timestamps older or newer than 300 seconds.** The timestamp is inside the
  signed string, so an attacker cannot move a captured signature onto a fresh timestamp.
- **Compare in constant time** (`hmac.compare_digest` or your language's equivalent),
  never with `==`.
- Retries are **re-signed with a fresh timestamp** at send time, so the 5-minute window
  never rejects a legitimate retry.

### 1.5 Delivery rules

- **Only a 2xx response counts as delivered.** Anything else — including 3xx — is a
  failure we retry. **Redirects are not followed**: we will not chase a signed body to
  a host you did not register.
- **Timeout is 10 seconds** per attempt. Respond fast and process async on your side.
- **Retry ladder: 3 attempts total**, driven by our job queue, with no delay between
  them. After the 3rd failed attempt the delivery is marked `failed`, we stop, and our
  on-call is alerted that your integration is broken.
  *Status: the 3-attempt budget is the contract, but our queue does not yet re-run a
  failed delivery — today a delivery that fails is marked `failed` on its FIRST attempt.
  Design for at-least-once and idempotent receipt either way (dedupe on the envelope's
  `id`, §1.2): when the ladder is switched on, retries will arrive.*
- **One forensic row per delivery** (not per attempt): retries update the same row's
  attempt count and status. `GET /v1/integrations/deliveries` shows the last 50 (up to
  `?limit=200`) with `status` (`delivered` / `failed` / `skipped`), `attempts`,
  `first_at`, `last_at` — so "did it reach my CRM?" needs no support ticket.
- An event queued for an endpoint you deactivated before it was sent is recorded as
  `skipped`, not retried.

### 1.6 Managing endpoints and rotating a secret

- `POST /v1/integrations/endpoints` with `{"url": "https://…", "events": ["lead.created"]}`
  registers an endpoint (http(s) URLs only, at least one event) and returns the signing
  secret **exactly once**, in that response. Store it in your secrets manager
  immediately — no later API call ever returns it again.
- `GET /v1/integrations/endpoints` shows each endpoint with a `secret_fingerprint`
  (first 8 hex characters of the secret's SHA-256) so you can confirm *which* secret
  you hold without anyone re-displaying it.
- `DELETE /v1/integrations/endpoints/{id}` **deactivates** the endpoint — it is kept,
  not deleted, so its delivery history stays readable.

**To rotate a secret:** create a new endpoint with the same URL, deploy the new secret
to your receiver (accept both during the cutover), then deactivate the old endpoint.
There is no in-place rotation, by design — a secret is born with its endpoint and shown
once.

---

## 2. Sending leads to us

### 2.1 The ingest endpoint

```
POST https://api.calevate.tech/hooks/v1/ingest/{webhook_id}
X-Ingest-Secret: <your lead-source secret>
Content-Type: application/json

{"full_name": "Ravi Kumar", "phone_number": "9876543210", "may_call": "yes"}
```

- `{webhook_id}` is the UUID we issue when your lead source is created.
- Authentication is the **`X-Ingest-Secret` header**, compared in constant time. No
  session, no OAuth — this endpoint is for machines.
- The body must be a **JSON object**. Non-JSON bodies are rejected with 422
  (`ingest_not_json`). Form-encoded bodies are not accepted.

On success you get **202 Accepted**:

```json
{"status": "accepted", "lead_id": "0198…", "dispatched": true}
```

`dispatched: false` plus a `"blocked"` field means the lead was **saved but not
called** — see consent and compliance below.

### 2.2 Field mapping

Each lead source carries a mapping from your field names to ours, e.g.
`{"phone": "phone_number", "name": "full_name"}` (ours → yours). When a mapping is
configured, **only mapped fields survive** into the lead; unmapped keys are dropped —
unknown data from an external party does not land in a lead row. With no mapping, your
payload is taken as-is and we look for `phone` / `phone_number` and `name`.

The phone is normalized to E.164. Bare 10-digit Indian mobiles (starting 6–9) get
`+91`; anything we cannot confidently normalize is rejected with 422
(`ingest_no_phone`) rather than dialled on a guess.

### 2.3 Consent (`consent_field`)

If your lead source names a `consent_field` (e.g. `may_call`), the payload must affirm
it: the value, trimmed and lowercased, must be one of `true`, `yes`, `1`, `on`.
Anything else — including the field being absent — means **the lead is saved but the
call is refused**, and the response says so:

```json
{"status": "accepted", "lead_id": "0198…", "dispatched": false, "blocked": "no_form_consent"}
```

This is deliberate: your form asserting permission to call is a compliance fact we
record, not one we assume.

### 2.4 Retries and duplicates

Form vendors and Zapier retry on timeouts. We deduplicate on a hash of the JSON body
(key order does not matter) per lead source: an identical retried submission returns
`{"status": "duplicate"}` with 202, and the customer's phone rings **once**. A payload
that differs in any field value is a new submission.

### 2.5 Error responses

Errors are RFC-9457 `application/problem+json`. A wrong or missing `X-Ingest-Secret`:

```json
{
  "type": "https://calevate.tech/problems/unauthorized",
  "title": "Unauthorized",
  "status": 401,
  "detail": "This lead source rejected the credentials.",
  "kind": "auth",
  "retryable": false,
  "instance": "/hooks/v1/ingest/0198c2b1-77aa-7b90-8d13-402f9e6c1b55",
  "trace_id": "8f3a1c…"
}
```

- **401** `unauthorized` — bad or missing `X-Ingest-Secret`.
- **404** `not_found` — unknown **or deactivated** webhook id (deliberately
  indistinguishable to a probing sender).
- **422** `ingest_not_json` (body is not JSON), `ingest_no_phone` (no dialable number;
  includes a `fields` array naming `phone`), `ingest_no_agent` (source not yet attached
  to an agent — fix in the console).

`retryable` tells you whether retrying can possibly help; for all of the above it is
`false` — fix the request instead.

### 2.6 Dry-run tester

```
POST /v1/lead-sources/{webhook_id}/test
{"payload": {"full_name": "Test", "phone_number": "9876543210", "may_call": "yes"}}
```

This runs your sample through the **real** decision chain — field mapping, phone
normalization, consent check, and the live compliance/DNC gate — and reports each step,
**without writing a lead, claiming a dedupe slot, or placing a call**:

```json
{"would_call": true, "steps": [{"step": "field_mapping", "ok": true, "…": "…"}]}
```

It requires a signed-in user with org-manage rights (it lives on the dashboard API, not
the machine surface). `GET /v1/lead-sources/activity` shows every real inbound delivery
as accepted / deduplicated / rejected, with per-source duplicate counts.
