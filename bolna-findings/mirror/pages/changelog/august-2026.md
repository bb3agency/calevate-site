> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for August, 2026

> Explore the latest features and improvements introduced in August 2026 for Bolna Voice AI agents.

<Update label="19th August, 2026">
  ## Cartesia Sonic 3.6 is available for voice agents

  Cartesia's newest Sonic model can now be selected as a synthesizer, as `sonic-preview` in the API and **Sonic 3.6 (Beta)** in the dashboard. It supports **42 languages** and works with every Cartesia voice available in Bolna.

  Sonic 3.5 remains the recommended choice for production agents while 3.6 is in beta.

  [Cartesia voice synthesis](/docs/providers/voice/cartesia)
</Update>

<Update label="12th August, 2026">
  ## Eleven v3 is available for voice agents

  ElevenLabs' most expressive model, `eleven_v3_conversational`, can now be selected as a synthesizer. It supports **74 languages**, including Hindi, Tamil, Bengali, Marathi, Gujarati, Kannada, Malayalam, Telugu and Punjabi, and every ElevenLabs voice available in Bolna works with it.

  One thing to know before switching an agent over: `speed`, `style` and `similarity_boost` have no effect on v3, and `temperature` maps to three stability presets (`0.0` creative, `0.5` natural, `1.0` robust).

  Turbo remains the default and the lower-latency option.

  [ElevenLabs voice synthesis](/docs/providers/voice/elevenlabs)
</Update>

<Update label="10th August, 2026">
  ## Sarvam saaras:v4 Transcriber Support

  Bolna now supports Sarvam's **saaras:v4** transcriber model — the latest Saaras speech-to-text model, transcribing directly in the original spoken language with automatic language detection support. Supports all 11 Indian languages.

  Learn more in the [Sarvam STT documentation](/docs/providers/transcriber/sarvam).
</Update>

<Update label="6th August, 2026">
  ## 🔌 Bolna joins viaSocket's app directory

  If you build automations in [viaSocket](https://viasocket.com/integrations/bolna), Bolna is now a first-class app you can drop into any flow — connect your API key once, no custom code needed.

  Six actions are live today:

  * **Make a Phone Call** — kick off an outbound call from any workflow
  * **Get All Executions** — pull call history and details into your flow
  * **List Voice AI Agents** — see every agent on your account
  * **List Phone Numbers** — see every number on your account
  * **List Knowledgebases** — see every knowledge base on your account
  * **List Providers** — see every provider connected to your account

  📘 [viaSocket integration overview](/docs/tutorials/viasocket/overview) · [Create a Bolna API connection with viaSocket](/docs/tutorials/viasocket/create-bolna-api-connection)
</Update>

<Update label="5th August, 2026">
  ## 🛠️ The MCP server now controls nearly your whole account

  When the [Bolna MCP server](/docs/build-with-ai/mcp) launched, it covered the basics — agents, calls, transcripts, account info. It's grown into something closer to a full remote control. From the same chat window, you can now say things like:

  * "Buy me a US number and route it to my support agent" — search, purchase, and set up inbound call routing
  * "Create a batch campaign from this CSV and schedule it for 9am" — batches can now be created, scheduled, stopped, or deleted, not just listed
  * "Add a disposition that pulls appointment\_time out of every call" — structured, typed data out of every transcript
  * "Set up a SIP trunk for my Twilio account and attach these numbers" — bring your own telephony
  * "Cancel every queued call for this agent" — stop one call or a whole agent's queue
  * "What did my Acme Corp sub-account spend this month?" — check and manage sub-accounts, and switch between them mid-conversation with a key you already have on hand

  Anything that deletes something, spends money, or places a real call still pauses for your confirmation first, same as before.

  📘 [MCP Overview](/docs/build-with-ai/mcp) · [Tool List](/docs/build-with-ai/mcp-tool-list) · [Prompt Cheatsheet](/docs/build-with-ai/mcp-prompts)
</Update>

<Update label="3rd August, 2026">
  ## 🎙️ Maya joins Bolna as a new voice synthesizer

  [Maya Research](https://www.mayaresearch.ai/)'s `Maya 2 Native` model is now available as a text-to-speech provider, with two voices — **Ananya** and **Arjun** — each covering all 11 supported languages, including Indian English.

  * Runs over a persistent WebSocket, so LLM output is spoken as it streams in rather than in fixed chunks
  * Language can switch mid-call without dropping the connection
  * Supports both telephony (mu-law) and web (native 24 kHz) audio

  📘 [Maya voice provider docs](/docs/providers/voice/maya)
</Update>
