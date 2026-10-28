# Rename map, part 2: everything a person reads or sees

Companion to `docs/REBRAND-MAP.md`. Taken at commit `6ef0c49e` (29 Oct 2026) with `git grep`
and by reading the files. Comments are left out; internal identifiers that nobody sees
(variable names, storage keys, `owner: "calevate"`, cookie names, header names) are listed
separately in §9 so they are not mistaken for visible text.

**Placeholders used in the "replace with" column**

| Token | Means |
|---|---|
| NAME | the new product name, as written |
| NAME's | its possessive |
| DOMAIN | the new apex domain (hosts `app.`, `admin.`, `api.`, `hooks.`, `status.`) |
| ENTITY | the enterprise name on the new Udyam certificate |
| UDYAM | the new Udyam registration number |
| FORM | the new legal form (sole proprietorship, LLP, company, ...) |
| CITY / STATE | the city and state to publish (no street, no PIN) |
| GST | the new GST position |
| MAIL_* | the new mailboxes (support, grievance, DPO, security, ops, alerts) |
| TAGLINE | the tagline under the logo (today "AI voice calling agents") |
| SLUG | the URL slug for the brand-named route (today `why-calevate`) |

---

## 1. Web app: page metadata, SEO and icons

| file:line | current text | replace with |
|---|---|---|
| apps/web/src/app/layout.tsx:113 | `title: "Calevate"` (fallback title for consoles and auth screens) | NAME |
| apps/web/src/lib/seo/metadata.ts:42 | `SITE_NAME = "Calevate"` (og:site_name, WebSite JSON-LD) | NAME |
| apps/web/src/lib/seo/metadata.ts:59 | `OG_IMAGE_ALT = "Calevate: AI phone agents for Indian businesses"` | NAME |
| apps/web/src/app/opengraph-image.tsx:98 | share card renders the word `Calevate` as text | NAME (the card is generated, not a file; also uses brand colours) |
| apps/web/src/lib/seo/structuredData.ts:100 | `SITE_DESCRIPTION` "Calevate answers your calls, follows up..." | NAME |
| apps/web/src/lib/seo/structuredData.ts:110 | Organization `logo` = `/brand/calevate-full-logo-without-tagline.png` | new logo file path |
| apps/web/src/lib/seo/structuredData.ts (organizationJsonLd) | `legalName`, `address`, Udyam `identifier`, telephone, email read from `placeholders.ts` | follows ENTITY, CITY, UDYAM, MAIL_SUPPORT automatically |
| apps/web/src/lib/site.ts:48 | `SITE_ORIGIN = "https://calevate.tech"` (canonical, sitemap, robots, metadataBase) | DOMAIN |
| apps/web/src/lib/site.ts:110-111 | route `/why-calevate`, nav label "Why Calevate" | `/SLUG`, "Why NAME" |
| apps/web/src/lib/site.ts:160 | "the public status page, also served on status.calevate.tech" | DOMAIN |
| apps/web/src/app/robots.ts, sitemap.ts | no literal; read `site.ts` | follows SITE_ORIGIN |
| (no `manifest.ts` / `manifest.webmanifest` exists) | none | nothing to change |
| apps/web/src/app/favicon.ico, icon.png, apple-icon.png | the mark only, no name | see §7 (new artwork only if the mark changes) |

Per-page titles and descriptions (each public page sets its own):

| file:line | current text | replace with |
|---|---|---|
| apps/web/src/app/page.tsx:33 | "Calevate — AI phone agents for Indian businesses" | NAME |
| apps/web/src/app/industries/page.tsx:47, :49 | "Industries — Calevate"; "What a Calevate agent asks..." | NAME |
| apps/web/src/app/legal/page.tsx:29, :31 | "Legal — Calevate"; "Calevate's privacy policy, terms..." | NAME |
| apps/web/src/app/legal/[slug]/page.tsx:49, :52 | "Not found — Calevate"; `${doc.title} — Calevate` | NAME |
| apps/web/src/app/pricing/page.tsx:79, :81 | "Pricing — Calevate"; "How Calevate is billed..." | NAME |
| apps/web/src/app/resources/page.tsx:50, :53 | "Resources — Calevate"; "...glossary of the words Calevate uses." | NAME |
| apps/web/src/app/roi/page.tsx:76, :78 | "ROI — Calevate"; "Compare Calevate against hiring telecallers..." | NAME |
| apps/web/src/app/security/page.tsx:81, :83 | "Security & compliance — Calevate"; "What Calevate enforces..." | NAME |
| apps/web/src/app/signup/layout.tsx:27, :33 | "Get started — Calevate"; "How a business gets a Calevate workspace..." | NAME |
| apps/web/src/app/solutions/page.tsx:84, :86 | "Solutions — Calevate"; "The six jobs a Calevate agent does..." | NAME |
| apps/web/src/app/status/page.tsx:16, :18 | "Service status — Calevate"; "Whether Calevate's phone calls..." | NAME |
| apps/web/src/app/why-calevate/page.tsx:34, :35 | path `/why-calevate`; "Why Calevate — Calevate" | `/SLUG`; NAME |

## 2. Web app: marketing pages

**The route `apps/web/src/app/why-calevate/` is named after the brand.** Renaming it means:
moving the folder, `site.ts:110`, the links at `resources/page.tsx:73`, `roi/page.tsx:238`,
`solutions/page.tsx:450`, and the tests that import or list it (`apps/web/tests/a11y.test.tsx:121,3811`,
`heroEntrance.test.tsx:7`, `marketingPages.test.tsx:10,75`, `seo.test.ts:17,51`,
`publicLanding.test.tsx:161`, `publicVendorNames.test.ts:78`, `internalReferencesGuard.test.ts:47`,
`voiceChoiceIsTheClients.test.ts:61`). Add a redirect from `/why-calevate` to the new path so
shared links keep working. No reference in `infra/` or `scripts/`.

