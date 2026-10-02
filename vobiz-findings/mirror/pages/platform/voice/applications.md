> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# XML Applications - Create & Manage Voice Apps

> Build XML applications in the Vobiz Console - point Answer and Hangup webhooks at your server, attach phone numbers, and serve programmable call flows. Walkthrough of the Applications list, app details, and the Create XML Application form.

A **Vobiz XML Application** ties a phone number to your server. When a call arrives, Vobiz POSTs (or GETs) to your **Answer URL**; your server responds with XML that tells Vobiz what to say, gather, dial, stream, or record. When the call ends, Vobiz POSTs the result to your **Hangup URL**.

```text URL theme={null}
https://console.vobiz.ai/app/voice/applications
```

## The Applications list

<Frame caption="Voice Applications - Applications">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/voice/voice-applications_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=ff554f7815cfe17a8b5fa69e4ffadb17" alt="Voice Applications page split into three columns - the navigation sidebar on the left, a searchable list of XML applications in the middle showing apps like Vobiz WebRTC Playground and qwerty, and an Application Details panel on the right showing Application ID, Answer URL, Hangup URL, attached phone numbers, and endpoints" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="4400" data-path="images/platform/voice/voice-applications_blur.png" />
</Frame>

Three columns top‑to‑bottom:

1. **Search + Create** - filter the list by name, or click **+ Create New Application** to open the [creation form](#create-an-xml-application).
2. **App list** - every app on your account. Each card shows the Answer URL, Hangup URL, and a **View details** link.
3. **Application Details panel** - the right side updates when you click a card.

## What the details panel shows

| Field | Meaning |
| - | - |
| **Application Name** | The friendly name you typed at creation. Edit any time via the pencil icon. |
| **Application ID** | The immutable identifier - quote this when filing support tickets and use it as the `application_id` in REST API calls. |
| **Default Number App** | `Yes` means any phone number that isn't explicitly attached to another app will fall back to this one. Useful for "catch‑all" routing. |
| **Primary Answer URL** | Method + URL Vobiz calls when an inbound call needs handling, or when an outbound API call has no inline XML. |
| **Hangup URL** | Method + URL Vobiz POSTs the final call result to. |
| **Public URI** | If `Yes`, the answer URL is reachable from the public internet - Vobiz can deliver calls. Toggle to `No` to disable the app without deleting it. |
| **Default Endpoint App** | `Yes` means [SIP endpoints](/docs/platform/voice/endpoints) without an explicit app assignment use this one. |

Below the details, two tabs:

* **Phone Numbers** - every DID attached to this application. Click **+ Attach Number** to add more, or **Detach** to release one.
* **Endpoints** - SIP endpoints (softphone logins) routed to this application.

## Create an XML Application

Click **+ Create New Application** to open the side panel.

<Frame caption="Create XML Application form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/voice/voice-app-create.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=b83581044117733502559b295e6ae520" alt="Create XML Application side panel with fields for Application Name, Default Number App toggle, Answer URL with HTTP method dropdown and Test URL button, Hangup URL, Fallback Answer URL, Public URI toggle, and Default Endpoint App toggle" style={{maxWidth: '600px', margin: '0 auto', display: 'block'}} width="2000" height="1111" data-path="images/platform/voice/voice-app-create.png" />
</Frame>

| Field | Required | Notes |
| - | - | - |
| **Application Name** | ✅ | A human label like "Inbound IVR" or "Outbound Survey". |
| **Default Number App** | – | Toggle on to make this the catch‑all for unassigned numbers. |
| **Answer URL** | ✅ | `POST` (recommended) or `GET`. Click **Test URL** to send a sample payload and verify your server responds with valid XML. |
| **Hangup URL** | – | Optional but strongly recommended - most CDR analytics depend on it. |
| **Fallback Answer URL** | – | If your primary URL returns 5xx or times out, Vobiz tries this one before failing the call. |
| **Public URI** | – | Toggle on if your server is publicly reachable. |
| **Default Endpoint App** | – | Toggle on to make this the default for [SIP endpoints](/docs/platform/voice/endpoints). |

<Tip>
  Use the **Test URL** button before saving. A green "200 OK" confirms reachability; a red error usually means your firewall is blocking Vobiz IPs - see [IP whitelisting](/docs/concepts/ip-whitelisting).
</Tip>

Generate the XML body your webhook returns with the [interactive XML Builder](/docs/xml-builder), or hand‑roll it using the [XML overview](/docs/xml/overview/how-it-works).

## Attach phone numbers

The final step of the create flow (and a separate **+ Attach Number** action on existing apps) opens the **Attach Phone Numbers to Application** view.

<Frame caption="Attach Phone Numbers modal">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/voice/voice-app-attach-numbers_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=9e94467c261ffc1917f522a6d8a2d852" alt="Attach Phone Numbers to Application screen showing two tabs Current Phone Numbers and Buy New Phone Number, a search field, and a table of 24 numbers with columns Number and Area, Alias, Type, Capabilities, Linked To, and Action with Select or Linked to Application / Trunk badges" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="5252" data-path="images/platform/voice/voice-app-attach-numbers_blur.png" />
</Frame>

Two tabs:

* **Current Phone Numbers** - every DID on your account. The **Linked To** column shows where each number is currently routed (another App, a Trunk, or unassigned). Only numbers with no link or those linked to *this* app can be selected.
* **Buy New Phone Number** - opens the [DID purchase flow](/docs/account-phone-number/list-inventory-numbers) without leaving this dialog.

Click **+ Select** on each row you want, then **Attach N Selected Numbers** at the bottom. You can also click **Skip for now** and attach numbers later from the details panel.

## Edit, delete, and disable

The two icons in the top‑right of the details panel:

* **✏ Edit** - opens the same form you used to create the app. URLs, name, and toggles can all change.
* **🗑 Delete** - permanently removes the app. Any attached numbers fall back to the default number app (or stop receiving calls if no default is set).

To **disable temporarily** without losing the config, edit the app and toggle **Public URI** off.

## Tips

* Keep one **Default Number App** that points to a small "this number is unconfigured" handler - newly purchased numbers will route there until you wire them up.
* Use a **Fallback Answer URL** in production. A 502 from your primary handler is rare, but when it happens you want graceful XML, not a SIP error.
* The **Application ID** is the canonical handle for API access - store it in your `.env` rather than the name.

## What's next

<CardGroup cols={2}>
  <Card title="SIP Endpoints" icon="plug" href="/docs/platform/voice/endpoints">
    Sign softphones into your app for click‑to‑call testing.
  </Card>

  <Card title="XML Reference" icon="code" href="/docs/xml/overview/how-it-works">
    Every supported XML verb with examples.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.