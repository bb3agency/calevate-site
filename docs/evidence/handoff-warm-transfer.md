# Handing a live caller to a person: what is achievable, and what is not (D-533)

**Question asked (the founder, 4 Sep 2026):** *"if the call is to be forwarded to a real
human then how is it handled? And to which number is the agent supposed to forward the call
to? can it connect to a list of numbers ... the ai agent first gives context about what
happened so far in the call and why it is handing the call to a human ... it should work
like that with industry standards."*

**Answer in one paragraph.** The industry standard he is describing is a WARM (attended)
transfer with a *call whisper* — the person answering hears a short summary while the caller
still hears ringing, and presses a key to accept. It is a real, ordinary telephony feature
and it is **not achievable on this deployment**, because performing it requires control of
the caller's telephony leg and this repository holds no telephony credential of any kind.
What ships instead is a **cold (blind) transfer to ONE number chosen by us before the call**,
from an ordered roster, honouring business hours, with the handover recorded and a call-back
booked when nobody answers. This document records why, at the evidence class each claim
carries, so the next person does not re-derive it — or, worse, promise the whisper.

---

## 1. Who places the transfer leg

**The ENGINE does.** Established from two independent sources that agree:

* **VERIFIED-OSS** — `bolna-ai/bolna@cd2e192`, `bolna/agent_manager/task_manager.py:3107-3360`,
  read 4 Sep 2026 (raw.githubusercontent.com is reachable from this container; `www.bolna.ai`
  is not). The `transfer_call` branch does **not** bridge anything itself. It POSTs a payload
  — `{call_sid, provider, stream_sid, from_number, execution_id, …}` — to a URL, and
  *whatever answers that URL performs the redirect at the telephony layer*. When the tool
  carries no `url`, the URL comes from the deployment's own `CALL_TRANSFER_WEBHOOK_URL`
  (`:3181-3183`), i.e. the vendor's own transfer service. The log line at `:3266` reads
  *"Response from the server after call transfer"*, and the exception handler reads
  *"Transfer webhook did not respond (call likely redirected)"*.