| file:line | current text | replace with |
|---|---|---|
| apps/web/src/app/why-calevate/page.tsx:130 | label "Why Calevate" | NAME |
| apps/web/src/app/why-calevate/page.tsx:183 | "Calevate is not your salesperson. It is the layer..." | NAME |
| apps/web/src/app/why-calevate/page.tsx:184 | lede "...Calevate is the first half..." | NAME |
| apps/web/src/app/legal/page.tsx:53-54 | "Calevate supplies AI telephone agents...whether you buy Calevate," | NAME |
| apps/web/src/app/resources/page.tsx:329 | "...whether you buy Calevate, work for a business that does..." | NAME |
| apps/web/src/app/roi/page.tsx:112 | output label "Calevate, a month" | NAME |
| apps/web/src/app/roi/page.tsx:244 | "The figure this tool uses for Calevate is our published list rate" | NAME |
| apps/web/src/app/security/page.tsx:258 | "...Calevate's" (staff access sentence) | NAME's |
| apps/web/src/app/security/page.tsx:318 | "...whether you buy Calevate, work for a business..." | NAME |
| apps/web/src/app/solutions/page.tsx:271 | "Your leads don't get trapped inside Calevate" | NAME |
| apps/web/src/app/solutions/page.tsx:451 | link text "why Calevate" | NAME |
| apps/web/src/app/signup/page.tsx:179 | "Calevate does not open accounts online yet..." | NAME |
| apps/web/src/app/signup/page.tsx:385 | "Create your Calevate workspace" | NAME |
| apps/web/src/app/signup/page.tsx:388 | "This creates the workspace for the Calevate account..." | NAME |
| apps/web/src/components/marketing/pageShell.tsx:281 | footer "Calevate — AI phone agents for Indian businesses." | NAME |
| apps/web/src/components/marketing/faq.tsx:125 | "Calevate's own staff can also see your account..." | NAME's |
| apps/web/src/components/marketing/home/hero.tsx:89 | "Calevate answers your calls, follows up..." | NAME |
| apps/web/src/components/marketing/home/closing.tsx:122 | "Calevate does not open accounts online..." | NAME |
| apps/web/src/components/marketing/home/problemAndPromise.tsx:104 | "Calevate handles the first layer of phone work..." | NAME |
| apps/web/src/components/marketing/home/teamReceives.tsx:87 | "Calevate is not your salesperson..." | NAME |
| apps/web/src/components/marketing/home/whatItDoes.tsx:103 | "Your leads don't get trapped inside Calevate" | NAME |
| apps/web/src/components/marketing/home/mockups/leadsWorkspace.tsx:41 | mockup timeline `by: "Calevate"` | NAME |
| apps/web/src/components/marketing/solutions/solutionMockups.tsx:391 | "Sent as X-Calevate-Signature" | follows the header rename decision (§9) |
| apps/web/src/components/marketing/roiCalculator.tsx:305, :310 | "Calevate answers the calls"; "Calevate calls first, your team closes" | NAME |
| apps/web/src/components/marketing/roiCalculator.tsx:445 | "...per-minute figure to price Calevate at" | NAME |
| apps/web/src/components/marketing/roiCalculator.tsx:628, :670 | legend "What you want Calevate to do"; label "Calevate's first call" | NAME / NAME's |
| apps/web/src/components/marketing/roiCalculator.tsx:844, :871, :877, :897 | "Calevate's first call costs..."; "Calevate calls first..."; "Calevate holds a ...-min first call"; "Calevate, first call to everyone" | NAME |
| apps/web/src/components/marketing/roiCalculator.tsx:946, :974, :1036 | "Calevate answers all"; "Calevate, a month"; "with Calevate — and that is only..." | NAME |
| apps/web/src/components/marketing/roiCalculator.tsx:1105, :1113, :1124 | "Calevate calls first..."; "...Calevate is not."; "...while Calevate answers" | NAME |
| apps/web/src/components/marketing/roiCalculator.tsx:1207, :1247, :1253, :1257, :1290 | "Calevate = calls a..."; "Calevate answers at every hour"; "Calevate calls first..."; "...Calevate holding a short first call"; "your actual Calevate cost" | NAME |
| apps/web/src/components/marketing/why/mockups.tsx | 2 hits, both in comments | none |

## 3. Web app: sign-in, account and shell

| file:line | current text | replace with |
|---|---|---|
| apps/web/src/app/(auth)/auth/sign-in/page.tsx:40 | `realmLabel="Calevate"` (shown in signed-out toast) | NAME |
| apps/web/src/app/(auth)/auth/sign-in/page.tsx:48 | "Sign in to Calevate" | NAME |
| apps/web/src/app/(auth)/auth/sign-in/page.tsx:68 | "New to Calevate?" | NAME |
| apps/web/src/app/(auth)/auth/accept-invitation/page.tsx:63 | "...creates your Calevate account and adds you to" | NAME |
| apps/web/src/components/authn/createAccountForm.tsx:102 | "Create your Calevate account" | NAME |
| apps/web/src/components/authn/sessionGate.tsx:111 | screen-reader heading "Calevate {realmLabel}" | NAME |
| apps/web/src/components/authn/sessionGate.tsx:171 | "Calevate did not answer, so we do not know..." | NAME |
| apps/web/src/components/authn/sidebarSignOut.tsx:146 | "Calevate could not be reached..." | NAME |
| apps/web/src/components/authn/signInForm.tsx:365 | "Calevate could not be reached to end the session..." | NAME |
| apps/web/src/components/authn/adminIdleTimeoutModal.tsx:226, :228 | "...did not reach Calevate."; "...Calevate refused the request" | NAME |
| apps/web/src/lib/authn/clientSession.tsx:42 | `CLIENT_REALM_LABEL = "Calevate"` | NAME |
| apps/web/src/lib/authn/problems.ts:172 | "...did not come from a Calevate page. Open Calevate directly..." | NAME |
| apps/web/src/lib/authn/problems.ts:211, :213 | "You already have a Calevate account with this email address..." | NAME |
| apps/web/src/lib/authn/problems.ts:242 | "We could not reach Calevate. Check your connection..." | NAME |
| apps/web/src/lib/authn/transport.ts:169-170 | "Calevate could not be reached"; "We could not reach Calevate." | NAME |
| apps/web/src/lib/api/client.ts:1138 | "Calevate is not answering right now." | NAME |
| apps/web/src/app/global-error.tsx:61 | "Calevate could not finish loading." | NAME |
| apps/web/src/components/maintenance.tsx:124 | "Calevate is down for planned maintenance" | NAME |
| apps/web/src/app/admin/layout.tsx:276 | sidebar title "Calevate admin" | NAME |
| apps/web/src/app/c/[slug]/ClientSidebar.tsx:133 | sidebar title "Calevate" | NAME |
| apps/web/src/app/c/page.tsx:120 | "If you belong to more than one Calevate account..." | NAME |
| apps/web/src/components/brand.tsx:110, :145 | `alt="Calevate"` (wordmark, header mark) | NAME |
| apps/web/src/components/brand.tsx:165 | `alt="Calevate — AI voice calling agents"` (lockup) | NAME — TAGLINE |
| apps/web/src/lib/api/adminAccount.ts:104 | role label "Calevate operator" | NAME |
| apps/web/src/lib/razorpayCheckout.ts:282 | Razorpay checkout `name: "Calevate"` (top of the payment window) | NAME |

## 4. Web app: client console (dashboard, onboarding, empty states, settings)

