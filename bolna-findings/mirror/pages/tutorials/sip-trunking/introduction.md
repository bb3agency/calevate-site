> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP Trunking for Voice AI on Bolna

> Learn what SIP trunking is, how it works, the benefits it offers, and how Bolna enables you to bring your own SIP trunk for AI-powered voice calls.

## What is a SIP Trunk?

A **SIP trunk** (Session Initiation Protocol trunk) is a virtual phone line that connects your phone system to the public telephone network (PSTN) over the internet. Instead of physical copper wires, voice calls are transmitted as data packets over your existing internet connection.

| Traditional Phone Line               | SIP Trunk                         |
| ------------------------------------ | --------------------------------- |
| Physical copper wires                | Virtual connection over internet  |
| Fixed capacity (23 channels per PRI) | Scalable on demand                |
| Local provider lock-in               | Provider-agnostic, works globally |
| High fixed monthly costs             | Pay-per-use or wholesale rates    |

<Tip>
  Just like email replaced physical mail for messages, SIP trunking replaces physical phone lines for calls. The calls sound the same to the person on the other end.
</Tip>

***

## How Does SIP Trunking Work?

Two protocols work together: **SIP** handles the signaling (setting up and tearing down calls), and **RTP** carries the actual voice audio.

### The Call Flow

<Steps>
  <Step title="Call Initiation">
    A **SIP INVITE** is sent to the provider's gateway with the destination number and codec preferences (e.g., G.711 ulaw).
  </Step>

  <Step title="Authentication and Routing">
    The provider verifies the request via **IP-based auth** or **username/password** (digest auth), then routes the call to the PSTN.
  </Step>

  <Step title="Media Negotiation (SDP)">
    Both sides exchange **SDP** messages to agree on audio codecs, IP addresses, and ports for the voice stream.
  </Step>

  <Step title="Voice Streaming (RTP)">
    Voice audio flows as **RTP packets** between the endpoints, encoded using the agreed codec (typically G.711 ulaw at 64 kbps).
  </Step>

  <Step title="Call Termination">
    When either party hangs up, a **SIP BYE** message closes the session and stops the audio stream.
  </Step>
</Steps>

### Key Terms

| Term            | Meaning                                                                  |
| --------------- | ------------------------------------------------------------------------ |
| **Origination** | Receiving inbound calls from the PSTN and delivering them to your system |
| **Termination** | Sending outbound calls from your system to the PSTN via the trunk        |
| **DID Number**  | A phone number assigned to your trunk that external callers can dial     |
| **Gateway**     | The provider's server address where SIP traffic is sent                  |
| **Codec**       | Audio encoding format (G.711 ulaw is the standard)                       |

***

## How Bolna Accommodates SIP Trunking

Bolna's **Bring Your Own Telephony (BYOT)** feature lets you connect any standards-compliant SIP trunk. Bolna runs an **Asterisk-based SIP media server** with the **PJSIP** channel driver.

When you register your trunk:

1. **Bolna creates a SIP endpoint** with your gateway address, authentication details, and codec preferences
2. **Inbound calls** arrive at Bolna's server (`sip:13.200.45.61:5060`), get matched to a registered DID, and route to the assigned AI agent
3. **Outbound calls** are sent through your trunk's gateway using your credentials and caller ID
4. **The AI agent** handles the conversation in real-time (speech-to-text, LLM response, text-to-speech)

### Supported Authentication

| Method                             | How It Works                                 | Best For               |
| ---------------------------------- | -------------------------------------------- | ---------------------- |
| **Username/Password** (`userpass`) | SIP digest auth with username and password   | Zadarma, Vonage, DIDWW |
| **IP-Based** (`ip-based`)          | Bolna identified by source IP `13.200.45.61` | Plivo Zentrunk, Telnyx |

***

## Benefits of Using a SIP Trunk with Bolna

<AccordionGroup>
  <Accordion title="Use Your Existing Telephony Relationships">
    Keep your current SIP provider, contracts, and phone numbers. Connect your trunk to Bolna and your AI agents are ready instantly.
  </Accordion>

  <Accordion title="Full Cost Control">
    Pay your SIP provider directly for call minutes at your own negotiated rates. Bolna charges separately only for AI processing.
  </Accordion>

  <Accordion title="Number Portability Without Migration">
    Your DID numbers stay with your current provider. No porting, no downtime. Just point them to Bolna's SIP server.
  </Accordion>

  <Accordion title="Provider Flexibility and Redundancy">
    Switch providers without changing anything on Bolna. Configure multiple trunks from different providers for failover.
  </Accordion>

  <Accordion title="Global Coverage with Local Numbers">
    Bring US toll-free, Indian DIDs, European local numbers, or any numbers from your provider's inventory.
  </Accordion>

  <Accordion title="Compliance and Regulatory Control">
    Your existing compliance setup (DLT registration, STIR/SHAKEN) stays with your provider. Bolna does not interfere.
  </Accordion>

  <Accordion title="Elastic Scalability">
    Scale from 1 concurrent call to thousands without hardware changes. Bolna scales alongside your trunk capacity.
  </Accordion>
</AccordionGroup>

<Warning>
  **SRTP (Secure RTP) is not supported.** Media must use standard (unencrypted) RTP. Trunks requiring mandatory SRTP will not work with Bolna.
</Warning>

***

## Get Started

Follow these guides in order to set up SIP trunking with Bolna:

<CardGroup cols={2}>
  <Card title="Set Up a Plivo Trunk" icon="server" href="/docs/tutorials/sip-trunking/plivo-trunk-setup">
    Create inbound and outbound SIP trunks on Plivo Zentrunk
  </Card>

  <Card title="Set Up a Twilio Trunk" icon="server" href="/docs/tutorials/sip-trunking/twilio-trunk-setup">
    Create an Elastic SIP Trunk on Twilio
  </Card>

  <Card title="Register Trunk on Bolna" icon="plug" href="/docs/tutorials/sip-trunking/register-trunk-on-bolna">
    Register your trunk and add phone numbers via API
  </Card>

  <Card title="Receive Inbound Calls" icon="phone-arrow-down-left" href="/docs/tutorials/sip-trunking/inbound-calls">
    Route incoming calls to Bolna AI agents
  </Card>

  <Card title="Make Outbound Calls" icon="phone-arrow-up-right" href="/docs/tutorials/sip-trunking/outbound-calls">
    Place outbound calls from your trunk numbers
  </Card>

  <Card title="SIP Trunk API Reference" icon="code" href="/docs/api-reference/sip-trunks/overview">
    Full API reference for managing trunks and numbers
  </Card>
</CardGroup>
