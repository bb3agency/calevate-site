# In-call model trials: Raghava Organics, 11 Oct 2026

Three outbound Telugu test calls made by the founder on `ENGINE=thinnest` after the specimen
call (`specimen-call-raghava-2026-10-11.md`). Each ran the D-749/D-751/D-752 platform text
(live apply `platform_prompt:d228658e40d43328`, applied 1, failed 0; instructions 7,798 of
8,000 characters). The agent speaks the founder's own cloned voice through our Cartesia key
(voice-only BYOK, Studio), so ThinnestAI allows only its `voiceOnlyByok` models: Prana, Prana
[Voice], GPT-OSS 120B, GPT-5 Nano, GPT-4.1 Nano (VERIFIED-VENDOR-DOCS
`thinnest-findings/mirror/snapshots/2026-10-07b/pages/api-reference/bring-your-own-keys.md:44-58`).

The transcripts are the founder's pastes from the call pages. The caller is the founder.

**Owner** as in the specimen doc: **ours** (prompt or adapter), **vendor** (ThinnestAI's
pipeline), **model** (the in-call model), **setting** (a value somebody chose).

## Settings found during the trials

Read from production with `psql` by the founder after call C:

| Setting | Value during the calls | Effect | Now |
|---|---|---|---|
| `agents.engine_model_id` | gpt-oss-120b (A), gpt-4.1-nano (B), gpt-5-nano (C) | which model answered | gpt-oss-120b (founder's choice after C) |
| `lead_call_policies.detect_machines` | **true** | the phone company listens for the first few seconds of every outbound call before the agent may speak (`channels/voice.md:619-622`, 8 Oct snapshot) | false |
| `agents.turn_silence_ms` | **500** | half a second of quiet before the agent's turn starts, on every reply | 250 (vendor's own default) |
| `agents.end_call_on_finish` | true | the agent may release the line when it decides the conversation is over | true |

The agent's own model (`engine_model_id`) overrides the console's in-call default
(`agents/service._engine_voice_fields`: `model or in_call_default_model(...)`). Changing the
console default to GPT-4.1 Nano therefore ran a live apply (applied 1, failed 0) that changed
nothing; the founder had to change the agent's own model. The console description now says so.

## Call A: GPT-OSS 120B (19:49)

Mostly short, correct turns. The price was right (six hundred rupees a kilo). The website and
"the team will send details" were correct (founder, 11 Oct 2026). "Our own organic farms in
Andhra Pradesh and Telangana" is unconfirmed against the knowledge.

| Class | Owner | Evidence |
|---|---|---|
| **Reasoning spoken aloud** | vendor + model | "We should end? Caller may ask more." spoken in the last turn |
| **Several closings glued into one turn, then hang-up before the caller said goodbye** | vendor + model | "Anything else I can help with?Thanks అండి, have a good day.thanks అండి, మీకు శుభ రాత్రి." with no spaces between the pieces |
| **Whole reply in English after a mixed caller line** | ours | caller "Okay, chilli powder price." → "One kilogram chilli powder costs six hundred rupees." |

The missing spaces between the glued pieces suggest separate generations joined by the
vendor's pipeline, not one model reply. UNKNOWN which: vendor question 23.

## Call B: GPT-4.1 Nano (20:10)

Short turns and natural Telugu, but a weaker conversation.

| Class | Owner | Evidence |
|---|---|---|
| **"End this call" taken as "never call me again"** | vendor + model + ours | caller "ఓకే అండి అంతే ఇంకా కట్ చేసేయండి థ్యాంక్ యూ" → the number was put on the do-not-call list at 20:11:09 |
| **Order taken with no details** | ours (script) + model | "ఒక కేజీ chilli" accepted without whole or powder, price, name or address; the call then went to "anything else?" |
| **Question and goodbye in one turn, with a Devanagari word** | model | "మీకు ఇంకేమైనా కావాలా?అన్నట్టు, … धन्यवाद అండి, వీలైనప్పుడు call చేయండి." |
| **Unverified service claim** | model | "గుంటూరు ప్రాంతానికి డెలివరీ చేస్తాం" without a knowledge search shown |

The opt-out evidence row: `{"rule": "engine_contact_opted_out", "matched": "",
"detected_by": "engine_platform"}`, `consent_source` `inbound_call_verbal`. ThinnestAI's own
agent filed it (its built-in do-not-call behaviour, `channels/voice.md:356-361`), not our
phrase list. The founder removed it from ThinnestAI's list and from `dnc_list`. The fix
(restore with attestation, and a prompt line separating "end this call" from "never call
again") is being built.

## Call C: GPT-5 Nano (20:20)

Clearly the worst.

| Class | Owner | Evidence |
|---|---|---|
| **Broken, unnatural Telugu** | model | "మంచి వాడు అండి", "అత్తచెయ్యి మంచి", "చక్కెరగా एक కేజీ" |
| **Own instructions spoken** | model | "అనే అడగాలని" ("I should ask") at the end of a turn |
| **Several questions and long turns** | model | three questions in turn 2; a five-clause turn after "cut the call" |
| **Symbols spoken** | model | "పడమరి/నాలుగు రహదారి" |
| **Ignored a request to end** | model | "కట్ చేసేయండి తర్వాత చూసుకుందాం", then "Cut the call", both answered with more talk |

## Felt by the caller on every call

- **2 to 3 seconds of silence after pickup.** Explained by `detect_machines` being on. Not
  yet re-measured with it off; vendor question 25 asks what else makes up that time.
- **600 ms to 1.5 s before each reply.** Part of it was the 500 ms pause setting. The rest is
  speech recognition, the model's first token (ThinnestAI's console figures: GPT-OSS 120B
  ~221 ms, GPT-4.1 Nano ~578 ms, GPT-5 Nano ~915 ms, `engine/thinnest._MODEL_CONSOLE_LATENCY_MS`),
  any knowledge search, and the first audio from the voice.
- **The voice is quiet, fast and flat.** ThinnestAI's console shows speed 1.0, volume 1.0 and
  no emotion for the own-key voice (founder screenshot). Their API (8 Oct snapshot) sets only
  the voice id (`api-reference/agents/set-agent-byok-voice.md`): vendor question 24.

## Founder's verdict

GPT-OSS 120B sounded best. GPT-5 Nano is ruled out. The founder believes Gemini models are
the best for Telugu; that is the subject of `in-call-model-research-2026-10-11.md`.