| file:line | current text | replace with |
|---|---|---|
| apps/web/src/app/c/[slug]/TrialCallPanel.tsx:175, :176 | "...from a shared Calevate number until then..."; "...from a shared Calevate number..." | NAME |
| apps/web/src/app/c/[slug]/TrialLockNotice.tsx:12 | "Test calls ring from a shared Calevate number until then." | NAME |
| apps/web/src/app/c/[slug]/agents/actions/AccountRow.tsx:111 | "...Ask your Calevate team." | NAME |
| apps/web/src/app/c/[slug]/agents/panels/delivery.tsx:97 | "Calevate default" | NAME |
| apps/web/src/app/c/[slug]/billing/LowBalanceAlertPanel.tsx:90, :100 | "Use Calevate's"; "Calevate's usual line, ₹..." | NAME's |
| apps/web/src/app/c/[slug]/campaigns/blockerCopy.tsx:123 | "Calevate paused outgoing calls for a while..." | NAME |
| apps/web/src/app/c/[slug]/do-not-call/copy.ts:74 | "Calevate has suppressed it across the whole platform..." | NAME |
| apps/web/src/app/c/[slug]/integrations/AddDestinationDrawer.tsx:74 | "Check the X-Calevate-Signature header..." | follows §9 header decision |
| apps/web/src/app/c/[slug]/integrations/WebhookForm.tsx:75 | placeholder "https://your-crm.example.com/calevate" | lower-case NAME |
| apps/web/src/app/c/[slug]/integrations/whatsapp/Templates.tsx:111, :128 | "Calevate's standard templates are on their way to Meta."; " · Written by Calevate" | NAME |
| apps/web/src/app/c/[slug]/integrations/whatsapp/WhatsAppSection.tsx:63 | "Calevate hears from Meta about this number" | NAME |
| apps/web/src/app/c/[slug]/integrations/whatsapp/WhatsAppSection.tsx:354 | "Give Calevate access through Meta" | NAME |
| apps/web/src/app/c/[slug]/leads/[leadId]/LeadTimeline.tsx:179 | system actor shown as "Calevate" | NAME |
| apps/web/src/app/c/[slug]/phone-number/BuyNumber.tsx:106 | "The connection is registered to your business, not to Calevate..." | NAME |
| apps/web/src/app/c/[slug]/phone-number/BuyNumber.tsx:138 | "Calevate provides your number on our own telephony account..." | NAME |
| apps/web/src/app/c/[slug]/phone-number/PhoneNumberScreen.tsx:141 | "...Calevate provides them on" | NAME |
| apps/web/src/app/c/[slug]/settings/models/ModelsScreen.tsx:85, :99 | "none — it follows the Calevate default"; ", the Calevate default" | NAME |
| apps/web/src/app/c/[slug]/settings/models/OrganizationDefault.tsx:57 | "Follows Calevate's default." | NAME's |
| apps/web/src/app/c/[slug]/settings/phone-numbers/PhoneNumbersScreen.tsx:97 | "Get your Calevate number first" | NAME |
| apps/web/src/app/c/[slug]/settings/phone-numbers/PhoneNumbersScreen.tsx:206 | "No Calevate number" | NAME |
| apps/web/src/app/c/[slug]/setup/_ui/copy.ts:130 | `needNumber: "Get your Calevate number first"` | NAME |
| apps/web/src/app/c/[slug]/verify-business/About.tsx:150 | "Calevate provides your calling number..." | NAME |
| apps/web/src/app/c/[slug]/verify-business/DltRegistration.tsx:81 | "Calevate authorised to dial for you:" | NAME |
| apps/web/src/app/c/[slug]/verify-business/copilot.ts:109 | "Is Calevate linked as the telemarketer on it?" | NAME |
| apps/web/src/components/forwarding/ExistingNumberGuide.tsx:228 | "This number belongs to my business. Calevate may ring it..." | NAME |
| apps/web/src/components/forwarding/ExistingNumberPrompt.tsx:48 | "Your existing phone forwards calls to your Calevate number..." | NAME |
| apps/web/src/components/callHandlingDefaults.tsx:106, :120, :187, :210 | "Calevate default: ..."; "Calevate default" | NAME |
| apps/web/src/lib/api/callHandling.ts:86, :104, :108, :112, :116, :129-132, :224 | "Calevate default" / "Calevate default: ..." (the one label behind every call-handling row) | NAME |
| apps/web/src/components/modelTierSetting.tsx:56, :58 | "Calevate's default"; "...Follows Calevate's default when it changes." | NAME's |
| apps/web/src/components/modelTierSetting.tsx:211 | "Calevate picks the language model your agents think with..." | NAME |
| apps/web/src/components/leadFields/LeadDetailsView.tsx:243 | admin side: "Calevate can draft these for you." (client side says Pip) | NAME |
| apps/web/src/components/invoiceDocument.tsx:95 | supplier name fallback `?? "Calevate"` | ENTITY (or set `GST_SUPPLIER_LEGAL_NAME`) |
| apps/web/src/lib/gstStatus.ts:12 | "Calevate is a sole proprietorship below the GST registration threshold..." (billing screen, What calls cost, pricing page, invoice) | NAME/ENTITY, FORM, GST — must match `apps/api/billing/gst.py:85` |
| apps/web/src/lib/api/actions.ts:319 | "Sheet not chosen for Calevate" | NAME |
| apps/web/src/lib/api/dltRegistration.ts:94, :98, :102, :106 | four DLT status sentences naming Calevate as telemarketer | NAME |
| apps/web/src/lib/api/kyc.ts:287 | "Calevate never records an individual's identity document..." | NAME |
| apps/web/src/lib/api/llmModels.ts:213 | "...ask your Calevate team to enable it." | NAME |
| apps/web/src/app/c/[slug]/billing/TransactionsTab.tsx:55 | download name `calevate-transactions-<date>.csv` | lower-case NAME |
| apps/web/src/app/c/[slug]/campaigns/ContactEditor.tsx:144 | download name `calevate-contacts-sample.csv` | lower-case NAME |

Pip (the in-app assistant) keeps its name; its client-side text in `apps/web/src` names
Pip via `ASSISTANT_NAME`, not the product. Pip's system prompts are in the API (§5.5).

## 5. Web app: admin console

| file:line | current text | replace with |
|---|---|---|
| apps/web/src/app/admin/operators/AddOperatorDrawer.tsx:93 | placeholder "asha@calevate.tech" | DOMAIN |
| apps/web/src/app/admin/ops/DashboardDataUsePanel.tsx:448 | placeholder "...project 'calevate-prod'" | example only; NAME |
| apps/web/src/app/admin/ops/KnowledgeDriftPanel.tsx:96 | names `calevate_shared.config.EngineName` (code path shown on screen) | keep while the package keeps its name |
| apps/web/src/app/admin/ops/OpsSurface.tsx:231 | "Calevate's telemarketer registration" | NAME's |
| apps/web/src/app/admin/ops/TmRegistrationPanel.tsx:124, :139 | "Calevate is the registered..."; "Calevate does not register as a telemarketer..." | NAME |
| apps/web/src/app/admin/ops/config/ConfigForm.tsx:204 | "Calevate will not record a card that sells a minute for less..." | NAME |
| apps/web/src/app/admin/ops/config/ConfigInput.tsx:441 | "answered by an agent outside Calevate" | NAME |
| apps/web/src/app/admin/ops/config/configControl.ts:272 | "Use an email address, like ops@calevate.tech." | MAIL_OPS |
| apps/web/src/app/admin/ops/dnc/DncScreen.tsx:165 | "Numbers Calevate never dials for any client..." | NAME |
| apps/web/src/app/admin/ops/healer/HealerScreen.tsx:392 | "The public reads this at status.calevate.tech..." | DOMAIN |
| apps/web/src/app/admin/ops/kit/sections/charts.tsx:200 | sample meta "24 Oct, 10:42 am · Calevate" | NAME |
| apps/web/src/app/admin/ops/kit/sections/content.tsx:210 | sample "Calevate is not answering right now." | NAME |
| apps/web/src/app/admin/ops/kit/sections/feedback.tsx:20 | sample type "https://calevate.tech/problems/agent_name_taken" | DOMAIN |
| apps/web/src/app/admin/ops/voices/hosted/VoiceDrawer.tsx:71 | voice-clone consent "...used by Calevate as a voice option for...Calevate's clients..." | NAME / ENTITY (a consent text: a new wording means new consents for new clones) |
| apps/web/src/lib/api/opsHostedVoices.ts:91 | `CONSENT_SCOPE = "Calls made by Calevate clients' agents."` | NAME (pair with `apps/api/agents/hosted_voices.py:648`) |
| apps/web/src/app/admin/ops/whatsapp/WhatsAppAdminScreen.tsx:53, :145 | "...callback URL https://api.calevate.tech..." | DOMAIN |
| apps/web/src/app/admin/ops/whatsapp/WhatsAppAdminScreen.tsx:93, :124 | "...with Calevate as the Tech Provider."; "Calevate's Meta set-up" | NAME |
| apps/web/src/app/admin/payments/PaymentsScreen.tsx:51 | `WEBHOOK_HOST = "https://api.calevate.tech"` (shown to copy into Razorpay) | DOMAIN |
| apps/web/src/app/admin/tenants/[tenantId]/accountFacts.ts:129 | "...held by Calevate" | NAME |
| apps/web/src/app/admin/tenants/[tenantId]/agents/[agentId]/prompt/sections/model.tsx:44 | "This voice platform runs Calevate's own models..." | NAME's |
| apps/web/src/app/admin/tenants/[tenantId]/call-handling/page.tsx:62, :67 | ", the Calevate default" | NAME |
| apps/web/src/app/admin/tenants/[tenantId]/credits/TrialPanel.tsx:176 | "Cost to Calevate so far:" | NAME |
| apps/web/src/app/admin/tenants/[tenantId]/numbers/CallLinesPanel.tsx:46 | "Calevate default (free trial / paying client)" | NAME |
| apps/web/src/app/admin/tenants/[tenantId]/numbers/ForwardingCard.tsx:31 | "...forwarded to their Calevate number." | NAME |
| apps/web/src/app/admin/tenants/[tenantId]/readiness/ReadinessScreen.tsx:98 | "How many of them are Calevate's to clear" | NAME's |
| apps/web/src/app/admin/tenants/[tenantId]/spend/SpendScreen.tsx:310 | "...Calevate absorbs this cost; the" | NAME |

