> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Receive Bolna Voice AI call updates

> Receive real-time call status updates from Bolna Voice AI using webhooks. Automate workflows, update CRM, and sync data with your systems.

## What are Webhooks?

Webhooks allow you to receive real-time call data from Bolna as call status updates happen. When a call status changes, Bolna sends an HTTP POST request to your server with the execution data.

<Frame caption="Configure Webhook in Extractions Tab">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uerR6qR-mPhGkJD9/images/extractions/extractions-tab.png?fit=max&auto=format&n=uerR6qR-mPhGkJD9&q=85&s=c7994cf421e3f434442bbc247a977815" alt="Extractions Tab showing webhook URL configuration and post-call tasks" width="1896" height="1036" data-path="images/extractions/extractions-tab.png" />
</Frame>

***

## Setting Up Webhooks

<Steps>
  <Step title="Go to Extractions Tab">
    Open your agent and navigate to the **[Extractions Tab](/docs/agent-setup/analytics-tab)**.
  </Step>

  <Step title="Enter Webhook URL">
    In the **"Push all execution data to webhook"** section, enter your webhook endpoint URL.
  </Step>

  <Step title="Save Agent">
    Click **Save agent** to activate the webhook.
  </Step>
</Steps>

<Warning>
  **Your webhook endpoint must be publicly accessible** and able to receive HTTP POST requests. Bolna will POST data to this URL as call status updates.
</Warning>

***

## IP Whitelist

<Info>
  Webhooks are sent from the following IP addresses. **Whitelist all three** on your server to ensure you receive all webhook events.
</Info>

```
13.203.39.153
13.126.9.249
13.202.133.53
```

***

## Webhook Payload

<Warning>
  The webhook payload is the **same structure as the Raw Call Data** you see in [Call History](/docs/agent-setup/call-history). It matches the [Get Execution API](/docs/api-reference/executions/get_execution) response format.
</Warning>

As call status updates (scheduled → queued → in-progress → completed), Bolna sends POST requests to your webhook with the current execution data.

<Tip>
  Test your webhook integration using [webhook.site](https://webhook.site) before implementing a production server.
</Tip>

***

## Pre-call Webhooks

The same payload shape is reused for **pre-call webhooks** — notifications fired by a [custom function tool](/docs/tool-calling/custom-function-calls#pre-call-webhooks) or the [Transfer Call tool](/docs/tool-calling/transfer-calls#pre-call-webhook) *before* the tool runs (for example, to send a transfer reason before a call is transferred).

<Warning>
  If a tool sets a `pre_call_webhook_param` without its own `pre_call_webhook_url`, the pre-call webhook is sent to **this agent-level Webhook URL**. The endpoint you configure here may therefore receive in-progress pre-call webhooks in addition to your post-call execution webhooks. Distinguish them by the `in-progress` `status` and the extra fields from the tool's `pre_call_webhook_param`.
</Warning>

Learn more in the [Pre-call Webhooks](/docs/tool-calling/custom-function-calls#pre-call-webhooks) section of the Custom Functions guide, or the [Transfer Call](/docs/tool-calling/transfer-calls#pre-call-webhook) guide.

***

## Use Cases

<CardGroup cols={2}>
  <Card title="CRM Integration" icon="database">
    Automatically update customer records after each call
  </Card>

  <Card title="Real-time Dashboards" icon="chart-line">
    Build live dashboards with call metrics and analytics
  </Card>

  <Card title="Workflow Automation" icon="bolt">
    Trigger actions based on call outcomes
  </Card>

  <Card title="Data Logging" icon="table">
    Log all call data to your preferred storage system
  </Card>
</CardGroup>

***

## Call Statuses

<CardGroup cols={1}>
  <Card title="View All Call Statuses" icon="ballot-check" href="/docs/guides/post-call/list-phone-call-status">
    Learn about all valid call status types in Bolna Voice AI
  </Card>
</CardGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Extractions Tab" icon="chart-line" href="/docs/agent-setup/analytics-tab">
    Configure post-call extraction and summarization
  </Card>

  <Card title="Call History" icon="clock-rotate-left" href="/docs/agent-setup/call-history">
    View raw call data and recordings
  </Card>

  <Card title="Get Execution API" icon="code" href="/docs/api-reference/executions/get_execution">
    Understand the execution data structure
  </Card>

  <Card title="Batch Calling" icon="phone" href="/docs/guides/outbound/batch-calling">
    Automate outbound calling campaigns
  </Card>
</CardGroup>
