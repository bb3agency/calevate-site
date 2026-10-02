> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Start a campaign

> Launch a ready campaign immediately. Starting clears any scheduled_at value and begins dialling within the account concurrency limit.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/start
```

Starts dialling immediately and clears any `scheduled_at` value. Allowed only from `ready`.

<Info>
  **Authentication required**

  * `X-Auth-ID` — your Vobiz account ID
  * `X-Auth-Token` — your Vobiz auth token
</Info>

<ParamField path="account_id" type="string" required>
  Your Vobiz account ID. Use the same value in `X-Auth-ID`.
</ParamField>

<ParamField header="X-Auth-ID" type="string" required>
  Your Vobiz account ID, for example `MA_XXXXXXXX`.
</ParamField>

<ParamField path="campaign_id" type="string" required>
  The campaign to start. It must be in `ready` state.
</ParamField>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/start" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

Account concurrency is enforced as each call is dialled. If the account is saturated the campaign stays `running` but idle until capacity frees up — check [account capacity](/docs/campaign-manager/capacity/account-capacity) first.

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

Invalid transitions return `409 Conflict`. Control endpoints take no request body.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.