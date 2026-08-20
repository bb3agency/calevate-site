> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Make Outbound Calls via SIP Trunk on Bolna

> Place outbound calls from your SIP trunk phone numbers using Bolna AI agents. Configure your agent, set the telephony provider, and start calling through your own trunk.

## How Outbound Calls Work

When you initiate an outbound call through your SIP trunk, here is the complete flow:

<Steps>
  <Step title="You Trigger a Call via API">
    You send a request to the [Bolna Call API](/docs/api-reference/calls/make) with your agent ID, the recipient's phone number, and the `from_number` (your SIP trunk phone number to use as the caller ID).
  </Step>

  <Step title="Bolna Resolves the Trunk">
    Bolna looks up the `from_number` in its database to find the associated SIP trunk and its gateway configuration (address, credentials, codecs).
  </Step>

  <Step title="SIP INVITE Sent via Asterisk">
    Bolna's Asterisk/PJSIP server sends a **SIP INVITE** to your trunk's gateway address (e.g., `bolna-trunk.pstn.twilio.com` or `XXXX.zt.plivo.com`) with the appropriate authentication.
  </Step>

  <Step title="Provider Routes to PSTN">
    Your SIP trunk provider receives the INVITE, authenticates the request, verifies the caller ID, and then routes the call to the recipient's phone number on the PSTN.
  </Step>

  <Step title="AI Agent Handles the Conversation">
    Once the recipient answers the phone, Bolna's Voice AI pipeline takes over. The AI agent speaks, listens, and responds in real-time throughout the entire conversation.
  </Step>
</Steps>

***

## Prerequisites

Before making outbound calls, make sure you have completed all previous steps:

1. Created a SIP trunk on your provider ([Plivo guide](/docs/tutorials/sip-trunking/plivo-trunk-setup) or [Twilio guide](/docs/tutorials/sip-trunking/twilio-trunk-setup))
2. [Registered the trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna) and confirmed `is_active` is `true`
3. [Added your phone numbers](/docs/tutorials/sip-trunking/register-trunk-on-bolna#step-2-add-phone-numbers) to the trunk on Bolna
4. Created a Bolna AI agent via the [Dashboard](https://platform.bolna.ai/) or the [Agent API](/docs/api-reference/agent/v2/create)

***

## Step 1: Configure the Agent's Telephony Provider

Before your agent can place calls through your SIP trunk, you need to tell it to use SIP trunking instead of the default telephony provider. Set `telephony_provider` to `"sip-trunk"` in your agent's configuration:

```bash theme={"system"}
curl -X PATCH https://api.bolna.ai/v2/agent/<agent-id> \
  -H "Authorization: Bearer <your-bolna-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_config": {
      "telephony_provider": "sip-trunk"
    }
  }'
```

<Note>
  Setting `telephony_provider` to `"sip-trunk"` tells Bolna to:

  1. Route all outbound calls through your SIP trunk's gateway instead of Twilio's or Plivo's standard API
  2. Use **ulaw** audio encoding (G.711 u-law) as required by SIP trunks
  3. Authenticate using the credentials stored in your trunk configuration
</Note>

***

## Step 2: Place an Outbound Call

Use the standard [Call API](/docs/api-reference/calls/make) to place a call. The key difference from a regular Bolna call is the `from_number` field, which must be a phone number registered on your SIP trunk.

<CodeGroup>
  ```bash request theme={"system"}
  curl -X POST https://api.bolna.ai/call \
    -H "Authorization: Bearer <your-bolna-api-key>" \
    -H "Content-Type: application/json" \
    -d '{
      "agent_id": "agt-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "recipient": {
        "phone_number": "+918800001234",
        "name": "Rahul Sharma"
      },
      "from_number": "+919876543210"
    }'
  ```
</CodeGroup>

### Field Reference

| Field                    | Description                                                                                                    |
| ------------------------ | -------------------------------------------------------------------------------------------------------------- |
| `agent_id`               | UUID of the Bolna agent that will handle the conversation                                                      |
| `recipient.phone_number` | The recipient's phone number in E.164 format (`+` followed by country code and number)                         |
| `recipient.name`         | The recipient's name. This is available to the AI agent during the conversation for personalized interactions. |
| `from_number`            | Your SIP trunk phone number to use as the caller ID. **This number must be registered on your SIP trunk.**     |

<Warning>
  The `from_number` **must** be a phone number that you purchased on your SIP provider (Plivo, Twilio, etc.) and then [added to your trunk on Bolna](/docs/tutorials/sip-trunking/register-trunk-on-bolna#step-2-add-phone-numbers). If the number is not found on any trunk, Bolna will not know which gateway to route the call through and the call will fail.
</Warning>

***

## Step 3: Verify Call Status

After placing a call, you can monitor its status using the [Call Status API](/docs/guides/post-call/list-phone-call-status):

```bash theme={"system"}
curl -X GET https://api.bolna.ai/call/<execution-id>/status \
  -H "Authorization: Bearer <your-bolna-api-key>"
```

You can also set up [webhooks](/docs/guides/post-call/polling-call-status-webhooks) to receive real-time status updates as the call progresses through different stages (ringing, answered, completed, etc.).

***

## Batch Outbound Calling

For high-volume outbound campaigns where you need to call many people automatically, Bolna supports batch calling through your SIP trunk. Use the [Batch API](/docs/api-reference/batches/create) to schedule and manage large call campaigns.

Key points for batch calling with SIP trunks:

* Ensure the agent's `telephony_provider` is set to `"sip-trunk"` as described in Step 1
* Each call in the batch should use a `from_number` that is registered on your trunk
* Monitor concurrency limits, which depend on your SIP trunk provider's capacity and plan

For detailed batch calling instructions, see the [Batch Calling guide](/docs/guides/outbound/batch-calling).

***

## Troubleshooting Outbound Calls

<AccordionGroup>
  <Accordion title="Call fails to connect">
    If the call never rings on the recipient's phone:

    * **Check trunk status.** Verify your trunk's `is_active` is `true`:

    ```bash theme={"system"}
    curl -X GET https://api.bolna.ai/sip-trunks/trunks/<trunk-id> \
      -H "Authorization: Bearer <your-bolna-api-key>"
    ```

    * **Verify `from_number`.** Ensure the `from_number` you used in the call request is registered on the trunk.
    * **Check gateway credentials.** For `userpass` auth, verify the username and password in your trunk configuration are correct and match what you set up on your provider.
    * **Check IP whitelist.** For `ip-based` auth, ensure `13.200.45.61` is whitelisted on your provider's side.
    * **Review provider logs.** Check your provider's call logs for SIP error codes (e.g., `401 Unauthorized`, `403 Forbidden`, `404 Not Found`).
  </Accordion>

  <Accordion title="Call connects but there is no audio">
    This is almost always caused by an **SRTP mismatch**:

    * **Disable SRTP / Secure Trunking** on your SIP provider. Bolna does not support SRTP, and if it is enabled, the media negotiation fails silently.
    * **Verify codec settings.** Ensure `ulaw` is in the `allow` list on your Bolna trunk.
    * **Check `rtp_symmetric`.** This should be `true` (which is the default).
    * **Check `force_rport`.** This should be `true` (which is the default).
  </Accordion>

  <Accordion title="One-way audio (only one side can hear)">
    If you can hear the agent but the caller cannot, or vice versa:

    * **Enable Symmetric RTP.** Set `rtp_symmetric` to `true` on your Bolna trunk (this is the default).
    * **Enable force\_rport.** Set `force_rport` to `true` (this is the default).
    * **Check NAT traversal.** Confirm your provider's RTP IP ranges are reachable from Bolna's IP `13.200.45.61`.
    * **Keep direct\_media disabled.** Ensure `direct_media` is `false` (the default). Enabling it bypasses Bolna's media server, which often causes one-way audio.
  </Accordion>

  <Accordion title="Leading plus (+) issues with phone numbers">
    Some carriers require the `+` prefix on dialed numbers (E.164 format), while others reject it.

    * **Twilio** requires the `+` prefix. Keep `outbound_leading_plus_enabled` as `true` (default).
    * **Plivo** generally accepts both formats.
    * **Other providers:** Check your provider's documentation for their preferred number format.

    You can update this setting per-trunk:

    ```bash theme={"system"}
    curl -X PATCH https://api.bolna.ai/sip-trunks/trunks/<trunk-id> \
      -H "Authorization: Bearer <your-bolna-api-key>" \
      -H "Content-Type: application/json" \
      -d '{ "outbound_leading_plus_enabled": false }'
    ```
  </Accordion>

  <Accordion title="Caller ID rejected by your provider">
    If the provider rejects the call because of an invalid caller ID:

    * **Twilio:** The `from_number` must be either a Twilio DID number on your account or a verified Caller ID number.
    * **Plivo:** The `from_number` must be a number in your Plivo account.
    * Ensure the number format matches what your provider expects. E.164 (with `+`) is recommended for all providers.
  </Accordion>
</AccordionGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Receive Inbound Calls" icon="phone-arrow-down-left" href="/docs/tutorials/sip-trunking/inbound-calls">
    Route incoming calls to your Bolna AI agents
  </Card>

  <Card title="Batch Calling" icon="list-ol" href="/docs/guides/outbound/batch-calling">
    Run high-volume outbound AI call campaigns
  </Card>

  <Card title="Monitor Call Status" icon="chart-line" href="/docs/guides/post-call/list-phone-call-status">
    Track call status and outcomes in real-time
  </Card>

  <Card title="SIP Trunk API Reference" icon="code" href="/docs/api-reference/sip-trunks/overview">
    Full API reference for managing trunks and numbers
  </Card>
</CardGroup>