---

## 6. API and workers: what clients and operators read

### 6.1 Email: sender, layout, subjects, bodies

| file:line | current text | replace with |
|---|---|---|
| packages/shared/src/calevate_shared/config.py:1335 | `notifications_from` default `support@calevate.tech` (also a live console setting) | MAIL_SUPPORT on DOMAIN |
| packages/shared/src/calevate_shared/config.py:1353 | `notifications_reply_to` default `calevate.voice@gmail.com` | MAIL_SUPPORT |
| apps/api/core/brand.py:61 | `PRODUCT = "Calevate"` — the name in every email's `<title>` and header (`email_layout.py:75`, `:84`) | NAME (one change covers all branded emails) |
| apps/api/core/alert_email.py:62 | "Calevate operator alert..." | NAME |
| apps/api/core/alerting.py:778 | subject `[Calevate {severity}] {code} ({service})` | NAME |
| apps/workers/email_render.py:54, :58 | footer "Calevate · AI voice agents for Indian businesses." | NAME · TAGLINE |
| apps/workers/email_render.py:73, :146 | sign-off "— Calevate" | NAME |
| apps/workers/email_render.py:103, :113, :121, :123, :129, :131 | OTP leads: "Enter this code in Calevate...", "...a Calevate account..." | NAME |
| apps/workers/email_render.py:172-179 | 8 subjects: "Reset your Calevate password", "Your Calevate verification code", "...sign-in code", "...authorization code", "You have been invited to Calevate", "Set up your Calevate administrator account", "Your Calevate sign-up code", "You already have a Calevate account" | NAME |
| apps/workers/email_render.py:195, :210, :211, :221, :223, :241 | reset, invite, existing-account and admin-bootstrap bodies | NAME |
| apps/workers/account_closure.py:95-97 | subjects "Your Calevate account has been closed / reopened", "The email address for your Calevate account was changed" | NAME |
| apps/workers/account_closure.py:150, :159, :168 | bodies naming "Calevate" | NAME |
| apps/workers/comp_notices.py:81, :82, :94, :95, :115 | credit-added and paid-account emails, "Calevate: {business} ..." | NAME |
| apps/workers/maintenance.py:120-123 | subjects "Planned Calevate maintenance", "...is finished", etc. | NAME |
| apps/workers/maintenance.py:810-814 | bodies "Calevate will be unavailable from...", etc. | NAME |
| apps/workers/rate_card_notice.py:101 | "Your Calevate calling rates are changing" | NAME |
| apps/workers/razorpay_jobs.py:129, :130 | "We are topping up your Calevate balance"; "...has been topped up" | NAME |
| apps/workers/number_holds.py:288 | "your Calevate account has been closed" | NAME |
| apps/api/core/console_links.py:30, :31 | links in emails `https://app.calevate.tech`, `https://admin.calevate.tech` | DOMAIN |
| apps/api/healer/notices.py:16 | `STATUS_PAGE_URL = "https://status.calevate.tech"` | DOMAIN |

There are no separate template files: every email is built in Python in the files above.

### 6.2 Invoices, receipts, GST

| file:line | current text | replace with |
|---|---|---|
| apps/api/billing/gst.py:85-86 | `GST_STATUS_SENTENCE` "Calevate is a sole proprietorship below the GST registration threshold, so it is not registered for GST, charges no GST and does not issue tax invoices." Printed on every bill of supply (`invoice.py:94`), receipt (`wallet_routes.py:399`), statement (`routes.py:273`) | NAME/ENTITY + FORM + GST. Must equal `apps/web/src/lib/gstStatus.ts:12` (`tests/gst_status_test.py`) |
| apps/api/billing/gst.py:251 | supplier legal name from setting `gst_supplier_legal_name` (no default) | set to ENTITY in the console; address setting `gst_supplier_address` to CITY level |
| apps/api/billing/invoice.py:610 | invoice serial `CAL{YYMM}{suffix}` | decide: keep `CAL` or a new prefix; a new entity starts a new series anyway |
| apps/api/billing/gst.py:307 | "No GST registration is configured for Calevate." | NAME |
| apps/api/billing/routes.py:269 | "The same statement the Calevate team sees..." (API description) | NAME |
| apps/api/billing/trials.py:666 | "Replaced by the trial Calevate set for this account." | NAME |

### 6.3 Problem+json titles and details shown to clients

