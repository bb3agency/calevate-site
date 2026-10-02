> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is a Multi-Level IVR? Nested Menus, Routing & How to Build One

> A multi-level IVR nests phone menus so callers self-route through sub-menus. How nested IVR works (DTMF + speech), design limits, and a real VobizXML build.

*June 24, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

A multi-level IVR is the layered version of the phone menu you already know: instead of one flat list of options, pressing "2" for billing opens a *billing* sub-menu, which can open another menu beneath it. This nesting lets a single business number route callers across dozens of departments, languages, and self-service flows without a human picking up. If you've ever heard *"Press 1 for new orders, press 2 for existing orders… for returns, press 1; for refunds, press 2,"* you've navigated a multi-level IVR.

This guide goes deeper than the definition. We cover what a multi-level IVR actually is and how it differs from a single-level menu, how the nesting works turn by turn (DTMF and speech), how to design a tree that callers don't abandon, a real working [VobizXML](/docs/xml/overview/how-it-works) build with nested menus and action URLs, and where conversational AI fits. For the broader fundamentals of IVR (the three levels, conversational pipelines, use cases), start with [what is an IVR](/docs/blogs/what-is-an-ivr) - this post focuses specifically on the *multi-level* design.

<Note>
  **Key takeaways**

  * A **multi-level IVR** (multi-tier or nested IVR) is a phone menu whose options open further sub-menus, forming a routing tree rather than a single flat list.
  * Each level is a separate **prompt-and-gather step**: the caller presses a key (DTMF) or speaks, and the platform requests the next menu from your application's action URL.
  * Multi-level IVRs are built with **APIs/XML**, not a fixed drag-and-drop box, so every branch can be dynamic and personalized.
  * The cardinal design rule: **keep it shallow** - 3–5 options per level, 2–3 levels deep, and a path to a human at every level. Depth is the number-one cause of caller abandonment.
  * On Vobiz, you build the menus; the same low-latency rails and bidirectional audio streaming can also carry a [conversational AI agent](/docs/solutions/ai-voice-agent) that replaces the menus entirely.
</Note>

## What is a multi-level IVR?

A **multi-level IVR** is an [interactive voice response](/docs/blogs/what-is-an-ivr) system whose menu options branch into additional sub-menus, creating a hierarchy (a *tree*) of choices rather than a single flat list. The defining distinction from an ordinary IVR is **nesting**: the answer to one menu determines which menu plays next, and that next menu can itself have sub-menus, several layers down.

A **single-level IVR** presents one menu and acts on the caller's choice immediately - *"Press 1 for sales, 2 for support"* connects the caller straight to that team. A multi-level IVR inserts intermediate decision points: *"Press 1 for support"* opens a support menu (*"Press 1 for billing, 2 for technical, 3 for account changes"*), and a billing choice might open yet another menu. Each layer narrows the caller's intent before the call is finally routed or resolved.

You'll also see this called a **multi-tier IVR**, **nested IVR**, or simply a **call menu** with sub-menus. They describe the same thing: a self-service routing tree a caller navigates by keypad or voice. The value is that one phone number can front an entire organization - every department, region, and language - without an operator manually transferring calls.

## How a multi-level IVR works

Under the hood, every level of a multi-level IVR is the same repeating unit: **play a prompt, collect input, decide the next step.** What makes it "multi-level" is that the decision can be *"play another menu"* instead of *"connect the call."*

### The prompt-and-gather loop

Each menu is one turn of a loop:

