# Runbook — Razorpay payments: going live, and when a payment did not land

Symptoms this runbook answers: switching payments on; a client says they cannot top up; a
payment was taken and the wallet did not move; a refund; a dispute; auto-recharge stopped;
any alarm named `razorpay_*`, `topup_*`, `payment_dispute_*` or `auto_recharge_*`
(`runbooks/alarm-index.md` lists each).

**Where the facts come from.** Every Razorpay behaviour this runbook and the code rely on was
read from Razorpay's own documentation on 9 Oct 2026 (`https://razorpay.com/docs/llms.txt`,
pages at `https://razorpay.com/docs/build/llm-docs/<path>.md`) and is cited where it is used:
`apps/api/billing/payments.py` (module docstring), `razorpay_api.py`, `auto_recharge.py`,
`disputes.py`. Two things are NOT in their documentation and are proved only by Part A's
rehearsal: the key-id prefixes `rzp_test_` / `rzp_live_` (§A3) and whether Checkout's script
loads an origin our Content-Security-Policy does not name (§A6).

**What is built (D-699).** Top-ups through Standard Checkout with server-side orders; the
signed webhook for payments, refunds, tokens and disputes; refunds (admin, step-up, up to the
unspent credit of a payment); auto-recharge on UPI Autopay or a card mandate; dispute holds
with an admin page to contest or accept; a daily reconciliation against Razorpay's API; a
test/live mode guard. Number rental is still charged from wallet credit. There are no
invoices or payment links for clients: everyone is prepaid.

`PROVIDER_CREATES_ORDERS` is `True` in `apps/api/billing/payments.py`: that is a claim about
the code (the order adapter exists). Whether THIS deployment can open a checkout is
`payment_capability().creates_orders`, which stays false until `RAZORPAY_KEY_SECRET` is set
in Part A.

---

## PART A — GOING LIVE, IN ORDER (founder)

Do every step in TEST mode first (A1-A7), then repeat A3-A4 with live values and do A8.
Nothing here is reversible by code if skipped: the order is the point.

### A1. Create the Razorpay account

Sign up at razorpay.com with the business email. The dashboard opens in **Test mode**
immediately; Live mode is available only after activation
(`payments/dashboard/test-live-modes.md`).

### A2. Activate: KYC as a sole proprietorship

In the dashboard, complete activation as a **sole proprietorship** in Calevate's trade name
(the legal person is the founder; `docs/legal/LEGAL-OPS-PLAYBOOK.md`). Have ready: PAN, the
bank account settlements go to, and the website with its legal pages live — Terms, Privacy,
Refund & Cancellation, Contact and Grievance (`/legal/*`). Razorpay's own form decides the
exact documents; this repository has not read the activation pages, so follow the form.

### A3. Keys, and the four console values

Generate API keys in the mode you are setting up: Account & Settings → API Keys
(`payments/dashboard/account-settings/api-keys.md`). Live keys need an OTP. **Check the key id
starts with `rzp_test_` (test) or `rzp_live_` (live)**: that prefix is not documented, our
mode guard relies on it, and a key that matches neither is refused with
`payment_mode_mismatch` — if that happens, stop and report it; do not edit code to pass it.

Admin console → **Platform configuration** (`/admin/ops/config`):

| Setting | Value | Where | Secret |
|---|---|---|---|
| `payment_provider` | `razorpay` | Billing → payments | no |
| `razorpay_mode` | `test` (rehearsal) or `live` | Billing → payments | no |
| `razorpay_key_id` | the key id | Billing → payments | no (the browser sees it) |
| `razorpay_key_secret` | the key secret | **Vendor credentials** (needs `platform:secrets`) | yes |
| `razorpay_webhook_secret` | the secret YOU choose in A4 | **Vendor credentials** | yes |

- **The key secret and the webhook secret are different secrets.** Swapping them installs
  cleanly and refuses every genuine payment (`razorpay_webhook_bad_signature`). Razorpay:
  "The webhook secret does not need to be the Razorpay API key secret"
  (`webhooks/setup-edit-payments.md`).
- **Production refuses test keys.** On `APP_ENV=prod`, `razorpay_mode` must be `live` and the
  key id must not be a test key, or every payment surface answers "unavailable"
  (`test_mode_in_production`). Off production, an unset mode is allowed.
- All five are `live` settings: the fleet re-reads them within seconds, no restart.
- `/admin/payments` shows the mode, which values are set (never the values), whether payments
  are available and why not.

### A4. The webhook: URL, secret, events

Dashboard → Accounts & Settings → **Webhooks** → **+ Add New Webhook**
(`webhooks/setup-edit-payments.md`). Test and live have SEPARATE webhooks; set up each.

- **URL**: `https://api.calevate.tech/hooks/v1/razorpay`. **NOT `hooks.calevate.tech`**: that
  host is voice-runtime, which answers this path with a 404, so every delivery would be lost
  (pinned by `tests/edge_route_policy_test.py`). Ports 80/443 only.
- **Secret**: a long random string you generate; install it as `razorpay_webhook_secret`.
  Changing it later means old retries are signed with the old secret
  (`webhooks/validate-test.md`).