| file:line | current text (short) | replace with |
|---|---|---|
| apps/api/core/errors.py:37 | problem `type` base `https://calevate.tech/problems` | DOMAIN |
| apps/api/core/errors.py:466, :676 | "This account cannot open this part of Calevate." | NAME |
| apps/api/core/errors.py:666 | "If a link inside Calevate brought you here, contact us." | NAME |
| apps/api/core/middleware.py:604 | "Calevate is closed for planned maintenance..." | NAME |
| apps/api/core/middleware.py:624 | "Calevate is very busy for a moment..." | NAME |
| apps/api/core/envelope.py:320, :325 | "A part of Calevate that keeps your saved details safe..."; "Your Calevate team has been alerted" | NAME |
| apps/api/core/settings.py:686, :691 | same pattern (audit store) | NAME |
| apps/api/core/auth.py:400 | "Contact Calevate support if you still need an export..." | NAME |
| apps/api/authn/cookies.py:526-527 | "This did not come from a Calevate page."; "Sign in from the Calevate dashboard..." | NAME |
| apps/api/authn/google.py:394, :428, :446, :460, :461 | Google sign-in errors naming "Calevate account" | NAME |
| apps/api/authn/registration.py:135 | "There is already a Calevate account for this email address." | NAME |
| apps/api/authn/routes.py:333, :337 | "Nobody can sign in to Calevate at the moment..."; "...contact Calevate" | NAME |
| apps/api/authn/policy.py:126 | password blocklist words `{"calevate", "calevate.tech"}` | add NAME and DOMAIN (keep the old two) |
| apps/api/tenancy/signup.py:291 | "Calevate is not taking new sign-ups right now..." | NAME |
| apps/api/actions/calendar.py:99, :104 | "Calevate's link to Google Calendar has not been set up..."; "Ask your Calevate team..." | NAME |
| apps/api/actions/oauth.py:219, :223 | same for Zoho/HubSpot | NAME |
| apps/api/actions/routes.py:479, :605 | "Remove Calevate from your ... connected apps"; "...no longer lets Calevate open its file picker." | NAME |
| apps/api/actions/credentials.py:88; actions/service.py:286 | "...not an integration Calevate can hold..."; "...filled in by Calevate on every call." | NAME |
| apps/api/admin/business_copy_routes.py:115; admin/business_type.py:119; billing/ai_quota.py:430, :1322; copilot/fair_use.py:148 | "AI help is paused across Calevate..." | NAME |
| apps/api/agents/service.py:2708 | "Calevate is in a maintenance window" | NAME |
| apps/api/agents/service.py:3625-3626 | "...not on the phone line Calevate places calls through...Ask Calevate to record..." | NAME |
| apps/api/agents/handoff.py:93 | "Calevate can only put callers through to Indian numbers..." | NAME |
| apps/api/agents/languages.py:293 | "Calevate does not offer {language} yet." | NAME |
| apps/api/agents/llm_models.py:393, :683; agents/llm_tiers.py:234 | "...ask your Calevate team to enable it"; "...Calevate cannot yet use it for" | NAME |
| apps/api/agents/engine_choice.py:144; engine_limits.py:304; engine_catalogue_offer.py:61; engine_catalogue_routes.py:253; voice_tuning_routes.py:289; ops/hosted_voice_routes.py:572, :699 | "...runs Calevate's own...", "The rules Calevate adds...", "Calevate offers only models...", "Voices ... come from Calevate's own catalogue." | NAME |
| apps/api/agents/prompt_size.py:39 | section label "Calevate's opening rules" | NAME's |
| apps/api/agents/transfer_providers/registry.py:29 | "Live transfer works on numbers rented through Calevate..." | NAME |
| apps/api/campaigns/service.py:214, :368 | "Calevate does not dial bought or rented..."; "...Calevate" (consent age) | NAME |
| apps/api/campaigns/provisioning.py:306; engine_number_purchase.py:142; engine/thinnest_workspace.py:179 | "...Calevate", "Otherwise your Calevate team..." | NAME |
| apps/api/campaigns/scheduling.py:794 | "...isn't one Calevate can run" | NAME |
| apps/api/compliance/service.py:185, :300 | "Calevate is in a planned maintenance window..."; "Calevate places calls to Indian (+91) numbers only." | NAME |
| apps/api/compliance/registration.py:81, :86 | "Your DLT Principal Entity has not authorised Calevate..."; "Ask Calevate to re-verify..." | NAME |
| apps/api/compliance/trial_access.py:70 | "...test calls ring from a shared Calevate number." | NAME |
| apps/api/compliance/outbound_pledge.py:49-50 | outbound pledge text "...made by Calevate's AI voice agent through Calevate's licensed telephony partners...Calevate keeps" | NAME (a signed pledge text: see §8) |
| apps/api/compliance/whatsapp_optin.py:119 | opt-in wording "I agree that Calevate may send WhatsApp messages..." | NAME (consent text) |
| apps/api/compliance/caller_notice.py:100, :651, :680 | draft caller notice "Calevate generated this...", "agreement with Calevate covers..." | NAME |
| apps/api/legal/readiness.py:115, :180, :205, :208 | readiness rows "...not Calevate.", "Calevate's telemarketer registration", "Calevate is not authorised on your DLT account", "authorise Calevate as your telemarketer" | NAME |
| apps/api/legal/statements.py:59 | acceptance statement "...Calevate will ask me to accept these documents again..." (provisional; check the reviewed one beside it) | NAME (a statement revision) |
| apps/api/engine/capabilities.py:197 | "Calevate cannot reach its voice platform right now." | NAME |
| apps/api/engine/vendor_http.py:740 | "Calevate stopped a voice platform call before it went out" | NAME |
| apps/api/forwarding/service.py:45, :90, :123, :248, :249, :254, :311 | "...your Calevate number", "Calevate number" not found, "That is your Calevate number..." | NAME |
| apps/api/forwarding/codes.py:149 | "Ask your provider to enable call divert to your Calevate number." | NAME |
| apps/api/crm/attention.py:229, :245 | "Your Google account has not given Calevate this spreadsheet..." | NAME |
| apps/api/kb/insights.py:313 | "...your Calevate dashboard and write what the agent should say" | NAME |
| apps/api/kb/service.py:671; quality/routes.py:73 | model label fallback `unclassified="Calevate"` | NAME |
| apps/api/live/routes.py:102 | "Close a few Calevate tabs..." | NAME |
| apps/api/whatsapp/accounts.py:134; graph.py:68; routes.py:225; signup.py:265 | "Calevate can no longer reach this WhatsApp account.", "contact Calevate support", "...WhatsApp with Calevate.", "...already connected to Calevate." | NAME |
| apps/api/ops/config_routes.py:697, :1071, :1144; config_service.py:250, :314; model_pricing.py:455, :567, :854, :1049; secret_service.py:114 | operator errors "...Calevate could not read it back", "...isn't a setting Calevate recognises", etc. | NAME |
| apps/api/reliability/engine_actions.py:546; engine_webhooks.py:142 | "...such as api.calevate.tech / hooks.calevate.tech" | DOMAIN |
| apps/workers/extraction.py:1599, :1629, :2004, :2012, :2025, :2056 | notes on AI-written text "written by Calevate's own assistant model", "contact Calevate support", "Ask your Calevate team..." | NAME |

API reference text (`summary=`/`description=` on routes) also names Calevate in about 40 places
(e.g. `agents/call_handling_routes.py:549,561,725`, `agents/llm_routes.py:406-467`,
`billing/wallet_routes.py:911`, `compliance/kyc_routes.py:285-493`,
`compliance/registration_routes.py:132-134`, `ops/hosted_voice_routes.py:681,972,1320,1420`,
`ops/routes.py:775,777`, `ops/maintenance_routes.py:583`, `announcements/routes.py:161`,
`admin/routes.py:2551,2644`, `tenancy/call_lines_routes.py:84`). They reach a person through
the generated `apps/web/src/lib/api/openapi.json` / `schema.d.ts` (744 + 88 hits) and the API
title `apps/api/main.py:110` "Calevate API", `apps/voice-runtime/main.py:88` "Calevate
voice-runtime". Change them, then regenerate (`pnpm -C apps/web gen:api`) so the snapshot
check passes.

### 6.4 Erasure certificates and exports

