> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Calling Guardrails: Control Outbound Call Timing and Rescheduling

> Restrict when your Bolna Voice AI agent makes outbound calls. Configure allowed calling hours, automatic rescheduling for off-hours calls, and bypass guardrails for urgent calls via API.

Calling guardrails let you restrict when your agent makes outbound calls. Calls outside the allowed window are automatically rescheduled.

<Frame caption="Call Tab showing Call Configuration and Outbound call timing restrictions">
  <img src="https://mintcdn.com/bolna-54a2d4fe/mQ_HSrxgFv467vUr/images/getting-started/agent-setup/call-tab-full.png?fit=max&auto=format&n=mQ_HSrxgFv467vUr&q=85&s=d60a60b32b6b46d22795ec944204735c" alt="Call Tab with Plivo telephony provider, Noise Cancellation, Voicemail Detection, Keypad Input DTMF, Auto Reschedule toggles, and Outbound call timing restrictions toggled on with 9 AM to 9 PM window" width="1480" height="944" data-path="images/getting-started/agent-setup/call-tab-full.png" />
</Frame>

***

## How It Works

<Steps>
  <Step title="Enable Restrictions">
    Toggle on **Outbound call timing restrictions** in the [Call Tab](/docs/agent-setup/call-tab). It is off by default.
  </Step>

  <Step title="Set the Allowed Time Window">
    Pick a start and end time (e.g., 9:00 AM to 9:00 PM).
  </Step>

  <Step title="Calls Are Validated Automatically">
    When a call is triggered, the system checks the current time in the **recipient's local timezone** (detected from their phone number).
  </Step>

  <Step title="Within Window: Call Goes Through">
    If the time falls inside the allowed window, the call is made immediately.
  </Step>

  <Step title="Outside Window: Call Is Rescheduled">
    If the time falls outside the window, the call status is set to `rescheduled` and it is automatically queued for the next allowed start time.
  </Step>
</Steps>

<Info>
  The time window is based on the **recipient's timezone**, not yours. A 9 AM start means 9 AM where the recipient is located.
</Info>

***

## Configure via API

You can also set calling guardrails through the API when creating or updating an agent. Use `call_start_hour` and `call_end_hour` in 24-hour format.

| Field             | Type           | Description                         |
| ----------------- | -------------- | ----------------------------------- |
| `call_start_hour` | integer (0-23) | Start of the allowed calling window |
| `call_end_hour`   | integer (0-23) | End of the allowed calling window   |

```bash theme={"system"}
curl --request POST \
  --url https://api.bolna.ai/v2/agent \
  --header 'Authorization: Bearer YOUR_API_TOKEN' \
  --header 'Content-Type: application/json' \
  --data '{
    "agent_config": {
      "agent_name": "Sales Agent",
      "agent_welcome_message": "Hello, how can I help you?",
      "calling_guardrails": {
        "call_start_hour": 9,
        "call_end_hour": 21
      },
      "tasks": [...]
    },
    "agent_prompts": {...}
  }'
```

<Note>
  Hours use 24-hour format: 0 = midnight, 9 = 9 AM, 17 = 5 PM, 21 = 9 PM. `call_end_hour` must be greater than or equal to `call_start_hour`.
</Note>

***

## Bypass Guardrails for Urgent Calls

Use the `bypass_call_guardrails` flag to skip time validation for a specific call. When set to `true`, the call goes through immediately regardless of the configured window.

```bash theme={"system"}
curl --request POST \
  --url https://api.bolna.ai/call \
  --header 'Authorization: Bearer YOUR_API_TOKEN' \
  --header 'Content-Type: application/json' \
  --data '{
    "agent_id": "3c90c3cc-0d44-4b50-8888-8dd25736052a",
    "recipient_phone_number": "+14155551234",
    "bypass_call_guardrails": true,
    "user_data": {...}
  }'
```

<CardGroup cols={2}>
  <Card title="Emergency Notifications" icon="bolt">
    Time-sensitive alerts that cannot wait
  </Card>

  <Card title="VIP / Priority Calls" icon="shield">
    High-priority calls that need immediate delivery
  </Card>
</CardGroup>

<Warning>
  Use the bypass flag responsibly. Calling outside allowed hours may violate local regulations or disturb recipients.
</Warning>

***

## Common Use Cases

<Accordion title="Business Hours Only (9 AM - 5 PM)">
  Restrict calls to standard business hours so your agent only reaches out during the workday.

  ```json theme={"system"}
  {
    "calling_guardrails": {
      "call_start_hour": 9,
      "call_end_hour": 17
    }
  }
  ```

  Calls triggered outside this window are automatically rescheduled to 9 AM the next day in the recipient's timezone.
</Accordion>

<Accordion title="Extended Hours for Sales (9 AM - 9 PM)">
  Sales teams often reach prospects in the evening. Extend the window while still avoiding late-night calls.

  ```json theme={"system"}
  {
    "calling_guardrails": {
      "call_start_hour": 9,
      "call_end_hour": 21
    }
  }
  ```
</Accordion>

<Accordion title="Bypass for Testing in Development">
  During development, use the bypass flag to test call flows at any time without waiting for the allowed window.

  ```json theme={"system"}
  {
    "bypass_call_guardrails": true
  }
  ```
</Accordion>

***

## In-Call Reschedule Validation

When a recipient asks to reschedule during a call (e.g., "call me back at 10 PM"), the system validates the requested time against the allowed window before scheduling it.

**Validation priority:**

| Priority | Source                        | Description                                                                      |
| -------- | ----------------------------- | -------------------------------------------------------------------------------- |
| 1        | **Calling guardrails config** | `call_start_hour` / `call_end_hour` always takes precedence                      |
| 2        | **Agent prompt**              | If no guardrails are set, the LLM reads time restrictions from the system prompt |
| 3        | **Default window**            | Falls back to 9 AM to 9 PM if neither is configured                              |

If the requested time falls outside the allowed window, the reschedule request is rejected entirely. The system does not adjust it to the nearest boundary.

<Note>
  Keep your agent prompt and guardrails config consistent. If the prompt says "call between 10 AM and 6 PM" but guardrails are set to 9 AM to 9 PM, the stricter guardrails config takes priority.
</Note>

***

## Calling Regulations to Know

Many countries enforce strict rules on when businesses can make outbound calls. Calling guardrails help you stay compliant.

| Region             | Regulation                                   | Allowed Hours                                                                                         |
| ------------------ | -------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| **India**          | TRAI (Telecom Regulatory Authority of India) | 9:00 AM to 9:00 PM IST. No calls on national Do Not Disturb (DND) registered numbers without consent. |
| **United States**  | TCPA (Telephone Consumer Protection Act)     | 8:00 AM to 9:00 PM in the recipient's local time. Prior express consent required for automated calls. |
| **European Union** | ePrivacy Directive                           | Varies by member state. Most restrict unsolicited calls to business hours and require prior consent.  |

<Warning>
  This is a general reference, not legal advice. Always verify the specific regulations that apply to your use case and region before making outbound calls.
</Warning>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Call Tab" icon="phone" href="/docs/agent-setup/call-tab">
    Configure telephony, noise, and call settings
  </Card>

  <Card title="Batch Calling" icon="list-check" href="/docs/guides/outbound/batch-calling">
    Schedule calls in bulk with CSV uploads
  </Card>

  <Card title="Auto Retry" icon="clock" href="/docs/guides/outbound/auto-retry">
    Automatically retry unanswered calls
  </Card>

  <Card title="Make Calls API" icon="code" href="/docs/api-reference/calls/make">
    Full API reference for the call endpoint
  </Card>
</CardGroup>
