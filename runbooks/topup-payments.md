# Runbook — a client wants to pay, or a payment did not land

Symptom: a self-serve client says they cannot top up; a payment was taken and the wallet
did not move; the alerts `razorpay_webhook_unconfigured`, `razorpay_webhook_bad_signature`
or `razorpay_unknown_tenant` fire; or someone asks "can client #1 pay by card today?"

Read this section before anything else, because it changes what you are allowed to
promise.

**Server-side order creation is not implemented.** `PROVIDER_CREATES_ORDERS` is `False`
(`apps/api/billing/payments.py`) — a greppable constant, not a note in a doc, because
"we have credentials" and "we have an order-creation adapter" are different facts.
`POST /v1/billing/topups/intent` returns `provider_order_id: null` and
`provider_order_pending: true` and always will until someone writes the adapter.
Flipping the constant is not a config change.

**The vendor half of the integration is UNVERIFIED.** There are no Razorpay credentials
in this repository and no call has ever been made against their API. Two things are our
best reading of their contract and are marked UNVERIFIED in the code:

- `verify_signature` — HMAC-SHA256 of the raw request body, hex, compared against the
  `X-Razorpay-Signature` header with the dashboard webhook secret as the key;
- `extract_captured_payment` — `event`, and
  `payload.payment.entity.{id, amount, currency, notes}` with `amount` an integer count
  of paise.

Razorpay's public documentation describes both the same way ([Validate and Test
Webhooks](https://razorpay.com/docs/webhooks/validate-test/), [Payment
Payloads](https://razorpay.com/docs/webhooks/payloads/payments/)), which is
corroboration, not verification: nothing here has ever been exercised against a live
account. **So the first real payment is a test, not a routine.** Plan it as an
attended event with someone watching the logs, on staging first if a staging Razorpay
account can be had. If the scheme is wrong the failure is fail-closed — every event is
refused and nothing is credited — which is the safe direction to be wrong in, and it is
also the direction that looks like "the client paid and nothing happened".

---

## 1. What can this deployment actually do?

One selector answers it, and every payment surface asks that one selector —
`payment_capability()` (`apps/api/billing/payments.py`). Nothing re-reads settings, so a
screen cannot offer what the route will refuse.

```
PaymentCapability(available, provider, reason, creates_orders)
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
caller can conclude "payments work" and then assume "so an order exists". It is False.

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

A successful response is not a payment. It is a priced, tenant-bound receipt plus
`notes: {"calevate_tenant_id": "<uuid>"}` — and those notes are not decoration. The
webhook resolves the tenant from exactly that key and from nothing else.

Money crosses the wire as a string (`"2500.00"`), never as a JSON float. A float is
refused at the boundary, not rounded (hard rule 7).

## 3. What to tell a client who wants to top up TODAY

The honest answer, in this order:

1. Online payment is not available on this deployment (§1 will tell you which reason).
   Even with credentials in place, we cannot create the provider-side order, so there is
   no checkout to send them to.
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

Do not promise a card payment "once we switch it on". Switching it on means writing an
order-creation adapter and verifying the signing scheme against a live account — two
pieces of work, neither of them configuration.

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
- **Never flip `PROVIDER_CREATES_ORDERS` to make a frontend happy.**
  `tests/payments_provider_seam_test.py` fails the moment it moves without an adapter
  behind it, and that test is the point of the constant.
- **Never paste a webhook body, a signature header or the webhook secret** into a ticket.
