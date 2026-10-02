> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Voice Campaign Manager API

> Create and operate outbound voice campaigns with reusable agents, CSV contact lists, caller-ID pools, retries, scheduling, capacity controls, and signed webhooks.

The Voice Campaign Manager API lets you create outbound calling campaigns and operate their full lifecycle. You define a reusable agent, configure campaign capacity and caller ID behavior, upload contacts, then start or schedule the campaign.

<Info>
  All requests go through the Vobiz API gateway at `https://api.vobiz.ai` and are scoped to an account under `/api/v1/account/{account_id}/`. Examples use `{account_id}` and `{auth_token}` placeholders. Keep credentials on your server and never expose them in client-side code.
</Info>

## Workflow

<Steps>
  <Step title="Create an agent">
    Save the returned agent `id`. The agent defines the answer URL, optional hangup URL, request methods, and static SIP headers.
  </Step>

  <Step title="Create a campaign">
    Select the agent, concurrency, timezone, caller-ID strategy, retry policy, and optional schedule or daily calling window.
  </Step>

  <Step title="Configure caller IDs">
    For a pool campaign, add at least one number. Fixed campaigns use `fixed_caller_id`. Per-contact campaigns read the caller ID from each CSV row.
  </Step>

  <Step title="Upload contacts">
    Upload a CSV with a `to` column. A valid upload moves the campaign from `draft` to `ready`.
  </Step>

  <Step title="Launch and monitor">
    Call the start endpoint for an immediate launch, or set `scheduled_at`. Monitor campaign health, contacts, attempts, and account capacity.
  </Step>

  <Step title="Export outcomes">
    Download campaign results or query CDRs with `campaign_id` for billing and call-quality analysis.
  </Step>
</Steps>

## Base URL

```text theme={null}
https://api.vobiz.ai
```

<Warning>
  **Always call the gateway.** The campaign service itself sits behind an internal load balancer on private addresses and is not reachable from the internet, so a service-specific hostname will not resolve. Every example on these pages uses `api.vobiz.ai`.
</Warning>

Authenticate with `X-Auth-ID` and `X-Auth-Token`, or with an account-service JWT through the gateway. See [Authentication](/docs/campaign-manager/authentication).

## Endpoint index

Every path below is prefixed with `/api/v1/account/{account_id}`. Each page has a live playground.

**Agents**

| Method | Path | Reference |
| - | - | - |
| `POST` | `/campaign/agents` | [Create an agent](/docs/campaign-manager/agents/create-agent) |
| `GET` | `/campaign/agents` | [List agents](/docs/campaign-manager/agents/list-agents) |
| `GET` | `/campaign/agents/{agent_id}` | [Retrieve an agent](/docs/campaign-manager/agents/retrieve-agent) |
| `PUT` | `/campaign/agents/{agent_id}` | [Update an agent](/docs/campaign-manager/agents/update-agent) |
| `DELETE` | `/campaign/agents/{agent_id}` | [Delete an agent](/docs/campaign-manager/agents/delete-agent) |

**Campaigns**

| Method | Path | Reference |
| - | - | - |
| `POST` | `/campaigns` | [Create a campaign](/docs/campaign-manager/campaigns/create-campaign) |
| `GET` | `/campaigns` | [List campaigns](/docs/campaign-manager/campaigns/list-campaigns) |
| `GET` | `/campaigns/{campaign_id}` | [Retrieve a campaign](/docs/campaign-manager/campaigns/retrieve-campaign) |
| `PUT` | `/campaigns/{campaign_id}` | [Update a campaign](/docs/campaign-manager/campaigns/update-campaign) |

**Lifecycle controls**

| Method | Path | Reference |
| - | - | - |
| `POST` | `/campaigns/{campaign_id}/start` | [Start](/docs/campaign-manager/controls/start-campaign) |
| `POST` | `/campaigns/{campaign_id}/pause` | [Pause](/docs/campaign-manager/controls/pause-campaign) |
| `POST` | `/campaigns/{campaign_id}/resume` | [Resume](/docs/campaign-manager/controls/resume-campaign) |
| `POST` | `/campaigns/{campaign_id}/cancel` | [Cancel](/docs/campaign-manager/controls/cancel-campaign) |
| `POST` | `/campaigns/{campaign_id}/archive` | [Archive](/docs/campaign-manager/controls/archive-campaign) |

