# Runbook — a client wants to pay, or a payment did not land

Symptom: a self-serve client says they cannot top up; a payment was taken and the wallet
did not move; the alerts `razorpay_webhook_unconfigured`, `razorpay_webhook_bad_signature`
or `razorpay_unknown_tenant` fire; or someone asks "can client #1 pay by card today?"

Read this section before anything else, because it changes what you are allowed to
promise.

**The order-creation adapter now exists; the credential does not** (D-98).
`PROVIDER_CREATES_ORDERS` is `True` in `apps/api/billing/payments.py` — a greppable
constant, and it moved because somebody wrote `RazorpayOrders.create_order`, a real
`POST /v1/orders`. That is a claim about CODE. **The claim about THIS DEPLOYMENT is
`payment_capability().creates_orders`, and it is `False` everywhere**, reason
`no_api_secret`: no Razorpay account has been provisioned and `RAZORPAY_KEY_SECRET` is
unset. So `POST /v1/billing/topups/intent` still returns `provider_order_id: null` and
`provider_order_pending: true` on every deployment today.

Do not conflate the two. "We have an adapter" and "this box can take a payment" are
different sentences, and §1's table now has a row for each.

**The vendor half of the integration is PART VERIFIED, PART NOT**, and the difference is
marked at the line in the code on a three-rung ladder (READ AT SOURCE / REPORTED, NOT
READ / UNVERIFIED — the same ladder `apps/api/engine/cartesia.py` uses).

`razorpay.com` is refused by this environment's egress proxy, so **nobody here has read
their documentation pages.** What was read is `github.com/razorpay/razorpay-python`,
Razorpay's own published client, on `master`, 2026-08-14. From it, READ AT SOURCE:

- the host and the version path — `BASE_URL = 'https://api.razorpay.com'`, `V1 = '/v1'`
  (and `V2` exists, which is why we pin), `ORDER_URL = "/orders"`;
- HTTP Basic auth with `(key_id, key_secret)`, `Content-Type: application/json`;
- the create body keys `amount` / `currency` / `receipt` / `notes`;
- **the webhook signing scheme** — `verify_signature` is HMAC-SHA256 of the raw body,
  hex-encoded, compared with `hmac.compare_digest`. This used to be marked UNVERIFIED.
  It is now their own code, and ours matches it.

Still NOT verified, and each fails loudly rather than quietly:

- the **header name** `X-Razorpay-Signature` — their SDK is handed the signature and
  never names where it came from. Wrong header ⇒ every event refused;
- `extract_captured_payment`'s payload paths — `event`, and
  `payload.payment.entity.{id, amount, currency, notes}` with `amount` an integer count
  of paise. Webhook payloads are not in their Python SDK;
- the **order RESPONSE** shape — that the order id comes back as `id`. Wrong ⇒
  `payment_order_unreadable`, never a fabricated id;
- whether an account rejects a duplicate `receipt`. It is a dashboard setting we do not
  rely on: our idempotency is ours (§2a).

**So the first real payment is still a test, not a routine.** Nothing here has ever been
exercised against a live account, in either direction. Plan it as an attended event, on
a Razorpay TEST account first. What to watch, in order:

1. **The order call.** `topup_order_created` in the API log carries the `order_id`. If
   instead you see `razorpay_order_rejected` with a status, the request shape or the
   credentials are wrong — the status is in the log line and the vendor's message
   deliberately is not. `razorpay_order_amount_mismatch` means they priced it differently
   from us and we stopped; treat that as a paise bug in our conversion until proven
   otherwise and do not retry it.
2. **The amount, in paise, against the dashboard.** ₹2,500.10 must appear as `250010`.
   This is the number to check by eye on the first payment and never again.
3. **The signature.** A first live `razorpay_webhook_bad_signature` is more likely to be
   the header name than an attack (§4).
4. **`notes.calevate_tenant_id` on the payment in their dashboard.** We now put it into
   the order server-side, so if it is absent the order call is not doing what this
   runbook says it does — and every payment would land on `payment_tenant_unresolved`.
5. **One ledger row, and one only** (§5). Then click "add credit" twice quickly and
   confirm the dashboard shows ONE order (§2a).

If the scheme is wrong the failure is fail-closed — every event is refused and nothing is
credited — which is the safe direction to be wrong in, and it is also the direction that
looks like "the client paid and nothing happened".