1. **Prompt.** The platform plays a menu using pre-recorded audio ([`<Play>`](/docs/xml/play)) or text-to-speech ([`<Speak>`](/docs/xml/speak)) - *"Press 1 for sales, 2 for support."*
2. **Gather input.** The caller responds by pressing a key (a [DTMF tone](https://en.wikipedia.org/wiki/Dual-tone_multi-frequency_signaling)) or by speaking. The [`<Gather>`](/docs/xml/gather) element captures it.
3. **Route.** The captured digit or phrase is sent to your application's **action URL**. Your backend decides what comes next and returns the corresponding block of XML - which may be the *next menu*, a transfer, or a self-service answer.

In a single-level IVR, step 3 ends the menu portion. In a multi-level IVR, step 3 frequently returns *another* prompt-and-gather block, and the loop repeats one level deeper. This is the key mechanic: **a sub-menu is just the action-URL response of the menu above it.** There's no special "nested menu" construct - nesting emerges from one menu's action URL returning the next menu.

### DTMF vs speech input at each level

Callers can navigate a multi-level IVR two ways, and good systems accept both:

* **DTMF (keypad tones).** The classic *"press 1."* Each key generates a [dual-tone multi-frequency signal](https://en.wikipedia.org/wiki/Dual-tone_multi-frequency_signaling) - a pair of audio frequencies standardized by the [ITU-T Q.23 recommendation](https://en.wikipedia.org/wiki/Dual-tone_multi-frequency_signaling) - that the platform decodes into a digit. DTMF is precise, universal, and free to process, which is why it remains the backbone of menu navigation.
* **Speech.** The caller says *"billing"* instead of pressing a key. The platform transcribes the speech via [automatic speech recognition](/docs/xml/gather/detecting-speech-inputs) and matches it to a branch. Speech shortcuts deep trees - a caller can jump straight to intent - but it incurs a per-request transcription cost and needs a confidence threshold.

With Vobiz you set `inputType="dtmf speech"` on a single [`<Gather>`](/docs/xml/gather), and whichever input the caller produces first is the one relayed to your action URL - so the same menu serves keypad and voice callers at once.

### The menu tree

It helps to picture a multi-level IVR as a tree. Here is a typical two-to-three-level structure for a retail line:

```text theme={null}
Main menu
├─ 1  Sales
│   ├─ 1  New order
│   └─ 2  Product questions
├─ 2  Support
│   ├─ 1  Billing  ──► account lookup (collect order #)
│   ├─ 2  Technical ──► transfer to tech queue
│   └─ 3  Returns
│       ├─ 1  Start a return
│       └─ 2  Refund status
├─ 9  Repeat this menu
└─ 0  Speak to an agent   (available at every level)
```

Every node with children is a menu (a prompt-and-gather turn); every leaf is an action - a transfer, a self-service lookup, or a hand-off to a human or AI agent. The "0 for an agent" escape hatch should appear at *every* level, not just the top.

## Single-level vs multi-level IVR

| | Single-level IVR | Multi-level IVR |
| - | - | - |
| **Structure** | One flat menu | Nested tree of menus and sub-menus |
| **Typical use** | Small business, 2–4 destinations | Larger orgs, many departments/languages |
| **Routing depth** | One decision | Multiple decisions, each narrows intent |
| **Build** | One prompt-and-gather | Each sub-menu = an action-URL response |
| **Caller effort** | Low (one choice) | Higher (rises with depth) |
| **Personalization** | Limited | Per-level, dynamic branches via your backend |
| **Abandonment risk** | Low | Rises sharply past 3 levels |
| **Best for** | Simple routing | Triage and self-service at scale |
| **Agent escape** | One "press 0" | "Press 0" needed at *every* level |

The trade-off is direct: multi-level IVRs scale routing for complex organizations, but every extra layer adds caller effort and a chance to get lost. The design goal is to capture the organization's complexity in the *fewest* levels possible.

## Designing a multi-level IVR menu

The mechanics are easy; good *design* is what separates an IVR callers tolerate from one they curse. The competitors' guides agree on the fundamentals - here are the rules that matter most, with concrete numbers.

* **Cap the depth.** Keep menus to **2–3 levels** wherever possible. Each additional level compounds effort and memory load; callers regularly abandon trees that bury their intent four or five layers down. If a flow needs more depth, that's a signal to use speech input or a conversational agent instead.
* **Limit options per level.** Offer **3–5 options per menu**, never more than 7. People struggle to hold a long spoken list in working memory, and the last option always wins disproportionate presses simply because it was heard last.
* **Front-load the common path.** Order options by call volume, not org chart. If 60% of callers want order status, that should be option 1.
* **Always offer "press 0 for an agent" - at every level.** [Callers consistently report frustration with menus that trap them](https://en.wikipedia.org/wiki/Interactive_voice_response) with no human escape. Make the escape reachable from any sub-menu, and make the [transfer](/docs/solutions/call-transfer) carry context so the caller doesn't repeat everything.
* **Say the option before the key.** *"For billing, press 1"* is easier to act on than *"Press 1 for billing"* once lists get long, because the caller knows whether to press before they hear the number.
* **Handle no-input and wrong-input gracefully.** After [`<Gather>`](/docs/xml/gather) times out (use `executionTimeout`, valid 5–60 s), re-prompt once, then fall back to an agent - don't dead-end or hang up silently.
* **Personalize with the caller's number.** Look up the caller by their [`From`](/docs/xml/gather) number and skip irrelevant branches - a known account holder shouldn't navigate the new-customer tree.
* **Add a "repeat menu" key.** A dedicated key (often 9 or \*) to replay the current menu spares callers who missed an option from starting over.
* **Test the whole tree and measure abandonment per branch.** Walk every path. Then watch [post-call analytics](/docs/solutions/post-call-analytics) - a branch with high drop-off is where callers get lost, and it's the first thing to redesign.

The honest trade-off: a multi-level IVR optimizes the *business's* routing, but every level you add optimizes against the *caller's* patience. Treat each new layer as a cost you must justify.

## Building a multi-level IVR with VobizXML

On a programmable platform you don't configure a fixed tree - you return [VobizXML](/docs/xml/overview/how-it-works) for each turn and your backend decides the branches. That makes the tree fully dynamic: every sub-menu is just the response your action URL returns. Below is a real two-level build. (Verify element and attribute names against the [Gather](/docs/xml/gather) and [Speak](/docs/xml/speak) references.)

### Level 1 - the main menu

When Vobiz answers the call, it requests your answer URL, which returns the top menu. `numDigits="1"` posts to the action URL the instant one key is pressed; `inputType="dtmf speech"` lets callers press *or* say their choice.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/ivr/main" method="POST"
            inputType="dtmf speech" numDigits="1" executionTimeout="10"
            hints="sales,support,agent">
        <Speak>Thanks for calling Acme. For sales, press 1. For support,
        press 2. To speak with an agent at any time, press 0.</Speak>
    </Gather>
    <Speak>Sorry, we didn't get that.</Speak>
    <Redirect>https://yourapp.com/ivr/answer</Redirect>
</Response>
```

If no input arrives within `executionTimeout`, Vobiz moves past the `<Gather>` and the [`<Redirect>`](/docs/xml/redirect) loops the caller back to the start for a retry rather than hanging up.

### Level 2 - returning a sub-menu from the action URL

Your `/ivr/main` handler reads the `Digits` (or `Speech`) parameter Vobiz POSTs and returns the *next* menu. This is the nesting: the sub-menu is the action-URL response. For "2" (support), return a second prompt-and-gather pointed at a deeper action URL.

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/ivr/support" method="POST"
            inputType="dtmf speech" numDigits="1" executionTimeout="10"
            hints="billing,technical,returns,agent">
        <Speak>You've reached support. For billing, press 1. For technical
        help, press 2. For returns, press 3. To go back, press star.
        For an agent, press 0.</Speak>
    </Gather>
    <Redirect>https://yourapp.com/ivr/support</Redirect>
</Response>
```

A sketch of the routing logic behind the action URL (any language; pseudocode):

```python theme={null}
# POST /ivr/main  - Vobiz sends Digits / Speech
digit = form.get("Digits")
speech = (form.get("Speech") or "").lower()

if digit == "0" or "agent" in speech:
    return xml_dial_agent()          # escape to a human at any level
elif digit == "1" or "sales" in speech:
    return xml_sales_menu()          # another sub-menu
elif digit == "2" or "support" in speech:
    return xml_support_menu()        # the Level-2 XML above
else:
    return xml_reprompt_main()       # invalid: re-play the main menu
```

### Level 3 - the leaf action

A leaf node ends navigation. A billing choice might collect an order number with a multi-digit [`<Gather>`](/docs/xml/gather) (using `finishOnKey="#"`), look it up, and speak the result - or it might [`<Dial>`](/docs/xml/dial) the right queue. The "0 for an agent" branch resolves to a context-preserving [call transfer](/docs/solutions/call-transfer).

```xml theme={null}
<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Gather action="https://yourapp.com/ivr/order-status" method="POST"
            inputType="dtmf" numDigits="10" finishOnKey="#" executionTimeout="20">
        <Speak>Enter your ten digit order number, then press pound.</Speak>
    </Gather>
    <Speak>We didn't receive an order number. Connecting you to an agent.</Speak>
    <Redirect>https://yourapp.com/ivr/agent</Redirect>
</Response>
```

For a complete, runnable build, see the [IVR XML + Python example](/docs/examples/vobiz-ivr-xml-python), plus the [number-capture](/docs/examples/vobiz-number-capture-xml-python) and [call-survey](/docs/examples/vobiz-call-survey-xml-python) examples for common leaf actions. The full [cloud IVR solution](/docs/solutions/cloud-ivr) walks through the architecture end to end.

## Multi-level IVR vs conversational AI IVR

A multi-level IVR makes the caller do the routing: they descend a tree of menus until they reach their intent. A **conversational AI IVR** flips that - the caller states their need in their own words (*"I want to check my refund status"*) and an AI pipeline (ASR → NLP/LLM → TTS) infers the intent and acts, collapsing several menu levels into one turn. (See the full breakdown of the [three IVR levels](/docs/blogs/what-is-an-ivr).)

| | Multi-level IVR | Conversational AI IVR |
| - | - | - |
| **Navigation** | Caller descends a menu tree | Caller speaks intent once |
| **Input** | DTMF (and constrained speech) | Natural, free-form speech |
| **Best for** | Deterministic routing, payments, compliance | Open-ended intent, complex requests |
| **Failure mode** | Deep trees, abandonment | Misrecognition, needs low latency |
| **What it needs** | Reliable menus | Real-time bidirectional audio + an AI brain |

These aren't mutually exclusive - many production lines use a shallow DTMF front door (precise, free, perfect for *"press 1 to confirm payment"*) that escalates to a conversational agent for anything that doesn't fit a tidy menu.

Here's the important positioning, and where Vobiz draws a firm line: **Vobiz is the telephony infrastructure, not the AI agent.** Vobiz carries the call, runs the [DTMF/speech menus](/docs/xml/gather), and provides low-latency [bidirectional audio streaming](/docs/audio-streams). The *agent brain* - the LLM that holds the conversation - is yours, or a partner's. Voice-AI platforms like Vapi, Retell, ElevenLabs, Pipecat, and LiveKit run on Vobiz rails; Vobiz powers the AI layer, it doesn't replace it.

## How Vobiz handles multi-level IVR

[Vobiz](/docs/introduction) is the programmable telephony layer under your IVR - full code control over every branch, not a fixed drag-and-drop tree:

* **Build the tree in XML.** [`<Speak>`](/docs/xml/speak) and [`<Play>`](/docs/xml/play) for prompts, [`<Gather>`](/docs/xml/gather) for DTMF or [speech](/docs/xml/gather/detecting-speech-inputs), and [`<Redirect>`](/docs/xml/redirect)/[`<Dial>`](/docs/xml/dial) for routing. Each sub-menu is the response your action URL returns, so the entire tree is dynamic and personalized per caller.
* **DTMF and speech in one menu.** `inputType="dtmf speech"` accepts a keypress *or* a spoken phrase on the same [`<Gather>`](/docs/xml/gather), so callers navigate however they prefer.
* **Clean escalation at any level.** Route "0 for an agent" to a context-preserving [call transfer](/docs/solutions/call-transfer) or [escalation](/docs/solutions/call-escalation) so the caller never repeats themselves.
* **Same rails carry conversational AI.** When a menu isn't enough, connect [bidirectional audio streaming](/docs/audio-streams) to your STT/LLM/TTS stack so a [voice AI agent](/docs/solutions/ai-voice-agent) can respond and handle barge-in - Vobiz powers the media path; you own the agent.
* **Built for scale and India-first compliance.** 99.99% uptime, 4.2+ MOS at 3M+ calls/day, instant eKYC provisioning, DID in **130+ countries**, outbound to **190+**, and flat **₹0.65/min** both ways. Trusted by fintechs like Razorpay and Acko and voice-AI builders like Bolna.

Wire it all together with a webhook into your CRM for live context, then measure each branch in [post-call analytics](/docs/solutions/post-call-analytics). For a higher-level view of automating phone operations, see [call center optimization with AI](/docs/blogs/call-center-optimization-with-ai).

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is a multi-level IVR?">
    A multi-level IVR is an interactive voice response system whose menu options open further sub-menus, forming a routing tree. Pressing a key (or speaking) at one level plays the next menu, so callers self-route through several layers to the right department or self-service flow.
  </Accordion>

  <Accordion title="What is the difference between single-level and multi-level IVR?">
    A single-level IVR has one flat menu and acts on the caller's choice immediately. A multi-level (nested) IVR layers menus so each choice can open a sub-menu, letting one number route many departments - at the cost of more caller effort per level.
  </Accordion>

  <Accordion title="How many levels should a multi-level IVR have?">
    Keep it to 2–3 levels with 3–5 options per menu. Each extra level raises caller effort and abandonment, so deep trees should be replaced by speech input or a conversational agent rather than more menus.
  </Accordion>

  <Accordion title="How do you build a multi-level IVR?">
    Use a programmable voice platform: return XML that speaks a menu and gathers DTMF or speech, then have your action URL return the next sub-menu based on the input. Each sub-menu is simply the action-URL response of the menu above it. See the Vobiz IVR example.
  </Accordion>

  <Accordion title="Can a multi-level IVR use speech as well as keypad input?">
    Yes. On Vobiz, set inputType="dtmf speech" on a Gather and the caller can press a key or say their choice; whichever input arrives first is relayed to your action URL, so the same menu serves keypad and voice callers.
  </Accordion>

  <Accordion title="Is a multi-level IVR the same as a conversational AI IVR?">
    No. A multi-level IVR makes the caller navigate a menu tree; a conversational AI IVR lets the caller state their intent in natural speech and an AI infers it. Vobiz is the telephony infrastructure for both - it powers the AI layer rather than being the agent.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [What is an IVR?](/docs/blogs/what-is-an-ivr) · [Cloud IVR solution](/docs/solutions/cloud-ivr) · [AI voice agent](/docs/solutions/ai-voice-agent)
* [Gather (collect input)](/docs/xml/gather) · [Detecting speech inputs](/docs/xml/gather/detecting-speech-inputs) · [Speak (text-to-speech)](/docs/xml/speak) · [Redirect](/docs/xml/redirect)
* [VobizXML, how it works](/docs/xml/overview/how-it-works) · [IVR XML + Python example](/docs/examples/vobiz-ivr-xml-python)
* [Call transfer](/docs/solutions/call-transfer) · [Call escalation](/docs/solutions/call-escalation) · [Post-call analytics](/docs/solutions/post-call-analytics)

## Sources

* Wikipedia, ["Interactive voice response"](https://en.wikipedia.org/wiki/Interactive_voice_response).
* Wikipedia, ["Dual-tone multi-frequency signaling"](https://en.wikipedia.org/wiki/Dual-tone_multi-frequency_signaling) (ITU-T Q.23).
* Wikipedia, ["E.164"](https://en.wikipedia.org/wiki/E.164) (ITU-T numbering plan).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and build a multi-level IVR with nested menus in minutes
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.