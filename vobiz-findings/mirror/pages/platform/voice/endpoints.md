> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# SIP Endpoints - Softphone & WebRTC Logins

> Create SIP endpoints in the Vobiz Console for softphones, Zoiper, and custom WebRTC clients. Review SIP URIs, credentials, and application assignment.

A **SIP endpoint** is a username/password Vobiz uses to register a softphone, browser, or WebRTC client. Once registered, the endpoint can make and receive calls just like a Vobiz phone number - handy for click‑to‑call from a browser, agent‑side softphones, or testing without buying a DID.

```text URL theme={null}
https://console.vobiz.ai/app/voice/endpoints
```

## The endpoints list

<Frame caption="Voice Applications - Endpoints">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/voice/voice-endpoints_blur.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=551d666cac59b1632c2b767a0b7fe97f" alt="SIP Endpoints page with a left column showing a search bar, Create New Endpoint button, and a list of endpoints (Vobiz WebRTC Playground Endpoint, test, piyush, piyush test zoiper) and a right panel showing endpoint details with Alias, Authentication username and password, and SIP Configuration with sip URI and assigned application" style={{maxWidth: '900px', margin: '0 auto', display: 'block'}} width="8000" height="5220" data-path="images/platform/voice/voice-endpoints_blur.png" />
</Frame>

Two columns:

* **Left** - a searchable list. Each card shows the **alias**, **username**, and the **application** the endpoint is wired to.
* **Right** - endpoint details for the row you've clicked.

## What the endpoint details show

| Section | Field | Purpose |
| - | - | - |
| **Endpoint Details** | **Alias** | Friendly name shown in lists. Editable. |
| **Authentication** | **Username** | Auto‑generated identifier (e.g. `play2042343509327874733`). This is what you type in your softphone's *Username* field. |
| | **Password** | Stored hashed - Vobiz never displays it after creation. Use **Change password** to set a new one. |
| **SIP Configuration** | **SIP URI** | The full SIP address (e.g. `sip:play2042343509327874733@registrar.vobiz.ai`). Use it as the *Domain* in any SIP client. |
| | **Application** | The [XML application](/docs/platform/voice/applications) routed to this endpoint. Calls placed *to* the endpoint hit this app's Answer URL. |

<Tip>
  In Zoiper, set **Domain** to `registrar.vobiz.ai`, **Username** to the endpoint username, and **Password** to whatever you typed at creation. Outbound proxy not required.
</Tip>

## Create a SIP endpoint

Click **+ Create New Endpoint** to open the form.

<Frame caption="Create SIP Endpoint form">
  <img src="https://mintcdn.com/vobizai/rHC7MC1ZnRKlF7P2/images/platform/voice/voice-endpoint-create.png?fit=max&auto=format&n=rHC7MC1ZnRKlF7P2&q=85&s=b2f9c4579d504b1c23a48d834b3ac657" alt="Create SIP Endpoint modal showing required Alias and Username fields, Password field with show/hide eye icon, optional Application dropdown set to None, and a tooltip saying Please fill out this field" style={{maxWidth: '720px', margin: '0 auto', display: 'block'}} width="1654" height="1556" data-path="images/platform/voice/voice-endpoint-create.png" />
</Frame>

| Field | Required | Notes |
| - | - | - |
| **Alias** | ✅ | A friendly name like "Agent 1 Zoiper" or "Sales WebRTC". |
| **Username** | ✅ | Alphanumeric only - no spaces, dots, or symbols. This becomes the SIP `username`. |
| **Password** | ✅ | Set a strong password. Vobiz won't show it again after save - store it in your password manager *now*. |
| **Application (optional)** | – | Pick the [XML application](/docs/platform/voice/applications) calls to this endpoint should hit. Leave as **None** if you only need outbound from this endpoint. |

Click **Create Endpoint** and Vobiz issues the SIP credentials.

## Vobiz WebRTC Playground

The hosted [Vobiz WebRTC Playground](https://rtc-demo.vobiz.ai) uses your account **Auth ID** and **Auth Token**, not a SIP endpoint username and password. The first connection automatically creates the `Vobiz-WebRTC-Playground` application for browser-based inbound and outbound calling.

<Card title="Set up browser calling" icon="globe" href="/docs/integrations/webrtc-application-setup">
  Connect the playground, configure caller ID, place an outbound call, and attach a DID for inbound calls.
</Card>

## Edit, change password, delete

Top‑right of the details panel:

* **✏ Edit** - change alias or the assigned application.
* **Change password** (inside the Authentication card) - rotate credentials. The old password is immediately invalidated; update your softphone before the next call.
* **🗑 Delete** - permanently remove the endpoint. Any registered client will drop the session.

## Tips

* **One endpoint per agent.** Don't share a username/password across team members - Vobiz registrar only allows one active registration per endpoint.
* **Rotate passwords on offboarding.** Deleting the endpoint is cleaner, but changing the password is faster if the same alias will be reassigned.
* **Use the WebRTC Playground for browser testing.** Follow the [WebRTC Playground guide](/docs/integrations/webrtc-application-setup) to call with your Vobiz API credentials and an attached DID.

## What's next

<CardGroup cols={2}>
  <Card title="WebRTC Playground" icon="globe" href="/docs/integrations/webrtc-application-setup">
    Make and receive browser calls with your API credentials and a Vobiz DID.
  </Card>

  <Card title="Applications" icon="file-code" href="/docs/platform/voice/applications">
    Point this endpoint at an XML app that responds with real call flows.
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.