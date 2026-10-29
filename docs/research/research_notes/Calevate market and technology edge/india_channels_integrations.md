# India channels, platforms and integrations for an AI voice/CRM product (as of Oct 2026)

All sources read 30 Oct 2026 unless stated. Evidence class follows CLAUDE.md hard rule 11:
**PRIMARY** = vendor or regulator page read this session; **SECONDARY** = third-party blog or press,
not checked against the primary; **UNKNOWN** = not found. Most India-specific numbers below are
SECONDARY. Meta's rate-card CSV/PDF for INR was **not** opened, so no ₹ figure here comes from Meta.

## 1. WhatsApp Business Platform: Calling API, pricing, Flows, payments, ads, AI

### Takeaway
The WhatsApp Business Calling API is a production feature (VoIP plus SIP, with OPUS and G.711 codecs).
India is not on its exclusion list, user-initiated calls are free, and business-initiated calls are billed
per 6-second pulse. This is the strongest new channel for a voice-agent product. Messaging moved to
per-message billing on 1 Jul 2025. On 1 Oct 2026 Meta started charging for service messages again
(1,000 free per number per month) and for utility messages sent inside the window. Meta also launched
its own "Meta Business Agent" AI, billed per token from 1 Jul 2026. That is a direct first-party
competitor for chat, but not for voice.

