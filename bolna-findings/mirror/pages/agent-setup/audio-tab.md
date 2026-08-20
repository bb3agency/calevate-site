> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Configure Voice and Transcription Settings

> Set up languages, speech-to-text, and text-to-speech for your Bolna Voice AI agent. Pick providers, select voices, clone custom voices, and tune audio quality.

The Audio Tab controls how your agent listens and speaks. Configure languages, choose transcription and voice providers, and tune audio quality. For multilingual agents, you can select **different STT and TTS providers per language**.

<Frame caption="Audio Tab showing language selector with English as primary, Deepgram for Speech-to-Text, ElevenLabs for Text-to-Speech with voice tuning sliders">
  <img src="https://mintcdn.com/bolna-54a2d4fe/xje3IUNKzO7g_x01/images/getting-started/agent-setup/audio-tab.png?fit=max&auto=format&n=xje3IUNKzO7g_x01&q=85&s=f30ec22e787e5a9205d092f0e32884c4" alt="Full Audio Tab view with Languages section showing English Primary, Hindi, and Dutch, Speech-to-Text with Deepgram nova-3 and Keywords, Text-to-Speech with ElevenLabs Eleven Turbo v2.5, Nila voice, and tuning sliders for Buffer Size, Speed rate, Similarity Boost, Stability, and Style Exaggeration" width="1502" height="1258" data-path="images/getting-started/agent-setup/audio-tab.png" />
</Frame>

***

## Languages

Set the languages your agent can understand and speak. Pick a primary language and add secondary languages for multilingual conversations.

<Frame caption="Language selector showing English as the primary language, with Dutch and Hindi added as secondary languages">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uyz7-RHjowDG1vOL/images/getting-started/agent-setup/audio-language.png?fit=max&auto=format&n=uyz7-RHjowDG1vOL&q=85&s=ae46bda408d0d4116f4e49db63b9bc5f" alt="Bolna Audio Tab language configuration showing English marked as Primary, Dutch and Hindi as secondary languages, and an Add Language button on the right" width="1024" height="149" data-path="images/getting-started/agent-setup/audio-language.png" />
</Frame>

* **Primary Language** is marked with `(Primary)` and is the language your agent uses at the start of every conversation. The main prompt and multilingual settings are tied to this language.
* **Secondary Languages** allow the agent to understand and respond when a caller switches languages mid-call.
* Click **+ Add Language** to add more languages.
* Remove any language by clicking the **x** next to it.

### Changing the Primary Language

Click the **crown icon** next to any secondary language to make it primary. A tooltip will confirm the action, for example "Make Hindi primary". This sets the selected language as the default for the main prompt and multilingual settings.

<Frame caption="Clicking the crown icon on Hindi shows a tooltip to make it the primary language">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uyz7-RHjowDG1vOL/images/getting-started/agent-setup/audio-language-primary.png?fit=max&auto=format&n=uyz7-RHjowDG1vOL&q=85&s=3de6a01c0665cd620274718c77e3d8a5" alt="Tooltip showing Make Hindi primary option when clicking the crown icon next to Hindi in the Bolna language selector" width="670" height="268" data-path="images/getting-started/agent-setup/audio-language-primary.png" />
</Frame>

### Supported Languages

| Language   | Code |
| ---------- | ---- |
| English    | `en` |
| Hindi      | `hi` |
| Bengali    | `bn` |
| Assamese   | `as` |
| French     | `fr` |
| Gujarati   | `gu` |
| Indonesian | `id` |
| Kannada    | `kn` |
| Malay      | `ms` |
| Malayalam  | `ml` |
| Marathi    | `mr` |
| Odia       | `od` |
| Punjabi    | `pa` |
| Spanish    | `es` |
| Tamil      | `ta` |
| Telugu     | `te` |
| Urdu       | `ur` |
| Dutch      | `nl` |

<Info>
  For agents that handle multiple languages in a single call, see the [Multilingual Support](/docs/customizations/multilingual-languages-support) guide.
</Info>

***

## Speech-to-Text

Controls how your agent converts the caller's spoken words into text before the LLM processes them. For multilingual agents, each language can have its own STT provider and model. Select a language tab to configure its transcription settings independently.

<Info>
  Different languages may perform better with different providers. For example, use **Sarvam** for Hindi and **Deepgram** for English.
</Info>

<Frame caption="Speech-to-Text configuration with Azure selected as provider and model, and a Keywords field showing Bruce:100">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uyz7-RHjowDG1vOL/images/getting-started/agent-setup/audio-stt.png?fit=max&auto=format&n=uyz7-RHjowDG1vOL&q=85&s=4a9eea99f91125de5713e665c8b32676" alt="Bolna Speech-to-Text settings showing Provider dropdown set to Azure, Model dropdown set to Azure, and Keywords input field with Bruce:100 as an example keyword boost entry" width="1024" height="271" data-path="images/getting-started/agent-setup/audio-stt.png" />
</Frame>

