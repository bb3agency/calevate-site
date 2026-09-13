# Replacing the orchestrator: LiveKit Agents vs Pipecat, read from source

**Date:** 12 September 2026
**Question:** which framework replaces Bolna as Calevate's voice orchestrator?
**Verdict:** **Pipecat**, on one structural asymmetry plus Indian-carrier support. Recorded
below with the evidence for each claim and, explicitly, the claims this document does NOT
establish.

## 0. Evidence class, and why this document exists at all

Every vendor documentation host for both candidates is **egress-blocked from this
container** — measured, not assumed, on 12 Sep 2026:

```
docs.livekit.io      blocked by the egress proxy (EGRESS_BLOCKED)
docs.pipecat.ai      connect failed
livekit.io           connect failed
www.daily.co         connect failed
raw.githubusercontent.com   200
pypi.org                    200
```

Both frameworks are open source, so the doc blockade is not a constraint — it is an
upgrade. Every behavioural claim here is **VERIFIED-OSS**, read from a shallow clone at a
named commit, which outranks documentation: docs describe intent, source is what runs.

| Repository | Commit read |
|---|---|
| `github.com/pipecat-ai/pipecat` | `f67c18afddbfb0609991cd6830355713baaad01b` |
| `github.com/livekit/agents` | `34a4e8f5bccad92ed9aa78ccc69e17eafc2720f1` |

Anything about **price, plan floors, included minutes, region availability, SLAs or data
processing terms** is NOT in either repository and is therefore **not established here**.
§8 lists those gaps rather than filling them.

## 1. The decisive asymmetry

Pipecat ships a **LiveKit transport**:

```
src/pipecat/transports/    daily  heygen  lemonslice  livekit  local
                           moq  smallwebrtc  tavus  vonage  websocket  whatsapp
```

`src/pipecat/transports/livekit/transport.py` imports `livekit.rtc` and defines
`LiveKitInputTransportMessageFrame` / `LiveKitOutputTransportMessageFrame`; the optional
dependency is declared as `pipecat-ai[livekit]`.

**LiveKit Agents ships no Pipecat pipeline.** The relationship is one-directional.

So the two choices are not symmetric bets:

- Choose **Pipecat** → LiveKit remains available as a transport. If LiveKit's India SIP
  edge proves valuable, we adopt it *underneath* the pipeline we already wrote.
- Choose **LiveKit Agents** → Pipecat's pipeline, serializers and eval harness are out.

This decision is being made **before launch, with no numbers provisioned, no accounts and
no live traffic** — i.e. under maximum uncertainty. Under uncertainty the option that
preserves the other option is worth more than any single feature comparison, and that is
the primary ground for the verdict.

## 2. Indian carriers

Pipecat treats Indian carriers as **first-class wire formats**, not generic SIP:

```
src/pipecat/serializers/   exotel.py  genesys.py  plivo.py  telnyx.py  twilio.py
                           vonage.py  protobuf.py  rtvi_client.py
```

`PlivoFrameSerializer` and `ExotelFrameSerializer` both default to **8000 Hz** with a
configurable pipeline-rate override — the PSTN narrowband rate, handled at the serializer
rather than left to the integrator.

This matters because of what D-421 already verified about our own telephony: 140-series is
carried by **Vobiz** and 160-series by **Plivo**, numbers are sourced **directly from the
carrier** (Bolna's own Indian inventory is geographic landline ranges only and cannot
satisfy our compliance gate), and there is **no provisioning API at all** — documents to
the carrier's compliance address, ₹5,900 DLT PE registration on the TATA portal, carrier
allocation, then header and template approval.

**The carrier relationship is therefore already ours and survives the migration intact.**
That removes the single largest hidden cost this kind of move usually carries.

LiveKit reaches carriers through SIP trunking rather than per-carrier serializers. That is
a legitimate design and may well work with Plivo; what this document records is that
Pipecat has named, in-tree support for both Indian carriers we actually use, and that no
equivalent Exotel path was found in the LiveKit repository.

## 3. The speech stack — our exact legs, in both

### Sarvam STT

| | Pipecat | LiveKit |
|---|---|---|
| Models | `saaras:v3`, `saaras:v4`, `saaras:v3-realtime` | `SarvamSTTModels = Literal["saaras:v3", "saaras:v4"]` |
| Default | — | `model: SarvamSTTModels \| str = "saaras:v4"` |
| Sunset guard | — | `_SUNSET_STT_MODELS = frozenset({"saarika:v2.5", "saaras:v2.5"})`, raising *"Sarvam STT model '…' is sunset. Please migrate to 'saaras:v3' or 'saaras:v4'."* |
| Telugu | `Language.TE_IN: "te-IN"` | `TE_IN = "te-IN"` |
| Modes | — | `Literal["transcribe", "translate", "verbatim", "translit", "codemix"]` |

