# Emails: every message the platform sends

**Status: DRAFT AWAITING THE RENAME (D-933, 29 Oct 2026).** Part 1 is the inventory of what
is sent today and is current. Part 3 is the proposed wording, written with `{Product}`,
`{domain}` and `{entity}` in place of the name, to be applied on rename day
(`docs/REBRAND-MAP.md` §5). Nothing in Part 3 is live; today's emails keep today's words
and frame until then.

Placeholders: `{Product}` = `apps/api/core/brand.PRODUCT`; `{domain}` =
`apps/api/core/console_links.DOMAIN`; `{entity}` = `brand.LEGAL_ENTITY_NAME` ·
`brand.REGISTERED_ADDRESS` (mirrors of `apps/web/src/lib/legal/placeholders.ts`, held equal
by `tests/brand_tokens_test.py`); `{app}` = `https://app.{domain}`; `{slug}` = the client's
workspace slug; `{business}` = the client's business name; `{agent}` = the agent's name.

---

## 1. Inventory (what is sent today)

Sender purposes (Part 2): **SEC** security · **NOT** notifications · **BIL** billing ·
**ALR** alerts · **OPS** operator. Every client email carries the Reply-To
`notifications_reply_to` (today `calevate.voice@gmail.com`).

### Sign-in and account security (`apps/workers/auth_email.py`, composed in `apps/workers/email_render.py`)

| # | Email | Trigger | Recipient | Purpose | Subject today |
|---|---|---|---|---|---|
| A1 | Sign-in code | password accepted on a realm that asks for a second factor (admin always, D-170) | the person signing in | SEC | Your Calevate sign-in code |
| A2 | Confirm-it's-you code | a signed-in person makes a sensitive change (step-up) | that person | SEC | Your Calevate authorization code |
| A3 | Email verification code | an address is added or changed on an account | the new address | SEC | Your Calevate verification code |
| A4 | Sign-up code | self-serve sign-up (`authn/registration.py`) | the address signing up | SEC | Your Calevate sign-up code |
| A5 | Already have an account | sign-up attempted with an address that has an account | that address | SEC | You already have a Calevate account |
| A6 | Password reset | "Forgot password" | the account's address | SEC | Reset your Calevate password |
| A7 | Invitation | an owner invites a team member | the invitee | NOT | You have been invited to Calevate |
| A8 | Administrator set-up | `scripts/bootstrap_admin.py` on a new deployment | the first administrator | SEC | Set up your Calevate administrator account |
| A9 | Account address changed | an operator changes a client's billing (notice) address (`admin/routes.py` → `account_closure.py`, `address_changed`) | the PREVIOUS address | SEC | The email address for your Calevate account was changed |

### Account and product (`NOT`)

| # | Email | Trigger | Recipient | Subject today | Code |
|---|---|---|---|---|---|
| N1 | Account closed | an account is closed (owner or operator) | billing address + active owners | Your Calevate account has been closed | `workers/account_closure.py` |
| N2 | Account reopened | a closed account is restored before erasure | billing address + active owners | Your Calevate account has been reopened | `workers/account_closure.py` |
| N3 | Trial started | a free trial begins | billing address | Your free trial has started | `workers/trial_notices.py` |
| N4 | Trial ending | about a day before the trial ends | billing address | Your free trial ends in about a day | `workers/trial_notices.py` |
| N5 | Free test minutes used | trial minutes run out before the end date | billing address | Your free test minutes are used | `workers/trial_notices.py` |
| N6 | Maintenance planned / changed / started / finished | an operator schedules, amends, opens or closes a window | billing address + active owners | Planned Calevate maintenance · Change to the planned Calevate maintenance · Calevate is in maintenance now · Calevate maintenance is finished | `workers/maintenance.py` |
| N7 | Line notice (healer) | an agent's line is struggling, down, back, or a platform outage (D-701) | owners' addresses | the notice headline, e.g. "{agent} is not taking calls properly", "Calls are affected for everyone right now", "{agent} is answering calls again" | `workers/healer.py`, `healer/notices.py` |
| N8 | Number held / released / calls stopped | a number goes on hold, is about to be released, or released | billing address + active owners | Calls to your phone number have stopped · Your phone number will be given up soon · We have given up your phone number(s) | `workers/number_holds.py` |
| N9 | Weekly knowledge digest | weekly, per agent with enough calls | billing address | What your callers asked this week | `workers/kb_aggregation.py` |
| N10 | Business verification approved / rejected | an operator decides a KYC review (D-932) | owners | Verification outcome, with the reason and a button to fix it when rejected | `workers/kyc_notices.py` |
| N11 | Daily summary (D-944) | once a day at 20:58 IST, only for an account whose owner turned it on (Notification settings), and not on a day with nothing in it | billing address + active owners | Today: {n} calls answered, {n} new leads | `workers/owner_digest.py`, `notifications/daily_summary.py` |

