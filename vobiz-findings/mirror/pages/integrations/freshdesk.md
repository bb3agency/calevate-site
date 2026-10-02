> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Freshdesk integration

> A Vobiz calling panel inside Freshdesk - browser-based inbound and outbound calls, click-to-call, and recording playback for agents in 130+ countries.

<img className="block w-14 h-14 rounded-xl mb-4" src="https://mintcdn.com/vobizai/0k3SZCvRL2SRjhv6/images/freshdesk/logo.png?fit=max&auto=format&n=0k3SZCvRL2SRjhv6&q=85&s=9dc7bb821c0ff62f04cc4023ca2ff050" alt="Freshdesk" width="512" height="512" data-path="images/freshdesk/logo.png" />

A calling panel that puts Vobiz telephony inside Freshdesk. Agents place and receive real phone calls from the browser and play back recordings without leaving the helpdesk.

**Source code:** [vobiz-ai/Vobiz-Freshdesk-Calling](https://github.com/vobiz-ai/Vobiz-Freshdesk-Calling) — the Freshworks app used throughout this guide, plus a zero-dependency mock backend so you can develop the panel without a Vobiz account.

<Note>
  **Scope:** inbound and outbound, with browser audio over WebRTC. This installs as a **custom app** on your own account — there is no Marketplace review to wait for, and it is usually live within about thirty minutes of upload.
</Note>

<Warning>
  **This replaces your current telephony.** Freshdesk allows only one CTI app to be active at a time, and Freshcaller cannot be enabled alongside one. Installing this takes over from whatever telephony the account uses today.
</Warning>

## What you get

| | |
| - | - |
| **Click-to-call** | Click any phone number in Freshdesk and the panel opens and dials |
| **Outbound calls** | Dial from the panel with a number picked from your Vobiz account |
| **Inbound calls** | Enable once, and calls to the agent's number ring the panel |
| **Recording playback** | Recent recordings listed and playable in the panel |
| **Browser audio** | Calls run over WebRTC in the tab — no desk phone, no desktop app |

## How it works

```text theme={null}
Freshdesk  ──cti.triggerDialer──▶  the panel  ──HTTPS──▶  your calling backend  ──▶  Vobiz REST API
                                       │                                                  │
                                       └─────────── SIP over WebSocket ───────────────────┘
                                                     (audio in the browser)
```

Freshdesk's telephony surface is small. It exposes exactly one event to a calling app:

```js theme={null}
client.events.on("cti.triggerDialer", cb);   // the only cti.* event that exists
```

It fires when an agent clicks a phone number on a ticket or contact page. Installing a CTI app is what makes those numbers clickable in the first place — the app registers nothing to enable it.

There is **no inbound-call event, no agent-presence event and no call-ended event**. Everything else flows the other way: the app tells Freshdesk what happened through `client.interface.trigger` and the Freshdesk REST API. The depth of any Freshdesk CTI integration is therefore a function of how much the app chooses to write back.

The whole Freshworks surface this app uses today:

| Call | Purpose |
| - | - |
| `app.initialized()` | Boot |
| `client.iparams.get()` | Read the installation settings |
| `client.events.on("cti.triggerDialer")` | Receive click-to-call |
| `client.interface.trigger("show", { id: "softphone" })` | Open the panel when a call starts |

## The outbound call flow

<div className="my-6">
  <img className="block dark:hidden w-full max-w-2xl mx-auto" src="https://mintcdn.com/vobizai/0k3SZCvRL2SRjhv6/images/freshdesk/outbound-flow-light.svg?fit=max&auto=format&n=0k3SZCvRL2SRjhv6&q=85&s=7e58dc34bab570794615f54a714d8695" alt="Five-step outbound call flow: the agent clicks Call, the panel POSTs /start-call, the backend has Vobiz dial the customer first, the customer answering triggers the /answer webhook which returns a Dial User element, and Vobiz then dials into the agent's browser where JsSIP auto-answers." width="720" height="550" data-path="images/freshdesk/outbound-flow-light.svg" />

  <img className="hidden dark:block w-full max-w-2xl mx-auto" src="https://mintcdn.com/vobizai/0k3SZCvRL2SRjhv6/images/freshdesk/outbound-flow-dark.svg?fit=max&auto=format&n=0k3SZCvRL2SRjhv6&q=85&s=b76b046e220d2811bb54b57ccabde3ca" alt="Five-step outbound call flow: the agent clicks Call, the panel POSTs /start-call, the backend has Vobiz dial the customer first, the customer answering triggers the /answer webhook which returns a Dial User element, and Vobiz then dials into the agent's browser where JsSIP auto-answers." width="720" height="550" data-path="images/freshdesk/outbound-flow-dark.svg" />
</div>

<Warning>
  **The order cannot be reversed.** The Vobiz REST API cannot originate a call to a registered WebRTC endpoint — it returns `Endpoint Not Registered`. So the customer is dialled first and the agent is bridged in second.

  Tell your agents about the ringback. A customer who answers and hears a second of tone sometimes hangs up, thinking the call failed.
</Warning>

## Inbound calls

The agent clicks **Enable inbound calls to this panel** once. The backend creates (or reuses) a Vobiz [application](/docs/applications) pointing at its own `/inbound-answer` webhook and attaches the agent's selected number to it. Real calls to that number then hit `/inbound-answer`, which dials `sip:…` — landing on the same auto-answer path as the outbound bridge leg.

Keep the Freshdesk tab open; the panel has to stay registered to receive the call.

## Requirements

| Requirement | Detail |
| - | - |
| Freshdesk | **Growth, Pro or Enterprise**, with admin access |
| A calling backend | You run this. The app holds no Vobiz credentials — see [the contract](#the-calling-backend) |
| Vobiz account | Auth ID, Auth Token, and at least one number — [console.vobiz.ai](https://console.vobiz.ai) |
| Freshworks CLI | `fdk`, pinned to the Node version in `manifest.json` |

## The calling backend

The app is a client. It holds no Vobiz credentials and cannot place a call on its own — it talks to a **calling backend that you run**, which holds the account credentials and drives the Vobiz REST API.

<Note>
  **The backend is not in the repository.** Its complete contract is in [`docs/backend-contract.md`](https://github.com/vobiz-ai/Vobiz-Freshdesk-Calling/blob/main/docs/backend-contract.md). Read it before you start — the obvious implementation of the recording endpoint is unsafe, and the document explains why.
</Note>

Two reasons the backend exists, both non-negotiable:

1. **Vobiz Auth Tokens are account-level API credentials.** Never expose `X-Auth-Token` in client-side code — see [authentication](/docs/api-reference/authentication). The backend holds the token and the browser never sees it.
2. **An `<audio>` element cannot send authentication headers.** Recordings are protected, so playback needs a server-side step.

Everything below is relative to the `backend_url` installation parameter. The app requires HTTPS and strips trailing slashes.

| Route | Called by | Purpose |
| - | - | - |
| `GET /agent/{agentId}` | Browser | The SIP identity the panel registers as. `sipUser` must be a full `user@domain` |
| `GET /session/{agentId}` | Browser | Session restore when the panel loads |
| `POST /login` | Browser | Validate credentials against Vobiz, store them server-side, return the account's numbers |
| `POST /select-number` | Browser | Set the caller ID for this agent |
| `POST /start-call` | Browser | Dial the customer; the agent is bridged in later |
| `GET /call-status/{callUuid}` | Browser | Polled every 3 seconds while a call is up |
| `POST /setup-inbound` | Browser | Create the Vobiz application and attach the agent's number |
| `GET /recordings/{agentId}` | Browser | List recent recordings |
| `GET /recording-audio/{agentId}/{recordingId}` | Browser | Playable audio, assigned straight to an `<audio>` element |
| `GET\|POST /answer` | **Vobiz** | Returns `<Dial><User>sip:…</User></Dial>` to bridge the agent in |
| `GET\|POST /inbound-answer` | **Vobiz** | The XML for an inbound call. A 20-second no-answer timeout to voicemail is a sensible default |

### Security requirements

The app sends `agentId` as a plain string in the path, body or query. **If your backend trusts that string, every browser route above is unauthenticated and the `agentId` is guessable.** Somebody who learned your backend URL could then read SIP passwords, place calls billed to your account, rewrite your inbound number routing, and download every recording.

<Warning>
  A backend implementing this contract must:

  * **Authenticate every request.** Do not treat `agentId` as proof of identity — issue a per-agent token at login and require it.
  * **Not serve long-lived SIP passwords.** Mint short-lived credentials, or gate `/agent/{agentId}` behind the same authentication.
  * **Sign recording URLs** with a short expiry, and verify the signature on every request. An endpoint that streams any recording to anyone holding the URL is a breach waiting to happen — and `/recordings` hands out the IDs.
  * **Scope CORS to the Freshdesk origin.** Never `Access-Control-Allow-Origin: *`.
  * **Store Auth Tokens encrypted at rest**, and never log them.
  * **Serve over HTTPS** with a stable hostname.

  If you are adapting an internal prototype, assume it does none of these.
</Warning>

## Step 1: Pack the app

The Freshworks CLI is pinned to a Node version, with a separate CLI build per Node major. Install the pair the app declares in `manifest.json`:

```bash theme={null}
nvm install 24.11.1 && nvm use 24.11.1
npm install https://cdn.freshdev.io/fdk/latest-v24.tgz -g
fdk version     # 10.1.9
```

```bash theme={null}
git clone https://github.com/vobiz-ai/Vobiz-Freshdesk-Calling.git
cd Vobiz-Freshdesk-Calling
fdk validate
fdk pack
```

The installable zip lands in `dist/`.

<Note>
  `fdk pack` enforces Freshworks' 80% coverage floor on every metric, and additionally wants *local simulation* coverage, which is only produced by running the app inside a real Freshdesk account via `?dev=true`. For local builds use `fdk pack --skip-coverage`; do not use that flag for a Marketplace submission.
</Note>

## Step 2: Create the custom app

1. In Freshdesk, go to **Admin → Apps**.
2. Click **Go to Developer Portal**.
3. Click **Create New App** and choose **Custom App**.
4. Select your Freshdesk account.
5. Upload the zip from `dist/`.
6. Fill in the app details — name, description, and your team's support email.
7. **Save and Publish**, then **Promote to Live**.

## Step 3: Install and configure

1. Back in Freshdesk, go to **Admin → Apps → Manage Apps**.
2. Filter to **Custom**.
3. Find the app and click **Install**.
4. Fill in the settings:

| Setting | Required | Value |
| - | - | - |
| Calling backend URL | Yes | The HTTPS base URL of your backend, no trailing slash |
| Agent identity | Yes | The identity for *this* agent. **Every agent needs a different one** |
| SIP registrar URL | No | Leave blank unless Vobiz support gave you a different one |

All three can be changed later without reinstalling, under **Admin → Apps → Manage Apps → Custom → Settings → Configure**.

## Step 4: Open the panel

Open any agent page and look for the Vobiz icon at the **bottom left**. The panel loads on all agent pages, not only tickets — if the icon does not appear, hard refresh.

Then:

1. **Log in** with your Vobiz Auth ID and Auth Token, and pick the number to call from. These are entered by the agent at runtime and are not stored by the app.
2. **Make a call** by typing a number and clicking **Call**, or by clicking any phone number in Freshdesk.
3. The first call prompts for **microphone permission**, since audio runs through the browser.
4. **Receive calls** by clicking **Enable inbound calls to this panel** once.

## Develop without a Vobiz account

The repository ships a mock backend that implements the whole contract with fake data, so the panel can be developed without placing a real call.

```bash theme={null}
npm install
npm run mock-backend     # terminal 1 — http://localhost:8092
fdk run                  # terminal 2 — http://localhost:10001
```

Open a Freshdesk page with `?dev=true` appended, then set the app's settings at `http://localhost:10001/custom_configs`:

| Setting | Value |
| - | - |
| Calling backend URL | `http://localhost:8092` |
| Agent identity | anything, e.g. `priya` |
| SIP registrar URL | leave blank |

Any Auth ID and Auth Token are accepted. Use `fail` as the Auth ID to exercise the error path. The mock backend's [README](https://github.com/vobiz-ai/Vobiz-Freshdesk-Calling/blob/main/mock-backend/README.md) covers pointing it at a real Vobiz SIP endpoint to test actual audio.

### Tests

```bash theme={null}
npm test        # Vitest in jsdom, with coverage
fdk validate    # platform and lint rules
```

The tests load the real `app/scripts/app.js` and the real markup from `app/index.html` into jsdom with the Freshworks SDK, JsSIP and `fetch` faked, so they exercise the code that ships rather than a copy of it. The whole app is three files — `app/index.html`, `app/scripts/app.js` and `app/styles/style.css`. No build step, no framework.

## Binding inbound audio

Worth knowing before you touch the SIP code. For an **incoming** session, JsSIP has not built the `RTCPeerConnection` yet — `session.connection` is `null` until the call is answered. Dereferencing it inside the `newRTCSession` handler throws, and because the throw happens inside that handler it aborts **before `.answer()` runs**.

The symptom is misleading: the browser silently never picks up, Vobiz rings the endpoint until it times out, and the far end is never connected. Bind through the `peerconnection` event instead:

```js theme={null}
session.on("peerconnection", e => bindTrack(e.peerconnection));
bindTrack(session.connection);   // no-op on the incoming path
```

## Troubleshooting

| Symptom | Cause | Resolution |
| - | - | - |
| "Not configured" | Setup was skipped or incomplete | Re-enter the settings under **Manage Apps → Custom → Settings → Configure** |
| "Backend URL must start with https\://" | The URL is missing its scheme | Enter the full `https://…` URL |
| "Cannot reach the calling backend" | The backend is down, or the URL is wrong | Confirm it is running and reachable over public HTTPS |
| Stuck on "Connecting…" | Same as above, or the agent identity does not exist | Check the identity matches one your backend knows |
| "Registration failed" | The SIP credentials from your backend were rejected | Check what `/agent/{agentId}` returns |
| Call button stays disabled | Not logged in, or SIP is not registered | The hint under the button says which |
| Connected but no audio | Microphone permission was blocked | Allow the microphone in the address bar, then reload |
| Calls ring the wrong person | Two agents share an identity | Give each agent their own |
| The panel icon never appears | Cached assets | Hard refresh (`Ctrl` + `F5`) |

<Note>
  **WebRTC inside a Freshdesk iframe.** The app registers over SIP-over-WebSocket from inside a Freshworks-hosted iframe, and Freshworks does not publish the Content-Security-Policy applied to app iframes. If your network or the platform blocks the WebSocket, registration fails and the panel reports it. Test on one account before rolling out widely.
</Note>

If the backend needs allowlisting on your side, see [IP whitelisting](/docs/concepts/ip-whitelisting).

## Scope today

The panel is a softphone that lives inside Freshdesk. Click-to-call, outbound, inbound and recording playback all work today. Writing back into Freshdesk's data — creating tickets from calls, logging calls as ticket notes, popping the contact record on an inbound call, attaching recordings — is on the roadmap in the repository's [CHANGELOG](https://github.com/vobiz-ai/Vobiz-Freshdesk-Calling/blob/main/CHANGELOG.md). Hold, mute, transfer and conference are not built, and one agent identity is set per installation by an admin.

Two constraints to plan around if you extend it:

* **The CTI sidebar has no page context.** `client.data.get("ticket")` is not available in `cti_global_sidebar`. Knowing which ticket the agent is viewing needs a separate `ticket_background` instance, which shares no JavaScript state — so coordination goes through `$db` or the backend.
* **The Freshdesk API key should be a secure iparam**, which means calls using it must go through `client.request.invokeTemplate` rather than `fetch`. Secure iparams are only substituted into request-template headers and are never readable from front-end JavaScript.

## Next steps

* Clone the app and mock backend: [vobiz-ai/Vobiz-Freshdesk-Calling](https://github.com/vobiz-ai/Vobiz-Freshdesk-Calling)
* Read the [backend contract](https://github.com/vobiz-ai/Vobiz-Freshdesk-Calling/blob/main/docs/backend-contract.md) before implementing your own
* Create the agents' SIP endpoints: [Endpoints API](/docs/endpoint) or the [console guide](/docs/platform/voice/endpoints)
* Read the [`<Dial>` reference](/docs/xml/dial) and [`<User>`](/docs/xml/dial/user)
* Want ticket logging out of the box? See [Zendesk](/docs/integrations/zendesk), where it ships with the backend


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.