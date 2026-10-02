> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What Is a Call Leg? A-Leg vs B-Leg in Programmable Voice

> A call leg is one connection between the platform and one party. Here's what A-leg and B-leg mean, how calls get bridged, and why legs matter.

*June 16, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

If you've read about [call transfers](/docs/blogs/context-aware-call-transfers), [escalations](/docs/blogs/intelligent-call-escalations), or looked at a CDR, you've run into terms like **A-leg**, **B-leg**, and "transfer the caller leg." A **call leg** is one of the most useful concepts in programmable voice, and one of the least explained. This post fixes that: what a leg actually is, the difference between the A-leg and the B-leg, how a single phone call ends up with two (or more) legs, and why the distinction shows up everywhere, in transfers, recordings, billing, and call events.

<Note>
  **Key takeaways**

  * A **call leg** is a single connection between the voice platform and **one** party. A normal two-party call has **two legs**.
  * The **A-leg** is the original/first leg (the caller side); the **B-leg** is the leg the platform creates to reach the other party (the callee). **Bridging** joins them so the two people can talk.
  * Legs are individually addressable, each has its own **UUID**, so you can transfer, redirect, record, bill, and track *one* leg without touching the other.
  * On [Vobiz](/docs/introduction), you target legs explicitly: the [Transfer API](/docs/call/transfer-call) takes `legs=aleg` / `bleg` / `both`, the [CDR](/docs/cdr) bills **per leg**, and a child leg points to its parent via `parent_call_uuid` (the A-leg).
</Note>

## What is a call leg?

A **call leg** (sometimes just "leg") is a single, independent connection between the telephony platform and one endpoint, one phone, SIP device, or carrier. Think of the platform as sitting in the middle: every party on the call has their own leg into it.

