> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Partner API Reference

> Complete reference for the Vobiz Partner API - endpoints across capacity allocation, authentication, customer provisioning, billing, CDRs, DIDs, KYC sessions, and analytics for resellers.

[← Partner Overview](/docs/partner)

Complete API reference for the Vobiz Partner Portal. Covers authentication, customer management, CPS and concurrency allocation, billing, CDRs, KYC, and more.

<Card title="End-to-end integration flow" icon="route" href="/docs/partner/flow">
  Follow the complete lifecycle from account creation to trunk setup.
</Card>

## Base URL & Authentication

All Partner API endpoints share a single base URL:

```
https://api.vobiz.ai/api/v1/partner
```

Every request must include the headers `X-Auth-ID` and `X-Auth-Token`. See [Authentication](/docs/partner/api/authentication) for full details.

Do not have credentials yet? [Contact support@vobiz.ai](mailto:support@vobiz.ai) to enable Partner access.

## API Sections

<CardGroup cols={2}>
  <Card title="Authentication" icon="key" href="/docs/partner/api/authentication">
    Header-based credentials and JWT login.
  </Card>

  <Card title="Profile" icon="id-card" href="/docs/partner/api/profile">
    Identity, balance, and GST configuration.
  </Card>

  <Card title="Dashboard & Analytics" icon="chart-line" href="/docs/partner/api/analytics">
    Live metrics and date-range performance reporting.
  </Card>

  <Card title="Customer Accounts" icon="users" href="/docs/partner/api/customers">
    Provision sub-accounts under your partner umbrella.
  </Card>

  <Card title="Balance Transfer" icon="wallet" href="/docs/partner/api/balance">
    Move credit from your master wallet to customers.
  </Card>

  <Card title="CPS and concurrency" icon="gauge" href="/docs/partner/api/capacity">
    Allocate and reclaim customer call capacity from your partner pool.
  </Card>

  <Card title="KYC Sessions" icon="id-badge" href="/docs/partner/api/kyc-sessions">
    Initiate and manage customer KYC verification.
  </Card>

  <Card title="Transactions" icon="receipt" href="/docs/partner/api/transactions">
    Per-customer and global financial ledgers.
  </Card>

  <Card title="CDRs" icon="phone" href="/docs/partner/api/cdrs">
    Call detail records for billing and troubleshooting.
  </Card>

  <Card title="Phone Numbers" icon="hashtag" href="/docs/partner/api/numbers">
    DID inventory across all customer accounts.
  </Card>
</CardGroup>

## All Endpoints at a Glance

| Method | Endpoint | Description | Docs |
| - | - | - | - |
| POST | `/login` | Exchange email/password for JWT access token | [Auth](/docs/partner/api/authentication) |
| GET | `/me` | Retrieve partner profile and balance | [Profile](/docs/partner/api/profile) |
| GET | `/dashboard` | Live partner dashboard summary | [Analytics](/docs/partner/api/analytics) |
| GET | `/analytics` | Date-range aggregated call analytics | [Analytics](/docs/partner/api/analytics) |
| POST | `/accounts` | Create a customer sub-account | [Customers](/docs/partner/api/customers) |
| GET | `/accounts` | List all customer accounts | [Customers](/docs/partner/api/customers) |
| GET | `/accounts/{customer_auth_id}` | Get customer profile | [Customers](/docs/partner/api/customers) |
| GET | `/accounts/{customer_auth_id}/balance` | Get customer wallet balance | [Customers](/docs/partner/api/customers) |
| POST | `/accounts/{customer_auth_id}/transfer-balance` | Transfer credit to a customer | [Balance](/docs/partner/api/balance) |
| POST | `/kyc-sessions` | Initiate KYC for a sub-account | [KYC](/docs/partner/api/kyc-sessions) |
| GET | `/kyc-sessions` | List KYC sessions (paginated) | [KYC](/docs/partner/api/kyc-sessions) |
| GET | `/kyc-sessions/{session_id}` | Get a KYC session by ID | [KYC](/docs/partner/api/kyc-sessions) |
| POST | `/kyc-sessions/{session_id}/resend` | Resend the KYC email | [KYC](/docs/partner/api/kyc-sessions) |
| DELETE | `/kyc-sessions/{session_id}` | Revoke a KYC session | [KYC](/docs/partner/api/kyc-sessions) |
| GET | `/accounts/{customer_auth_id}/transactions` | Customer transaction ledger | [Transactions](/docs/partner/api/transactions) |
| GET | `/transactions` | Global transaction ledger | [Transactions](/docs/partner/api/transactions) |
| GET | `/accounts/{customer_auth_id}/cdrs` | Customer CDR list | [CDRs](/docs/partner/api/cdrs) |
| GET | `/accounts/{customer_auth_id}/cdrs/{call_uuid}` | Single CDR by UUID | [CDRs](/docs/partner/api/cdrs) |
| GET | `/cdrs` | Global CDR list | [CDRs](/docs/partner/api/cdrs) |
| GET | `/accounts/{customer_auth_id}/numbers` | Numbers assigned to a customer | [Numbers](/docs/partner/api/numbers) |
| GET | `/numbers` | Global number inventory | [Numbers](/docs/partner/api/numbers) |

## Capacity allocation endpoints

| Method | Endpoint | Description | Docs |
| - | - | - | - |
| POST | `/accounts/{customer_auth_id}/concurrency/transfer` | Transfer CPS or concurrent-call slots to a customer | [Capacity](/docs/partner/api/capacity) |
| POST | `/accounts/{customer_auth_id}/concurrency/reclaim` | Reclaim previously allocated capacity | [Capacity](/docs/partner/api/capacity) |
| GET | `/accounts/{customer_auth_id}/concurrency` | Inspect both resources and allocations | [Capacity](/docs/partner/api/capacity) |
| GET | `/concurrency/transfers` | List capacity transfers | [Capacity](/docs/partner/api/capacity) |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.