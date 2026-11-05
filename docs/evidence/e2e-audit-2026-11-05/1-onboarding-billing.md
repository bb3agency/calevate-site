# Lane 1: onboarding and billing (client realm)

Phase 1 of the 5 Nov 2026 audit: map, research, find. No code was changed.

**How this was checked**
- I read the code for every screen below and the API behind it.
- I drove the real app headless with Playwright and Chromium, at 1440px and 375px:
  - the web app on :3000 and the API on :8000;
  - signed in as the seeded owner of `sunrise-homes`, a real-estate business;
  - read only, with no writes.
- Screenshots and page text are in `C:/Users/jumes/AppData/Local/Temp/claude/a50a3f0a872c1724/0c51a750-0b23-4950-961e-84972febca40/scratchpad/audit/1-onboarding-billing/`. Files are `<route>-<width>.png` and `text/<route>-<width>.txt`, and the walk script is `walk.mjs` in the same folder.
- A delegated read-only review covered the top-up money path. Its findings are marked **[sub-review]**. I re-opened the key line for B-1 (`payments.py:652-662`). The others are cited as the reviewer gave them.

**What I could not check, and why**
- **The signup form and account creation.** Signup is closed on this deployment: `self_serve_signup` is false, and `/signup` renders "Signing up online is closed". The form was audited from code only (`app/signup/page.tsx`).
- **The own-number journey (`OwnNumbersJourney`).**
  - Locally `engine_has_workspaces()` is false, so `/v1/numbers/own/status` answers `available=False` (`apps/api/campaigns/engine_number_routes.py:130-144`).
  - The screen therefore falls back to the legacy operator-led panel.
  - The production path (ENGINE=thinnest) was read from code only.
- **The Meet-your-agent build, the trial test call, and Razorpay Checkout.** None of these was run, because they would place real calls or payments. The first-run screens were walked only up to step 1.
- **`/invite` and `/auth/accept-invitation`.** The walk crashed on a redirect, and I did not retry.
- **Spend figures.** The seeded account shows 12.5 minutes and 6 calls with ₹0 spent. That is consistent with seeded calls that have no debit rows. Whether a real call debits correctly is outside what this walk could see.

---

## 1. Map