### Billing (`BIL`)

| # | Email | Trigger | Recipient | Subject today | Code |
|---|---|---|---|---|---|
| B1 | Platform fee due / reminder / outgoing paused | monthly fee issued; reminder; grace ends unpaid | billing address | Your monthly platform fee is due · Reminder: your monthly platform fee is unpaid · Outgoing calls are paused: your platform fee is unpaid | `workers/billing.py` |
| B2 | Low credit / credit run out | wallet crosses the low or empty level | billing address | Your calling credit is running low · Your calling credit has run out | `workers/wallet_alerts.py` |
| B3 | Credit lapsing | a credit lot nears its lapse date | billing address | Some of your calling credit lapses soon | `workers/credit_expiry.py` |
| B4 | Auto-recharge started / done / failed / switched off | the auto-recharge flow | billing address | We are topping up your Calevate balance · Your Calevate balance has been topped up · Your automatic top-up did not go through · Auto-recharge is now off | `workers/razorpay_jobs.py` |
| B5 | Mandate approved / ended | the card or UPI mandate is confirmed or ends | billing address | Automatic top-ups are approved · Your automatic top-up approval has ended | `workers/razorpay_jobs.py` |
| B6 | Complimentary credit / made a paid account | a super admin grants credit or converts a trial | billing address | ₹X of credit added to your Calevate account · Your Calevate account is now a paid account | `workers/comp_notices.py` |
| B7 | Calling rates changing | the rate card changes for this client | billing address | Your Calevate calling rates are changing | `workers/rate_card_notice.py` |
| B8 | Dispute decided (won / lost / closed) | the first won, lost or closed outcome of a payment dispute (D-932) | billing address and owners | Dispute outcome wording, kinds `dispute_won` / `dispute_lost` / `dispute_closed` | `workers/razorpay_jobs.py` |

### Call, lead and team alerts (`ALR`)

| # | Email | Trigger | Recipient | Subject today | Code |
|---|---|---|---|---|---|
| L1 | Hot lead | a lead is marked hot after a call (2-minute SLO) | billing address | Hot lead from your AI agent | `workers/notifications.py` |
| L2 | Caller needs your team | a call matches a team-alert rule | the rule's verified contacts | A caller needs your team | `workers/team_alerts.py` |
| L3 | Caller-alert address code | a team contact address is added (SEC sender: it is a code) | that address | Your code for caller alerts | `workers/team_alerts.py` |

### Operator (`OPS`, to our own team only)

| # | Email | Trigger | Recipient | Subject today | Code |
|---|---|---|---|---|---|
| O1 | Alarm | an `alert()` classed as needing action (D-790) | `alerts_email` | [calevate/{env}/{service}] Action needed / Still open: {headline} ({code}) | `core/alerting.py`, `core/alert_email.py` |
| O2 | Alarm cleared | an episode stays quiet | `alerts_email` | [calevate/{env}/{service}] Cleared: {headline} ({code}) | `workers/alerts.py` |
| O3 | Complimentary grant made | a super admin grants credit | every super admin | Calevate: {business} {what} | `workers/comp_notices.py` |
| O4 | Backup alarms | the host's backup checks fail | `/etc/calevate/alerts.env` | set by `scripts/backup/*`, not by the app transport | `scripts/backup/` |

### Not sent today

Searched for and not found as emails (29 Oct 2026): welcome/onboarding, agent published,
number bought, top-up receipt for a manual payment (only auto-recharge mails, B4), invoice
delivery, refunds, Pip job finished, WhatsApp connection events, account erasure completed,
sign-in from a new device. **Disputes and KYC emails are being added in parallel (D-932) and
are not in this inventory**; they should be built with `email_render.product_email` (Part 3)
and given a purpose (`BIL` for disputes and refunds, `NOT` for KYC outcomes).

---

## 2. Senders (built, live, unchanged until set)

`calevate_shared.config.EmailPurpose` and `email_sender()`; every `get_transport(purpose)`
call names its purpose and `tests/email_senders_test.py` holds each module to the table
above.

| Purpose | Setting (ops console, live) | Proposed value on rename day | Display name |
|---|---|---|---|
| SEC | `sender_security` | `no-reply@{domain}` | {Product} |
| NOT | `notifications_from` | `notifications@{domain}` | {Product} |
| BIL | `sender_billing` | `billing@{domain}` | {Product} Billing |
| ALR | `sender_alerts` | `alerts@{domain}` | {Product} Alerts |
| OPS | `sender_operator` | `ops@{domain}` | {Product} Ops |

- **Unset means `notifications_from`**, so today every email still comes from
  `support@calevate.tech`. Reply-To stays `notifications_reply_to` for every purpose.