- **Alert email**: the founder's. Razorpay disables a webhook that fails for 24 hours and
  emails this address (`webhooks/best-practices.md`).
- **Active events** — tick exactly these (also listed live on `/admin/payments`,
  `payments.SUBSCRIBED_EVENTS`):

  `payment.authorized`, `payment.captured`, `payment.failed`, `order.paid`,
  `refund.processed`, `refund.failed`, `token.confirmed`, `token.rejected`,
  `token.cancelled`, `token.paused`, `payment.dispute.created`, `payment.dispute.won`,
  `payment.dispute.lost`, `payment.dispute.closed`, `payment.dispute.under_review`,
  `payment.dispute.action_required`.

  Test mode asks for an OTP when you save; Razorpay's documented test OTP is `754081`.

### A5. Capture, refunds and international cards

- Account & Settings → **Payment Capture**: **Automatic capture**, "Capture all payments
  authorised within" **3 days**, **Refund automatically**, speed **Normal**
  (`payments/payments/capture-settings.md`). This is Razorpay's default; confirm it. We never
  capture through the API: a payment Razorpay does not capture is refunded by Razorpay, and
  the daily reconciliation alarms (`uncaptured:`) on one left authorised for over an hour.
- Account & Settings → **International payments**: keep the toggle **OFF**
  (`payments/international-payments/international-debit-credit-cards.md`). It is off until
  requested. One arriving anyway is credited and alarmed (`razorpay_international_payment`).
- All payment methods Razorpay enables by default stay on: debit and credit cards,
  netbanking, UPI, EMI and wallets (`.../web-integration/standard/integration-steps.md`).
- **Recurring Payments must be active on the account.** Razorpay's overview says the
  recurring methods are "available by default" (`payments/recurring-payments.md`) while the
  UPI integration guide says to raise a request to activate them
  (`payments/recurring-payments/upi/integrate.md`). Raise the request from the dashboard
  support page anyway and do not switch auto-recharge on for clients until a test mandate
  confirms (A7 step 5) — OPERATIONS §2 gate 44i. RuPay recurring is a beta enabled on
  request (`payments/recurring-payments/cards/faqs.md`); it is not needed. UPI Autopay registers through UPI Intent on mobile and a
  QR code on desktop; UPI Collect is deprecated for new mandates from 28 Feb 2026.

### A6. Content-Security-Policy check

`apps/web/src/lib/security/csp.ts` admits, from Checkout's own script (`checkout.js`, read
9 Oct 2026): script `checkout.razorpay.com`; frames `checkout.razorpay.com`,
`api.razorpay.com`; connections `api.razorpay.com` and the `lumberjack*` telemetry hosts;
images `cdn.razorpay.com`. Open the browser console on the top-up screen with Checkout open,
and on the auto-recharge set-up. **Any `Content-Security-Policy` refusal naming a Razorpay
origin**: the payment still works if it is telemetry; add the origin to `csp.ts` and redeploy.
The collector at `POST /reports/v1/csp` records it either way (`csp_violation`).

### A7. Test-mode rehearsal (all of it, before any live key)

Test details (`payments/payments/test-card-details.md`, `test-upi-details.md`): card
`4100 2800 0000 1007` (Visa debit), any future expiry, any CVV, OTP of 4-10 digits succeeds;
UPI `success@razorpay` / `failure@razorpay`; recurring card `4718 6091 0820 4366` (test card
tokens last 3 days only).

1. **Top-up ₹100.** Client billing page → Add credit. Expect: "Paying" → "Verifying" →
   "Credited"; one `topup` row on the client's credits page with the payment id as ref; the
   attempt captured; no alarm. In the dashboard the payment is Captured, amount `10000`.
2. **Double click.** Two clicks within 15 minutes give ONE order.
3. **Failure.** `failure@razorpay` → "The payment did not go through", nothing credited, the
   attempt failed.
4. **Refund.** `/admin/tenants/<id>/credits` → Refund, part of the payment. Needs the step-up
   (`X-Confirm-Action: refund_payment:<tenant>:<payment>` and a fresh second factor; the
   console sends both). Expect one negative `refund` row and `refund.processed` deduped onto
   it. Asking for more than the unspent credit of that payment is refused.
5. **Auto-recharge.** Client billing → Auto-recharge → Set up with UPI (or the recurring
   card). The ₹1 approval payment is credited; the mandate shows "Waiting for your bank",
   then "Approved" on `token.confirmed`. Turn it on with a threshold above the balance; within
   five minutes a charge starts and the client is emailed. In test mode Razorpay's debit
   follows its own pre-debit timing (25 h UPI, 36 h 5 min cards); the charge row stays
   "pending" until then. Withdraw the approval: `token.cancelled`, auto-recharge off.
6. **Reconciliation.** `/admin/payments` → Run reconciliation. Expect nothing unexplained.
7. **Mode guard.** Set `razorpay_mode` to `live` with the test key: payments become
   unavailable (`payment_mode_mismatch`). Set it back.

### A8. Live: one attended ₹100 payment and its refund

