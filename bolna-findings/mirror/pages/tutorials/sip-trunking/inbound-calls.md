> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Receive Inbound Calls via SIP Trunk on Bolna

> Route incoming phone calls from your SIP trunk to Bolna AI agents. Map DID phone numbers to specific agents so inbound calls are automatically answered by your Voice AI.

## How Inbound Calls Work

When someone calls your DID phone number, here is the complete flow:

<Steps>
  <Step title="Caller Dials Your Number">
    A caller on the PSTN (regular phone network) dials your DID phone number, for example `+919876543210`.
  </Step>

  <Step title="Provider Routes to Bolna">
    Your SIP trunk provider (Plivo or Twilio) receives the call and forwards a SIP INVITE message to Bolna's SIP server at `sip:13.200.45.61:5060`, based on the origination settings you configured in the previous steps.
  </Step>

  <Step title="Bolna Matches the Number">
    Bolna receives the INVITE and looks at the called number in the SIP headers. It matches this number against your registered phone numbers to find the associated trunk and agent.
  </Step>

  <Step title="AI Agent Answers">
    The call is routed to the AI agent that you have **mapped** to that phone number. The agent answers and begins the conversation, speaking and listening in real-time.
  </Step>
</Steps>

***

## Prerequisites

Before setting up inbound calls, make sure you have completed all these previous steps:

1. Created a SIP trunk on your provider ([Plivo guide](/docs/tutorials/sip-trunking/plivo-trunk-setup) or [Twilio guide](/docs/tutorials/sip-trunking/twilio-trunk-setup))
2. Configured origination settings so your provider knows to route inbound calls to `sip:13.200.45.61:5060`
3. [Registered the trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna) with `inbound_enabled` set to `true`
4. [Added your phone numbers](/docs/tutorials/sip-trunking/register-trunk-on-bolna#step-2-add-phone-numbers) to the trunk on Bolna
5. Created a Bolna AI agent via the [Dashboard](https://platform.bolna.ai/) or the [Agent API](/docs/api-reference/agent/v2/create)

***

## Map a Phone Number to an AI Agent

This is the key step where you tell Bolna which AI agent should answer calls on a specific phone number. Use the [Set Inbound Agent API](/docs/api-reference/inbound/agent):

<CodeGroup>
  ```bash request theme={"system"}
  curl -X POST https://api.bolna.ai/inbound/setup \
    -H "Authorization: Bearer <your-bolna-api-key>" \
    -H "Content-Type: application/json" \
    -d '{
      "agent_id": "agt-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "phone_number_id": "01HQNUMBER111222333"
    }'
  ```

  ```json response theme={"system"}
  {
    "message": "SIP trunk number successfully mapped to agent"
  }
  ```
</CodeGroup>

### Where to find these values

| Field             | Type   | Where to Find It                                                                                                                                                                                                                                                                         |
| ----------------- | ------ | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `agent_id`        | string | The UUID of your Bolna agent. Found in the [Bolna Dashboard](https://platform.bolna.ai/) by clicking on your agent, or returned by the [Create Agent API](/docs/api-reference/agent/v2/create).                                                                                               |
| `phone_number_id` | string | The ID of the phone number on Bolna. This must be a number you purchased on your SIP provider and then [added to your trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna#step-2-add-phone-numbers). Use the `id` from the Add Number response, not the phone number itself. |

<Note>
  **One number can only be mapped to one agent at a time.** If you map a number to a new agent, it is automatically unmapped from the previous agent. When a number is mapped to an agent via SIP trunk, Bolna automatically sets the audio format to **ulaw** (G.711) to match the trunk's requirements.
</Note>

***

## Test Your Inbound Setup

After mapping your number, test the complete flow:

<Steps>
  <Step title="Dial Your DID Number">
    From any phone (a mobile phone will do), call the DID number you mapped to the agent. For example, dial `+919876543210`.
  </Step>

  <Step title="Verify the Agent Answers">
    You should hear your AI agent's greeting message. Try having a brief conversation to confirm the agent is responding correctly.
  </Step>

  <Step title="Check Call Logs">
    After the call, verify it appeared in:

    * Your [Bolna Dashboard](https://platform.bolna.ai/) call history
    * Your SIP provider's call logs ([Plivo logs](https://console.plivo.com/zentrunk/logs/calls/) or [Twilio logs](https://www.twilio.com/console/sip-trunking/logs))
  </Step>
</Steps>

***

## Unlink a Number from an Agent

To stop an agent from answering calls on a specific number (without removing the number from the trunk entirely), use the unlink endpoint:

```bash theme={"system"}
curl -X POST https://api.bolna.ai/inbound/unlink \
  -H "Authorization: Bearer <your-bolna-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agt-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "phone_number_id": "01HQNUMBER111222333"
  }'
```

After unlinking, inbound calls to that number will no longer be answered by any agent. The number remains on the trunk and can be re-mapped to a different agent (or the same agent) at any time.

***

## Troubleshooting Inbound Calls

<AccordionGroup>
  <Accordion title="Calls are not arriving at Bolna">
    If calls ring on the caller's end but never reach Bolna:

    * **Check your provider's origination settings.** Confirm the origination URI is set to `sip:13.200.45.61:5060` on your provider.
    * **Check the phone number assignment** on your provider's side:
      * **Plivo:** Ensure the Application Type is set to `Zentrunk` and the correct inbound trunk is selected for the number.
      * **Twilio:** Ensure the number is associated with the correct trunk in the Numbers tab.
    * **Review your provider's call logs** for error codes or rejection reasons (e.g., `404 Not Found` or `403 Forbidden`).
  </Accordion>

  <Accordion title="Calls connect but there is no audio">
    If the call connects (no ringing tone stops) but neither party can hear anything:

    * **SRTP is likely enabled.** This is the most common cause. Ensure Secure Trunking / SRTP is **disabled** on your SIP provider.
    * **Check codec settings.** Verify that `ulaw` is in the `allow` list on your Bolna trunk configuration.
    * **Check Symmetric RTP.** Ensure `rtp_symmetric` is set to `true` on your Bolna trunk.
  </Accordion>

  <Accordion title="Calls are rejected by Bolna">
    If the call fails immediately with an error:

    * **Phone number not registered.** Confirm the number has been [added to the trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna#step-2-add-phone-numbers) using the Add Number API.
    * **Number not mapped to an agent.** Confirm you have [mapped the number to an agent](#map-a-phone-number-to-an-ai-agent) using the inbound setup API.
    * **Inbound is disabled.** Check your trunk configuration and verify that `inbound_enabled` is set to `true`.
    * **Number format mismatch.** The number in the SIP INVITE's `To` header should match what you stored. Bolna performs flexible matching (with/without `+`), but try to keep the format consistent.
  </Accordion>

  <Accordion title="Agent is not responding or call drops immediately">
    If the call connects to Bolna but the agent doesn't speak:

    * **Verify the agent is active.** Open the [Bolna Dashboard](https://platform.bolna.ai/), find your agent, and confirm it is in an active state.
    * **Check provider connections.** Make sure all required AI providers (transcriber, LLM, and voice synthesizer) are properly configured and connected in the agent's settings.
  </Accordion>
</AccordionGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Make Outbound Calls" icon="phone-arrow-up-right" href="/docs/tutorials/sip-trunking/outbound-calls">
    Place outbound calls from your SIP trunk numbers using AI agents
  </Card>

  <Card title="SIP Trunk API Reference" icon="code" href="/docs/api-reference/sip-trunks/overview">
    Full API reference for managing SIP trunks and phone numbers
  </Card>
</CardGroup>
