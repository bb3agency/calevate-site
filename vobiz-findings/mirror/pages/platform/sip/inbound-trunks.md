> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Inbound Trunks - Receive PSTN Calls

> Create and manage inbound (origination) SIP trunks in the Vobiz Console - deliver incoming calls to your PBX or AI agent via a Primary URI, with per-trunk recording, AI transcription, PII redaction, and webhooks.

An **Inbound (origination) trunk** is the path Vobiz uses to deliver incoming PSTN calls to *your* SIP endpoint - typically a PBX, soft‑switch, or AI agent. Each trunk has its own Primary URI (the destination Vobiz forwards to), its own recording settings, and its own webhook.

```text URL theme={null}
https://console.vobiz.ai/app/sip/in/trunks
```

## The Inbound Trunks list

<Frame caption="Inbound Trunks - list, details, and toggles">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-inbound-trunks_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=e2cd04493ccabd8521b6dc12f5c77268" alt="Inbound Trunks page with a searchable list of trunks (qwertyu, piyush video sdk, vapi new kush, inbound, vobiz inbound) showing ID, Primary URI, Status Enabled, and a Trunk Details panel on the right with Trunk Name (qwertyu), Trunk ID UUID, Status toggle on, Call Recording on, AI Transcription on, PII Redaction off, Recording Webhook off, a Webhook section with POST URL, and a URI Configuration section showing Primary URI (qwerty.asfg.com)" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4404" data-path="images/platform/sip/sip-inbound-trunks_blur.png" />
</Frame>

Same three‑column layout as outbound trunks - search + create on top, list on the left, details on the right.

## The trunk details panel

| Field | Meaning |
| - | - |
| **Trunk Name** | Friendly label. |
| **Trunk ID** | Immutable UUID - quote in support tickets. |
| **Status** | Toggle to enable/disable. A disabled trunk doesn't receive inbound calls - Vobiz returns a SIP error to the carrier. |
| **Primary URI** | The SIP URI Vobiz forwards inbound calls to (e.g. `qwerty.asfg.com`). One [Origination URI](/docs/platform/sip/origination-uri) per trunk. |

### Recording & Transcription toggles

Identical to [outbound trunks](/docs/platform/sip/outbound-trunks#recording--transcription-toggles): **Call Recording**, **AI Transcription**, **PII Redaction**, **Recording Webhook**. Each obeys the same prerequisite chain - transcription needs recording, redaction needs transcription.

### Webhook

A general‑purpose webhook URL Vobiz POSTs inbound‑call events to (`incoming.ringing`, `incoming.answered`, `incoming.ended`). Use it to track who's calling, drive a live CRM update, or log to your data warehouse.

### URI Configuration

| Field | Meaning |
| - | - |
| **Primary URI** | The SIP destination. Vobiz forwards inbound INVITEs to this URI. Manage the list of available URIs from [Origination URI](/docs/platform/sip/origination-uri). |

Click the copy icon (⧉) next to the URI to copy it to your clipboard.

### Linked Numbers

Below the URI Configuration card, the **Linked Numbers (N)** section lists every DID currently routing to this trunk. Click **Link Numbers** in the top‑right of the section to attach more numbers or detach existing ones.

## Create an Inbound Trunk

Click **+ Create New Trunk** to open the side panel.

<Frame caption="Create Inbound Trunk form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-inbound-trunk-create_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=c3494593afb411b50754eeb0e8c65265" alt="Create Inbound Trunk side panel with Trunk Name required field, Recording and Transcription section with toggles for Call Recording, Recording Webhook, AI Transcription, and PII Redaction (each with Enable recording first or Enable transcription first prerequisite hints), Primary URI (optional) dropdown with Select Primary URI and an Add New URI link, and a Webhook Configuration Optional section with POST method dropdown and URL placeholder https://your-domain.com/webhook/calls plus the hint Receive real-time call events via HTTP to this endpoint" style={{maxWidth: '600px', margin: '0 auto', display: 'block'}} width="3280" height="3096" data-path="images/platform/sip/sip-inbound-trunk-create_blur.png" />
</Frame>

| Section | Field | Notes |
| - | - | - |
| **Trunk Name** | Required | A friendly label. |
| **Recording & Transcription** | Same four toggles as the trunk details panel. | – |
| **Primary URI (optional)** | Select Primary URI | Pick from existing [Origination URIs](/docs/platform/sip/origination-uri), or click **+ Add New URI** to create one inline. |
| **Webhook Configuration (Optional)** | POST URL | Receive inbound call state events. |

Click **Create Trunk**.

## Linking numbers

After the trunk exists:

1. Open the trunk details.
2. Scroll to **Linked Numbers** and click **Link Numbers**.
3. Pick existing numbers from your account or buy new ones inline - same flow as the [Voice Applications attach‑number modal](/docs/platform/voice/applications#attach-phone-numbers).

From the moment a number is linked, every call to that number forwards to the trunk's Primary URI.

## Tips

* **Use Origination URIs as named destinations.** Even if you only have one PBX, give the URI a name like `primary-pbx-mumbai` - it's clearer than a raw `1.2.3.4:5060`.
* **Webhook before recording.** If you only want call state for analytics, the webhook is enough - no need to enable recording.
* **Status toggle for maintenance windows.** Disable the trunk to fail‑fast on inbound (carrier returns "all circuits busy") instead of timing out on a dead PBX.

## What's next

<CardGroup cols={2}>
  <Card title="Origination URI" icon="route" href="/docs/platform/sip/origination-uri">
    Add or edit the SIP destinations Vobiz forwards to.
  </Card>

  <Card title="Phone Numbers" icon="phone" href="/docs/account-phone-number/list-account-phone-numbers">
    Buy or port the DIDs that ring this trunk.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.