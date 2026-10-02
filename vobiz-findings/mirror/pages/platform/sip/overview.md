> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP Trunking Overview - Global Voice Connectivity

> The SIP Trunking hub in the Vobiz Console - usage tiles, outbound termination, inbound origination, and end-to-end how-it-works diagrams. Configure your PBX, AI agent, or VoIP stack to place and receive calls in 130+ countries.

The **SIP Trunking** section of the Vobiz Console is where you wire your PBX, AI agent, or VoIP stack to the Vobiz global voice network - outbound termination to any number worldwide, inbound origination to your phone numbers, with per‑trunk recording, transcription, PII redaction, and webhooks.

```text URL theme={null}
https://console.vobiz.ai/app/sip
```

<Frame caption="SIP Trunking Overview - usage tiles plus outbound and inbound how-it-works">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-overview.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=292eabee00d868988c6b2e0e2cd0fe40" alt="SIP Trunking Overview page with the SIP TRUNK left sidebar (Overview, Outbound Trunks with Trunks 24/IP Access Control List 1/Credentials List 25, Inbound Trunks with Trunks 22/Origination URI 28, Logs with Call Logs 15/Recordings 610), KPI tiles showing Total Calls 15 (27% In, 73% Out), Minutes 7m, Call Quality 4.3 Avg MOS Score, Spend ₹11, and two how-it-works panels for Outbound Calling (Your PBX → VOBIZ → Recipient) and Inbound Calling (PSTN → VOBIZ → Agent)" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="2000" height="1114" data-path="images/platform/sip/sip-overview.png" />
</Frame>

## The SIP Trunking sidebar

The left navigation mirrors the SIP Trunk console exactly. Each item links to its dedicated walkthrough:

| Group | Page | What you do there |
| - | - | - |
| – | **[Overview](/docs/platform/sip/overview)** | You're here - usage tiles and how‑it‑works. |
| **Outbound Trunks** | **[Trunks](/docs/platform/sip/outbound-trunks)** | Outbound termination trunks - point your PBX to Vobiz to place calls. |
| | **[IP Access Control List](/docs/platform/sip/ip-access-control-list)** | Whitelist your PBX's source IPs for IP‑based auth. |
| | **[Credentials List](/docs/platform/sip/credentials)** | SIP usernames + passwords for credential‑based auth. |
| **Inbound Trunks** | **[Trunks](/docs/platform/sip/inbound-trunks)** | Origination trunks - Vobiz delivers inbound calls to your destination. |
| | **[Origination URI](/docs/platform/sip/origination-uri)** | The SIP URI Vobiz forwards inbound calls to. |
| **Logs** | **[Call Logs](/docs/platform/sip/call-logs)** | Per‑call records with MOS, quality, recording, and AI transcription. |
| | **[Recordings](/docs/platform/sip/recordings)** | Stored WAV / MP3 audio for the last 30 days. |

## Usage tiles

Four KPI tiles summarising SIP‑only traffic for the selected [date range](/docs/platform/dashboard#top-bar):

| Tile | What it measures |
| - | - |
| **Total Calls** | Every SIP attempt. Split by `% In / % Out` shows the inbound / outbound mix. |
| **Minutes** | Sum of billable talk time. The `% In · % Out` line breaks down direction. |
| **Call Quality** | Average MOS (Mean Opinion Score) across the period. 4.0+ is good, 3.5–4.0 acceptable. |
| **Spend** | INR spent on SIP traffic only (excludes Voice API). |

## Outbound Calling (Termination)

The right‑side "How it works" panel walks the path **Your PBX → Vobiz Global Gateway → Recipient (mobile / fixed line)**.

| Step | What to do |
| - | - |
| **1. Create an Outbound trunk** | Set up the trunk with **IP** or **Credential** auth. See [Outbound Trunks](/docs/platform/sip/outbound-trunks). |
| **2. Configure PBX** | Point your SIP infrastructure at the trunk's `SIP Domain` (e.g. `<trunk-id>.sip.vobiz.ai`). |
| **3. Start Calling** | Place calls to any number worldwide at Vobiz rates. |

Click **Create New SIP Trunk** in the top‑right of the overview, or **Click here to create new outbound trunk** at the bottom of the Outbound panel.

## Inbound Calling (Origination)

The left‑side panel walks the path **PSTN Global Network → Vobiz Global Gateway → your Agent / PBX / soft‑switch**.

| Step | What to do |
| - | - |
| **1. Create an Inbound trunk** | Define where Vobiz should deliver your incoming calls. See [Inbound Trunks](/docs/platform/sip/inbound-trunks). |
| **2. Link Number** | Purchase or port phone numbers and map them to the trunk. |
| **3. Receive calls** | Vobiz forwards inbound calls to your [Origination URI](/docs/platform/sip/origination-uri). |

## View Auth ID & Token

The **View Auth ID & Token** button (top‑right) reveals your API credentials in a modal - same values as the [main Dashboard](/docs/platform/dashboard#api-credentials), surfaced here for convenience when scripting SIP trunk provisioning via the [Trunks API](/docs/trunks).

<Warning>
  The Auth Token grants full API access. Treat it like a password - never paste it into client‑side code or public repos.
</Warning>

## What's next

<CardGroup cols={2}>
  <Card title="Create an Outbound Trunk" icon="arrow-up-right-from-square" href="/docs/platform/sip/outbound-trunks">
    Connect your PBX to place calls worldwide.
  </Card>

  <Card title="Create an Inbound Trunk" icon="arrow-down-to-bracket" href="/docs/platform/sip/inbound-trunks">
    Receive PSTN calls to your numbers.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.