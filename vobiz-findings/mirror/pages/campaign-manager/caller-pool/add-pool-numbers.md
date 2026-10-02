> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Add caller pool numbers

> Add one or more caller-ID numbers to a pool campaign so calls rotate across them under the campaign's rotation strategy and limits.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pool
```

Use a caller pool when `caller_id_strategy` is `pool`. The pool rotates calls across eligible numbers and applies per-number limits.

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
  The pool campaign to add numbers to.
</ParamField>

<ParamField body="numbers" type="array" required>
  Array of number objects. Each requires `from_number` in E.164 format; `label` is optional with a maximum of 100 characters.
</ParamField>

<Warning>
  The pool can be edited only while the campaign is `draft` or `ready`. Add, update, and delete return `409` while it is `running`, `paused`, or `queued`.
</Warning>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}/pool" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "numbers": [
      { "from_number": "+919000000001", "label": "DID-North-1" },
      { "from_number": "+919000000002", "label": "DID-North-2" }
    ]
  }'
```

## Response

```json 201 Created theme={null}
{
  "added": [
    {
      "id": "4b3890ea-e773-4cef-9442-58f644fddca7",
      "from_number": "+919000000001",
      "label": "DID-North-1",
      "total_calls": 0
    }
  ]
}
```

Save the returned `id` as `number_id` for [updates](/docs/campaign-manager/caller-pool/update-pool-number) or [deletion](/docs/campaign-manager/caller-pool/delete-pool-number).

## Rotation and limits

These fields are configured on the campaign, not on individual numbers:

| Field | Description |
| - | - |
| `pool_rotation_strategy` | `round_robin`, `least_used`, or `random`. |
| `pool_max_calls_per_number` | Lifetime cap per number. `null` means unlimited. |
| `pool_max_calls_per_day` | Daily cap per number. Resets at midnight in the campaign timezone. |
| `pool_cooldown_seconds` | Minimum time between consecutive calls from the same number. `0` disables it. |

When every number reaches its lifetime cap the campaign pauses with `caller_pool_exhausted` and needs a manual [resume](/docs/campaign-manager/controls/resume-campaign) once you add capacity. When every number reaches its daily cap it pauses with `caller_pool_daily_limit_reached` and resumes automatically at midnight.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.