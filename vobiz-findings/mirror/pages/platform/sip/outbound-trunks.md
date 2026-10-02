> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Outbound Trunks - SIP Termination from Your PBX

> Create and manage outbound SIP trunks in the Vobiz Console - IP or credential auth, per-trunk call recording, AI transcription, PII redaction, and webhooks. Walkthrough of the trunk list, trunk details, and Create Outbound Trunk form.

An **Outbound (termination) trunk** lets your PBX, soft‑switch, or AI agent place calls *out* through Vobiz to any phone number in the world. Each trunk gets its own SIP domain, its own auth choice (IP allowlist or username/password), and its own recording/transcription/redaction settings.

```text URL theme={null}
https://console.vobiz.ai/app/sip/out/trunks
```

## The Outbound Trunks list

<Frame caption="Outbound Trunks - list, details, and toggles">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-outbound-trunks_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=891c7d6473f941ac640f62cef5826aee" alt="Outbound Trunks page with a searchable list of trunks (Trunk1, test, PII Test, qwerty) showing ID, SIP Domain, IP ACL, Credentials, and Status, and a Trunk Details panel with Trunk Name, Trunk ID, Status toggle, Call Recording, AI Transcription, PII Redaction, Recording Webhook toggles, SIP Domain field, and a Webhook section" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4408" data-path="images/platform/sip/sip-outbound-trunks_blur.png" />
</Frame>

Three columns:

1. **Search + Create** - `Search trunks…` filter and a **+ Create New Trunk** button.
2. **Trunk list** - each card shows the trunk name, ID, SIP Domain, IP ACL status, attached Credentials, and current Status badge (`Enabled` / `Disabled`).
3. **Trunk Details panel** - the right side updates when you click a card.

## The trunk details panel

| Field | Meaning |
| - | - |
| **Trunk Name** | Friendly label. Edit any time via the pencil icon. |
| **Trunk ID** | Immutable UUID. Use this as `trunk_id` in REST API calls. |
| **Status** | Toggle to enable/disable the trunk without deleting it. A disabled trunk rejects all SIP traffic instantly. |
| **SIP Domain** | The hostname your PBX points its INVITEs at (e.g. `39a32383.sip.vobiz.ai`). One per trunk - never shared. |

### Recording & Transcription toggles

Four togglable features, all per‑trunk:

| Feature | What it does |
| - | - |
| **Call Recording** | Records every call on this trunk to WAV (default) or MP3. Retention is 30 days; export historical recordings via the [Recording API](/docs/recording/export-historical-recordings) for longer storage. |
| **AI Transcription** | Generates speaker‑labelled transcripts plus sentiment scoring. **Requires Call Recording.** |
| **PII Redaction** | Masks names, phone numbers, emails, and other PII in both audio and transcripts. **Requires AI Transcription.** Use **+ Add entity types** to extend the redaction list. |
| **Recording Webhook** | POSTs a notification to a URL when each recording is ready for download. Useful for hooking recordings straight into your storage pipeline. |

### Configuration

The bottom card surfaces the auth wiring at a glance:

* **IP ACL** - name of the IP Access Control List attached (or `Not configured`). See [IP Access Control List](/docs/platform/sip/ip-access-control-list).
* **Credentials** - name of the credential list attached (or `Not configured`). See [Credentials List](/docs/platform/sip/credentials).

### Webhook

A general‑purpose webhook URL Vobiz POSTs call state events to (started, answered, ended). Click **+ Add Webhook** to configure - same payload shape as the [trunk webhook reference](/docs/trunks/webhook).

## Create an Outbound Trunk

Click **+ Create New Trunk** to open the side panel.

<Frame caption="Create Outbound Trunk form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/sip/sip-outbound-trunk-create.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=f25e417b58316c5a102e023610d0b1bf" alt="Create Outbound Trunk side panel with Trunk Name required field, Recording and Transcription section with toggles for Call Recording, Recording Webhook, AI Transcription, and PII Redaction (each with Enable recording first / Enable transcription first prerequisite hints), Authentication and Linking section with Credentials List dropdown and IP Access Control List dropdown plus Create New Credential and Add New IP ACL links, optional Description, and Webhook Configuration with POST method and URL placeholder" style={{maxWidth: '600px', margin: '0 auto', display: 'block'}} width="2000" height="1114" data-path="images/platform/sip/sip-outbound-trunk-create.png" />
</Frame>

| Section | Field | Notes |
| - | - | - |
| **Trunk Name** | Required | A friendly label. |
| **Recording & Transcription** | Call Recording | Master switch. Other recording toggles are greyed until this is on. |
| | Recording Webhook | Notification on each new recording. |
| | AI Transcription | Auto‑transcribe + sentiment. Requires recording. |
| | PII Redaction | Mask PII in audio and transcripts. Requires transcription. |
| **Authentication & Linking** | Credentials List | Pick an existing credential set, or click **+ Create New Credential** to make one inline. |
| | IP Access Control List | Pick an existing ACL, or click **+ Add New IP ACL** to whitelist your PBX IPs. |
| **Description (optional)** | – | Notes for your own team. |
| **Webhook Configuration (optional)** | POST URL | Receive real‑time call events for state changes. |

<Tip>
  Use either Credentials *or* IP ACL - you don't need both. Credentials work from anywhere; IP ACL is faster (no SIP digest round‑trip) but only works from fixed source IPs.
</Tip>

Click **Create Trunk**. Vobiz issues the SIP Domain and you can point your PBX at it immediately.

## Pointing your PBX

Once the trunk is created:

```text theme={null}
SIP Server / Domain:  <trunk-id>.sip.vobiz.ai
Port:                 5060 (UDP) or 5061 (TLS)
Username:             <credential username>      (credential auth)
Password:             <credential password>      (credential auth)
```

For IP auth: just dial out from the whitelisted source IP - no SIP REGISTER required.

## Edit, disable, delete

Top‑right of the details panel:

* **✏ Edit** - opens the form for changing any field except the Trunk ID.
* **Status toggle** - disable without deleting; calls are rejected instantly.
* **🗑 Delete** - permanently removes the trunk. Active calls drop.

## Tips

* **One trunk per environment.** Keep prod, staging, and dev on separate trunks so a misconfigured stage trunk can't bleed into prod metrics.
* **Recording + transcription has a billing impact.** It's worth it for AI agent flows, but expensive at carrier‑grade volumes - see the [Cost Calculator](/docs/resources/calculator).
* **Webhook over polling.** The trunk webhook is the cheapest way to know when a recording is ready - beats polling `GET /recordings`.

## What's next

<CardGroup cols={2}>
  <Card title="IP Access Control List" icon="shield-halved" href="/docs/platform/sip/ip-access-control-list">
    Whitelist your PBX's source IPs.
  </Card>

  <Card title="Credentials List" icon="key" href="/docs/platform/sip/credentials">
    Set up SIP usernames and passwords.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.