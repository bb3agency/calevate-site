> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Transfer Live Calls to Human Agents with Bolna Voice AI

> Learn how to transfer live phone calls to human agents or custom endpoints using Bolna Voice AI. Enable seamless handoffs based on conversation context.

## What is Call Transfer?

Call transfer enables your Voice AI agent to route live calls to human agents or specific phone numbers based on conversation context. Essential for escalations, specialized support, or when human intervention is needed.

***

## Configuration Options

<Frame caption="Transfer Call Configuration Modal">
  <img src="https://mintcdn.com/bolna-54a2d4fe/zRZRzNcgm9P0_dMD/images/tool-calling/transfer-call-config.png?fit=max&auto=format&n=zRZRzNcgm9P0_dMD&q=85&s=c38f731c65ae233720511b870994d952" alt="Transfer call configuration showing Description prompt, phone number field, pre-tool message with multi-language support, and custom server URL option" width="865" height="1024" data-path="images/tool-calling/transfer-call-config.png" />
</Frame>

| Setting                      | Description                                                                                                                                                                           |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Description (Prompt)**     | Tell the LLM when to trigger the transfer. Be specific - e.g., *"Transfer when caller requests to speak with a human agent or sales team."*                                           |
| **Transfer to phone number** | Destination number in international format (e.g., `+19876543210`)                                                                                                                     |
| **Pre-tool message**         | What the agent says while transferring - e.g., *"Sure, I'll transfer the call for you. Please wait a moment."* Supports multiple languages.                                           |
| **Pre-call webhook**         | Optionally notify a URL of your choice *before* the transfer happens — useful for sending the transfer reason to your system in real time. See [Pre-call Webhook](#pre-call-webhook). |

<Tip>
  Add multiple languages for pre-tool messages using **+ Add** to support multilingual callers.
</Tip>

***

## Pre-call Webhook

The Transfer Call tool can fire an optional **pre-call webhook** — a notification sent to a URL of your choice *before* the call is transferred. A common use case is sending the transfer reason to your system so a human agent has context the moment the call connects.

<Info>
  The pre-call webhook is **fire-and-forget**. A slow or failing webhook endpoint never blocks or delays the transfer itself.
</Info>

Two optional fields control the webhook:

| Field                    | Purpose                                                                                                                                  |
| ------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------- |
| `pre_call_webhook_param` | The JSON body template to send, with `%(field)s` substitution. This is the on/off switch — if it is not set, no pre-call webhook fires.  |
| `pre_call_webhook_url`   | Where to send the webhook. If left blank, the agent-level [Webhook URL](/docs/guides/post-call/polling-call-status-webhooks) is used instead. |

### Available Substitution Fields

`pre_call_webhook_param` is a JSON template. You can reference the transfer tool's runtime arguments using the same `%(field)s` [substitution syntax](/docs/tool-calling/custom-function-calls#format-specifiers) used elsewhere. The Transfer Call tool exposes:

| Field                      | Description                                                    |
| -------------------------- | -------------------------------------------------------------- |
| `%(reason)s`               | Why the caller is being transferred, as determined by the LLM. |
| `%(summary)s`              | A short summary of the conversation so far.                    |
| `%(call_transfer_number)s` | The destination number the call is being transferred to.       |
| `%(call_sid)s`             | The telephony provider's call identifier.                      |

<Note>
  Any field that is not available at transfer time is sent as an empty string rather than failing the substitution.
</Note>

```json theme={"system"}
{
  "pre_call_webhook_url": "https://your-api.com/pre-transfer-hook",
  "pre_call_webhook_param": {
    "transfer_reason": "%(reason)s",
    "conversation_summary": "%(summary)s",
    "transferred_to": "%(call_transfer_number)s",
    "channel": "voice"
  }
}
```

Static values (like `"channel": "voice"` above) are passed through as-is; `%(field)s` placeholders are substituted with the transfer tool's runtime arguments.

### What Your Endpoint Receives

The webhook body is the **same execution record** you receive on the [post-call execution webhook](/docs/guides/post-call/polling-call-status-webhooks) (execution id, agent id, telephony details, status, etc.), merged with the fields from your `pre_call_webhook_param`:

```json theme={"system"}
{
  "id": "<execution_id>",
  "agent_id": "<agent_id>",
  "status": "in-progress",
  "telephony_data": { "...": "..." },
  "...": "...",

  "transfer_reason": "caller asked for billing support",
  "conversation_summary": "Caller could not resolve a billing issue with the agent.",
  "transferred_to": "+19876543210",
  "channel": "voice"
}
```

<Note>
  Because the call is still in progress when the pre-call webhook fires, fields that are only finalized at call end (transcript, cost, summary) won't be complete yet.
</Note>

### URL Resolution Rules

| `pre_call_webhook_param` | `pre_call_webhook_url` | Result                                                                                                |
| ------------------------ | ---------------------- | ----------------------------------------------------------------------------------------------------- |
| Set                      | Set                    | Webhook sent to the transfer tool's `pre_call_webhook_url`.                                           |
| Set                      | Not set                | Webhook sent to the **agent-level Webhook URL** (the same URL used for post-call execution webhooks). |
| Not set                  | Set or not set         | **No pre-call webhook fires.**                                                                        |

<Warning>
  **`pre_call_webhook_param` is the master switch.** If it is not set, no pre-call webhook fires — even if `pre_call_webhook_url` is configured. The agent's normal post-call webhook is unaffected.
</Warning>

<Warning>
  **Agent-level URL fallback:** when `pre_call_webhook_param` is set without a `pre_call_webhook_url`, the pre-call webhook is sent to your agent's configured [Webhook URL](/docs/guides/post-call/polling-call-status-webhooks). If you already use that endpoint for post-call execution webhooks, it will now also receive pre-call webhooks. Distinguish them by the in-progress `status` and the extra fields from your `pre_call_webhook_param`.
</Warning>

### UI Configuration

In the agent dashboard, the Transfer Call configuration modal has a **Send a pre-call webhook before transfer** toggle. Turning it on reveals two inputs:

* **Pre-call webhook URL** — the endpoint to notify (`pre_call_webhook_url`). Leave blank to use the agent-level Webhook URL.
* **Pre-call webhook parameters** — the JSON body template with `%(field)s` substitution (`pre_call_webhook_param`).

Both save with the transfer tool and round-trip on edit.

***

## How to Set Up Call Transfer

<Steps>
  <Step title="Open Tools Tab">
    Navigate to the [Tools Tab](/docs/agent-setup/tools-tab) in your agent configuration.
  </Step>

  <Step title="Select Transfer Call">
    Click **"Select functions"** → choose **"Transfer Call"** from the dropdown.
  </Step>

  <Step title="Configure Phone Number">
    Enter the destination phone number where calls should be transferred.
  </Step>

  <Step title="Write a Clear Description">
    Describe when the transfer should trigger - e.g., *"Transfer when caller asks for sales, pricing, or demos."*
  </Step>

  <Step title="Add Pre-tool Message">
    Set the message your agent speaks while initiating the transfer.
  </Step>

  <Step title="(Optional) Enable a Pre-call Webhook">
    Toggle **Send a pre-call webhook before transfer** to notify your system *before* the transfer happens — see [Pre-call Webhook](#pre-call-webhook).
  </Step>

  <Step title="Save Configuration">
    Click **Save transfer call** to apply your settings.
  </Step>
</Steps>

<Info>
  **Multiple departments?** Add separate transfer functions for Sales, Support, Billing - each with its own phone number and trigger description.
</Info>

***

## Example Conversation

<AccordionGroup>
  <Accordion title="Caller requests human agent" icon="message">
    **Caller**: "I'd like to speak with someone from your sales team."

    **Agent**: "Sure, I'll transfer you to our sales team. Please wait a moment..."

    *Agent triggers transfer\_call function → Call is routed to configured sales number*
  </Accordion>
</AccordionGroup>

***

## Best Practices

<CardGroup cols={2}>
  <Card title="Be Specific" icon="bullseye">
    Use detailed descriptions like *"Transfer to sales when caller asks about pricing, demos, or purchasing"* instead of generic "Transfer call"
  </Card>

  <Card title="Test Phone Numbers" icon="phone-check">
    Verify destination numbers are correct and always reachable before deploying
  </Card>

  <Card title="Use Pre-tool Messages" icon="comment">
    Always set a friendly message so callers know they're being transferred
  </Card>

  <Card title="Handle Failures" icon="triangle-exclamation">
    Have a fallback plan if the destination is busy or unavailable
  </Card>
</CardGroup>

<Warning>
  **Test before deploying!** Failed transfers frustrate callers. Always verify phone numbers are correct and reachable.
</Warning>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Custom Functions" icon="code" href="/docs/tool-calling/custom-function-calls">
    Build custom API integrations for your agent
  </Card>

  <Card title="Check Calendar Slots" icon="calendar-range" href="/docs/tool-calling/fetch-calendar-slots">
    Query availability via Cal.com integration
  </Card>

  <Card title="Book Appointments" icon="calendar-check" href="/docs/tool-calling/book-calendar-slots">
    Schedule meetings during live calls
  </Card>

  <Card title="Tools Tab Guide" icon="function" href="/docs/agent-setup/tools-tab">
    Complete function configuration guide
  </Card>
</CardGroup>