**Contacts, upload, and results**

| Method | Path | Reference |
| - | - | - |
| `POST` | `/campaigns/{campaign_id}/upload` | [Upload contacts](/docs/campaign-manager/contacts/upload-contacts) |
| `GET` | `/campaigns/{campaign_id}/contacts` | [List contacts](/docs/campaign-manager/contacts/list-contacts) |
| `GET` | `/campaigns/{campaign_id}/calls` | [List call attempts](/docs/campaign-manager/contacts/list-calls) |
| `GET` | `/campaigns/{campaign_id}/results` | [Download results](/docs/campaign-manager/contacts/download-results) |

**Caller pool**

| Method | Path | Reference |
| - | - | - |
| `POST` | `/campaigns/{campaign_id}/pool` | [Add pool numbers](/docs/campaign-manager/caller-pool/add-pool-numbers) |
| `GET` | `/campaigns/{campaign_id}/pool` | [List pool numbers](/docs/campaign-manager/caller-pool/list-pool-numbers) |
| `PUT` | `/campaigns/{campaign_id}/pool/{number_id}` | [Update pool number](/docs/campaign-manager/caller-pool/update-pool-number) |
| `DELETE` | `/campaigns/{campaign_id}/pool/{number_id}` | [Remove pool number](/docs/campaign-manager/caller-pool/delete-pool-number) |

**Capacity and lookup**

| Method | Path | Reference |
| - | - | - |
| `GET` | `/capacity` | [Account capacity](/docs/campaign-manager/capacity/account-capacity) |
| `GET` | `/campaigns/{campaign_id}/call-lookup/{call_uuid}` | [Call lookup](/docs/campaign-manager/capacity/call-lookup) |

That is **24 account-scoped endpoints**. A `GET /status/` liveness check is also exposed, unauthenticated and unprefixed. Service-to-service routes under `/internal/*` are covered in [Authentication](/docs/campaign-manager/authentication) and are not reachable through the gateway.

## Resource map

<CardGroup cols={2}>
  <Card title="Authentication" icon="key" href="/docs/campaign-manager/authentication">
    Configure customer and internal request headers.
  </Card>

  <Card title="Agents" icon="user-gear" href="/docs/campaign-manager/agents/create-agent">
    Manage reusable answer and hangup webhook configurations.
  </Card>

  <Card title="Campaigns" icon="bullhorn" href="/docs/campaign-manager/campaigns/create-campaign">
    Create, list, retrieve, and update outbound campaigns.
  </Card>

  <Card title="Campaign controls" icon="sliders" href="/docs/campaign-manager/controls/start-campaign">
    Start, pause, resume, cancel, and archive campaigns.
  </Card>

  <Card title="Contacts and results" icon="address-book" href="/docs/campaign-manager/contacts/upload-contacts">
    Upload CSV contacts, browse contacts and attempts, and export results.
  </Card>

  <Card title="Caller-ID pools" icon="phone" href="/docs/campaign-manager/caller-pool/add-pool-numbers">
    Add numbers and manage rotation limits.
  </Card>

  <Card title="Capacity and monitoring" icon="gauge-high" href="/docs/campaign-manager/capacity/account-capacity">
    Inspect account capacity and campaign health.
  </Card>

  <Card title="Webhook events" icon="webhook" href="/docs/campaign-manager/webhooks">
    Verify signed campaign and contact events.
  </Card>
</CardGroup>

## Lifecycle

```text theme={null}
draft ──upload──▶ ready ──start/schedule──▶ running ──▶ completed
                     │                       │  ▲
                     │                       ▼  │
                     │                     paused
                     │                       │
                     └───────────────────────┴──▶ cancelled

non-running campaign ──archive──▶ archived
```

`queued` can appear while launch work is being prepared. Some mutation endpoints reject both `queued` and active states.

## Common status codes

| Code | Meaning |
| - | - |
| `200` | Request succeeded. |
| `201` | Resource created. |
| `400` | Request data is invalid. |
| `401` | Authentication failed. Check both headers and account ownership. |
| `404` | The resource does not exist for the authenticated account. |
| `409` | The requested transition or edit is not allowed in the current state. |
| `502` | An upstream platform dependency is unavailable. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.