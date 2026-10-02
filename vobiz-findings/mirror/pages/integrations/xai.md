> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# xAI Grok Voice Integration

> Connect a Vobiz phone number to an xAI Grok voice agent over Direct SIP with TLS - bring your own number in regions where xAI does not provision numbers, including India.

[xAI](https://x.ai) voice agents answer calls over SIP. Its **Direct SIP** option lets you attach a phone number you already own, so you can put a Grok agent on a Vobiz number in any region Vobiz serves - including India, where xAI does not provision numbers itself.

## What you'll build

An inbound calling setup where someone dials your Vobiz number, Vobiz routes the call over TLS to xAI's SIP endpoint, and the Grok agent handles the conversation.

## Architecture

```text theme={null}
Caller → Vobiz number → Vobiz inbound trunk → sip.voice.x.ai (TLS) → xAI Grok agent
```

## Prerequisites

* **xAI account** with a voice agent → [xAI console](https://console.x.ai)
* **Vobiz account** → [Vobiz Console](https://console.vobiz.ai)
* **A Vobiz phone number** you want the agent to answer on

## Step 1: Add the number in xAI

In the xAI console, open your agent and add a new phone number. Select the **Direct SIP** tab rather than Twilio.

<Frame>
  <img src="https://mintcdn.com/vobizai/ftLRYaD1FRuB0E7n/images/xai/xai-direct-sip-number.png?fit=max&auto=format&n=ftLRYaD1FRuB0E7n&q=85&s=9d2d4771946d16f0359e91526a0e124d" alt="xAI New phone number dialog with the Direct SIP tab selected, showing the SIP URI and allowed addresses fields" width="1214" height="1336" data-path="images/xai/xai-direct-sip-number.png" />
</Frame>

Fill in the fields:

| Field | Value |
| - | - |
| Name | Any label that identifies this number |
| Phone number | Your Vobiz number in E.164 format, for example `+91XXXXXXXXXX` |
| SIP URI | `sip:{number}@sip.voice.x.ai;transport=tls` |
| Allowed addresses | The Vobiz SIP signaling IPs - see below |

The SIP URI field shows `{number}` as a template. xAI resolves it to the number you entered, so the address Vobiz sends to becomes `+91XXXXXXXXXX@sip.voice.x.ai`.

<Warning>
  Keep `transport=tls` in the SIP URI. The origination URI you create in Step 2 must use the same transport, or the call will not connect.
</Warning>

### Allowed addresses

**Allowed addresses** controls which hosts xAI accepts SIP traffic from. Add the Vobiz SIP signaling IPs so calls from your trunk are accepted:

```text theme={null}
13.203.7.132
65.2.100.211
13.126.98.234
13.235.11.131
13.233.44.61
3.111.255.163
3.111.128.110
43.204.64.203
15.207.232.91
35.154.133.28
```

These are the India signaling IPs. For the full list including RTP media ranges, and for other regions, see [IP Whitelisting](/docs/concepts/ip-whitelisting).

## Step 2: Create the origination URI in Vobiz

An origination URI is the SIP destination Vobiz routes inbound calls to. Navigate to [Origination URIs](https://console.vobiz.ai/app/sip/in/uri) and create one pointing at xAI.

<Frame>
  <img src="https://mintcdn.com/vobizai/ftLRYaD1FRuB0E7n/images/xai/vobiz-create-origination-uri.png?fit=max&auto=format&n=ftLRYaD1FRuB0E7n&q=85&s=3582bbe933eb533435b51f308eb5da84" alt="Vobiz Create Origination URI dialog with the xAI SIP address and TLS transport selected" width="1646" height="1554" data-path="images/xai/vobiz-create-origination-uri.png" />
</Frame>

| Field | Value |
| - | - |
| URI | `+91XXXXXXXXXX@sip.voice.x.ai` - your number, then the xAI SIP domain |
| Description | Optional, for example `xAI Grok agent` |
| Transport | **TLS** |
| Active | On |

<Note>
  Use the same number here that you entered in xAI. The URI is what xAI matches the incoming call against.
</Note>

## Step 3: Create the inbound trunk

Navigate to [Inbound Trunks](https://console.vobiz.ai/app/sip/in/trunks) and create a trunk that uses the origination URI from Step 2.

<Frame>
  <img src="https://mintcdn.com/vobizai/ftLRYaD1FRuB0E7n/images/xai/vobiz-create-inbound-trunk.png?fit=max&auto=format&n=ftLRYaD1FRuB0E7n&q=85&s=28b1fc62a29f4128be446db0339113ab" alt="Vobiz Create Inbound Trunk dialog with a trunk name and the xAI origination URI selected as the primary URI" width="1654" height="1554" data-path="images/xai/vobiz-create-inbound-trunk.png" />
</Frame>

| Field | Value |
| - | - |
| Trunk Name | Any label, for example `xAI` |
| Primary URI | Select the origination URI you created in Step 2 |

Two optional sections are available on the same screen:

* **Recording & transcription** - turn on call recording for this trunk, then optionally add a recording webhook, AI transcription, and PII redaction. Each depends on the one above it.
* **Webhook configuration** - set a URL to receive real-time call events over HTTP. See [Callbacks](/docs/concepts/callbacks) for the event payloads.

## Step 4: Link the number to the trunk

Open the trunk you just created and link your Vobiz number to it under **Linked Numbers**.

<Frame>
  <img src="https://mintcdn.com/vobizai/ftLRYaD1FRuB0E7n/images/xai/vobiz-trunk-linked-numbers.png?fit=max&auto=format&n=ftLRYaD1FRuB0E7n&q=85&s=0fe6393d9b1a6a4add65812f1c2eeeb0" alt="Vobiz inbound trunk detail showing the primary URI configuration and a linked phone number" width="1470" height="1538" data-path="images/xai/vobiz-trunk-linked-numbers.png" />
</Frame>

Click **Link Numbers**, select your number, and confirm. The trunk detail view then shows the number under **Linked Numbers (1)**, and the trunk status reads **Enabled**.

At this point the route is complete: the number is linked to the trunk, the trunk points at the origination URI, and the origination URI points at xAI.

## Step 5: Test the integration

Call your Vobiz number from any phone. The Grok agent should answer and begin the conversation.

## Troubleshooting

### The call rings but the agent never answers

Check that the number in the Vobiz origination URI exactly matches the number configured in xAI, including the `+` and country code.

### The call fails immediately

Confirm the transport is TLS in both places - `transport=tls` in the xAI SIP URI and **TLS** on the Vobiz origination URI.

### Calls are rejected by xAI

Verify the Vobiz SIP signaling IPs are present in the **Allowed addresses** list on the xAI number. See [IP Whitelisting](/docs/concepts/ip-whitelisting) for the current list.

### The number is not reachable at all

Open the trunk and confirm **Status** is Enabled and the number appears under **Linked Numbers**.

## Next steps

<Columns cols={2}>
  <Card title="IP Whitelisting" icon="shield" href="/docs/concepts/ip-whitelisting">
    Full SIP signaling and RTP media IP ranges
  </Card>

  <Card title="Callbacks" icon="webhook" href="/docs/concepts/callbacks">
    Receive call events on your own endpoint
  </Card>

  <Card title="Call Recording" icon="microphone" href="/docs/recording">
    Record, retrieve, and download calls on this trunk
  </Card>

  <Card title="SIP Trunking" icon="network-wired" href="/docs/concepts/sip-trunking">
    How Vobiz trunks route calls
  </Card>
</Columns>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.