---

## 1. What can this deployment actually do?

One selector answers it, and every payment surface asks that one selector —
`payment_capability()` (`apps/api/billing/payments.py`). Nothing re-reads settings, so a
screen cannot offer what the route will refuse.

```
PaymentCapability(available, provider, reason, creates_orders, orders_reason)
```

`reason` is non-None exactly when `available` is False, and it is an authored code
naming OUR configuration state — never a vendor error string. It is logged
(`payments_unavailable`) and never returned to the client: a client cannot act on
"no_webhook_secret", and telling them which of our secrets is missing is an internals
leak. What they see is one RFC-9457 problem, `payments_not_configured`, with the
remediation "Contact us to pay by bank transfer instead."

| `reason` | Meaning | What to do |
|---|---|---|
| `no_payment_provider` | `PAYMENT_PROVIDER` unset. **This is the default and the truth today** | Nothing is broken. Route the client to the manual path (§3) |
| `provider_not_implemented:<name>` | `PAYMENT_PROVIDER` names something other than `razorpay` | There is one implemented provider. A name with no adapter fails loudly on purpose |
| `no_publishable_key` | `PAYMENT_PROVIDER=razorpay` but `RAZORPAY_KEY_ID` unset | Complete the credentials — both of them |
| `no_webhook_secret` | Key id set, `RAZORPAY_WEBHOOK_SECRET` unset | **The worst of the three states**: this deployment could take money and could never credit it. It is refused at the intent AND at the receiver, which is the point of one selector |

`creates_orders` rides on the same object rather than being a separate lookup, so no
caller can conclude "payments work" and then assume "so an order exists". It has its own
reason, and there is exactly one:

| `orders_reason` | Meaning | What to do |
|---|---|---|
| `no_api_secret` | `RAZORPAY_KEY_SECRET` unset. **This is the state of every deployment today** | Nothing is broken. The intent still prices the top-up and mints a reference; route the client to the manual path (§3) |

**`no_api_secret` must never pull `available` down, and it does not.** A deployment
holding the webhook secret but not the API secret is perfectly coherent — it credits
payments taken somewhere else — so the receiver still works. Two questions, two answers,
one object.

### The client screen asks this too

`GET /v1/billing/topups/capability` (client realm, `billing:read`) publishes exactly two
booleans, `online_payments_available` and `provider_orders_available`. **No reason code is
published** — a client cannot act on `no_webhook_secret` and naming our missing secret is
an internals leak. The reasons are logged (`payments_unavailable`,
`topup_capability_unavailable`, `topup_orders_unavailable`) where you can reach them.

It is a RENDERING HINT and never the check: the intent route asks the same selector
server-side and remains the authority, so a stale `true` costs a refusal after the click
and can never cost a payment. It exists because without it the top-up form was offered on
every deployment and refused on every deployment.

## 2. The intent route, and its own refusals

`POST /v1/billing/topups/intent`, client realm, `org:manage`
(`apps/api/billing/payment_routes.py`). `org:manage` and not a read, and it is in
`MUTATING_PERMISSIONS`, so an impersonating admin (D-22) cannot start a payment on a
client's behalf.

The tenant comes from the verified session, never from the body.

| code | Meaning |
|---|---|
| `topup_amount_out_of_range` | Outside ₹100 – ₹100,000 (`MIN_TOPUP_INR` / `MAX_TOPUP_INR`) |
| `payments_not_configured` | §1. Writes NOTHING — no receipt is minted, no row is touched |
| `topup_not_available` | The tenant's `plan_tier` is not `self_serve` or `trial`. A managed client is invoiced against their retainer; letting them top up would be charging twice |
| `topup_amount_unrepresentable` | The amount is finer than a paisa, non-positive, or arrived as a float. **Refused, never rounded** — `inr_to_paise` |
| `payment_provider_unreachable` | Razorpay did not answer within 8s. Nothing was created; the client is told to retry or transfer |
| `payment_provider_rejected` | Razorpay refused the order. The HTTP status is in `razorpay_order_rejected`; their message is deliberately not forwarded |
| `payment_order_unreadable` | 200 with no readable order `id`. **On a first live payment this is the response-shape guess being wrong**, and refusing beats fabricating an id a checkout would reject |
| `payment_order_amount_mismatch` | They echoed a different `amount` from the paise we sent. A money fact — stop and reconcile before retrying |
| `idempotent_request_in_flight` | A concurrent identical request is still creating the order. 409 with `Retry-After: 3` (§2a) |

