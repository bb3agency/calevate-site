> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# What is Answering Machine Detection (AMD)? How It Works in 2026

> Answering Machine Detection (AMD) tells you if a human or voicemail picked up. How it works, sync vs async, accuracy vs latency, and AMD for voice AI agents.

*June 25, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

Answering Machine Detection (AMD) is the telephony feature that, in the first few seconds after an outbound call is answered, decides whether a live human or a machine - voicemail, an answering machine, a fax, or silence - picked up the phone. It exists for one blunt reason: in most consumer outbound calling, the majority of dials never reach a person, and a platform that can't tell a human from a recording will happily waste an agent, a prerecorded message, or an expensive AI-agent conversation talking to someone's voicemail greeting.

This guide is the explainer, not the build manual. We'll define AMD precisely, open up how it actually works (call-progress analysis, beep and tone detection, the acoustic cues that separate "Hello?" from "Hi, you've reached…", and the move to machine-learning classifiers), the two architectures every implementation lands on, the unavoidable accuracy-versus-latency trade-off, why AMD matters even more for [voice AI agents](/docs/integrations), and the compliance context around it. If you want the step-by-step campaign engineering - pacing math, CPS vs concurrency, and the exact API parameters - read the companion how-to, [Scaling outbound: automated calling and AMD](/docs/blogs/automated-calling-answering-machine-detection).

<Note>
  **Key takeaways**

  * **Answering Machine Detection (AMD)** classifies who or what answered an outbound call - human, machine/voicemail, fax, or silence - so your application can branch instead of wasting the call.
  * AMD works by **call-progress analysis**: measuring greeting length, the speech-to-silence cadence, and beep/tone signatures in the first seconds of audio, increasingly backed by ML acoustic classifiers.
  * The core architectural choice is **synchronous vs asynchronous**. Synchronous AMD adds seconds of dead air a human can hear; **asynchronous** AMD connects the call instantly and posts the verdict to a webhook - the right default for any real-time experience.
  * There is an inherent **accuracy ↔ latency trade-off**: hearing more audio is more accurate but slower; deciding early is faster but riskier. "Wait for the greeting to end" modes approach very high accuracy on familiar destinations; fast modes are quicker but less certain.
  * For **voice AI agents**, AMD is used to *gate the media stream* - hold the agent's first words until a human is confirmed. On [Vobiz](/docs/introduction), this runs over sub-80 ms, single-hop telephony so detection plus the agent's STT/LLM/TTS loop still fits the conversational latency budget.
</Note>

## What is Answering Machine Detection (AMD)?

**Answering Machine Detection (AMD)** - also called voicemail detection or machine detection - is a programmable-voice capability that determines, immediately after an outbound call is answered, whether the answering party is a live human or an automated system. The result is returned to your application as a label such as `human`, `machine`, `fax`, or `silence`, so your call flow can react: connect a person, drop a recorded message after the beep, hang up, or release a voice AI agent to speak.

The one non-obvious distinction worth fixing in your head: AMD is **not** the same as detecting whether a call was *answered at all*. The carrier already tells you about ringing, busy, and no-answer through standard [call-progress and hangup signaling](/docs/concepts/hangup-causes). AMD is the harder, fuzzier problem that begins *after* "answered" - distinguishing a human who says "Hello?" from a recording that says "Hi, you've reached Priya, please leave a message." That happens entirely in the audio, which is why AMD is a probabilistic, tunable feature rather than a deterministic flag.

