# Inbound call handling in India — what a research pass could and could not establish

**Date:** 21 September 2026
**Class:** FOUNDER-RELAYED RESEARCH. A Comet run over operator, regulator and vendor
pages, relayed by the founder. Every host below is egress-blocked from the build
container, so nothing here was opened from this repo. Treat each finding at the class its
own line states, never higher.

**Why this file exists.** Three product decisions were waiting on facts nobody here could
read: whether a forwarded Indian number carries simultaneous calls, whether a business can
keep its number on a trunk, and how a live caller is handed to a human. One is answered,
one is answered badly, and one is NOT ANSWERABLE from published sources — and that last
result is the most useful of the three, because it stops us designing on a guess.

---

## 1. Call forwarding and concurrency — NOT STATED, and that is the finding

The research looked at Jio, Vi, Airtel and BSNL call-forwarding help pages, TRAI's
regulations index and DoT's Telecom Act pages. **No Indian operator document and no
TRAI/DoT regulation states what happens when several callers dial a number that has
unconditional forwarding set.** Not for CFU vs CFB vs CFNRy, not per operator, not mobile
vs landline, and not where the limit sits.

**EVIDENCE CLASS: NOT STATED.** The research offered an inference — that CFU redirects each
call independently in the home network, so the ceiling is usually the destination's own
line capacity — and labelled it an inference. It is recorded here as one and may not be
relied on.

**CONSEQUENCE FOR US.** The product claim "we answer every call" rests on this, and it
cannot be settled by reading. It must be MEASURED: set unconditional forwarding on one
Indian number to a number we control, have three people dial it in the same second, and
record how many legs arrive. That is an afternoon's work and it decides whether forwarding
is a viable onboarding path at all.

Until it is measured, no client-facing surface may state or imply that forwarding carries
concurrent calls.

## 2. Keeping an existing number on a SIP trunk — harder than assumed

Tata Tele Business Services' own SIP Trunk FAQ: **"No direct migration; a new SIP Trunk
order is required."** (VENDOR-PUBLISHED, founder-relayed.)

Jio publishes SIP trunking "scaling from 10 to 5,000 simultaneous call sessions" and Airtel
"handle simultaneous calls with just 1 number", both VENDOR-PUBLISHED — but neither states
whether an existing number can be moved onto one, and MNP is documented for mobile-to-mobile
porting only.

**So the onboarding shape we assumed for a client who will not change their number — keep
the number, add channels — is NOT established.** It may still be possible via a fixed-line
DID port with a particular operator; nobody has shown that it is.

## 3. Transferring a live caller — the finding that is easy to misread

Plivo documents SIP REFER for inbound transfer, quoted by the research:

> "A caller dials your Plivo number, Plivo routes it to your AI agent or PBX, and your
> endpoint sends REFER to hand off to a human agent. Plivo bridges the caller to the
> transfer target and disconnects your endpoint."

**THIS DOES NOT APPLY TO OUR ARCHITECTURE, AND READING IT AS A SOLUTION WOULD BE A
MISTAKE.** SIP REFER is sent BY A SIP ENDPOINT. Ours is not one: `voice_worker/carrier.py`
builds a `FastAPIWebsocketTransport` over a WebSocket media stream, and the word SIP does
not appear in that module. We have no SIP leg from which to send a REFER.

The same research names a second Plivo path — a Voice API transfer against the live call —
but does not quote its endpoint, method or parameters. **That one, not REFER, is the
mechanism our architecture would use, and it remains UNREAD.**

Other Indian providers documented as transferring to an external mobile, all
VENDOR-PUBLISHED and all platform-side bridges rather than REFER: Acefone
(`type: 4` with `intercom: "<mobile>"`), Knowlarity (`{"type":"transfer","data":
{"destination":"+91…"}}`). Exotel's public docs name no single transfer verb; the research
found only flow/Connect-applet SIP handoff. Ozonetel exposes a flow node, no named API.

**No provider documents a special regulatory charge for the second leg** — it bills as an
ordinary outbound minute.

## 4. Concurrency pricing — useful, and cheap

Market sources put Indian SIP trunk channels at **₹350–700 per channel per month**
(REPORTED — market commentary, not an operator price card):

| Channels | Monthly |
|---|---|
| 5 | ₹1,750 – ₹3,500 |
| 10 | ₹3,500 – ₹7,000 |
| 30 | ₹10,500 – ₹21,000 |

No TRAI tariff order governs this; it is commercial.

## 5. Regulatory — an AI answering inbound carries no extra duty

The research found **no TRAI or DoT clause imposing an obligation on a business because an
AI rather than a human answers an inbound call**. TCCCPR governs UNSOLICITED commercial
communication, which is outbound by definition; the AI-disclosure requirement the research
found is stated in an outbound context. A caller who dialled the business initiated the
call.

**EVIDENCE CLASS: NOT STATED (absence of an obligation), from a research pass over TRAI and
DoT indexes.** An absence found by searching is weaker than a rule read, and this one has
not been checked by anybody qualified.

**IT CHANGES NOTHING ABOUT WHAT WE DO.** Hard rule 5 is ours, not theirs: an agent answers
truthfully when asked whether it is an AI or whether the call is recorded, inbound
included. We do not narrow a promise because a regulator turns out not to compel it.

---

## What must be measured, because reading has been exhausted

1. **Forwarding concurrency** (§1). Three simultaneous callers to a forwarded number.
   Blocks: whether "keep your number, forward to us" is a viable onboarding path.
2. **The Plivo Voice API transfer** (§3). Endpoint, method, parameters, and what the
   caller hears. Blocks: `PIPECAT_CAPABILITIES.transfer`, and therefore whether a roster
   can ever be honoured on our own runtime.
3. **Whether any Indian operator will port a fixed number onto a trunk** (§2). Blocks: the
   onboarding shape for a client who will not change their number.
