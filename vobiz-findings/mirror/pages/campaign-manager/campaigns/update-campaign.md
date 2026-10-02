> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update a campaign

> Partially update a draft or ready campaign — concurrency, caller-ID settings, schedule, daily window, retries, and webhook URL.

```http theme={null}
PUT https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}
```

Every field is optional — only what you send changes.

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
  ID of the campaign, returned by [Create a campaign](/docs/campaign-manager/campaigns/create-campaign).
</ParamField>

<ParamField body="name" type="string">
  New campaign name. Maximum 100 characters.
</ParamField>

<ParamField body="max_concurrent" type="integer">
  Must stay within the account concurrency limit.
</ParamField>

<ParamField body="caller_id_strategy" type="string">
  `fixed`, `per_contact`, or `pool`.
</ParamField>

<ParamField body="fixed_caller_id" type="string">
  E.164 caller ID, required while the strategy is `fixed`.
</ParamField>

<ParamField body="scheduled_at" type="string">
  ISO 8601 timestamp for a scheduled launch.
</ParamField>

<ParamField body="clear_schedule" type="boolean">
  Set to `true` to remove an existing `scheduled_at` value.
</ParamField>

<ParamField body="window_enabled" type="boolean">
  Enables or disables the daily calling window.
</ParamField>

<ParamField body="retry_attempts" type="integer">
  Range `0`–`5`.
</ParamField>

<ParamField body="notify_url" type="string">
  Target for signed campaign and contact webhooks.
</ParamField>

## Example

```bash cURL theme={null}
curl -X PUT \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{ "max_concurrent": 25, "clear_schedule": true }'
```

<Warning>
  A campaign can be updated only while it is `draft` or `ready`. Editing a `running`, `paused`, `queued`, or `archived` campaign returns `409 Conflict`.
</Warning>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.