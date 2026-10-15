# Clients' WhatsApp through Meta: what the founder sets up (D-784)

Calevate becomes a Meta **Tech Provider** so a client can connect their own WhatsApp from
the Integrations screen by signing in to Facebook in Meta's own window. Until the steps
below are done, the client's WhatsApp screen offers only the paste-a-key guides (AiSensy,
Interakt, a Meta token). Nothing in our code needs to change when you finish: the screen
switches itself on once the four values in step 7 are saved.

Every Meta quote below was read on Meta's own pages on **15 Oct 2026**. Relative paths are
under `https://developers.facebook.com/documentation/business-messaging/whatsapp/`.
Durations are given only where Meta states one.

**Have ready before you start**

- Admin access to Calevate's Meta business portfolio (business.facebook.com) and a Facebook
  login with two-factor authentication on.
- The registration documents Meta may ask for in business verification.
- A phone with WhatsApp, and a second mobile number with its own SIM for the test client in
  step 8 (not a number already on WhatsApp).
- Access to the ops console (`admin.calevate.tech`) as an administrator.

The gates these steps close are OPERATIONS §2 **W-1 to W-4**; W-5 to W-8 are listed at the
end.

---

## 1. Create the Meta app with the WhatsApp use case

1. Go to developers.facebook.com > My Apps > **Create app**. Choose the use case for
   connecting with customers through WhatsApp and connect the app to Calevate's business
   portfolio. Meta's prerequisite: "a Meta app with the WhatsApp use case and a connected
   business portfolio" (`solution-providers/get-started-for-tech-providers.md`).
2. In the App Dashboard, open **Use cases > Customize** and select **Tech Provider
   onboarding** (same page).
3. Under **App settings > Basic**, fill in the app icon, **Privacy policy URL**
   `https://calevate.tech/legal/privacy`, **Terms of service URL**
   `https://calevate.tech/legal/terms`, and the category. App review needs these
   (`solution-providers/app-review.md`).
4. Copy the **App ID**. Under **App settings > Basic > App secret**, press Show and copy it.
   Keep both for step 7. The app secret is a password: paste it only into our console.

## 2. Verify Calevate's business (gate W-1)

Business Settings > **Security Centre** > Start verification. Give the legal name, address,
phone, email and website exactly as on the documents.

- Meta: "Your business must be verified before you can start the app review process"
  (`solution-providers/get-started-for-tech-providers.md`).
- Meta states no duration.
- **If Meta refuses:** the refusal names the field that did not match. Correct it to match
  the document exactly (spelling, address format, website on the same domain as the email)
  and resubmit. Do not upload a different document type unless asked.

## 3. Set up Embedded Signup (Facebook Login for Business)

From `embedded-signup/implementation.md`:

1. App Dashboard > **Facebook Login for Business > Settings > Client OAuth settings**.
   Turn on: Client OAuth login, Web OAuth login, Enforce HTTPS, Embedded Browser OAuth
   Login, Use Strict Mode for redirect URIs, and **Login with the JavaScript SDK**.
2. Add `https://app.calevate.tech` to **Allowed domains** and to
   **Valid OAuth redirect URIs**. Meta accepts HTTPS only.
3. **Facebook Login for Business > Configurations > Create configuration**. Choose the
   **WhatsApp Embedded Signup** login variation (or create it from Meta's template). Meta
   picks the permissions for you; "You will need advanced access for all permissions
   automatically selected in the flow" (`embedded-signup/version-4`, quoted in the research
   doc).
4. Copy the **Configuration ID**.

We launch the window exactly as Meta documents: the SDK from
`https://connect.facebook.net/en_US/sdk.js`, `FB.login` with `config_id`,
`response_type: 'code'`, `override_default_response_type: true` and
`extras: { setup: {} }`. Meta: "Embedded signup v2 will be deprecated on October 15, 2026";
we use v4 only.

## 4. App review: two permissions, two recordings (gate W-2)

App Dashboard > **App review > Permissions and features**. Request **advanced access** for:

- `whatsapp_business_messaging` — "required to send messages on behalf of your clients";
- `whatsapp_business_management` — "required to access your clients' WABAs"
  (research doc §6; `solution-providers/app-review.md`).