| Screen / route | File(s) | What it is for |
|---|---|---|
| `/auth/sign-in` | `app/(auth)/auth/sign-in/page.tsx`, `components/authn/signInForm.tsx` | Email and password sign-in, or Google. The second step (emailed code) runs only if the server asks; the client realm does not require it. |
| `/auth/forgot-password`, `/auth/reset-password` | `app/(auth)/auth/*`, `components/authn/resetRequestForm.tsx`, `setPasswordForm.tsx` | Password reset |
| `/signup` | `app/signup/page.tsx`, `components/authn/createAccountForm.tsx`, `emailVerificationPanel.tsx`, `lib/api/signup.ts`, `lib/businessTypes.ts` | Account creation (work email, then a six-digit code, then name and password, or Google). After that, the business form: name, workspace URL, kind of business, billing email. Then a "What happens next" success card. API: `apps/api/tenancy/signup_routes.py` (next_steps at :148-153). |
| `/invite`, `/auth/accept-invitation` | `app/invite/page.tsx`, `app/(auth)/auth/accept-invitation/page.tsx` | Accepting a team invitation |
| `/auth/account` | `app/(auth)/auth/account/page.tsx`, `components/authn/accountSections.tsx` | The person's own account (name, password, sessions) |
| `/c` junction | `app/c/page.tsx` | Routes a signed-in person:<br>• to the first-run screen (`agents/first`) when it is due;<br>• otherwise to `go-live` when it is due;<br>• otherwise to the dashboard;<br>• with no workspace, to `/signup`. |
| Meet your agent `/c/[slug]/agents/first` | `agents/first/MeetYourAgent.tsx` plus `JobStep`, `BriefStep`, `BriefDocuments`, `QuestionsStep`, `BuildStep`, `HearItStep`, `ResultStep`, `OpeningLine`, `AgentTakingShape`, `LiveStage`, `shell.tsx`; `lib/useVerticalExamples.ts`, `lib/verticalExamples.ts` | Four steps:<br>1. Its job and its language.<br>2. Tell it about you (typed, voice or documents).<br>3. Hear it: accept the agreements and the pledge, attest "this number is my own", then a test call.<br>4. Make it yours.<br>API: `/v1/first-run`, `/v1/trial/calls` (`apps/api/agents/trial_call_routes.py`, `trial_calls.py`). |
| Business profile `/c/[slug]/settings/business` (`/setup` redirects here) | `settings/business/BusinessProfileScreen.tsx`, `SetupWizard.tsx`, `ProfileSection.tsx`, `BusinessCopySection.tsx`, `SetupDone.tsx` | Hours, address, what you offer, common questions, staff names, how to go ahead, people who take calls, and languages. Shown as "All answers" or "One at a time". Go-live blockers come from `apps/api/tenancy/business_profile.py:350-412`. |
| Go-live guide `/c/[slug]/go-live` | `go-live/GoLiveGuide.tsx`, `_ui/copy.ts` (GO_LIVE), `lib/api/goLive.ts` | Four steps: move agents, verify business, get number, switch on. It is owed from the first payment. API: `apps/api/go_live/guide.py`, `routes.py`. |
| Verify your business `/c/[slug]/verify-business` (`/verification` redirects here) | `verify-business/page.tsx`, `Steps.tsx`, `About.tsx`, `CallingNumbers.tsx`, `DltRegistration.tsx`, `PhoneNumbersNext.tsx`, `copy.ts` | Business details, certificate, owner ID (PAN or DigiLocker), and the no-cold-calls pledge and disclosure. API: `apps/api/compliance/kyc.py` and the pledge routes. |
| Phone numbers `/c/[slug]/phone-number` (`/settings/phone-numbers` redirects here) | `phone-number/PhoneNumberScreen.tsx`, `OwnNumbers.tsx`, `BuyNumber.tsx` (legacy), `NumberAssignment.tsx`, `ExistingNumber.tsx` | Numbers from Calevate, an existing number with forwarding, calls at once, and the "save my number" WhatsApp message. API: `apps/api/campaigns/engine_number_routes.py`, `engine_number_purchase.py`, `provisioning.py`. |
| Existing number `/c/[slug]/phone-number/existing-number` | `phone-number/existing-number/ExistingNumberScreen.tsx` | Forwarding codes and a test |
| Billing `/c/[slug]/billing` (`/credits`, `/usage`, `/spend` and `/invoice` redirect to a tab) | `billing/BillingScreen.tsx`, `WalletHero.tsx`, `TopUp.tsx`, `AddCredit.tsx`, `AutoRechargePanel.tsx`, `LowBalanceAlertPanel.tsx`, `UsageTab.tsx`, `UsageView.tsx`, `SpendPanel.tsx`, `SpendChart.tsx`, `CostPerResult.tsx`, `WhereItWent.tsx`, `VoiceTiers.tsx`, `WhatCallsCost.tsx`, `TransactionsTab.tsx`, `WalletLedgerPanel.tsx`, `ReceiptSheet.tsx`, `StatementsView.tsx`, `statementCsv.ts`, `LotsPanel.tsx`, `lots.ts`, `UnfinishedPayments.tsx`, `PlatformFeeCard.tsx`, `InvoicedAccount.tsx` | Balance and top-up (Razorpay), auto top-up, low-credit email, usage, spend, cost per result, voice tiers and rates, transactions and receipts, and statements. API: `apps/api/billing/payment_routes.py`, `payments.py`, `wallet_routes.py`, `spend_routes.py`, `history_routes.py`, `cap_routes.py`, `auto_recharge*.py`, `trial*.py`, `first_payment.py`, `credit_expiry.py`. |
| Team `/c/[slug]/settings/team` | `settings/team/TeamScreen.tsx`, `InviteForm.tsx`, `teamRows.tsx`, `roles.ts` | Invite, change roles (owner or staff), remove access |
| Agreements `/c/[slug]/agreements` | `agreements/Readiness.tsx`, `AcceptPanel.tsx`, `documents.tsx`, `copy.ts` | Terms, Privacy, Acceptable Use and DPA acceptance, plus what is still blocking calls |
| Privacy notice `/c/[slug]/caller-notice` | `caller-notice/page.tsx` | The notice the business shows to callers, with print and copy |
| Line protection `/c/[slug]/settings/line-protection` | `settings/line-protection/LineProtectionScreen.tsx` | Backup phone, and problems with your lines |
| Data rights `/c/[slug]/data-rights` | `data-rights/page.tsx` | Export or erase a person's data, and the rights-request desk |
| Alerts, messaging consent | `settings/alerts/AlertsScreen.tsx`, `messaging-consent/page.tsx` | Alert recipients; consent records |
| Trial gates (server) | `apps/api/compliance/trial_access.py:59-100`, `apps/api/billing/trials.py` | What a trial account may not do yet, and the wording it is given |

