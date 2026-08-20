> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Auto-Retry for Failed Calls

> Automatically retry calls that fail due to no-answer, busy signals, or errors to improve contact rates.

## What is Auto-Retry?

Auto-retry automatically reschedules calls that fail to connect. When a call ends with statuses like `no-answer` or `busy`, Bolna retries the call after a configurable delay, improving your overall contact rates without manual intervention.

***

## How to Enable Auto-Retry

Add the `retry_config` object when making a call via the [Make Call API](/docs/api-reference/calls/make) or [Create Batch API](/docs/api-reference/batches/create).

<CodeGroup>
  ```bash Single Call theme={"system"}
  curl -X POST 'https://api.bolna.ai/call' \
  -H 'Authorization: Bearer <api_key>' \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_id": "your-agent-id",
    "recipient_phone_number": "+1234567890",
    "retry_config": {
      "enabled": true,
      "max_retries": 3,
      "retry_on_statuses": ["no-answer", "busy", "failed"],
      "retry_intervals_minutes": [30, 60, 120]
    }
  }'
  ```

  ```bash Batch Call theme={"system"}
  curl -X POST 'https://api.bolna.ai/batches' \
  -H 'Authorization: Bearer <api_key>' \
  -F 'agent_id=your-agent-id' \
  -F 'file=@contacts.csv' \
  -F 'retry_config={"enabled":true,"max_retries":2,"retry_intervals_minutes":[15,30]}'
  ```
</CodeGroup>

***

## Configuration Options

| Parameter                 | Type    | Default                           | Description                                  |
| ------------------------- | ------- | --------------------------------- | -------------------------------------------- |
| `enabled`                 | boolean | `false`                           | Enable auto-retry                            |
| `max_retries`             | integer | `3`                               | Maximum retry attempts (1–3)                 |
| `retry_on_statuses`       | array   | `["no-answer", "busy", "failed"]` | Statuses that trigger a retry                |
| `retry_on_voicemail`      | boolean | `false`                           | Retry if voicemail is detected               |
| `retry_intervals_minutes` | array   | `[30, 60, 120]`                   | Delay (in minutes) before each retry attempt |

### Supported Retry Statuses

| Status      | Description                    |
| ----------- | ------------------------------ |
| `no-answer` | Call rang but was not answered |
| `busy`      | Line was busy                  |
| `failed`    | Call failed to connect         |
| `error`     | Technical error occurred       |

***

## Monitoring Retries via Webhook

When auto-retry is configured, your webhook receives retry information with each status update:

```json theme={"system"}
{
  "id": "execution-id",
  "status": "scheduled",
  "retry_count": 1,
  "retry_config": {
    "enabled": true,
    "max_retries": 3
  },
  "retry_history": [
    {
      "attempt": 1,
      "status": "no-answer",
      "at": "2026-01-26T10:00:00Z"
    }
  ],
  "scheduled_at": "2026-01-26T10:30:00Z"
}
```

***

## Best Practices

<CardGroup cols={2}>
  <Card title="Conservative Intervals" icon="clock">
    Start with 30+ minute intervals to avoid annoying contacts with rapid retries
  </Card>

  <Card title="Skip Voicemail Retries" icon="voicemail">
    Keep `retry_on_voicemail: false` (default) to avoid repeated voicemail deposits
  </Card>

  <Card title="Monitor Retry Counts" icon="chart-line">
    Track `retry_count` in webhooks to measure retry effectiveness over time
  </Card>

  <Card title="Match Urgency" icon="gauge-high">
    Use 1–2 retries for time-sensitive calls, 3 for lead outreach campaigns
  </Card>
</CardGroup>

***

## Related Features

<CardGroup cols={3}>
  <Card title="Batch Calling" icon="file-spreadsheet" href="/docs/guides/outbound/batch-calling">
    Run campaigns with thousands of contacts
  </Card>

  <Card title="Webhooks" icon="webhook" href="/docs/guides/post-call/polling-call-status-webhooks">
    Get real-time call status updates
  </Card>

  <Card title="Call Details" icon="list-check" href="/docs/agent-setup/call-history">
    View execution history and outcomes
  </Card>
</CardGroup>
