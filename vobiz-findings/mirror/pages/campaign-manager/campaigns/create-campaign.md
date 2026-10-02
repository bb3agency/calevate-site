> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create a campaign

> Create an outbound voice campaign with concurrency, timezone, caller-ID strategy, scheduling, daily calling window, and retry policy.

```http theme={null}
POST https://api.vobiz.ai/api/v1/account/{account_id}/campaigns
```

A campaign links an agent to a contact list and defines concurrency, caller-ID selection, scheduling, daily windows, and retry behaviour. New campaigns start in `draft`.

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

<ParamField body="name" type="string" required>
  Campaign name. Maximum 100 characters.
</ParamField>

<ParamField body="agent_id" type="string" required>
  ID of an existing [agent](/docs/campaign-manager/agents/create-agent).
</ParamField>

<ParamField body="max_concurrent" type="integer" required>
  Maximum simultaneous calls. At least `1`, and no higher than the account concurrency limit.
</ParamField>

<ParamField body="timezone" type="string" required>
  IANA timezone such as `Asia/Kolkata`. Governs the daily window and daily pool limits.
</ParamField>

<ParamField body="caller_id_strategy" type="string" required>
  `fixed`, `per_contact`, or `pool`.
</ParamField>

<ParamField body="fixed_caller_id" type="string">
  Required when the strategy is `fixed`. E.164 format.
</ParamField>

<ParamField body="cps" type="integer">
  Retained for backward compatibility. Values below `1` normalise to `1`. CPS does not gate campaign capacity — use `max_concurrent`.
</ParamField>

<ParamField body="scheduled_at" type="string">
  ISO 8601 timestamp for a scheduler-based launch instead of an immediate start.
</ParamField>

<ParamField body="window_enabled" type="boolean" default="false">
  Enables the daily calling window.
</ParamField>

<ParamField body="window_start_time" type="string">
  Required when the window is enabled. `HH:mm` in the campaign timezone.
</ParamField>

<ParamField body="window_end_time" type="string">
  Required when the window is enabled. Must differ from the start time.
</ParamField>

<ParamField body="retry_attempts" type="integer" default="0">
  Retries after the initial attempt. Range `0`–`5`.
</ParamField>

<ParamField body="retry_delays" type="array">
  Delay in minutes before each retry, for example `[60, 240]`.
</ParamField>

<ParamField body="retry_window_days" type="integer" default="7">
  Maximum number of days retries may span.
</ParamField>

<ParamField body="notify_url" type="string">
  Target for signed campaign and contact [webhooks](/docs/campaign-manager/webhooks).
</ParamField>

## Example

```bash cURL theme={null}
curl -X POST \
  "https://api.vobiz.ai/api/v1/account/{account_id}/campaigns" \
  -H "X-Auth-ID: {account_id}" \
  -H "X-Auth-Token: {auth_token}" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Q1 Appointment Reminders",
    "agent_id": "{agent_id}",
    "max_concurrent": 10,
    "timezone": "Asia/Kolkata",
    "caller_id_strategy": "fixed",
    "fixed_caller_id": "+919876543210",
    "window_enabled": true,
    "window_start_time": "09:00",
    "window_end_time": "18:00",
    "retry_attempts": 2,
    "retry_delays": [60, 240],
    "retry_window_days": 7,
    "notify_url": "https://example.com/campaign-webhooks"
  }'
```

The response is `201` with a `draft` campaign. [Upload contacts](/docs/campaign-manager/contacts/upload-contacts) to move it to `ready`.

## Caller-ID strategies

<Tabs>
  <Tab title="Fixed">
    Set `caller_id_strategy` to `fixed` and supply `fixed_caller_id`. Every attempt uses the same number.
  </Tab>

  <Tab title="Per contact">
    Set the strategy to `per_contact`. Every CSV row must contain a `from` value — the upload fails if the column is missing.
  </Tab>

  <Tab title="Pool">
    Set the strategy to `pool`, then [add numbers](/docs/campaign-manager/caller-pool/add-pool-numbers) before launch.

    Pool campaigns also accept `pool_rotation_strategy` (`round_robin`, `least_used`, or `random`), `pool_max_calls_per_number`, `pool_max_calls_per_day`, and `pool_cooldown_seconds`.
  </Tab>
</Tabs>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.