- **DNS:** none beyond the domain itself. Resend: "Once a domain is verified in your Resend
  account, you can send from any email address at that domain"
  (resend.com/docs/knowledge-base/how-do-I-create-an-email-address-or-sender-in-resend, read
  29 Oct 2026). So the five addresses need no per-address step; the founder verifies the new
  domain once (SPF, DKIM, DMARC). The addresses need not be real mailboxes, since replies go
  to Reply-To.
- **Display names are not wired yet.** The console field is an email input. On rename day,
  `ResendTransport` and `SmtpTransport` should send `"{display} <address>"` with the display
  name from the table, built in code from `brand.PRODUCT`, not typed into each setting.

---

## 3. Proposed wording (apply on rename day)

Rules: subject says what happened, specific and short; first line says what happened, second
what to do; one button; no exclamation marks; no vendor names (D-679); never another
product's wording. Every legally required and security sentence kept. Amounts stay in
`display_inr` form. Frame: `email_render.product_email` (logo, heading, up to 3 lines,
button, facts, footer with `{entity}` and the reason line).

Footer reason lines, by purpose:
- SEC: "You got this because someone used this email address on {Product}."
- NOT: "You got this because you own the {business} account on {Product}."
- BIL: "You got this because you are the billing contact for {business} on {Product}."
- ALR: "You got this because this address receives alerts for {business}." + Notification
  settings link `{app}/c/{slug}/settings/alerts`.
- OPS: unchanged operator frame (D-790).

### Security

| # | Subject | Heading | Lines | Button | Note (callout) |
|---|---|---|---|---|---|
| A1 | Your {Product} sign-in code | Your sign-in code | Enter this code to finish signing in. | (code panel, no button) | It expires in 10 minutes and works once. Didn't ask for this? It is sent only after your password was entered correctly. Do not share this code, and change your password. |
| A2 | Confirm it's you | Confirm it's you | Enter this code to confirm the change you asked for. | (code panel) | Didn't ask for this? Someone may be using your account. Do not share this code, and change your password. |
| A3 | Confirm your email address | Confirm your email address | Enter this code in {Product} to confirm this address is yours. | (code panel) | Didn't add this address? You can ignore this email. Nothing changes without the code. |
| A4 | Your {Product} sign-up code | Finish creating your account | Enter this code to finish creating your {Product} account. | (code panel) | Didn't sign up? You can ignore this email. No account is created without the code. |
| A5 | You already have a {Product} account | You already have an account | Someone tried to sign up with this address. Nothing new was created. | Choose a new password | The link works once and expires in one hour. If this wasn't you, your account and password have not changed. |
| A6 | Reset your {Product} password | Reset your password | Choose a new password with the button below. | Choose a new password | The link works once and expires in one hour. If you didn't ask, your password has not changed. |
| A8 | Set up your {Product} administrator account | Set up your administrator account | You have an administrator account on {Product}. Set a password to finish. | Set your password | The link works once and expires in one hour. |
| A9 | Your {Product} notice address changed | Your notice address changed | {business}'s account notices now go to a different address, so this is the last one sent here. | (none: the reader may no longer have access) | Didn't expect this? Reply to this email and we will look into it. |
| L3 | Your code for caller alerts | Confirm this address | Enter this code to start receiving caller alerts for {business}. | (code panel) | It expires in 30 minutes. Didn't ask for this? You can ignore this email. |

### Account and product

