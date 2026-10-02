> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# List caller pool numbers

> List the caller-ID numbers in a pool campaign with per-number usage statistics and eligibility status.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pool
```

Returns every number in the pool with its usage counters and current eligibility.

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
  The pool campaign to inspect.
</ParamField>

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pool" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

## Response fields

Each object includes `is_active`, `total_calls`, `daily_calls`, and `pool_status`.

| Status | Meaning |
| - | - |
| `active` | Eligible for selection. |
| `at_limit` | Reached the lifetime cap. |
| `at_daily_limit` | Reached the daily cap. |
| `in_cooldown` | Within the configured cooldown. |
| `inactive` | Disabled with `is_active: false`. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.