---

## 2. Findings

**Severity counts**

| Severity | Count |
|---|---|
| P0 | 0 |
| P1 | 7 |
| P2 | 16 |
| P3 | 11 |

### P1

| ID | Sev | Where | What happens (observed) | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| OB-1 | P1 | `go-live/GoLiveGuide.tsx` (NUMBER_COPY.locked, NumberStep) and `apps/api/go_live/guide.py:127-135` | The number step is "locked" for every purchase blocker other than business details: the trial, workspace not provisioned, and **price not attested**. The guide reaches that step only after KYC is verified. It then says "Opens once your business is verified" and offers a "Verify business first" button to an already verified business. | Map each blocker to its own sentence and action:<br>• `add_credit` → "Add credit";<br>• `workspace` → "We're setting up your calling account";<br>• `price` → "Numbers open soon. We'll tell you".<br>Send `blocker` in `GoLiveOut`. | `_BLOCKER_STEP` in `engine_number_purchase.py:82-88`; mapping at `guide.py:131-135` | 6 (truthful UI) |
| OB-2 | P1 | Same files, `waiting_approval` | `business_status` can be `rejected`, `suspended` or `expired` (`tenancy/models.py:673`). Any non-accepted status maps to "Your number is being approved. Nothing to do. This page moves on by itself". A rejected application waits forever, with the review note never shown. | When the status is rejected, show the review note and a "Fix and resend" button, as `OwnNumbers` already does. | `guide.py:132-135`; NUMBER_COPY.waiting_approval | 6 |
| OB-3 | P1 | `verify-business/About.tsx:44,137-148` | The "Where your calling number comes from" section reads: "From us, on our own telephony account… no operator account for you to open". This is shown to every client in production. D-693 says numbers are bought **in the client's own business name, in its own workspace**. `OwnNumbers.tsx` itself says "Registered to your business, not to us". The two pages contradict each other on a legal fact: who holds the connection. | Rewrite it to say the number is registered to your business once it is verified. Remove the operator-led sentence everywhere ThinnestAI workspaces are on. | Observed: `text/c_sunrise_homes_verify_business-1440.txt` ("From us, on our own telephony account."); CLAUDE.md D-693 | 6, 11 |
| OB-4 | P1 | `billing/UsageTab.tsx:178-188` | Postpaid-plan tiles are shown to a prepaid pay-as-you-go wallet. Observed:<br>• "Extra minutes 12.5, Beyond your plan";<br>• "Extra charges ₹0, ₹0 per extra minute".<br>On the same page Clear is "₹4.5 per minute". An owner reads this as "calls are free" or "the plan is exceeded". | When `included_minutes == 0` and the account is prepaid, hide the extra-minutes and extra-charges tiles. Show "Spent this month" from the wallet ledger instead. | `c_sunrise_homes_billing-1440.png`, `text/c_sunrise_homes_billing-1440.txt` | 6, 7 |
| OB-5 | P1 | `billing/VoiceTiers.tsx` and `apps/api/billing/payment_routes.py:612-623` | Clear shows "Not available to choose yet…" (a 45-word paragraph). On the same card it is still badged "The lowest price per minute" and "Best for: Most businesses", and the advice box says "**Clear suits you**". So we recommend a tier the client cannot choose.<br>On this engine the sentence also says "the vendor that speaks this voice changed". | When a tier is not offered:<br>• do not recommend it;<br>• collapse its benefits;<br>• replace the paragraph with "Not open yet" plus a "Why?" tap.<br>Never say "vendor". | `text/c_sunrise_homes_billing-1440.txt` (the "Clear or Studio" block). The local engine is fake; on thinnest, `_NOT_YET_OPENED_NOTICE` (:619-623) has the same shape for Studio. | 3, 4, 6 |
| OB-6 | P1 | `phone-number/PhoneNumberScreen.tsx:65-100` with legacy `BuyNumber.tsx` | On an account where own numbers are not available, the screen shows four messages at once: "cannot be bought from this screen… arranged with us", "Nothing to do here. We set it up with you.", "First, verify your business. [Verify your business]" and "No number yet." They say three different things about what to do. In production this branch is reached only when the engine has no workspaces. | Retire `BuyNumber.tsx` and the operator-led refusal now that D-693 is built. Rule: one way per problem. If that branch is kept, show one sentence and one action. | `text/c_sunrise_homes_phone_number-1440.txt`; API 422 `number_purchase_is_operator_led` observed on `GET /v1/numbers/available` | 4, 6, quality bar (one way) |
| OB-7 | P1 (law risk; founder decision to re-confirm) | `agents/first/HearItStep.tsx:390-397`; `apps/api/agents/trial_calls.py:144-205` | A trial test call rings any number the owner types after one tick: "This number is my own". There is no code sent to that phone (founder, 23 Oct 2026, quoted in the docstring). The tick also **lifts the 09:00-21:00 IST calling window** (`own_number_attested` → `check_dispatch`). So an unpaid, unverified signup can place AI calls to a third party at night. Twilio, the industry default, lets a trial call **only verified recipients**, verified by a code sent to that phone. | Before ringing a number that is not already verified for this account, send a one-time code to it. Then keep the tick for the calling-hours exception. Put this back to the founder as a decision. | Code cited; Twilio trial docs (read 5 Nov 2026, see §3) | 5 (compliance), TRAI calling hours |

