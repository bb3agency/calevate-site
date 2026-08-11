# Runbook — Client says events are not reaching their CRM

Symptom: "leads aren't showing up in our CRM" / "we stopped getting call webhooks".

The delivery path, in order (each stage has a table you can read):

```
domain write ──(same txn)── enqueue_event ── outbox_messages(pending)
      │                                            │
      │                          dispatch_outbox cron (every 10s)
      │                                            │
      │                              ARQ job deliver_outbound_webhook
      │                                            │
      └── the fact being reported          signed POST → client URL
                                                   │
                                     webhook_deliveries(direction='out')
```

`enqueue_event` (`apps/api/integrations/service.py`) fans out one outbox row PER active
subscribed endpoint, in the caller's transaction — so "lead created but CRM never heard"
requires a failure downstream, never a missing enqueue. Work downstream in order.

Ground rules: audited admin path for any production SQL
(SECURITY-COMPLIANCE.md §"Admin access path"); read-only; ids and counts only, never
payloads or phone numbers (hard rule 6 — `webhook_deliveries` deliberately stores NO
payload column for exactly this reason).

## 1. Is the endpoint configured and subscribed?

Config row: `outbound_webhooks` — must be `active = true`, `kind = 'webhook'`, and the
event must be in its `events` array (`enqueue_event` filters on
`:event = ANY(events)`). Valid events (`EVENT_TYPES`,
`apps/api/integrations/service.py`): `lead.created`, `lead.updated`, `call.completed`,
`campaign.completed`.

The client can check this themselves: `GET /v1/integrations/endpoints`
(`apps/api/integrations/routes.py`) shows url, events, active, and the secret
fingerprint (first 8 hex of SHA-256 — the secret itself is shown exactly once, at
creation, and never again).

```sql
SELECT id, active, events, created_at
FROM outbound_webhooks
WHERE tenant_id = :tenant_id AND kind = 'webhook';
```

- Not subscribed to the event → no outbox row was ever written. Client fix: register
  an endpoint with the right events.
- `active = false` → deliveries in flight when it was deactivated are recorded as
  `skipped` and the job returns `endpoint_inactive` (`apps/workers/outbound_webhooks.py`
  — deactivation is "the client changed their mind", not a failure). Deactivation is
  the client's own `DELETE /v1/integrations/endpoints/{id}` (soft — row kept so history
  stays readable).

## 2. Did the event get enqueued?

`lead.created` fires from lead ingest (`apps/api/ingest/service.py`); `call.completed`
fires from the post-call pipeline only when the call status is `completed`
(`apps/workers/pipeline.py`). If the underlying fact never happened (call not
`completed`, lead write rolled back), there is nothing to deliver — check the domain
row before blaming delivery.

## 3. Outbox: pending / published / failed

`outbox_messages` statuses (`apps/api/reliability/service.py`): `pending` (awaiting
dispatch), `published` (handed to ARQ), `failed` (the outbox DLQ — publish failed
`OUTBOX_MAX_ATTEMPTS = 5` times). The dispatcher (`dispatch_outbox`,
`apps/workers/dispatcher.py`) runs every 10 seconds (cron
`second={0, 10, 20, 30, 40, 50}`, `apps/workers/settings.py`).

```sql
SELECT status, count(*), min(created_at) AS oldest
FROM outbox_messages
WHERE job = 'deliver_outbound_webhook'
GROUP BY status;
```

- Growing `pending` backlog → the dispatcher or workers are down; check the
  `outbox_lag_seconds` metric (`apps/api/core/alerting.py`) and worker health first.
- `failed` rows → each one fired alert `OUTBOX_DISPATCH` / `outbox_dead_letter` with
  the message id, and DLQ depth is the `outbox_dlq_depth` metric. Inspect
  `last_error` on the row. Replay is NOT a hand edit: `POST /v1/ops/outbox/replay`
  (admin realm, `ops:manage`, `apps/api/ops/routes.py`) calls `replay_dead_letters`
  — flips up to 100 oldest `failed` rows back to `pending` with `attempt_count = 0`
  and writes an `ops.outbox_replay` audit entry.

## 4. ARQ delivery job and its retry ladder

`deliver_outbound_webhook` (`apps/workers/outbound_webhooks.py`) raises on failure —
raising is how it asks ARQ to retry. `MAX_ATTEMPTS` (= `WORKER_MAX_TRIES`, 3)
(`apps/api/integrations/service.py`); on the last allowed try the job stops, returns
`"exhausted after N"`, and fires alert `WORKER_DELIVERY` / `outbound_webhook_exhausted`
with the tenant id — that alert is the "client's integration is broken and someone has
to know" signal, so if you're reading this because of that alert, skip to steps 5–6.

Both ceilings read the SAME constant (`WORKER_MAX_TRIES` in
`apps/api/core/queue.py`) — they were briefly two numbers (worker said 5, ARQ said 3),
which meant a delivery could stop retrying without the exhausted alert ever firing.
Pinned by `test_the_last_allowed_try_knows_it_is_the_last`. If a `failed` row's
`attempts` has stopped climbing and no alert fired, that invariant has regressed —
check the test before anything else.