AMD became essential alongside the [predictive dialer](https://en.wikipedia.org/wiki/Predictive_dialer), which places more calls than it has agents on the bet that many will hit voicemail or no-answer. Without AMD, every machine-answered call burns an agent's time or, worse, gets abandoned; with it, the dialer routes only confirmed humans to people and handles the rest automatically.

## How Answering Machine Detection works

There is no magic in AMD - it is real-time **audio classification** running on the first moments of an answered call. Modern engines blend four kinds of signal.

### Call-progress analysis (timing and cadence)

The oldest and still-central technique is **call-progress analysis**: instead of understanding *what* is said, the detector measures the *shape* of the audio. A human who answers gives a short utterance and then stops - "Hello?" lasts a few hundred milliseconds and is followed by expectant silence, because they're waiting for you to respond. A voicemail greeting is the opposite: a longer, continuous block of speech that runs for seconds without pausing for a reply.

That single behavioural difference is encoded as a tunable **speech-length threshold**. Speech *shorter* than the threshold is classified as human; speech *longer* than it is classified as machine. Competitor implementations publish rough buckets that match real-world greetings: personal and mobile greetings tend to run under \~1,800 ms, business greetings \~1,800–3,000 ms, and answering-machine greetings typically exceed \~3,000 ms. The detector also watches the **speech-to-silence ratio** and the rhythm of pauses to refine the call between these patterns.

### Beep and tone detection

If your goal is to *leave* a message rather than just classify the call, timing the greeting isn't enough - you need to start speaking at the right instant. So AMD also listens for the **end-of-greeting beep** (or the silence that follows the greeting) and signals "now safe to speak." This is harder than it sounds: the frequency content of a voicemail "beep" varies enormously by carrier and country, and it can overlap with - or be indistinguishable from - standard [call-progress tones](https://en.wikipedia.org/wiki/Call-progress_tone). That's why mature engines return *how* the greeting ended, distinguishing a greeting that ended on a clear beep from one that ended on silence or on some other audio (a network tone, a "mailbox full" message, and so on). Knowing the ending type lets your flow decide whether it's truly safe to drop a recording.

### Acoustic and machine-learning signals

Hand-tuned timing heuristics handle the easy cases but struggle with edge cases: a chatty human who keeps talking, a terse "This is Sam," or region-specific greeting styles. Newer AMD engines (the 2024–2026 generation) add trained **machine-learning acoustic classifiers** that use speech recognition and learned features rather than fixed thresholds. These models return richer, more reliable labels - for example distinguishing a residential human from a business human - and adapt better across accents and destinations. The newest wrinkle they handle is **on-device call screening** (the AI screening assistants now shipping on smartphones), which sounds like neither a classic human greeting nor a classic voicemail and has to be recognised as its own category.

### Human vs machine cues, summarised

| Cue | Human ("Hello?") | Machine / voicemail |
| - | - | - |
| **Initial utterance length** | Short (often \< \~1,800 ms) | Long, continuous (often > \~3,000 ms) |
| **Pause behaviour** | Speaks, then waits silently for you | Keeps talking through the greeting |
| **Speech-to-silence ratio** | Low (brief speech, then silence) | High (sustained speech) |
| **End-of-greeting signal** | None expected | Often a beep, "mailbox" tone, or trailing silence |
| **Interactivity** | Responds to what you say | Ignores input, plays to completion |

Two properties define *every* AMD implementation regardless of vendor: its **latency** (how long before it decides) and its **accuracy / false-positive profile**. Those two are in tension, which is what the rest of this guide turns on.

## Types of AMD: synchronous vs asynchronous

Strip away the branding and AMD comes in two architectures. Choosing between them is the single most consequential AMD decision you'll make.

### Synchronous AMD

**Synchronous AMD** blocks the call flow until detection finishes. Nothing happens - no greeting, no connect, no agent - until the engine returns its verdict. The benefit is simplicity: by the time your application is invoked, you already know `human` or `machine`. The cost is brutal for live experiences: a real person who answered hears several seconds of **dead air** before anything happens, which is a terrible first impression and one of the biggest causes of early hang-ups. Synchronous AMD is acceptable for fully automated, non-conversational flows (drop a recorded message or nothing), but it's the wrong tool the moment a human or an AI agent is meant to talk in real time.

### Asynchronous AMD

**Asynchronous AMD** lets the call proceed *immediately*. The callee is connected, your answer flow runs, and a human can start talking right away - while detection runs in the background and posts its verdict (`human` / `machine` / `fax`) to a **callback URL** the instant it's confident. There's no dead air on the human path; your application simply reacts to the AMD result when it arrives, hanging up or branching to a voicemail flow if the answer turns out to be a machine. Asynchronous is the correct default for anything real-time, and it is *essential* for AI voice agents. Several major platforms now offer asynchronous mode (some, notably, only support async for outbound calls placed through their calls API), reflecting how strongly the industry has converged on it for conversational use.

Within both architectures you'll also see two **detection intents**: decide as soon as the answering party is identified (fastest - best for predictive dialers that want to connect or drop), or wait until the greeting *ends* (slower, but lets you cleanly leave a message after the beep). That's the same speed-versus-accuracy fork, applied to *when* the verdict fires.

## AMD accuracy and latency trade-offs

AMD is probabilistic, so the honest framing is not "how accurate is it" but "what are you trading for that accuracy." Three realities matter.

**Accuracy depends on the mode and the destination.** "Wait for the greeting to end" detection sees the most audio and is the most accurate - vendors report it approaching near-perfect accuracy on familiar domestic destinations with default settings. But that accuracy drops for **international** calls, because the beep frequencies, greeting styles, and voicemail tones differ by country and carrier - exactly the call-progress-tone variation noted above. Fast "decide as early as possible" modes are inherently less certain because they act on less audio.

**Latency is a few seconds, not milliseconds.** Because the engine must hear enough audio to judge, AMD verdicts typically land **a few seconds** after the call is answered (one major platform cites \~4 seconds on average with default settings; common defaults for the detection window sit around 5,000 ms). Shrinking the timeout too aggressively starves the classifier of data and *increases* errors - a classic case where "faster" makes the result worse.

**There are two failure modes, and they aren't equal.** Track both:

* **False human** - a machine misclassified as a human. Your agent or AI delivers its opener into a voicemail. Wasteful, but recoverable.
* **False machine** - a *real person* misclassified as a machine. You hang up on, or drop a recording on, an actual prospect. This is the worse error: it's a bad customer experience and it wastes a genuine contact. Tune thresholds to *favour not abandoning humans*.

A third bucket - `unknown` (or "answered\_by: unknown") - appears when the engine genuinely can't decide within the window. You reduce it by giving detection a little more time and a longer speech-length allowance, not by squeezing it. The throughline: **validate AMD on your own traffic and accents and tune for it.** Published accuracy figures are marketing-clean averages; your real numbers depend on your destinations, your audience, and your timeout settings.

## AMD for voice AI agents: gating the media stream

This is where AMD stops being a contact-center nicety and becomes architectural. An [AI voice agent](/docs/integrations) connects to the call over a [bidirectional audio WebSocket](/docs/concepts/streaming-websockets) and begins its speech-to-text → LLM → text-to-speech loop the instant audio flows. If a *voicemail* answered, the agent cheerfully delivers its opening line into a recording: you pay for the STT, the LLM, and the TTS; the prospect later hears a confusing half-message; and the contact is wasted.

The fix is to **gate the agent's media stream on a confirmed human**:

1. Place the outbound call with **asynchronous** AMD enabled.
2. Let the call connect, but *hold* the agent's first utterance.
3. When the AMD callback returns `human`, release the agent to speak. If it returns a machine result, hang up or branch to a "leave a voicemail" flow.

Why asynchronous is non-negotiable here comes down to the [latency budget](/docs/blogs/what-is-a-voice-api). A natural conversational turn has to fit inside roughly a one-second round trip across telephony + STT + LLM + TTS. A *synchronous* AMD that injects 4 seconds of silence before the agent can even hear the caller obliterates that budget. Asynchronous AMD keeps the human path instant and runs detection in parallel. Pair that with [native barge-in](/docs/audio-streams) so the caller can interrupt, and the agent feels human instead of robotic. Every major AI-agent framework - Vapi, Retell, and others Vobiz powers - now exposes exactly this voicemail-detection hook so the agent only engages a real person.

## AMD and compliance (TCPA and abandoned calls)

AMD isn't just an efficiency feature; it sits squarely inside outbound-calling regulation, especially in the US.

The [Telephone Consumer Protection Act (TCPA)](https://en.wikipedia.org/wiki/Telephone_Consumer_Protection_Act_of_1991) and the FCC's implementing rules in [47 CFR §64.1200](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-64/subpart-L/section-64.1200) govern autodialed and prerecorded calls - consent requirements, calling-time windows, and, critically for AMD, a cap on **abandoned calls** in telemarketing. An "abandoned" call is one where a live person answers but no agent is available to talk within two seconds; the rule limits these to a small percentage of calls. This is the same constraint regulators worldwide imposed on [predictive dialers](https://en.wikipedia.org/wiki/Predictive_dialer) once over-aggressive dialing became a nuisance.

AMD is double-edged here. Used well - to route confirmed humans to available agents and handle machines automatically - it *reduces* abandonment and improves the experience. Used carelessly, it can *cause* problems: a slow synchronous detector that makes a human wait, or a misconfigured one that drops real people, both degrade the called party's experience and can push you toward the abandonment limit. Two practical takeaways: measure your abandonment rate inside your pacing loop rather than as an afterthought, and remember that AMD is one input to compliance, not a substitute for consent management and calling-window discipline. For the India-specific regulatory layer (TRAI, DLT registration), see Vobiz's [calling-regulations](/docs/compliance/india/calling-regulations) and [DLT](/docs/best-practices/dlt-registration) docs.

## How Vobiz handles AMD

[Vobiz](/docs/introduction) is the telephony **infrastructure** beneath your dialer or AI agent - you bring the campaign logic, Vobiz runs the calls. It *powers* voice-AI builders (Vapi, Retell, LiveKit, Pipecat, ElevenLabs); it does not ship its own agent or compete with yours. Concretely for AMD:

* **AMD as call parameters.** Enable detection on the [outbound call](/docs/solutions/automated-outbound-calling), choosing whether to detect-and-continue or to drop machine-answered calls automatically. A machine-answered call can end cleanly with a dedicated [machine-detected hangup cause](/docs/concepts/hangup-causes), so your reporting separates "voicemail" from "no answer."
* **Asynchronous by callback.** Provide a machine-detection callback URL and Vobiz runs detection in the background, then POSTs the result so your AI agent can gate its stream - no dead air on the human path. This is the architecture conversational use demands.
* **Voicemail-end detection in XML.** Use [`<Wait silence="true" minSilence="2000"/>`](/docs/xml/wait/machine-detection) so that once a voicemail greeting finishes and silence begins, your flow advances (for example, to drop a message) without waiting out the full timer. See the [`<Wait>` reference](/docs/xml/wait) for the attributes.
* **Built for the AI latency budget.** Sub-80 ms single-hop media and bidirectional [audio streaming](/docs/audio-streams) leave more of the conversational turn for AMD and the agent's STT/LLM/TTS processing.
* **Tuned for reputation, too.** Because over-dialing degrades number reputation, Vobiz pairs AMD with number rotation, per-number caps, and cooldowns - contributing to a **30% reduction in spam-flag rate** - and lets you keep a trusted, owned caller ID via the [`<Dial>` `callerId`](/docs/xml/dial) attribute. Run the program through the [campaign manager](/docs/platform/campaigns/list) and follow the [outbound best practices](/docs/best-practices/outbound-campaign-manager) and [number-utilization](/docs/best-practices/number-utilization) guides.

For the full implementation walkthrough - pacing math, CPS-vs-concurrency sizing, and the exact parameters - see the companion how-to: [Scaling outbound: automated calling and AMD](/docs/blogs/automated-calling-answering-machine-detection).

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is answering machine detection?">
    Answering Machine Detection (AMD) is a programmable-voice feature that determines, in the first seconds after an outbound call is answered, whether a live human or a machine (voicemail, answering machine, fax, or silence) picked up. It returns a label such as `human` or `machine` so your application can connect a person, leave a message, hang up, or release an AI agent.
  </Accordion>

  <Accordion title="How does answering machine detection work?">
    AMD performs call-progress analysis on the first moments of answered audio: it measures greeting length, the speech-to-silence cadence, and end-of-greeting beep or tone signatures, then classifies the answer. A human "Hello?" is short and followed by silence; a voicemail greeting is long and continuous. Newer engines add machine-learning acoustic classifiers for richer, more accurate labels.
  </Accordion>

  <Accordion title="What is the difference between synchronous and asynchronous AMD?">
    Synchronous AMD blocks the call until detection finishes, so a human who answers hears several seconds of silence first. Asynchronous AMD connects the call immediately and posts the verdict to a webhook in the background, so there's no dead air. Asynchronous is the right default for real-time experiences and essential for AI voice agents.
  </Accordion>

  <Accordion title="How accurate is answering machine detection?">
    It depends on the mode and destination. "Wait for the greeting to end" detection sees the most audio and approaches very high accuracy on familiar domestic destinations with default settings, but accuracy drops internationally because beep frequencies and greeting styles vary by country. Fast "decide early" modes are quicker but less certain. Always validate on your own traffic and tune to avoid hanging up on real people.
  </Accordion>

  <Accordion title="How long does AMD take to return a result?">
    Because the engine must hear enough audio to judge, AMD verdicts typically land a few seconds after the call is answered - one major platform cites around four seconds on average with default settings, and common detection windows default to roughly 5,000 ms. Shortening the timeout too aggressively starves the classifier and increases errors.
  </Accordion>

  <Accordion title="How do AI voice agents avoid talking to voicemail?">
    They gate the agent's media stream on a confirmed human: place the call with asynchronous AMD, hold the agent's first line, and only let it speak when the AMD callback returns `human` - otherwise hang up or branch to a voicemail flow. This keeps the human path instant while detection runs in parallel.
  </Accordion>
</AccordionGroup>

## Further reading on Vobiz

* [Scaling outbound: automated calling & AMD](/docs/blogs/automated-calling-answering-machine-detection) · [What is a Voice API?](/docs/blogs/what-is-a-voice-api) · [What is VoIP?](/docs/blogs/what-is-voip)
* [Automated outbound calling](/docs/solutions/automated-outbound-calling) · [Machine detection in `<Wait>`](/docs/xml/wait/machine-detection) · [`<Wait>` reference](/docs/xml/wait)
* [Audio streaming](/docs/audio-streams) · [Streaming over WebSockets](/docs/concepts/streaming-websockets) · [Hangup causes](/docs/concepts/hangup-causes)
* [Campaign manager](/docs/platform/campaigns/list) · [Outbound campaign best practices](/docs/best-practices/outbound-campaign-manager) · [Number utilization](/docs/best-practices/number-utilization) · [Integrations hub](/docs/integrations)

## Sources

* Wikipedia, ["Predictive dialer"](https://en.wikipedia.org/wiki/Predictive_dialer) (answering-machine detection, abandoned calls, and dialer regulation).
* Wikipedia, ["Call-progress tone"](https://en.wikipedia.org/wiki/Call-progress_tone).
* Wikipedia, ["Answering machine"](https://en.wikipedia.org/wiki/Answering_machine).
* Wikipedia, ["Telephone Consumer Protection Act of 1991"](https://en.wikipedia.org/wiki/Telephone_Consumer_Protection_Act_of_1991).
* US Government, ["47 CFR §64.1200" (telephone solicitation / abandoned calls)](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-64/subpart-L/section-64.1200).

<Card title="Build on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and place your first AMD-gated outbound call in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.