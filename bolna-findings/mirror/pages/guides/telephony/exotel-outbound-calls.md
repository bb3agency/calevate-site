> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Make Outbound Calls with Exotel and Bolna

> Set up & run outbound calling campaigns in India with Bolna Voice AI on Exotel. Follow this step-by-step guide for dashboard setup and seamless API integration.

## Launching Outbound Calls Through the Bolna Dashboard

### Step 1: Access Your Bolna Platform Account

Navigate to [https://platform.bolna.ai](https://platform.bolna.ai) and authenticate using your registered account credentials.

<Frame caption="Login Bolna playground">
  <img src="https://mintcdn.com/bolna-54a2d4fe/BtSsoIcVmoT1Eun6/images/outbound_exotel_step_1.gif?s=ddd3d133b2291eda399c897765a0568b" alt="Bolna platform login interface showing authentication process for connecting Voice AI agent dashboard with your Exotel account" width="1152" height="648" data-path="images/outbound_exotel_step_1.gif" />
</Frame>

<br />

### Step 2: Configure Exotel as Your Telephony Provider

Within your agent configuration settings, select `Exotel` from the available call provider options. This designation tells Bolna to route all outbound calls through Exotel's telephony infrastructure.

<Frame caption="Choose Exotel as the agent call provider">
  <img src="https://mintcdn.com/bolna-54a2d4fe/BtSsoIcVmoT1Eun6/images/outbound_exotel_step_2.gif?s=a744dc324c625f3044004e2800e5dffb" alt="Exotel provider selection in Bolna agent configuration showing call provider setup for outbound Voice AI calling" width="1692" height="1017" data-path="images/outbound_exotel_step_2.gif" />
</Frame>

<br />

### Step 3: Initiate Calls to Your Target Recipients

Enter the phone numbers of your intended call recipients in the designated input field. Bolna will automatically initiate calls through your Exotel connection, engaging with each recipient using the voice agents you've configured.

<Frame caption="Start placing phone calls on Bolna using Exotel">
  <img src="https://mintcdn.com/bolna-54a2d4fe/BtSsoIcVmoT1Eun6/images/outbound_exotel_step_3.gif?s=c5a811b5b33dc9e1c313956fd7113618" alt="Outbound call initiation interface in Bolna showing phone number input and call placement process using Exotel integration" width="1692" height="1017" data-path="images/outbound_exotel_step_3.gif" />
</Frame>

<br />

<Note>
  To utilize your own dedicated Exotel phone numbers for outbound calling, you must first establish a connection between your Exotel account and Bolna. Detailed instructions for linking your Exotel account are available in the [providers configuration guide](/docs/exotel-connect-provider).
</Note>

## Programmatic Outbound Calling Using Bolna APIs

For developers building custom applications or integrating voice AI into existing systems, Bolna provides comprehensive REST APIs for programmatic call management.

### Step 1: Obtain Your API Authentication Key

1. Generate and save your [Bolna API Key](/docs/api-reference/introduction#steps-to-generate-your-api-key)

### Step 2: Configure Agent with Exotel Provider

When creating or updating your Bolna agent through the [`/create` Agent API](/docs/api-reference/agent/create), specify `exotel` as both the input and output provider within your tools configuration.

```create-agent.json theme={"system"}
...
...
"tools_config": {
    "output": {
        "format": "wav",
        "provider": "exotel"
    },
    "input": {
        "format": "wav",
        "provider": "exotel"
    },
    "synthesizer": {...},
    "llm_agent": {...},
    "transcriber": {...},
    "api_tools": {...}
}
...
...
```

### Step 3: Trigger Outbound Calls Programmatically

Execute the [`/call` API endpoint](api-reference/calls/make) to initiate outbound calls to your target recipients. Include your agent ID and the recipient's phone number in E.164 international format. The API will return a call ID that you can use to track call status and retrieve conversation analytics.

```call.json theme={"system"}

curl --request POST \
  --url https://api.bolna.ai/call \
  --header 'Authorization: <authorization>' \
  --header 'Content-Type: application/json' \
  --data '{
  "agent_id": "fd3d9b56-0742-4a39-aaac-50dec1f37d00",
  "recipient_phone_number": "+919876543210"
}'
```