Meta: "You must submit a different video clip for each permission", a written explanation
is required, "you cannot submit a screenshot", and review takes "about 24 hours"
(`solution-providers/app-review.md`). If our own screens cannot be recorded yet because
nothing is approved, Meta also accepts the recording from WhatsApp Manager or the App
Dashboard's API Setup page (`solution-providers/get-started-for-tech-providers.md`).

Before recording, connect Calevate's own test WhatsApp account to a test client in our
console (step 8), so the screens below have something to show.

### Recording 1 — `whatsapp_business_messaging`

Meta asks for "a video showing your app being used to send a message to a WhatsApp number,
and the WhatsApp client (either web or mobile app) receiving and displaying the sent
message". Script, about 60 seconds, screen and phone both visible:

1. Show `app.calevate.tech` signed in to the test client. Say: "This is Calevate. Our
   customers' AI phone agents send WhatsApp messages from the customer's own WhatsApp
   Business number."
2. Open **Integrations**. Point at WhatsApp: connected, with the business number and name.
3. Open **Agents > (the agent) > Actions > Send a WhatsApp message**. Show the template
   chosen from the list of approved templates.
4. Press **Test**, type the business's own mobile number, send.
5. Cut to the phone (or WhatsApp Web) and show the message arriving from the business's
   display name.
6. Say: "During a real call, the agent first asks the caller 'Shall I send this on WhatsApp
   to this number?' and sends only after they say yes."

Written explanation to paste: *"Calevate is a voice-agent platform for small businesses in
India. Each business connects its own WhatsApp Business account through Embedded Signup.
During or after a phone call, when the caller asks for a booking confirmation, details or a
payment link and agrees to receive it on WhatsApp, Calevate sends the business's approved
utility template from the business's own number using this permission. We never send from
our own account on a business's behalf."*

### Recording 2 — `whatsapp_business_management`

Meta asks for "a video of your app, or WhatsApp Manager, being used to create a message
template". Script, about 60 seconds:

1. Show `app.calevate.tech` > **Integrations > WhatsApp > Message templates**. Point at the
   four Calevate templates in Telugu, Hindi and English and their status.
2. Press **Add a template**. Name `order_ready`, category Utility, language English, body
   "Your order from Lakshmi Traders is ready for pickup, {{1}}. Thank you." with the
   example "Ravi". Show the preview, then **Send to Meta for review**.
3. Show the new template listed as **Waiting for Meta**.
4. Cut to WhatsApp Manager > Message templates and show the same template there, In review.

Written explanation: *"When a business connects its WhatsApp Business account, Calevate
subscribes to its webhooks, registers its phone number and creates standard utility
templates (booking confirmation, requested details, payment link, call-back time) in
Telugu, Hindi and English. The business can also write its own templates in Calevate. We
use this permission to create templates, read their review status and the account's
quality rating, and receive account and template webhooks."*

**If Meta refuses:** the notice names the permission and the reason. The common ones are a
recording that does not show the message arriving in WhatsApp, or a privacy policy URL that
does not load. Fix exactly that and resubmit the one permission.

## 5. Access verification (gate W-3)

App Dashboard > **Basics > Verifications > Access verification**
(`https://developers.facebook.com/documentation/development/release/access-verification.md`).

- Meta: "Access verification is the process we use to determine if a business operates as a
  Tech Provider." Describe how Calevate uses other businesses' data to provide a service to
  them (the written explanations above work).
- Prerequisite: business verification done.
- Meta: "a decision will be made within approximately 5 days."
- **Why it matters:** "By default, you can onboard up to 10 new business customers in a
  rolling 7-day window." After business verification, app review **and** access
  verification, "your limit is automatically increased to 200"
  (`embedded-signup/overview.md`). WhatsApp Manager > Partner overview shows Meta's own count.

When it is approved, set **New WhatsApp clients per 7 days** to `200` in our console
(step 7). Admin > WhatsApp shows our count against it, and an alarm
(`whatsapp_onboarding_limit_near`) fires at 80%.

## 6. Webhooks

1. Make a verify token: 32 or more random characters (for example from a password manager).
   Save it in our console first (step 7), so the handshake can succeed.
2. App Dashboard > **WhatsApp > Configuration** (for an app created with the use case:
   **Use cases > Customize > Configuration**) (`webhooks/create-webhook-endpoint.md`).
   - **Callback URL:** `https://api.calevate.tech/hooks/v1/meta/whatsapp`
     — **`api.`, not `hooks.`**: `hooks.calevate.tech` goes to the voice runtime, which has
     no Meta route, so Meta's handshake would fail there.
   - **Verify token:** the one from step 6.1. Press **Verify and save**. Our endpoint answers
     only when the token matches.