### P2

| ID | Sev | Where | What happens | What should happen | Evidence | Rule |
|---|---|---|---|---|---|---|
| OB-8 | P2 | `go-live/GoLiveGuide.tsx` MOVE_COPY / GO_LIVE_STEPS | Step 1 of going live is "Move your agents", with "Setting up your calling account… Your agents move to your own account". This is our infrastructure migration (D-693) presented as the owner's task. A new owner has nothing to move. | Do it silently. If waiting is unavoidable, use a single line such as "Getting your account ready". Drop it from the four steps. | `c_sunrise_homes_go_live-375.png` | 4 |
| OB-9 | P2 | `go-live/GoLiveGuide.tsx` | The page header (mobile top bar and desktop breadcrumb) reads "Dashboard" on the Go live page. | Title it "Go live". | `c_sunrise_homes_go_live-375.png`; `text/...go_live-1440.txt` | 4 |
| OB-10 | P2 | `go-live` versus `agreements`, `verify-business` | The guide's four steps leave out agreement acceptance and the no-cold-calls pledge. Agreements shows "Outgoing calls blocked… cannot… publish an agent". The guide can therefore say "Switch it on" while the agent's switch refuses for a reason the guide never listed. | Add the agreements and pledge to the verify step's state, or link them, so the list matches the gates. | `text/c_sunrise_homes_agreements-1440.txt`; `guide.py` reads only KYC | 6 |
| OB-11 | P2 | `verify-business/About.tsx:157-159` | "Tell your account manager". Self-serve clients have no account manager. | "Tell us" with a contact button | code | 4, 6 |
| OB-12 | P2 | `verify-business/page.tsx` OutgoingSummary | A brand-new business sees "Outgoing calls are paused". "Paused" implies they were on. | "Outgoing calls open after these steps" | `text/...verify_business-1440.txt` | 4 |
| OB-13 | P2 | `verify-business` step 4 (pledge text, server-authored) | The disclosure says calls go "through Calevate's licensed telephony partners". Whether the engine vendor holds a licence is not evidenced in this lane. | Re-verify the licence with a primary source, or reword to "telephony partners". Hand this to the compliance lane. | `text/...verify_business-1440.txt` | 11 (UNVERIFIED claim) |
| OB-14 | P2 | `billing/CostPerResult.tsx` | It shows "Per answered call ₹0" (6 calls) and "Per lead ₹0" (3 leads) when nothing was charged. That reads as "leads are free". | Show "—" with "No charges in this window" when `spent == 0`. | `c_sunrise_homes_billing-1440.png` | 6 |
| OB-15 | P2 | `billing/VoiceTiers.tsx` / `WhatCallsCost.tsx` | The billing screen is long and shouts at once, with spending, cost per result, usage, the limit form, where-it-went, tiers and what calls cost all open. On 375px the user scrolls past three empty charts. | Collapse any empty sections. Put tiers and rates behind a tab or a "Why?". | screenshots at 375 | 4, density |
| OB-16 | P2 **[sub-review]** | `apps/api/billing/payments.py:652-662`; `TopUp.tsx:179-196` | The receipt key is built from tenant, amount and a 15-minute window only. After a paid top-up, picking the same amount again replays the **already paid** order: `choose()` does not reset once `stage==="verified"`. How Checkout behaves on a paid order is UNVERIFIED; the likely result is our "payment did not go through". | Never replay an intent whose attempt is captured. Reset the intent after `verified`. | Key composition re-read (`payments.py:652-662`) | 6, 7 |
| OB-17 | P2 **[sub-review]** | `TopUp.tsx:204-210`; `payment_routes.py:1082-1087` | "Payment received" is shown on the checkout signature, which proves authorisation, not capture. Razorpay auto-refunds uncaptured payments after the capture window. After `CREDIT_WAIT_MS` (3 min), "Balance updates within about a minute" stays on screen indefinitely. | Say "Payment approved, adding credit". After the wait, switch to "Still settling" and link to Unfinished payments. | Razorpay capture docs (§3) | 6 |
| OB-18 | P2 **[sub-review]** | `billing/AutoRechargePanel.tsx` | Auto top-up credit (and the ₹1 mandate payment) gets the 12-month expiry lot, but the panel never states the expiry. D-840 says the term is stated wherever a pack is sold. | Add the expiry line used in `TopUp.tsx:612-618`. | sub-review citation of `service.py:1303-1305` | 6, 7 |
| OB-19 | P2 **[sub-review]** | `payment_routes.py:912-924` | If `_remember_order` fails, its error is swallowed and the attempt never matches. The page then waits forever on a credit that has already landed. | Fall back to watching the wallet ledger by receipt. | sub-review | 6 |
| OB-20 | P2 | `app/signup/page.tsx:94` | The auth frame label on the signup page reads "Nothing here places a call". | "Create your account", or no label | `text/signup-1440.txt` | 4 |
| OB-21 | P2 | `app/signup/page.tsx:216`, `lib/legal/placeholders.ts:223` | The signup-closed page says "Write to calevate.voice@gmail.com" and "Open /c/your-slug". A Gmail address undermines trust, and a URL path is not an instruction an owner can follow. | Use a business-domain contact (a founder decision). Replace the path with a "Sign in" button. | `text/signup-1440.txt` | 4 |
| OB-22 | P2 | `app/signup/page.tsx:476-515` | Signup asks for a "Workspace URL" (`/c/…`, "Cannot be changed later") as a field. That is a technical, permanent decision at the first touch. Telugu names must type one by hand. | Derive it silently, ask only when it cannot be derived, and call it "Your web address". | code | 4; onboarding research §3 |
| OB-23 | P2 | `components/marketing/home/mockups/callCards.tsx:30-50`, rendered beside sign-in and signup (`AuthShowcase`) | Hand-written Telugu lines in source ("నమస్కారం, Akshara Coaching…"). | Move them into a founder-owned data file, as `spoken_style.json` does. | `text/signup-1440.txt` | 2 |
| OB-24 | P2 | Client realm (absence) | There is no client-facing guidance on spam labels (Hiya, Truecaller, Samsung "Suspected spam") on Line protection or Phone numbers, although the research exists: `docs/evidence/caller-spam-labels-2026-11.md` (4 Nov). A client whose campaign is blocked sees nothing. | Add a short "If callers see 'Suspected spam'" card on Phone numbers. It should give the steps from the evidence doc that are the business's own (registration in its own name). | grep for "spam" in `app/c`, `lib/api`: no match | 6, tempo (finish the seam) |
| OB-25 | P2 | `settings/business/BusinessProfileScreen.tsx` | The same four to-dos are shown twice, stacked: "Finish your business profile" and "Your setup 0 of 8". | Keep one list. | `c_sunrise_homes_settings_business-375.png` | 4, density |

