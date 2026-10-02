> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Account API – Manage Balance, Credentials & Concurrency

> Manage your Vobiz account via REST API - retrieve balance, concurrency limits, CPS, auth credentials, and billing mode for prepaid or postpaid plans across 130+ countries.

Use the Account object to perform actions on your Vobiz account.

<Info>
  **Key Features**

  * View account type (standard or developer) and billing mode (prepaid or postpaid)
  * Monitor account balance and credit information
  * Preview and purchase additional CPS or concurrent-call capacity
  * Access auth credentials and resource URIs for API integration
</Info>

## Base URI

```text theme={null}
https://api.vobiz.ai/api/v1/Account/
```

<Note>
  API path casing is significant. Most account operations use `/Account/`, while the capacity pricing and subscription endpoints use lowercase `/accounts/{auth_id}/`.
</Note>

## Account Operations

<CardGroup cols={2}>
  <Card title="The Account Object" icon="cube" href="/docs/account/account-object">
    View the structure and attributes of the Account object including account type, billing mode, credits, and timezone.
  </Card>

  <Card title="Retrieve Account Details" icon="download" href="/docs/account/retrieve-account">
    GET request to retrieve all details of your Vobiz account including balance, auth credentials, and settings.
  </Card>

  <Card title="Balance" icon="wallet" href="/docs/account/balance">
    Check available balance, reserved funds, promotional credit, and credit limit by currency.
  </Card>

  <Card title="Transactions" icon="receipt" href="/docs/account/transactions">
    Retrieve the credit and debit ledger with per-day totals and reference-type breakdowns.
  </Card>

  <Card title="Concurrency" icon="bolt" href="/docs/account/concurrency">
    Monitor and manage the number of concurrent lines being used in your account.
  </Card>

  <Card title="Preview capacity pricing" icon="calculator" href="/docs/account/channel-pricing-preview">
    Calculate the monthly price for additional CPS or concurrent-call capacity without purchasing it.
  </Card>

  <Card title="Purchase capacity" icon="gauge-high" href="/docs/account/channel-subscriptions">
    Purchase recurring CPS or concurrent-call capacity for your account.
  </Card>
</CardGroup>

## What to do next

<CardGroup cols={2}>
  <Card title="Retrieve your account details" icon="user" href="/docs/account/retrieve-account">
    Fetch auth credentials, balance, and account type via API. (2 min)
  </Card>

  <Card title="Create a SIP trunk" icon="server" href="/docs/trunks/create-trunk">
    Provision your first trunk and get a unique SIP domain. (3 min)
  </Card>

  <Card title="Buy a phone number" icon="phone" href="/docs/account-phone-number">
    Search and rent a DID number for inbound calling.
  </Card>

  <Card title="Sub-accounts" icon="sitemap" href="/docs/sub-accounts">
    Isolate usage and billing for different customers or environments.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.