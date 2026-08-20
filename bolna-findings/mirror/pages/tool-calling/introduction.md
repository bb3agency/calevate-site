> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Function Calling for Voice AI Agents

> Use function tools with Bolna Voice AI agents to automate workflows. Integrate calendar booking, call transfers, and custom API endpoints during live conversations.

## What is Function Calling?

Function calling lets your Voice AI agent execute real-time actions during live conversations. Instead of just responding with text, your agent can transfer calls, book appointments, fetch data from APIs, or trigger any custom workflow.

<Frame caption="Tools Tab in Bolna showing built-in function tools for Calendar Availability, Book Appointment, Transfer Call, and a Custom Function section with Write manually and Generate from cURL options">
  <img src="https://mintcdn.com/bolna-54a2d4fe/cPN9NUobq5alKAm2/images/getting-started/agent-setup/tools-tab-overview.png?fit=max&auto=format&n=cPN9NUobq5alKAm2&q=85&s=92b9444c771072240a9fe8b62a099434" alt="Bolna Tools Tab showing Function Tools for LLM Models with Calendar Availability, Book Appointment, Transfer Call cards, and Custom Function section with Write manually and Generate from cURL buttons" width="1024" height="592" data-path="images/getting-started/agent-setup/tools-tab-overview.png" />
</Frame>

<Info>
  Function calling follows the [OpenAI specification](https://platform.openai.com/docs/guides/function-calling), so you can reuse existing function schemas with Bolna.
</Info>

***

## Available Function Tools

Bolna provides built-in tools for common use cases. Click **+ Add** next to any tool in the Tools Tab to enable it.

<CardGroup cols={2}>
  <Card title="Calendar Availability" icon="calendar-range" href="/docs/tool-calling/fetch-calendar-slots">
    Check open meeting slots from Cal.com in real-time
  </Card>

  <Card title="Book Appointment" icon="calendar-check" href="/docs/tool-calling/book-calendar-slots">
    Create calendar bookings via Cal.com during a call
  </Card>

  <Card title="Transfer Call" icon="phone-arrow-right" href="/docs/tool-calling/transfer-calls">
    Route the call to a human agent or another number
  </Card>

  <Card title="Custom Function" icon="code" href="/docs/tool-calling/custom-function-calls">
    Connect any external API endpoint with a custom schema
  </Card>
</CardGroup>

For custom integrations, you can either **write the function schema manually** or **generate it from a cURL command** you already have. See the [Custom Functions guide](/docs/tool-calling/custom-function-calls) for details.

***

## How It Works

<Steps>
  <Step title="LLM Reads Function Definition">
    The LLM sees your function's `name` and `description` to understand what the function does
  </Step>

  <Step title="Decides When to Call">
    Based on conversation context, the LLM decides if this function should be triggered
  </Step>

  <Step title="Extracts Parameters">
    The LLM collects required parameter values from the conversation with the caller
  </Step>

  <Step title="Bolna Executes API Call">
    Bolna makes the HTTP request to your API endpoint with the extracted parameters
  </Step>

  <Step title="Response Feeds Back">
    The API response is returned to the LLM, which continues the conversation naturally
  </Step>
</Steps>

<Tip>
  **The description is everything.** The LLM relies heavily on your function description to decide when to trigger it. A vague description leads to unreliable results.
</Tip>

***

## Context Variables

The following variables are automatically available in every conversation and can be passed to function parameters:

| Variable         | Description                                              |
| ---------------- | -------------------------------------------------------- |
| `{agent_id}`     | The `id` of the agent                                    |
| `{call_sid}`     | Unique `id` of the phone call (from Twilio, Plivo, etc.) |
| `{from_number}`  | Phone number that **initiated** the call                 |
| `{to_number}`    | Phone number that **received** the call                  |
| Custom variables | Any variable you define in the agent prompt              |

<Info>
  Variables defined in your agent prompt are automatically substituted in function parameters. Learn more in [Using Context Variables](/docs/guides/prompting/using-context).
</Info>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Custom Functions" icon="code" href="/docs/tool-calling/custom-function-calls">
    Complete guide to building custom API integrations
  </Card>

  <Card title="Transfer Calls" icon="phone-arrow-right" href="/docs/tool-calling/transfer-calls">
    Set up call routing to human agents
  </Card>

  <Card title="Calendar Booking" icon="calendar-check" href="/docs/tool-calling/book-calendar-slots">
    Integrate Cal.com for appointment scheduling
  </Card>

  <Card title="Tools Tab" icon="function" href="/docs/agent-setup/tools-tab">
    Configure tools from the agent setup interface
  </Card>
</CardGroup>
