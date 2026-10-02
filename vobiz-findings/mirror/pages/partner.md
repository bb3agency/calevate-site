> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Partner Portal – Reseller & White-Label telephony Program

> Vobiz Partner Program gives resellers full API control over account provisioning, balance transfers, DID inventory, CDR access, and analytics - white-label telephony platform across 130+ countries.

<Note>
  You're viewing the **Partner Portal** - a separate product from SIP Trunking, Voice XML, and WhatsApp. [← Back to main docs](/docs/introduction)
</Note>

The Vobiz Partner Program gives resellers and platform builders full programmatic control over their entire customer ecosystem - account provisioning, balance management, DID inventory, CDR access, and analytics - through a single API.

As a Vobiz Partner, you are the **master account**. You hold the primary balance, create and fund customer sub-accounts, and have read-visibility into all their traffic and transactions.

## Enable Partner Access

<Warning>
  The Partner API is not enabled by default. To become a Vobiz Partner and unlock access to the Partner Portal and API, [email us](mailto:support@vobiz.ai?subject=Partner%20Program%20Access%20Request). We will set up your partner account, issue your credentials, and onboard you to the reseller program.

  **Typical response time:** 1 business day.
</Warning>

## What is the Partner Program?

The Partner Program is Vobiz's white-label reseller infrastructure. It lets you build a voice platform on top of Vobiz's SIP trunking and telephony backbone - provisioning Vobiz accounts for your own end-customers, funding their wallets from your master balance, and monitoring their usage - all without your customers needing to interact with Vobiz directly.

There are three actors in this model:

* **You (Partner / Master Account)** - Hold the primary Vobiz balance. Billing entity. Full API access. Creates and funds all customer accounts.
* **Your Customers (Child Accounts)** - Virtual wallet funded by you. Get DIDs assigned by you. Make and receive calls on Vobiz infrastructure. Invisible to Vobiz billing.
* **Vobiz (Infrastructure)** - Provides SIP trunking, phone numbers, call routing, CDRs, and the partner API layer.

## How It Works

<Steps>
  <Step title="Get partner credentials">
    Contact [support@vobiz.ai](mailto:support@vobiz.ai). You will receive a Partner ID (`X-Auth-ID`) and Auth Token (`X-Auth-Token`) tied to your master account.
  </Step>

  <Step title="Create customer accounts">
    Use the [Create Customer Account API](/docs/partner/api/customers) to provision a sub-account for each of your clients. Store the returned `auth_id` in your database.
  </Step>

  <Step title="Fund customer wallets">
    Transfer balance from your partner account to each customer wallet using the [Transfer Balance API](/docs/partner/api/balance). Customers cannot make calls without balance.
  </Step>

  <Step title="Assign phone numbers">
    Use the Vobiz Console or [Numbers API](/docs/partner/api/numbers) to assign DID phone numbers to each customer account.
  </Step>

  <Step title="Monitor usage and billing">
    Pull [CDRs](/docs/partner/api/cdrs) and [transaction logs](/docs/partner/api/transactions) for any customer at any time. Use [analytics](/docs/partner/api/analytics) to identify top spenders, troubleshoot call quality, and run monthly billing cycles.
  </Step>
</Steps>

## Authentication

The Partner API uses the same dual-header authentication as the core Vobiz API. Every request must include your Partner credentials - retrievable from the [Partner Console](https://console.vobiz.ai).

* **`X-Auth-ID`** *(required)* - Your permanent Partner ID (e.g. `partner-882...`). This never changes.
* **`X-Auth-Token`** *(required)* - Your rotating secret API token. Rotate immediately if compromised.
* **`Accept`** *(required)* - Must be `application/json` on all GET and POST requests.
* **`Content-Type`** *(POST/PUT only)* - Must be `application/json` for all POST/PUT requests with a body.

<Warning>
  **Security:** Never expose your `X-Auth-Token` in client-side code, browser console, or version control. If compromised, rotate it immediately in the [Partner Console](https://console.vobiz.ai).
</Warning>

## Get Partner Access

Partner access is not self-serve. It requires a brief onboarding process where the Vobiz team verifies your use case, sets up your master account, configures your balance and credit limits, and issues your credentials.

<Card title="Email us to enable Partner access" icon="envelope" href="mailto:support@vobiz.ai?subject=Partner%20Program%20Access%20Request&body=Company:%20%0D%0AUse%20case:%20%0D%0AMonthly%20call%20volume:%20%0D%0AStarting%20credit:%20">
  Send an email to **[support@vobiz.ai](mailto:support@vobiz.ai)** with your company name, intended use case (reseller, platform builder, enterprise), and approximate expected call volume. We will get back to you within 1 business day.
</Card>

## API Reference

<Columns cols={2}>
  <Card title="Example partner flow" icon="route" href="/docs/partner/flow">
    Walk through a complete reseller onboarding flow - from master account setup to provisioning the first customer.
  </Card>

  <Card title="Partner API endpoints" icon="terminal" href="/docs/partner/api">
    Full reference for all Partner API endpoints - authentication, profile, customers, balance, transactions, CDRs, numbers, and analytics.
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.