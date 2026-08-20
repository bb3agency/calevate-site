> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Make Outbound Calls via Your SIP Trunk

> Place outbound calls from your own SIP trunk phone numbers using Bolna AI agents. Configure your agent and start calling through your trunk.

## How outbound calls work with BYOT

Outbound calls from your SIP trunk are placed via the standard Bolna call API. Bolna looks up the `from_number`, resolves the associated trunk and gateway, and places the call via Asterisk's PJSIP channel driver using your trunk's credentials.

## Prerequisites

Before making outbound calls, ensure:

1. You have [created a SIP trunk](/docs/sip-trunking/byot-setup) on Bolna
2. You have [added your phone numbers](/docs/sip-trunking/byot-setup#add-phone-numbers-to-your-trunk) to the trunk
3. `is_active` is `true` on the trunk
4. You have a Bolna agent created

## Step 1. Configure the agent's telephony provider

Set `telephony_provider` to `"sip-trunk"` in your agent's configuration. This tells Bolna to route outbound calls through your SIP trunk and use ulaw audio encoding.

```bash theme={"system"}
curl -X PATCH https://api.bolna.ai/v2/agent/{agent_id} \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_config": {
      "telephony_provider": "sip-trunk"
    }
  }'
```

## Step 2. Place an outbound call

Use the standard [call API](/docs/api-reference/calls/make), specifying the `from_number` as a DID registered on your trunk:

<CodeGroup>
  ```bash request theme={"system"}
  curl -X POST https://api.bolna.ai/call \
    -H "Authorization: Bearer <token>" \
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

<Note>
  The `from_number` must be a phone number you have registered on your SIP trunk. Bolna will use the trunk's gateway and credentials to place the call.
</Note>

## Troubleshooting outbound calls

If outbound calls are failing or not being placed:

1. Confirm `is_active` is `true` on the trunk
2. Confirm the `from_number` used in the call request is registered on the trunk
3. Confirm the gateway address and credentials are correct -- check your provider portal for authentication errors
4. For `ip-based` trunks, ensure `13.200.45.61` is in your provider's IP whitelist
5. Confirm `outbound_leading_plus_enabled` matches what your carrier expects (some carriers reject `+`, others require it)

### No audio / call connects but no voice

A common cause is an SRTP mismatch with your carrier. If the trunk has `media_encryption="sdes"` but the carrier has SRTP disabled (or vice versa), the SIP call sets up but the media path never establishes. Either align both sides on SDES, or set `media_encryption="no"` and use UDP/TCP transport. See [SIP Trunk setup](/docs/sip-trunking/byot-setup#prerequisites) for details.

### Audio quality issues / one-way audio

* Ensure `rtp_symmetric` and `force_rport` are both `true` (the defaults)
* Confirm your SIP provider's RTP IP ranges are reachable from `13.200.45.61`
* Verify `allow` includes `ulaw`
* Avoid enabling `direct_media` unless explicitly advised by Bolna support

## Next steps

* [Set up inbound calls](/docs/sip-trunking/byot-inbound-calls) to receive calls on your SIP trunk numbers
* [Batch calling](/docs/guides/outbound/batch-calling) for high-volume outbound campaigns
* [Monitor call status](/docs/guides/post-call/list-phone-call-status) and [call hangup statuses](/docs/guides/post-call/list-phone-call-hangup-status)
