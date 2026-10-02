> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Campaign Agents - Reusable Webhook Configs

> Create reusable Campaign Agents in the Vobiz Console - shared answer/hangup webhook configurations used by one or more outbound campaigns. Walkthrough of the agents list, the New Agent form, and Static SIP Headers.

A **Campaign Agent** is a reusable bundle of webhook configuration - the Answer URL, the Hangup URL, and any static SIP headers - that one or more campaigns share. Create the agent once and you can launch a hundred campaigns against it without re‑typing those URLs.

```text URL theme={null}
https://console.vobiz.ai/app/campaigns/agents
```

## The Agents list

<Frame caption="Campaigns - Campaign Agents">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/campaign/campaign-agents_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=eac2382da14d308e143b4f627a35f746" alt="Campaign Agents page subtitled Reusable webhook configurations shared across campaigns, showing two agent cards (API Test Agent 2 and test) each listing the Answer URL with POST method badge, the Hangup URL or Not configured, and Static SIP Headers (None for both)" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4404" data-path="images/platform/campaign/campaign-agents_blur.png" />
</Frame>

Each Agent card shows:

| Section | What it contains |
| - | - |
| **Header** | Friendly name (e.g. `API Test Agent 2`) and the creation date. |
| **Answer** | The URL Vobiz POSTs (or GETs) when a campaign call connects - your server's IVR / AI flow lives here. |
| **Hangup** | Where Vobiz POSTs the final call result. Shown as *Not configured* if you skipped it. |
| **Static SIP Headers** | Custom headers Vobiz attaches to every campaign call placed through this agent (none by default). |

The pencil/trash icons on each card let you edit or delete the Agent. Deleting an Agent returns `409` while any linked campaign is `running`, `queued`, or `paused`. Finish, cancel, and archive those campaigns first.

## Create a new Agent

Click **+ New Agent** in the top‑right.

<Frame caption="New Agent form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/campaign/campaign-agent-new.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=d338ab3bc306d1750429c32217b115eb" alt="New Agent side panel with fields for Name (filled in with Appointment Reminder Agent), Answer URL with POST method dropdown, Hangup URL with POST method dropdown, and a Static SIP Headers section with an Add header link, plus Cancel and orange Create Agent buttons at the bottom" style={{maxWidth: '600px', margin: '0 auto', display: 'block'}} width="2000" height="1107" data-path="images/platform/campaign/campaign-agent-new.png" />
</Frame>

| Field | Required | Notes |
| - | - | - |
| **Name** | ✅ | Something descriptive - *"Appointment Reminder Agent"*, *"Q4 Survey Bot"*. You'll pick this from a dropdown when creating campaigns. |
| **Answer URL** | ✅ | Method (`POST` recommended) + URL. Vobiz hits this when a campaign call is answered. Same XML conventions as a normal [XML application](/docs/platform/voice/applications). |
| **Hangup URL** | – | Optional. Vobiz POSTs the call result here when the call ends. Recommended in production - most analytics depend on it. |
| **Static SIP Headers** | – | Click **+ Add header** to attach key/value pairs that Vobiz sends with every outgoing INVITE. Use for tagging traffic (`X-Campaign-Source: q4-reminders`) or routing hints. |

Click **Create Agent**.

<Note>
  Vobiz takes a frozen Agent snapshot when a campaign launches. Editing the Agent does not change campaigns that are already `running` or `queued`; the changes apply on the next launch.
</Note>

## Static SIP Headers - when to use them

The headers you add here are attached to every INVITE Vobiz sends on behalf of campaigns that use this agent. Common patterns:

* **`X-Campaign-Source`** - tag for your downstream PBX or CRM to know the source.
* **`P-Asserted-Identity`** - carrier‑specific identity routing (check with your trunk provider first).
* **`X-RingTime`** - pass a max ring time hint to the receiving system.

<Warning>
  Static headers apply to **every** call from every campaign that uses this agent. If you need per‑call values, set them in your Answer URL XML response with `<SipHeader>` instead.
</Warning>

## Use the Agent in a campaign

Open [Campaigns → + New Campaign](/docs/platform/campaigns/list) - the **Agent** dropdown lists every agent on your account. Pick the one you just made and the rest of the form takes over from there.

## What's next

<CardGroup cols={2}>
  <Card title="Launch a campaign" icon="bullhorn" href="/docs/platform/campaigns/list">
    Wire this agent into a real outbound run.
  </Card>

  <Card title="XML reference" icon="code" href="/docs/xml/overview/how-it-works">
    The XML your Answer URL should return.
  </Card>

  <Card title="Campaign Agents API" icon="terminal" href="/docs/campaign-manager/agents/create-agent">
    Create and manage Agents programmatically.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.