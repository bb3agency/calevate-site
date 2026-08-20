> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Errors & Status Codes

> HTTP status codes, error response shapes, execution status enums, and batch status enums for the Bolna API.

## HTTP status codes

| Code  | Meaning               | When you see it                                                                                        |
| ----- | --------------------- | ------------------------------------------------------------------------------------------------------ |
| `200` | OK                    | Successful GET / action (stop, schedule, etc.)                                                         |
| `201` | Created               | `POST /v2/agent`, `POST /batches` — resource created                                                   |
| `400` | Bad Request           | Invalid or missing parameter — check `message` in the response body                                    |
| `401` | Unauthorized          | Missing or invalid API key — add `Authorization: Bearer <key>`                                         |
| `403` | Forbidden             | Valid key but insufficient permissions                                                                 |
| `404` | Not Found             | Resource ID doesn't exist or belongs to another account                                                |
| `429` | Too Many Requests     | Rate limit hit — back off and retry with exponential backoff                                           |
| `500` | Internal Server Error | Unexpected server error — also returned when `scheduled_at` uses the `Z` suffix (use `+00:00` instead) |

## Error response shape

All 4xx/5xx responses return JSON:

```json theme={"system"}
{
  "error": 1001,
  "message": "agent_id is required"
}
```

The `error` integer is an internal code; `message` is human-readable. The `message` field is the most useful for debugging.

## Execution status enum

Returned in `GET /executions/{id}` and webhook payloads as the `status` field.

| Status              | Type              | Description                                                                                                                 |
| ------------------- | ----------------- | --------------------------------------------------------------------------------------------------------------------------- |
| `scheduled`         | Intermediate      | Call is scheduled for a future time                                                                                         |
| `prepared`          | Intermediate      | Execution record created and validated (recipient number, from/to number assigned) but not yet handed off to the dial queue |
| `queued`            | Intermediate      | Call accepted and waiting to dial                                                                                           |
| `rescheduled`       | Intermediate      | Call was rescheduled (e.g. due to guardrails)                                                                               |
| `initiated`         | Intermediate      | Dialing has started                                                                                                         |
| `ringing`           | Intermediate      | Recipient's phone is ringing                                                                                                |
| `in-progress`       | Intermediate      | Call answered, conversation active                                                                                          |
| `call-disconnected` | **Soft terminal** | Line dropped — data still finalizing; `completed` follows                                                                   |
| **`completed`**     | **Terminal ✓**    | Call finished; all fields populated                                                                                         |
| `no-answer`         | Terminal          | Recipient didn't pick up                                                                                                    |
| `busy`              | Terminal          | Line was busy                                                                                                               |
| `failed`            | Terminal          | Telephony provider error                                                                                                    |
| `canceled`          | Terminal          | Call canceled before answer                                                                                                 |
| `stopped`           | Terminal          | Manually stopped via API                                                                                                    |
| `error`             | Terminal          | Internal error                                                                                                              |
| `balance-low`       | Terminal          | Insufficient wallet balance to place call                                                                                   |

<Warning>
  **`call-disconnected` is not the final state.** `conversation_duration`, `total_cost`, `recording_url`, and `extracted_data` are `null` or `0` at this point. Wait for **`completed`** (or any other terminal status above) before reading those fields.
</Warning>

### Polling pattern

```python theme={"system"}
TERMINAL = {"completed","no-answer","busy","failed","canceled","stopped","error","balance-low"}

while True:
    data = get_execution(execution_id)
    if data["status"] in TERMINAL:
        break   # safe to read all fields now
    time.sleep(5)
```

## Batch status enum

Returned by `GET /batches/{batch_id}` as the `status` field.

| Status      | Description                                                                            |
| ----------- | -------------------------------------------------------------------------------------- |
| `created`   | Batch created, not yet scheduled                                                       |
| `processed` | CSV parsed and per-call records generated; batch is ready to run (no calls dialed yet) |
| `scheduled` | Scheduled and waiting for start time                                                   |
| `running`   | Calls are actively being placed                                                        |
| `completed` | All calls finished                                                                     |
| `stopped`   | Manually stopped                                                                       |
| `failed`    | Error prevented execution                                                              |

## Per-call status in a batch

Each execution inside `GET /batches/{batch_id}/executions` has an individual `status` from the execution enum above. The batch's `execution_status` field gives a summary count: `{ "completed": 5, "no-answer": 2, "running": 3 }`.

## Scheduling errors

| Scenario                          | HTTP  | Message                                                    |
| --------------------------------- | ----- | ---------------------------------------------------------- |
| `scheduled_at` uses `Z` suffix    | `500` | Internal server error                                      |
| `scheduled_at` \< 2 minutes ahead | `400` | "Scheduled time should be atleast 2 minutes in the future" |
| Invalid ISO 8601 format           | `400` | Parsing error                                              |

**Fix:** always use a numeric offset: `2026-06-23T18:30:00+00:00`.