A successful response is not a payment. It is a priced, tenant-bound receipt plus
`notes: {"calevate_tenant_id": "<uuid>"}` — and those notes are not decoration. The
webhook resolves the tenant from exactly that key and from nothing else. **Since D-98 the
notes go INTO the order server-side**, not merely into the response, so a checkout that
forgets to attach them can no longer strand a payment on `payment_tenant_unresolved`.

Money crosses the wire as a string (`"2500.00"`), never as a JSON float. A float is
refused at the boundary, not rounded (hard rule 7). It reaches Razorpay as an **integer
count of paise** — ₹2,500.10 is `250010` — through `payments.inr_to_paise`, which is the
only conversion in that direction and refuses anything finer than a paisa rather than
rounding it.

### 2a. Clicking twice

**One order per (tenant, amount) per fifteen minutes.** The key is derived server-side by
`payments.topup_receipt` — content-addressed over the tenant, the quantized amount and a
time bucket — and claimed through `reliability.claim_idempotency`. It is also the
`receipt` we send Razorpay and the reference the client quotes on a bank transfer: one
string, because they are one fact.

Two consequences an operator will meet:

- **A client who genuinely wants to pay the same amount twice inside fifteen minutes gets
  the first order back.** That is the stated cost of the window. Tell them to pay the one
  they have, or ask for the combined amount. It is not a bug and there is nothing to
  clear.
- **A crashed attempt is retaken by the client's own next click**, because a failure marks
  the claim `failed` rather than leaving it `processing`. If a click is answered
  `idempotent_request_in_flight`, an identical request really is running; retry in a few
  seconds. Past `CLAIM_LEASE` (10 min) it is retaken automatically.

We do NOT rely on Razorpay's own receipt-uniqueness setting for any of this. It is a
dashboard toggle, which is not an idempotency guarantee.

## 3. What to tell a client who wants to top up TODAY

The honest answer, in this order:

1. Online payment is not available on this deployment (§1 will tell you which reason).
   A checkout widget now EXISTS (D-470) and opens whenever the intent comes back with a
   real `provider_order_id`. What is missing on our boxes is the API secret, so
   `creates_orders` is False, `provider_order_id` is null, and no window can open — the
   client screen says so and hands over the order id as a reference rather than implying a
   payment is in progress. "A widget exists" and "this box can take a payment" stay
   different sentences (D-98); only the first one changed.
2. The path that works is a bank transfer — NEFT or UPI — recorded by us against their
   wallet from the UTR the bank printed. Record it on the **admin credits screen**,
   `/admin/tenants/<tenantId>/credits` (D-82); it calls the same route that has always
   existed for this (`POST /v1/admin/tenants/{tenant_id}/credits`, admin realm,
   `admin:tenants`, `apps/api/billing/credit_routes.py`). Hand-constructing that call is
   no longer the procedure — the screen exists, and it double-keys the reference.
   It is idempotent by the payment reference: the same UTR twice returns the existing
   entry and credits nothing; the same UTR with a different amount is a conflict, not a
   second payment.
   **If you recorded the wrong amount or the wrong client**, do not ask anyone to edit the
   row — the ledger is append-only. Two controls on the same screen, and which one you
   want depends on the DIRECTION:

   | What went wrong | Control | Route |
   |---|---|---|
   | We credited TOO MUCH — wrong client, or more than arrived | "Correct a wrong entry" | `POST .../credits/adjustments` (D-87) |
   | We credited TOO LITTLE — ₹5,000 typed for a ₹50,000 UTR | "A payment was for more than we recorded" | `POST .../credits/restatements` (D-89) |

   - **The adjustment** appends a compensating entry naming the entry it corrects, and can
     never take back more than that entry put in. Taking credit away asks for a typed
     confirmation; putting it back does not. The balance MAY go negative if the wrong
     credit was already partly spent, and the screen will tell you when that has stopped
     the client's outbound dialling.
   - **The restatement** credits the difference against the SAME reference, so the wallet
     still shows one bank transfer. **You type the TOTAL the bank moved, never the
     difference** — the amount to credit is worked out on the server, from the figure the
     reference credits today (which the screen shows you beside the field). Every
     restatement needs the confirmation header, and it carries the amount, so one captured
     for ₹50,000 cannot be sent with a request for ₹500,000. Doing it twice credits once;
     restating again to a HIGHER total credits only the new difference.

   Re-recording a reference for a different amount is a `topup_reference_conflict` (409)
   either way, and that refusal is doing its job — it is the only thing stopping one bank
   transfer being credited twice. Its remediation names whichever of the two routes matches
   the direction you are out by.
