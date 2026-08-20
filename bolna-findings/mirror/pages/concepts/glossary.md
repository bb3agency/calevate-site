> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Glossary

> Definitions for the key terms used throughout the Bolna documentation.

## A

**Agent**
A complete Voice AI configuration that can make and receive phone calls. An agent bundles together a prompt, a voice pipeline (transcriber + LLM + synthesizer), telephony settings, and optional tools.

**ASR (Automatic Speech Recognition)**
See *Transcriber*.

**Agent ID**
A UUID that uniquely identifies an agent in Bolna. Required when making calls or managing the agent via API. Example: `5bc97541-e320-4d95-a3a5-242cfe45621d`.

***

## B

**Batch**
A campaign that places calls to a list of recipients uploaded as a CSV file. Batches are created, scheduled, and tracked via the `/batches` API endpoints.

**Batch ID**
A string identifier for a batch. Example: `3c90c3cc0d444b5088888dd25736052a`.

**Buffer size**
The number of text characters the synthesizer accumulates before sending the first audio chunk. Smaller buffers start audio sooner; larger buffers produce smoother speech.

***

## C

**Call-disconnected**
An intermediate execution status — NOT the final state. Fires when the phone line drops, but post-call processing (transcript assembly, cost calculation, extraction) has not yet completed. Always wait for `completed`.

**Completed**
The terminal execution status indicating all post-call processing is done. At this point `conversation_duration`, `total_cost`, `recording_url`, and `extracted_data` are populated.

**Concurrency**
The number of simultaneous active calls your account can run. Visible in `GET /user/me` as `concurrency.max`. Contact support to increase.

**Context details**
Per-call metadata attached at call time, including `recipient_data` (the CSV row columns for batch calls) and any custom fields.

***

## D

**DTMF (Dual-Tone Multi-Frequency)**
Touch-tone signals generated when a caller presses phone keys (0–9, \*, #). Used in IVR agents for menu navigation.

***

## E

**Endpointing**
The process of detecting when a caller has finished speaking. Configured in milliseconds on the transcriber. Too low causes interruptions; too high adds dead air.

**Execution**
A single call event — one phone call placed or received. Identified by an `execution_id`. Contains the full call record: status, transcript, cost, recording URL, extracted data.

**Execution ID**
A UUID identifying a single call execution. Used to poll status or retrieve results. Example: `b7140255-af33-4608-8e97-04dd944b8e48`.

**Extracted data**
Structured data automatically pulled from the conversation transcript by post-call extraction (if configured). Returns a JSON object keyed by category and field name.

***

## G

**Graph agent**
An agent architecture where the conversation is structured as a directed graph of nodes, each with its own prompt and routing rules. Contrast with *conversation agent*.

**Guardrail**
A calling restriction that prevents calls from being placed under certain conditions — time of day, do-not-call lists, daily limits.

***

## H

**Hangup prompt**
A phrase or condition configured on an agent that triggers the agent to end the call when detected in conversation. Example: when the agent says "Goodbye" or "Have a great day."

***

## I

**Inbound call**
A call received by a Bolna agent on a phone number linked to the agent. The caller initiates.

**IVR (Interactive Voice Response)**
An agent type that routes callers based on key presses rather than AI conversation. See [IVR Inbound Calls](/docs/guides/inbound/ivr-inbound-calls).

***

## K

**Knowledge base**
A collection of documents (PDFs, URLs, text) that an agent can search during conversations using RAG (Retrieval-Augmented Generation). Configured in the LLM tab.

***

## L

**Latency**
The delay between when a caller finishes speaking and when the agent starts responding. Measured as Time to First Audio (TTFA) in milliseconds. See [Latency](/docs/concepts/latency).

**LLM (Large Language Model)**
The AI model that processes the conversation transcript and generates the agent's responses. Examples: GPT-4.1, Claude, Gemini.

***

## O

**Outbound call**
A call placed by Bolna to a recipient. Initiated via `POST /call` or as part of a batch.

***

## P

**Pipeline**
The ordered chain of processing components for a task: `[["transcriber", "llm", "synthesizer"]]`. Must be an array of arrays.

**Prompt**
The system instruction given to the LLM that defines the agent's persona, task, and behavior. Written in natural language.

***

## R

**RAG (Retrieval-Augmented Generation)**
A technique where the LLM is given relevant excerpts from a knowledge base before generating a response, allowing it to answer questions from your documents.

**Recording URL**
A URL to the audio recording of the call. Available in `telephony_data.recording_url` after the execution reaches `completed`.

***

## S

**Scheduled\_at**
The ISO 8601 timestamp at which a batch should start calling. Must use a numeric UTC offset (e.g. `+00:00`) — the `Z` suffix is rejected. Must be at least 2 minutes in the future; Bolna rounds up to the next 10-minute mark.

**Synthesizer**
The text-to-speech provider that converts the LLM's response into spoken audio. Examples: ElevenLabs, Cartesia, Azure TTS.

***

## T

**Task**
The unit of work inside an agent. A conversation task handles the real-time conversation; an extraction task runs post-call to pull structured data from the transcript.

**Telephony provider**
The phone network provider that handles call connections, phone number assignment, and audio transport. Examples: Plivo, Twilio, Exotel.

**Time to First Audio (TTFA)**
The latency metric reported per call in `latency_data.time_to_first_audio` (milliseconds). Measures from end of caller's utterance to start of agent's audio response.

**Toolchain**
The configuration block that defines the pipeline and execution mode for an agent task. Contains `execution` (e.g. `"sequential"`) and `pipelines` (array of arrays).

**Transcriber**
The speech-to-text provider that converts caller audio into text in real-time. Examples: Deepgram, Azure Speech, Sarvam.

**Transcript**
The full text of the conversation, with speaker labels (`assistant:` / `user:`). Available in the execution record after `completed`.

***

## W

**Wallet**
The credit balance used to pay for calls. Each call deducts from the wallet based on duration, provider costs, and platform fee. A `balance-low` execution status means the wallet was empty when the call was attempted.

**Webhook**
An HTTP POST that Bolna sends to your server at each execution status change. Delivers the same payload as `GET /executions/{id}`. Source IPs: `13.203.39.153`, `13.126.9.249`, `13.202.133.53`.

***

## Related

* [Platform Concepts](/docs/platform-concepts) — visual overview of how Bolna works
* [Call Flow](/docs/concepts/call-flow) — step-by-step lifecycle of a call
* [Errors & Status Codes](/docs/api-reference/errors) — full status enum tables