| file:line | current text | replace with |
|---|---|---|
| apps/api/compliance/deletion.py:421-872 (about 30 sentences) | the caller-erasure certificate's scope and exemption text: "...floor Calevate applies...", "Calevate's consent ledger is append-only...", "Calevate holds no account with that carrier...", "Calevate's erasure scope is..." | NAME |
| apps/api/compliance/tenant_erasure.py:190-196, :311, :326, :339, :345, :432 | the account-erasure certificate, same pattern | NAME |
| apps/api/compliance/deletion_proof.py:354 | "...in Calevate and on the voice platform's copy..." | NAME |
| apps/api/actions/sheets.py:38 | Google Sheets column header "Calevate call" | NAME (existing client sheets keep the old header) |
| apps/api/integrations/service.py:1566 | sheet column "Calevate Delivery ID" | NAME (same caution) |
| apps/api/actions/execution.py:832 | calendar event description "Booked on a phone call by your Calevate agent." | NAME |
| apps/api/integrations/service.py:217-220, :1335 | webhook headers `X-Calevate-Signature/-Timestamp/-Event/-Delivery`, User-Agent `Calevate-Webhooks/1` | a contract with clients' receivers: send both names for a period, or keep (§9) |

Certificates already issued stay as issued; only new ones carry the new name.

### 6.5 Pip (the assistant): identity and system prompts

Pip's own name stays. These lines tell the model, and through it the user, which product it belongs to:

| file:line | current text | replace with |
|---|---|---|
| apps/api/copilot/prompt.py:210-211 | "You are {Pip}, the Calevate assistant...part of the Calevate product." | NAME |
| apps/api/copilot/prompt.py:218, :226, :227 | identity rules "...the Calevate assistant, that Calevate does not discuss which AI..." | NAME |
| apps/api/copilot/prompt.py:322 | "You are the in-app assistant inside Calevate, a platform that gives small Indian..." | NAME |
| apps/api/copilot/prompt.py:490-491 | "You are {Pip}, the Calevate assistant...the AI providers Calevate buys from" | NAME |
| apps/api/copilot/admin_prompt.py:102, :104, :120, :140, :157, :215, :216 | admin Pip: "operations assistant inside the Calevate admin console. Calevate is a...", "Calevate operator", "Calevate's own runbooks" | NAME |
| apps/api/copilot/identity.py:302-303 | fixed answer "I am {Pip}, the Calevate assistant — an AI that helps you work inside Calevate. I do not discuss which AI providers Calevate buys from..." | NAME |
| apps/api/copilot/context.py:103 | "...read by the Calevate server" | NAME |
| apps/api/copilot/screen_guides.py:29 | "--- FIRST AGENT (Calevate's guide for this screen) ---" | NAME's |
| apps/api/copilot/screens.py:394, :409 | "What Calevate is allowed to notify...", "...forwarded to the Calevate number" | NAME |
| apps/api/copilot/account_actions.py:286, :336, :516, :1887, :2470, :2544 | proposals "...to your Calevate number", "Lead details leave Calevate", "(Calevate's)" | NAME |
| apps/api/copilot/agent_actions.py:560, :759; agent_setup_actions.py:867, :1073; campaign_actions.py:919; console_actions.py:3140, :3198; console_reads.py:480, :498, :949; admin_tools.py:284, :303, :777 | tool summaries and read-outs naming Calevate | NAME |

Tests that pin these: `tests/assistant_vendor_identity_test.py:172,235`.

### 6.6 WhatsApp

| file:line | current text | replace with |
|---|---|---|
| apps/api/whatsapp/templates.py:74, :93, :113, :135 | template NAMES `calevate_booking_confirmed`, `calevate_details_you_asked_for`, `calevate_payment_link`, `calevate_call_back_time` | new prefix; Meta re-approves in every connected account. The template BODIES do not name Calevate |
| apps/api/forwarding/save_number.py:50 | template name `calevate_save_our_number_v1` | new prefix |
| packages/shared/src/calevate_shared/config.py:1412, :1416, :1417, :1419 | our own account's template names `calevate_hot_lead_v1`, `calevate_alarm_page_v1`, `calevate_line_notice_v1`, `calevate_line_restored_v1` (settings) | new prefix, after Meta approves |
| apps/api/ops/config_catalog.py:875, :905 | "...shared with Calevate."; "Calevate's Meta app that every client's WhatsApp connection is made through." | NAME |

Template names are seen by Meta reviewers and in WhatsApp Manager, not by the person receiving the message.

### 6.7 Text sent to the voice platform

| file:line | current text | who sees it | replace with |
|---|---|---|---|
| **apps/api/campaigns/engine_numbers.py:710-713** | `TRIAL_LINE_MESSAGE` "Thanks for calling back. This number only places test calls for businesses trying Calevate, so no one can take your call here. Goodbye." | **SPOKEN to anyone who calls the shared trial number back** | NAME (≤300 characters; `tests/trial_line_agent_test.py:105-171` pins it by reference, not by text) |
| apps/api/engine/thinnest_customer_data.py:54 | DNC reason "Opted out with this business (Calevate do-not-call list)" | ThinnestAI workspace | NAME |
| apps/api/engine/trial_line.py:16 | agent name "Calevate shared trial number (no answer)" | ThinnestAI console only. **The code finds this agent by this exact name**: renaming without migrating makes a second agent | NAME, with a lookup that accepts the old name once |
| apps/api/engine/forwarding_probe.py:20-21 | agent names "Calevate forwarding test, line 1/2 (automated)" | ThinnestAI console only | NAME (check whether it is also looked up by name) |
| apps/api/engine/hosted_platform.py:182 | operator note "...Calevate points..." | admin console | NAME |
| apps/api/ops/config_catalog.py:1363-1364 | placeholders `https://api.calevate.tech`, `api.calevate.tech:443` | admin console | DOMAIN |

### 6.8 Other

