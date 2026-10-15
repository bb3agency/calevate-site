# WhatsApp onboarding for clients: what Meta allows, what we have, what to build (15 Oct 2026)

Scope: how a Calevate client gets their own WhatsApp sending capability so that their agent can
send WhatsApp messages during or after a call (D-700 client actions). It covers three starting
points: a client with no WhatsApp Business Platform account, a client who uses the WhatsApp
Business **app** on their number, and a client who already has an API account through a BSP
or directly. The doc does not cover Calevate's own WABA, which is H-1, F-8 and D-91. It touches
that WABA only where a design choice depends on it.

**How to read the evidence classes.** Every vendor sentence below names its source and its
read date. All reads are 15 Oct 2026 unless marked otherwise. The classes, per
`docs/RESEARCH-DISCIPLINE.md`, are:

- **VERIFIED-VENDOR-DOCS**: read this session on the vendor's own page.
- **VENDOR-PUBLISHED (mirror)**: read in the hash-pinned ThinnestAI mirror at
  `thinnest-findings/mirror/snapshots/2026-10-13/pages/`.
- **REPORTED**: third-party or secondary. It is a lead, never evidence.
- **UNKNOWN**: not established.

Meta pages were read as the `.md` renderings under
`https://developers.facebook.com/documentation/business-messaging/whatsapp/`, abbreviated below
as `wa-docs/`.

---

## 1. Summary

**Possible**

1. **Calevate can onboard a client's WhatsApp without the client touching any developer
   tooling.** This requires Calevate to become a Meta **Tech Provider** and host Meta's
   **Embedded Signup**. Embedded Signup creates the client's WABA, verifies their number and
   grants our app access. It then returns the WABA id, the phone number id and a code we
   exchange for a per-client **business token**. With that token we can do the rest by API:
   subscribe webhooks, register the number, create templates and send.
2. **A client already on the WhatsApp Business app can keep using the app** through
   **Coexistence**, which is onboarded through the same Embedded Signup. Meta documents the
   limits (fixed 20 mps, broadcast lists read-only, some 1:1 features off, groups not
   supported). Messages sent from the app stay free.