* **VERIFIED-VENDOR-DOCS** — the pinned mirror. `TransferCallData`
  (`bolna-findings/mirror/pages/api-reference/agent/v2/get_agent_execution.md:270-328`)
  models the transferred leg as an object of its own with `provider_call_id` ("Unique ID of
  the call from the Telephony Provider"), `from_number` ("Phone number which is making the
  transfer call"), `duration`, `cost` and `recording_url`. A leg with its own provider call
  id, its own duration and its own cost is a leg somebody else placed.

**Could we take it over?** In principle yes: `TransferCallToolParams.url` is documented as
*"Link of the URL to control the transferring of call"*
(`.../api-reference/agent/v2/create.md:1174`) and the OSS honours it. Pointing it at us is
the seam through which a warm transfer, a whisper and a real hunt list would all become
possible. **It is not taken, and the reason is not a preference.** Performing the redirect
means calling the telephony provider's API for the account that owns the live call, and this
repository holds no such credential: `grep` finds no Plivo or Exotel client, no auth id, no
auth token, and `campaigns/provisioning.PROVISIONING_IMPLEMENTED` is `False` (D-05 puts the
carrier account on the client's side, connected to the engine — the vendor's own
"connect your Plivo account" flow). An endpoint that received that POST and could not
redirect would leave the caller listening to an agent that has been told the transfer
succeeded, which is worse than the cold transfer we ship.

## 2. Why there is no whisper

A whisper is a property of the leg the caller is on. The mechanism, on the carrier this
product runs on:

* **VERIFIED-VENDOR-SDK** — `plivo/plivo-python@master`, read 4 Sep 2026.
  `plivo/xml/DialElement.py` carries `confirm_sound`, `confirm_key` and `confirm_timeout`;
  `plivo/resources/calls.py:299-338` is the live-call redirect (`POST /Call/{call_uuid}`
  with `legs` ∈ {aleg, bleg, both} and `aleg_url`). So the shape is: redirect the caller's
  leg to XML of ours that `<Dial>`s the destination with a `confirmSound` URL — the human
  hears our summary while the caller hears ringing, and a key press accepts.
* **WEB-SEARCH RELAY** (`plivo.com` is egress-blocked from this container, 403 on CONNECT,
  measured 4 Sep 2026): Plivo's own "Confirm to answer call" page describes `confirmKey` as
  *"the digit to be pressed by the called party to accept the call"* and `confirmSound` as a
  URL requested for a `Play`, `Speak` or `Wait` element. This corroborates the SDK reading;
  no page was fetched, and nothing in our code moves on the relay alone.

**Every one of those calls needs credentials we do not have, on an account that is not
ours.** Nothing in the engine's own documented surface plays audio to the called party:
the transfer tool has a *pre-tool message* (what the agent says to the CALLER) and a
*pre-call webhook* (a notification to OUR SERVER). Neither reaches the human's ear.

**What ships instead is the founder's own stated second choice**: a message on the
destination's phone as it rings, carrying the reason and the summary. ⚠ **That message has
no channel today** — no WhatsApp Business Account, and SMS to an Indian handset needs a
DLT-registered template through a registered sender. `workers/handoff._send_brief` logs and
raises `handoff_brief_channel_absent`; OPERATIONS §2 gate 46d is what closes it. **Until
then the person answering is told nothing before they pick up, and the client's screen says
so in those words.**

## 3. Why the hunt list is not tried in turn during the call

**VERIFIED-OSS** — `task_manager.py:3116-3126`. The engine latches on the first transfer:

> `if self.has_transfer: … "Call transfer already in progress. Wait silently for the user to
> be connected; do not transfer again."`

and the branch is selected by NAME (`if called_fun.startswith("transfer_call")`, `:3107`),
so the latch covers every transfer tool on the agent however many are configured. Publishing
one tool per roster member would therefore produce an agent that silently tries exactly one
of them. The vendor's own guidance points the same way: *"Multiple departments? Add separate
transfer functions for Sales, Support, Billing — each with its own phone number and trigger
description"* — multiple numbers are multiple INTENTS, not failover
(`bolna-findings/mirror/pages/tool-calling/transfer-calls.md`). On failure the same page
says only *"Have a fallback plan if the destination is busy or unavailable"*; **no mechanism
is documented, and what the CALLER hears when nobody answers is unknown** (OPERATIONS §2
gate 45(d)).

So "tried in turn" is honoured by **choosing before the call**: `agents/handoff.on_duty`
walks the roster in order and returns the first member who is active and inside their hours,
and that number is published as the agent's single destination. The miss is caught
afterwards: `transfer_call_data.status` ∈ {no-answer, busy, failed, canceled} settles the
attempt `unreached` and books the caller a call-back at the soonest lawful time.

## 4. What was built, and where each decision landed

| The founder's decision | What ships | Achievable as asked? |
| --- | --- | --- |
| One ordered hunt list, no departments | `agent_handoff_members` — ordered, per-agent, RLS'd, edited as one whole-list PUT | **Yes**, resolved before the call rather than during it |
| A spoken whisper before bridging | Nothing on the human's ear; a brief queued to a channel that does not exist yet | **No** — §2, gate 46d |
| Try the next number, then a call-back | The call-back, booked automatically from a leg nobody answered | **Half** — §3 |
| Never transfer outside business hours | The publish carries NO transfer tool at all outside every member's hours | **Yes**, and structurally rather than by prompt |

The fourth is worth its own sentence, because it is the one place this platform's
constraint helped: the destination is fixed when the agent is published and no instruction
reaches a running call, so "do not transfer after 9pm" written into a prompt would be a
request to a model. `handoff=None` means the adapter emits no tool and the model has nothing
to fire. **Unknown hours count as nobody on duty** — the deliberate inversion of FLOWS §3's
"24/7 by default", because the thing at stake is a named person's private mobile rather than
whether an AI answers the phone.

## 5. What would change the answer

1. **A carrier account held by this deployment** (Plivo or Exotel auth id + token, on the
   account that owns the caller's leg). That is the whole of it: with one, the transfer tool's
   `url` points at our voice-runtime, we redirect the caller's leg to our own XML, and the
   whisper, the sequential hunt and a real warm transfer all become ordinary work. It is a
   commercial decision (D-05 puts the connection on the client's side), not an engineering
   one, and it would move the in-call latency budget and the DLT story with it.
2. **A WhatsApp Business Account and one approved template** — gate 46d. This does not buy a
   whisper; it buys the founder's second choice, working.

## 6. Facts that could NOT be verified, stated as such

* **What the caller hears when the destination does not answer.** Not documented anywhere in
  the mirror. Gate 45(d).
* **Whether `reason` and `summary` are really the model's own tool arguments.** The OAS
  declares only `call_sid` on the tool's `parameters` while the transfer-call page names
  `%(reason)s` and `%(summary)s` as available substitutions. We declare them; a wrong guess
  yields empty strings, never a broken transfer. Gate 46.
* **Whether the transferred leg's `cost` is already inside `total_cost`.** Gate 46c. Nothing
  meters it (hard rule 7).
* **How long the platform keeps the transferred leg's recording, and whether that recording
  can be switched off.** Gate 46b. This one is a live data-protection obligation, not a
  curiosity: a caller's audio exists at the vendor that our erasure path cannot reach.
* **Whether the hosted platform runs the OSS code read above.** The mirror and the OSS agree
  on every point this document turns on, which is the strongest available evidence and is
  still not a measurement. `api.bolna.ai` is unreachable from this container and no
  credential exists here.
