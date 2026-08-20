> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Limits & Quotas

> Concurrency, rate limits, batch size, CSV limits, and payload caps for the Bolna API.

## Concurrency

Concurrency is the number of simultaneous active calls your account can run. Check your current concurrency in `GET /user/me`:

```json theme={"system"}
{
  "concurrency": { "max": 10, "current": 3 }
}
```

To increase your concurrency limit, contact [support@bolna.ai](mailto:support@bolna.ai) or upgrade your plan. See [Outbound Calling Concurrency](/docs/pricing/outbound-calling-concurrency) for scheduling behavior when the limit is reached.

## Rate limits

The API is rate-limited per account. If you exceed the limit you receive HTTP `429`. Apply exponential backoff and retry:

```python theme={"system"}
import time

def call_with_backoff(fn, max_retries=5):
    for i in range(max_retries):
        status, data = fn()
        if status != 429:
            return status, data
        time.sleep(2 ** i)
    raise Exception("Rate limit exceeded after retries")
```

## Batch limits

| Limit                            | Value                                                              |
| -------------------------------- | ------------------------------------------------------------------ |
| Minimum `scheduled_at` lead time | 2 minutes                                                          |
| Start rounding                   | Rounds up to next 10-minute mark                                   |
| `scheduled_at` format            | ISO 8601 with numeric offset (e.g. `+00:00`) — `Z` suffix rejected |
| Maximum CSV rows                 | Contact support for high-volume batches                            |

## CSV requirements

| Field                   | Rule                                                   |
| ----------------------- | ------------------------------------------------------ |
| `contact_number` column | **Required** — E.164 format (e.g. `+919876543210`)     |
| Additional columns      | Optional — become `{variable}` substitutions in prompt |
| File type               | CSV (`text/csv`)                                       |
| Encoding                | UTF-8                                                  |

## Webhook delivery

| Property          | Value                                                                                 |
| ----------------- | ------------------------------------------------------------------------------------- |
| Source IPs        | `13.203.39.153`, `13.126.9.249`, `13.202.133.53` — whitelist all three on your server |
| Events per call   | Multiple (status changes: queued → in-progress → call-disconnected → completed)       |
| Expected response | HTTP `200` — return fast; Bolna retries on non-2xx or timeout                         |

## Wallet & balance

Calls require wallet credits. A `balance-low` execution status means the call was not placed due to insufficient balance. Top up from the [dashboard](https://platform.bolna.ai) or contact support for invoice billing.