3. **A client already on a BSP or on Cloud API directly has three ways to link:**
   - They paste their BSP key or a system-user token. This is what we build today.
   - They grant our app access to their existing WABA through Embedded Signup ("app-only
     install").
   - They migrate their number to a WABA onboarded by us. Two-step verification must be off,
     and approved GREEN templates are duplicated.

**Not possible, or not established**

1. **Not possible:** onboarding with no Meta login at all. Meta's flow has the customer
   "authenticate their identity using their Facebook or Meta Business Credentials"
   (`wa-docs/embedded-signup/overview.md`). Whether a login other than a Facebook account
   works in practice is **UNKNOWN**.
2. **Not possible for Calevate as a Tech Provider:** paying the client's Meta message fees.
   For Tech Providers, "your onboarded business customers must add a payment method to their
   WhatsApp Business account" (`embedded-signup/overview.md`, Billing). Sharing a credit line
   is a **Solution Partner** capability, which is a much heavier programme.
3. **Not possible: sending as the client from Calevate's own WABA.** Calevate's number would
   show Calevate's display name. Meta forbids impersonating another business
   (whatsappbusiness.com/policy). Opt-in must name the business the person opts in to
   (`wa-docs/getting-opt-in.md`).
4. **Not possible: in-call WhatsApp to a caller with no messaging consent on file.** This is
   our own rule, and it is correct. It matters because nothing captures that consent during
   a call (§7, gap G-7). In practice, most in-call sends will be refused today.
5. **UNKNOWN: whether Coexistence is available for Indian numbers.** Meta's Coexistence page
   names no countries. Third-party pages contradict each other.
6. **UNKNOWN: whether a WABA held through an Indian BSP can also be granted to our app.**
   Meta's pages describe app-only install and multi-partner solutions. Neither says whether a
   WABA on another partner's credit line can be added.

**Through ThinnestAI (VENDOR-PUBLISHED mirror)**

ThinnestAI already runs Embedded Signup inside its console. It offers two cards: "Apply for a
WhatsApp Business Account" and "Connect an account you already have"
(`channels/whatsapp.md:15-25`). It also has built-in "Send the customer a WhatsApp" tools
(`agent/actions.md:99`, `agent/after-the-call.md:24`). But WhatsApp "is connected in the
console, because Meta's sign-up runs in the business owner's own browser"
(`api-reference/channels/connect-telegram-bot.md:50-53`). So for our API-created customer
workspaces there is no API path. A client would need to sit in ThinnestAI's console, which
D-679 rules out for clients.

---

## 2. What our code does today

| Area | What is built | Where |
|---|---|---|
| Action kinds | `whatsapp` action, delivered by provider `aisensy`, `meta_cloud`, `interakt` or `custom` (generic REST) | `apps/api/actions/models.py:46-52, :65-70, :85-91` |
| Credential the client provides | **AiSensy:** API key. **Meta Cloud:** "A permanent system user token from Meta Business Settings". **Interakt:** API key. Each is pasted, sealed per tenant with `core/envelope.seal`, and never returned. | `apps/web/src/app/c/[slug]/integrations/ConnectedAccounts.tsx:71-78`; `apps/api/actions/credentials.py:1-30` |
| What the action form asks | Template name (AiSensy: "Campaign name"), template language (not AiSensy), **Phone number ID** for Meta ("From WhatsApp Manager → API Setup"), ordered body variables, optional header variable | `apps/web/src/app/c/[slug]/agents/actions/KindFields.tsx:302-322`; schema `apps/api/actions/schema.py:146-174` |
| How sending works | One executor (`execution._send_template`, `apps/api/actions/execution.py:478`, called by `_run_whatsapp` at `:543`). It runs `check_dispatch` (DNC first), then requires the caller's **messaging consent** on file, then builds the provider's template request. | `apps/api/actions/whatsapp.py:95-136`, builders `:166-302` |
| Templates | Always a template, never free text, because we cannot see the client's 24-hour window. The client must already have an approved template (or a Live AiSensy API campaign) and type its name. We do not create, list or check templates. | `apps/api/actions/whatsapp.py:33-37`; `runbooks/client-actions.md:59-60` |
| Limits | 2 WhatsApp sends per action per call (Redis) | `apps/api/actions/in_call.py:63` |
| Test button | Sends only to the client's own business contacts | `apps/api/actions/whatsapp.py:139-163` |
| Calevate's own WABA (separate) | Hot-lead alerts, missed-call follow-up `calevate_missed_call_follow_up_v1` (names the CLIENT's business, sent from CALEVATE's WABA), save-our-number `calevate_save_our_number_v1`. Never run against a live WABA. | `apps/workers/whatsapp.py:811-827`; `apps/workers/whatsapp_cloud.py:190`; `apps/api/forwarding/save_number.py:50`; OPERATIONS H-1, F-8 |
| Meta webhook receiver | Lead Ads only: `X-Hub-Signature-256` with the app secret, plus the `hub.challenge` handshake. No WhatsApp fields. | `apps/api/ingest/meta.py:1-40` |
| ThinnestAI built-ins | `send_whatsapp` is pinned **false** on every publish | D-690; `engine/thinnest.built_in_tools_body` |
| Gates | A-5 (WhatsApp shapes not printed), A-7 (every action live), A-9 (counsel: client's processors) | `docs/OPERATIONS.md:258-262` |

**Defects found while reading.** These need code changes; none was made here.

1. **AiSensy `userName` is set to `"Calevate"`** (`apps/api/actions/whatsapp.py:201`).
   AiSensy documents `userName` as the "Name of the user to whom the campaign has to be sent"
   (aisensy.com/tutorials/api-reference-docs, VERIFIED-VENDOR-DOCS). So every contact we
   create in the client's AiSensy is named "Calevate". The fix is to send the caller's name
   when known, else the number.
2. **The Interakt rate limit in the docstring is stale.** It says "40 requests a minute"
   (`apps/api/actions/whatsapp.py:45`). Interakt's page now lists 300 a minute on Growth, 600
   on Advanced, and a configurable limit on Enterprise, with a 429 when exceeded
   (interakt.shop/resource-center/how-to-send-whatsapp-templates-using-apis-webhooks,
   VERIFIED-VENDOR-DOCS). It is only a comment, but under rule 11 it is a wrong vendor figure.
3. **The `apps/workers/whatsapp_cloud.py` docstring may be wrong about in-window pricing.** It
   says the free in-window utility carve-out "closes on 1 October 2026". ThinnestAI's page says
   the same: "free inside an open window, until 1 October 2026" (`meta/windows-and-pricing.md`).
   But Meta's pricing page, read today, still says "Utility templates delivered within an open
   customer service window are free" and states no closure (`wa-docs/pricing.md`).
   **UNKNOWN which is current.** Treat the docstring as REPORTED until Meta's 1 Oct 2026 rate
   card is read.
4. **That same docstring's India rates (₹0.115 utility, ₹0.8631 marketing, "effective 1 July
   2026") are REPORTED.** Meta's rate card is "effective July 1, 2026" (`wa-docs/pricing.md`),
   but the INR figures are not in the page text. The interactive table did not render
   (whatsappbusiness.com/products/platform-pricing). Only third-party pages print those
   numbers. **UNKNOWN as primary-verified.**

---

## 3. Scenario A: a client with no WhatsApp Business Platform account

### 3.1 What Meta's Embedded Signup does (VERIFIED-VENDOR-DOCS, `wa-docs/embedded-signup/overview.md`)

- **The customer's side of the flow.** The customer:
  - authenticates "using their Facebook or Meta Business Credentials";
  - accepts terms;
  - grants our app access;
  - selects or creates a business portfolio;
  - selects or creates a WABA;
  - enters and verifies a business phone number, "their own, or one you have provided";
  - enters a display name.
- **What it returns.** "Embedded Signup returns the customer's WABA ID, business phone number
  ID, and an exchangeable token code."
- **Code lifetime.** The code has a "time-to-live of 30 seconds"
  (`embedded-signup/implementation.md`).
- **Version.** "Embedded signup v2 will be deprecated on October 15, 2026." That is today. v4
  was released 8 Oct 2025 (`embedded-signup/version-4`). Build on v4 only.
- **Configuration.** v4 is configured in App Dashboard > Facebook Login for Business >
  Configurations, with the Embedded Signup login variation. Selecting products "automatically
  selects all necessary permissions and assets". "You will need advanced access for all
  permissions automatically selected in the flow."
- **Launch call.** `FB.login({config_id, response_type: 'code',
  override_default_response_type: true, extras: {setup: {}}})`.
- **Result events.** The session-logging event returns `phone_number_id`, `waba_id` and
  `business_id`, with `event` set to one of `FINISH`, `FINISH_ONLY_WABA`,
  `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING`, `FINISH_OBO_MIGRATION`,
  `FINISH_GRANT_ONLY_API_ACCESS`, `CANCEL` (with `current_step`) or `ERROR`.
- **Domains.** Our domain must be in "Allowed domains" and "Valid OAuth redirect URIs", and
  must be HTTPS (`implementation.md`).
- **Number restrictions.** "Business phone numbers can only be registered for use with Cloud
  API." Numbers already on the WhatsApp Business app are supported once the flow is
  customised for it (scenario B).
- **Onboarding limits.** "By default, you can onboard up to 10 new business customers in a
  rolling 7-day window." This rises to 200 once "you complete Business Verification, App
  Review, and Access Verification". Beyond 200 a week means applying to be a Meta Business
  Partner.

### 3.2 Steps: who does what

| # | Step | Who | Can Calevate automate it? | Source |
|---|---|---|---|---|
| 1 | Log in to Facebook (or Meta Business credentials) in Meta's popup on our page | **Client** | No. Meta requires the business owner's own login. | `embedded-signup/overview.md` |
| 2 | Accept Meta's terms; grant our app access | **Client** | No | same |
| 3 | Pick or create a business portfolio and a WABA | **Client**, inside the popup | Partly. Fields can be pre-filled (`embedded-signup/pre-filled-data.md`, not read this session). | same |
| 4 | Enter the number; receive and type the 6-digit code (SMS or voice) | **Client** | No | same; ThinnestAI `channels/whatsapp.md:64-70` |
| 5 | Enter the display name | **Client** | Pre-fill only | same |
| 6 | Exchange the code for a business token: `GET https://graph.facebook.com/v21.0/oauth/access_token?client_id&client_secret&code` | **Calevate** server, within 30 s | Yes | `embedded-signup/onboarding-customers-as-a-tech-provider.md` |
| 7 | Subscribe our app to the WABA's webhooks: `POST /<WABA_ID>/subscribed_apps` | Calevate | Yes | same |
| 8 | Register the number: `POST /<PHONE_NUMBER_ID>/register {messaging_product: "whatsapp", pin}`. The 6-digit PIN becomes the number's two-step verification PIN. | Calevate | Yes | same |
| 9 | Create templates: `POST /<WABA_ID>/message_templates`. Review "can take up to 24 hours"; status arrives on the `message_template_status_update` webhook. | Calevate | Yes | `wa-docs/templates/overview.md`; webhooks overview |
| 10 | **Add a payment method in Meta** (WhatsApp Manager > Overview > Add payment method) | **Client** | No. "Once this is done, the customer is fully onboarded." | `onboarding-customers-as-a-tech-provider.md` (Step 5) |
| 11 | Business verification of the client's portfolio. It raises the 250 limit and unlocks OTP templates; India documents are typically GST, COI or a utility bill. | **Client** in Meta Business Settings | No for us. Partner-led verification exists, but "is currently only available to approved **Select Solution** and **Premier** Solution Partners". | `wa-docs/messaging-limits.md`; `solution-providers/partner-led-business-verification.md`; ThinnestAI `meta/verification.md` (India documents, VENDOR-PUBLISHED) |
| 12 | Display name review. "You can change a display name 10 times per 30-day period"; an approved name must be re-registered within 14 days. | Meta reviews; client or Calevate can submit | Yes, by API | `wa-docs/display-names.md` |

**Can we do it without the client ever logging in to Facebook? No.** Steps 1, 2, 4 and 10 are
the client's by Meta's design. Step 10 happens in Meta Business, not in our product.

**Using the client's Calevate-rented number.** The flow accepts "one you have provided". Our
ThinnestAI numbers cannot take SMS. ThinnestAI states that Meta's verification **call** does
reach them, and that its own agent can answer that call and read the code back
(`channels/whatsapp.md:68-101`, VENDOR-PUBLISHED). Doing the same on our side is not built. It
is **UNKNOWN** whether ThinnestAI's auto-read would act on a number in a customer workspace
whose WhatsApp is connected through *our* app.

### 3.3 Messaging limits a new client starts with (VERIFIED-VENDOR-DOCS, `wa-docs/messaging-limits.md`)

- "Newly created business portfolios have a messaging limit of 250." The tiers then go
  2,000, 10,000, 100,000, unlimited.
- The limit applies to the business portfolio and is shared by all its numbers.
- To reach 2,000, the client either verifies their business or sends 2,000 delivered
  messages outside customer-service windows within 30 days.
- After that, scaling is automatic "within 6 hours".

For an SMB voice agent sending a few confirmations a day, 250 unique recipients in 24 hours
is not a constraint.

---

## 4. Scenario B: a client who uses the WhatsApp Business app on that number (Coexistence)

All of the following is VERIFIED-VENDOR-DOCS from `wa-docs/embedded-signup/onboarding-business-app-users.md`.

- **Requirements:**
  - "WhatsApp Business app version 2.24.17 or higher";
  - we must be a Tech Provider or Solution Partner;
  - Embedded Signup with session logging;
  - a webhook receiver.
- **Sync:**
  - contacts with a WhatsApp number;
  - chat messages from the most recent 6 months, delivered as `history` webhooks within 180
    days, with media ids only for the last 14 days;
  - group chats are not synced.
  - "you have 24 hours to synchronize their messaging history, otherwise they must be
    offboarded."
- **Limits:**
  - Fixed throughput: "a fixed throughput of 20 mps".
  - Disappearing messages and view-once are turned off for 1:1 chats.
  - Live location is disabled.
  - Broadcast lists are disabled ("Existing Broadcast lists will become read-only").
  - "Group chats, voice and video calls, and business tools are not supported" on the API
    side.
  - 1:1 messages are mirrored between app and API.
- **Pricing:** "messages sent by the business via the WhatsApp Business app will continue to
  be free"; Cloud API sends are charged normally.
- **Inactivity:** after about 14 days with the primary device inactive (about 30 for a
  companion device) the number is disconnected. We receive `account_update` with
  `PARTNER_REMOVED`.
- **Webhooks:** the business's app-sent messages arrive as `smb_message_echoes`, and Meta says
  "You must display these in your app's message thread". Contact changes arrive as
  `smb_app_state_sync`.

**Availability in India: UNKNOWN.** Meta's page names no countries. The REPORTED sources
disagree:

- 360dialog's undated guide lists India as unsupported.
- Chakra (a seller of the feature) says India was in the May 2025 beta and that "all
  countries" are supported as of June 2026.

ThinnestAI's docs also disagree with each other. `channels/whatsapp.md:109` says the number
"cannot already be active on WhatsApp or the WhatsApp Business app". `:335` says "If your
number also runs on the WhatsApp Business app, change the name in the app". **The first real
onboarding attempt closes this.**

**What it means for us.** Coexistence is the right default for the typical owner, who already
answers customers on the Business app. But it brings obligations we do not have today:

- an inbound-message receiver;
- a 24-hour history sync window;
- Meta's "must display" requirement for echoes, which implies an inbox we have not built and
  which the founder has never asked for.

If we onboard Coexistence numbers only to send templates, the obligation to "display" echoes
is a policy question. **UNKNOWN whether a send-only integration may ignore them.**

---

## 5. Scenario C: a client already on the API, through a BSP or directly

| Option | How | What Meta or the BSP says | Fit for a non-technical owner |
|---|---|---|---|
| **(a) Grant our app access to their existing WABA** | Embedded Signup with the `app_only_install` feature. Returns `FINISH_GRANT_ONLY_API_ACCESS` with `phone_number_id`, `waba_id` and `business_id`, plus an `account_update` `PARTNER_APP_INSTALLED` webhook. The business token is fetched via the System User Access Tokens API with `fetch_only=true`. | VERIFIED-VENDOR-DOCS, `embedded-signup/app-only-install.md`. That page uses `extras.version: v3`, so whether it works in v4 is UNKNOWN. **UNKNOWN whether it works for a WABA held on a BSP's credit line**, and who is billed for our sends: the page does not cover billing or BSP-owned WABAs. Note: "Existing WABAs created via the developer app cannot be selected or onboarded directly through the Embedded Signup flow" (`overview.md`). | Good, if it works: the same one-button flow as scenario A |
| **(b) Call the BSP's own API with their BSP key** | The client pastes a key and names the template. This is what we build for AiSensy and Interakt. | See the per-BSP table below | Medium: the client must find a key and a template name |
| **(c) A system-user token they generate** | Business Settings > System Users > Add > assign the **app** with Manage app > Generate token with `business_management`, `whatsapp_business_management`, `whatsapp_business_messaging`, choosing an expiry | VERIFIED-VENDOR-DOCS, `wa-docs/access-tokens.md`. **It needs an app in their portfolio**, i.e. a Meta developer app of their own. A WABA owned through a BSP may not be assignable this way: UNKNOWN. | Poor. This is what our UI asks today ("A permanent system user token…"). Developer-level work. |
| **(d) Migrate the number to a WABA onboarded by us** | Client disables two-step verification > our Embedded Signup > we capture ids, subscribe webhooks and register | VERIFIED-VENDOR-DOCS, `solution-providers/support/migrating-phone-numbers-among-solution-partners-via-embedded-signup.md`. Display name, quality rating, messaging limit and OBA status are preserved. "Only templates with both a `status` of `APPROVED` and `quality_score` of `GREEN` are eligible for duplication." The client's portfolio must be **verified** and its display name approved. The step list includes "Share your credit line", a Solution Partner step, so its exact form for a Tech Provider is UNKNOWN. | Takes the client off their BSP, so they lose its inbox. Rarely wanted. |

### 5.1 Send-template APIs of the main BSPs

All VERIFIED-VENDOR-DOCS unless marked otherwise.

| BSP | Endpoint | Auth | Template referenced by | Notes / source |
|---|---|---|---|---|
| AiSensy | `POST https://backend.aisensy.com/campaign/t1/api/v2` | `apiKey` in the body ("manage > API Key") | **API campaign name**; the campaign must be Live | `templateParams` length must match. aisensy.com/tutorials/api-reference-docs |
| Interakt | `POST https://api.interakt.ai/v1/public/message/` | `Authorization: Basic <API key>` (Developer Settings) | Template **name** + `languageCode` | `bodyValues`, `headerValues`, `buttonValues`; 300 or 600 per minute by plan. interakt.shop/resource-center/how-to-send-whatsapp-templates-using-apis-webhooks |
| Gupshup | `POST https://api.gupshup.io/wa/api/v1/template/msg`, form-encoded | `Apikey` header | Template **id** (not name) + `params` | `source` is the registered number in E.164. docs.gupshup.io/docs/template-messages |
| WATI | `POST https://live-mt-server.wati.io/{tenant}/api/v2/sendTemplateMessage?whatsappNumber=…` | `Authorization: Bearer` (dashboard > API Docs) | `template_name` + `broadcast_name` + `parameters[{name,value}]` | **REPORTED** only (third-party mirrors; WATI's own reference URL returned 404) |
| 360dialog | `POST https://waba-v2.360dialog.io/messages`, Cloud API shape | Header not shown on the page read: UNKNOWN | Template **name**, Active only | docs.360dialog.com/docs/resources/templates/sending-template-messages |
| Twilio | `POST https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json` | API key and secret (Basic) | **ContentSid** (`HX…`), not name; `ContentVariables` | `From: whatsapp:+…`. twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates |
| Meta Cloud API direct | `POST https://graph.facebook.com/{v}/{phone-number-id}/messages` | Bearer business or system token | Template **name** + `language.code` | Already built (`apps/api/actions/whatsapp.py:206-260`) |

---

## 6. What Calevate must do once

| Step | Detail | Time stated by a source |
|---|---|---|
| Meta app with the WhatsApp use case, connected to Calevate's business portfolio | Prerequisite (`solution-providers/get-started-for-tech-providers.md`) | none stated |
| **Business verification of Calevate** | Name, address, phone, email, website; documents if Meta cannot find the business. "Your business must be verified before you can start the app review process." | Meta: none stated. ThinnestAI: "Days, occasionally longer" (VENDOR-PUBLISHED, `meta/verification.md`) |
| **App Review**, advanced access | `whatsapp_business_messaging` ("required to send messages on behalf of your clients") and `whatsapp_business_management` ("required to access your clients' WABAs"). Plus an app icon, privacy policy, category, and **two videos**: a message sent from our app arriving in WhatsApp, and our app creating a template. v4 may auto-select more permissions, each needing advanced access (`version-4`). | none stated |
| **Access Verification** | Named as the third condition for the 10 → 200 weekly onboarding limit (`embedded-signup/overview.md`). Its procedure was not read: UNKNOWN. | UNKNOWN |
| Facebook Login for Business configuration (Embedded Signup v4) | `config_id`; allowed domains `app.calevate.tech` (HTTPS) | none |
| Webhook endpoint with app-level subscriptions | See §8 | none |
| Tech Partner (optional, later) | ≥2,500 average daily messages or ≥200 average daily calls over 7 days, **10 or more active clients**, quality ≥90% (`solution-providers/upgrade-to-tech-partner.md`) | "will likely take a few weeks" (same page, about the approvals) |
| Meta terms | Meta Terms for WhatsApp Business Platform, "Last Modified: September 23, 2026" (facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform) | n/a |

---

## 7. Costs and who pays

- **Meta's per-message fee.** "Effective July 1, 2025, Meta charges on a per-message basis."
  Only templates are charged, by category and recipient country. Marketing is charged even
  inside a customer-service window. Utility inside an open window is free
  (`wa-docs/pricing.md`). Whether that changed on 1 Oct 2026 is UNKNOWN (§2, item 3).
- **Who pays Meta.** With Calevate as a Tech Provider, **the client pays Meta** on a card in
  their own Meta business portfolio. Without a working card, "Meta blocks the conversations
  you start: templates and broadcasts" (ThinnestAI `whatsapp/payment-method.md`,
  VENDOR-PUBLISHED; Meta's own Tech Provider page says the customer "must add a payment
  method"). For Calevate to pay, it would have to be a Solution Partner with a line of credit
  (`embedded-signup/overview.md`, Billing).
- **India currency deadline.** "Eligible customers must ensure all WABAs in their business
  portfolio are migrated to INR by December 31, 2026", and from 1 Jan 2027 "Meta will no
  longer deliver the messages of non-INR WABAs" of eligible customers (`wa-docs/pricing.md`).
  Eligibility is partners and directly-integrated clients whose Sold-To country is India; how
  that applies to a client onboarded by a Tech Provider is UNKNOWN. **New client WABAs should
  be created in INR.**
- **India rates.** UNKNOWN as primary-verified (§2, item 4). Meta's pricing page only says
  "India - Higher marketing rate" among the 1 Oct 2026 changes.
- **Calevate's own cost.** None per message under the Tech Provider model. We could mark up
  through our own invoice (`whatsapp_message_inr` already exists for absorbed sends). That is
  a founder decision.

---

## 8. Webhooks we need

Field names are VERIFIED-VENDOR-DOCS from `wa-docs/webhooks/overview.md`.

| Field | Why |
|---|---|
| `messages` | Delivery status of what we send (sent, delivered, read, failed), recorded on `action_invocations`. Inbound user messages also arrive here: we must ack them and store nothing we do not use. |
| `message_template_status_update` | Approval, rejection, pause or disable of the client's templates |
| `template_category_update` | A utility template recategorised as marketing. There is "a 1-day advance notice"; for warned businesses changes are instant (`templates/template-categorization.md`). This changes the price. |
| `message_template_quality_update` | Quality drops before a pause |
| `account_update` | `PARTNER_APP_INSTALLED`, `PARTNER_REMOVED`, offboarding, policy violations |
| `account_alerts` / `business_capability_update` | Messaging-limit and capability changes |
| `phone_number_name_update` | Display name review outcome |
| `phone_number_quality_update` / `security` | Throughput and two-step verification PIN changes |
| `history`, `smb_app_state_sync`, `smb_message_echoes` | Only if we accept Coexistence (§4) |
| `user_preferences` | A user's marketing-message preference. Feed it to the DNC/consent ledger. |

**Signature.** `X-Hub-Signature-256` HMAC over the raw body with the app secret. That is
already implemented for Lead Ads in `apps/api/ingest/meta.py`, whose docstring records that
the claim was then read via secondary sources. One Meta receiver should serve both
(BACKEND-PATTERNS: one way per problem).

**Per-WABA callback overrides** exist (`webhooks/overview.md`) but are not needed.

---

## 9. Policy constraints and risks

1. **Meta's AI-provider restriction does not reach us, on the text as read.** Section 4.7 of
   the Meta Terms for WhatsApp Business Platform says providers of AI technologies "are
   strictly prohibited from accessing or using the WhatsApp Business Platform, whether
   directly or indirectly" when "such technologies are the primary (rather than incidental or
   ancillary) functionality being made available" (facebook.com/legal/Meta-Terms-for-WhatsApp-Business-Platform,
   VERIFIED-VENDOR-DOCS). A voice agent sending a business's own transactional templates is
   incidental to that business's service. Meta decides "in its sole discretion", so this is
   our reading, not a ruling. The 15 Jan 2026 effective date is REPORTED (press coverage);
   the terms page states no separate date for §4.7.
2. **Opt-in.** "Businesses must clearly state the business's name that a person is opting in
   to receive messages from". Accepted channels include "By phone (using an interactive voice
   response (IVR) flow)" (`wa-docs/getting-opt-in.md`).
   - Whether a spoken yes to an AI voice agent counts as the IVR channel is UNKNOWN. It is a
     counsel question.
   - Today no consent is captured during a call (`compliance/consent.record_messaging_consent`
     is reached only from `consent_routes.py:185` and imports). So **in-call WhatsApp works
     only for callers the client already imported as opted in.** The F-8 note already says
     this for save-our-number.
3. **Automation needs an escalation path.** "You may use automation when responding during
   the 24-hour window" but with "prompt, clear, and direct escalation paths", for example a
   phone number (whatsappbusiness.com/policy, "Last updated: September 23, 2026").
   Template-only sending does not respond, but each template should carry the business's
   phone number.
4. **Impersonation.** "You may not use WhatsApp for Business to impersonate another business
   or entity" (same policy). Sending from Calevate's WABA while presenting as the client is
   out.
   - Sending as Calevate *about* the client, which is what `calevate_missed_call_follow_up_v1`
     does ("{{1}} tried to reach you"), is not addressed by any Meta page read. The consumer
     opted in to (at most) the client, not Calevate. **Risk: rejection or quality strikes.**
   - That display names for agencies must show an evident relationship is **REPORTED**
     (provider copies of Meta's Help Center article; the Meta article body did not load).
5. **Template category.** Utility must be "non-promotional" and "clearly related to their
   order, account, services, or transactions" (`templates/template-categorization.md`). A
   booking confirmation or payment link after a caller asked for one fits. A "thanks for
   calling, here is our offer" does not, and Meta re-categorises. ThinnestAI refuses
   marketing templates for after-call sends (`agent/after-the-call.md:69`, VENDOR-PUBLISHED).
6. **Per-user marketing caps** are adaptive, not a fixed number. Error 131049 means a send was
   withheld, with a 24-hour back-off advised (REPORTED via search summary of
   `wa-docs/templates/marketing-templates/per-user-limits.md`; the page itself was not opened
   this session). This is irrelevant if we send utility only.
7. **Token blast radius.** Business tokens are per client, which ThinnestAI and Meta both
   prefer over system tokens (`app-only-install.md`: "scopes access to the customer's assets
   rather than relying on system tokens"). Seal them like any tenant credential and never log
   them (hard rule 6).
8. **Two-step verification PIN.** Registering sets it. If we set it, the client needs it to
   ever migrate away. Migration requires two-step verification **disabled**, so we must be
   able to turn it off or hand it over.

---

## 10. India regulation

- **DLT / TCCCPR: REPORTED, not primary-verified.**
  - Stakeholder submissions to TRAI's 2024 consultation (NASSCOM, BIF, COAI, listed at
    trai.gov.in) and press on the Feb 2025 amendment all describe TCCCPR as covering
    commercial communication over *telecommunication services*, with OTT messaging such as
    WhatsApp outside it. COAI objected to that exclusion.
  - The TRAI PDFs returned 404 to this session, and the regulation text was not read.
  - Our own position, "Not DLT/TCCCPR", is in `docs/legal/LEGAL-OPS-PLAYBOOK.md:431-433` and
    `apps/api/actions/whatsapp.py:24-26`, and is itself unsourced.
  - **Status: UNKNOWN at primary level; route to counsel with gate A-9.**
- **DPDP.** The caller's number and template variables reach Meta under the client's
  instruction. A-9 already asks counsel whether naming the client's own processors (Meta,
  AiSensy, Interakt) outside our sub-processor list is sufficient. Purpose limitation means
  the WhatsApp opt-in is a separate consent from the call, which is how `messaging` consent is
  modelled. Nothing new is needed beyond A-9 and the in-call opt-in question in §9.2.

---

## 11. Gap table: today versus a self-serve onboarding

| # | Gap | Today (file:line) | Needed |
|---|---|---|---|
| G-1 | No Meta Tech Provider standing | none | Meta app, business verification, App Review (2 permissions, 2 videos), Access Verification (§6) |
| G-2 | Client must find and paste a system-user token and a phone number id | `ConnectedAccounts.tsx:74-77`; `KindFields.tsx:314-321` | "Connect WhatsApp" button running Embedded Signup v4; ids come back from Meta |
| G-3 | No code exchange, register, subscribe or token storage for a business token | none | Server route that exchanges within 30 s, seals the token in `tenant_credentials` (kind `meta_cloud`, `non_secret` = waba_id, phone_number_id, business_id), subscribes, registers |
| G-4 | Templates are typed by name and never checked | `apps/api/actions/whatsapp.py:33-37`; `schema.py:151-155` | List templates via `GET /<WABA>/message_templates`; Calevate-authored utility templates created by API in te, hi and en; status shown |
| G-5 | No WhatsApp webhooks | `apps/api/ingest/meta.py` (Lead Ads only) | One Meta receiver, with the fields in §8 |
| G-6 | No payment-method or account-health check | none | Read account status and alarm on blocked sending. The exact Graph field is UNKNOWN; ThinnestAI surfaces it (`channels/whatsapp.md:231-250`). |
| G-7 | No in-call opt-in capture | consent written only by `compliance/consent_routes.py:185` | Founder and counsel decision (§9.2); if yes, an engine action recording `messaging` consent with the call id |
| G-8 | AiSensy `userName` = "Calevate" | `apps/api/actions/whatsapp.py:201` | Caller's name or number |
| G-9 | Gupshup, WATI, Twilio, 360dialog not supported except through "custom" REST | `models.py:85-91` | Only on client demand (decision 4) |
| G-10 | Calevate-WABA templates name the client | `apps/workers/whatsapp.py:811-827` | Decision 6 |
| G-11 | Pricing comment conflicts with Meta's page | `apps/workers/whatsapp_cloud.py` (D-91 docstring) | Re-read Meta's 1 Oct 2026 rate card; correct the comment |

---

## 12. Recommended design

### 12.1 Backend

1. **Settings, set in the ops console:**
   - `meta_app_id`;
   - `meta_app_secret`, in the platform secret store and already needed by Lead Ads;
   - `whatsapp_es_config_id`;
   - `meta_graph_version`, defaulting to the documented `v25.0` (as
     `actions/whatsapp.META_GRAPH_VERSION`).
2. **`POST /v1/actions/whatsapp/connect`** (owner only, client realm, view-as refused, as for
   `integrations.connect`). It takes `{code, waba_id, phone_number_id, business_id, event}`
   from the popup and then:
   - exchanges the code immediately, since its TTL is 30 s;
   - seals the token with `actions/credentials.create_credential`, kind `meta_cloud`;
   - subscribes the app to the WABA's webhooks;
   - registers the number with a random 6-digit PIN (shown once to the owner, never stored,
     the same choice ThinnestAI made at `channels/whatsapp.md:273-279`);
   - submits the standard templates;
   - returns a checklist.

   For `FINISH_WHATSAPP_BUSINESS_APP_ONBOARDING` (Coexistence), skip register. Whether
   register applies to Coexistence is UNKNOWN; verify on the first attempt. Each step is an
   idempotent outbox job, so a half-done connect resumes rather than repeats
   (BACKEND-PATTERNS reliability triad).
3. **The send path is unchanged.** `build_meta_cloud` already sends the Cloud API template
   shape. The phone number id moves from the action form to the credential's `non_secret`.
4. **Webhooks.** Extend `apps/api/ingest/meta.py` to `object: whatsapp_business_account`.
   - Verify the signature once.
   - Route `messages.statuses` to the invocation's delivery state (ids only; hard rule 6).
   - Route template, category and account fields to the attention feed and alarms
     (`whatsapp_template_rejected`, `whatsapp_template_recategorised`,
     `whatsapp_sending_blocked`, `whatsapp_disconnected`).
   - Inbound `messages` bodies are dropped after ack unless the founder chooses an inbox.
5. **Tokens.** These are business tokens, with no expiry stated by Meta. Disconnect revokes
   locally and asks the owner to remove the app in Meta Business Suite (`app-only-install.md`).

### 12.2 UI copy for a non-technical owner

Integrations > Connected accounts > WhatsApp. D-679 already prints "Meta Lead Ads and
WhatsApp" as services a client connects itself (ROADMAP D-679), so **no new carve-out is
needed** to say WhatsApp, Meta and Facebook.

- **Card:** "Send WhatsApp messages from your own business number. Your agent can send a
  booking confirmation or a payment link while the caller is still on the line."
- **Button:** "Connect WhatsApp". Before the popup:
  > "Meta (the company behind WhatsApp and Facebook) will open a window. Sign in with the
  > Facebook account that manages your business, choose your business, and enter the number
  > you want to send from. Meta will send that number a 6-digit code."
- **Three choices before the popup:**
  - "I'm new to WhatsApp Business"
  - "I use the WhatsApp Business app on my phone and want to keep using it": only shown if
    Coexistence is confirmed for India
  - "I already use WhatsApp through another company": app-only install first; the
    paste-a-key fallback is behind "Use a key instead"
- **After connect, a checklist checked against Meta:**
  - "Add a card in Meta so WhatsApp can charge you for messages (Meta bills you directly; we
    do not)"
  - "Verify your business with Meta (optional, raises how many people you can message a day)"
  - "Your business name is approved"
  - "Message templates approved"
- **Action form:** a template dropdown of approved templates with their blanks, replacing
  the free-text template name and phone number id.

---

## 13. Decisions for the founder

1. **Become a Meta Tech Provider and host Embedded Signup?**
   - Options: (a) yes; (b) keep paste-a-key only; (c) use ThinnestAI's WhatsApp channel
     instead.
   - **Recommend (a).** (b) leaves every client without a BSP stuck at the system-user-token
     step. (c) has no API connect path for customer workspaces
     (`connect-telegram-bot.md:50-53`) and would put the client in a vendor console against
     D-679.
   - Ask ThinnestAI in the pending email (§13 of `docs/vendor/thinnest-replies-2026-10-12.md`)
     whether a hosted connect link for customer workspaces exists, before ruling (c) out
     finally.
2. **Who pays Meta?**
   - Options: (a) the client's own card in Meta (the Tech Provider model); (b) Calevate pays,
     which needs Solution Partner status and a credit line.
   - **Recommend (a).** It is the only model a Tech Provider can run.
3. **Offer Coexistence for business-app users?**
   - Options: (a) yes, send-only; (b) yes, with an inbox; (c) no, and ask them to use another
     number.
   - **Recommend (a) once India availability is confirmed on the first attempt**, with the
     echo-display obligation put to Meta support first. If it is refused, (c).
4. **Existing BSP users.**
   - Options: (a) try app-only install first, keeping AiSensy and Interakt keys as fallback;
     (b) keys only; (c) add Gupshup, WATI and Twilio adapters now.
   - **Recommend (a)**, adding a BSP adapter only when a paying client asks (Gupshup needs a
     template *id*, Twilio a ContentSid).
5. **In-call WhatsApp opt-in.**
   - Options: (a) the agent asks "May <business> send you this on WhatsApp?" and records
     `messaging` consent tied to the call; (b) imported consent only, as today.
   - **Recommend (a), subject to counsel** (Meta lists IVR phone opt-in; an AI voice is not
     named). Without it, in-call sends are refused for almost every caller.
6. **Calevate's own WABA sending messages that name the client** (missed-call follow-up,
   save-our-number).
   - Options: (a) keep; (b) send from the client's WABA when connected, falling back to
     Calevate's with wording "Calevate, on behalf of {{1}}"; (c) drop when the client has no
     WABA.
   - **Recommend (b).**
