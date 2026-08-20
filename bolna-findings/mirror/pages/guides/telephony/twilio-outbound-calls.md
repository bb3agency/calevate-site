> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Make Outbound Calls via Twilio with Bolna Voice AI

> Set up Bolna Voice AI agents to place outbound calls through Twilio. Learn dashboard configurations and API methods for efficient call management.

## Making outbound calls from dashboard

1. Login to the dashboard at [https://platform.bolna.ai](https://platform.bolna.ai) using your account credentials

<Frame caption="Login Bolna playground">
  <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/outbound_twilio_step_1.gif?s=b10c3b9a30fbb39d976468346f11c7ad" alt="Bolna platform login interface showing authentication process for accessing Voice AI agents with Twilio" width="1152" height="648" data-path="images/outbound_twilio_step_1.gif" />
</Frame>

<br />

2. Choose `Twilio` as the Call provider for your agent and save it

<Frame caption="Choose Twilio as the agent call provider">
  <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/outbound_twilio_step_2.gif?s=4008391e69c5b34f0abafea99d76ac28" alt="Twilio provider selection in Bolna configuration showing call provider setup for outbound callings with Bolna Voice AI agents" width="1152" height="648" data-path="images/outbound_twilio_step_2.gif" />
</Frame>

<br />

3. Start placing phone calls by providing the recipient phone numbers.
   Bolna will place the calls to the provided phone numbers.

<Frame caption="Start placing phone calls on Bolna using Twilio">
  <img src="https://mintcdn.com/bolna-54a2d4fe/DqJpudnR0YtgOS49/images/outbound_twilio_step_3.gif?s=5c651cd80372b39497bcdc2f0e066946" alt="Outbound call initiation interface in Bolna showing phone number input and call placement process using Twilio integration" width="1152" height="648" data-path="images/outbound_twilio_step_3.gif" />
</Frame>

<br />

<Note>
  You can place calls using your own custom Twilio phone numbers only if you've connected your Twilio account.
  You can read more on how to connect your Twilio account [here](/docs/providers).
</Note>

## Making outbound calls Using APIs

1. Generate and save your [Bolna API Key](/docs/api-reference/introduction#steps-to-generate-your-api-key)
2. Set your agent `input` and `output` tools as `twilio` while using [`/create` Agent API](/docs/api-reference/agent/create)

```create-agent.json theme={"system"}
...
...
"tools_config": {
    "output": {
        "format": "wav",
        "provider": "twilio"
    },
    "input": {
        "format": "wav",
        "provider": "twilio"
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
