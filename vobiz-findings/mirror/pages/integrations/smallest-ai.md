> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Smallest AI Integration

> Connect a Smallest AI voice agent to Vobiz SIP trunking - import a Vobiz number over SIP for outbound calls and route inbound calls to your agent, including India and 130+ countries.

[Smallest AI](https://smallest.ai) builds real-time voice agents. Its **SIP Trunking** option lets you import a phone number you already own, so you can run a Smallest AI agent on a Vobiz number anywhere Vobiz operates.

<iframe width="100%" height="420" src="https://www.youtube.com/embed/M2ztN2Z82Cw" title="Smallest AI + Vobiz Integration" frameBorder="0" allow="accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture" allowFullScreen style={{ borderRadius: "12px", marginTop: "1rem", marginBottom: "1rem" }} />

## What you'll build

A two-way setup on a single Vobiz number:

* **Outbound** - the Smallest AI agent places calls through your Vobiz outbound trunk.
* **Inbound** - calls to your Vobiz number route through an inbound trunk to the Smallest AI agent.

Each direction uses its own trunk, so configure both.

## Architecture

```text theme={null}
Outbound   Smallest AI agent → Vobiz outbound trunk (SIP digest auth) → PSTN
Inbound    Caller → Vobiz number → Vobiz inbound trunk → Smallest AI origination URL
```

## Prerequisites

* **Smallest AI account** → [Smallest AI dashboard](https://app.smallest.ai/dashboard/phone-numbers)
* **Vobiz account** → [Vobiz Console](https://console.vobiz.ai)
* **A Vobiz phone number** → see [Buy a phone number](/docs/buy-a-phone-number)

## Part 1: Outbound calls

### Step 1: Create a SIP credential in Vobiz

Smallest AI is cloud-hosted and calls out from addresses you cannot pin down in advance, so authenticate the trunk with a username and password rather than an IP allow-list.

Go to [Credentials List](https://console.vobiz.ai/app/sip/out/credentials) and click **+ Add Credential**. Note the username and password - Vobiz stores the password hashed and does not display it again after creation.

See [Credentials List](/docs/platform/sip/credentials) for the full walkthrough.

### Step 2: Create the outbound trunk

Go to [Outbound Trunks](https://console.vobiz.ai/app/sip/out/trunks) and click **+ Create New Trunk**. Attach the credential from Step 1 under **Credentials**.

<Frame>
  <img src="https://mintcdn.com/vobizai/I0vxbXdrjw6v0FV3/images/smallest-ai/vobiz-outbound-trunk.png?fit=max&auto=format&n=I0vxbXdrjw6v0FV3&q=85&s=5178e9c5524dfe48c34c4cc75ed51db2" alt="Vobiz outbound trunk detail showing the SIP domain and an attached credentials list" width="1524" height="1568" data-path="images/smallest-ai/vobiz-outbound-trunk.png" />
</Frame>

<Warning>
  Attach the credential to the trunk. Without either a credential or an IP ACL, the trunk has no way to authenticate traffic from Smallest AI.
</Warning>

### Step 3: Copy the SIP domain

The trunk details panel shows a **SIP Domain** in the form `<trunk-id>.sip.vobiz.ai`. Copy it - this is the SIP termination URL that Smallest AI sends outbound calls to. Each trunk gets its own domain and it is never shared.

### Step 4: Import the number in Smallest AI

In the Smallest AI dashboard, open [Phone Numbers](https://app.smallest.ai/dashboard/phone-numbers), choose **Add phone number**, and select the **SIP Trunking** method rather than **Rent a number**.

<Frame>
  <img src="https://mintcdn.com/vobizai/I0vxbXdrjw6v0FV3/images/smallest-ai/smallest-ai-import-sip-number.png?fit=max&auto=format&n=I0vxbXdrjw6v0FV3&q=85&s=7a5053c8474785235dedfcc4fb12ca07" alt="Smallest AI Import SIP number dialog with fields for phone number, SIP termination URL, SIP authentication details, and SIP origination URL" width="1830" height="1252" data-path="images/smallest-ai/smallest-ai-import-sip-number.png" />
</Frame>

| Field | Value |
| - | - |
| Phone number | Your Vobiz number, with the country code selected |
| Friendly name | Optional label |
| SIP termination URL | The Vobiz **SIP Domain** from Step 3, for example `a2dea0d3.sip.vobiz.ai` |
| SIP authentication username | The credential username from Step 1 |
| SIP authentication password | The credential password from Step 1 |

Although Smallest AI marks the authentication fields optional, this setup needs them - they are what the Vobiz trunk checks.

Click **Import number**. Outbound is now wired.

## Part 2: Inbound calls

### Step 5: Copy the SIP origination URL

The same Smallest AI dialog shows a read-only **SIP origination URL**, for example `sip:5rdbhjuwtlk.sip.livekit.cloud`. Copy it with the icon on the right.

### Step 6: Create the origination URI in Vobiz

Go to [Origination URIs](https://console.vobiz.ai/app/sip/in/uri) and create a URI pointing at the Smallest AI address.

<Frame>
  <img src="https://mintcdn.com/vobizai/I0vxbXdrjw6v0FV3/images/smallest-ai/vobiz-create-origination-uri.png?fit=max&auto=format&n=I0vxbXdrjw6v0FV3&q=85&s=a8c27f52facc4674dcbb5ed24f4b2e90" alt="Vobiz Create Origination URI dialog with the Smallest AI SIP address and UDP transport selected" width="1656" height="1556" data-path="images/smallest-ai/vobiz-create-origination-uri.png" />
</Frame>

<Warning>
  **Remove the `sip:` prefix.** Smallest AI presents the value as `sip:5rdbhjuwtlk.sip.livekit.cloud`, and the Vobiz URI field takes `domain` or `domain:port`. Paste `5rdbhjuwtlk.sip.livekit.cloud` instead.
</Warning>

| Field | Value |
| - | - |
| URI | The origination URL with `sip:` removed |
| Description | Optional, for example `Smallest AI agent` |
| Transport | **UDP** |
| Active | On |

### Step 7: Create the inbound trunk

Go to [Inbound Trunks](https://console.vobiz.ai/app/sip/in/trunks) and create a trunk with the origination URI from Step 6 as its **Primary URI**.

<Frame>
  <img src="https://mintcdn.com/vobizai/I0vxbXdrjw6v0FV3/images/smallest-ai/vobiz-inbound-trunk.png?fit=max&auto=format&n=I0vxbXdrjw6v0FV3&q=85&s=a37684ed7ca1e5fd18094e86f1ab283b" alt="Vobiz inbound trunk detail showing the primary URI configuration and an empty linked numbers list" width="1504" height="1546" data-path="images/smallest-ai/vobiz-inbound-trunk.png" />
</Frame>

Recording, transcription, and webhooks are available on this screen and are all optional. See [Callbacks](/docs/concepts/callbacks) for the webhook payloads.

### Step 8: Link the number to the trunk

A new trunk starts with **Linked Numbers (0)**. Click **Link Numbers**, select your Vobiz number, and confirm.

<Frame>
  <img src="https://mintcdn.com/vobizai/I0vxbXdrjw6v0FV3/images/smallest-ai/vobiz-link-number.png?fit=max&auto=format&n=I0vxbXdrjw6v0FV3&q=85&s=cffa313dde06862e9e3ad6cbe6b4b1f0" alt="Vobiz inbound trunk showing one linked phone number under the primary URI configuration" width="1472" height="668" data-path="images/smallest-ai/vobiz-link-number.png" />
</Frame>

The count updates to **Linked Numbers (1)** and inbound routing is live.

## Test the integration

* **Inbound** - call your Vobiz number. The Smallest AI agent should answer.
* **Outbound** - trigger a call from Smallest AI to your own phone.

Check [Call Logs](https://console.vobiz.ai/app/sip/logs) in the Vobiz Console to see both legs.

## Troubleshooting

### Outbound calls are rejected with a 401 or 403

The trunk is not accepting the credentials. Confirm the username and password in Smallest AI match the Vobiz credential exactly, and that the credential is attached to the outbound trunk and set to **Active**.

### Outbound calls do not reach Vobiz

Check the SIP termination URL is the trunk's own SIP domain, in the form `<trunk-id>.sip.vobiz.ai`. Each trunk has a distinct domain.

### The origination URI is rejected when saving

Remove the `sip:` prefix. The field takes `domain` or `domain:port`.

### Inbound calls ring but never reach the agent

Open the inbound trunk and confirm the number appears under **Linked Numbers** and the trunk **Status** is Enabled.

## Next steps

<Columns cols={2}>
  <Card title="Outbound Trunks" icon="arrow-up-right-from-square" href="/docs/platform/sip/outbound-trunks">
    Trunk settings, recording, and webhooks
  </Card>

  <Card title="Credentials List" icon="key" href="/docs/platform/sip/credentials">
    Create and rotate SIP credentials
  </Card>

  <Card title="Inbound Trunks" icon="arrow-down-to-bracket" href="/docs/platform/sip/inbound-trunks">
    Route inbound calls to your agent
  </Card>

  <Card title="IP Whitelisting" icon="shield" href="/docs/concepts/ip-whitelisting">
    Vobiz SIP signaling and RTP ranges
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.