Retries reuse the same `delivery_id` (minted at enqueue time in `enqueue_event`, NOT in
the worker), so one delivery = one forensic row, and a receiver deduplicating on the
`X-Calevate-Delivery` header sees a retry as a retry.

## 5. Delivery forensics: webhook_deliveries

One row per delivery, upserted by delivery id (`record_delivery`,
`apps/api/integrations/service.py`). Statuses: `delivered`, `failed`, `skipped`
(endpoint gone/inactive). `source` carries the HTTP result as `http_<code>` (or `http`
when the request never got a response — timeout/DNS/TLS; the error TYPE is in the
worker log line `outbound_delivery_failed`).

The table is not tenant-RLS'd, so scope by the tenant's own endpoint ids — exactly how
`GET /v1/integrations/deliveries` does it (`apps/api/integrations/routes.py`):

```sql
SELECT d.id, d.event_type, d.status, d.attempts, d.source, d.first_at, d.last_at
FROM webhook_deliveries d
WHERE d.direction = 'out'
  AND d.endpoint_id IN (SELECT id FROM outbound_webhooks WHERE tenant_id = :tenant_id)
ORDER BY d.last_at DESC
LIMIT 50;
```

Example (no payloads exist in this table by design):

```
                  id                  |   event_type   | status  | attempts |  source
--------------------------------------+----------------+---------+----------+----------
 0198c2f2-7c1e-7d3a-9f00-3b6a1e9d2b41 | lead.created   | failed  |        3 | http_500
 0198c2f1-11aa-7e02-8c11-9d4f0a7b6c22 | call.completed | delivered |      1 | http_200
```

Read it:

- `delivered` everywhere but the client still sees nothing → THEIR side accepted with
  2xx and then dropped it (or a field mapping renamed things — `apply_mapping` drops
  mapped fields we didn't send rather than sending nulls). Move to step 6.
- `failed` with `http_4xx/5xx` → their endpoint is rejecting us. Step 6.
- `failed` with `source = http` → we never got a response: timeout
  (`DELIVERY_TIMEOUT_S = 10.0`), DNS, TLS. Their infra.
- `skipped` → endpoint was inactive at delivery time (step 1).

## 6. Client-side checks (what to tell them to verify)

All from `deliver` / `sign_payload` / `verify_signature` in
`apps/api/integrations/service.py`:

1. **Return 2xx.** Anything else is a failure we retry — INCLUDING 3xx: we send with
   `follow_redirects=False` and will not chase a redirect with a signed body. An
   endpoint behind an http→https redirect fails every delivery.
2. **Respond within 10 seconds** (`DELIVERY_TIMEOUT_S`). Ack fast, process async.
3. **Verify the signature correctly.** Header `X-Calevate-Signature`, format
   `t={timestamp},v1={hex}` — HMAC-SHA256 over the string `{timestamp}.{body}` with
   their endpoint secret. Tolerance is 5 minutes (`tolerance_s = 300` in
   `verify_signature` — shipped reference implementation). The two classic client bugs:
   verifying over the body alone (missing the `{timestamp}.` prefix), and a server
   clock skewed past 5 minutes rejecting every event as stale.
4. **Other headers**: `X-Calevate-Timestamp`, `X-Calevate-Event`,
   `X-Calevate-Delivery` (dedupe key — the envelope's `id` is the delivery id, not the
   object id), User-Agent `Calevate-Webhooks/1`.
5. **Phone is masked by default** in `lead.*` payloads (`lead_payload`) — a "the phone
   field looks redacted" complaint is the default working, not a bug. Raw phone is a
   per-endpoint opt-in recorded in the config row, changed by us on request.

## 7. Self-serve vs. needs us

Client can do alone (integrations screen, backed by `apps/api/integrations/routes.py`,
all `org:manage`):

- List endpoints + secret fingerprints (`GET /v1/integrations/endpoints`).
- Register a new endpoint — secret shown once (`POST /v1/integrations/endpoints`).
- Rotate a secret: create a new endpoint, point their CRM at it, deactivate the old.
- Deactivate an endpoint (`DELETE /v1/integrations/endpoints/{id}`).
- Read recent delivery attempts — status/attempts/timestamps
  (`GET /v1/integrations/deliveries`, up to 200).
- List subscribable events (`GET /v1/integrations/events`).

Needs us (admin realm / config row):

- Outbox DLQ inspection and replay (`POST /v1/ops/outbox/replay`, audited).
- Investigating `outbound_webhook_exhausted` / `outbox_dead_letter` alerts.
- Field mapping changes (`outbound_webhooks.mapping`) and the raw-phone opt-in
  (`include_raw_phone` — an auditable config choice, not a client toggle).
- Anything requiring `webhook_deliveries.source` or worker logs.

## What NOT to do

- Never hand-UPDATE `outbox_messages` to replay — the ops endpoint exists so a message
  delivered twice has an audit note saying who asked (`apps/api/ops/routes.py`).
- Never paste an endpoint secret, envelope body, or lead payload into a ticket or log —
  the secret is shown once by design, and payloads carry PII (hard rule 6).
- Never "test" by re-firing a domain event — that creates a real lead/call fact. Replay
  the outbox row instead.
