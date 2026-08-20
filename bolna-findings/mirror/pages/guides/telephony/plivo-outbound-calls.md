> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Initiate Outbound Calls via Plivo with Bolna Voice AI

> Configure Bolna Voice AI agents to make outbound calls through Plivo. Learn to set up calls using the dashboard and APIs for effective outreach.

## Making outbound calls from dashboard

1. Login to the dashboard at [https://platform.bolna.ai](https://platform.bolna.ai) using your account credentials

<Frame caption="Login Bolna playground">
  <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/outbound_plivo_step_1.gif?s=29e3d738fae9e5fdfaf3623c0815e96e" alt="Bolna platform login interface showing authentication process for connecting Voice AI agent dashboard with your Plivo account" width="1152" height="648" data-path="images/outbound_plivo_step_1.gif" />
</Frame>

<br />

2. Choose `Plivo` as the Call provider for your agent and save it

<Frame caption="Choose Plivo as the agent call provider">
  <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/outbound_plivo_step_2.gif?s=b747fe686dfa156ec3975e3ac3c89467" alt="Plivo provider selection in Bolna agent configuration showing call provider setup for outbound Voice AI calling" width="1152" height="648" data-path="images/outbound_plivo_step_2.gif" />
</Frame>

<br />

3. Start placing phone calls by providing the recipient phone numbers.
   Bolna will place the calls to the provided phone numbers.

<Frame caption="Start placing phone calls on Bolna using Plivo">
  <img src="https://mintcdn.com/bolna-54a2d4fe/HwOYKfzp4mnvdMa0/images/outbound_plivo_step_3.gif?s=8f55072faa2275011b31dac8a1b1c549" alt="Outbound call initiation interface in Bolna showing phone number input and call placement process using Plivo integration" width="1280" height="640" data-path="images/outbound_plivo_step_3.gif" />
</Frame>

<br />

<Note>
  You can place calls using your own custom Plivo phone numbers only if you've connected your Plivo account.
  You can read more on how to connect your Plivo account [here](/docs/providers).
</Note>

## Making outbound calls Using APIs

1. Generate and save your [Bolna API Key](/docs/api-reference/introduction#steps-to-generate-your-api-key)
2. Set your agent `input` and `output` tools as `plivo` while using [`/create` Agent API](/docs/api-reference/agent/create)

```create-agent.json theme={"system"}
...
...
"tools_config": {
    "output": {
        "format": "wav",
        "provider": "plivo"
    },
    "input": {
        "format": "wav",
        "provider": "plivo"
    },
    "synthesizer": {...},
    "llm_agent": {...},
    "transcriber": {...},
    "api_tools": {...}
}
...
...
```

3. Use [`/call` API](api-reference/calls/make) to place the call to the agent

```call.json theme={"system"}

curl --request POST \
  --url https://api.bolna.ai/call \
  --header 'Authorization: <authorization>' \
  --header 'Content-Type: application/json' \
  --data '{
  "agent_id": "123e4567-e89b-12d3-a456-426655440000",
  "recipient_phone_number": "+10123456789"
}'
```
