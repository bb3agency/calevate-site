> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Zoho integration

> Vobiz as a Zoho PhoneBridge telephony provider - click-to-dial, live call states, and call logging with recordings across Zoho CRM, Desk, Recruit and Bigin.

Vobiz runs as a [Zoho PhoneBridge](https://www.zoho.com/phonebridge/developer/v3/) telephony provider. Agents click a number anywhere in Zoho, the call is placed on Vobiz, and the call log lands on the Zoho record with its recording.

**Source code:** [vobiz-ai/Vobiz-Zoho-Calling](https://github.com/vobiz-ai/Vobiz-Zoho-Calling) — the Node backend that Zoho calls on click-to-dial and that reports call state back as the call progresses.

<Note>
  **There is no widget to build or install per user.** Zoho draws the entire interface — its own call bar, its own incoming-call pop-up — and Vobiz runs underneath as the engine. The integration is **server-to-server**: Vobiz exposes an endpoint Zoho calls when a user clicks a phone number, and reports call state back as the call progresses.

  This makes it different from the [Zendesk](/docs/integrations/zendesk), [HubSpot](/docs/integrations/hubspot) and [Pipedrive](/docs/integrations/pipedrive) integrations, which each ship their own softphone panel.
</Note>

## What works today

| Capability | Status |
| - | - |
| **Click-to-dial** | A user clicks a number in Zoho and the call is placed |
| **Call states** | `ringing` / `answered` / `ended` reported as they happen |
| **Call logging** | Inbound and outbound written to the Zoho record |
| **Recordings** | Delivered to the call log behind a signed URL |
| **Failed dials** | Reported to Zoho as `clicktodialerror` |
| **Browser audio** | Outbound and inbound, with an Accept / Decline banner |

Zoho requires click-to-dial, call logging and call states of any provider. Transfers (blind and warm) and ringing groups (parallel and sequential) are optional extras in the PhoneBridge specification and are **not built yet**.

## How a call flows

### Outbound

The agent's browser leg comes up **first**, which is what Zoho's click-to-dial specification asks for.

<div className="my-6">
  <img className="block dark:hidden w-full max-w-2xl mx-auto" src="https://mintcdn.com/vobizai/jE0gEHDg7wcmdt3G/images/zoho/outbound-flow-light.svg?fit=max&auto=format&n=jE0gEHDg7wcmdt3G&q=85&s=c65a60e062e4e11ba3ebbd5ab145c55f" alt="Sequence diagram of a Zoho click-to-dial call across four lanes: Zoho, the Vobiz backend, the agent's browser and the customer. Zoho posts tonumber to the backend, the backend hands the number to the agent's softphone over the call-events stream, the browser sends the SIP INVITE and Vobiz dials the customer, audio flows both ways, and the backend reports callnotify ringing, answered and ended back to Zoho." width="720" height="490" data-path="images/zoho/outbound-flow-light.svg" />

  <img className="hidden dark:block w-full max-w-2xl mx-auto" src="https://mintcdn.com/vobizai/jE0gEHDg7wcmdt3G/images/zoho/outbound-flow-dark.svg?fit=max&auto=format&n=jE0gEHDg7wcmdt3G&q=85&s=b0139eb4a52510da0efae295b4815d56" alt="Sequence diagram of a Zoho click-to-dial call across four lanes: Zoho, the Vobiz backend, the agent's browser and the customer. Zoho posts tonumber to the backend, the backend hands the number to the agent's softphone over the call-events stream, the browser sends the SIP INVITE and Vobiz dials the customer, audio flows both ways, and the backend reports callnotify ringing, answered and ended back to Zoho." width="720" height="490" data-path="images/zoho/outbound-flow-dark.svg" />
</div>

<Note>
  Setting `BROWSER_FIRST_DIAL=false` reverts to **customer-first** dialling: Vobiz places the call to the customer over the REST API and bridges the agent in once they answer. That ordering is kept as a fallback because a browser-plus-phone simultaneous ring connects the call either way.

  The trade-off is audible — on customer-first the customer hears a few seconds of ringback *after* answering, while the agent leg is bridged in.
</Note>

### Inbound

A PSTN call to the attached number rings the softphone with an **Accept / Decline** banner rather than answering automatically. **Enter** accepts, **Escape** declines. The agent has 20 seconds before the caller falls through to voicemail.

Set `INBOUND_RECORD=true` to record inbound sessions.

## Connecting a Zoho organization

Zoho runs **11 datacentres** and a customer's data lives in exactly one. Domains are resolved at runtime.

<Steps>
  <Step title="Resolve the datacentre">
    `GET accounts.zoho.com/oauth/serverinfo` returns the domain list. Zoho forbids hardcoding these, and getting it wrong is grounds for rejecting a provider.
  </Step>

  <Step title="Authorize">
    The customer consents in the browser and is redirected back with a `code` and a `location` (for example `in`). Exchanging that code returns an access token, a refresh token, and the `api_domain` every later call must use.
  </Step>

  <Step title="Activate the PBX">
    `POST {api_domain}/phonebridge/v3/integrate` — once, before anything else.
  </Step>

  <Step title="Register click-to-dial">
    `POST {api_domain}/phonebridge/v3/clicktodial` with `clicktodialuri`, the endpoint Zoho will call when a user clicks a number.
  </Step>
</Steps>

<Warning>
  **`POST /phonebridge/v3/integrate` is not in Zoho's V3 documentation, and nothing works without it.** Until it is called once for an organization, every other PhoneBridge endpoint rejects that org with `PBX_NOT_INTEGRATED` — including `clicktodial`, `callnotify` and `users`.

  Zoho's own screens report the opposite while this is outstanding: Marketplace → Telephony shows the provider as *installed for all users*, and CRM offers *View Configuration*. Installed according to the UI, not integrated according to the API. The call takes no parameters and is idempotent.
</Warning>

## The PhoneBridge API

Base `{api_domain}/phonebridge/v3/`, where `api_domain` comes from the token response and is never hardcoded. Bodies are form-encoded.

<Warning>
  The auth header is **`Zoho-oauthtoken <token>`**. `Bearer` returns `401`.
</Warning>

| Endpoint | Purpose | Required params |
| - | - | - |
| `POST integrate` | Activate the PBX. Must be first | none |
| `POST clicktodial` | Register where Zoho sends dial requests | `clicktodialuri` |
| `DELETE clicktodial` | Deregister | none |
| `GET users` | List Zoho users with their `zohouser` ids | none |
| `POST callnotify` | Report a call state change | `type`, `state`, `id`, `from`, `to` |
| `POST clicktodialerror` | Report a failed dial | `from`, `to`, `code` |

### Call states

Verified against the live API, for both `type=dialed` and `type=received`:

| State | Extra params | Accepted |
| - | - | - |
| `ringing` | — | Yes |
| `answered` | — | Yes |
| `ended` | `start_time`, `duration`, `voiceuri` | Yes |
| `missed` | with and without | **No — `400`** |
| `busy`, `rejected`, `notavailable`, `noanswer` | with and without | **No — `400`** |

<Warning>
  **`missed` is documented by Zoho but rejected by their live API.** So is every other terminal state except `ended`. A missed call is therefore logged as a zero-length completed call — there is currently no way to distinguish it in the Zoho log.
</Warning>

### Timestamp format

```text theme={null}
start_time = "2026-09-15 12:00:00"       ← yyyy-MM-dd HH:mm:ss, GMT
start_time = "2026-09-15T12:00:00.000Z"  ← ISO 8601 is REJECTED
```

## Gotchas worth knowing

<Note>
  * **`callerId` on `<Dial>` is mandatory, not cosmetic.** Omit it and Vobiz refuses to create the agent leg at all — no dial-leg CDR, the call runs about three seconds and falls through to the fallback message. See [`<User>`](/docs/xml/dial/user).
  * **Ask for the microphone before the call, never during.** If the permission prompt appears while a call is ringing, the agent reads a dialog while the SIP session waits for media, and the leg is torn down before **Allow** is clicked.
  * **`session.connection` is null on an incoming SIP session.** Reading it throws inside the `newRTCSession` handler and aborts before `answer()`, so the call rings in the browser forever. Bind audio on the `peerconnection` event instead.
  * **Recordings need a signed URL.** Zoho fetches `voiceuri` with no Vobiz credentials of its own, and comes back for the audio long after the agent session has gone — so the HMAC signature is what authenticates the request, and the fetch itself runs on the account credentials.
  * **Ignore `sip_registered`.** It never flips to `"true"` for WebSocket registrations, on any endpoint. It is not evidence of anything — gate on JsSIP's `registered` event.
</Note>

Three JsSIP settings are required and none are obvious from their symptoms:

| Setting | Symptom without it |
| - | - |
| `session_timers: false` | `422`, surfaced as the opaque cause *SIP Failure Code*, and no CDR at all |
| `pcConfig.iceServers` | Host-only candidates, *Incompatible SDP*, CDR billed `0s` |
| Space-free `user_agent` | Vobiz interpolates it unescaped into a gateway URI; JsSIP's default contains a space |

## Current limitations

<Warning>
  This integration is not yet generally available. Outstanding before launch:

  * **Token storage is single-tenant and ephemeral.** It works for one organization; real multi-tenant operation needs a database with encryption at rest. On an ephemeral filesystem the stored org does not survive a restart.
  * **The OAuth redirect URI registered with Zoho does not yet resolve**, so the authorization round-trip cannot complete unattended.
  * **The backend has no authentication on its own routes.**
  * **No Zoho-user to Vobiz-agent mapping.** One registration serves one agent. The `zohouser` ids are obtainable, so per-user addressing is buildable — it is also the prerequisite for transfers and ringing groups.
  * **No transfers or ringing groups.**
</Warning>

## Next steps

* The same calling in other CRMs: [Zendesk](/docs/integrations/zendesk), [HubSpot](/docs/integrations/hubspot), [Pipedrive](/docs/integrations/pipedrive), [Freshdesk](/docs/integrations/freshdesk)
* Reference: [`<Dial>`](/docs/xml/dial), [`<User>`](/docs/xml/dial/user), [SIP endpoints](/docs/endpoint/endpoint-object), [CDRs](/docs/cdr/get-cdr)
* Zoho's [PhoneBridge V3 developer documentation](https://www.zoho.com/phonebridge/developer/v3/)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.