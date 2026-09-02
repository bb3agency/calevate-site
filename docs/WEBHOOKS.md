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
| `lead.updated`       | A lead's status, name or owner actually changes — one event per lead per edit, and nothing at all for a re-save that moved no field. In the same transaction as the edit. | Live |
| `campaign.completed` | An outbound campaign has nothing left to dial and reaches its terminal `completed` status — in the same transaction as that status write. A campaign that REPEATS does not fire this at the end of each run: it is not finished, it is waiting for its next occurrence. | Live |

All four fire. `GET /v1/integrations/events` returns the list you may subscribe to.

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
- **`created_at` is when the event happened, not when we posted it.** UTC, ISO-8601, and
  identical on every retry of the same `id`. Order by it if your system applies
  last-write-wins to a lead: deliveries can arrive out of order — a retried event is
  posted minutes after the edit that caused it, and an unrelated later edit may reach you
  first — and this is the field that tells you which one is newer.

A `lead.updated` envelope carries the same `data` keys as `lead.created`, with the values
as they stand AFTER the edit.

A `call.completed` envelope carries in `data`: `call_id`, `lead_id` (may be null),
`direction`, `duration_s`, `outcome`, `sentiment`, `summary`. By default the summary —
never the transcript — is what leaves on a webhook. Three **per-endpoint opt-ins** add
more, and only to the endpoint that asked (§1.7):

- `recording_url` — present only if the endpoint opted into `include_recording_url` **and**
  a recording exists. A **signed, short-lived link** to our copy of the audio (never the
  audio bytes). It expires within minutes — fetch it as soon as you receive the delivery,
  and do not store the URL. If the call has no recording (never made, erased, or aged out
  under retention), the field is **omitted**, not sent as `null`.
- `transcript` — present only if the endpoint opted into `include_transcript`. The
  **redacted** transcript: a JSON array of turns, each `{ "speaker", "text", "lang",
  "start_ms" }`, in call order, with personal details (numbers, IDs, OTPs) masked — the
  same text a dashboard reader with `calls:read` sees.
- `raw_transcript` — present only if the endpoint opted into `include_raw_transcript`. The
  **unredacted** transcript, same array shape as `transcript`. This is your customer's
  personal data in the clear, so it is gated harder — see §1.7.

