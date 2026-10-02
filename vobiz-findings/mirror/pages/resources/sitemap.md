> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Documentation Sitemap

> Every page in the Vobiz documentation, grouped as it appears in the sidebar, with a one line summary of each - 481 pages across the guides, API reference, integrations, tutorials, and blog, so you (or your AI agent) can find the right page in one look.

A complete, always-current index of the Vobiz documentation: **481 pages**, grouped exactly as they appear in the sidebar, each with a one line summary.

<Info>
  Machine-readable versions of this index: [`sitemap.xml`](https://vobiz.ai/docs/sitemap.xml) for crawlers, [`llms.txt`](https://vobiz.ai/docs/llms.txt) for AI agents, and [`llms-full.txt`](https://vobiz.ai/docs/llms-full.txt) for the full text of every page in one file. Agents can also query the docs live over the [MCP server](/docs/resources/mcp) or install the [agent skills](/docs/resources/skills).
</Info>

| Section | Pages |
| - | - |
| Documentation | 76 |
| API Reference | 258 |
| Integrations | 66 |
| Examples & Tutorials | 56 |
| Blogs | 25 |
| **Total** | **481** |

## Documentation

### Getting Started

* [Vobiz – Global SIP Trunking & Voice API Platform](/docs/introduction) — Vobiz is a developer-first telephony platform with global SIP trunking and voice APIs in 130+ countries - native integrations with Vapi, Retell..
* [Quick Start – Make Your First Vobiz Call](/docs/quick-start) — Set up Vobiz and make your first call in under 5 minutes - connect an AI voice agent via Vapi or Retell, configure a SIP trunk, or build a..
* [Vobiz API Authentication – X-Auth-ID & X-Auth-Token](/docs/api-reference/authentication) — Authenticate Vobiz API requests with X-Auth-ID and X-Auth-Token headers, or use a supported account Bearer access token for capacity subscription..
* [Buy a Phone Number on Vobiz – Step-by-Step Guide](/docs/buy-a-phone-number) — A complete, step-by-step guide to buying a phone number (DID) on Vobiz - in the console and via the API
* [Vobiz API Error Handling – Status Codes & Response Formats](/docs/errors) — Every Vobiz API error returns a consistent JSON payload with error codes, HTTP status, and messages - reference this guide to handle auth failures..

### Core Concepts

* [Vobiz Platform Concepts – SIP, WebSocket & Voice API Architecture](/docs/concepts) — Master core Vobiz telephony concepts - SIP signaling, RTP media, WebSocket streaming, callbacks, and when to choose SIP vs WebSockets for AI voice..
* [SIP Trunking](/docs/concepts/sip-trunking) — SIP is the signaling standard behind nearly every modern phone call
* [Bring Your Own Carrier (BYOC)](/docs/concepts/bring-your-own-carrier) — Connect your existing carrier, SBC, or PBX to Vobiz
* [Voice streaming over WebSockets](/docs/concepts/streaming-websockets) — Understand how Vobiz sends inbound call audio to your WebSocket application and receives independent outbound playback audio
* [SIP vs WebSockets](/docs/concepts/sip-vs-websockets) — Compare SIP and WebSocket architectures for connecting phone calls to AI voice agents - pick the right fit for latency, cost, and deployment speed
* [Vobiz Webhooks (Callbacks) – Real-Time Event Notifications](/docs/concepts/callbacks) — Vobiz webhooks (callbacks) are HTTP POST requests sent to your server when call, recording, conference, and message events occur - enabling real-time..
* [Vobiz Webhook (Callback) Configuration](/docs/concepts/callback-configurations) — Configure Vobiz webhook (callback) URLs across resources to receive real-time event notifications for calls, conferences, recordings, and more
* [Validating Callbacks](/docs/concepts/validating-callbacks) — Verify that every callback your server receives genuinely came from Vobiz by checking the HMAC signatures sent in each request
* [IP Address Whitelisting](/docs/concepts/ip-whitelisting) — Whitelist these IP addresses on your firewall to ensure uninterrupted SIP signaling, RTP media, WebSocket streaming, and callback delivery between..
* [Voice API Hangup Causes – Codes & Troubleshooting](/docs/concepts/hangup-causes) — Reference every Vobiz hangup code, cause, and source - decode why a call disconnected from the call detail record or hangup callback, and follow the..

### Best Practices

* [Vobiz Integration Best Practices – Security, Reliability & Performance](/docs/best-practices) — Secure, reliable, and high-performance Vobiz integrations start here
* [How an Outbound Campaign Manager Works (2026 Guide)](/docs/best-practices/outbound-campaign-manager) — A vendor-neutral guide to outbound campaign managers - the dial lifecycle, carrier reputation, number rotation, daily caps, cooldown, retry policy..
* [Number Utilization Guide](/docs/best-practices/number-utilization) — Maximize call connectivity, reduce spam flagging, and maintain TRAI compliance with these Vobiz number utilization best practices for Indian..
* [Number Health Guide](/docs/best-practices/number-health-guide) — Keep your caller-ID (DID) numbers healthy for high-volume outbound voice - pickup/answer rate, pacing & CPS, repeat-dial limits, ring time, inbound..
* [DLT Entity Registration Guide](/docs/best-practices/dlt-registration) — Step-by-step DLT registration and compliance process on Vobiz - Principal Entity, header, content template, and consent template approval for India..
* [140 & 160 Series Number Acquisition Guide](/docs/best-practices/140-160-acquisition) — Acquire TRAI-regulated 140 and 160 series numbers on Vobiz - covers eligibility, required documents, use-case scenarios, and 2025 compliance..
* [DID Provisioning Process for 140 & 160 Series](/docs/best-practices/did-provisioning) — Client onboarding guide for provisioning 140 and 160 series DID numbers on Vobiz - PE certificate, LOI, TM ID header registration, NOC-based DLT..
* [92 Series Number Guide](/docs/best-practices/92-series-guide) — Acquire and manage 92-series mobile-format numbers on Vobiz for India - higher consumer pickup rates, mandatory per-number Aadhaar (KYC)..

### Using Vobiz Platform

* [Vobiz Console Login & Signup - Sign In or Create Your Voice Infrastructure Account](/docs/platform/login) — Sign in to console.vobiz.ai or create a new Vobiz account
* [Dashboard](/docs/platform/dashboard) — A tour of the Vobiz Console dashboard - KPI cards, usage and cost charts, inbound vs outbound activity, API credentials, capacity limits, and the..
* **Voice Applications**
  * [Voice Applications - Overview](/docs/platform/voice/overview) — The Voice Applications hub in the Vobiz Console - usage summary, call analytics, API credentials, and quick links to every voice resource (apps..
  * [XML Applications - Create & Manage Voice Apps](/docs/platform/voice/applications) — Build XML applications in the Vobiz Console - point Answer and Hangup webhooks at your server, attach phone numbers, and serve programmable call..
  * [SIP Endpoints - Softphone & WebRTC Logins](/docs/platform/voice/endpoints) — Create SIP endpoints in the Vobiz Console for softphones, Zoiper, and custom WebRTC clients
  * [How to Receive an Inbound Call in Your Browser](/docs/guides/receive-inbound-call) — Answer a call to your Vobiz number in the browser using the WebRTC Playground - connect with your Auth ID and Auth Token, attach the DID to the Vobiz..
  * **Logs**
    * [Voice Call Logs - Per-Call Records & Quality Metrics](/docs/platform/voice/call-logs) — Browse every voice call in the Vobiz Console - MOS scores, call timeline, hangup cause, SIP details, and CSV export
    * [Call Recordings - Playback, Transcripts & AI Insights](/docs/platform/voice/recordings) — Browse, play, and download call recordings (WAV / MP3) in the Vobiz Console
  * [Campaigns - Launch & Manage Outbound Runs](/docs/platform/campaigns/list) — Create outbound campaigns in the Vobiz Console - set CPS and concurrency, pick caller IDs with Round Robin / Least Used / Random rotation, upload a..
  * [Campaign Agents - Reusable Webhook Configs](/docs/platform/campaigns/agents) — Create reusable Campaign Agents in the Vobiz Console - shared answer/hangup webhook configurations used by one or more outbound campaigns
  * [Campaign Call Logs - Per-Attempt Outbound History](/docs/platform/campaigns/call-logs) — Every attempt placed by every Vobiz campaign - answered, busy, no answer, failed - with attempt number, duration, cost, and Call UUID
* **SIP Trunking**
  * [SIP Trunking Overview - Global Voice Connectivity](/docs/platform/sip/overview) — The SIP Trunking hub in the Vobiz Console - usage tiles, outbound termination, inbound origination, and end-to-end how-it-works diagrams
  * **Outbound Trunks**
    * [Outbound Trunks - SIP Termination from Your PBX](/docs/platform/sip/outbound-trunks) — Create and manage outbound SIP trunks in the Vobiz Console - IP or credential auth, per-trunk call recording, AI transcription, PII redaction, and..
    * [IP Access Control List (ACL) - Whitelist PBX Source IPs](/docs/platform/sip/ip-access-control-list) — Create IP Access Control Lists in the Vobiz Console to authorise specific source IPs or CIDR ranges to send SIP traffic to your outbound trunks
    * [SIP Credentials List - Username & Password Auth](/docs/platform/sip/credentials) — Create SIP credentials in the Vobiz Console - username and password pairs that authorise PBX traffic to your outbound trunks
  * **Inbound Trunks**
    * [Inbound Trunks - Receive PSTN Calls](/docs/platform/sip/inbound-trunks) — Create and manage inbound (origination) SIP trunks in the Vobiz Console - deliver incoming calls to your PBX or AI agent via a Primary URI, with..
    * [Origination URI - SIP Destinations for Inbound Calls](/docs/platform/sip/origination-uri) — Manage SIP Origination URIs in the Vobiz Console - the destination addresses (host:port + transport) Vobiz forwards inbound PSTN calls to
  * **Logs**
    * [SIP Call Logs - Per-Call Records & Quality](/docs/platform/sip/call-logs) — Browse every SIP trunk call in the Vobiz Console - MOS scores, call timeline, hangup cause, transcription, recording playback, and CSV export
    * [SIP Call Recordings - Playback, Transcription & AI Insights](/docs/platform/sip/recordings) — Browse, play, and download SIP trunk call recordings in the Vobiz Console
* **Phone Numbers**
  * [Buy a Number - Numbers Inventory](/docs/platform/numbers/buy) — Buy a phone number in the Vobiz Console - browse the inventory by country, number type, region and series, read the monthly + setup + release..
  * [My Numbers - Your Number Inventory](/docs/platform/numbers/my-numbers) — Manage the phone numbers on your Vobiz account - filter by status, type and link state, see which voice app or trunk each number routes to, check..
* [Sub-Accounts - Child Accounts, Credentials & Number Assignment](/docs/platform/subaccounts) — Create and run sub-accounts in the Vobiz Console - child accounts with their own Auth ID and Auth Token, inherited or independent KYC, token rotation..
* **Capacity**
  * [CPS - Buy Call-Initiation Throughput](/docs/platform/capacity/cps) — Buy calls-per-second capacity in the Vobiz Console - what CPS controls, when to raise it, how the blocks-of-three pricing works, and how to preview\..
  * [Concurrency - Buy Simultaneous Call Capacity](/docs/platform/capacity/concurrency) — Buy concurrent-call capacity in the Vobiz Console - what concurrency controls, the busy-signal symptom of hitting the ceiling, how the blocks-of-ten..
  * [My Subscriptions - Manage Capacity Subscriptions](/docs/platform/capacity/subscriptions) — Review and cancel the CPS and concurrency subscriptions on your Vobiz account - quantity, monthly cost, next billing date, and status for every..

### Compliance (India)

* [India Calling Regulations](/docs/compliance/india/calling-regulations) — Regulatory requirements, eligibility rules, and compliance setup for domestic voice calling within India on Vobiz - DLT, KYC, and TRAI guidelines
* [India Number KYC](/docs/compliance/india/kyc) — Verify your identity or business to start renting Indian phone numbers
* [UCC & NDNC Compliance](/docs/compliance/india/ucc) — NDNC/DND registry, UCC complaints, and TRAI enforcement for Indian voice numbers - how Vobiz enforces the Do Not Call list and what to do when a..

### FAQ

* [Vobiz FAQ – Billing, API Limits, SIP Trunking & Integrations](/docs/faq) — Quick answers on Vobiz accounts, billing, concurrency limits, SIP trunking, AI voice integrations, and global compliance
* [Can I connect my trial number for inbound calls?](/docs/faq/trial-inbound) — Vobiz trial numbers are outbound-only - understand why inbound routing is restricted on trial accounts and the exact steps to unlock it on a verified..
* [Why am I receiving SIP response codes 480 or 486?](/docs/faq/sip-codes-480-486) — SIP 480 and 486 errors on Vobiz indicate the callee is unavailable or busy - learn what triggers each code, how to read CDRs, and how to debug..
* [Why am I receiving a 429 error?](/docs/faq/error-429) — A Vobiz 429 Too Many Requests error means you have hit a concurrency or CPS limit - find out which limit is breached and the exact steps to fix it
* [What is Concurrency?](/docs/faq/concurrency) — Concurrency on Vobiz defines how many calls run simultaneously on your account - understand channel limits, what triggers a 429 error, and how to..
* [What is CPS (Calls Per Second)?](/docs/faq/cps) — CPS on Vobiz controls how fast you can initiate calls, independent of concurrency - learn how CPS rate limiting works and how to pace outbound..
* [Can I purchase additional Concurrency or CPS?](/docs/faq/purchase-concurrency-cps) — Upgrade your Vobiz concurrency and CPS limits through the dashboard to scale outbound campaigns and handle thousands of simultaneous calls..
* [Do you provide 140, 160, and 92 series numbers?](/docs/faq/number-series) — Vobiz provisions 140, 160, and 92-series numbers for India - learn the TRAI-regulated use case for each series, mobile pickup rate advantages, and..
* [What integrations do you support?](/docs/faq/integrations) — Vobiz natively supports LiveKit, Pipecat, Retell AI, ElevenLabs, VAPI, and SIP PBX systems - connect any AI voice agent or WebRTC stack to the global..
* [Is call transfer supported?](/docs/faq/call-transfer) — Vobiz supports three call transfer methods - Dial XML, REST API live transfer, and SIP REFER (RFC 3515) - covering warm transfers, cold transfers..
* [Do you support IVR?](/docs/faq/ivr) — Build fully programmable IVR menus on Vobiz using Gather, Speak, Play, and SIP transfer XML - supporting DTMF input, speech recognition, and dynamic..
* [What documents are required for verification?](/docs/faq/verification-docs) — Complete Vobiz KYC verification with GST certificate for organizations or Aadhaar and PAN for individuals - required before purchasing live numbers..
* [How can I contact support?](/docs/faq/contact-support) — Contact the Vobiz engineering and success teams via email for API integration help, network debugging, capacity upgrades, and billing - with tips for..
* [Domestic Calling in India](/docs/faq/domestic-calling-india) — Use Vobiz domestic calling for IN-to-IN traffic to get lower latency, guaranteed local caller ID, INR billing, and better audio quality than..

### Tools

* [CPS & Cost Calculator](/docs/resources/calculator) — Estimate Calls Per Second, simultaneous concurrency, and capacity requirements for your voice campaigns
* [Vobiz Visual XML Builder – Compose Voice Call Flows](/docs/xml-builder) — Compose Vobiz Voice XML visually - pick verbs, reorder them, and configure attributes with a live preview
* [Stream Events Visualizer](/docs/resources/stream-events-visualizer) — Step through the Vobiz bidirectional Stream WebSocket lifecycle and inspect start, media, playback, checkpoint, barge-in, and stop events
* [Dial XML Transfer Visualizer](/docs/resources/dial-transfer-visualizer) — Step through a Vobiz call transfer: a caller reaches your AI agent, Dial rings a human on standby, and the human accepts or rejects
* [Gather XML Input Visualizer](/docs/resources/gather-visualizer) — Walk a Gather from prompt to action URL. Press the dial pad, watch which of the four terminators wins - numDigits, finishOnKey, digitEndTimeout or..
* [SIP Trunk vs WebSocket Visualizer](/docs/resources/sip-vs-websocket-visualizer) — Step through both Vobiz connectivity paths side by side - a SIP trunk authenticated by IP ACL or SIP credentials, and a WebSocket app driven by your..
* [CPS & Concurrency Visualizer](/docs/resources/cps-concurrency-visualizer) — Dial calls onto a live board second by second and hit both Vobiz limits yourself - CPS caps how fast you start calls, concurrency caps how many run..
* [Bulk and batch operations](/docs/resources/bulk-operations) — Every bulk and batch capability in Vobiz in one place - multi-destination bulk dialing, batch CSV campaigns, bulk CDR and recording exports, batched..
* [Vobiz MCP Server](/docs/resources/mcp) — Connect Claude, Cursor, VS Code, and other AI clients directly to the Vobiz documentation through the Model Context Protocol (MCP)
* [Vobiz Agent Skills](/docs/resources/skills) — Install the Vobiz agent skills into Claude Code, Codex, and 40+ other coding agents with one command, so your AI assistant knows how to drive the..
* [Vobiz Documentation Sitemap](/docs/resources/sitemap) — Every page in the Vobiz documentation, grouped as it appears in the sidebar, with a one line summary of each

## API Reference

### Regular APIs

* [Vobiz API Reference – Voice, SIP, Numbers & WhatsApp](/docs/api-reference) — Use the Vobiz API reference to build voice calls, SIP trunks, phone-number workflows, audio streams, WhatsApp messaging, and account automation
* [Vobiz API Versioning & Deprecation Policy](/docs/api-reference/versioning) — How Vobiz versions the REST API, which changes are additive versus breaking, and the deprecation lifecycle with Deprecation and Sunset response..

#### Account

* [Vobiz Account API – Manage Balance, Credentials & Concurrency](/docs/account) — Manage your Vobiz account via REST API - retrieve balance, concurrency limits, CPS, auth credentials, and billing mode for prepaid or postpaid plans..
* [The Account Object](/docs/account/account-object) — Explore every field in the Vobiz Account object - auth\_id, pricing tier, CPS limits, concurrency caps, IP whitelist, and verification status for..
* [Retrieve Account Details](/docs/account/retrieve-account) — Fetch complete Vobiz account details - auth credentials, pricing tier, verification status, and contact info - with a single authenticated GET..
* [Balance](/docs/account/balance) — Check your Vobiz account balance by currency - available balance, reserved funds, promotional credit, credit limit, and low-balance thresholds
* [Transactions](/docs/account/transactions) — Retrieve a full Vobiz transaction ledger - credits, debits, call charges, DID rentals, and invoice history with per-day totals and reference-type..
* [Concurrency](/docs/account/concurrency) — Retrieve real-time concurrent call usage for your Vobiz account - monitor active channels, check capacity headroom, and scale voice infrastructure..
* [Preview CPS and concurrency pricing](/docs/account/channel-pricing-preview) — Calculate the monthly price for additional Vobiz CPS or concurrent-call capacity without purchasing capacity or debiting the account
* [Purchase CPS or concurrency capacity](/docs/account/channel-subscriptions) — Purchase recurring Vobiz CPS or concurrent-call capacity and activate a channel subscription that renews every 30 days
* [NDNC Webhook](/docs/account/ndnc-webhook) — Receive real-time UCC / NDNC complaint alerts on your own HTTPS endpoint

#### Sub-Accounts

* [Vobiz Sub-Accounts API – Multi-Tenant & Reseller Account Management](/docs/sub-accounts) — Provision and manage isolated customer sub-accounts under a Vobiz parent account - segmented billing, independent credentials, and usage tracking for..
* [Sub-Account Onboarding Flow](/docs/sub-accounts/onboarding-flow) — End-to-end example: create a customer\_use sub-account, complete KYC, buy and assign a number, and place the first call - with explicit guidance on..
* [The Subaccount Object](/docs/sub-accounts/subaccount-object) — Explore the Vobiz Subaccount object schema - auth credentials, permissions, rate limits, SA\_ identifier format, and tenant isolation under a parent..
* [Create a Subaccount](/docs/sub-accounts/create-subaccount) — Provision an isolated Vobiz subaccount with its own auth credentials for multi-tenant SaaS apps, white-label resellers, or departmental resource..
* [Retrieve a Subaccount](/docs/sub-accounts/retrieve-subaccount) — Fetch the full details of a specific Vobiz subaccount by its sub\_auth\_id - credentials, permissions, rate limits, and current status for a single..
* [Update a Subaccount](/docs/sub-accounts/update-subaccount) — Update any fields on a Vobiz subaccount - rename it, toggle enabled status, adjust rate limits, or modify permissions
* [Delete a Subaccount](/docs/sub-accounts/delete-subaccount) — Permanently delete a Vobiz subaccount and revoke its authentication credentials - irreversible operation for offboarding tenants or closing reseller..
* [List All Subaccounts](/docs/sub-accounts/list-all-subaccounts) — Retrieve a paginated list of all Vobiz subaccounts sorted by creation date - enumerate tenants across your multi-tenant SaaS or reseller platform
* [Assign DID to Sub-Account](/docs/account-phone-number/assign-subaccount) — Assign a parent-pool DID to one of your sub-accounts so it can place and receive calls on that number
* [Unassign DID (15-Day Cool-Off)](/docs/account-phone-number/unassign-subaccount) — Move a DID back to the parent pool. A 15-day cool-off blocks numbers that had a call in the last 15 days; admins can bypass with force=true
* **KYC**
  * [Sub-Account KYC](/docs/sub-accounts/kyc/overview) — Verify customer\_use sub-accounts with per-document KYC - PAN, GST, CIN, and Aadhaar via DigiLocker - or hand off to a Vobiz-hosted KYC session
  * [Get KYC Status](/docs/sub-accounts/kyc/kyc-status) — Retrieve the aggregated KYC state for a customer\_use sub-account - which verifications have passed, whether calls are still blocked, and the business..
  * [Verify PAN](/docs/sub-accounts/kyc/verify-pan) — Run a real-time PAN verification for a customer\_use sub-account
  * [Verify GST](/docs/sub-accounts/kyc/verify-gst) — Run a real-time GSTIN verification for a customer\_use sub-account using a 15-character GSTIN
  * [CIN Search](/docs/sub-accounts/kyc/cin-search) — Look up a company's CIN by name. Returns candidate matches to confirm in the next step
  * [CIN Confirm](/docs/sub-accounts/kyc/cin-confirm) — Confirm the CIN selected from the search results to complete company identity verification
  * [DigiLocker Initiate](/docs/sub-accounts/kyc/digilocker-initiate) — Start a DigiLocker-based Aadhaar verification - returns the authorization link and an access\_request\_id for the customer to complete OAuth
  * [DigiLocker Verify](/docs/sub-accounts/kyc/digilocker-verify) — Finalize Aadhaar verification via DigiLocker after the customer completes the OAuth flow
  * [Create KYC Session](/docs/sub-accounts/kyc/kyc-session) — Hand off sub-account KYC to a Vobiz-hosted widget - either email the customer a signed link or redirect them inline
  * [KYC Email Flow with Webhook](/docs/sub-accounts/kyc/email-flow-webhook) — Start a hosted sub-account KYC via email link and register a webhook to receive status updates - create the session, the events Vobiz POSTs, and how\..
  * [KYC Redirect Flow with Webhook](/docs/sub-accounts/kyc/redirect-flow-webhook) — Start a hosted sub-account KYC via redirect - get a widget\_url back, redirect the customer yourself, and register a webhook for status updates
  * [KYC Test Mode](/docs/sub-accounts/kyc/test-mode) — Build and test your sub-account KYC integration without real documents

#### Phone Numbers

* [Vobiz Phone Numbers API – Buy, Manage & Release DIDs Globally](/docs/account-phone-number) — Buy, manage, and release virtual phone numbers globally via the Vobiz API - covering India DIDs, 160 series, 140 series, E.164 numbers across 130+..
* [The PhoneNumber Object](/docs/account-phone-number/account-phone-number-object) — Every Vobiz phone number is modeled as a PhoneNumber object holding capabilities, billing, E.164 format, status, and assignment details for voice..
* [List Account Phone Numbers](/docs/account-phone-number/list-account-phone-numbers) — Retrieve all phone numbers purchased and assigned to your Vobiz account - capabilities, billing, status, and application assignments across 130+..
* [List Inventory Numbers](/docs/account-phone-number/list-inventory-numbers) — Browse Vobiz phone numbers available for purchase - search unassigned DIDs, virtual numbers, and toll-free numbers by country, prefix, or voice..
* [Purchase from Inventory](/docs/account-phone-number/purchase-from-inventory) — Purchase a Vobiz phone number from inventory and assign it to your account - instantly deducts setup and monthly fees and activates the number for..
* [Release a Phone Number](/docs/account-phone-number/unrent-number) — Release a Vobiz phone number for an account-specific fee, with a 24-hour cancellation window or an immediate-release option
* [Cancel a Number Release](/docs/account-phone-number/cancel-release) — Cancel a pending phone number release during the 24-hour cooldown and restore the number to active
* [Get Number Health Dashboard](/docs/account-phone-number/get-number-health) — Retrieve the health and analytics dashboard for a Vobiz number - status, spam flag, and call metrics (total/answered calls, answer rate, minutes)..

#### Recordings

* [Vobiz Recordings API – Call & Conference Recording Management](/docs/recording) — List, retrieve, download, and delete Vobiz call and conference recordings via REST API - with bulk export, compliance-grade storage, per-recording..
* [The Recording Object](/docs/recording/recording-object) — Explore every field on the Vobiz Recording object - recording ID, file URL, format, duration, source call UUID, and storage billing
* [Retrieve a Recording](/docs/recording/retrieve-recording) — Fetch full metadata for a specific Vobiz call recording by ID - file URL, duration, format, associated call UUID, and storage billing
* [List All Recordings](/docs/recording/list-all-recordings) — Retrieve a paginated list of Vobiz call recordings with filters for recording type, trunk, or extension - for archival, compliance, and quality..
* [Download a Recording](/docs/recording/download-recording) — Programmatically download Vobiz recording files and resolve common authentication issues during playback - example code and troubleshooting tips
* [Export Historical Recordings](/docs/recording/export-historical-recordings) — Export Vobiz call recordings matching filter criteria as a downloadable archive delivered via email - async background job for bulk historical data..

#### Call Detail Records

* [Vobiz Call Detail Records (CDR) API – Call Logs & Billing Analytics](/docs/cdr) — Query, filter, and export Vobiz CDRs with per-call billing data, MOS scores, jitter, hangup attribution, and CSV export - for reconciliation, fraud..
* [List CDRs](/docs/cdr/list-cdrs) — Retrieve paginated Vobiz call detail records with filters for date range, number, direction, and duration - the primary endpoint for call analytics..
* [Get Single CDR](/docs/cdr/get-cdr) — Retrieve the full call detail record for a specific call by its call\_id - duration, disposition, caller ID, timestamps, and billing data for a single..
* [Search CDRs](/docs/cdr/search-cdrs) — Search Vobiz call detail records with active filter combinations - find specific calls by number, status, or duration for dispute resolution and..
* [Recent CDRs](/docs/cdr/recent-cdrs) — Fetch the most recent Vobiz call detail records without date filters - a quick tail view of your latest voice traffic for real-time debugging and..
* [Export CDRs as CSV](/docs/cdr/export-cdrs) — Export Vobiz call detail records as a CSV file for billing reconciliation, compliance auditing, and traffic analysis - returns text/csv content..

### SIP Trunking

#### Trunks

* [Vobiz SIP Trunking API – Enterprise Voice & Elastic SIP Trunks](/docs/trunks) — Create and manage elastic SIP trunks on Vobiz - auto-provisioned SIP domains, IP or credential auth, CPS throttling, and priority failover routing..
* [The Trunk Object](/docs/trunks/trunk-object) — Explore the Vobiz SIP Trunk object schema - SIP domain, auth mode, credentials, IP ACLs, origination URIs, rate limits, and all fields returned by..
* [Create a Trunk](/docs/trunks/create-trunk) — Provision a new Vobiz SIP trunk with concurrent-call limits, CPS caps, TLS/SRTP, credentials, IP ACLs, and origination URIs - all in a single API..
* [Retrieve a Trunk](/docs/trunks/retrieve-trunk) — Fetch full configuration of a single Vobiz SIP trunk by ID - rate limits, auth mode, SIP domain, and attached credentials, IP ACLs, and origination..
* [Retrieve All Trunks](/docs/trunks/retrieve-all-trunks) — Paginated list of all SIP trunks on your Vobiz account - view configurations, monitor rate limits, and manage global SIP trunking resources in one..
* [Update a Trunk](/docs/trunks/update-trunk) — Modify an existing Vobiz SIP trunk - update name, description, concurrent-call limits, CPS caps, or webhook URL without recreating the trunk resource
* [Assign Number to Trunk](/docs/trunks/assign-number) — Assign a phone number to a Vobiz SIP trunk so all inbound calls to that DID route through the designated trunk - supports global and India DID..
* [Unassign Number from Trunk](/docs/trunks/unassign-number) — Remove a phone number's trunk assignment on Vobiz - the DID returns to your account inventory and inbound routing via the trunk stops immediately
* [Delete a Trunk](/docs/trunks/delete-trunk) — Permanently delete a Vobiz SIP trunk and all associated credentials, IP ACLs, and origination URIs - this action is irreversible and stops all trunk..
* [Trunk Webhooks](/docs/trunks/webhook) — Configure HTTP webhooks on Vobiz SIP trunks to receive real-time call events globally - call admitted, rejected, or ended with duration, cost, and..

#### Credentials

* [Credentials](/docs/trunks/credentials) — Manage SIP credentials for username and password authentication on your Vobiz trunks - create, list, rotate, and revoke credentials per trunk
* [The Credential Object](/docs/trunks/credentials/credential-object) — Explore the Vobiz SIP Credential object schema - credential\_id, username, write-only password, enabled flag, trunk association, and ISO 8601..
* [Create Credential](/docs/trunks/credentials/create-credential) — Add a SIP digest credential to a Vobiz trunk to authenticate softphones, IP phones, or AI voice agents - unique username required, password is..
* [Retrieve All Credentials](/docs/trunks/credentials/retrieve-all-credentials) — Paginated list of all SIP digest credentials on your Vobiz account - audit usernames, check enabled states, and manage authentication for global SIP..
* [Update Credential](/docs/trunks/credentials/update-credential) — Rotate the password, toggle the enabled state, or update the description of a Vobiz SIP credential without interrupting other active trunk..
* [Delete Credential](/docs/trunks/credentials/delete-credential) — Permanently revoke a SIP digest credential from your Vobiz trunk - every device or AI agent using that username loses authentication access..

#### IP Access Control List

* [IP Access Control Lists](/docs/trunks/ip-acl) — Manage IP-based authentication for your Vobiz SIP trunks using IPv4 whitelisting - restrict trunk access to known PBX and softswitch addresses
* [The IP ACL Object](/docs/trunks/ip-acl/ip-acl-object) — Complete field reference for the Vobiz IP ACL object - covers ip\_address, enabled flag, UUID, and ISO 8601 timestamps for SIP trunk IP allowlists
* [Create IP ACL](/docs/trunks/ip-acl/create-ip-acl) — Add an IPv4 address to your Vobiz SIP trunk allowlist so PBX systems, SBCs, or carriers authenticate calls without SIP digest credentials - 130+..
* [Retrieve All IP ACLs](/docs/trunks/ip-acl/retrieve-all-ip-acls) — Fetch a paginated list of all IP ACL entries on your Vobiz account to audit whitelisted IPv4 addresses, enabled states, and trunk IP auth coverage..
* [Update IP ACL](/docs/trunks/ip-acl/update-ip-acl) — Modify a Vobiz IP ACL entry to update the whitelisted IPv4 address, toggle its enabled state, or edit the description - all with a single PUT request
* [Delete IP ACL](/docs/trunks/ip-acl/delete-ip-acl) — Permanently remove a whitelisted IPv4 address from a Vobiz SIP trunk, revoking IP-based authentication and blocking unauthenticated calls from that..

#### Origination URI

* [Origination URIs](/docs/trunks/origination-uri) — Configure outbound SIP routing destinations on your Vobiz trunk - origination URIs control where the trunk delivers inbound traffic for termination
* [The Origination URI Object](/docs/trunks/origination-uri/origination-uri-object) — Complete field reference for the Vobiz Origination URI object - SIP URI format, priority, weight, transport protocol, enabled flag, and ISO 8601..
* [Create Origination URI](/docs/trunks/origination-uri/create-origination-uri) — Add a SIP destination URI to your Vobiz trunk for outbound routing - set priority and weight for load balancing and carrier failover across 130+..
* [Retrieve All Origination URIs](/docs/trunks/origination-uri/retrieve-all-origination-uris) — List all SIP destination URIs on a Vobiz trunk - review routing priority, load-balancing weights, and enabled status to audit outbound call..
* [Update Origination URI](/docs/trunks/origination-uri/update-origination-uri) — Update a Vobiz origination URI - change SIP destination, routing priority, load-balancing weight, or enabled state with a partial PUT; no re-creation..
* [Delete Origination URI](/docs/trunks/origination-uri/delete-origination-uri) — Permanently remove a SIP destination URI from a Vobiz trunk, halting outbound routing to that endpoint - keep at least one active URI to avoid call..

### Voice & XML

#### Applications

* [Vobiz Applications API – Configure Answer, Hangup & Message URLs](/docs/applications) — Bundle Answer URL, Hangup URL, and Message webhook URLs into reusable Vobiz Applications that control inbound call routing and XML flow for any phone..
* [The Application Object](/docs/applications/application-object) — Explore every field of the Vobiz Application object - answer\_url, hangup\_url, message\_url, HTTP methods, SIP URI, and fallback behavior for call..
* [Create an Application](/docs/applications/create-application) — Create a Vobiz voice application by registering your answer\_url and hangup\_url webhooks - the first step to handling inbound calls and messages..
* [Retrieve an Application](/docs/applications/retrieve-application) — Retrieve a single Vobiz voice application by app\_id - inspect its webhook URLs, HTTP methods, fallback configuration, and current number assignments
* [Update an Application](/docs/applications/update-application) — Update an existing Vobiz voice application - modify webhook URLs, HTTP methods, app name, or SIP URI to change how inbound calls and messages are..
* [Delete an Application](/docs/applications/delete-application) — Permanently delete a Vobiz voice application by app\_id - removes all webhook configuration and disassociates attached phone numbers and SIP endpoints
* [List All Applications](/docs/applications/list-all-applications) — List all voice applications on your Vobiz account - paginated results with full configuration for each app\_id, including webhook URLs and attached..
* [Attach Number to Application](/docs/applications/attach-number) — Link a Vobiz phone number to a voice Application so incoming calls and messages on that number are routed to the Application's configured webhooks
* [Detach Number from Application](/docs/applications/detach-number) — Remove the link between a phone number and a voice application

#### Endpoints

* [Vobiz Endpoint API](/docs/endpoint) — Manage SIP endpoints on Vobiz for making and receiving calls from IP phones, mobile SIP clients, softphones, and any SIP-compliant device
* [The Endpoint Object](/docs/endpoint/endpoint-object) — Schema reference for the Vobiz SIP Endpoint object: username, SIP URI, registration status, application binding, call permissions, and live..
* [Create an Endpoint](/docs/endpoint/create-endpoint) — Provision a new SIP endpoint on Vobiz to register IP phones, softphones, or AI voice agents - assign a SIP URI, credentials, and call permissions in..
* [Retrieve an Endpoint](/docs/endpoint/retrieve-endpoint) — Fetch a Vobiz SIP endpoint by ID - returns live registration status, SIP contact, expiry, user agent string, and attached application details for..
* [Update an Endpoint](/docs/endpoint/update-endpoint) — Modify a Vobiz SIP endpoint - rotate its password, update the alias, swap the attached application, or toggle voice and video permissions; no..
* [Delete an Endpoint](/docs/endpoint/delete-endpoint) — Permanently remove a SIP endpoint from your Vobiz account, immediately unregistering all devices and making the SIP URI permanently unavailable..
* [List all endpoints](/docs/endpoint/list-all-endpoints) — Retrieve all SIP endpoints on your Vobiz account with pagination - filter by username or alias, check registration status, and audit application..

#### Call Management

* [Call Management Overview](/docs/call/overview) — Manage voice calls globally with Vobiz telephony platform - make, transfer, hang up, record, and monitor calls across 130+ countries via a unified..
* [The Call Object](/docs/call/call-object) — Explore every field of the Vobiz Call object - UUID, status, direction, duration, hangup cause, STIR/SHAKEN verification, and per-call billing rate
* [Make an Outbound Call](/docs/call/make-call) — Initiate an international outbound call to any PSTN number or SIP endpoint across 130+ countries, with bulk dialing, AMD, and recording in one API..
* [Machine Detection](/docs/call/machine-detection) — Detect answering machines and voicemail on global outbound calls with Vobiz AMD - configure sync or async mode, silence timeout, callback delivery..
* [Transfer a Call](/docs/call/transfer-call) — Redirect an active call to a new XML instruction URL mid-session using Vobiz - transfer the A-leg, B-leg, or full session for dynamic IVR call..
* [Hang Up a Call](/docs/call/hangup-call) — Terminate an active Vobiz call by UUID - hang up the A-leg, B-leg, or full bridged session instantly with a DELETE request that triggers CDR..
* [Retrieve a live call](/docs/call/retrieve-live-call) — Fetch real-time state, direction, duration, and per-leg metadata for a single active Vobiz call by UUID using a GET request with status=live
* [Retrieve all live calls](/docs/call/retrieve-all-live-calls) — List UUIDs of every active call on your Vobiz account in real time - power monitoring dashboards, concurrent capacity audits, and bulk operations
* [Retrieve a queued call](/docs/call/retrieve-queued-call) — Fetch details of a single pending Vobiz call by UUID before it connects - inspect destination, timestamps, and queue state via GET with status=queued
* [Retrieve all queued calls](/docs/call/retrieve-all-queued-calls) — List UUIDs for all pending outbound calls on your Vobiz account waiting to connect - returns up to 20 queued calls per request for full queue..
* **Record calls**
  * [Record calls](/docs/call/record-calls) — Record specific portions of active Vobiz calls with mp3 or wav format, optional speech-to-text transcription, and completion callback delivery
  * [Start recording a call](/docs/call/record-calls/start-recording) — Begin recording an active Vobiz call in MP3 or WAV format with optional auto-transcription, multiple concurrent recordings, and callback on..
  * [Stop recording a call](/docs/call/record-calls/stop-recording) — Stop one or all active recordings on a Vobiz call - finalize the audio file, trigger the callback URL, and make the recording available for download
* **Play audio**
  * [Play audio on calls](/docs/call/play-audio) — Play audio files into active Vobiz calls for hold music, IVR prompts, announcements, and dynamic in-call media without interrupting other legs
  * [Play audio on a call](/docs/call/play-audio/play-audio) — Stream MP3 or WAV audio files to participants on an active Vobiz call - play single or multiple files in sequence, loop hold music, and target..
  * [Stop playing audio on a call](/docs/call/play-audio/stop-audio) — Interrupt audio playback on an active Vobiz call instantly - stop hold music, end looping files, or cancel announcements when an agent becomes..
* **Speak text**
  * [Speak text on calls](/docs/call/speak-text) — Convert text to speech and play it into active Vobiz calls using the built-in TTS engine with 29-language support and selectable voices
  * [Speak text on a call](/docs/call/speak-text/speak-text) — Convert text to speech on any active Vobiz call - choose from 29 languages including Hindi, and WOMAN or MAN voice, for dynamic in-call messages
  * [Stop speaking text during a call](/docs/call/speak-text/stop-speak) — Halt active text-to-speech playback on a Vobiz call - interrupt looping messages on DTMF input or when an agent joins, without affecting the call..
* **DTMF**
  * [DTMF](/docs/call/dtmf) — Send DTMF tones programmatically to an active call to automate IVR navigation, enter access codes, or drive automated phone menus
  * [Send digits on an active call](/docs/call/dtmf/send-digits) — Send DTMF keypad tones on any active Vobiz call to automate IVR navigation, enter access codes, and control phone systems programmatically at scale

#### Conferences

* [The Conference Object](/docs/conference/conference-object) — Explore the Vobiz Conference object schema - member arrays, mute/deaf states, runtime, call UUID, and join-time fields for multi-party voice calls..
* [Retrieve a Conference](/docs/conference/retrieve-conference) — Fetch live details of a named Vobiz conference via GET - runtime, member count, mute/deaf states, call UUIDs, and join times for multi-party calls..
* [List All Conferences](/docs/conference/retrieve-all-conferences) — Retrieve the names of all ongoing conferences on your account, so you can look up details or perform operations on specific rooms
* [Hang Up a Conference](/docs/conference/hang-up-conference) — Terminate an active Vobiz conference by name via DELETE - instantly disconnects all participants and stops any in-progress recordings across 130+..
* [Hang Up All Conferences](/docs/conference/hang-up-all-conferences) — Immediately disconnect every participant across all ongoing conferences on your account in a single request
* **Conference Members**
  * [Conference Members](/docs/conference/members) — Control individual Vobiz conference members - mute, deaf, kick, hang up, and play audio or text to a single participant without affecting others
  * [Play Audio to a Member](/docs/conference/members/play-audio) — Inject a private MP3 or WAV audio file to targeted Vobiz conference members via POST - whisper announcements or hold music to one participant or all
  * [Stop Playing Audio to a Member](/docs/conference/members/stop-audio) — Interrupt in-progress audio playback for one or more Vobiz conference members via DELETE - stop whisper files or hold music mid-stream across 130+..
  * [Deaf a Member](/docs/conference/members/deaf-member) — Block incoming audio for conference participants via POST - deafen one member, a comma-separated list, or all members in a Vobiz multi-party call..
  * [Undeaf a Member](/docs/conference/members/undeaf-member) — Restore incoming audio for deafened Vobiz conference members via DELETE - re-enable one participant, a list of IDs, or all members to hear the call..
  * [Mute a Member](/docs/conference/members/mute-member) — Silence outgoing audio for conference participants via POST - mute one member, a comma-separated list, or all members in a Vobiz multi-party call..
  * [Unmute a member](/docs/conference/members/unmute-member) — Restore outgoing audio for muted Vobiz conference members via DELETE - unmute one participant, a list of IDs, or all members in a multi-party call..
  * [Kick a member](/docs/conference/members/kick-member) — Remove a conference participant via POST while continuing their XML flow - play a post-disconnect message or redirect them across Vobiz's global..
  * [Hang up a member](/docs/conference/members/hang-up-member) — Terminate a conference member's call via DELETE - disconnect one participant, a list of IDs, or all members from a Vobiz multi-party voice call..
* **Conference Recording**
  * [Conference recording](/docs/conference/recording) — Start and stop Vobiz conference recordings in MP3 or WAV format and handle asynchronous API responses
  * [Start conference recording](/docs/conference/recording/start-recording) — Start recording a Vobiz conference via POST - capture all participants in MP3 or WAV format, set a callback URL, and meet compliance requirements..
  * [Stop conference recording](/docs/conference/recording/stop-recording) — Stop an active Vobiz conference recording and handle the empty success response

#### Audio Streams

* [Vobiz Audio Streams API – Real-Time WebSocket Call Audio](/docs/audio-streams) — Fork live call audio to a WebSocket server in real time with the Vobiz Audio Streams API - enabling AI voice agents, speech transcription, sentiment..
* [The Stream Object](/docs/audio-streams/stream-object) — Understand every field on the Vobiz audio Stream object: stream ID, status, codec, track direction, WebSocket URL, bidirectional mode, and start/end..
* [Start an Audio Stream](/docs/audio-streams/start-audio-stream) — Fork live call audio over a WebSocket connection to your AI pipeline in near real time - configure codec, track direction, and bidirectional mode per..
* [Retrieve an Audio Stream](/docs/audio-streams/retrieve-audio-stream) — Fetch full details for a specific Vobiz audio stream by stream ID - status, WebSocket URL, codec, track direction, bidirectional mode, and start/end..
* [List all Audio Streams](/docs/audio-streams/list-audio-streams) — List all audio streams - both active and stopped - associated with a Vobiz call UUID, including each stream's status, codec, track direction, and..
* [Stop a Specific Audio Stream](/docs/audio-streams/stop-audio-stream) — Stop a single Vobiz audio stream by stream ID without affecting other active forks on the same call - triggers a Stream stopped status callback on..
* [Stop all Audio Streams](/docs/audio-streams/stop-all-audio-streams) — Stop every active audio stream running on a Vobiz call in one DELETE request - ideal for pipeline cleanup at call end or before transferring to a new\..

#### Voice Campaign Manager

* [Voice Campaign Manager API](/docs/campaign-manager/overview) — Create and operate outbound voice campaigns with reusable agents, CSV contact lists, caller-ID pools, retries, scheduling, capacity controls, and..
* [Campaign API authentication](/docs/campaign-manager/authentication) — Authenticate customer-facing Campaign Manager requests with API keys or a JWT, and understand how internal service endpoints are protected
* **Agents**
  * [Create a campaign agent](/docs/campaign-manager/agents/create-agent) — Create a reusable Campaign Manager agent that defines the answer URL, hangup URL, and static SIP headers used for every call in a campaign
  * [List campaign agents](/docs/campaign-manager/agents/list-agents) — Retrieve every non-archived Campaign Manager agent on your account with limit and offset pagination
  * [Retrieve a campaign agent](/docs/campaign-manager/agents/retrieve-agent) — Fetch a single Campaign Manager agent by ID, including its answer and hangup webhook configuration and static SIP headers
  * [Update a campaign agent](/docs/campaign-manager/agents/update-agent) — Partially update a Campaign Manager agent
  * [Delete a campaign agent](/docs/campaign-manager/agents/delete-agent) — Soft-delete a Campaign Manager agent. Agents with active campaigns are rejected until those campaigns finish, are cancelled, or are archived
* **Campaigns**
  * [Create a campaign](/docs/campaign-manager/campaigns/create-campaign) — Create an outbound voice campaign with concurrency, timezone, caller-ID strategy, scheduling, daily calling window, and retry policy
  * [List campaigns](/docs/campaign-manager/campaigns/list-campaigns) — List active or archived outbound voice campaigns on your account with limit and offset pagination
  * [Retrieve a campaign](/docs/campaign-manager/campaigns/retrieve-campaign) — Fetch a single campaign with its status, computed health, outcome counters, caller-ID configuration, schedule, and pause reason
  * [Update a campaign](/docs/campaign-manager/campaigns/update-campaign) — Partially update a draft or ready campaign — concurrency, caller-ID settings, schedule, daily window, retries, and webhook URL
* **Lifecycle controls**
  * [Start a campaign](/docs/campaign-manager/controls/start-campaign) — Launch a ready campaign immediately. Starting clears any scheduled\_at value and begins dialling within the account concurrency limit
  * [Pause a campaign](/docs/campaign-manager/controls/pause-campaign) — Pause a running campaign. New dials stop, in-flight calls finish, and the campaign requires an explicit resume
  * [Resume a campaign](/docs/campaign-manager/controls/resume-campaign) — Return a paused campaign to running and immediately re-enqueue its pending contacts
  * [Cancel a campaign](/docs/campaign-manager/controls/cancel-campaign) — Permanently stop a running or paused campaign
  * [Archive a campaign](/docs/campaign-manager/controls/archive-campaign) — Soft-delete a non-running campaign to remove it from active lists while preserving its contacts, CDRs, and statistics
* **Contacts and results**
  * [Upload campaign contacts](/docs/campaign-manager/contacts/upload-contacts) — Upload a contacts CSV to a campaign. A valid upload moves the campaign from draft to ready and detects custom columns as SIP headers
  * [List campaign contacts](/docs/campaign-manager/contacts/list-contacts) — Browse a campaign's contacts with limit and offset pagination, filter by contact status, or search for a specific number
  * [List campaign call attempts](/docs/campaign-manager/contacts/list-calls) — Retrieve the per-attempt call log for a campaign, joining campaign call records with CDR data, using page and per\_page pagination
  * [Download campaign results](/docs/campaign-manager/contacts/download-results) — Export campaign contact outcomes as CSV, including partial exports while the campaign is still running
* **Caller-ID pool**
  * [Add caller pool numbers](/docs/campaign-manager/caller-pool/add-pool-numbers) — Add one or more caller-ID numbers to a pool campaign so calls rotate across them under the campaign's rotation strategy and limits
  * [List caller pool numbers](/docs/campaign-manager/caller-pool/list-pool-numbers) — List the caller-ID numbers in a pool campaign with per-number usage statistics and eligibility status
  * [Update a caller pool number](/docs/campaign-manager/caller-pool/update-pool-number) — Rename a pool number or disable it so it is excluded from caller-ID rotation without losing its call history
  * [Remove a caller pool number](/docs/campaign-manager/caller-pool/delete-pool-number) — Remove a caller-ID number from a pool campaign
* **Capacity and lookup**
  * [Get account capacity](/docs/campaign-manager/capacity/account-capacity) — Inspect live account concurrency, available capacity, utilisation, and the running campaigns consuming it
  * [Look up a campaign call](/docs/campaign-manager/capacity/call-lookup) — Resolve a call UUID to its campaign and contact, and confirm that a campaign owns a given call
* [Campaign webhook events](/docs/campaign-manager/webhooks) — Receive and verify signed voice campaign and contact lifecycle events

#### XML Overview

* [How Vobiz Voice XML Works – Event-Driven Call Flow Architecture](/docs/xml/overview/how-it-works) — Discover the event-driven cycle powering Vobiz Voice XML
* [Getting Started with Vobiz Voice XML – Build Your First App](/docs/xml/overview/getting-started) — Build your first Vobiz voice application from scratch
* [Vobiz XML Best Practices – Reliable & Scalable Voice Apps](/docs/xml/overview/best-practices) — Proven patterns for robust Vobiz XML apps - fast webhook responses, audio caching, fallback flows, CallUUID logging, and scalable IVR architecture..

#### Stream

* [Stream XML Element – Real-Time WebSocket Audio | Vobiz](/docs/xml/stream) — Fork live call audio to a WebSocket server in real time with Vobiz Stream
* [Audio formats: 8, 16, and 24 kHz](/docs/xml/stream/audio-formats) — Choose and configure supported 8, 16, and 24 kHz audio formats for inbound Vobiz streams and outbound WebSocket playback
* [Initiate a Stream](/docs/xml/stream/initiate) — Establish a WebSocket connection to Vobiz Stream and begin streaming raw audio from an active call - covers handshake, codecs, and authentication
* [Stream Events Overview](/docs/xml/stream/stream-events) — Use the Vobiz Stream WebSocket connection to send events from your application to control playback, mark checkpoints, and signal interruption
* [Checkpoint Event](/docs/xml/stream/checkpoint-event) — Send a checkpoint event via Vobiz Stream WebSocket when queued audio events are ready - used to synchronize playback with downstream processing logic
* [Clear Stream](/docs/xml/stream/clear-audio) — The Vobiz clearAudio Stream event interrupts audio previously sent via playAudio - useful for instantly stopping TTS when the caller starts speaking
* [Play audio event](/docs/xml/stream/play-audio) — Send raw L16 or μ-law audio from your WebSocket application to Vobiz for playback on a live call
* [Stop Event](/docs/xml/stream/stop-event) — Send a stop event via Vobiz Stream WebSocket to terminate the stream from your application - Vobiz immediately proceeds to the next XML element, or..

#### Dial

* [Dial XML element](/docs/xml/dial) — Bridge the current call to PSTN numbers or SIP users with Vobiz Dial, with explicit answer and connected-call limits, real-time events, and a final..
* [Number XML element](/docs/xml/dial/number) — Dial an E.164 PSTN destination inside the Vobiz Dial element, optionally sending DTMF after answer or during early media
* [User XML element](/docs/xml/dial/user) — Dial a SIP URI or registered Vobiz WebRTC/SIP user inside Dial, with optional DTMF and X-VH metadata
* [Sequential dialing](/docs/xml/dial/sequential-dialing) — Attempt PSTN destinations in sequence by returning the next Dial instruction from the previous Dial action URL
* [Simultaneous dialing](/docs/xml/dial/simultaneous-dialing) — Attempt several PSTN destinations concurrently with sibling Number elements and handle the winning and LOSE\_RACE callback outcomes
* [Answer confirmation settings](/docs/xml/dial/confirm-to-answer-call) — Configure confirmSound and confirmKey on the Vobiz Dial element while confirmKey connection enforcement remains unverified
* [Custom caller tone](/docs/xml/dial/custom-caller-tone) — Return Play, Speak, or Wait instructions from dialMusic while Vobiz connects a Dial destination
* [Dial status reporting](/docs/xml/dial/dial-status-reporting) — Handle real-time Dial lifecycle events through callbackUrl and receive one final Dial result through action
* [Transferred calls end to end](/docs/xml/dial/transferred-calls) — How a transferred Vobiz call behaves across its whole lifecycle - the two call legs it creates, the order its webhooks arrive in, how to correlate..

#### Gather

* [Gather XML Element – Collect DTMF & Speech Input | Vobiz](/docs/xml/gather) — Collect caller input via DTMF or speech recognition (ASR) in a live call
* [Detecting speech inputs](/docs/xml/gather/detecting-speech-inputs) — Gather's automatic speech recognition (ASR) on Vobiz accepts spoken input as well as DTMF - configure language, hints, and timeout per gather call
* [Pricing for speech recognition](/docs/xml/gather/pricing-for-speech-recognition) — Speech recognition pricing on Vobiz Gather is billed by the duration of speech analyzed - learn how seconds are counted and how to control your spend
* [Supported languages](/docs/xml/gather/supported-languages) — Reference list of BCP-47 language codes Vobiz Gather supports for speech recognition - including en-IN, Hindi, and major global locales for IVR..

#### Speak

* [Speak XML Element – Text-to-Speech in Live Calls | Vobiz](/docs/xml/speak) — Convert text to speech in a live call with the Vobiz Speak element
* [Play a message](/docs/xml/speak/play-a-message) — Example of the Vobiz Speak XML element - when an inbound call is directed to this document, the Speak verb plays a TTS message to the caller
* [Play in a loop](/docs/xml/speak/play-in-a-loop) — Example of the Vobiz Speak XML element with looping - tells Vobiz to say the word Wow three times in a row using the loop attribute on the Speak verb
* [SSML](/docs/xml/speak/ssml) — Use Speech Synthesis Markup Language (SSML) inside the Vobiz Speak XML element to control pronunciation, pauses, emphasis, and prosody of TTS output

#### Play

* [Play XML Element – Stream Audio Files to Callers | Vobiz](/docs/xml/play) — Stream MP3 or WAV audio from a remote URL to a caller with the Vobiz Play element
* [Play music](/docs/xml/play/play-music) — Example of the Vobiz Play XML element - fetches and plays the audio file Trumpet.mp3 to the active caller on an incoming or outbound call leg

#### Record

* [Record XML Element – Call & Conference Recording | Vobiz](/docs/xml/record) — Record calls or conferences with the Vobiz Record element and get a URL at your callback endpoint
* [Record a voicemail](/docs/xml/record/record-a-voicemail) — This example shows how to record a voicemail message
* [Stream with Record](/docs/xml/record/stream-with-record) — Use the Vobiz Record and Stream XML elements together to simultaneously record a call to file and stream raw audio to your WebSocket in real time

#### Redirect

* [Redirect XML Element – Dynamic Call Flow Routing | Vobiz](/docs/xml/redirect) — Transfer call control to a new URL with the Vobiz Redirect element
* [Transfer a call](/docs/xml/redirect/transfer-a-call) — Use the Vobiz Redirect XML element after a Speak verb to transfer control of a call to a different URL that returns fresh XML for the next flow step

#### Hangup

* [Hangup XML Element – Terminate or Reject Calls | Vobiz](/docs/xml/hangup) — End or reject a call at any point with the Vobiz Hangup element
* [Hang up call after a minute](/docs/xml/hangup/hang-up-after-a-minute) — Schedule a hangup on a Vobiz call after one minute using the Hangup XML element - example plays a final message before the call is terminated

#### Wait

* [Wait XML Element – Silent Pause & Machine Detection | Vobiz](/docs/xml/wait) — Pause a call silently for a set duration with the Vobiz Wait element
* [Basic wait](/docs/xml/wait/basic-wait) — Example of the Vobiz Wait XML element - demonstrates how to insert a seven-second silent pause between two lines of TTS during a Vobiz call flow
* [Beep detection](/docs/xml/wait/beep-detection) — You can use the Wait element to aid leaving voice mails on answering machines by adding an extra parameter called beep and setting it to true
* [Delayed call answer](/docs/xml/wait/delayed-call-answer) — Example of the Vobiz Wait XML element - demonstrates how to delay answering an inbound call by 10 seconds before any other XML verb executes
* [Machine detection](/docs/xml/wait/machine-detection) — Use the silence parameter on the Vobiz Wait element with machine\_detection to distinguish a human pickup from voicemail before continuing the call..

#### PreAnswer

* [PreAnswer XML Element – Early Media Before Call Answer | Vobiz](/docs/xml/preanswer) — Answer incoming calls in early media mode with the Vobiz PreAnswer element
* [Notify callers](/docs/xml/preanswer/notify-callers) — Use the Vobiz PreAnswer XML element to notify the caller that the current call costs \$2 a minute before fully answering and billing the call

#### Conference

* [Conference XML Element – Multi-Party Call Rooms | Vobiz](/docs/xml/conference) — Connect callers to a named conference room with the Vobiz Conference element
* [Conference Attributes](/docs/xml/conference/attributes) — Full reference for every attribute on the Vobiz Conference XML element - control muting, beeps, participant limits, hold music, and recording
* [Conference callbacks](/docs/xml/conference/conference-callbacks) — Handle participant enter and exit callbacks and wait-audio requests from Vobiz conferences

#### Request

* [Vobiz XML Request – Webhook Parameters & Call Payload](/docs/xml/request) — Vobiz sends a synchronous HTTP request with call parameters to your endpoint on each call event
* [Call status](/docs/xml/request/call-status) — Vobiz sends a call status to request URLs under the CallStatus key
* [Event](/docs/xml/request/event) — Vobiz generates call events when the state of a call changes - your application receives them as HTTP requests so it can update state and trigger..
* [SIP headers](/docs/xml/request/sip-headers) — Receive X-VH custom headers from inbound SIP calls or pass application metadata through Dial and User callbacks

#### Response & DTMF

* [Response XML Element – Root Container for Call Instructions | Vobiz](/docs/xml/response) — Every Vobiz XML document must wrap call instructions in a single Response root element
* [DTMF XML Element – Send Tones on Live Calls | Vobiz](/docs/xml/dtmf) — Send DTMF tones programmatically on a live call with the Vobiz DTMF element

### WhatsApp

#### Getting Started

* [Introduction to WhatsApp Business](/docs/whatsapp/getting-started/introduction) — Discover how the WhatsApp Business API works on Vobiz - enterprise messaging at scale in 130+ countries with templates, webhooks, and a no-code..
* [Prerequisites](/docs/whatsapp/getting-started/prerequisites) — Complete every prerequisite for WhatsApp Business on Vobiz - Meta Business Account, verified phone number, and approved display name - in 15–30..
* [Quick Start Guide](/docs/whatsapp/getting-started/quick-start) — Get up and running with Vobiz WhatsApp Business in under 5 minutes - connect your first channel and send messages via console and API examples
* [Console Walkthrough](/docs/whatsapp/getting-started/console-walkthrough) — A screenshot-by-screenshot walkthrough of connecting a WhatsApp Business channel in the Vobiz Console - embedded signup with Meta, creating a..

#### Channel Management

* [Channel Management](/docs/whatsapp/channels) — Connect and manage WhatsApp Business channels on Vobiz - choose from multiple connection methods, run multiple channels, and monitor performance
* [Bring Your Own Number (BYON) Setup Guide](/docs/whatsapp/channels/byon) — Connect your existing WhatsApp Business number to Vobiz using BYON - step-by-step setup guide covering OTP verification, Meta Business Manager, and..

#### Messaging

* [WhatsApp Messaging](/docs/whatsapp/messaging) — Send messages, manage conversations, and engage customers on WhatsApp Business via Vobiz - message types, the 24-hour window, and template basics
* [Using the WhatsApp Inbox](/docs/whatsapp/messaging/inbox) — Manage all WhatsApp conversations from the Vobiz shared inbox - send messages, view history, use canned responses, and collaborate across agents in..
* [WhatsApp Message Templates](/docs/whatsapp/messaging/templates) — Create and submit WhatsApp message templates on Vobiz for Meta approval - required for all outbound business-initiated messages outside the 24-hour..

#### Webhooks

* [WhatsApp Webhooks](/docs/whatsapp/webhooks) — Receive real-time WhatsApp event notifications from Vobiz on your own server - inbound messages, delivery status, and call events delivered as signed..
* [Webhook Events Reference](/docs/whatsapp/webhooks/events) — Reference for every outbound WhatsApp webhook event Vobiz delivers to your server - the common envelope, the three real event types (message.inbound..

#### WhatsApp Business API

* [Vobiz WhatsApp Business API Reference](/docs/whatsapp/api) — Use the Vobiz WhatsApp Business API reference to send messages and manage channels, contacts, templates, campaigns, conversations, calls, and..
* [API Authentication](/docs/whatsapp/api/authentication) — Authenticate every Vobiz WhatsApp API request using X-Auth-ID and X-Auth-Token headers - find your credentials in the Vobiz Console and secure them..
* [Send Message API](/docs/whatsapp/api/send-message) — Send WhatsApp messages via the Vobiz REST API - text, images, video, audio, documents, stickers, and Meta-approved templates over a single endpoint
* [Channels API](/docs/whatsapp/api/channels) — Create, update, and remove WhatsApp Business channels on Vobiz - connect your WABA, manage display names, and rotate access tokens via REST API
* [Numbers API](/docs/whatsapp/api/numbers) — Search and purchase WhatsApp-capable numbers on Vobiz, or verify and connect an existing number via BYON - OTP-based ownership verification included
* [Conversations API](/docs/whatsapp/api/conversations) — Retrieve and paginate WhatsApp conversation threads on Vobiz - build inbox views, sync message history to your CRM, or audit logs with cursor-based..
* [Contacts API](/docs/whatsapp/api/contacts) — Create, update, tag, and delete WhatsApp contacts on Vobiz, or import thousands of contacts at once via CSV bulk upload for campaign targeting
* [Templates API](/docs/whatsapp/api/templates) — Submit, manage, and sync WhatsApp Message Templates via the Vobiz API - Meta-approved formats required for all proactive business-initiated outbound..
* [Campaigns API](/docs/whatsapp/api/campaigns) — Create and manage WhatsApp broadcast campaigns on Vobiz - send bulk outbound messages via Meta-approved templates to segmented contact audiences at..
* [Canned responses API](/docs/whatsapp/api/canned-responses) — Create and manage WhatsApp canned responses on Vobiz - reusable reply snippets that agents trigger with a /shortcut command directly inside the inbox
* [Calls API](/docs/whatsapp/api/calls) — Initiate and manage WhatsApp Business voice calls programmatically via Vobiz - WebRTC-based signaling for inbound, outbound, and call state..
* [Webhooks API](/docs/whatsapp/api/webhooks) — Manage Vobiz outbound webhook subscriptions and understand the inbound Meta callback - create, list, and delete subscriptions to receive WhatsApp..

### Partner API

#### Overview & Flow

* [Vobiz Partner Portal – Reseller & White-Label telephony Program](/docs/partner) — Vobiz Partner Program gives resellers full API control over account provisioning, balance transfers, DID inventory, CDR access, and analytics..
* [Partner Integration Flow](/docs/partner/flow) — Walk through a full Vobiz partner integration - provision a customer, transfer balance, complete KYC, create a SIP trunk, and monitor live CDRs..
* [Partner API Reference](/docs/partner/api) — Complete reference for the Vobiz Partner API - endpoints across capacity allocation, authentication, customer provisioning, billing, CDRs, DIDs, KYC..

#### Endpoints

* [Partner API Authentication](/docs/partner/api/authentication) — Authenticate against the Vobiz Partner API using permanent X-Auth headers for server integrations or short-lived JWT tokens for interactive sessions
* [Partner Profile](/docs/partner/api/profile) — Retrieve your Vobiz partner identity, billing configuration, GST status, and current balance - the authoritative source for your permanent partner ID..
* [Dashboard & Analytics](/docs/partner/api/analytics) — Access aggregated usage metrics and date-range analytics across your Vobiz reseller ecosystem - live dashboard summary and flexible reporting..
* [Customer Accounts](/docs/partner/api/customers) — Provision, list, and manage SIP-enabled customer sub-accounts under your Vobiz partner account - each customer gets a unique auth\_id for all..
* [Balance Transfer](/docs/partner/api/balance) — Transfer credits from your Vobiz partner master wallet to a customer's wallet - the primary mechanism for funding reseller sub-accounts with prepaid..
* [Vobiz partner CPS and concurrency allocation](/docs/partner/api/capacity) — Transfer and reclaim CPS and concurrent-call capacity between your Vobiz partner account and customer accounts
* [KYC Sessions](/docs/partner/api/kyc-sessions) — Initiate and manage Vobiz KYC verification sessions for sub-accounts under your partner umbrella - supports both async email-link delivery and..
* [Partner Transactions](/docs/partner/api/transactions) — Access detailed financial ledgers for every credit and debit event across your Vobiz reseller ecosystem - essential for monthly billing..
* [CDRs (Call History)](/docs/partner/api/cdrs) — Fetch full call detail records for every voice session across your Vobiz partner ecosystem - filter by date, direction, or hangup cause for billing..
* [Phone Numbers (DIDs)](/docs/partner/api/numbers) — View and monitor DID phone number assignments for each customer in your Vobiz partner ecosystem - list per-customer numbers or get a global inventory..

## Integrations

### AI Voice Platforms

* [Vobiz Integrations & SDKs](/docs/integrations) — Connect Vobiz to leading AI voice platforms globally - Vapi, Retell AI, ElevenLabs, LiveKit, Pipecat, Rapida AI, and more via SIP trunking, REST..
* **Vapi**
  * [Vapi integration](/docs/integrations/vapi) — Vapi connects to Vobiz SIP trunking for AI voice agent calling - enable outbound and inbound calls in 130+ countries via dashboard or API
  * [Vapi integration (dashboard)](/docs/integrations/vapi-dashboard) — Connect Vapi to Vobiz SIP trunking without code - no-code dashboard walkthrough to receive inbound calls and make outbound calls in 130+ countries
  * [Vapi integration (API)](/docs/integrations/vapi-api) — Connect Vapi to Vobiz SIP trunking via API - route inbound calls to any Vapi AI assistant and place outbound calls to 130+ countries programmatically
* **Retell AI**
  * [Retell AI integration (dashboard)](/docs/integrations/retellai-dashboard) — Connect Retell AI to Vobiz SIP trunking without code - no-code dashboard setup for outbound and inbound AI voice calls in 130+ countries
  * [Retell AI integration (API)](/docs/integrations/retellai-api) — Connect Retell AI to Vobiz SIP trunking via API - programmatic outbound and inbound call routing for AI voice agents across 130+ countries
* **ElevenLabs**
  * [ElevenLabs integration](/docs/integrations/elevenlabs) — ElevenLabs connects to Vobiz SIP trunking for ultra-realistic AI voice calls - enable outbound and inbound calling in 130+ countries via dashboard or..
  * [ElevenLabs integration (dashboard)](/docs/integrations/elevenlabs-dashboard) — ElevenLabs connects to Vobiz SIP trunking without code - no-code dashboard setup for AI voice agents with ultra-realistic TTS voices in 130+..
  * [ElevenLabs integration (API)](/docs/integrations/elevenlabs-api) — Connect ElevenLabs to Vobiz SIP trunking via API - programmatic setup for ultra-realistic AI voice agents on outbound and inbound calls in 130+..
* [LiveKit integration](/docs/integrations/livekit) — LiveKit connects to Vobiz SIP trunking for real-time AI voice agents - inbound and outbound calling across 130+ countries with dispatch rules and..
* [Pipecat integration](/docs/integrations/pipecat) — Pipecat connects to Vobiz SIP trunking to power AI voice pipelines on real phone calls - WebSocket streaming and SIP trunk setup across 130+..
* [Sarvam integration](/docs/integrations/sarvam) — Take a Sarvam Samvaad voice agent live on a real phone number in minutes - Vobiz powers the Rent from Sarvam telephony option, so you complete KYC..
* [Bolna integration](/docs/integrations/bolna) — Connect Bolna.ai voice agents to Vobiz SIP trunking for global inbound and outbound calling across 130+ countries, including India
* [Dograh integration](/docs/integrations/dograh) — Connect Vobiz telephony to a self-hosted Dograh instance to place and receive AI voice-agent calls - Docker setup, telephony config, and the..
* [Rapida AI integration](/docs/integrations/rapida-ai) — Connect an open-source Rapida AI deployment to Vobiz for inbound and outbound AI phone calls using Vobiz applications, the REST API, and..
* [Ultravox Integration](/docs/integrations/ultravox) — Run Ultravox conversational AI over Vobiz SIP trunking - configure your trunk, dispatch outbound calls, and reach 130+ countries including India
* [Smallest AI Integration](/docs/integrations/smallest-ai) — Connect a Smallest AI voice agent to Vobiz SIP trunking - import a Vobiz number over SIP for outbound calls and route inbound calls to your agent..
* [Agora Integration](/docs/integrations/agora) — Connect an Agora Conversational AI agent to Vobiz SIP trunking - add a Vobiz number to Agora for outbound campaigns and route inbound calls to your..
* [xAI Grok Voice Integration](/docs/integrations/xai) — Connect a Vobiz phone number to an xAI Grok voice agent over Direct SIP with TLS - bring your own number in regions where xAI does not provision..
* [Build an AI voice agent with WebSockets](/docs/integrations/websockets) — Connect a custom AI voice agent to Vobiz with bidirectional WebSocket audio, direction-specific formats, playback, checkpoints, and barge-in
* [OpenAI Realtime SIP Call Handler](/docs/integrations/openai-realtime) — Connect inbound Vobiz SIP calls directly to OpenAI's Realtime API for natural, low-latency AI voice conversations across 130+ countries including..
* [Gemini Live Voice Agent](/docs/integrations/gemini-live) — Bridge a Vobiz XML \<Stream> to Google's Gemini Live API to build a phone-callable voice agent with real barge-in and no audio resampling anywhere in..
* [Deepgram Voice Agent](/docs/integrations/deepgram) — Bridge a Vobiz XML \<Stream> to the Deepgram Voice Agent API for a phone-callable agent on Deepgram's India region, with Flux STT, Indian-accented..
* [Vobiz WebRTC Playground](/docs/integrations/webrtc-application-setup) — Make and receive browser-based phone calls with the Vobiz WebRTC Playground using your API credentials and a Vobiz DID

### Official SDKs

* [Python SDK](/docs/integrations/python-sdk) — Build Python voice apps with the Vobiz SDK - outbound calls, SIP trunking, VobizXML, and Flask webhook handlers for 130+ countries including India
* [Node.js SDK](/docs/integrations/node-sdk) — Build Node.js and TypeScript voice apps with the Vobiz SDK - outbound calls, SIP trunks, CDR, and call recording across 130+ countries including..
* [Ruby SDK](/docs/integrations/ruby-sdk) — Build Ruby and Rails voice apps with the Vobiz SDK - outbound calls, SIP trunks, DID management, and VobizXML for global calling in 130+ countries
* [Go SDK](/docs/integrations/go-sdk) — Build Go voice apps with the Vobiz SDK - place outbound calls, manage SIP trunks, and craft VobizXML synchronously for 130+ countries including India
* [C# / .NET SDK](/docs/integrations/csharp-sdk) — Build C# and .NET 8 voice apps with the Vobiz SDK - outbound calls, SIP trunks, and VobizXML with native DI for global calling in 130+ countries
* [Java SDK](/docs/integrations/java-sdk) — Build Java voice apps with the Vobiz SDK - outbound calls, SIP trunks, CDR, and call recording across 130+ countries including India
* [PHP SDK](/docs/integrations/php-sdk) — Build PHP voice apps with the Vobiz SDK - outbound calls, SIP trunks, CDR, and call recording across 130+ countries including India

### Browser & WebRTC

### Business Phone Systems

* [3CX integration](/docs/integrations/3cx) — Connect 3CX PBX to Vobiz SIP trunking for inbound and outbound calling across 130+ countries - configure a generic SIP trunk in minutes
* [Zoiper5 Integration](/docs/integrations/zoiper) — How to set up an XML application, create a SIP Endpoint, configure Zoiper5, and make an outbound call using Vobiz

### CRM & Helpdesk

* [Zendesk integration](/docs/integrations/zendesk) — Put a Vobiz softphone in the Zendesk top bar - click-to-call, screen pop, call logging to tickets, and recording playback for agents in 130+..
* [Freshdesk integration](/docs/integrations/freshdesk) — A Vobiz calling panel inside Freshdesk - browser-based inbound and outbound calls, click-to-call, and recording playback for agents in 130+ countries
* [HubSpot integration](/docs/integrations/hubspot) — Put a Vobiz softphone inside HubSpot - call from a contact record, talk in the browser, and let HubSpot log the call against the contact..
* [Pipedrive integration](/docs/integrations/pipedrive) — A Vobiz softphone inside Pipedrive - dial from the page, talk in the tab, and every call lands in the CRM as an Activity and a Call Log with a signed..
* [Zoho integration](/docs/integrations/zoho) — Vobiz as a Zoho PhoneBridge telephony provider - click-to-dial, live call states, and call logging with recordings across Zoho CRM, Desk, Recruit and..
* [Salesforce integration](/docs/integrations/salesforce) — A Vobiz softphone inside Salesforce Lightning over Open CTI - dial from any phone number in the CRM, talk in the browser, and every call is logged as..
* [ServiceNow integration](/docs/integrations/servicenow) — A Vobiz WebRTC softphone inside ServiceNow - agents call from a record or the OpenFrame panel, talk in the browser, and every call is written back to..
* [ClickUp integration](/docs/integrations/clickup) — A Vobiz WebRTC softphone that logs calls into ClickUp - agents dial in the browser, and each completed call becomes a ClickUp task carrying the CDR..
* [Expedify integration](/docs/integrations/expedify) — Connect Expedify's CRM and AI calling platform to Vobiz - configure outbound and inbound voice with your Auth ID, Auth Token, and Caller IDs from the..

### Migrations

* **Plivo**
  * [Plivo vs Vobiz - full comparison](/docs/compare/plivo/overview) — The complete, domain-by-domain Plivo to Vobiz migration reference: voice call API, call-control XML, phone numbers, SIP trunking, conferences..
  * [Migrate from Plivo with the AI Agent](/docs/compare/plivo/migration-agent) — Install the Vobiz migration skill for Claude Code and let the AI agent move your app from Plivo to Vobiz - converting PlivoXML to VobizXML, mapping..
  * [Plivo → Vobiz: Code Snippets for Common Tasks](/docs/compare/plivo/code-snippets) — Side-by-side Plivo and Vobiz code for the most common voice tasks - make an outbound call, answer with XML, play/speak/DTMF on a live call, record..
  * [Plivo Voice Call API → Vobiz: Endpoint & SDK Migration](/docs/compare/plivo/voice-call-api) — Map every Plivo Voice Call API endpoint and SDK method - make a call, list/get live & queued calls, hang up, transfer, play, speak, send DTMF, record..
  * [PlivoXML to VobizXML: Verb-by-Verb Call-Control Reference](/docs/compare/plivo/call-control-xml) — A complete verb-by-verb map of PlivoXML to VobizXML call control: GetDigits/GetInput to Gather, Dial, Record, Conference, Stream, plus every..
  * [Plivo vs Vobiz: Phone Numbers & DID API](/docs/compare/plivo/phone-numbers) — Migrate Plivo's PhoneNumber/Number API to Vobiz phone\_numbers.\*: search inventory, buy, release, list owned numbers, attach to trunks/sub-accounts..
  * [Plivo Zentrunk → Vobiz SIP Trunking Migration](/docs/compare/plivo/sip-trunking) — Map Plivo Zentrunk trunks, IP access lists, credentials, and origination URIs to Vobiz trunks, ip\_access\_control\_list, credentials, and..
  * [Plivo Conferences to Vobiz: XML + API Migration Guide](/docs/compare/plivo/conferences) — Map Plivo's Conference XML element and Conference/Member REST APIs to Vobiz
  * [Plivo to Vobiz: Recordings & Transcription Migration](/docs/compare/plivo/recordings) — Map Plivo's Record XML, Recording API, and transcription to Vobiz
  * [Plivo Subaccounts → Vobiz Sub-Accounts: Migration & Mapping](/docs/compare/plivo/sub-accounts) — Map Plivo's Subaccount API to Vobiz sub\_accounts.\* - create, list, update, delete, assign DIDs - plus the India KYC verification and 15-day DID..
  * [Plivo vs Vobiz: Webhooks, Callbacks & Signature Validation](/docs/compare/plivo/webhooks) — Map Plivo answer/ring/hangup callbacks and X-Plivo-Signature-V3 (HMAC) verification to Vobiz answer\_url events and X-Vobiz-Signature-V2/V3
  * [Plivo vs Vobiz: Server SDKs & XML Builder Migration](/docs/compare/plivo/sdks) — Port your Plivo server SDK code to Vobiz: 7-for-7 language parity, registry installs vs git-clone, client init (RestClient to Vobiz/VobizClient)..
* **Twilio**
  * [Twilio vs Vobiz - full comparison](/docs/compare/twilio/overview) — The complete, domain-by-domain Twilio to Vobiz migration reference: voice call API, TwiML to VobizXML, phone numbers, SIP trunking, conferences..
  * [Migrate from Twilio with the AI Agent](/docs/compare/twilio/migration-agent) — Install the Vobiz migration skill for Claude Code and let the AI agent move your app from Twilio to Vobiz - converting TwiML to VobizXML, mapping SDK..
  * [Twilio → Vobiz: Code Snippets for Common Tasks](/docs/compare/twilio/code-snippets) — Side-by-side Twilio and Vobiz code for the most common voice tasks - make an outbound call, answer with XML, control a live call, search a number..
  * [Twilio Voice Call API → Vobiz](/docs/compare/twilio/voice-call-api) — Migrate Twilio Programmable Voice outbound calls and live call control to Vobiz
  * [TwiML → VobizXML: verb-by-verb](/docs/compare/twilio/twiml-to-vobizxml) — Map every TwiML voice verb to its VobizXML equivalent - Say→Speak, Play→Play, Gather→Gather, Dial→Dial, Record, Conference, Stream and more
  * [Twilio → Vobiz: Phone Numbers & DID](/docs/compare/twilio/phone-numbers) — Migrate Twilio's AvailablePhoneNumber search and IncomingPhoneNumber provisioning to Vobiz phone\_numbers.\*: browse inventory, purchase by E.164, list..
  * [Twilio Elastic SIP Trunking → Vobiz SIP Trunking](/docs/compare/twilio/sip-trunking) — Migrate from Twilio Elastic SIP Trunking to Vobiz
  * [Twilio Conferences → Vobiz Conferences](/docs/compare/twilio/conferences) — Migrate Twilio conference rooms to Vobiz: map conferences.list()/fetch(), participants.create/list/update(muted/hold)/delete, and the \<Conference>..
  * [Twilio Recordings & Transcription → Vobiz](/docs/compare/twilio/recordings) — Migrate Twilio call recording and transcription to Vobiz: map recordings.list / fetch / delete, in-call recording (calls(sid).recordings.create), the..
  * [Twilio Subaccounts → Vobiz Sub-Accounts](/docs/compare/twilio/subaccounts) — Migrate Twilio subaccounts to Vobiz. Map api.accounts.create / list / update(status) and subaccount auth to Vobiz sub\_accounts.create\_subaccount /..
  * [Twilio Webhooks & Signatures → Vobiz](/docs/compare/twilio/webhooks) — Migrate Twilio voice webhooks to Vobiz: map request params (CallSid, From, To, Direction, CallStatus, Digits, SpeechResult) to Vobiz call params and..
  * [Twilio Helper Libraries → Vobiz SDKs](/docs/compare/twilio/sdks) — Migrate from Twilio's helper libraries (twilio-python, twilio-node, and the seven official languages) to the Vobiz SDKs: client init..

## Examples & Tutorials

### Guides

* [Build an AI Voice Agent](/docs/guides/ai-voice-agent) — Connect leading conversational AI platforms - Vapi, Retell, ElevenLabs, Pipecat, LiveKit - directly to real phone numbers using Vobiz SIP trunking
* [Build an inbound AI voice agent](/docs/guides/ai-voice-agent/inbound) — Set up an AI-powered inbound voice agent on Vobiz that answers incoming calls and routes audio to your agent platform over SIP trunking..
* [Build an outbound AI voice agent](/docs/guides/ai-voice-agent/outbound) — Set up an AI-powered voice agent on Vobiz that places outbound calls - dial out from your agent platform over Vobiz SIP trunking with full control
* [Migrate from Plivo to Vobiz](/docs/guides/plivo-to-vobiz) — Move your voice app from Plivo to Vobiz in hours, not weeks
* [Authentication & base URL](/docs/guides/plivo-to-vobiz/auth-and-base-url) — Migrate authentication and the API base URL from Plivo to Vobiz - swap the SDK package, switch raw HTTP to the X-Auth-ID and X-Auth-Token headers..
* [Endpoint & SDK mapping](/docs/guides/plivo-to-vobiz/endpoint-mapping) — Map every Plivo REST endpoint and SDK method to its Vobiz equivalent
* [Convert PlivoXML to VobizXML](/docs/guides/plivo-to-vobiz/xml-migration) — Migrate your Plivo call-control XML to VobizXML
* [Webhooks & signature validation](/docs/guides/plivo-to-vobiz/webhooks-and-signatures) — Migrate your Plivo webhook handlers and signature verification to Vobiz - the params and the HMAC-SHA256 scheme are nearly identical, you mostly swap..
* [Gotchas & breaking changes](/docs/guides/plivo-to-vobiz/gotchas) — The handful of real breaking changes when migrating from Plivo to Vobiz - XML verb renames, path casing, required status params, webhook signatures..
* [Phone numbers (you can't port from Plivo)](/docs/guides/plivo-to-vobiz/number-porting) — When migrating from Plivo to Vobiz you cannot port or transfer your Plivo numbers - there is no porting flow
* [Cutover checklist](/docs/guides/plivo-to-vobiz/cutover-checklist) — An end-to-end runbook for moving a production Plivo voice app to Vobiz with minimal risk - swap creds, convert XML, re-point webhooks, canary..

### How-Tos

### LiveKit Templates

* [Call transfer agent](/docs/examples/vobiz-livekit-call-transfer-example) — Transfer an active Vobiz call to any E.164 phone number via SIP REFER from inside a LiveKit AI voice agent - full code, payloads, and trunk setup
* [LiveKit IVR with DTMF](/docs/examples/vobiz-livekit-ivr-dtmf-example) — Build an IVR menu in a LiveKit AI voice agent on Vobiz that responds to DTMF keypad input in addition to spoken voice commands - Python example
* [Agent-to-agent handoff](/docs/examples/vobiz-livekit-agent-to-agent-handoff-example) — Transfer an active Vobiz call from one LiveKit AI agent to a specialized agent mid-conversation while preserving full conversation context and..
* [Answering machine detection](/docs/examples/livekit-vobiz-machine-detection-agent-example) — Detect whether an outbound LiveKit call reached a human or a voicemail machine on Vobiz before your AI agent begins speaking - Python example
* [LiveKit all-features example](/docs/examples/livekit-vobiz-all-feature-example) — A single LiveKit agent example demonstrating inbound, outbound, transfers, DTMF, answering machine detection, and webhooks together on Vobiz
* [LiveKit webhook & CRM integration](/docs/examples/livekit-vobiz-webhook-integration-example) — Push Vobiz call events to your CRM in real time using HMAC-signed webhooks and LiveKit function tools - end-to-end Python example with sample..
* [LiveKit inbound calling](/docs/examples/livekit-vobiz-inbound) — Route inbound calls from any Vobiz phone number to a LiveKit AI voice agent over SIP trunking with real-time audio streaming - Python example
* [LiveKit outbound calling](/docs/examples/livekit-vobiz-outbound) — Place outbound calls from a LiveKit AI voice agent via a Vobiz SIP trunk, with per-call dispatch metadata and end-of-call webhooks - Python example

### Server Templates

* [Vobiz + Pipecat](/docs/examples/vobiz-x-pipecat) — Stream raw Vobiz call audio into a Pipecat AI voice agent pipeline using WebSocket transport - covers trunk setup, Python code, and pipeline wiring
* [Bun Media Stream Server](/docs/examples/vobiz-bun-media-stream) — Minimal Bun WebSocket server that receives Vobiz call audio, writes it to WAV, and logs status callbacks
* [Bare-metal XML WebSocket](/docs/examples/vobiz-all-xml) — Build a real-time AI voice agent on Vobiz using only the XML WebSocket streaming primitive - no LiveKit, no Pipecat, no third-party SDK required
* [IVR menu](/docs/examples/vobiz-ivr-xml-python) — Build a multi-level Interactive Voice Response menu on Vobiz with dynamic configuration, DTMF keypad routing, and call analytics tracking in Python
* [Call queue](/docs/examples/vobiz-call-queue-xml-python) — Build a hold-music call queue on Vobiz featuring round-robin agent dispatch, configurable retry cycles, and voicemail fallback - Python and XML..
* [Call survey](/docs/examples/vobiz-call-survey-xml-python) — Run an outbound three-question DTMF voice survey on Vobiz, store results via the API, and export responses to CSV - complete Python and XML example
* [Appointment reminder](/docs/examples/vobiz-appointment-reminder-xml-python) — Send outbound appointment reminder calls on Vobiz with confirm, reschedule, and cancel DTMF options - every outcome stored per appointment in Python
* [OTP call](/docs/examples/vobiz-otp-call-xml-python) — Generate a six-digit OTP, place a Vobiz outbound call, read it digit by digit to the caller, and verify the response on your backend - Python example
* [Voicemail](/docs/examples/vobiz-voicemail-xml-python) — Capture caller voice messages on Vobiz using the Record verb, store recordings as MP3, and retrieve them via the admin API - Python and XML example
* [Number capture](/docs/examples/vobiz-number-capture-xml-python) — Collect a caller's phone number on Vobiz via DTMF keypad input with the # terminator, validation, and duplicate detection in a Python XML example
* [Two-way number masking](/docs/examples/vobiz-two-way-number-masking-python) — Connect a field agent and a customer through two masking DIDs so neither sees the other's real number, bidirectional call masking with FastAPI and..

### Use Cases

* [Solutions](/docs/solutions) — Build production-ready voice applications with Vobiz telephony platform
* [AI Voice Agent – Deploy 24/7 AI Phone Agents at Scale | Vobiz](/docs/solutions/ai-voice-agent) — Deploy 24/7 AI voice agents that handle real callers at scale
* [Cloud IVR](/docs/solutions/cloud-ivr) — Build programmable cloud IVR on Vobiz with DTMF, speech recognition, and intelligent routing - no hardware, globally available across 130+ countries
* [Contact Centre](/docs/solutions/contact-centre) — Build a fully custom contact centre on Vobiz - inbound routing, queuing, recording, and AI augmentation without per-seat CCaaS pricing, across 130+..
* [Conference Calling](/docs/solutions/conference-calling) — Host multi-party calls with live moderation, recording, and coach mode
* [Automated Outbound Calling](/docs/solutions/automated-outbound-calling) — Reach thousands of customers with personalised voice calls at scale
* [Appointment Reminders](/docs/solutions/appointment-reminders) — Cut no-show rates with automated voice appointment reminders that confirm, reschedule, or cancel via keypad - deployed across 130+ countries
* [Call Recording](/docs/solutions/call-recording) — Capture, store, and analyse call audio for compliance, QA, and AI training
* [Number Masking](/docs/solutions/number-masking) — Connect two parties through proxy DIDs so neither sees the other's real number, two-way call masking for ride-hailing, delivery, and marketplaces on..
* [Call Transfer](/docs/solutions/call-transfer) — Move active calls between agents, teams, or IVRs on Vobiz globally - warm transfers, blind transfers, SIP REFER, and full context preservation
* [Call Escalation](/docs/solutions/call-escalation) — Automatically route complex calls to senior handlers with full context intact
* [Agent-to-Agent Handoff](/docs/solutions/agent-to-agent-handoff) — Transfer calls from AI to human agents without losing context - Vobiz carries full transcripts and call metadata through warm handoffs across 130+..
* [Post-Call Analytics](/docs/solutions/post-call-analytics) — Turn every completed call into structured business intelligence using Vobiz CDR and recording APIs
* [CRM Integration](/docs/solutions/crm-integration) — Eliminate manual call logging by auto-syncing every call, recording, and outcome to your CRM via Vobiz webhooks

### Industries

* [Healthcare](/docs/solutions/healthcare) — Automate patient appointment booking, triage, reminders, and teleconsultation with Vobiz
* [Finance & Fintech](/docs/solutions/finance-fintech) — Scale collections, fraud alerts, and KYC onboarding with a compliant voice API built for fintech
* [Logistics & Delivery](/docs/solutions/logistics-delivery) — Automate last-mile delivery confirmations, ETA alerts, and driver-customer coordination with Vobiz
* [E-commerce & Retail](/docs/solutions/ecommerce-retail) — Reduce RTO and recover revenue with automated COD confirmations, delivery alerts, and post-purchase surveys
* [Real Estate](/docs/solutions/real-estate) — Qualify leads and automate site-visit scheduling at scale with Vobiz - IVR routing, outbound call campaigns, and CRM integration for property..

### Compare Platforms

* [Vobiz vs Twilio: Best Voice API for India in 2025](/docs/compare/vobiz-vs-twilio) — Twilio charges in USD with no TRAI compliance
* [Vobiz vs Plivo: Voice API Comparison for India 2025](/docs/compare/vobiz-vs-plivo) — Plivo has pivoted to AI agents and bills in USD
* [Vobiz vs Telnyx: Voice API Pricing and Features in India](/docs/compare/vobiz-vs-telnyx) — Telnyx is built for global reach but lacks India-specific compliance
* [Vobiz vs Vonage: Voice API for India, Pricing and Features](/docs/compare/vobiz-vs-vonage) — Vonage bundles enterprise complexity with USD billing and no TRAI compliance
* [Vobiz vs Exotel: Voice API Comparison for India 2025](/docs/compare/vobiz-vs-exotel) — Exotel requires a sales demo and locks out developers
* [Vobiz vs JustCall: Developer API vs Business Phone System](/docs/compare/vobiz-vs-justcall) — JustCall is a sales phone app, not a developer API
* [Vobiz vs TeleCRM: Voice API vs Sales CRM, India 2025](/docs/compare/vobiz-vs-telecrm) — TeleCRM is sales software, not a developer API

## Blogs

### Blogs

* [Vobiz Blog](/docs/blogs) — Guides, deep-dives, and product updates from the Vobiz team - voice AI engineering, telephony best practices, and platform announcements

### Articles

* [What is Voice Transcription (ASR)? How Telephony Affects Accuracy (2026)](/docs/blogs/what-is-voice-transcription-asr) — Voice transcription (ASR) turns speech into text
* [What is Caller ID and CNAM? How Caller Name Display Works (2026)](/docs/blogs/what-is-caller-id-cnam) — Caller ID shows the number; CNAM shows the name
* [What is Call Routing? Types, How It Works & Examples (2026 Guide)](/docs/blogs/what-is-call-routing) — Call routing decides which endpoint a call reaches
* [What is WebRTC? How It Works, APIs, Codecs & Voice AI (2026 Guide)](/docs/blogs/what-is-webrtc) — WebRTC explained: how it works (getUserMedia, signaling, SDP, ICE/STUN/TURN, SRTP), the core APIs, codecs, WebRTC vs SIP, and WebRTC for voice AI
* [What is Answering Machine Detection (AMD)? How It Works in 2026](/docs/blogs/what-is-answering-machine-detection) — Answering Machine Detection (AMD) tells you if a human or voicemail picked up
* [What is a Multi-Level IVR? Nested Menus, Routing & How to Build One](/docs/blogs/what-is-multi-level-ivr) — A multi-level IVR nests phone menus so callers self-route through sub-menus
* [What is E.164 Phone Number Formatting? The Complete Guide (2026)](/docs/blogs/what-is-e164-phone-number-formatting) — E.164 is the global standard for phone numbers: +country code, up to 15 digits, no leading zeros
* [Toll-Free vs Local vs Mobile Numbers: The 2026 Guide](/docs/blogs/toll-free-vs-local-vs-mobile-numbers) — Toll-free vs local vs mobile numbers compared: US prefixes, area codes, A2P/10DLC, SMS deliverability, cost, caller perception, and when to use each..
* [What Is a Virtual Phone Number? How It Works, Types & Uses (2026)](/docs/blogs/what-is-a-virtual-phone-number) — A virtual phone number is a real number not tied to a SIM or copper line
* [What is a DID Number? Direct Inward Dialing Explained (2026)](/docs/blogs/what-is-a-did-number) — A DID number is a phone number that routes straight to a specific endpoint
* [What Is a Call Leg? A-Leg vs B-Leg in Programmable Voice](/docs/blogs/what-is-a-call-leg) — A call leg is one connection between the platform and one party
* [Scaling Outbound: Mastering Automated Calling & Answering Machine Detection in 2026](/docs/blogs/automated-calling-answering-machine-detection) — How automated outbound calling and answering machine detection work in 2026 - dialer pacing, CPS vs concurrency, and AMD across major voice APIs
* [Mastering Call Transfers in 2026: The Switch to Context-Aware Programmable Voice](/docs/blogs/context-aware-call-transfers) — Call transfer in 2026: blind vs warm vs supervised, the SIP REFER/Replaces/UUI protocol layer, programmable per-leg transfer, and AI handoff
* [Building Compliant Pipelines: The State of Call Recording APIs in 2026](/docs/blogs/call-recording-apis-compliant-pipelines) — Call recording APIs in 2026 - dual vs mono channels, WAV/MP3, transcription pipelines, encryption & retention, and consent/PCI/GDPR-compliant design
* [Designing Intelligent Call Escalations: Going Beyond Blind Transfers in 2026](/docs/blogs/intelligent-call-escalations) — Escalation design in 2026: triggers, skills-based routing, AI-to-human handoff with context, and conference-based supervisor controls
* [What is Number Masking? How Two-Way Call Masking Works](/docs/blogs/what-is-number-masking) — Number masking hides both parties' real phone numbers behind a proxy DID
* [What is VoIP? How It Works, Types, Costs & Setup (2026 Guide)](/docs/blogs/what-is-voip) — VoIP turns phone calls into internet data
* [What is SIP (Session Initiation Protocol)? The Complete 2026 Guide](/docs/blogs/what-is-sip) — SIP sets up and ends almost every internet call
* [SIP vs VoIP: What's the Difference? The Complete 2026 Guide](/docs/blogs/sip-vs-voip) — SIP and VoIP aren't the same, VoIP is the category, SIP is the protocol
* [What is an IVR (Interactive Voice Response)? The Complete 2026 Guide](/docs/blogs/what-is-an-ivr) — An IVR is the automated phone menu that greets and routes callers
* [What is SIP Trunking?](/docs/blogs/what-is-sip-trunking) — SIP trunking connects your phone system to the internet, replacing physical phone lines
* [Call Center Optimization with AI: The Complete Guide](/docs/blogs/call-center-optimization-with-ai) — Call center optimization that lifts efficiency and CSAT without burning out agents - key metrics, a 5-step plan, and AI building blocks like IVR and..
* [What is a Voice API?](/docs/blogs/what-is-a-voice-api) — Learn what a voice API is and how it streamlines business communication with call routing, IVR, and more - plus transparent INR pricing with Vobiz
* [What is a Landline Number?](/docs/blogs/what-is-a-landline-number) — Understand what a landline number is, its role, types, and reliable benefits

## Unlinked pages

These pages are published and crawlable but are not reachable from the sidebar. If a page belongs in the docs, add it to `docs.json`; if it does not, add it to `.mintignore`.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.