> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Archive a campaign

> Soft-delete a non-running campaign to remove it from active lists while preserving its contacts, CDRs, and statistics.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/archive
```

Removes the campaign from active lists without deleting its data. Allowed from any non-running, non-archived state.

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
  The campaign to archive. It must not be `running`.
</ParamField>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/archive" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

Archived campaigns remain readable through [List campaigns](/docs/campaign-manager/campaigns/list-campaigns) with `archived=true`, and their contacts, CDRs, and statistics stay intact.

<Warning>
  [Cancel](/docs/campaign-manager/controls/cancel-campaign) a running campaign before archiving it. Archiving a running campaign, or one that is already archived, returns `409`.
</Warning>

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