### Cited Findings
- **Calling API (PRIMARY)**
  - The API lets businesses make and receive VoIP calls with WhatsApp users. Business-initiated calling is available "every location Cloud API is available" except the US, Canada, Egypt, Vietnam and Nigeria. India is not excluded, but the business number's country code must be on a supported list that the page does not spell out. — [Meta Calling API docs](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/)
  - **Requirements:**
    - The number must be on Cloud API, not the WhatsApp Business app.
    - The business needs a messaging limit of at least 2,000 unique recipients per day.
    - Subscribe to the `calls` webhook (or use SIP).
    - The app needs the `whatsapp_business_messaging` permission.
    - Business-initiated calls need the user's call permission. — [same](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/)
  - **SIP:** supported with WebRTC media (TLS, ICE/DTLS/SRTP) or SDES SRTP. The default codec is OPUS, and PCMA/PCMU (G.711) were added on 23 Mar 2026. There is an Asterisk integration guide (29 Sep 2025). For an AI voice engine this is the bridging path. — [same](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/)
  - **Changelog:**
    - 5 Sep 2025: low-pickup restrictions took effect.
    - 13 Oct 2025: business-initiated limit raised to 10/day.
    - 19 Dec 2025: raised to 100/day.
    - 27 Jan 2026: user-feedback calling restrictions took effect.
    - The same page still says permission-request limits are "1 per day and 2 per week per business-user pair". That figure is internally inconsistent with the changelog, so confirm it. — [same](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/)
  - **Calling pricing (PRIMARY):**
    - "All user-initiated calls are free."
    - Business-initiated calls are billed in 6-second pulses by the called country code and a monthly volume tier.
    - Call-permission request messages are charged at message rates.
    - A payment method is required.
    - Current rate cards are effective 1 Apr 2026, and "Calling rates do not change on October 1, 2026".
    - Recording and transcription are free for now, with pricing coming later.
    - The India ₹/min figure is only in the rate-card file, which was not read (**UNKNOWN** here). — [Meta Calling pricing](https://developers.facebook.com/docs/whatsapp/cloud-api/calling/pricing/)
- **Messaging pricing model (PRIMARY):**
  - Per-message billing since 1 Jul 2025, charged only on delivery.
  - Categories: marketing, utility, authentication, service, and Meta Business Agent.
  - Service messages were free from 1 Nov 2024.
  - **From 1 Oct 2026** service messages are charged after 1,000 free per business phone number per month, with no rollover. Utility messages sent inside an open window, free since 1 Jul 2025, are also charged from that date. A payment method was required by 30 Sep 2026.
  - Click-to-WhatsApp ad entry windows (up to 7 days) stay free for marketing, utility, authentication and service messages.
  - 1 Jan 2026: higher India marketing rate, and India billing localisation to INR (migration due by 31 Dec 2026).
  - 1 Apr 2026: higher India authentication-international rate.
  - Meta changes rates only on 1 Jan, 1 Apr, 1 Jul or 1 Oct. — [Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing/)
- **Meta Business Agent (PRIMARY):** Meta's own AI replies in the service window from 1 Jul 2026, billed at $2.00 per million tokens (Meta's estimate is roughly 4–5 cents per message). It is not covered by the free entry-point window. — [Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing/)
- **Marketing Messages API:** Meta's pricing page mentions a max-price option for marketing messages from 2026. — [Meta pricing](https://developers.facebook.com/docs/whatsapp/pricing/). Frequency caps on marketing messages per user were not covered on that page (**UNKNOWN**).
- **India ₹ rates (SECONDARY, consistent across blogs):**
  - Marketing ₹0.8631 per message (said to be up about 10% on 1 Jan 2026 from ₹0.7846).
  - Utility and authentication ₹0.1150.
  - Plus 18% GST and the BSP's markup.
  - — [digitaltoolbox.in](https://digitaltoolbox.in/blog/whatsapp-business-api-pricing-india/); [splashifypro](https://splashifypro.com/blog/whatsapp-business-api-pricing-india-2026); [chatmitra](https://chatmitra.com/blog/whatsapp-business-cost-per-message/)
- **WhatsApp payments (SECONDARY):**
  - WhatsApp Pay handled 167M UPI transactions in a month in 2026, making it the 8th-largest UPI app and ahead of Cred and Amazon Pay. — [Business Today, 17 Aug 2026](https://www.businesstoday.in/personal-finance/story/whatsapp-pay-races-up-upi-charts-with-167-million-transactions-overtakes-cred-and-amazon-pay-549570-2026-08-17)
  - India lifted the user-cap curbs on WhatsApp payments in Dec 2024. — [TechCrunch, 31 Dec 2024](https://techcrunch.com/2024/12/31/india-lifts-whatsapp-payment-curbs/)
  - Bill payments through Bharat Connect (UPI, debit and credit cards). — [Inc42](https://inc42.com/buzz/whatsapp-takes-on-phonepe-google-pay-with-bill-payments-in-india/)
  - In-chat business payments (cards, netbanking, all UPI apps) run through partner gateways including Razorpay and PayU. — [Yahoo/Reuters](https://sg.news.yahoo.com/whatsapp-users-india-now-pay-054554132.html)
  - One guide says Meta Business Agent payments are "only for select businesses in India and Brazil" (from WhatsApp Help Center, not verified). — [SleekFlow](https://phrase-marketing.sleekflow.io/blog/whatsapp-pay-india)

### Inferences
- A WhatsApp voice channel is now practical. Because inbound calls are free to the business, adding a "Call us on WhatsApp" button plus a SIP bridge into the voice engine gives clients a free inbound line with no telecom numbering, DLT or spam-tag exposure. Whether ThinnestAI accepts SIP from Meta is not established here.
- Business-initiated WhatsApp calls depend on the user's opt-in permission and on pickup health, so they suit warm follow-ups rather than cold outbound.
- The 1 Oct 2026 service-message charge raises the running cost of a WhatsApp inbox. Each number's 1,000 free messages per month makes this small for SMBs. The 2,000-recipient tier needed for calling may exclude brand-new numbers.
- Meta Business Agent is first-party chat AI inside WhatsApp at about 4–5 cents per message. A text-only "AI on WhatsApp" proposition now competes with Meta itself. Voice plus CRM extraction is the differentiator.

### Gaps
- The India ₹/minute business-initiated calling rate is UNKNOWN: the INR rate card was not opened.
- Whether +91 numbers are on the calling country-code list was not stated in the text read.
- The current per-user call-permission request limit conflicts between the page body (1/day, 2/week) and the changelog (100/day).
- Marketing-message frequency caps per user in India: UNKNOWN.
- Flows and catalogue/commerce API changes in 2025-26 were not researched (tool budget).

## 2. RCS, SMS/DLT, Truecaller, CNAP and branded calling

### Takeaway
The biggest 2026 change is regulatory caller-name display. CNAP (Calling Name Presentation) is mandated
default-on for 4G and above **from 1 Nov 2026**, using the operator's KYC name, and businesses can apply
for a preferred name. That partly commoditises Truecaller's verified-caller pitch. RCS is live on Jio,
Airtel and Vi, but whether DLT applies to it is contested in secondary sources. Answer-rate uplift
claims for verified caller ID are vendor marketing only.

### Cited Findings
- **CNAP:**
  - A DoT circular dated 13 Oct 2026 directs operators to provide CNAP from **1 Nov 2026** "without the requirement of any separate request from such user".
  - 2G, 3G and landline are excluded for now.
  - The March 2026 deadline was missed, and BSNL's rollout was months behind. — [ThePrint](https://theprint.in/india/no-more-unknown-callers-govt-makes-caller-name-display-mandatory-from-1-november/3072774/)
  - The name comes from the originating operator's subscriber records, and a saved contact overrides it. Businesses can apply to show a verified preferred name; the procedure was not found. — [Outlook Money](https://www.outlookmoney.com/news/caller-name-display-on-mobile-networks-to-be-mandatory-in-india-from-november-1)
  - The earlier March 2026 target. — [Business Standard, Oct 2025](https://www.business-standard.com/industry/news/cnap-service-nationwide-rollout-by-march-2026-dot-trai-telecom-125102901190_1.html)
- **Truecaller for Business:**
  - Verified Business Caller ID shows the brand name, logo and an optional call reason before the call is answered. — [Exotel developer docs](https://developer.exotel.com/docs/call-support/advanced-features/truecaller-verified-caller-id)
  - Pickup uplift "up to 52%" is an unverified vendor claim. — [Ameyo](https://www.ameyo.com/solutions/truecaller-verified-brand-identity)
  - Exotel shows answer-rate bands of 20–35% vs 45–65% without clear labels and advises measuring verified against unverified numbers. — [Exotel](https://developer.exotel.com/docs/call-support/advanced-features/truecaller-verified-caller-id)
  - No independent study was found.
- **RCS (SECONDARY):**
  - Live on Jio, Airtel and Vi through Google Jibe; BSNL lags. — [bonvoice](https://bonvoice.com/insights/rcs-business-messaging-in-india/)
  - Airtel is reported at about ₹0.11 per basic RCS message under a 2026 Google deal. — [bonvoice](https://bonvoice.com/insights/rcs-business-messaging-in-india/)
  - Sources conflict on DLT. Some say RCS sits outside DLT and only the SMS fallback needs DLT templates; others say commercial RCS falls under DLT. — [bonvoice](https://bonvoice.com/insights/rcs-business-messaging-in-india/); [messagebot](https://messagebot.in/blog/rcs-messaging-in-india/)
- **Google Business Messages / GBP chat:** retired 31 Jul 2024. — [Google developer release notes](https://developers.google.com/business-communications/business-messages/resources/release-notes/update-on-gbm)

### Inferences
- From 1 Nov 2026, outbound calls from an SMB's KYC'd number will show the registered entity name by default on 4G and above. Making sure clients' numbers are registered in the right business name (and the preferred-name application, once its procedure is known) may matter more for answer rate than a paid Truecaller badge. Truecaller remains additive for the call-reason and logo display.
- SMS remains the fallback that needs DLT; RCS needs DLT plus Google agent verification. Adding SMS means DLT entity, header and template registration per client, which is the PE/TM model already in Calevate's vocabulary.

### Gaps
- The CNAP preferred-name procedure for businesses, its cost, and whether CNAP shows the name for 1600 and 140 numbers: UNKNOWN.
- Any measured, non-vendor answer-rate uplift from verified caller ID in India: none found.
- Primary TRAI position on DLT for RCS: not found.

## 3. Lead sources with instant-push APIs

### Takeaway
IndiaMART is the only major Indian marketplace with a documented, self-serve real-time **Push API**
(webhook) that we found. 99acres and MagicBricks push to a URL that their account manager configures,
and some need a premium plan. JustDial delivers leads mainly by email/SMS or via an account-manager
webhook. No public docs were found for Housing.com, NoBroker, Sulekha or Practo.

### Cited Findings
- **IndiaMART:**
  - The Lead Manager CRM **Push API** sends each lead in real time to your listener URL.
  - Enable it under Lead Manager → Import/Export Leads → Push API, with OTP to the primary mobile.
  - API Hit Logs show per-lead delivery status. — [IndiaMART help (PRIMARY)](https://help.indiamart.com/knowledge-base/integration-of-indiamarts-lead-manager-crm-push-api-with-third-party-crms-real-time-push-of-leads)
  - A separate **Pull API** exists for paid accounts. — [IndiaMART help](https://help.indiamart.com/knowledge-base/lms-crm-integration-v2)
- **JustDial (SECONDARY):** a webhook is usually set up by the JustDial account manager, with no self-serve screen. — [edesy](https://edesy.in/blog/call-indiamart-justdial-leads-ai-voice-2026). Another source says leads arrive mainly by email/SMS and are often handled by parsing emails. — [vedain](https://vedain.com/blog/indiamart-leads-automatic-crm). No official API doc was found.
- **99acres:**
  - The CRM gives 99acres a base URL and API key, and 99acres pushes leads to it. — [Sell.Do support](https://support.sell.do/support/solutions/articles/6000068700-99acres-integration); [Anarock](https://support.anarock.com/support/solutions/articles/35000226722-99acres-push-integration)
  - The URL must be sent to the 99acres account manager. — [Pabbly](https://www.pabbly.com/how-to-add-99acres-leads-to-your-crm-using-pabbly-connect/)
  - A premium account is needed. — [Corefactors](https://www.corefactors.ai/blogs/99-acres-integration-and-auto-lead-capture)
- **MagicBricks:** the same account-manager flow as 99acres. — [Pabbly](https://www.pabbly.com/send-real-estate-leads-to-crm-automatically/)
- **Housing.com:** no integration docs found beyond a mention by Corefactors. — [Corefactors](https://www.corefactors.ai/integrations/99acres)

### Inferences
- The common pattern is a per-portal inbound webhook endpoint plus an API key that the client hands to the portal's account manager. Calevate's signed-webhook and website-form intake could expose a generic "portal push" URL per tenant with a portal-specific field mapper. IndiaMART is a self-serve quick win that suits manufacturers and traders.
- Middleware (Pabbly, n8n) is how most SMBs bridge portals today. Supporting it, or replacing it, is a competitive angle.

### Gaps
- Google Ads lead-form webhook and Google Business Profile lead APIs: not verified this session (the search returned nothing relevant).
- Sulekha, NoBroker, Housing.com, Practo, Justdial official APIs: UNKNOWN.

## 4. CRMs and ERPs popular with Indian SMBs: API availability

### Takeaway
LeadSquared publishes a full developer centre with lead APIs and a webhook-creation API. Kylas supports
webhooks. Official API docs for TeleCRM and Bigin were not surfaced in this pass. Shopify COD
confirmation by AI voice, writing back order tags, is a crowded vendor category with unverified RTO claims.

### Cited Findings
- **LeadSquared (PRIMARY docs):**
  - Webhooks for lead create, task update, user create and similar events, plus a Create Webhook API. — [LeadSquared Developer Centre](https://apidocs.leadsquared.com/create-a-webhook/)
  - Caveat: leads updated through the Update Lead API do not fire update-based webhooks or automations by default. — [LeadSquared](https://apidocs.leadsquared.com/update-a-lead/)
  - The API host is region-specific, and the wrong host returns 401 (SECONDARY). — [rapidevelopers](https://www.rapidevelopers.com/md/retool-integrations/leadsquared)
  - LeadSquared also sells a 99acres integration. — [LeadSquared](https://www.leadsquared.com/99acres-integration/)
- **Kylas:** webhooks are configured under CRM settings → Integrations → Webhooks. — [Kylas support](https://support.kylas.io/portal/en/kb/articles/how-to-setup-lead-re-engagement-flow-in-kylas)
- **Shopify and Shiprocket COD confirmation (SECONDARY):**
  - The pattern is a Shopify order webhook, then an AI call, then a write-back that tags the order confirmed or cancelled. — [Caller Digital](https://caller.digital/integrations/shopify)
  - Shiprocket webhooks are said to include Out for Delivery, RTO Initiated and RTO Delivered (not checked against Shiprocket docs). — [codingclave](https://codingclave.com/integrations/shiprocket-integration)
  - RTO reduction claims range from 30–45% to "30% to 18%", all vendor marketing. — [Caller Digital](https://caller.digital/ai-voice-bot-for-cod-verification); [edesy](https://edesy.in/ai-voice-assistant/integrations/shiprocket)

### Inferences
- The next CRM pushes after Zoho and HubSpot should be LeadSquared, the dominant India mid-market CRM in education and real estate with documented APIs, then Kylas. COD confirmation for Shopify D2C is a well-defined, webhook-driven outbound use case, but it is crowded.

### Gaps
- TeleCRM, Bigin (Zoho), Freshsales, Sell.Do (beyond portal intake), Tally, Vyapar, Odoo and Practo/clinic APIs were not verified this pass.

## 5. Payments by voice: UPI AutoPay, payment links, collections

### Takeaway
UPI AutoPay is the recurring rail: a one-time PIN mandate, a ₹15,000 per-debit cap without extra
authentication, and a higher cap for approved categories. All figures here are secondary. Payment links
sent during a call over WhatsApp or SMS, which Calevate already has with Razorpay, remain the standard
voice-to-pay path.

### Cited Findings
- The standard AutoPay limit is ₹15,000 per transaction without additional authentication; approved categories (mutual funds, insurance, credit card bills, loan EMIs) go up to ₹1,00,000. One vendor cites higher figures, so the upper bound is unclear. — [Analytics Insight](https://www.analyticsinsight.net/news/upi-autopay-explained-how-rs-1-lakh-recurring-payments-work); [Cashfree](https://www.cashfree.com/en/upi-autopay/)
- About 20M AutoPay revocations a month because of low customer balance. — [Business Standard, Sep 2025](https://www.business-standard.com/amp/finance/news/upi-autopay-revocations-hit-20-mn-monthly-over-low-customer-balances-125090700500_1.html)
- Customers can pause or revoke a mandate from their UPI app. — [Zoho Payments academy](https://www.zoho.com/payments/academy/payment-processing/upi-autopay-mandates-and-recurring-debits.html)

### Inferences
- Collections and renewal reminder calls before an AutoPay debit, given the revocations from low balances, are a plausible voice use case. Setting up an AutoPay mandate needs a PIN in the UPI app, so voice can only send the link.

### Gaps
- NPCI and RBI primary circulars on 2026 limits and the e-mandate framework were not read. PhonePe and Cashfree payment-link API specifics were not checked.

## 6. Telephony in India: 1600/140 series, SIP, spam tagging

### Takeaway
TRAI requires **140xx numbers for promotional calls by entities of any sector** and reserves **1600xx
for service and transactional calls** (deadlines phased in for BFSI). TRAI's July 2026 clarification says
tagging, blocking or filtering of 1600 calls is not permitted. Calls to and from Indian numbers must
enter and leave the PSTN through licensed operators. Primary DoT text on SIP trunking was not found.

### Cited Findings
- TRAI Press Release 91/2026 (10 Jul 2026) clarifies the 1600 and 140 series. It says tagging, blocking or filtering 1600-series calls "is not permitted under TCCCPR" and that TRAI "has mandated use of 140xx series numbers for making promotional calls by entities of any sector". This was read via SECONDARY sources: the PDF is a scanned image that did not parse. — [SCC Online, 18 Jul 2026](https://www.scconline.com/blog/post/2026/07/18/trai-clarifies-1600-and-140-series-number-framework/); [TRAI PR 91/2026 (scanned PDF)](https://trai.gov.in/sites/default/files/2026-07/PR_No91of2026.pdf)
- 1600 adoption deadlines by sector (SECONDARY): commercial banks 1 Jan 2026; large NBFCs, payment banks and small finance banks 1 Feb 2026; insurers and mutual funds 15 Feb 2026. — [Outlook Business](https://www.outlookbusiness.com/news/trai-sets-firm-deadlines-for-bfsi-entities-to-adopt-1600-series-for-service-transactional-calls); [TRAI PR 135/2025](https://trai.gov.in/sites/default/files/2025-11/PR_No.135of2025.pdf) (not opened)
- Calls to and from Indian numbers must enter and leave the PSTN through DoT-licensed operators or VNOs (SECONDARY, vendor blog). — [edesy](https://edesy.in/blog/sip-trunk-providers-india-ai-calling-2026)

### Inferences
- An SMB's outbound promotional AI calls (campaigns) belong on 140-series numbers, and service follow-ups to existing customers may qualify for 1600 numbers if those become available to non-BFSI entities. The fact that 1600 calls cannot be tagged or blocked is a strong answer-rate lever. Whether SMBs outside BFSI can obtain 1600 numbers is not established.
- Calevate's ThinnestAI-hosted numbers sit under ThinnestAI's licensing. Which number classes (10-digit, 140, 1600) ThinnestAI can provision is a vendor question, not answered here.

### Gaps
- Whether 1600 numbers are available to non-BFSI SMBs, and how: UNKNOWN.
- Primary DoT SIP-trunk and OSP rules for 2025-26, and spam-tagging statistics for AI calls: not found.
- Answer rates for 10-digit vs 140 vs 1600 numbers: no data found.
