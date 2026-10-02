> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Cancel a campaign

> Permanently stop a running or paused campaign. Remaining contacts are never dialled and the campaign cannot be restarted.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/cancel
```

Permanently stops remaining work. Allowed from `running` or `paused`.

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
  The campaign to cancel. It must be `running` or `paused`.
</ParamField>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/cancel" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

Sends the `campaign.cancelled` webhook when `notify_url` is configured. Contacts, CDRs, and statistics are preserved — you can still [download results](/docs/campaign-manager/contacts/download-results).

<Warning>
  **Cancellation is irreversible.** No further contacts are dialled and the campaign cannot be restarted. Verify the account and campaign ID before sending the request.
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