### Provider and Model

Choose a transcription provider from the **Provider** dropdown, then pick the specific model from the **Model** dropdown.

| Provider       | What it offers                                                 |
| -------------- | -------------------------------------------------------------- |
| **AssemblyAI** | Real-time transcription with strong punctuation and formatting |
| **Azure**      | Microsoft Azure Speech Services                                |
| **Deepgram**   | High-accuracy, low-latency transcription with keyword boosting |
| **ElevenLabs** | Transcription powered by ElevenLabs                            |
| **Gladia**     | Multilingual transcription service                             |
| **Google**     | Google Cloud Speech-to-Text                                    |
| **OpenAI**     | OpenAI Whisper-based transcription                             |
| **Sarvam**     | Optimized for Indian languages like Hindi, Tamil, and Telugu   |
| **Smallest**   | Lightweight, fast transcription provider                       |

### Keywords

Boost recognition accuracy for specific words the transcriber might miss, such as brand names, product names, or technical terms. Enter keywords in the format `word:boost_value` (e.g., `Bruce:100`).

<Note>
  Keyword boosting is **only available with Deepgram**. The Keywords field has no effect when using other providers.
</Note>

***

## Text-to-Speech

Controls how your agent sounds when speaking to the caller. For multilingual agents, each language can have its own TTS provider, model, and voice. Select a language tab to configure voice settings independently.

<Frame caption="Text-to-Speech configuration with Sarvam as provider, Bulbul v2 as model, and Anjura voice selected, along with voice tuning sliders">
  <img src="https://mintcdn.com/bolna-54a2d4fe/cPN9NUobq5alKAm2/images/getting-started/agent-setup/audio-tts.png?fit=max&auto=format&n=cPN9NUobq5alKAm2&q=85&s=39679feb5e56682141a48649f06ca8e7" alt="Bolna Text-to-Speech settings showing Sarvam provider, Bulbul v2 model, Anjura voice selected, with sliders for Buffer Size at 220, Speed rate at 1, Similarity Boost at 0.65, Stability at 0.7, and Style Exaggeration at 0" width="1024" height="423" data-path="images/getting-started/agent-setup/audio-tts.png" />
</Frame>

### Provider, Model, and Voice

<Steps>
  <Step title="Select a Provider">
    Choose from **AzureTTS**, **Cartesia**, **ElevenLabs**, or **Sarvam**.
  </Step>

  <Step title="Pick a Model">
    Select the model that fits your latency and quality needs (e.g., ElevenLabs `eleven_turbo_v2_5` for low latency).
  </Step>

  <Step title="Choose a Voice">
    Click the **Voice** dropdown to browse all voices for the selected provider and model.
  </Step>
</Steps>

### Browsing Voices

Click the Voice dropdown to see a searchable list of all available voices. Filter by gender using the **All**, **Male**, **Female**, and **Neutral** tabs. Each voice shows a **play button** so you can preview it before selecting.

<Frame caption="Voice selector dropdown showing a searchable list of voices with gender filter tabs and play preview buttons">
  <img src="https://mintcdn.com/bolna-54a2d4fe/cPN9NUobq5alKAm2/images/getting-started/agent-setup/audio-voice-selector.png?fit=max&auto=format&n=cPN9NUobq5alKAm2&q=85&s=aaa9c75d867d2675b9e72b85ea6fd13f" alt="Bolna voice selector dropdown with search bar, gender filter tabs for All Male Female and Neutral, and voices including Chef DJ, Viraj, Ben, Roger, Matt, and Angelica with play buttons" width="892" height="758" data-path="images/getting-started/agent-setup/audio-voice-selector.png" />
</Frame>

### Preview Welcome Message

Click **Preview welcome message** to hear the selected voice speak your agent's welcome prompt (configured in the [Agent Tab](/docs/agent-setup/agent-tab)). This lets you test how the voice sounds before going live.

### Voice Tuning Parameters

Fine-tune your agent's voice using the sliders below the voice selector. Available parameters may vary by provider.

| Parameter              | What it controls                                                                                                                                                  |
| ---------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Buffer Size**        | Audio buffered before playback begins. Higher values produce smoother audio but increase delay. Values between 150 and 250 work well for real-time conversations. |
| **Speed Rate**         | Speaking speed. `1` is natural pace, above `1` is faster, below `1` is slower.                                                                                    |
| **Similarity Boost**   | How closely the output matches the original voice sample. Higher values are more faithful but may reduce naturalness.                                             |
| **Stability**          | Voice consistency across sentences. Higher values keep tone steady, lower values add expressive variation.                                                        |
| **Style Exaggeration** | Emphasis on stylistic characteristics. `0` is neutral, higher values add more personality.                                                                        |

