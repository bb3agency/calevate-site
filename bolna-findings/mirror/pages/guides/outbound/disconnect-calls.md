> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Terminate Bolna Voice AI calls

> Optimize call lengths with Bolna Voice AI by setting duration limits. Automatically terminate calls exceeding limits for better resource management.

<Warning>
  This page has been merged into [Hangup & Disconnect calls](/docs/guides/outbound/hangup-calls). You will be redirected automatically. Update any bookmarks to point to [/hangup-calls](/docs/guides/outbound/hangup-calls).
</Warning>

## What are Call Duration Limits?

Bolna Voice AI lets you set a maximum call duration (in seconds) for automatic termination. Once the limit is reached, the call ends automatically, providing a safety net against unexpectedly long calls.

<Frame caption="Configuring maximum call duration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/disconnect_calls_3.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=5c2839af80f16d1f9c0fb6eba6149846" alt="Call duration limit settings in Bolna Voice AI showing maximum duration configuration for automatic termination" width="731" height="583" data-path="images/disconnect_calls_3.png" />
</Frame>

***

## Why Set Duration Limits?

<CardGroup cols={2}>
  <Card title="Control Costs" icon="dollar-sign">
    Prevent unexpectedly long calls from consuming credits
  </Card>

  <Card title="Manage Resources" icon="server">
    Ensure fair allocation of concurrent call capacity
  </Card>

  <Card title="Safety Net" icon="shield-check">
    Protect against edge cases where calls do not end naturally
  </Card>

  <Card title="Predictable Billing" icon="receipt">
    Better forecast and manage calling expenses
  </Card>
</CardGroup>

<Info>
  Learn more about [call pricing](/docs/pricing/call-pricing) and [outbound calling concurrency](/docs/pricing/outbound-calling-concurrency).
</Info>

***

## Compatibility

| Call Type      | Support           |
| -------------- | ----------------- |
| Outbound calls | ✓ Fully supported |
| Inbound calls  | ✓ Fully supported |

***

## Duration Limits vs. Hangup Prompts

| Feature           | Duration Limits                   | Hangup Prompts                      |
| ----------------- | --------------------------------- | ----------------------------------- |
| **Trigger**       | Hard time-based cutoff            | Context-aware conversation analysis |
| **Accuracy**      | 100%, always triggers at set time | Prompt-dependent, may need tuning   |
| **Use case**      | Safety net for runaway calls      | Natural, intelligent call endings   |
| **Configuration** | Set duration in seconds           | Write a custom evaluation prompt    |

<Tip>
  **Use both together** for optimal call management: hangup prompts for natural conversation endings, and duration limits as a safety net to prevent runaway calls.
</Tip>

***

## Related Features

<CardGroup cols={3}>
  <Card title="Hangup Settings" icon="phone-hangup" href="/docs/guides/outbound/hangup-calls">
    Configure silence detection and hangup prompts
  </Card>

  <Card title="Call Status List" icon="ballot-check" href="/docs/guides/post-call/list-phone-call-status">
    Monitor the full lifecycle of your calls
  </Card>

  <Card title="Hangup Status Codes" icon="phone-xmark" href="/docs/guides/post-call/list-phone-call-hangup-status">
    Understand call termination reasons
  </Card>
</CardGroup>