3. Give them a realistic turnaround, because the recording is a human action, not a
   callback.

Do not promise a card payment "once we switch it on". Switching it on now means: a
provisioned Razorpay account with `RAZORPAY_KEY_SECRET` in the secrets manager, a
checkout on the client screen (deliberately not built — see below), and the first live
payment run as an attended test. The adapter is written; the account, the checkout and
the verification are not.

**The checkout is a decision, not an omission.** Razorpay's `checkout.js` is a third
unverified vendor surface and a supply-chain decision (hard rule 9), and it would not be
the source of truth in any case: the wallet is credited by the signed webhook, never by
the browser's callback. When it is built, the gate to insist on is that the browser's
success callback changes NOTHING on the ledger.

## 4. The receiver, when a payment HAS been taken

`POST /hooks/v1/razorpay`. Under `/hooks` because it shares the webhook doctrine with
the other machine callbacks: never load-shed (`/hooks` is in `ALWAYS_ALLOWED_PREFIXES`
— a payment landing during degraded mode is still a payment), authenticated by a
signature rather than a session, inbox-deduped, idempotent on the provider's own
payment id.

Signature first, money last. Nothing is read out of the payload until the HMAC verifies
and nothing durable is written until the tenant resolves, so a forged or malformed event
leaves no row at all — not even an inbox trace it could later be replayed from.

Work the failure by which alert fired:

- **`razorpay_webhook_unconfigured`** — capability check failed at the receiver. §1.
  Fail-closed on purpose: an unverifiable payment feed credits wallets on anyone's
  say-so.
- **`razorpay_webhook_bad_signature`** → 401. Treat as an attack until proven config
  drift, exactly as the webhook-signature runbook in OPERATIONS §7 says. Then consider
  the second possibility, which for a first live payment is the likely one: **our reading
  of the signing scheme is wrong.** The comparison is `hmac.compare_digest` over the
  bytes as received — re-serializing parsed JSON would compare against something the
  sender never signed. If the scheme turns out to differ, that is a one-function change
  in `verify_signature` and the fix ships with a fixture captured from the real
  delivery.
- **`razorpay_unknown_tenant`** → 404. Real money we cannot attribute. A 404 rather than
  a silent ack is what gets it into someone's hands instead of nobody's wallet. The
  tenant came from `notes.calevate_tenant_id`; if the checkout was built without that
  key, every payment lands here.

Refusals that are not alerts but stop the credit, all from
`extract_captured_payment` / `paise_to_inr`, and all of which credit nothing:

| code | Meaning |
|---|---|
| `payment_payload_unrecognized` | The envelope did not match the shape we can read, or carried no payment id. **On a first live payment this is the field-path guess being wrong**, not a broken payment |
| `payment_currency_unsupported` | Not INR. Refused rather than converted — an fx rate applied at credit time is a number nobody can reproduce |
| `payment_amount_unrecognized` | The amount was not a positive integer number of paise. A JSON float is refused even when it looks whole |
| `payment_tenant_unresolved` | `notes` did not carry `calevate_tenant_id` |
| `payment_amount_conflict` | One payment id already on the wallet **for a different amount**. Absorbing this as a replay would swallow the difference silently; refusing is how anyone finds out. Reconcile against the provider |

An event that is not `payment.captured` is ACKed and ignored (`status: "ignored"`), which
stops the provider retrying. Authorized-but-not-captured is not money we hold, and a
refund is a compensating entry someone decides on, not one we infer from a callback.

## 5. "The payment went through and the wallet did not move"

Answer it from the ledger, which is the only permanent record — the inbox is per delivery
and can be swept.

```sql
-- Tenant-scoped session. Ids and amounts; no PII on this path at all.
SELECT id, delta, reason, ref, balance_after, occurred_at
FROM credit_ledger
WHERE reason = 'topup'
ORDER BY occurred_at DESC
LIMIT 20;
```

