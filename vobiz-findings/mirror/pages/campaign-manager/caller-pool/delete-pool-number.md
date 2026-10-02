> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Remove a caller pool number

> Remove a caller-ID number from a pool campaign. Disable the number instead if you want to keep it out of rotation but retain it in the pool.

```http theme={null}
DELETE https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pool/{number_id}
```

Removes the number from the pool.

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

<Warning>
  The pool can be edited only while the campaign is `draft` or `ready`. Add, update, and delete return `409` while it is `running`, `paused`, or `queued`.
</Warning>

## Example

```bash cURL theme={null}
curl -X DELETE \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pool/{number_id}" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

<Tip>
  To take a number out of rotation temporarily, set `is_active: false` with [Update a pool number](/docs/campaign-manager/caller-pool/update-pool-number) instead. That keeps the number and its usage counters in the pool.
</Tip>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.