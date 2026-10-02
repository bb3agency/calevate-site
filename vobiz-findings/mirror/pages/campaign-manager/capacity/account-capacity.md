> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Get account capacity

> Inspect live account concurrency, available capacity, utilisation, and the running campaigns consuming it.

```http theme={null}
GET https://api.vobiz.ai/api/v1/account/{account_id}/capacity
```

Call this before and during a campaign to understand how many calls can run concurrently.

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

## Example

```bash cURL theme={null}
curl "https://api.vobiz.ai/api/v1/account/{account_id}/capacity" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}"
```

## Response fields

| Field | Description |
| - | - |
| `concurrent_calls` | Active calls across the account. |
| `max_concurrent` | Account concurrency limit. |
| `concurrent_free` | Capacity available for new calls. |
| `utilization_pct` | Current utilisation percentage. |
| `running_campaigns` | Summaries of the campaigns consuming capacity, with running and queued breakdown. |

The endpoint returns `502` when the upstream platform concurrency service is unavailable.

## Capacity behaviour

A campaign's `max_concurrent` cannot exceed the account concurrency limit. Capacity is enforced at dial time: a saturated account does not fail the campaign — it stays `running` and waits for a slot.

<Note>
  The `cps` field remains for backward compatibility but does not gate campaign capacity. Use live concurrency and `max_concurrent` when reasoning about throughput.
</Note>

## Health and automatic pauses

A running campaign reports `active`, `idle`, `stalled`, or `not_started` health through [Retrieve a campaign](/docs/campaign-manager/campaigns/retrieve-campaign). Operational pause reasons are:

| Reason | Clears |
| - | - |
| `manual_pause` | Manual [resume](/docs/campaign-manager/controls/resume-campaign) |
| `window_closed` | Automatically, at the next open window |
| `caller_pool_exhausted` | Manual resume after adding pool capacity |
| `caller_pool_daily_limit_reached` | Automatically, at midnight in the campaign timezone |
| `account_inactive` | Manual resume once the account is reactivated |
| `stalled` | Manual resume |
| `consecutive_failures` | Manual resume after fixing the failure cause |
| `balance_insufficient` | Manual resume after topping up |

## Related monitoring endpoints

| Endpoint | Use |
| - | - |
| [`GET /campaigns/{campaign_id}`](/docs/campaign-manager/campaigns/retrieve-campaign) | Status, computed health, counters, and pause reason. |
| [`GET /campaigns/{campaign_id}/contacts`](/docs/campaign-manager/contacts/list-contacts) | Contact state with `status` and `search` filters. |
| [`GET /campaigns/{campaign_id}/calls`](/docs/campaign-manager/contacts/list-calls) | Every attempt, including attempts with no matching CDR. |
| [`GET /campaigns/{campaign_id}/results`](/docs/campaign-manager/contacts/download-results) | Current or final contact outcomes as CSV. |


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.