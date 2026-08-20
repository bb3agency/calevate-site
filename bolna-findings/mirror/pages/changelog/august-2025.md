> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for August, 2025

> Explore the latest features, improvements, and API updates introduced in August 2025 for Bolna Voice AI agents.

<Update label="21st August, 2025">
  ## Support for scheduling calls at a future timestamp in `/call` endpoint.

  * If `scheduled_at` is provided, the call will be queued and executed at that timestamp. Refer [docs](https://www.bolna.ai/docs/api-reference/calls/make#body-scheduled-at).
</Update>

<Update label="20th August, 2025">
  ## Instantly Clone Voices with a Single Click

  * You can now create high-quality AI clones of any voice directly from the Voice Lab.
  * Simply provide a name and a 1-2 minute audio sample to generate a new, unique voice for your agents.
  * Voice cloning is powered by leading providers like ElevenLabs to ensure top-tier quality. Learn more in our [new guide to cloning voices](https://www.bolna.ai/docs/clone-voices).

  <Frame caption="New 'Clone Voices' feature in the Voice Lab">
    <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/clone_voices_1.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=b0886657f41e04c9832e9afc7e62d445" alt="Voice Lab clone voices feature interface in Bolna showing one-click voice cloning with audio sample upload" width="789" height="349" data-path="images/clone_voices_1.png" />
  </Frame>
</Update>

<Update label="3rd August, 2025">
  ## Added `OpenRouter` support

  * Support for the following models via [OpenRouter](/docs/providers/llm-model/openrouter). Learn more about OpenRouter from their [official website](https://openrouter.ai).
    1. `gpt-4.1` OpenRouter OpenAI
    2. `gpt-4.1-mini` OpenRouter OpenAI
    3. `gpt-4.1-nano` OpenRouter OpenAI
    4. `gpt-4o` OpenRouter OpenAI
    5. `gpt-4o-mini` OpenRouter OpenAI
    6. `gpt-4` OpenRouter OpenAI

  <Frame caption="OpenRouter OpenAI model clusters">
    <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/changelog/3_august_2025_openrouter_openai_models.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=277da385a277d1c4a5ee433f289c2d93" alt="OpenRouter OpenAI model selection interface in Bolna showing available GPT models for Voice AI agents" width="1658" height="890" data-path="images/changelog/3_august_2025_openrouter_openai_models.png" />
  </Frame>

  ## Add your own `OpenRouter` API keys

  * Use your own OpenRouter account by adding your API Key to the [OpenRouter provider](https://www.bolna.ai/docs/providers).

  <Frame caption="OpenRouter Provider connection">
    <img src="https://mintcdn.com/bolna-54a2d4fe/mJ1zPF3eB4Dyupzj/images/changelog/3_august_2025_openrouter_provider_connection.png?fit=max&auto=format&n=mJ1zPF3eB4Dyupzj&q=85&s=8e6529c1fc64ca65bca4614d1bf3e589" alt="OpenRouter provider connection setup in Bolna showing API key configuration" width="1936" height="1334" data-path="images/changelog/3_august_2025_openrouter_provider_connection.png" />
  </Frame>
</Update>