3. Subscribe to these fields: `messages`, `message_template_status_update`,
   `template_category_update`, `message_template_quality_update`, `account_update`,
   `account_alerts`, `business_capability_update`, `phone_number_quality_update`,
   `phone_number_name_update`, `security`. Do **not** subscribe the coexistence fields (history,
   app state sync and message echoes) while coexistence is off (gate W-6).
   Embedded Signup also needs the `account_update` subscription
   (`embedded-signup/implementation.md`).

Every delivery is signed: "HMAC-SHA256 hash, calculated using the post body payload and your
app secret as the secret key" (`webhooks/create-webhook-endpoint.md`). If the app secret in
our console does not match Meta's, every delivery is refused and
`whatsapp_webhook_signature_rejected` fills Admin > Alerts.

## 7. Paste the values into our console

Admin console (`admin.calevate.tech`) > **Ops > Config > Integrations > Clients' WhatsApp
(Meta Embedded Signup)**:

| Setting | Value |
|---|---|
| Meta app ID | from step 1.4 |
| Embedded Signup configuration ID | from step 3.4 |
| New WhatsApp clients per 7 days | `10` until step 5 is approved, then `200` |
| Offer WhatsApp Business app users coexistence | **off** (gate W-6) |

Admin console > **Ops > Secrets** (sealed; only the last four characters are ever shown):

| Secret | Value |
|---|---|
| `meta_app_secret` | the app secret from step 1.4 |
| `whatsapp_webhook_verify_token` | the token from step 6.1 |

All six take effect on the next request; no deploy.

## 8. First connection, end to end (gate W-4)

1. In a test client account on `app.calevate.tech`, open **Integrations > WhatsApp** and
   press **Connect WhatsApp** with "I'm new to WhatsApp Business".
2. In Meta's window: sign in, create or choose the business, enter the second SIM's number,
   type the 6-digit code Meta sends, choose a display name.
3. Back on our screen: note the **two-step verification PIN** shown once. Store it in the
   client's password manager; Calevate does not keep it, and "There is no endpoint to disable
   two-step verification" (`business-phone-numbers/two-step-verification.md`).
4. In WhatsApp Manager > Overview, **Add payment method**: "Once your customer adds a payment
   method, they are fully onboarded" (`embedded-signup/onboarding-customers-as-a-tech-
   provider.md`, step 5).
5. Admin > WhatsApp should show the account **Connected**, 12 templates submitted, and
   "Last heard from Meta" within a few minutes. Templates are reviewed in "up to 24 hours"
   (`templates/template-review.md`).
6. When a template is approved, set up **Send a WhatsApp message** on the test agent with it
   and press **Test** to your own number. It should arrive.

Record the date in OPERATIONS §2 W-4.

---

## Open items, each a gate

- **W-5** — granting an EXISTING WhatsApp account (a client on AiSensy or Interakt): Meta
  documents app-only install only for v3. Until the first client proves it, those clients
  use the key guides on the same screen.
- **W-6** — coexistence (keep the WhatsApp Business app on the same number): India
  availability is not stated by Meta, and Meta requires app-sent messages to be shown in our
  app. Ask Meta support both questions in writing before turning the switch on.
- **W-7** — a Telugu and a Hindi speaker read the standard templates
  (`apps/api/whatsapp/templates.py`) before the first paying client connects.
- **W-8** — counsel on the in-call spoken opt-in.

## When something goes wrong later

| What you see | What it means | What to do |
|---|---|---|
| `whatsapp_account_restricted` | Meta removed our app, restricted the account, or rejected the client's business verification. | The client fixes it in Meta Business Suite; if our app was removed, they reconnect. |
| `whatsapp_message_not_delivered` | Meta reported a message from the client's number failed, with Meta's error code. | Look the code up in Meta's error-code list. If the client never added a payment method (step 8.4), that is the first thing to check: Meta requires one before a client is "fully onboarded". |
| `whatsapp_template_not_usable` | Meta rejected or paused a template. | Reword and resubmit from the client's WhatsApp screen. |
| `whatsapp_onboarding_limit_near` | 80% of this week's new connections used. | Finish step 5, then raise the limit. |
