> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz Sub-Accounts API – Multi-Tenant & Reseller Account Management

> Provision and manage isolated customer sub-accounts under a Vobiz parent account - segmented billing, independent credentials, and usage tracking for SaaS and resellers globally.

Subaccounts let you manage multiple customer accounts under a single parent Account. Use them to segment, manage, and track each user's usage independently.

## Base URI

```text theme={null}
https://api.vobiz.ai/api/v1/Account/{auth_id}/Subaccount/
```

## Key features

<Info>
  * Complete resource isolation with dedicated auth credentials for secure multi-tenancy
  * Independent management of trunks, numbers, CDRs, and balances per subaccount
  * Parent account retains full administrative control over all subaccount operations
  * Each subaccount receives unique `auth_id` and `auth_token` for API access
</Info>

## Subaccount Operations

<CardGroup cols={2}>
  <Card title="The Subaccount Object" icon="cube" href="/docs/sub-accounts/subaccount-object">
    View the structure and attributes of the Subaccount object including auth credentials, enabled status, and resource URI.
  </Card>

  <Card title="Create a Subaccount" icon="plus" href="/docs/sub-accounts/create-subaccount">
    POST request to create a new subaccount with a name and enabled status. Returns unique auth credentials.
  </Card>

  <Card title="Retrieve a Subaccount" icon="download" href="/docs/sub-accounts/retrieve-subaccount">
    GET request to retrieve details of a specific subaccount including auth credentials and settings.
  </Card>

  <Card title="Update a Subaccount" icon="pen-to-square" href="/docs/sub-accounts/update-subaccount">
    PUT request to update subaccount name or enabled status. Disabling blocks all API calls and trunk usage.
  </Card>

  <Card title="Delete a Subaccount" icon="trash" href="/docs/sub-accounts/delete-subaccount">
    DELETE request to permanently remove a subaccount. Optionally cascade delete or reassociate resources.
  </Card>

  <Card title="List All Subaccounts" icon="list" href="/docs/sub-accounts/list-all-subaccounts">
    GET request to retrieve all subaccounts with pagination support. Sorted by creation date.
  </Card>

  <Card title="Sub-Account KYC" icon="id-card" href="/docs/sub-accounts/kyc/overview">
    Verify `customer_use` sub-accounts via the per-document API (PAN, GST, CIN, DigiLocker) or a hosted KYC session.
  </Card>
</CardGroup>

## Customer KYC (`kyc_mode`)

A sub-account's `kyc_mode` decides whether it needs its own verification:

| `kyc_mode` | KYC required? | Use it for |
| - | - | - |
| `personal_use` *(default)* | No - inherits the parent account's KYC. | Internal departments, dev/staging, your own workloads. |
| `customer_use` | Yes - the sub-account must verify itself before placing calls. Requires `email`. | Reseller customers and multi-tenant SaaS end-customers who must be KYC'd in their own name. |

A fresh `customer_use` sub-account is returned with `kyc_calls_blocked: true` and stays call-blocked until KYC completes. Drive verification with the [Sub-Account KYC API](/docs/sub-accounts/kyc/overview) - either per-document or via a [hosted session](/docs/sub-accounts/kyc/kyc-session) - and build against it risk-free using [Test Mode](/docs/sub-accounts/kyc/test-mode).

## Subaccount Use Cases

<CardGroup cols={2}>
  <Card title="Multi-Tenant SaaS" icon="users">
    Create a subaccount for each customer. Each customer gets isolated resources and its own API credentials for programmatic access.
  </Card>

  <Card title="Department Isolation" icon="building">
    Create subaccounts for different departments (Sales, Support, Operations). Each department gets its own trunks and phone numbers.
  </Card>

  <Card title="Reseller Model" icon="handshake">
    Create subaccounts for resellers who manage their own customers. Track usage and billing separately per subaccount.
  </Card>

  <Card title="Development/Staging" icon="code">
    Create subaccounts for dev, staging, and production environments. Test changes in isolation without affecting production.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.