1. Repeat A3 with the live key pair and `razorpay_mode = live`, and A4 for the live webhook.
2. On a real client account (or the founder's own), top up ₹100 with a real card or UPI.
   Record: the order id in the logs (`topup_order_created`); the payment Captured at
   `10000` paise; ONE `topup` ledger row with the payment id as ref; the attempt captured;
   no `razorpay_*` alarm; no CSP refusal.
3. Refund it from the credits page. Record the `refund.processed` and the one negative row.
4. Mark OPERATIONS §2 gate 44H passed with the date and the payment id.

---

## PART B — OPERATING

### B1. Is this deployment able to take a payment?

`/admin/payments` answers it: provider, mode, the key id's mode, which credentials are set,
`online_payments_available`, `provider_orders_available`, and the reason when not. The reasons
are ours: `no_payment_provider`, `provider_not_implemented:<name>`, `no_publishable_key`,
`no_webhook_secret`, `payment_mode_mismatch`, `test_mode_in_production`, and for orders only
`no_api_secret`.

### B2. A client says they paid and the balance did not move

1. Find the payment in the Razorpay dashboard; note the payment id and order id.
2. `/admin/payments` → Run reconciliation. It credits a captured payment of ours that the
   webhook missed, through the webhook's own code and onto the same ledger ref, so a late
   webhook cannot double it.
3. If the reconciliation lists it as unexplained:
   - `unattributed:` — no order record and no notes (a payment made outside our checkout).
     Credit it by hand on `/admin/tenants/<id>/credits` with the **payment id** as the
     reference, after confirming the payer.
   - `payment_order_mismatch` / `amount:` — the payment's amount or account differs from what
     we asked the order for. Do not credit; investigate in the dashboard.
   - `uncaptured:` — authorised, not captured: fix the capture setting (A5); Razorpay refunds
     it after the window.
4. `topup_settlement_silent` means no delivery at all is arriving: check the URL first (A4),
   then the secret, then whether Razorpay disabled the webhook after 24 hours of failures.

### B3. The webhook

- One endpoint, `POST /hooks/v1/razorpay`, verified on the raw body before anything is read.
- Deduped on Razorpay's `x-razorpay-event-id` (inbox) and, for money, on the payment or
  refund id on the ledger (the guarantee).
- No handler calls Razorpay or sends mail inline; emails and alert mails go through the
  outbox and the alert thread, so the 200 returns well inside Razorpay's 5-second timeout.
- Retries for 24 hours with backoff; then the webhook is disabled and the alert email is
  sent. Re-enable it in the dashboard after fixing the cause; reconciliation then catches up.

### B4. Refunds

Admin only, per client: `/admin/tenants/<id>/credits` → Refund. The refund goes to the
original payment method through the Refunds API (normal speed, 5-7 working days), is recorded
as a compensating negative entry, and is capped at the **unspent** credit of that payment.
`refund.failed` releases the claim and pages (`razorpay_refund_failed`): reissue, or pay by
bank transfer and record it. A 409 from Razorpay means the same refund is still processing:
wait; the claim is kept. Unused credit is NOT refunded on closure (Refund Policy §2.2): the
closure screen shows the forfeited amount before you confirm.

### B5. Disputes and chargebacks

`payment_dispute_opened` pages. The disputed amount is held against the client's credit and
their OUTBOUND calling pauses; inbound is untouched; the client's screens say why.

1. `/admin/payments` → Disputes. Note the respond-by date.
2. **Contest**: attach evidence (PDF/JPEG/PNG, 5 MB each; at least one is required by
   Razorpay) — the receipt, the call records for the period, our Terms and Refund Policy —
   choose the evidence type, write a summary, confirm. **Accept** refunds the customer and
   is irreversible.
3. Won or closed: the hold is released automatically. Lost: the hold stays as the final debit
   (Razorpay has deducted it from our balance). Outbound resumes when no dispute is open.

### B6. Auto-recharge

- Per-debit limit ₹15,000 (no additional authentication is possible unattended), a monthly
  cap the client sets, one recharge in flight per client.
- Razorpay sends the pre-debit notification and debits 25 h (UPI) / 36 h 5 min (cards) after
  it, retrying failed debits itself. We fail a charge Razorpay has not answered in 3 days.
- After `auto_recharge_max_failures` (default 3) failures in a row it switches off and the
  client is emailed (`auto_recharge_disabled`, attention).
- A mandate the client pauses or cancels in their UPI app arrives as `token.paused` /
  `token.cancelled` and switches auto-recharge off.

### B7. Settlements

Read only: the daily reconciliation counts and sums them in its log line and on the admin
"Run reconciliation" result. Nothing in Calevate acts on a settlement.

## What NOT to do

- Do not credit a payment by hand without the payment id as the reference.
- Do not change the webhook secret without installing the new one in the same minute.
- Do not put test keys on production, or edit the mode guard to make a key pass.
- Do not capture payments from the dashboard "to help": auto-capture is the setting.
- Do not loosen a payload parser to make a refusal go away; capture the real delivery and fix
  the one function that reads it.
