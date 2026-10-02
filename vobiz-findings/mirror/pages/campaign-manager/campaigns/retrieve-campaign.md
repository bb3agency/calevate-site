> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retrieve a campaign

> Fetch a single campaign with its status, computed health, outcome counters, caller-ID configuration, schedule, and pause reason.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}
```

Returns status, outcome counters, capacity settings, caller-ID strategy, schedule, daily window, pause reason, webhook URL, and timestamps.

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

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns/{campaign_id}" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

## Computed health

For a running campaign, `health` is derived from recent dial activity.

| Value | Meaning |
| - | - |
| `active` | Calls are being placed. |
| `idle` | Running but not currently dialling — for example while account capacity is saturated. |
| `stalled` | No recent dial beyond the watchdog threshold. |
| `not_started` | No dial has occurred yet. |

See [Capacity and monitoring](/docs/campaign-manager/capacity/account-capacity) for the pause reasons that can accompany a `paused` status.


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.