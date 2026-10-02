> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Resume a campaign

> Return a paused campaign to running and immediately re-enqueue its pending contacts.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/resume
```

Returns the campaign to `running` and re-enqueues pending contacts straight away. Allowed only from `paused`.

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
  The campaign to resume. It must be `paused`.
</ParamField>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/resume" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

Sends the `campaign.resumed` webhook when `notify_url` is configured.

<Note>
  Some pause reasons clear on their own. A `window_closed` pause resumes at the next open window, and `caller_pool_daily_limit_reached` resumes at midnight in the campaign timezone. Reasons such as `manual_pause`, `caller_pool_exhausted`, and `balance_insufficient` need this endpoint after you fix the underlying cause.
</Note>

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