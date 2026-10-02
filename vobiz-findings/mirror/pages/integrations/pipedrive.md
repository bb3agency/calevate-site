> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Pipedrive integration

> A Vobiz softphone inside Pipedrive - dial from the page, talk in the tab, and every call lands in the CRM as an Activity and a Call Log with a signed recording link.

A browser softphone that logs every call to Pipedrive. Agents dial from the page, talk in the tab, and the call lands in the CRM as an **Activity** and a **Call Log** with duration and a signed recording link.

**Source code:** [vobiz-ai/Vobiz-Pipedrive-Calling](https://github.com/vobiz-ai/Vobiz-Pipedrive-Calling) — the softphone, the embedded CTI panel, and the Node backend that answers Vobiz webhooks and syncs to Pipedrive.

<Note>
  **Scope:** inbound and outbound, with browser audio over WebRTC. Verified end to end against a live Vobiz account and a live Pipedrive sandbox — both directions connect with two-way audio and activities appear in the CRM.
</Note>

## What you get

| | |
| - | - |
| **Click-to-call** | Dial from the panel, or from a person record |
| **Activity + Call Log** | Every call written through `POST /activities` and `POST /callLogs` |
| **Caller lookup** | Inbound numbers resolved through `/persons/find`, falling back to `/itemSearch` |
| **In-call controls** | Mute, Hold and Transfer while connected |
| **Recordings** | Playable from the panel behind an HMAC-signed, short-expiry link |
| **Browser audio** | Calls run over WebRTC in the tab — no desk phone, no desktop app |

## How it works

The one thing to understand first: **the browser is the A leg.** The page sends the SIP INVITE itself, and the backend answers `<Dial><Number>` to reach the customer.

```text theme={null}
browser ──SIP INVITE──▶ Vobiz ──answer_url──▶ backend /answer
                                                  │
                                           <Dial><Number> ──▶ customer
```

<Warning>
  **The intuitive design does not work,** and is what this app used to do. Originating to the customer over the REST API and then bridging the agent in with `<Dial><User>` is blocked platform-side: Vobiz builds a gateway URI it cannot parse and drops its own INVITE (`tr_eval_uri(): invalid uri`, `blocking gw`). The customer answers, hears ringback, then *"the agent could not be reached"*.

  Inbound is the exception — `<Dial><User>` is the only way to reach a registered endpoint, and it works today.
</Warning>

| Path | Role |
| - | - |
| `backend/server.js` | Webhooks, softphone API, CRM sync |
| `backend/pipedrive-oauth.js` | OAuth 2.0 — authorize, exchange, refresh, `api_domain` |
| `agent-phone/` | The softphone — `vobiz-sip.js` is the SIP layer (register, dial, answer, mute/hold/DTMF) |
| `pipedrive-app/` | The embedded CTI panel for Pipedrive |
| `backend/fetch-cdr.js` | CLI — pull CDRs from Vobiz and sync them |

## Requirements

| Requirement | Detail |
| - | - |
| Vobiz account | `AUTH_ID`, `AUTH_TOKEN`, a number, and balance — [console.vobiz.ai](https://console.vobiz.ai) |
| Pipedrive sandbox | From [developers.pipedrive.com](https://developers.pipedrive.com) |
| Public HTTPS URL | `cloudflared` or ngrok. Vobiz must reach `/answer`, `/dial-status` and `/recording-callback` |
| Runtime | Node 18+ |

## Step 1: Prove the Vobiz account

Place a call with [rtc-demo.vobiz.ai](https://rtc-demo.vobiz.ai/). If that fails, nothing here will work and you will debug the wrong layer for a day.

## Step 2: Create the SIP endpoint

```bash theme={null}
curl -X POST "https://api.vobiz.ai/api/v1/Account/$AUTH_ID/Endpoint/" \
  -H "X-Auth-ID: $AUTH_ID" -H "X-Auth-Token: $AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"pdagent","password":"<choose one>","alias":"Pipedrive Agent"}'
```

<Warning>
  **Vobiz rewrites the username you submit.** Send `pdagent` and the stored username comes back as something like `pdagent1187694299145202883643`. Read the stored `username` out of the response — that is what registers, and what `VOBIZ_SIP_USER` must contain.
</Warning>

## Step 3: Run the backend

```bash theme={null}
cp backend/.env.example backend/.env    # fill it in
npm start                               # :8092 by default
cloudflared tunnel --url http://localhost:8092
```

Put the tunnel URL in `TUNNEL_URL`, then **check the answer URL is alive before touching any UI**:

```bash theme={null}
curl -s -X POST "$TUNNEL_URL/answer" \
  -d "From=sip:x@registrar.vobiz.ai&To=91XXXXXXXXXX&RouteType=sip"
```

You must get `<Response>` containing `<Dial …><Number>`. Anything else — an ngrok interstitial, a 404 page — and every call dies.

## Step 4: Point Vobiz at the backend

Create an application whose `answer_url` is `$TUNNEL_URL/answer`, bind the SIP endpoint to it, and attach a DID for inbound:

```bash theme={null}
# create the application
curl -X POST ".../Account/$AUTH_ID/Application/" -d '{
  "app_name":"Pipedrive Calling","answer_url":"'"$TUNNEL_URL"'/answer",
  "answer_method":"POST","hangup_url":"'"$TUNNEL_URL"'/answer","hangup_method":"POST"}'

# bind the endpoint — the field is app_id, NOT the documented `application`,
# which is silently ignored and still returns 202 "changed"
curl -X POST ".../Account/$AUTH_ID/Endpoint/$ENDPOINT_ID/" -d '{"app_id":"'"$APP_ID"'"}'

# attach a DID for inbound. Lowercase /numbers, + encoded as %2B.
# /Number/ returns a bare 401 that reads like a credentials problem and is not.
curl -X POST ".../Account/$AUTH_ID/numbers/%2B91XXXXXXXXXX/application" \
  -d '{"application_id":"'"$APP_ID"'"}'      # 204 on success
```

## Step 5: Connect Pipedrive over OAuth

In **Developer Hub → Create public app**, set the callback URL to `$TUNNEL_URL/auth/pipedrive/callback` — it must match `PIPEDRIVE_REDIRECT_URI` exactly, and only one callback URL is allowed per app.

Request these scopes and nothing more. Over-scoping is a documented rejection reason:

| Toggle | Setting | Used for |
| - | - | - |
| Deals | Read only | Activities link to `deal_id` |
| Activities | Full access | `POST /activities` |
| Contacts | Read only | `/persons/find` caller lookup |
| Search for all data | On | `/itemSearch` fallback lookup |
| Call logs | On | `POST /callLogs` |

Put the Client ID and Secret in `.env`, visit `$TUNNEL_URL/auth/pipedrive` and approve. `GET /auth/pipedrive/status` should then report `"connected": true`.

## Step 6: Sign in and call

Open the panel. Before credentials are entered it shows **NOT SIGNED IN**.

<Frame caption="The panel before sign-in.">
  <img src="https://mintcdn.com/vobizai/nEjKL7mvuJGFrmwF/images/pipedrive/not-signed-in.png?fit=max&auto=format&n=nEjKL7mvuJGFrmwF&q=85&s=85caacfeb7545391af33add417c470f3" alt="Vobiz Calling for Pipedrive panel showing a NOT SIGNED IN badge, a Not signed in banner, and step 1 Sign in to Vobiz with Auth ID, Auth Token and Agent profile fields" style={{maxWidth: "589px", width: "100%", margin: "0 auto", display: "block"}} width="589" height="600" data-path="images/pipedrive/not-signed-in.png" />
</Frame>

Sign in with the **Auth ID and Auth Token** from the [console](https://console.vobiz.ai) under **API credentials**. The badge turns green when JsSIP has registered.

<Frame caption="Registered. The badge reads READY and the signed-in account is shown.">
  <img src="https://mintcdn.com/vobizai/nEjKL7mvuJGFrmwF/images/pipedrive/ready-signed-in.png?fit=max&auto=format&n=nEjKL7mvuJGFrmwF&q=85&s=296f2ddab3cc93c28ea71b1437b11736" alt="The panel showing a green READY badge, a Ready banner, the filled Auth ID and Auth Token fields, an Agent profile selector, and a Signed in as SA_LAUUF1D9 line" style={{maxWidth: "570px", width: "100%", margin: "0 auto", display: "block"}} width="570" height="596" data-path="images/pipedrive/ready-signed-in.png" />
</Frame>

<Warning>
  **Wait for Ready before dialling.** The Call button stays disabled until JsSIP registers, deliberately — dialling with SIP down rings the customer into silence.
</Warning>

### Choose a caller ID

**Calling from** lists the numbers on the account. Carriers require a real number here to bridge a call to a mobile or landline.

<Frame caption="Selecting the outbound caller ID.">
  <img src="https://mintcdn.com/vobizai/nEjKL7mvuJGFrmwF/images/pipedrive/caller-id-dropdown.png?fit=max&auto=format&n=nEjKL7mvuJGFrmwF&q=85&s=078e57f00ffbb2dcc2f44b19ccac3e63" alt="The Choose a caller ID field expanded into a dropdown of six Vobiz numbers with one highlighted, above the dialpad" style={{maxWidth: "586px", width: "100%", margin: "0 auto", display: "block"}} width="586" height="650" data-path="images/pipedrive/caller-id-dropdown.png" />
</Frame>

### Place the call

Type a number in E.164 format or use the built-in dialpad.

<Frame caption="Entering the destination number on the dialpad.">
  <img src="https://mintcdn.com/vobizai/nEjKL7mvuJGFrmwF/images/pipedrive/dialpad-number-entry.png?fit=max&auto=format&n=nEjKL7mvuJGFrmwF&q=85&s=3ae7351af3a253e3d65c467792f98422" alt="The Place a call step with a destination number typed into the Number to call field and a numeric dialpad below it" style={{maxWidth: "584px", width: "100%", margin: "0 auto", display: "block"}} width="584" height="611" data-path="images/pipedrive/dialpad-number-entry.png" />
</Frame>

Once connected the panel shows the timer and the in-call controls — **Mute**, **Hold** and **Transfer** — with the matched Pipedrive contact underneath.

<Frame caption="An active call, with in-call controls and the matched CRM contact.">
  <img src="https://mintcdn.com/vobizai/nEjKL7mvuJGFrmwF/images/pipedrive/active-call-controls.png?fit=max&auto=format&n=nEjKL7mvuJGFrmwF&q=85&s=e43cc1aa3b18cbb2f7f7f03c7f40c776" alt="Live call view showing a red Hang up button, a Calling status line with a ten-second timer, Mute Hold and Transfer buttons, and a Pipedrive CRM contact panel below" style={{maxWidth: "533px", width: "100%", margin: "0 auto", display: "block"}} width="533" height="594" data-path="images/pipedrive/active-call-controls.png" />
</Frame>

## Inbound calls

A call to the attached DID raises an in-panel prompt. **Enter** accepts, **Escape** declines.

<Frame caption="The inbound prompt, with keyboard shortcuts.">
  <img src="https://mintcdn.com/vobizai/nEjKL7mvuJGFrmwF/images/pipedrive/incoming-call-popup.png?fit=max&auto=format&n=nEjKL7mvuJGFrmwF&q=85&s=9df9cc19f1704a51541ea2781af8a89c" alt="The panel with an ON CALL badge, a Ringing banner, and a green Incoming call card showing the calling number with Accept and Decline buttons" style={{maxWidth: "706px", width: "100%", margin: "0 auto", display: "block"}} width="706" height="604" data-path="images/pipedrive/incoming-call-popup.png" />
</Frame>

## When the call ends

A summary confirms the duration and — the part that matters — that the call reached the CRM.

<Frame caption="Call finished, with the CRM sync confirmed on the card itself.">
  <img src="https://mintcdn.com/vobizai/nEjKL7mvuJGFrmwF/images/pipedrive/call-finished-sync.png?fit=max&auto=format&n=nEjKL7mvuJGFrmwF&q=85&s=af696a62fa45945a6304c554004b8bac" alt="Call Finished notification card showing an Inbound call completed badge, the number, duration and finish time, and a green Synced to Pipedrive CRM Activity and Call Log confirmation" style={{maxWidth: "554px", width: "100%", margin: "0 auto", display: "block"}} width="554" height="485" data-path="images/pipedrive/call-finished-sync.png" />
</Frame>

Recordings are listed with their timestamp and duration, each with its own inline player.

<Frame caption="Recordings, with inline players.">
  <img src="https://mintcdn.com/vobizai/nEjKL7mvuJGFrmwF/images/pipedrive/call-recordings.png?fit=max&auto=format&n=nEjKL7mvuJGFrmwF&q=85&s=24107b049b6ffe45c2d35b4a3f5bdfe3" alt="Call recordings list showing three timestamped entries with durations, two of them expanded into inline audio players, above Activity log and Frequently asked sections" style={{maxWidth: "602px", width: "100%", margin: "0 auto", display: "block"}} width="602" height="329" data-path="images/pipedrive/call-recordings.png" />
</Frame>

## Backend routes

| Route | Role |
| - | - |
| `POST /answer`, `/fallback` | The XML Vobiz executes. Branches on direction |
| `POST /dial-status` | The `action` target of `<Dial>` |
| `POST /recording-callback` | Fires when the recording is downloadable |
| `POST /hangup-callback`, `/hangup-call` | Call teardown |
| `POST /start-call`, `/transfer-call` | Softphone call control |
| `POST /login`, `/login-sip`, `/logout`, `GET /session` | Session handling |
| `GET /numbers`, `/api/agent-sip` | Caller IDs and SIP identity |
| `GET /recordings`, `/recording-info`, `/recording-file`, `/play-recording` | Recording access |
| `GET /auth/pipedrive`, `/callback`, `/status`, `/disconnect` | Pipedrive OAuth |
| `GET /api/pipedrive/persons/lookup` | Caller lookup |
| `POST /sync-recent-cdrs` | Backfill CDRs into the CRM |
| `GET /health` | Resolved configuration |

## Testing

```bash theme={null}
npm test                  # everything
npm run test:outbound
npm run test:inbound
npm run test:recording    # SSRF regression tests
npm run test:sync
```

The suite reports **PASS / FAIL / SKIP** and exits non-zero on failure. A fully configured run is `9 passed, 0 failed, 0 skipped`.

<Warning>
  **SKIP is not a pass.** It means a service is not configured, and the summary says so. Mocks are opt-in (`ALLOW_MOCK=1`) and label themselves — they used to be the silent fallback, which made the whole suite pass against a CRM it had never contacted.
</Warning>

## Security

<Note>
  * **Recording playback is HMAC-signed with a short expiry and carries no credentials.** It previously took a `url` parameter and fetched it with the account's Vobiz credentials attached — a credential-exfiltration primitive any web page could drive. Never reintroduce a caller-supplied URL here.
  * **The browser never holds the Vobiz Auth Token.** It is POSTed once at sign-in and exchanged for an opaque session token.
  * **CORS is an allowlist**, not `*`.
  * **OAuth tokens live in `backend/.pipedrive-tokens.json`, mode `0600`, gitignored.** That file holds a refresh token — a long-lived credential for the customer's entire CRM.
</Note>

## Troubleshooting

The backend log is the honest account. The field that matters:

```text theme={null}
[DIAL RESULT] status=completed ring=true cause=NORMAL_CLEARING bleg=abc-123 dur=42
```

<Note>
  **`DialBLegUUID` is the single most useful field in this stack.** Present means it connected; empty means no B leg was ever created, whatever the UI showed.
</Note>

| Symptom | Cause |
| - | - |
| No `WEBHOOK /answer` line at all | Endpoint not bound to the application, or `TUNNEL_URL` is stale |
| `bleg=(none…)` | Destination unreachable, or the caller ID is not owned by this account |
| No CDR in Vobiz at all | `422 Session Interval Too Small` — a session-timer problem |
| CDR billed `0s` | SDP/ICE — check STUN candidates in the browser console |
| Panel stuck on *Connecting…* | Backend unreachable, or it crashed — check the log |
| *Registration failed* | Wrong `VOBIZ_SIP_USER` — probably the name you submitted, not the one Vobiz stored |
| Caller hears ringback then the fallback | `<Dial><User>` naming an endpoint that is not registered |

Three client settings in `agent-phone/vobiz-sip.js` are **not optional**, and all three fail in ways that point nowhere near the cause:

| Setting | Symptom without it |
| - | - |
| `session_timers: false` | `422`, surfaced as the opaque cause *SIP Failure Code*, and **no CDR at all** |
| `pcConfig.iceServers` | Host-only candidates, *Incompatible SDP*, CDR billed `0s` |
| Space-free `user_agent` | Vobiz interpolates it unescaped into a gateway URI; JsSIP's default contains a space |

<Note>
  Ignore the Endpoint API's `sip_registered`. It reads `"false"` even when registration genuinely succeeded, on every endpoint on the account. The panel gates on JsSIP's `registered` event instead.

  **Quick tunnels are the most common cause of "it stopped working."** The hostname changes on every restart, and `TUNNEL_URL`, the Vobiz application's `answer_url` and the Pipedrive OAuth callback all go stale together.
</Note>

## Next steps

* Clone the app: [vobiz-ai/Vobiz-Pipedrive-Calling](https://github.com/vobiz-ai/Vobiz-Pipedrive-Calling)
* The same softphone in other CRMs: [Zendesk](/docs/integrations/zendesk), [HubSpot](/docs/integrations/hubspot), [Freshdesk](/docs/integrations/freshdesk)
* Reference: [`<Dial>`](/docs/xml/dial), [`<Record>`](/docs/xml/record), [SIP endpoints](/docs/endpoint/endpoint-object), [CDRs](/docs/cdr/get-cdr)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.