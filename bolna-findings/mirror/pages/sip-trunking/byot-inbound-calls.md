> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Receive Inbound Calls via Your SIP Trunk

> Route incoming calls from your SIP trunk to Bolna AI agents. Map DID phone numbers to agents so calls are automatically answered.

## How inbound calls work with BYOT

When a call arrives on one of your DID numbers, the following happens:

1. Your SIP provider sends the INVITE to Bolna's SIP server at `sip:sip.bolna.ai:5060` (UDP/TCP) or `sip:sip.bolna.ai:5061;transport=tls` (TLS trunks)
2. Bolna matches the called number against your registered phone numbers
3. The call is routed to the AI agent mapped to that number
4. The agent answers and handles the conversation

## Prerequisites

Before setting up inbound calls, ensure:

1. You have [created a SIP trunk](/docs/sip-trunking/byot-setup) on Bolna
2. You have [added your phone numbers](/docs/sip-trunking/byot-setup#add-phone-numbers-to-your-trunk) to the trunk
3. Your SIP provider is routing those DIDs to `sip:sip.bolna.ai:5060` (or `sip:sip.bolna.ai:5061;transport=tls` for TLS trunks)
4. `inbound_enabled` is set to `true` on your trunk
5. You have a Bolna agent created

## Map a phone number to an agent

Use the [Set Inbound Agent API](/docs/api-reference/inbound/agent) to map a phone number to your Bolna agent.

<CodeGroup>
  ```bash request theme={"system"}
  curl -X POST https://api.bolna.ai/inbound/setup \
    -H "Authorization: Bearer <token>" \
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

| Field             | Type   | Required | Description                                                                                                         |
| ----------------- | ------ | -------- | ------------------------------------------------------------------------------------------------------------------- |
| `agent_id`        | string | **Yes**  | The UUID of the Bolna agent that should handle calls on this number.                                                |
| `phone_number_id` | string | **Yes**  | The phone number ID returned when you [added the number to the trunk](/docs/byot-setup#add-phone-numbers-to-your-trunk). |

Once mapped, any call arriving on that DID will be answered by the specified agent. The agent's audio format is automatically updated to `ulaw` to match Asterisk's requirements.

<Note>
  **One number, one agent:** A phone number can only be mapped to one agent at a time. Mapping it to a new agent automatically unmaps it from the previous one.
</Note>

## Unlink a number from an agent

To stop an agent from answering calls on a number (without removing the number from the trunk), use the unlink endpoint:

```bash theme={"system"}
curl -X POST https://api.bolna.ai/inbound/unlink \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "agt-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    "phone_number_id": "01HQNUMBER111222333"
  }'
```

After unlinking, inbound calls to that number will no longer be answered by an agent.

## Troubleshooting inbound calls

If inbound calls are not arriving or are being rejected:

1. Confirm your SIP provider has `sip:sip.bolna.ai:5060` (or `sip:sip.bolna.ai:5061;transport=tls` for TLS trunks) set as the origination URI for the DID
2. Confirm the phone number has been [added to the trunk](/docs/sip-trunking/byot-setup#add-phone-numbers-to-your-trunk)
3. Confirm the phone number has been mapped to an agent (above)
4. Confirm `inbound_enabled` is `true` on the trunk
5. Check that the number format in the INVITE's `Request-URI` or `To` header matches what you stored (with or without `+`)

## Next steps

* [Make outbound calls](/docs/sip-trunking/byot-outbound-calls) from your SIP trunk numbers
* [Manage your trunk](/docs/api-reference/sip-trunks/overview) using the SIP Trunk API
* [Monitor call status](/docs/guides/post-call/list-phone-call-status) in real-time
