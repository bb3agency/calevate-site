> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Mastering Call Transfers in 2026: The Switch to Context-Aware Programmable Voice

> Call transfer in 2026: blind vs warm vs supervised, the SIP REFER/Replaces/UUI protocol layer, programmable per-leg transfer, and AI handoff.

*June 16, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

A call transfer looks like a button. Underneath, it's one of the harder things in telephony to do *well*, because moving a live conversation from one party to another without dropping it, and without making the customer repeat everything, touches signaling protocols, call-control APIs, and increasingly, an AI agent's conversation state. The difference between a 2016 contact center and a 2026 one isn't whether they can transfer a call; it's whether the transfer carries **context**. This guide covers call transfer end to end: the three types, the SIP protocol layer (REFER, Replaces, UUI), how programmable platforms transfer a live call leg, and the shift to **context-aware transfer** that voice AI now demands.

<Note>
  **Key takeaways**

  * There are three transfer types: **blind/cold** (hand off immediately, no introduction), **warm/attended/consultative** (talk to the receiving party first), and **supervised** (a third party coaches/monitors).
  * At the protocol layer, [RFC 5589](https://www.rfc-editor.org/rfc/rfc5589) defines the roles and uses the **REFER** method ([RFC 3515](https://www.rfc-editor.org/rfc/rfc3515.html)) plus the **Replaces** header ([RFC 3891](https://www.rfc-editor.org/rfc/rfc3891.html)) for attended transfer; progress is reported via `NOTIFY` bodies of type `message/sipfrag`.
  * Programmable platforms transfer by **redirecting a specific call leg** (A-leg, B-leg, or both) to a new URL that returns call-control XML; a **conference room** is the standard staging area for a warm transfer.
  * **Context-aware transfer** is the 2026 theme: carry context across the handoff via the standardized **User-to-User** SIP header ([RFC 7433](https://www.rfc-editor.org/rfc/rfc7433.html)), custom SIP X-headers, or your own backend, so the receiving human (or agent) starts informed.
  * On [Vobiz](/docs/introduction), the [Transfer Call API](/docs/call/transfer-call) redirects `aleg`/`bleg`/`both` to fresh XML, and [`<Conference>`](/docs/xml/conference) is the warm-transfer staging area, the rails under your [Vapi](/docs/integrations/vapi-dashboard)/[Retell](/docs/integrations/retellai-dashboard) agent's handoff.
</Note>

## The three types of call transfer

Every transfer is a variation on "connect the caller to someone else," but the *experience* and the engineering differ sharply.

| Type | What happens | Caller experience | When to use |
| - | - | - | - |
| **Blind / cold** | The transferor hands the call to the target and drops immediately, no introduction | May land on someone with zero context; risk of re-explaining | High-volume, low-complexity routing where any qualified agent can help |
| **Warm / attended / consultative** | The transferor first speaks privately with the target (caller on hold), briefs them, then completes the handoff | Smooth, "they already know why I'm calling" | High-value, sensitive, or complex issues; escalations |
| **Supervised** | A third party (supervisor) monitors, whispers to, or coaches one participant | Often unaware of the coach | Training, QA, live deal support |

The blind transfer is cheap and fast but is the source of the classic customer complaint, *"I had to explain my problem three times."* The warm transfer fixes that at the cost of agent time. Context-aware transfer (below) aims to give you the *quality* of a warm transfer at closer to the *cost* of a blind one, by moving the context with the call instead of re-narrating it.

## The protocol layer: how SIP transfer actually works

Under any programmable abstraction, transfer on a SIP network follows a small, stable set of IETF standards. [RFC 5589](https://www.rfc-editor.org/rfc/rfc5589) (BCP 149) is the current best practice and defines three roles: the **Transferor** (the party initiating the transfer), the **Transferee** (the party being transferred, usually the caller), and the **Transfer Target** (the new destination).

### REFER (RFC 3515)

The mechanism is the **REFER** method. Per [RFC 3515](https://www.rfc-editor.org/rfc/rfc3515.html), "the REFER method indicates that the recipient… should contact a third party using the contact information provided in the request." A REFER **must contain exactly one `Refer-To` header field value** (zero or more than one is a `400 Bad Request`). In transfer terms: the Transferor sends a REFER to the Transferee whose `Refer-To` points at the Transfer Target, causing the Transferee to issue a fresh `INVITE` to that target.

A REFER also **implicitly establishes a subscription to the `refer` event**, and the recipient reports progress back with `NOTIFY` messages whose body is of type `message/sipfrag`, beginning with a SIP response status line (`100 Trying`, `200 OK`, …) that tells the transferor whether the referred call is pending, succeeded, or failed. (RFC 4488 later let you suppress that subscription with `Refer-Sub: false`, and RFC 6665 refined the event mechanics, refinements, not contradictions.)

### Replaces (RFC 3891) for attended transfer

A blind transfer is just a REFER. An **attended** transfer needs more: the Transferor has *two* live dialogs (the caller on hold, the target on a consultation call) and must fuse them. That's what the **Replaces** header ([RFC 3891](https://www.rfc-editor.org/rfc/rfc3891.html)) does, it "logically replaces an existing SIP dialog with a new SIP dialog," enabling attended transfer in a distributed, peer-to-peer way without a central controller. In RFC 5589's attended-transfer flow, the Transferor places both parties on hold and sends a REFER whose `Refer-To` URI embeds an **escaped `Replaces`** parameter; the Transferee then issues an `INVITE` that replaces the consultation dialog, and the leftover dialogs are torn down with `BYE`. Replaces and REFER are independent mechanisms that are *commonly combined* for attended transfer, neither requires the other.

A programmable platform typically runs as a **B2BUA** (back-to-back user agent): rather than passing a raw REFER through to your app, it terminates the signaling on both sides and re-originates the legs, which is exactly what lets it expose transfer as a simple REST call instead of raw SIP.

## Programmable transfer: redirecting a live call leg

On a programmable platform you don't hand-craft REFER, you tell the platform, via REST, to move a leg of a live call to new instructions, and it speaks the SIP for you. Two patterns are standard:

* **Redirect a specific leg.** A modify-call REST endpoint points a live leg at a new URL that returns call-control XML. Because each leg is addressable on its own, you can target the A-leg (caller), the B-leg (callee), or both, commonly via a `legs` parameter (`aleg` / `bleg` / `both`) with a URL per leg. (New to A-leg/B-leg? See [what is a call leg?](/docs/blogs/what-is-a-call-leg).)
* **Bridge with a dial/connect verb.** A `<Dial>`-style verb connects the current call to a new party, it bridges an *existing* call rather than originating one. An `action` URL on it can take control of the surviving leg after the other party hangs up, which is how you sequentially re-route.

That per-leg redirect model is the clean abstraction over the SIP plumbing, and it's exactly what Vobiz implements (below).

## Warm transfer with a conference as the staging area

The standard pattern for a *warm* transfer is to use a **conference room as the meeting point**: place the original caller into a conference (named, say, by the caller's call ID), then add the receiving agent on a new leg that joins the same conference, so all three are briefly bridged. Configure the transferring agent so they can **drop off without ending the conference** (e.g. `endConferenceOnExit="false"`), while the caller and the new agent end the call when either of them leaves. The result: the original agent introduces the caller, then leaves; the caller and new agent continue seamlessly.

### A worked context-aware warm transfer

Putting the pieces together, here's the flow for an AI agent escalating to a human with full context:

1. The AI agent decides to escalate and writes a short summary + the caller's ticket ID to your backend, keyed by the call UUID.
2. Your backend transfers the **caller leg** into a conference (e.g., named by the call UUID) with hold music, so the customer waits in a staged room rather than hearing silence.
3. Your backend places an outbound leg to the next available human agent that joins the same conference, and screen-pops the summary + ticket to the agent's desktop using the call UUID as the key.
4. The agent reads the context, then the conference bridges agent and caller. (If you ran a bot-to-human *warm* handoff, the bot can stay until the human is briefed, then leave.)
5. On completion, the transient legs tear down and you log transfer success, the receiving agent's first words are *"I see this is about order #1234,"* not *"How can I help?"*

Notice nothing here required raw SIP, the platform's per-leg redirect + conference primitives plus your own context store deliver a context-aware transfer with a few API calls.

## Supervised / whisper (coach) transfer

Supervision is implemented inside the conference too. Conference platforms expose a **coach / whisper** capability: a supervisor joins and is heard *only by the agent* (one-way private audio), guiding them mid-call without the customer hearing. The same conference lets a supervisor also **monitor** silently (joined muted) or **barge in** (unmute), all without re-connecting the call.

## Context-aware transfer: the 2026 shift

Here's the real story of 2026: the transfer *mechanism* is solved; the *context* is the frontier. A blind transfer drops the caller on a stranger who knows nothing, so the caller re-explains, handle time balloons, and CSAT drops. Context-aware transfer carries the "who is this and why are they calling" payload *with* the call.

The IETF-standardized way to do this is the **User-to-User** SIP header. [RFC 7433](https://www.rfc-editor.org/rfc/rfc7433.html) defines it "to transport User-to-User Information (UUI)", an opaque, application-level payload "inserted by an application initiating the session and utilized by an application accepting the session," with parameters for the UUI package (`purpose`), content (`content`), and encoding (`enc`). Crucially, the RFC notes UUI "is widely used in the Public Switched Telephone Network (PSTN) today for contact centers" and is "transition\[ing] from ISDN to SIP", so this isn't theoretical, it's how PSTN contact centers already pass a caller's account ID or queue context through a transfer.

UUI's practical limit is small (on the order of \~128 characters), so in practice teams complement it with **custom SIP X-headers** for larger payloads, and, for anything substantial, with an out-of-band lookup: pass a small key (call ID, ticket ID) in the header and have the receiving system fetch the full record. The three layers of context-aware transfer, then, are:

1. **A standardized token** (UUI) for small, portable context that survives carrier hops.
2. **Custom X-headers** for larger structured payloads where your SBC/carrier permits.
3. **A backend key + screen-pop**, the call carries an ID; your CRM/agent desktop pops the full customer record and history when the call lands.

## The voice-AI angle: handing off with full context

This is where context-aware transfer stops being a contact-center nicety and becomes essential. An AI voice agent that can't hand off cleanly creates the dreaded **"AI dead-end"**, the bot can't help, can't escalate gracefully, and the customer rage-quits. A good AI→human handoff does three things:

1. **Detects the need to escalate** (low confidence, negative sentiment, explicit "agent" request, or a compliance-sensitive topic).
2. **Warm-transfers to a human** using the conference-staging pattern, so the human is bridged in, not cold-dialed.
3. **Hands over the conversation context**, a summary or transcript of what the bot already collected, so the human opens with "I see you're calling about your delayed order #1234" instead of "How can I help you?"

The [agent-to-agent handoff](/docs/solutions/agent-to-agent-handoff) pattern, where one specialized AI agent transfers to another (and ultimately to a human), is now a first-class design in voice-AI frameworks (see, e.g., [LiveKit's handoff pattern for voice agents](https://livekit.com/blog/handoff-pattern-voice-agents)). The infrastructure requirement underneath all of it is the same: redirect a leg, stage a conference, and pass a context payload, which is exactly the transfer toolkit above.

## How Vobiz handles call transfer

[Vobiz](/docs/introduction) is the telephony **infrastructure** under your contact center or AI agent, it runs the transfer; your app owns the routing and the context. It powers voice-AI builders (Vapi, Retell, LiveKit, Pipecat, ElevenLabs) and ships no agent of its own.

* **Per-leg programmable transfer.** The [Transfer Call API](/docs/call/transfer-call) (`POST .../Call/{call_uuid}/`) takes a `legs` parameter, `aleg` (caller), `bleg` (callee), or `both` (default `aleg`), with `aleg_url`/`bleg_url` (and `aleg_method`/`bleg_method`) returning fresh XML. You transfer exactly the leg you mean to.
* **In-XML redirect.** [`<Redirect>`](/docs/xml/redirect) hands call control to a new URL mid-flow (everything after it is skipped), ideal for conditional IVR branching and routing decisions computed live by your backend.
* **Warm transfer via conference.** [`<Conference>`](/docs/xml/conference) with `startConferenceOnEnter` and `endConferenceOnExit` is the staging area, bridge the caller and the receiving agent, let the transferring agent introduce and drop, exactly the documented warm-transfer pattern.
* **Trusted identity on the bridged leg.** The [`<Dial>` `callerId`](/docs/xml/dial) attribute sets a number you own on the new leg.
* **Context is yours to carry.** Because every routing decision is your answer URL returning XML, you decide what context travels, pass a key in the request, screen-pop the record, and (for AI) hand your human the bot's transcript/summary.
* **Built for real-time.** Sub-80 ms single-hop media and [bidirectional streaming](/docs/concepts/streaming-websockets) with barge-in keep a transferred AI call responsive. (Need to gate that handoff on a real human first? See [automated calling & AMD](/docs/blogs/automated-calling-answering-machine-detection).)

## Metrics & best practices

Track these to know whether your transfers are actually helping:

* **Transfer rate** - % of calls transferred. High rates can signal mis-routing upstream (fix the IVR/agent, not the transfer).
* **Transfer success rate** - % of transfers that reach the intended party and stay connected (vs dropped mid-transfer).
* **Average handle time (AHT)** - context-aware transfer should *lower* AHT on the receiving leg because the customer doesn't re-explain.
* **"Repeat information" rate** - survey or detect how often customers restate their issue; the clearest signal of context loss.
* **First-contact resolution (FCR)** - warm, context-rich transfers raise it.

Best practices: **prefer warm or context-aware transfer for anything complex**; **always pass at least a correlation key** so the receiving system can screen-pop; **use a conference for handoffs** so no one is cold-dropped; **keep UUI payloads small** and look up the rest; and for AI, **never transfer without a summary**, the whole point is that the human starts informed.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is the difference between a blind transfer and a warm transfer?">
    A blind (cold) transfer hands the call to the target and the transferring party drops immediately, with no introduction, so the receiving party may have no context. A warm (attended/consultative) transfer lets the transferring party speak privately with the target first, brief them, and then complete the handoff, so the customer doesn't have to re-explain.
  </Accordion>

  <Accordion title="How does call transfer work in SIP?">
    SIP transfer (per RFC 5589) uses the REFER method (RFC 3515): the transferor sends a REFER whose Refer-To header points at the new destination, causing the transferee to INVITE that target. Attended transfer adds the Replaces header (RFC 3891) to fuse two existing dialogs. Progress is reported via NOTIFY messages with a message/sipfrag body.
  </Accordion>

  <Accordion title="What is context-aware call transfer?">
    Context-aware transfer carries the caller's context, identity, reason for calling, account or ticket ID, or an AI conversation summary, across the transfer so the receiving party starts informed. It's done with the standardized SIP User-to-User (UUI) header (RFC 7433), custom SIP X-headers, or by passing a key that triggers a CRM screen-pop.
  </Accordion>

  <Accordion title="How do I transfer only the caller (A-leg) and not the agent?">
    On Vobiz, call the Transfer Call API with `legs=aleg` and an `aleg_url` that returns the new XML; the caller leg is redirected while the other leg is untouched. Use `bleg` for the callee or `both` to redirect each leg to its own URL.
  </Accordion>

  <Accordion title="How does an AI voice agent transfer a call to a human with context?">
    The agent detects it needs to escalate, warm-transfers the caller into a conference where the human is bridged in, and hands the human the conversation transcript or summary (via your backend or a context header) so they open already knowing the issue, avoiding the "AI dead-end" and the customer repeating themselves.
  </Accordion>

  <Accordion title="What is a supervised or whisper transfer?">
    A supervised/whisper (coaching) transfer lets a third party, usually a supervisor, privately speak to one participant without the others hearing. It's implemented in a conference: the supervisor joins and is heard only by the coached agent (a coach/whisper setting), so the customer never hears them.
  </Accordion>
</AccordionGroup>

## Sources

* [RFC 5589 - SIP Call Control: Transfer (BCP 149)](https://www.rfc-editor.org/rfc/rfc5589)
* [RFC 3515 - The SIP REFER Method](https://www.rfc-editor.org/rfc/rfc3515.html)
* [RFC 3891 - The SIP "Replaces" Header](https://www.rfc-editor.org/rfc/rfc3891.html)
* [RFC 7433 - Transporting User-to-User Call Control Information in SIP](https://www.rfc-editor.org/rfc/rfc7433.html)
* [RFC 4488 - Suppression of SIP REFER Implicit Subscription](https://www.rfc-editor.org/rfc/rfc4488.html)
* [Vobiz - Transfer a Call](/docs/call/transfer-call) · [`<Redirect>`](/docs/xml/redirect) · [`<Conference>`](/docs/xml/conference)
* [LiveKit - The handoff pattern for voice agents](https://livekit.com/blog/handoff-pattern-voice-agents)

<Card title="Build transfers on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and wire a context-aware transfer in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.