That middle position is the key idea. Modern voice platforms run as a **back-to-back user agent (B2BUA)**: instead of connecting two phones directly, the platform terminates a separate call to each party and then *joins* those calls in the middle. Each of those separate calls is a leg. At the protocol level, a leg corresponds to a [SIP dialog](https://www.rfc-editor.org/rfc/rfc3261) (one `INVITE`/`200 OK`/`ACK` exchange and the media that follows). Because each leg is its own dialog with its own identity, the platform can control them independently, which is exactly what makes voice programmable.

A simple way to hold it: **a "call" is what the humans experience; "legs" are how the platform actually wires it up.** One conversation between two people is usually two legs bridged together.

## A-leg vs B-leg

In a two-party programmable call, the two legs have conventional names:

| | A-leg | B-leg |
| - | - | - |
| **What it is** | The original / first leg | The leg the platform creates to reach the other party |
| **Inbound call** | The caller who dialed your number | The agent/number you `<Dial>` to connect them |
| **Outbound call** | The call you initiated to the customer | A third party you then bridge in |
| **Identity** | The "parent" leg; its UUID is the parent | A "child" leg; references the parent |
| **Typical role** | Caller | Callee |

The **A-leg is the side that exists first**; the **B-leg is the side that gets added to complete the connection**. When the B-leg answers, the platform **bridges** the two legs, audio from the A-leg flows to the B-leg and back, and the two people are talking. Until that bridge happens they're two separate calls that simply share a session.

## How a call ends up with two legs

Walk through a typical inbound flow:

1. A customer (`+1 415 555 0142`) dials your Vobiz number. That inbound call is the **A-leg**.
2. Vobiz invokes your [answer URL](/docs/xml/overview/how-it-works); your app returns XML, say a [`<Dial>`](/docs/xml/dial) to an agent (`+1 202 555 0188`).
3. Vobiz places a *new* outbound call to the agent. That's the **B-leg**.
4. When the agent picks up, Vobiz **bridges** the A-leg and B-leg. Now the customer and agent hear each other; the audio rides over both legs through the platform.

An outbound campaign is the mirror image: the call you place to the customer via the [Make Call API](/docs/call/make-call) is the A-leg, and if your flow dials a third party (a human agent, a supervisor), that becomes the B-leg.

### Parent, child, and conference legs

Because the B-leg is created *from* the A-leg, platforms model the relationship as **parent → child**. On Vobiz, the call object exposes `parent_call_uuid`, which holds the **UUID of the A-leg**, so a child (B-) leg always knows its parent. This is how you correlate the two halves of one conversation in logs and webhooks.

A [conference](/docs/xml/conference) generalizes the idea: instead of one A-leg bridged to one B-leg, *each* participant has their own leg into a shared room, three participants means three legs, all mixed in the conference rather than directly bridged. (This is also why a conference recording usually can't cleanly separate every party onto its own channel the way a two-leg call can.)

## Why call legs matter

The reason "leg" is worth learning is that almost every advanced voice operation is **scoped to a leg**, not to the whole call:

* **Transfers and redirects.** You rarely want to move *everyone*. You transfer the **A-leg** (send the caller somewhere new while the agent leg ends) or the **B-leg** (swap the agent without dropping the caller). On Vobiz the [Transfer API](/docs/call/transfer-call) makes this explicit with `legs=aleg` (caller), `bleg` (callee), or `both`, and when you transfer one leg, the other keeps running its current flow. (See [context-aware call transfers](/docs/blogs/context-aware-call-transfers).)
* **Billing and CDRs.** Each leg is metered separately, an inbound A-leg and an outbound B-leg are two different rated segments. Vobiz's [CDR](/docs/cdr) records a **per-leg `cost`**, with the originating number and destination per leg, so reconciliation and cost attribution work at leg granularity.
* **Recording.** Recording the *bridge* with each party on a separate channel (stereo) only works because the platform sees the A-leg and B-leg as distinct audio sources, which is what makes per-speaker transcription clean. (See [call recording APIs](/docs/blogs/call-recording-apis-compliant-pipelines).)
* **Call events and status.** Ring, answer, and hangup events fire per leg, the A-leg can be live while the B-leg is still ringing or has failed. A [`<Dial>` status callback](/docs/xml/dial) reports how the B-leg ended (`completed`, `busy`, `no-answer`, `failed`), which is exactly the signal you use to escalate or retry. Hangup causes are likewise per leg (see [hangup causes](/docs/concepts/hangup-causes)).
* **Answering machine detection.** AMD runs on the **B-leg** (the party you dialed), so your agent or message only starts once that leg is confirmed human. (See [automated calling & AMD](/docs/blogs/automated-calling-answering-machine-detection).)

Miss the leg distinction and these all get confusing, "why did my transfer drop the customer?" is almost always "you transferred the wrong leg."

## How Vobiz exposes call legs

Vobiz gives you direct, per-leg control:

* **Address a leg by UUID.** Every leg has its own `call_uuid`; a child leg references its parent through `parent_call_uuid` (the A-leg). Pass the UUID of the leg you mean to act on.
* **Transfer per leg.** [`POST .../Call/{call_uuid}/`](/docs/call/transfer-call) with `legs=aleg` / `bleg` / `both` and a URL per leg redirects exactly the side you intend, leaving the other side untouched unless you choose `both`.
* **Bridge with `<Dial>`.** [`<Dial>`](/docs/xml/dial) creates and bridges the B-leg from an active A-leg; its `action` URL reports the B-leg's outcome so your app can react.
* **Per-leg records.** The [CDR API](/docs/cdr) returns per-leg cost and metadata, so each leg is independently auditable.

Because legs are first-class, you compose transfers, escalations, conferences, and recording flows precisely, on the rails Vobiz provides, without managing raw SIP dialogs yourself.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is a call leg in simple terms?">
    A call leg is one connection between the voice platform and a single party. The platform sits in the middle and has a separate leg to each person, so a normal two-person call is actually two legs joined ("bridged") together.
  </Accordion>

  <Accordion title="What is the difference between the A-leg and the B-leg?">
    The A-leg is the original/first leg, the caller side (for an inbound call, the person who dialed your number; for an outbound call, the call you placed to the customer). The B-leg is the leg the platform creates to reach the other party (the callee). Bridging the A-leg and B-leg lets the two people talk.
  </Accordion>

  <Accordion title="Is a call leg the same as a call?">
    No. A "call" is the conversation the people experience; "legs" are how the platform wires it up. One two-party call is typically two legs (A and B) bridged in the middle, and each leg has its own UUID, billing, and events.
  </Accordion>

  <Accordion title="Why would I transfer only one leg?">
    To change one side without disturbing the other, transfer the B-leg to swap the agent while keeping the caller connected, or transfer the A-leg to send the caller to a new flow. On Vobiz you choose `legs=aleg`, `bleg`, or `both`; transferring one leg leaves the other running.
  </Accordion>

  <Accordion title="How are call legs billed?">
    Per leg. An inbound A-leg and an outbound B-leg are separate rated segments, and Vobiz's CDR records a per-leg cost, so you can attribute and reconcile charges at leg granularity rather than per whole call.
  </Accordion>

  <Accordion title="How many legs does a conference call have?">
    One per participant. Instead of a single A-leg bridged to a single B-leg, each participant has their own leg into a shared conference room, so a five-person conference is five legs mixed together.
  </Accordion>
</AccordionGroup>

## Sources

* [RFC 3261 - SIP: Session Initiation Protocol (dialogs)](https://www.rfc-editor.org/rfc/rfc3261)
* [Back-to-back user agent (B2BUA)](https://en.wikipedia.org/wiki/Back-to-back_user_agent)
* [Vobiz - Transfer a Call](/docs/call/transfer-call) · [Make Call API](/docs/call/make-call) · [`<Dial>`](/docs/xml/dial) · [CDR](/docs/cdr)

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and place your first programmable, multi-leg call in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.