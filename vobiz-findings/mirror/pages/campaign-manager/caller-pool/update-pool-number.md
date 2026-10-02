> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Update a caller pool number

> Rename a pool number or disable it so it is excluded from caller-ID rotation without losing its call history.

```http theme={null}
PUT https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pool/{number_id}
```

Change a number's label or its active state.

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
  The pool campaign that owns the number.
</ParamField>

<ParamField path="number_id" type="string" required>
  ID of the pool number, returned by [Add pool numbers](/docs/campaign-manager/caller-pool/add-pool-numbers).
</ParamField>

<ParamField body="label" type="string">
  Human-readable label, maximum 100 characters.
</ParamField>

<ParamField body="is_active" type="boolean">
  Set to `false` to exclude the number from future selection while keeping its history.
</ParamField>

<Warning>
  The pool can be edited only while the campaign is `draft` or `ready`. Add, update, and delete return `409` while it is `running`, `paused`, or `queued`.
</Warning>

## Example

```bash cURL theme={null}
curl -X PUT \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pool/{number_id}" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "label": "Primary DID",
    "is_active": false
  }'
```

Disabling excludes the number from future selection without removing its call history, so its `total_calls` and `daily_calls` counters remain readable through [List pool numbers](/docs/campaign-manager/caller-pool/list-pool-numbers).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.