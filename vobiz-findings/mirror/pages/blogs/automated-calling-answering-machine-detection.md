> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Scaling Outbound: Mastering Automated Calling & Answering Machine Detection in 2026

> How automated outbound calling and answering machine detection work in 2026 - dialer pacing, CPS vs concurrency, and AMD across major voice APIs.

*June 16, 2026 · By [Piyush Sahoo](https://www.linkedin.com/in/piyush-s713/)*

Automated outbound calling, dialing people programmatically for reminders, verification, alerts, collections, surveys, or a full AI-agent conversation, looks trivial in a demo and breaks at scale. The reason is structural: outbound is a numbers game where *most dials never reach a human*. A typical campaign loses calls to no-answers, busy signals, and, above all, voicemail; only a fraction connect to a live person. That funnel is what makes outbound hard, and it's why two unglamorous mechanics, not the dialing itself, decide whether a program is profitable or quietly bleeds money.

Those two levers are **pacing** and **answering machine detection (AMD)**. Pacing is how fast you dial relative to how many calls you can actually handle and what regulators allow: dial too slowly and your agents (or AI sessions) sit idle; dial too fast and you abandon live people, which is both a poor experience and, in the US, a capped regulatory violation. AMD is what happens at the instant of pickup, detecting whether a human or a machine answered, so you never spend an agent, an LLM turn, or a prerecorded message talking to someone's voicemail. Get either wrong and the damage compounds: wasted capacity, abandoned-call exposure, and, worst of all, phone numbers that get flagged "Spam Likely", at which point answer rates fall off a cliff and the whole campaign degrades.

This guide is the developer-and-engineering-leader view of both, in 2026: the dialer mechanics, the CPS-vs-concurrency math, how AMD actually works, how the major voice platforms implement it, why AMD matters even more for AI voice agents, and the compliance and deliverability guardrails you have to build around.

<Note>
  **Key takeaways**

  * **CPS ≠ concurrency.** Calls-per-second limits how fast you *initiate* calls; concurrency limits how many run at once. They relate by `concurrent_calls ≈ CPS × answer_rate × average_talk_time` (Little's Law), only answered calls hold a channel for the full talk time.
  * **Answering machine detection** classifies who/what answered (human, machine, fax, silence) so you don't waste an agent, AI, or prerecorded message on a voicemail.
  * **Sync vs async AMD is the key design choice.** Synchronous AMD adds seconds of dead air before connect; **asynchronous AMD** lets the call proceed immediately and posts the result to a webhook, which is what voice-AI agents need.
  * **AMD accuracy and latency vary by mode** - "wait for the greeting to end" modes are slower but more accurate; fast heuristic modes are quicker but less certain. Always validate on your own traffic and tune to avoid hanging up on real people.
  * On [Vobiz](/docs/introduction), AMD is a few [Make Call API](/docs/call/make-call) parameters; `machine_detection=hangup` drops machine-answered calls (hangup code [`9100`](/docs/concepts/hangup-causes)), and an async `machine_detection_url` lets your AI agent gate its media stream on a confirmed human.
</Note>

## How automated outbound calling actually works

Strip away the marketing and an outbound calling platform is a loop: your backend tells the carrier to dial a number, the carrier rings it, and the moment it's answered the platform asks *your* server what to do. On Vobiz that's a **REST dial → answer URL → call-control XML** pattern: you `POST` to the [Make Call API](/docs/call/make-call), and when the callee picks up, the platform invokes your `answer_url`, which must return valid call-control [XML](/docs/xml/response). That webhook-returns-XML contract is what makes routing programmable: your app decides, live, whether to speak, gather input, bridge, or stream audio to an AI agent.

### Dialer types

How aggressively you dial is the *dialer mode*, and the four classic modes trade agent idle time against the risk of abandoning calls:

| Dialer mode | How it paces | Abandonment risk | Best for |
| - | - | - | - |
| **Preview** | Agent reviews the contact, then triggers the dial | None | High-value, complex, regulated calls |
| **Progressive** | One call dialed per available agent | Very low | Balanced quality + efficiency |
| **Power** | A fixed ratio of lines per agent (e.g. 2:1) | Low–moderate | Steady mid-volume campaigns |
| **Predictive** | An algorithm dials *ahead* of agent availability, predicting when agents free up | Higher (must be capped) | High-volume, answer-rate-driven |

Predictive dialing is where AMD and pacing become non-negotiable: you are deliberately placing more calls than you have agents (or AI sessions) to absorb, betting that ring-no-answers and voicemails will balance the books. When that bet is wrong, the caller hears silence and hangs up, an *abandoned call*, which is exactly what regulators cap (more on that below).

## The pacing math: CPS vs concurrency

The single most common scaling mistake is conflating two independent limits.

* **Calls per second (CPS)** governs how fast you may *initiate* calls, i.e., how many new call set-ups (SIP INVITEs) per second the platform will accept. Per Vobiz's own [CPS reference](/docs/faq/cps), "at a CPS of 1, your dialer should wait 1,000 milliseconds between API calls," and "even with a CPS of 1, you can still dial 3,600 calls per hour." It's a velocity limit.
* **Concurrency** governs how many calls are *active at the same time*, i.e., your channel count. See [Concurrency](/docs/faq/concurrency).

They are mathematically linked by Little's Law, with one refinement that trips people up: only **answered** calls hold a channel for the full talk time, so concurrency scales with your **answer (pickup) rate**:

```text theme={null}
concurrent_calls ≈ CPS × answer_rate × average_talk_time
```

So a campaign dialing at **5 CPS** with a **30% answer rate** and a **90-second** average talk time holds roughly **5 × 0.30 × 90 ≈ 135 concurrent channels** for connected calls, even though it initiates 5 calls a second. (Unanswered calls still occupy a channel briefly while ringing, add a `(1 − answer_rate) × CPS × average_ring_time` term for the full figure; the worked example below sums both.) Size CPS for how fast you reach your list and concurrency for how long connected conversations last; under-provision either and calls queue or fail. Vobiz's built-in [CPS & concurrency calculator](/docs/resources/calculator) does this arithmetic (including pickup rate and ring time) so you can provision before a campaign, not during the fire.

### A worked example: sizing a 50,000-dial campaign

Say you need to dial a 50,000-contact list in an 8-hour window, expect a 25% pickup rate, and your connected calls average 2 minutes (with unanswered calls ringing \~14 seconds before timeout). The dial rate is `50,000 ÷ (8 × 3,600 s) ≈ 1.74 CPS`, comfortably under most accounts' limits. But concurrency is set by *hold time*, not dial rate: connected calls (12,500 × 120 s) plus ring time on the rest (37,500 × 14 s) is \~2.0M call-seconds over 28,800 seconds ≈ **70 concurrent channels**. Provision \~20% headroom for peak-hour bursts and you land near 85 channels. The lesson: a "small" 1.74 CPS campaign still needs dozens of channels, and a predictive dialer that ignores this either blocks calls (under-provisioned) or abandons humans (over-paced). Always model both numbers before launch.

## What is answering machine detection (AMD)?

**Answering machine detection** is the platform classifying *what answered the call*, a live human, an answering machine / voicemail, a fax, or silence, in the first few seconds after pickup, then telling your application so it can branch. The payoff is direct: in most consumer outbound campaigns a large share of dials land in voicemail, and every one of those that reaches a human agent or an AI session before being classified is wasted capacity. AMD lets you hang up on machines, leave a message after the beep, or only connect humans.

## How AMD actually works

There's no magic, AMD is audio classification on the first moments of the answered call:

1. **Acoustic + cadence analysis.** The detector listens to the greeting and measures features like utterance length, speech-to-silence ratio, and rhythm. A human "Hello?" is short and followed by silence (they're waiting for you); a voicemail greeting is longer and continuous ("Hi, you've reached…"). A tunable *speech-length threshold* encodes exactly this heuristic, speech *shorter* than the threshold is classified human, *longer* is classified machine.
2. **Beep / tone detection.** To leave a message, the detector waits for the end-of-greeting beep or the silence that follows it, then signals "now safe to speak."
3. **ML-based classification (2024–2026).** Newer engines replace hand-tuned heuristics with trained models that use speech recognition and machine learning, returning richer labels (residential vs business human, for example) than a binary human/machine split.

Two properties define every AMD implementation: **latency** (how long before it decides) and the **accuracy/false-positive trade-off**. The longer you let the detector listen, the more confident it is, but the more dead air a real human hears first. That tension is why the *sync vs async* decision matters so much.

### Synchronous vs asynchronous AMD

* **Synchronous AMD** blocks the call until detection finishes. The result is reliable, but a human who answered hears several seconds of silence before anything happens, a terrible first impression and a major cause of early hangups.
* **Asynchronous AMD** lets the call proceed *immediately* (your answer flow runs, the human can start talking) while detection runs in the background and posts the verdict (`human`/`machine`/`fax`) to a callback URL the moment it's confident. A person who answers can begin interacting with no silence at all, while your app reacts to the AMD result when it arrives. Asynchronous is the right default for any real-time experience, and essential for AI agents.

## AMD modes, results, and tuning

Whatever voice platform you build on, AMD converges on the same handful of design choices. Knowing them lets you configure it sensibly on any stack:

* **Two detection intents.** Either *decide as soon as the called party is identified*, fastest, best for predictive dialers that want to connect a human or drop immediately, or *wait until the greeting ends* so you can leave a message after the beep. It's the classic speed-versus-accuracy fork: deciding early is quicker but less certain; waiting for the full greeting sees more audio and is more accurate but slower.
* **Result labels beyond human/machine.** Production AMD returns more than a binary: `human`, `machine`, `fax`, `silence`, and distinctions like *greeting ended on a beep* versus *ended on silence*. Newer ML-based detectors add finer classes (for example, residential versus business human) as the field moves from hand-tuned heuristics to trained models.
* **Tunable timing.** A detection timeout, a speech-length threshold (a short utterance reads as a human "Hello?", a long one as a voicemail greeting), a silence timeout, and greeting/word limits let you trade accuracy against latency for *your* traffic and accents.

These are the knobs to look for. The two properties that matter most for an AI agent, asynchronous delivery and low latency, are what the next section is about.

## AMD for voice AI agents: gating the media stream

This is where AMD stops being a contact-center nicety and becomes architectural. An AI voice agent connects to a call over a [bidirectional audio WebSocket](/docs/concepts/streaming-websockets) and starts its STT → LLM → TTS loop the instant audio flows. If a *voicemail* answered, the agent cheerfully delivers its opening line into a recording, you pay for the LLM and TTS, the prospect gets a confusing half-message, and the call is wasted.

The fix is to **gate the agent's media stream on a confirmed human**. Concretely:

1. Place the outbound call with **asynchronous** AMD enabled.
2. Let the call connect, but hold the agent's first utterance.
3. When the AMD callback returns `human`, release the agent to speak. If it returns a machine result, either hang up (`machine_detection=hangup`) or branch to a "leave voicemail" flow.

Every major AI-agent framework now exposes exactly this hook, [Vapi](https://docs.vapi.ai/calls/voicemail-detection) and [Retell](https://docs.retellai.com/build/handle-voicemail) both document voicemail detection so the agent only engages a real person. The reason async matters so much here is the [latency budget](/docs/blogs/what-is-a-voice-api): a natural conversation lives inside roughly a one-second round trip across telephony + STT + LLM + TTS. A *synchronous* AMD that adds 4 seconds of silence before the agent can even hear the caller destroys that budget; async keeps the human path instant and runs detection in parallel. Pair that with [native barge-in](/docs/audio-streams) so the caller can interrupt the agent, and the experience feels human instead of robotic.

## Outbound deliverability & compliance in 2026

Pacing and AMD keep your campaign *efficient*; compliance and reputation keep it *alive*. Three forces gate every US outbound program:

* **TCPA / FCC rules.** Federal rules under [47 CFR §64.1200](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-64/subpart-L/section-64.1200) govern autodialed and prerecorded calls, require prior express (often written) consent for many call types, restrict calling-time windows, and cap *abandoned* calls in telemarketing, the well-known three-percent abandonment provision that directly constrains how aggressively a predictive dialer can run. Build abandonment measurement into your pacing loop, not as an afterthought.
* **STIR/SHAKEN.** US carriers cryptographically sign caller ID with an **attestation** level, A (full), B (partial), or C (gateway), so downstream networks can reason about whether a number is who it claims to be. Higher attestation correlates with better treatment; spoofed or poorly-attested traffic gets filtered.
* **Number reputation / "Spam Likely."** Analytics engines (Hiya, First Orion, TNS) score numbers and surface labels on the called handset. A flagged number's answer rate falls off a cliff. Mitigation is operational: **rotate numbers**, set **per-number daily caps**, enforce **cooldown** periods, and use **local presence** so the callee sees a familiar area code. (See [number utilization best practices](/docs/best-practices/number-utilization).)

None of this is optional at scale; a single over-dialed, poorly-attested number can poison a whole pool.

## How Vobiz handles automated calling + AMD

[Vobiz](/docs/introduction) is the telephony **infrastructure** under your dialer or AI agent, you bring the campaign logic, Vobiz runs the calls. It powers voice-AI builders (Vapi, Retell, LiveKit, Pipecat, ElevenLabs); it does not ship its own agent. Concretely for outbound:

* **AMD as Make Call parameters.** Set [`machine_detection`](/docs/call/machine-detection) to `true` (detect and continue) or `hangup` (drop machine-answered calls automatically, the call ends with hangup cause [`9100` Machine Detected](/docs/concepts/hangup-causes)). Tune the window with `machine_detection_time` (2000–10000 ms), `machine_detection_initial_greeting`, `machine_detection_maximum_speech_length`, `machine_detection_initial_silence`, and `machine_detection_maximum_words`.
* **Asynchronous by callback.** Provide a `machine_detection_url` (with `machine_detection_method`) and Vobiz runs detection in the background, then POSTs the result (`IfMachine`, `Event: MachineDetection`, call identifiers) so your AI agent can gate its stream, no dead air on the human path.
* **Voicemail-end detection in XML.** Use [`<Wait silence="true" minSilence="2000"/>`](/docs/xml/wait/machine-detection) so that once a voicemail greeting finishes and there's silence, your flow advances (e.g., to drop a message) without waiting out the full timer.
* **Pace with real limits.** Size [CPS](/docs/faq/cps) and [concurrency](/docs/faq/concurrency) with the [calculator](/docs/resources/calculator); run the campaign through the [campaign manager](/docs/platform/campaigns/list) and [outbound best practices](/docs/best-practices/outbound-campaign-manager).
* **Protect reputation.** Number rotation, per-number caps, and cooldown are why Vobiz reports a **30% reduction in spam-flag rate**; custom caller ID via the [`<Dial>` `callerId`](/docs/xml/dial) attribute keeps a trusted, owned identity on every leg.
* **Built for the AI path.** Sub-80 ms single-hop media and bidirectional [audio streaming](/docs/audio-streams) leave more of the conversational latency budget for AMD and the agent's STT/LLM/TTS processing.

## Best practices & metrics for scaling outbound

Instrument these and tune against them:

* **Answer rate** - % of dials answered. The leading indicator of number-reputation health; a sudden drop means you're getting flagged.
* **Connect rate / contact rate** - % of dials that reach a *human* (answer rate × human-vs-machine split). This is what AMD protects.
* **AMD accuracy** - track false-human (machine misread as human → agent talks to voicemail) and false-machine (human misread as machine → you hang up on a real prospect). The second is worse; tune your thresholds to favor not abandoning humans.
* **Abandonment rate** - keep it under your regulatory cap; if predictive pacing pushes it up, throttle CPS or add agents/sessions.
* **Reputation hygiene** - monitor per-number volume against caps, rotate before a number degrades, and cool numbers down rather than burning them.

The throughline: **dial only as fast as you can handle the humans who answer, and only spend an agent (or an LLM token) on a confirmed human.** That's the whole game.

## Frequently asked questions

<AccordionGroup>
  <Accordion title="What is the difference between CPS and concurrency?">
    CPS (calls per second) limits how fast you can *initiate* calls; concurrency limits how many calls run *at the same time*. They relate by `concurrent_calls ≈ CPS × answer_rate × average_talk_time`, because only answered calls hold a channel for the full talk time. A 5 CPS campaign at a 30% answer rate with 90-second talk time holds \~135 channels for connected calls (plus a smaller ring-time term for unanswered).
  </Accordion>

  <Accordion title="How does answering machine detection work?">
    AMD analyzes the first seconds of audio after a call is answered, measuring greeting length, speech-to-silence cadence, and beep/tone, then classifies the answer as human, machine, fax, or silence. Newer engines use machine-learning models for richer, more accurate classification.
  </Accordion>

  <Accordion title="What is the difference between synchronous and asynchronous AMD?">
    Synchronous AMD blocks the call until detection finishes, adding seconds of silence a human can hear. Asynchronous AMD lets the call proceed immediately and posts the result to a webhook, so there's no dead air, which is essential for real-time AI voice agents.
  </Accordion>

  <Accordion title="How accurate is answering machine detection?">
    It depends on the mode. "Wait for the greeting to end" modes are the most accurate (they hear more audio) at the cost of a few seconds of latency; fast heuristic modes return in a few seconds but are less certain. Published accuracy figures vary widely, so validate on your own traffic and tune thresholds to avoid hanging up on real humans.
  </Accordion>

  <Accordion title="How do AI voice agents avoid talking to voicemail?">
    They gate the agent's media stream on a confirmed human: place the call with asynchronous AMD, hold the agent's first line, and only let it speak when the AMD callback returns `human`; otherwise hang up or branch to a voicemail flow. Vapi and Retell both expose voicemail-detection hooks for this.
  </Accordion>

  <Accordion title="How do I stop my outbound numbers from being flagged as 'Spam Likely'?">
    Rotate numbers, cap per-number daily volume, add cooldown periods, and use local-presence caller IDs you own. Combined with STIR/SHAKEN attestation, these practices reduce spam flagging, Vobiz reports a 30% reduction in spam-flag rate from rotation, caps, and cooldown.
  </Accordion>
</AccordionGroup>

## Sources

* [Vobiz - Make Call API](/docs/call/make-call) · [Machine detection](/docs/call/machine-detection) · [Hangup causes](/docs/concepts/hangup-causes)
* [Vapi - Voicemail Detection](https://docs.vapi.ai/calls/voicemail-detection) · [Retell - Handle Voicemail](https://docs.retellai.com/build/handle-voicemail)
* [US FCC - 47 CFR §64.1200 (telephone solicitation / abandoned calls)](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-64/subpart-L/section-64.1200)

<Card title="Build outbound on Vobiz" icon="rocket" href="/docs/quick-start">
  Provision a number and place your first AMD-gated outbound call in minutes.
</Card>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.