Two findings worth keeping:

**LiveKit's sunset guard names the exact model that cost us six live 400s in the 11 Sep
session.** `saaras:v2.5` was the configured value when publishes were failing. A library
that refuses it by name at construction is a class of defect we debugged by hand.

**`codemix` is a documented STT mode.** Telugu-English code-switching is the realistic
speech pattern for our callee population, and it is a first-class mode rather than
something to prompt around. Pipecat's Sarvam service exposes no equivalent mode literal in
the source read.

### Sarvam TTS

Both carry `bulbul:v3`. Pipecat's `TTS_MODEL_CONFIG` makes it the **default** and records
in its module docstring that `bulbul:v2` is deprecated and cannot synthesize — matching the
correction already standing in this repo's `CLAUDE.md`.

**The speaker lists disagree three ways, and this document does not resolve it:**

| Source | `bulbul:v3` speakers |
|---|---|
| Live `GET /voice-config/tts/voices` against our Bolna account, 11 Sep 2026 | **9** |
| Pipecat source, `SarvamTTSSpeakerV3` | **25** |
| LiveKit source, `bulbul:v3` speaker map | **33** (includes `kavitha`, `shruti`, `suhani`, `rupali`, `tanya`) |
| Sarvam's own docs, as relayed by the founder's research agent, 12 Sep 2026 | **37** |

Four readings, four counts, and the lists are not nested — Pipecat has `amelia` and
`sophia`, which do not appear in the relayed docs list. **Only a call to Sarvam's own API
settles which is current**, and none of these may be quoted as the answer (hard rule 11).

What is not in doubt: **9 is the smallest by a wide margin, and 9 is what the engine gave
us.** The founder's complaint that Bolna offers too few voices is corroborated from two
independent library sources.

### Cartesia

Both support Sonic. LiveKit's `TTSModels` literal enumerates through `sonic-3` and
prefix-matches `sonic-3*` via `_is_sonic_3()`; Pipecat's service references `sonic-3.6`.
Our configured model is `sonic-3.5` (`voices.py::TtsModel`), so **the exact identifier we
ship should be confirmed against whichever library is adopted** before the first call.

## 4. Turn detection — the finding that matters most

This repo's own arithmetic (computed 12 Sep 2026 from
`calevate_shared.engine.LATENCY_BUDGET`) says:

```
voice-to-voice target                 500 ms   (founder, 27 Aug 2026)
declared floor, all stages at vendor floors   600 ms   composes = False
what we actually ship, floor         650–1050 ms
  of which INHERITED_TURN_DETECTION_MS  650 ms   = 1.3x the whole target
  budgeted for that same stage          100 ms   (6.5x over budget)
```

The 650ms is Bolna's `transcriber.endpointing` (250) plus `incremental_delay` (400), both
inherited defaults, and both sit **inside Bolna's own recommended range**. An India-hosted
orchestrator removes only the 100ms ocean crossing. **Turn detection, not geography, is the
binding constraint on our latency target.**

Both candidates replace fixed-timeout endpointing with a **semantic turn-detection model**:

```
LiveKit   livekit-plugins/livekit-plugins-turn-detector/.../  base.py  english.py  multilingual.py
Pipecat   src/pipecat/audio/turn/smart_turn/  base_smart_turn.py  http_smart_turn.py
                                              local_coreml_smart_turn.py
                                              local_smart_turn_v2.py  local_smart_turn_v3.py
```

A model that decides *"this person has finished speaking"* from the utterance, rather than
waiting a fixed 650ms of silence, is the only mechanism found in this evaluation that could
close the dominant term. **This is the strongest engineering argument for leaving Bolna,
and it is not the argument anyone started with.** It is also unmeasured: neither model's
real latency or accuracy on Telugu PSTN audio is established here, and §8 records that.

Pipecat additionally runs turn detection **locally** (CoreML / ONNX variants in-tree), which
keeps it off a network round trip. LiveKit's `multilingual.py` is the closer fit to a
Telugu-first product on its face; neither claim is measured.

## 5. Telephony and conversation features

Read from the LiveKit repository:

```
livekit-agents/livekit/agents/beta/workflows/   warm_transfer.py  dtmf_inputs.py
                                                address.py  credit_card.py  dob.py
                                                email_address.py  name.py  phone_number.py
livekit-agents/livekit/agents/voice/amd/        detector.py  classifier.py
```

