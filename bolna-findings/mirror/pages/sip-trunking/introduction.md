> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bring Your Own SIP Trunk to Bolna Voice AI

> Connect your own SIP trunk to Bolna and use your existing telephony relationships and phone numbers for AI-powered inbound and outbound voice calls.

## What is Bring Your Own Telephony (BYOT)?

Bring Your Own Telephony (BYOT) lets you connect any standards-compliant SIP trunk to the Bolna platform. Instead of using Bolna's built-in telephony providers (Twilio, Plivo, etc.), you can use your existing SIP trunk provider, your own phone numbers, and your own calling rates.

Once connected, Bolna can:

* **Receive inbound calls** on your DID numbers and route them to AI agents
* **Place outbound calls** from your DID numbers using your trunk's minutes and rates

Learn more about [supported telephony providers](/docs/supported-telephony-providers).

## How to get started with your SIP Trunk

<CardGroup cols={2}>
  <Card title="Set up your SIP trunk" icon="server" href="/docs/sip-trunking/byot-setup">
    Configure your SIP provider and create a trunk on Bolna
  </Card>

  <Card title="Make outbound calls" icon="phone-arrow-up-right" href="/docs/sip-trunking/byot-outbound-calls">
    Place outbound calls through your SIP trunk
  </Card>

  <Card title="Receive inbound calls" icon="phone-arrow-down-left" href="/docs/sip-trunking/byot-inbound-calls">
    Route incoming calls to your Bolna AI agents
  </Card>

  <Card title="SIP Trunk API Reference" icon="code" href="/docs/api-reference/sip-trunks/overview">
    Full API reference for managing SIP trunks
  </Card>
</CardGroup>

## Supported authentication methods

| Method     | How it works                                                                                                                      |
| ---------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `userpass` | Bolna authenticates to your SIP trunk using a username and password (SIP REGISTER or INVITE auth).                                |
| `ip-based` | Your SIP trunk identifies Bolna by source IP address; no username/password required. You must whitelist Bolna's IP on your trunk. |

## Why bring your own SIP trunk?

* **Use existing relationships**: Keep your current SIP provider and phone numbers
* **Cost control**: Use your own negotiated rates and minutes
* **Provider flexibility**: Works with any standards-compliant SIP trunk (Twilio Elastic SIP, Plivo, Zadarma, Telnyx, Vonage, DIDWW, and more)
* **Number portability**: No need to port numbers to a new provider

<Note>
  **Media encryption (SRTP via SDES) is supported on TLS trunks.** By default, BYOT trunks use plain RTP and that works on every transport. To turn on SDES, set the transport to TLS and `media_encryption` to `sdes` -- see [SIP Trunk setup](/docs/sip-trunking/byot-setup#prerequisites) for details. Your carrier must also be configured for SRTP.
</Note>

## Next steps

Ready to connect your SIP trunk? Start with the [setup guide](/docs/sip-trunking/byot-setup) to configure your provider and create a trunk on Bolna.