A `campaign.completed` envelope carries in `data`: `campaign_id`, `name` (the campaign's,
not a person's), `contacts_total`, `contacts_reached` and `completed_at`. **It is the one
event that carries no personal data at all** — aggregates only, no per-contact roster —
which is also why it is the one event whose delivered body we do not retain a copy of:
there is no data subject in it for a deletion request to find. `contacts_reached` counts
the contacts a call actually connected to, not the contacts dialled.

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

- **Only a 2xx response counts as delivered.** **Redirects are not followed**: we will
  not chase a signed body to a host you did not register, so a 3xx is a failure.
- **Timeout is 10 seconds** per attempt. Respond fast and process async on your side.
- **Retry ladder: 3 attempts total**, driven by our job queue, waiting **30 seconds then
  2 minutes**. After the 3rd failed attempt the delivery is marked `failed`, we stop, and
  our on-call is alerted that your integration is broken.
- **Not every failure is retried, and that is deliberate.** A timeout, a connection or
  TLS failure, a 5xx, a 408, a 425 or a 429 gets the full ladder. **Any other 4xx stops
  immediately** and is recorded as rejected with your status code: a 401, 404 or 422 is
  your endpoint telling us the request itself is wrong, and repeating it three times
  would only delay that verdict and treble the load on a host that is already unhappy.
  If you want a delivery retried, do not answer 4xx — answer 429 or 503.
- Design for **at-least-once**: dedupe on the envelope's `id` (§1.2), which stays the
  same across retries.
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
  immediately — no later API call ever returns it again. The body also accepts the three
  `call.completed` opt-ins (§1.7), all defaulting to `false`:
  `include_recording_url`, `include_transcript`, `include_raw_transcript`. The response and
  `GET /v1/integrations/endpoints` echo all three so you can confirm what an endpoint is
  set to receive.

**Where an endpoint may live.** Your URL must resolve to an address on the public
internet and listen on port **80 or 443**. We resolve the hostname and refuse anything
that answers with a loopback, link-local, private (RFC 1918 / RFC 4193), multicast,
reserved or otherwise non-routable address, with `422 webhook_url_not_public` naming
which it was; a port other than 80 or 443 is `422 webhook_url_port_not_allowed`, and a
hostname we cannot resolve is `422 webhook_url_unresolvable`. A URL whose destination is
not the same under two standards-compliant readings of it — in practice a non-ASCII
domain name, where IDNA 2003 and IDNA 2008 disagree about what it spells — is
`422 webhook_url_ambiguous`; send the punycode (`xn--…`) form of the host instead, which
is unambiguous. If your receiver runs
inside your own network, publish it through the reverse proxy or load balancer you
already use — we cannot deliver to an address only you can reach, and a delivery
attempted into a private range is an attack against our infrastructure whoever asked
for it.

**The check is repeated at delivery, not only at registration**, so an endpoint that
was public when you registered it and later resolves to a private address stops
receiving leads: the attempt is recorded `failed` on your delivery screen with the same
reason code and is **not** retried, because the next attempt would resolve identically.
Redirects are never followed (§1.5), so moving an endpoint means registering the new
URL, not returning a `3xx` from the old one.
- `GET /v1/integrations/endpoints` shows each endpoint with a `secret_fingerprint`
  (first 8 hex characters of the secret's SHA-256) so you can confirm *which* secret
  you hold without anyone re-displaying it.
- `DELETE /v1/integrations/endpoints/{id}` **deactivates** the endpoint — it is kept,
  not deleted, so its delivery history stays readable. It is idempotent (RFC 9110
  §9.2.2): deactivating an already-inactive endpoint is `204`, so a retry after a lost
  response is safe. `404` means only that no endpoint of yours has that id.

**To rotate a secret:** create a new endpoint with the same URL, deploy the new secret
to your receiver (accept both during the cutover), then deactivate the old endpoint.
There is no in-place rotation, by design — a secret is born with its endpoint and shown
once.

### 1.7 Getting the recording and transcript on `call.completed`

By default a `call.completed` webhook carries the summary and the outcome, not the
transcript and not the recording — the transcript is the most sensitive thing we hold. If
your system needs more, you opt in **per endpoint**, at registration, with three booleans
on `POST /v1/integrations/endpoints` (all default `false`):

| Field                    | Adds to `call.completed.data`                | Gate |
| ------------------------ | -------------------------------------------- | ---- |
| `include_recording_url`  | `recording_url` — a signed, short-TTL link to our copy of the audio, omitted when there is no recording | `org:manage` |
| `include_transcript`     | `transcript` — the REDACTED transcript, as an array of turns | `org:manage` |
| `include_raw_transcript` | `raw_transcript` — the UNREDACTED transcript, same array shape | `org:manage` **and** `calls:read_raw` |

Three rules govern them:

- **The recording link is short-lived and is not the audio.** It points at our own copy
  and expires within minutes. Fetch it as soon as the delivery arrives; do not store the
  URL. It is omitted entirely for a call that has no recording.
- **`include_raw_transcript` is a SECOND opt-in on top of `include_transcript`**, not a
  standalone one — the request is refused (`raw_transcript_requires_transcript`) if you
  ask for raw without redacted. The unredacted transcript contains every phone number, ID
  and OTP spoken on the call, in the clear, so it also requires the same permission as
  reading a raw transcript in the dashboard (`calls:read_raw`); a caller without it is
  refused. And **every delivery that carries a raw transcript is written to your audit
  log** — the same control that governs reading a raw transcript or a delivered payload on
  screen (hard rule 5).
- **These do not change the retained delivery body or its gating.** As with any delivery,
  we keep a copy of what we sent (§1.5 / the payload view), still behind `calls:read_raw`
  and still audited on read. Opting in widens what your endpoint receives, not who may
  read the forensic copy.

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

### 2.6 Meta Lead Ads (native)

A lead source whose `source` is `meta_lead_ads` gets a second endpoint, spoken in
Meta's own protocol rather than ours:

```
GET|POST https://api.calevate.tech/hooks/v1/ingest/meta/{webhook_id}
```

- `POST /v1/lead-sources/{webhook_id}/meta/setup` (org-manage) returns the **callback path**,
  the **`hub.verify_token`** to paste into the Meta App Dashboard, and the field to
  subscribe the Page to (`leadgen`). The verify token is *derived* from the endpoint's
  app secret, so it is per-endpoint and rotates with the secret; we never store a
  second one.
- **Subscription handshake**: Meta GETs the URL with `hub.mode=subscribe`,
  `hub.verify_token` and `hub.challenge`. We echo the challenge as `text/plain` with
  200 when both match, and answer **403** otherwise. Nothing is written either way.
- **Authenticity**: every POST must carry `X-Hub-Signature-256: sha256=<hex>` — the
  HMAC-SHA256 of the **raw body bytes**, keyed with your **Meta App Secret** (which is
  what `secret_ref` holds for this source; it is *not* the verify token and *not* a
  Page access token). Verified before the body is parsed, compared in constant time.
  A missing or wrong signature is **401** and writes nothing at all.
- **Duplicates and order**: Meta retries with backoff for hours and guarantees no
  ordering, so we deduplicate on the **`leadgen_id`** — one lead, one unit of work —
  not on the delivery body. A re-batched retry is still a duplicate; a genuinely new
  lead sharing the delivery is still processed.
- **Consent**: a lead-ad fill is not permission to be telephoned. Unless the source's
  mapping names a `consent_field` that the form's own answers affirm, the lead is
  saved and the call is refused (`no_consent_field_configured` / `no_form_consent`).

**What is not built, and will not be pretended:** the webhook is a change notification
and carries no answers. Fetching them is `GET /{leadgen_id}?fields=field_data` with a
Page access token holding `leads_retrieval`, and this deployment has no Meta app
credentials. So a verified delivery is acknowledged (200 — a permanent refusal must not
make Meta retry for 36 hours and then unsubscribe your Page), recorded against its
`leadgen_id` with the reason `meta_lead_retrieval_unavailable` (or
`meta_page_token_not_configured` where an adapter exists and your source has no token
yet), and shown in `GET /v1/lead-sources/activity` as **rejected** with
`recoverable: true`.

**It is not lost, and it stays recoverable after Meta gives up.** Meta redelivers for
about 36 hours and then unsubscribes the Page; while it is still redelivering, attaching
the credential is enough — the recorded refusal is re-claimable and the next redelivery
lands the lead. After that window, `POST /v1/lead-sources/{webhook_id}/meta/redrive`
(`org:manage`, audited) re-runs those recorded refusals for that source through the same
path a live delivery takes, compliance gate included. It answers counts:
`candidates`, `accepted`, `duplicate`, `refused`, `deferred` — where `deferred` means we
could not reach Meta just now and those leads are still waiting, so press it again.

### 2.7 Dry-run tester

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