<Warning>
  High **Buffer Size** improves quality but adds latency. If callers notice a delay before the agent speaks, lower this value.
</Warning>

***

## Adding and Cloning Voices

Click the **Add Voice +** button in the Text-to-Speech section to add a custom voice by ID or clone one from an audio sample.

<Note>
  Custom voice uploads are **only available for ElevenLabs and Cartesia**.
</Note>

### Add a Voice by ID

Use this when you already have a voice ID from your provider's voice library.

<Frame caption="Add Voice dialog with the Add by ID tab selected, ElevenLabs as provider, and a Voice ID input field">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uyz7-RHjowDG1vOL/images/getting-started/agent-setup/audio-add-voice.png?fit=max&auto=format&n=uyz7-RHjowDG1vOL&q=85&s=255e1fd7e0268c2d147e080c8f01d565" alt="Bolna Add Voice modal with Add by ID tab active, ElevenLabs selected as provider, Voice ID input field with placeholder pNInz6obpgDQGcFmaJgB, and a blue Add voice button" width="1024" height="681" data-path="images/getting-started/agent-setup/audio-add-voice.png" />
</Frame>

<Steps>
  <Step title="Select the Add by ID tab">
    Make sure the **Add by ID** tab is selected in the dialog.
  </Step>

  <Step title="Choose a Provider">
    Select **ElevenLabs** or **Cartesia**.
  </Step>

  <Step title="Enter the Voice ID">
    Paste the voice ID from your provider. For ElevenLabs, find IDs in the [ElevenLabs voice library](https://elevenlabs.io/voice-library).
  </Step>

  <Step title="Click Add voice">
    The voice will appear in the Voice dropdown for all your agents.
  </Step>
</Steps>

### Clone a Voice

Create a new voice by uploading an audio recording. Useful for maintaining a consistent brand voice or using a specific person's voice (with their permission).

<Frame caption="Clone Voice dialog with Cartesia as provider, fields for Voice name, Description, Sample language, and a file upload area">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uyz7-RHjowDG1vOL/images/getting-started/agent-setup/audio-clone-voice.png?fit=max&auto=format&n=uyz7-RHjowDG1vOL&q=85&s=3bfd196449113581dc1f51764151b129" alt="Bolna Clone Voice modal with Cartesia selected as provider, Voice name placeholder Sales Assistant Voice, Description placeholder Warm male Indian accent, Sample language Hindi, and drag-and-drop upload area for audio files up to 10 MB" width="944" height="1024" data-path="images/getting-started/agent-setup/audio-clone-voice.png" />
</Frame>

<Steps>
  <Step title="Select the Clone Voice tab">
    Switch to the **Clone Voice** tab in the dialog.
  </Step>

  <Step title="Choose a Provider">
    Select **ElevenLabs** or **Cartesia**.
  </Step>

  <Step title="Enter Voice Details">
    Add a **Voice name** (e.g., "Sales Assistant Voice") and **Description** (e.g., "Warm male Indian accent").
  </Step>

  <Step title="Select Sample Language">
    Choose the language of your audio sample.
  </Step>

  <Step title="Upload an Audio Sample">
    Drag and drop your audio file or click **click to browse**. Audio files only, maximum 10 MB.
  </Step>

  <Step title="Click Clone voice">
    The platform processes your sample and adds the new voice to the Voice dropdown.
  </Step>
</Steps>

### Supported Languages for Voice Cloning

Both ElevenLabs and Cartesia support the same set of languages for cloning:

| Language            | Code | Language   | Code |
| ------------------- | ---- | ---------- | ---- |
| English             | `en` | Hindi      | `hi` |
| Bengali             | `bn` | Assamese   | `as` |
| Dutch               | `nl` | French     | `fr` |
| Gujarati            | `gu` | Indonesian | `id` |
| Kannada             | `kn` | Malay      | `ms` |
| Malayalam           | `ml` | Marathi    | `mr` |
| Odia                | `od` | Punjabi    | `pa` |
| Spanish             | `es` | Tamil      | `ta` |
| Telugu              | `te` | Urdu       | `ur` |
| Indian Multilingual | -    |            |      |

<Tip>
  For best results, use a clean recording with no background noise, a single speaker, and at least 30 seconds of continuous speech.
</Tip>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Engine Tab" icon="gear" href="/docs/agent-setup/engine-tab">
    Configure interruption handling, endpointing, and latency
  </Card>

  <Card title="Multilingual Support" icon="globe" href="/docs/customizations/multilingual-languages-support">
    Set up agents that speak multiple languages in a single call
  </Card>

  <Card title="Clone Voices" icon="waveform" href="/docs/clone-voices">
    Create a custom voice from an audio sample
  </Card>

  <Card title="Deepgram Provider" icon="microphone" href="/docs/providers/transcriber/deepgram">
    Explore Deepgram transcription models and keyword boosting
  </Card>
</CardGroup>