| # | Subject | Heading | Lines | Button |
|---|---|---|---|---|
| A7 | {inviter} invited you to {business} on {Product} | Join {business} on {Product} | {inviter} added you to their team. Set a password to get started. | Accept the invitation (link expires in 72 hours) |
| N1 | Your {Product} account is closed | Your account is closed | {business}'s account is closed and its agents no longer take calls. Your data is erased on {date} unless you reopen it before then. | Reopen the account |
| N2 | Your {Product} account is open again | Your account is open again | {business}'s account is back. Your agents can take calls again. | Open your dashboard |
| N3 | Your free trial has started | Your trial has started | Calls are on us until {date}. Set up your first agent and call it. | Open your dashboard |
| N4 | Your free trial ends tomorrow | Your trial ends soon | Your trial ends at {date}. Add credit to keep your agents answering. | Add credit |
| N5 | Your free test minutes are used | Your test minutes are used | You have used all {n} free minutes. Add credit to keep testing and go live. | Add credit |
| N6a | Planned maintenance on {date} | Planned maintenance | {Product} is unavailable from {start} to {end}. Calls during the window {behaviour}. | See details |
| N6b | Maintenance moved to {date} | Planned maintenance has changed | It now runs from {start} to {end}. | See details |
| N6c | Maintenance has started | Maintenance has started | {Product} is in planned maintenance until about {end}. | Status page `https://status.{domain}` |
| N6d | Maintenance is finished | Everything is back | The planned maintenance is finished. | Open your dashboard |
| N7 | (unchanged: `healer/notices.line_notice` headline) | same | what happened · what we did · whether you need to act (D-701) | See what happened |
| N8a | Calls to your number have stopped | Calls to your number have stopped | {number's agent} no longer receives calls because {reason}. | Open phone numbers |
| N8b | Your number will be released on {date} | Your number will be released | Keep it by {action} before {date}. | Open phone numbers |
| N8c | We released your phone number | Your number was released | {agent}'s number is no longer yours. | Open phone numbers |
| N9 | What your callers asked this week | What your callers asked | {agent} took {n} calls. Here is what callers asked that the agent could not answer. | Add answers |
| N11 | Today: {n} calls answered, {n} new leads | Your day on the phones | {n} calls answered and {n} missed today. · {n} new leads, {n} of them hot. · {n} call-backs waiting for you. Facts: spent today, cost per lead today, up to three hot leads by name with the number masked to its last two digits. Built on `product_email` already. | Open your dashboard |

### Billing

Facts block on every billing mail: Amount, Balance (where known), Date (IST).

| # | Subject | Heading | Lines | Button |
|---|---|---|---|---|
| B1a | Your platform fee for {month} is due | Platform fee due | {amount} is due by {date}. It is separate from your calling credit. Incoming calls are never affected. | Pay now |
| B1b | Reminder: platform fee due {date} | Platform fee still unpaid | Pay {amount} by {date} or outgoing calls pause. Incoming calls are never affected. | Pay now |
| B1c | Outgoing calls paused: platform fee unpaid | Outgoing calls are paused | Your {month} fee ({amount}) is unpaid. Outgoing calls resume as soon as it is paid; incoming calls continue. | Pay now |
| B2a | Your calling credit is low: {balance} left | Credit running low | Add credit before your calls stop. | Add credit |
| B2b | Your calling credit has run out | Your calls have stopped | Your agents have stopped answering. Add credit to start again. | Add credit |
| B3 | Some of your credit lapses on {date} | Credit lapsing soon | {amount} lapses on {date}. Use it before then or it is removed from your balance. | See your credit |
| B4a | Topping up your balance: {amount} | Top-up in progress | Your credit is below the level you set, so we are adding {amount} with the payment method you approved. | Open billing |
| B4b | Payment received: {amount} | Payment received | We added {amount} to your calling credit. | Open billing |
| B4c | Your automatic top-up didn't go through | Top-up failed | We could not add {amount}. Add credit yourself to keep calls running. | Add credit |
| B4d | Auto-recharge is off | Auto-recharge is off | {reason}. Turn it on again any time. | Open billing |
| B5a | Automatic top-ups approved | Automatic top-ups are on | We top up {amount} when your credit falls below {level}. | Open billing |
| B5b | Your automatic top-up approval has ended | Automatic top-ups are off | Approve again to keep your balance topped up. | Open billing |
| B6a | {amount} of credit added to your account | Credit added | We added {amount} of calling credit to {business}. No payment was taken and nothing is owed. | Open your dashboard |
| B6b | Your {Product} account is now a paid account | You are on a paid account | Your trial limits are lifted. No payment was taken. | Open your dashboard |
| B7 | Your calling rates change on {date} | Your rates are changing | From {date} your calls cost {new rate}. {legally required notice sentence kept as today}. | See the new rates |

### Call and lead alerts

| # | Subject | Heading | Lines | Button |
|---|---|---|---|---|
| L1 | New hot lead from {agent} | A hot lead is waiting | {agent} marked a caller as a hot lead at {time}. Call them back soon. | Open the lead |
| L2 | A caller needs your team: {agent} | A caller needs your team | {agent} needs someone to follow up with {caller}. | Open the call |

The hot-lead and team-alert bodies stay redacted exactly as today (`redact()`, no full
number in the mail, hard rule 6); only the frame and the first lines change.

---

## 4. Unsubscribe headers (RFC 8058)

Not built. Gmail's sender guidelines (support.google.com/a/answer/81126, read 29 Oct 2026)
require one-click unsubscribe for "Marketing messages and subscribed messages" from senders
above 5,000 messages a day to Gmail; the page does not address transactional mail. Of the
emails above N9 (weekly digest) and N11 (daily summary, which the owner switches on and off
on Notification settings; its footer links there) are subscribed periodic messages. There is no per-person
email preference store to honour an unsubscribe, so a `List-Unsubscribe` header would promise
something nothing records. What it needs: a per-recipient opt-out row (tenant-scoped, RLS,
one migration), a signed one-click `POST` endpoint on the api, the digest worker reading the
row, and `Transport.send` gaining optional headers. Security, billing and alert mail stay
without it.
