> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Connect Function Tools and API Integrations

> Add built-in function tools and custom API integrations to your Bolna Voice AI agent. Enable calendar booking, call transfers, and connect any external API endpoint.

The Tools Tab is where you connect external tools and APIs that your agent's LLM can call during live conversations. This lets your agent take real-time actions like booking appointments, transferring calls, or fetching data from your own backend.

<Frame caption="Tools Tab showing built-in function tools for Calendar Availability, Book Appointment, and Transfer Call, along with the Custom Function section for connecting any API endpoint">
  <img src="https://mintcdn.com/bolna-54a2d4fe/cPN9NUobq5alKAm2/images/getting-started/agent-setup/tools-tab-overview.png?fit=max&auto=format&n=cPN9NUobq5alKAm2&q=85&s=92b9444c771072240a9fe8b62a099434" alt="Bolna Tools Tab with Function Tools for LLM Models header, Add Tool section showing Calendar Availability, Book Appointment, and Transfer Call cards with Add buttons, and Add a Custom Tool section with Write manually and Generate from cURL options" width="1024" height="592" data-path="images/getting-started/agent-setup/tools-tab-overview.png" />
</Frame>

***

## Built-in Tools

Bolna provides ready-to-use tools for common voice agent workflows. Click **+ Add** next to any tool to enable it for your agent.

<CardGroup cols={2}>
  <Card title="Calendar Availability" icon="calendar-range" href="/docs/tool-calling/fetch-calendar-slots">
    Check open meeting slots from Cal.com in real-time during a call
  </Card>

  <Card title="Book Appointment" icon="calendar-check" href="/docs/tool-calling/book-calendar-slots">
    Create calendar bookings directly via Cal.com during the conversation
  </Card>

  <Card title="Transfer Call" icon="phone-arrow-right" href="/docs/tool-calling/transfer-calls">
    Route the call to a human agent or another phone number — with an optional [pre-call webhook](/docs/tool-calling/transfer-calls#pre-call-webhook)
  </Card>

  <Card title="Custom Function" icon="code" href="/docs/tool-calling/custom-function-calls">
    Connect any external API endpoint with a custom function schema
  </Card>
</CardGroup>

***

## Custom Functions

For integrations beyond the built-in tools, use **Custom Functions** to connect any API endpoint. You can create a custom function in two ways:

<Frame caption="Add a Custom Tool section showing the two ways to create a custom function: Write manually or Generate from cURL">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Vch3BdKvmDByoJ44/images/tool-calling/custom-tool-section.png?fit=max&auto=format&n=Vch3BdKvmDByoJ44&q=85&s=68558245b869aef8d2ae407f089fe711" alt="Bolna Add a Custom Tool section with Custom Function card showing Write manually button and Generate from cURL button side by side" width="1024" height="158" data-path="images/tool-calling/custom-tool-section.png" />
</Frame>

### Write Manually

Click **Write manually** to open a JSON editor where you define the function schema from scratch. This gives you full control over the function name, description, parameters, and API configuration.

<Frame caption="Custom function JSON editor showing a function schema with name, description, pre_call_message, parameters, and API configuration fields">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Vch3BdKvmDByoJ44/images/tool-calling/custom-function-config.png?fit=max&auto=format&n=Vch3BdKvmDByoJ44&q=85&s=b76342024dd993998c8025c66f6212a6" alt="Bolna custom function configuration modal with a dark code editor showing JSON schema with name test, description, pre_call_message, parameters with startTime and endTime properties, key set to custom_task, and value object with method GET, url, api_token, and headers fields" width="994" height="1024" data-path="images/tool-calling/custom-function-config.png" />
</Frame>

<Note>
  The fields `name`, `description`, `key`, and `method` are mandatory. The `key` must always be set to `"custom_task"`. Do not change this value.
</Note>

### Generate from cURL

Click **Generate from cURL** to paste an existing cURL command. Bolna will parse the request and auto-generate a function schema that you can review and edit before adding it to your agent.

<Frame caption="Generate function from cURL dialog where you paste a cURL command to auto-generate a custom function schema">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Vch3BdKvmDByoJ44/images/tool-calling/curl-to-custom-function.png?fit=max&auto=format&n=Vch3BdKvmDByoJ44&q=85&s=5f06f4bdb09045d66f47b2500210e1a9" alt="Bolna Generate function from cURL modal with a text area containing a sample curl GET request to api.bolna.ai with Authorization Bearer header, Cancel button in red and Generate function button in blue" width="1024" height="573" data-path="images/tool-calling/curl-to-custom-function.png" />
</Frame>

After clicking **Generate function**, Bolna parses the cURL and produces a ready-to-edit function configuration:

<Frame caption="Generated custom function configuration from a cURL command, showing the parsed function with auto-populated name, description, method, URL, and authentication fields">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Vch3BdKvmDByoJ44/images/tool-calling/curl-generated-result.png?fit=max&auto=format&n=Vch3BdKvmDByoJ44&q=85&s=59e968597199064f79159ffc8ca89035" alt="Bolna generated custom function configuration showing name get_agent, description Called when user asks to get agent details by agent ID, pre_call_message One moment while I fetch the details, parameters object, key custom_task, value with method GET, url https://api.bolna.ai/v2/agent/agent_id, api_token, and headers" width="1024" height="893" data-path="images/tool-calling/curl-generated-result.png" />
</Frame>

<Tip>
  The cURL import is a starting point. Always review the generated function name, description, and parameters before submitting. See the [Custom Functions guide](/docs/tool-calling/custom-function-calls#generate-from-curl) for a detailed walkthrough.
</Tip>

### Pre-call Webhook (optional)

Each custom tool also has two optional inputs to fire a [pre-call webhook](/docs/tool-calling/custom-function-calls#pre-call-webhooks) *before* the tool's main API call runs:

* **Pre-call webhook URL** — the endpoint to notify. If left blank, the agent-level Webhook URL is used.
* **Pre-call webhook parameters** — the JSON body template, with `%(field)s` substitution for the tool's arguments. Leaving this empty disables the pre-call webhook.

Both save with the tool and round-trip on edit.

<Note>
  The built-in [Transfer Call](/docs/tool-calling/transfer-calls#pre-call-webhook) tool supports the same pre-call webhook fields via a **Send a pre-call webhook before transfer** toggle in its configuration modal.
</Note>

***

## Managing Added Tools

Once you add a tool, it appears as a configurable card in the Tools Tab.

| Action        | How to do it                                                  |
| ------------- | ------------------------------------------------------------- |
| **Configure** | Click the tool card to edit its parameters and API connection |
| **Delete**    | Click the delete icon on the tool card to remove it           |

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Custom Functions Guide" icon="code" href="/docs/tool-calling/custom-function-calls">
    Full schema reference, examples, and best practices
  </Card>

  <Card title="Transfer Calls" icon="phone-arrow-right" href="/docs/tool-calling/transfer-calls">
    Set up call routing to human agents
  </Card>

  <Card title="Extractions Tab" icon="chart-line" href="/docs/agent-setup/analytics-tab">
    Configure webhooks and post-call extractions
  </Card>

  <Card title="Context Variables" icon="brackets-curly" href="/docs/guides/prompting/using-context">
    Pass dynamic data into your function tools
  </Card>
</CardGroup>