### P3

| ID | Where | What | Fix |
|---|---|---|---|
| OB-26 | `TopUp.tsx:438-442` | Shows "order order_…" (Razorpay's internal id) and a lowercase "ref". **[sub-review]** | Show only "Reference clv_…". |
| OB-27 | `UnfinishedPayments.tsx:168` | A raw `attempt.outcome` code can reach the screen when it is not mapped. **[sub-review]** | Use a generic fallback sentence. |
| OB-28 | `verify-business/copy.ts` `stateLabel` | Returns a raw status string when unknown. | Use a fallback label. |
| OB-29 | Billing, Transactions tab | "Your credit history, newest first — 1 entries" | Pluralise. |
| OB-30 | `lib/verticalExamples.ts:110-267` | Placeholder examples keyed by vertical ("dental clinic in Hyderabad", "2 BHK in Gachibowli") show before AI copy lands. Real estate saw "We are a property office in Hyderabad…" in "Your agent so far". This is sanctioned as a fallback, but is still per-trade text in code. | Use the neutral "custom" example until `placeholders` arrive. |
| OB-31 | `payment_routes.py:353-408,571` | OpenAPI field docs call Clear "Sarvam" and name "Sarvam and Cartesia" rates. Not rendered, but the text is wrong per CLAUDE.md. **[sub-review]** | Fix the docstrings. |
| OB-32 | `auto_recharge.py:465` | `int(MANDATE_AUTH_AMOUNT_INR * 100)` instead of `inr_to_paise`. **[sub-review]** | Use the shared function. |
| OB-33 | `payments.py:653-661` | A pack and a custom amount of the same value share one receipt key. **[sub-review]** | Include `pack_id` in the key. |
| OB-34 | `app/c/page.tsx` error card | "there is no list of yours to choose from yet". A person in two businesses cannot switch. | Add an account switcher, or say who to ask. |
| OB-35 | `settings/team/teamRows.tsx` | After a member is removed, "Their leads stay assigned to them". Nobody follows them up. | Offer to reassign. |
| OB-36 | Team page at 375px | 429 `rate_limited` on `/v1/members`, `/v1/invitations`, `/v1/live` and `/v1/team/members` during one page load. Other lanes share localhost, so the cause is UNVERIFIED. | Check the rate-limit bucket per user versus per IP. |

**Checked and found correct:**
- No provider names appear on onboarding or billing screens; the only one is Razorpay inside its own checkout.
- Money is parsed as decimal strings. `Number()` is used only to size bars (`UsageTab.tsx:192`, `SpendPanel.tsx:98`).
- Dates are in IST (`formatIST`, `lots.ts:427`). `SpendChart` uses UTC deliberately, for date-only labels.
- The [sub-review] confirmed the following top-up properties:
  - Amounts are set on the server.
  - The webhook HMAC and the checkout signature are compared in constant time.
  - Credit is applied exactly once.
  - Only INR is accepted, and `first_paid_at` is set once.
- Layout: no horizontal overflow at 375px on any page walked (`scrollWidth == clientWidth`).
- The trial refusals are plain and consistent with signup's "What happens next" (`compliance/trial_access.py:59-89`, `signup_routes.py:148-153`).

---

## 3. Research notes

- **Trial calling only to verified numbers.** Twilio's trial guide says "You can call or message only verified recipients from a trial account". A recipient is verified by a code sent to that phone, up to 5 per account. Source: https://www.twilio.com/docs/usage/tutorials/how-to-use-your-free-trial-account (read 5 Nov 2026). This bears on OB-7: the industry default for free-trial outbound is verify-by-code, not a self-attestation tick.
- **Authorised is not captured.** Razorpay says an authorised payment "is approved but not yet captured". It also says "payments that are not captured within this period will be refunded automatically"; the default window is 3 days. Source: https://razorpay.com/docs/payments/payments/capture-settings/ (read 5 Nov 2026). This bears on OB-17: "Payment received" should wait for capture, or say "approved".
- **Locked steps in a task list.** The GOV.UK "complete multiple tasks" pattern says to use "Cannot start yet" when another task must be finished first, to leave the row unlinked, and to use a hint that tells users what they are waiting for. Source: https://design-system.service.gov.uk/patterns/complete-multiple-tasks/ (read 5 Nov 2026). This bears on OB-1, OB-2 and OB-10: each locked step needs its true reason, not one generic sentence.
- **Signup fields (OB-22).** No external source was fetched this session, so this is labelled design judgement and not a cited standard. The reasoning: a permanent technical field at the first touch adds a decision the server can already make (`derive_slug`).

---

## 4. Proposed fixes, grouped so lanes do not collide

**Group A: go-live guide truthfulness (OB-1, 2, 8, 9, 10)**
- API files: `apps/api/go_live/guide.py`, `apps/api/go_live/routes.py`, which add `number_blocker` and `business_review_note` to `GoLiveOut`.
- Web files: `apps/web/src/app/c/[slug]/go-live/GoLiveGuide.tsx`, `apps/web/src/app/c/[slug]/_ui/copy.ts` (GO_LIVE), and `lib/api/goLive.ts`, then regenerate the schema.
- Tests: `apps/web/tests/*goLive*`, and the guide's tests in `tests/`.

**Group B: number supply, one story (OB-3, 6, 11, 24)**
- Retire `phone-number/BuyNumber.tsx` and the `self_serve_purchase_refused` copy where workspaces exist (`apps/api/campaigns/provisioning.py:283-310`, `provisioning_routes.py`).
- Rewrite `verify-business/About.tsx` PhoneNumbers.
- Add a spam-label card in `phone-number/PhoneNumberScreen.tsx`.
- Tests that pin the old copy: `apps/web/tests/*BuyNumber*` and `*verifyBusiness*`.

**Group C: billing display (OB-4, 5, 14, 15, 29)**
- Web: `billing/UsageTab.tsx`, `CostPerResult.tsx`, `VoiceTiers.tsx`, `BillingScreen.tsx`, `TransactionsTab.tsx` / `WalletLedgerPanel.tsx`.
- API wording: `apps/api/billing/payment_routes.py:612-623`.
- Tests: `apps/web/tests/credits.test.tsx`, `topup.test.tsx` and `voiceNotOffered.test.tsx`, which pin the "vendor" sentence.

**Group D: the top-up path (OB-16, 17, 18, 19, 26, 27, 31, 32, 33)**
- API: `apps/api/billing/payments.py`, `payment_routes.py`, `auto_recharge.py`.
- Web: `billing/TopUp.tsx`, `AutoRechargePanel.tsx`, `UnfinishedPayments.tsx`, `lib/api/wallet.ts`.
- Must run the money tests and the coverage ratchet (hard rule 10).

**Group E: trial test-call safety (OB-7).** Founder decision first. Then:
- API: `apps/api/agents/trial_calls.py`, `trial_call_routes.py`, and `compliance/dispatch` (`check_dispatch`).
- Web: `agents/first/HearItStep.tsx`.

**Group F: signup and sign-in copy (OB-20, 21, 22, 23, 34)**
- `app/signup/page.tsx`, `lib/legal/placeholders.ts` (contact address, founder decision), `components/marketing/home/mockups/callCards.tsx` together with a data file, and `app/c/page.tsx`.
- This touches marketing mockups, so coordinate with the marketing lane.

**Group G: verification and profile copy (OB-12, 13, 25, 28, 30, 35, 36)**
- `verify-business/page.tsx`, `copy.ts`, the server pledge text (compliance lane, for OB-13), `settings/business/BusinessProfileScreen.tsx`, `lib/verticalExamples.ts`, `settings/team/teamRows.tsx`, and `apps/api/core/ratelimit.py` (investigate only).
