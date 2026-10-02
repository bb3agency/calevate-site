> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Pause a campaign

> Pause a running campaign. New dials stop, in-flight calls finish, and the campaign requires an explicit resume.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pause
```

Stops new dials. Calls already in flight complete normally. Allowed only from `running`.

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
  The campaign to pause. It must be `running`.
</ParamField>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pause" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

A manual pause sets `paused_reason` to `manual_pause` and sends the `campaign.paused` webhook when `notify_url` is configured. It requires an explicit [resume](/docs/campaign-manager/controls/resume-campaign) — it will not restart on its own.

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