| file:line | current text | replace with |
|---|---|---|
| apps/api/billing/payments.py:243 | `USER_AGENT = "Calevate/1.0 (+https://calevate.tech)"` (seen in vendors' logs) | NAME, DOMAIN |
| apps/api/core/bootstrap.py:86 | `MARKETING_ORIGIN = "https://calevate.tech"` (CORS, not text) | DOMAIN (part of the one-setting work in REBRAND-MAP §2B) |

---

## 7. Agent call text: what callers hear

Read: `packages/shared/src/calevate_shared/engine.py` (prompt composition, `CONFIDENTIALITY_RULE`,
truthful-answer block), `spoken_style.json`, `spoken_style.py`, `call_script.py`, and the
disclosure, notice, greeting and opening code under `apps/api/agents/`.

- **No client agent line names Calevate.** The only matches in those files are comments and
  the module name `calevate_shared` (inside `spoken_style.json`'s `"about"` note, which is
  not spoken). Disclosure and recording-notice lines, openings, thinking lines and the
  trial-call opening are free of the name.
- **Exception 1 (spoken):** `apps/api/campaigns/engine_numbers.py:710-713`, the shared trial
  number's call-back message (§6.7). It does say "Calevate". `docs/REBRAND-MAP.md` §2A says
  "nothing" for what is said on calls; that line in the map is wrong for this message.
- **Exception 2 (prompt, may be spoken):** `apps/workers/maintenance.py:256`, the
  maintenance-window prompt: "You are answering a call while the Calevate platform is closed
  for planned maintenance." It instructs the model rather than giving a line to read, but
  the model can repeat it to a caller. Change to NAME, or better remove the name so callers
  of a client's business never hear the platform's name (D-679).
- `apps/api/engine/forwarding_probe.py:26` `TEST_CALL_PURPOSE` (spoken on the forwarding test
  call) says "your business's call service" and does not name Calevate.

---

## 8. Legal documents

### 8.1 The facts in `apps/web/src/lib/legal/placeholders.ts`

| token (line of `value`) | current value | replace with |
|---|---|---|
| LEGAL_ENTITY_NAME (:100) | "Calevate" (Udyam enterprise name CALEVATE) | ENTITY |
| ENTITY_REGISTRATION_NUMBER (:118) | "UDYAM-AP-04-0146106" | UDYAM |
| GST_STATUS (:137-138) | "not registered for GST, and not required to be at present turnover" | GST |
| REGISTERED_ADDRESS (:195) | "Guntur, Andhra Pradesh, India" | CITY, STATE, India (no street, no PIN) |
| JURISDICTION_CITY (:327) | "Guntur" (arbitration seat and courts) | CITY, or another seat the lawyer advises |
| CONTACT_PHONE (:206) | (the published contact number, see `placeholders.ts:206`) | unchanged unless new |
| SUPPORT_EMAIL (:223) | "calevate.voice@gmail.com" | MAIL_SUPPORT |
| GRIEVANCE_OFFICER_NAME (:234) | "Umesh J" | unchanged unless new |
| GRIEVANCE_OFFICER_DESIGNATION (:247) | "Grievance Officer" | unchanged |
| GRIEVANCE_OFFICER_EMAIL (:264) | "calevate.voice@gmail.com" | MAIL_GRIEVANCE |
| DATA_PROTECTION_CONTACT_NAME (:277) | "Umesh J" | unchanged unless new |
| DATA_PROTECTION_CONTACT_EMAIL (:294) | "calevate.voice@gmail.com" | MAIL_DPO |
| SECURITY_CONTACT_EMAIL (:314) | "calevate.voice@gmail.com" | MAIL_SECURITY |
| EFFECTIVE_DATE (:339) | "2 September 2026" | the publication date of the new revision |
| PRIMARY_HOSTING_LOCATION, REFUND_PROCESSING_DAYS, DATA_RETURN_WINDOW_DAYS | not entity facts | unchanged |

The `describes`/`source` prose of each entry also cites the old certificate (e.g. :97-99
"printed from udyamregistration.gov.in on 25 Aug 2026...enterprise name CALEVATE", :323-326
for the jurisdiction decision, :214-217 etc. naming `calevate.tech` mailboxes). Rewrite the
sources against the new certificate. These notes are not shown to readers.

### 8.2 Per document: clauses naming the entity, form, Udyam, city, GST, emails

Every document also says "Calevate" in ordinary prose (counts: privacy 27, terms 14,
acceptable use 13, cookies 10, dpa 9, grievance 6, subprocessors 4, refunds 2); each is a
NAME swap. The entity facts flow in through the tokens above:

| document (current revision in versions.ts) | entity / Udyam / address | legal form | city / courts | GST | emails / phone | other brand text |
|---|---|---|---|---|---|---|
| Terms `terms.ts` (rev 19, blocking) | §1 :90-93 "between {{LEGAL_ENTITY_NAME}} (Udyam registration number {{...}}, principal place of business {{REGISTERED_ADDRESS}}) — "Calevate", "we"..."; §17 :993-995 "Who you are contracting with" | none stated (:967 mentions a sole proprietor as a CUSTOMER, not us) | §16 :952, :955 arbitration seat and courts {{JURISDICTION_CITY}} | §6.2 :470 "{{LEGAL_ENTITY_NAME}} is {{GST_STATUS}}" | §17 :981-989 support, phone, grievance, DPO, security; :694, :916 support | :77, :80, :93, :112, :192, :206, :221, :267, :331-333, :591, :716, :857, :965 |
| Privacy `privacy.ts` (rev 26, blocking) | §1 :203-206 "Calevate is a product operated by {{LEGAL_ENTITY_NAME}} (Udyam ...) ...'Calevate' mean that business"; §14 :1635-1637 | none | — | — | §14 :1617-1637 DPO, grievance, security, phone; :1473, :1523 DPO | :190-194 "Visitors to calevate.tech", :222 "You are visiting calevate.tech", :231 "app.calevate.tech", :306 "3.1 If you only visit calevate.tech", :266-268, :332-370, :712-717, :749, :1213, :1369, :1404, :1553 |
| DPA `dpa.ts` (rev 18, blocking) | :64-66 "'we' means {{LEGAL_ENTITY_NAME}} (Udyam ..., principal place of business {{REGISTERED_ADDRESS}})" | none | — | — | Contact :1058-1060 DPO name, email, security | :50, :53, :87, :92, :259, :313, :807, :928 |
| Acceptable use `acceptableUse.ts` (rev 7, blocking) | — | — | — | — | :539, :608 security; :599 support | :43, :46, :56, :65, :78, :119, :296, :425-427 (the outbound-call disclosure, same words as `outbound_pledge.py:49`), :493, :523 |
| Sub-processors `subprocessors.ts` (rev 24) | — | — | — | — | :1032 DPO | :428, :431, :456 |
| Refunds `refunds.ts` (rev 7) | §7 :262-264 "{{LEGAL_ENTITY_NAME}}, Udyam registration number ..., {{REGISTERED_ADDRESS}}" | — | — | :198 {{GST_STATUS}} | :85, :189, :228, :252 support/phone; :256-257 grievance | :32, :41 |
| Grievance `grievance.ts` (rev 3) | :157-159 "Calevate is operated by {{LEGAL_ENTITY_NAME}} (Udyam ...{{REGISTERED_ADDRESS}})" | — | :391 contract disputes seated at {{JURISDICTION_CITY}} | — | :128-129, :139, :145, :154, :328 officer, DPO, security, phone | :105, :170, :172, :240, :314 |
| Cookies `cookies.ts` (rev 6) | — | — | — | — | :309 DPO | :79 "Anyone using calevate.tech or app.calevate.tech", :133 "app.calevate.tech or admin.calevate.tech", :145-146, :160-161 cookie names `__Host-calevate_client_session`/`_admin_session` and "set by Calevate", :207 storage keys `calevate.authn.had-session.*`, :280 "calevate.tech" |

Notes:
- **Legal form.** No legal document states "sole proprietorship" (deliberately, per
  `placeholders.ts:91-94`). The form appears only in the GST sentence:
  `apps/web/src/lib/gstStatus.ts:12` and `apps/api/billing/gst.py:85`, and in the invoice
  comments. If the new enterprise is a company or LLP, that sentence changes, and so may the
  GST position and the contracting-party wording.
- **The cookie table names the real cookie and storage-key names.** If those stay
  `calevate_*` (§9), the Cookies notice must keep naming them as they are.
- `apps/web/src/lib/legal/document.tsx:394` "drafted against what the Calevate codebase
  actually..." is shown under the documents: NAME.
- `apps/web/src/app/legal/page.tsx:53-54` (the legal index) — see §2.

### 8.3 versions.ts, catalogue.py and the acceptance statement

- `apps/web/src/lib/legal/versions.ts`: each document needs a NEW revision entry (privacy 27,
  terms 20, acceptable-use 8, dpa 19, subprocessors 25, refunds 8, grievance 4, cookies 7).
  `material: true` for terms, privacy, dpa (new contracting party) and acceptable use; every
  client accepts again. Each new entry needs a fresh `contentHash`.
- `apps/api/legal/catalogue.py` mirrors the same identities and must get the same revisions;
  `scripts/check_docs_drift.py` §4d fails if the two disagree. Its `reason` strings name
  Calevate (:279, :450, :545, :583-584, :642, :710, :722, :888-891, :1018): historical
  records of past revisions, leave them.
- `apps/api/legal/statements.py:59` (provisional statement) names Calevate; check the
  reviewed statement beside it and bump `_STATEMENT_REVISION` if its words change.
- Pre-launch with nothing signed: the change is a new revision of each document, not an
  edit in place, because the content-hash check refuses words that move under an existing
  revision.

### 8.4 Tests that pin legal and brand text

| test | what it pins |
|---|---|
| apps/web/tests/legalContentHash.test.ts | the hash of each document's text **with placeholders resolved**, so changing any token value (ENTITY, UDYAM, CITY, emails) changes the hash of every document that uses it, not only the prose edits |
| apps/web/tests/legal.test.tsx:1221, :1228, :1229 | "Every Calevate administrator and staff member...", "Calevate is not responsible for: the personal data you put", "Calevate is not responsible for: that data" |
| apps/web/tests/legalRegister.test.ts:108 | comment only; reads the register's entity facts |
| apps/web/tests/legalReader.test.tsx, simpleCopyLegal.test.ts, legalVendorNames.test.ts | structure and wording rules; no brand string |
| tests/legal_agreements_test.py | acceptance flow by version; no brand string |
| tests/gst_status_test.py | the web and API GST sentences are identical |
| apps/web/tests/seo.test.ts:230, :323, :324, :328, :329 | `siteName` "Calevate", Organization `name` and `legalName` "Calevate", "UDYAM-AP-04-0146106", address "Guntur, Andhra Pradesh, India" |
| apps/web/tests/brand.test.tsx:38-40, :75, :77 | image sizes 216×216 and 720×240; alt "Calevate" and "Calevate — AI voice calling agents" |
| tests/assistant_vendor_identity_test.py:172, :235 | Pip's identity sentences |
| tests/brand_tokens_test.py | email colour tokens vs `globals.css` (brand colours, if they change) |

112 test files mention "Calevate" in total; most follow whatever the code says.

---

## 9. Seen only by developers or vendors (keep, or change with care)

Not visible text, listed so nobody renames them by search-and-replace: storage keys
(`calevate:trial-strip-closed:*`, `calevate:agent-tour-seen:*`, `calevate:caller-notice:*`,
`calevate:existing-number-prompt:*`, `calevate:view-as-grant:`, `calevate.oauth.*`,
`calevate.kyc.pendingRun`, `calevate.google-invite`, `calevate.authn.had-session.*`,
`calevate.pip.attachNotice`, `calevate.desktopAlerts.*`, event `calevate:desktop-alerts`);
popup window name `calevate-connect`; `urn:calevate:browser/*` problem types in
`lib/api/client.ts`, `razorpayCheckout.ts`, `authn/transport.ts`, `copilot/stream.ts`,
`integrations.ts`, `PlatformFeeCard.tsx`; console log prefix `[calevate]`; API field names
`calevate_number_e164`, `calevate_numbers`, `calevate_tm_id`, `calevate_tm_active`,
`blocked_on_calevate`, `owner/actor: "calevate"`, `origin: "calevate"`; constants
`CALEVATE_PAISE_PER_MIN`; Razorpay notes keys `calevate_tenant_id`, `calevate_pack_id`,
`calevate_purpose`; idempotency prefixes. Renaming any of these has the costs in
`docs/REBRAND-MAP.md` §2C. The webhook headers `X-Calevate-*` (§6.4) are the one item here
a client's developer sees and builds against: change only with both names sent for a period.

---

## 10. Images that need new artwork

| file | size (px) | shows | used by |
|---|---|---|---|
| apps/web/public/brand/wordmark.png | 720×240 | mark + "calevate" | `BrandWordmark` (auth pages, `components/authPage.tsx:76`); `BrandHeaderMark` from 640px up (marketing header, `marketing/siteHeader.tsx:99`) |
| apps/web/public/brand/lockup.png | 720×240 | mark + "calevate" + "AI VOICE CALLING AGENTS" | `BrandLockup`, marketing footer (`marketing/pageShell.tsx:230`) |
| apps/web/public/brand/calevate-full-logo-without-tagline.png | 2171×724 | mark + "calevate" | Organization logo in structured data (`lib/seo/structuredData.ts:110`) |
| apps/web/public/brand/calevate-full-logo-with-tagline.png | 2172×724 | mark + name + tagline | source file; not referenced in code |
| apps/web/public/brand/calevate-icon-logo-no-text.png | 1024×1024 | mark only | source file; not referenced in code |
| apps/web/public/brand/icon.png | 216×216 | mark only | `BrandIcon` (sidebars), `BrandHeaderMark` below 640px |
| apps/web/src/app/icon.png | 192×192 | mark only | browser favicon (Next file convention) |
| apps/web/src/app/apple-icon.png | 180×180 | mark only | iOS home-screen icon |
| apps/web/src/app/favicon.ico | 3.6 KB | mark only (by name; not opened) | browser tab icon |
| calevate-full-logo-with-tagline-final.png (repo root) | 2172×724 | name + tagline | byte-identical to the `public/brand` copy; not referenced |
| calevate-full-logo-without-tagline-final.png (repo root) | 2171×724 | name | byte-identical to the `public/brand` copy; not referenced |
| apps/web/src/app/opengraph-image.tsx | 1200×630, generated | the word "Calevate" as live text | link previews; no file to redraw, only the text (§1) |

The four mark-only files need new artwork only if the mark changes with the name. The
`public/brand/models/` and `services/` images are vendor logos, not ours. No image files are
tracked under `docs/design/`. Emails use no image: the header is the text `brand.PRODUCT`.
New files must keep the sizes `apps/web/tests/brand.test.tsx:38-40` checks (216×216, 720×240,
720×240), or the test changes with them.

---

## 11. What the founder must supply

1. NAME, exactly as written, and its lower-case form for file names and URLs.
2. SLUG for the "Why NAME" page (replacing `/why-calevate`).
3. TAGLINE (today "AI voice calling agents", in the lockup and email footer as
   "AI voice agents for Indian businesses").
4. ENTITY: the enterprise name on the new Udyam certificate.
5. UDYAM: the new Udyam registration number (and the certificate, as the source to cite).
6. FORM: the legal form of the new enterprise.
7. CITY and STATE to publish (city level only).
8. Arbitration seat and courts city, if not the same CITY.
9. GST: registered or not; if registered, GSTIN, state and the registered address for invoices
   (`gst_supplier_legal_name`, `gst_supplier_address`, GSTIN settings).
10. DOMAIN.
11. Mailboxes: support (sender and reply-to), grievance officer, data protection, security,
    ops, alerts. Today all four legal contact addresses are `calevate.voice@gmail.com`.
12. Contact phone, grievance officer name and data-protection contact name, if they change.
13. The effective date for the new revision of the legal set, after the lawyer's review.
14. Invoice serial prefix (keep `CAL` or a new one).
15. Artwork: wordmark 720×240, lockup with tagline 720×240, full logo with and without tagline
    (about 2170×724), and, if the mark changes, icon 1024×1024, 216×216, 192×192, 180×180
    and a favicon. Transparent PNG.