`ref` is the provider's payment id for an online top-up and the bank's UTR for a manual
one. `meta` carries `{"source": "razorpay", ...}` for the former.

**A payment may be more than one row.** A restated payment (D-89) has a second `topup`
row whose `ref` is `restated:<payment_ref>:<corrected total>` and whose
`meta.payment_ref` names the transfer. "What has this reference credited" is therefore a
SUM, and this is the one expression that answers it — the same one
`billing.service.PAYMENT_REF_SQL` uses, so an answer got here and an answer got from the
console cannot differ:

```sql
-- Tenant-scoped session. One line per bank transfer, comparable to a statement.
SELECT COALESCE(meta->>'payment_ref', ref) AS payment_ref,
       SUM(delta) AS credited_inr, count(*) AS rows, MIN(occurred_at) AS first_at
FROM credit_ledger
WHERE reason = 'topup'
GROUP BY 1
ORDER BY first_at DESC
LIMIT 20;
```

The same view is on the credits screen ("Payments — one line per bank transfer"), so
this query is for a session where the console is not available. Note it does NOT subtract
adjustments: it answers what we credited against the reference, which is the question a
bank statement asks. The BALANCE is `balance_after` on the newest row, as always.

```sql
-- Did the delivery arrive at all?
-- `status` is one of processing / enqueued / processed / failed; UNIQUE (provider, event_key).
SELECT event_key, event_name, status, last_error, created_at, processed_at
FROM webhook_inbox_events
WHERE provider = 'razorpay'
ORDER BY created_at DESC
LIMIT 20;
```

- **Ledger row present, client says the balance is wrong** — read `balance_after` on the
  newest row rather than adding deltas by eye, and check whether a `usage` debit landed
  between the two screenshots.
- **Inbox row present, no ledger row** — the credit path raised after the claim. The
  claim and the credit share one transaction, so a crash rolls the claim back too and the
  provider's retry is processed rather than answered "duplicate" forever. If the inbox
  row survives with no ledger row, something committed the claim without the credit;
  capture both rows before touching anything and escalate.
- **Neither** — the event never arrived or never verified. §4.

## What NOT to do

- **Never UPDATE or DELETE a `credit_ledger` row** (hard rule 4 — and a database trigger
  enforces it). A wrong credit is corrected by appending one compensating entry with
  `reason = 'adjustment'`; `scripts/reconcile_credit_ledger.py` is the tool that does it
  idempotently, under the per-tenant credit lock, and `--apply` is the only flag that
  writes.
- **Never record a shortfall under an ANNOTATED reference** — `UTR-123-part2`,
  `UTR-123 (balance)`, `UTR-123/2`. This was the documented workaround until D-89 and it
  was the wrong answer: the ledger then carries two payment references for one bank
  transfer, so the reference stops being usable as the thing reconciliation keys on, and
  nothing afterwards can tell the pair apart from two genuine payments that happened to
  look alike. Restate the payment instead (§3) — it credits the difference against the
  reference the bank actually printed.
- **Never type the DIFFERENCE into a restatement.** The field is the total the bank moved.
  A difference is a well-formed rupee amount and no validator can tell it from a correct
  total, so the guards are the figure shown beside the field, the double keying, and the
  confirmation header that carries the number. If you send one by mistake the ledger keeps
  the entry: take the excess back with an adjustment against it, which is bounded by what
  that entry put in.
- **Never hand-INSERT a ledger row.** `record_entry` owns the balance arithmetic, the
  ordering and the advisory lock; a second writer is how the duplicate residue this
  system already carries got there.
- **Never credit a payment "manually to unblock the client" while a signature failure is
  unexplained.** The signature is the only thing standing between our wallets and
  anyone's say-so.
- **Never flip `PROVIDER_CREATES_ORDERS` to make a frontend happy**, in either direction.
  `tests/payments_provider_seam_test.py` fails the moment it claims an adapter this
  module does not contain, and that tripwire is the point of the constant. The knob for
  "this deployment cannot create orders" is the absence of `RAZORPAY_KEY_SECRET`, not the
  constant.
- **Never set `RAZORPAY_KEY_SECRET` to "see if it works".** It is the private half of the
  key pair and setting it makes the intent route place real calls to Razorpay on a live
  account. Use a Razorpay TEST account, or leave it unset.
- **Never paste a webhook body, a signature header or the webhook secret** into a ticket.