Structured-capture workflows for name, phone number, email, address and date of birth map
almost exactly onto our extraction-schema product, and `amd/` is answering-machine
detection — directly relevant to outbound campaigns. Pipecat's nearest equivalent found is
`src/pipecat/extensions/voicemail/voicemail_detector.py`.

**This is the one axis where LiveKit is materially ahead**, and it is recorded as such
rather than minimised. It does not outweigh §1 and §2, because these are conversation
patterns we can write, whereas a carrier integration and a preserved option are not.

## 6. What neither gives us

Both are **frameworks with a managed runtime**, not declarative agent platforms. Neither
holds a business-agent object. Of the 27 operations on
`calevate_shared.engine.VoiceEngine`, these have **no vendor equivalent in either** and move
into our own control plane:

```
create_agent   update_agent   get_agent   delete_agent
attach_kb      detach_kb      list_kb     list_account_kb
set_llm_credential            list_voices
```

That is not a defect of either candidate; it is the shape of the category, and it is the
honest cost of the move. What we gain in exchange is that `get_agent` stops being a
read-back of a vendor's opinion and becomes a read of our own committed configuration —
i.e. agent drift ceases to exist as a failure mode rather than being detected after it
happens.

Neither addresses **TRAI/DLT** in any form found in either repository: Principal Entity and
Telemarketer registration, 140/160 header registration, content templates, consent ledger,
DNC/NCPR scrubbing and calling-hour windows remain ours and the carrier's. Unchanged by
this decision in either direction.

## 7. Verdict

**Pipecat**, on:

1. **§1** — it preserves LiveKit as an option; the reverse is false. Decisive under
   pre-launch uncertainty.
2. **§2** — first-class Plivo *and* Exotel serializers at the PSTN rate, against carriers
   we already hold the relationship with.
3. **§3** — `bulbul:v3` default, `saaras:v4`, Telugu first-class in both legs.
4. **§4** — local semantic turn detection, against the term that actually dominates our
   latency gap.
5. **Cost shape** — no monthly platform floor found in-repo, against a development phase of
   unknown length at near-zero minutes. Unverified: see §8.

LiveKit is the better product on §5 and arguably §4's multilingual model, and its India SIP
edge is real. None of that is lost: it is reachable later through
`pipecat.transports.livekit`.

## 8. NOT ESTABLISHED — do not quote this document for any of it

> ⚠ **PARTLY CLOSED, 13 Sep 2026 — read
> `docs/evidence/orchestrator-commercial-and-carrier-2026-09-13.md` before using this list.**
> The commercial half was researched the next day. §9's reversal condition is **NOT triggered**:
> Pipecat Cloud has no mandatory monthly floor AND has an India region (`ap-south`, Mumbai). The
> verdict stands. Pricing, floors, regions and concurrency for both candidates are answered there
> at class REPORTED; the SLA, DPA, training-clause, retention, sub-processor and turn-detector
> benchmark rows below are **still unanswered** and were re-confirmed as not-found. That companion
> document also carries three carrier findings this one did not look for — an irreversible Plivo
> account decision, a per-tenant compliance application that adds a stage to onboarding, and a
> contradiction about whether a landline number may carry a commercial service call that outranks
> everything in either document.

- **Pricing, monthly floors, included minutes, reserved-instance rates** for either
  platform. Not in either repository. The founder's research agent reports LiveKit Ship at
  $50/month with 5,000 agent + 5,000 SIP minutes and Pipecat `agent-1x` at $0.01/active
  minute with no floor — **REPORTED, relayed, unverified from here.**
- **Region availability** (`ap-south`/Mumbai) for either managed runtime, and whether
  Pipecat Cloud pins media to India.
- **What an "active minute" bills** on Pipecat Cloud — connected call time, or container
  startup and teardown as well.
- **Real latency or Telugu accuracy** of either turn-detection model on 8 kHz PSTN audio.
- **Which Sarvam speaker list is current** (§3).
- **Whether `sonic-3.5` is accepted** by the adopted library's Cartesia plugin.
- **SLA, DPA, training-on-data terms, sub-processors** for either managed runtime.
- **Tested Exotel interoperability for LiveKit** — absence of evidence in the repository is
  not evidence of absence.

## 9. What would reverse this

- Pipecat Cloud pricing turning out to carry a floor comparable to LiveKit Ship's, **and**
  Pipecat Cloud having no India region while LiveKit does. Then LiveKit's India SIP edge is
  bought at the same price and §1's option value is the only thing left on Pipecat's side.
- `pipecat.transports.livekit` proving unmaintained or unable to carry SIP participants.
  §1's whole argument rests on that transport being real; it is present and imports the
  LiveKit RTC SDK, but it has not been run.

Either would be a decision-log entry superseding this document, not a silent change.