7. **Templates.**
   - Options: (a) Calevate-authored utility templates (booking confirmed, payment link,
     directions or info link) created by API in te, hi and en in every connected WABA;
     (b) the client writes their own.
   - **Recommend (a) plus (b) for advanced users.** Utility only for in-call sends.
8. **Use the client's Calevate number for WhatsApp too.**
   - Options: (a) allow, verified by Meta's voice call (we would need to read the code: not
     built); (b) require a SIM mobile number.
   - **Recommend (b) first.** (a) is a later convenience.
9. **Mark-up.** Options: (a) none, since the client pays Meta directly; (b) a per-message
   platform fee as ThinnestAI does (10%, `whatsapp/payment-method.md`).
   **Recommend (a)** at launch.

---

## 14. UNKNOWNs

1. Coexistence availability for Indian numbers, and whether a send-only integration may
   ignore `smb_message_echoes`.
2. Whether app-only install works for a WABA held through an Indian BSP (on its credit line),
   and who is billed for our sends.
3. Whether app-only install works under v4 (the page shows `extras.version: v3`).
4. The Access Verification procedure and duration; Business Verification and App Review
   durations (Meta states none).
5. Meta India INR rates in force (rate card effective 1 Jul 2026; the figures were not
   readable). Whether in-window utility became chargeable on 1 Oct 2026 (Meta's page says
   free; ThinnestAI and our code say not after 1 Oct).
6. Whether Embedded Signup can be completed with Meta Business credentials and no Facebook
   account.
7. TCCCPR/DLT non-applicability to WhatsApp at primary level (TRAI text not read).
8. Whether an AI voice agent's spoken question is a valid Meta phone opt-in.
9. The Graph field that reports the payment-method or "can send" status of a client's WABA.
10. Whether the register step applies to Coexistence numbers.
11. WATI's send API on WATI's own pages (only REPORTED copies were read); 360dialog's auth
    header.
12. ThinnestAI: whether a customer workspace can connect WhatsApp without the console, and
    the contradiction between `customers.md:233-234` ("a person you invite into it") and
    `:238` ("Your customers have no members of their own").
