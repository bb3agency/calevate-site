> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Set Up Multilingual Voice AI Agents

> Deploy Bolna Voice AI agents in multiple languages. Configure per-language prompts, language switching, handoff messages, and multilingual knowledge bases.

Bolna supports multiple languages, letting you deploy voice agents globally. Language support is integrated across all components: transcription, LLM processing, and voice synthesis.

<Frame caption="Language selection in the Audio Tab showing English as primary with Dutch and Hindi as secondary languages">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uyz7-RHjowDG1vOL/images/getting-started/agent-setup/audio-language.png?fit=max&auto=format&n=uyz7-RHjowDG1vOL&q=85&s=ae46bda408d0d4116f4e49db63b9bc5f" alt="Bolna Audio Tab language configuration showing English marked as Primary, Dutch and Hindi as secondary languages, and an Add Language button" width="1024" height="149" data-path="images/getting-started/agent-setup/audio-language.png" />
</Frame>

***

## How Multilingual Agents Work

A multilingual agent can understand and respond in multiple languages within a single call. Here is how the pieces fit together:

<CardGroup cols={3}>
  <Card title="Languages" icon="language">
    Add languages in the [Audio Tab](/docs/agent-setup/audio-tab) or [Agent Tab](/docs/agent-setup/agent-tab). They stay synced across both.
  </Card>

  <Card title="Per-Language Prompts" icon="file-lines">
    Each language gets its own prompt tab. Write a dedicated prompt for every language your agent supports.
  </Card>

  <Card title="Language Switching" icon="shuffle">
    A shared instruction field tells the agent when to switch languages mid-call.
  </Card>
</CardGroup>

***

## Setting Up Languages

<Steps>
  <Step title="Add Languages">
    In the [Audio Tab](/docs/agent-setup/audio-tab) or [Agent Tab](/docs/agent-setup/agent-tab), click **+ Add Language**. Languages sync between both tabs automatically.
  </Step>

  <Step title="Set a Primary Language">
    Click the **crown icon** next to any language to make it primary. The primary language is what the agent starts every conversation in.
  </Step>

  <Step title="Write a Prompt for Each Language">
    In the [Agent Tab](/docs/agent-setup/agent-tab), select each language tab and write its prompt. The agent activates the matching prompt when speaking in that language.
  </Step>

  <Step title="Configure Handoff Messages">
    In the [Advanced Settings](/docs/agent-setup/agent-tab#per-language-advanced-settings) for each language, set a **Handoff Message** that plays when the agent transitions away from that language.
  </Step>
</Steps>

<Frame caption="Crown icon tooltip to set a language as primary">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uyz7-RHjowDG1vOL/images/getting-started/agent-setup/audio-language-primary.png?fit=max&auto=format&n=uyz7-RHjowDG1vOL&q=85&s=3de6a01c0665cd620274718c77e3d8a5" alt="Tooltip showing Make Hindi primary when clicking the crown icon next to Hindi" width="670" height="268" data-path="images/getting-started/agent-setup/audio-language-primary.png" />
</Frame>

***

## Language Switching

The **Language Switching Instructions** field in the [Agent Tab](/docs/agent-setup/agent-tab) is a single shared field that applies to all languages. It tells the agent when and how to switch languages during a call.

| What to include        | Example                                               |
| ---------------------- | ----------------------------------------------------- |
| **Trigger conditions** | "Switch to Hindi if the user speaks in Hindi"         |
| **Fallback behavior**  | "Fall back to English if the language is unsupported" |
| **Default rule**       | "Respond in the language the user is currently using" |

<Info>
  Write these once. They apply across all languages automatically.
</Info>

### Auto-Switching System Messages

Beyond prompt-level switching, Bolna can also **auto-detect** the caller's language and switch system messages to match. This works for:

<CardGroup cols={3}>
  <Card title="User Online Check" icon="user-check">
    "Are you still there?" adapts to the caller's language
  </Card>

  <Card title="Hangup Message" icon="phone">
    Farewell message plays in the detected language
  </Card>

  <Card title="Tool Call Messages" icon="gear">
    "Please wait" messages during API calls match the language
  </Card>
</CardGroup>

<Tip>
  Detection activates after 3 conversation turns to ensure accuracy. See the full [Auto-Switch Languages](/docs/customizations/auto-switch-multilingual-messages) guide for setup details.
</Tip>

***

## Per-Language Configuration

Each language you add gets its own independent configuration:

<Frame caption="Canvas with English as primary, Hindi and Dutch tabs, and per-language advanced settings">
  <img src="https://mintcdn.com/bolna-54a2d4fe/hfgmDYlY4OmNMCdc/images/getting-started/agent-setup/agent-prompt.png?fit=max&auto=format&n=hfgmDYlY4OmNMCdc&q=85&s=910f9725f9d8e474c4c286798c2b2a89" alt="Canvas with English marked as Primary, Hindi and Dutch language tabs, prompt editor showing Personality and Identity sections" width="1524" height="1340" data-path="images/getting-started/agent-setup/agent-prompt.png" />
</Frame>

| What                                | Where                        | Scope             |
| ----------------------------------- | ---------------------------- | ----------------- |
| **Prompt**                          | Agent Tab, language tabs     | Per language      |
| **Agent Name**                      | Agent Tab, Advanced Settings | Per language      |
| **Handoff Message**                 | Agent Tab, Advanced Settings | Per language      |
| **Language Switching Instructions** | Agent Tab                    | Shared across all |
| **Text-to-Speech**                  | Audio Tab                    | Per language      |
| **Speech-to-Text**                  | Audio Tab                    | Per language      |

Each language can use a different STT and TTS provider. For example, use **Deepgram** for English transcription and **Sarvam** for Hindi, or **ElevenLabs** for English voice and **Sarvam** for Hindi voice. Select a language tab in the [Audio Tab](/docs/agent-setup/audio-tab) to configure its providers independently.

<Info>
  Settings are independent per language. The Agent Name, Handoff Message, STT provider, and TTS provider for Hindi do not affect English.
</Info>

***

## Supported Languages

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

***

## Writing Effective Multilingual Prompts

<CardGroup cols={2}>
  <Card title="Use Native Script" icon="pen-nib">
    Write prompts in the language's native script, not phonetic English. "नमस्ते" not "Namaste".
  </Card>

  <Card title="Include Accented Characters" icon="spell-check">
    Use proper accents for European languages. "Cómo estás?" not "Como estas?"
  </Card>
</CardGroup>

<Accordion title="Examples: Correct vs Incorrect Prompts">
  **Hindi**

  * Incorrect: "Namaste! Aap kaise ho?"
  * Correct: "नमस्ते! आप कैसे हैं?"

  **Spanish**

  * Incorrect: "Hola! Como estas?"
  * Correct: "¡Hola! ¿Cómo estás?"

  **French**

  * Incorrect: "Bonjour! Comment ca va?"
  * Correct: "Bonjour ! Comment ça va ?"
</Accordion>

<Tip>
  Read the full [guide for writing prompts in non-English languages](/docs/guides/writing-prompts-in-non-english-languages) for detailed best practices.
</Tip>

***

## Multilingual Knowledge Bases

If your agent uses knowledge bases with non-English documents, enable **multilingual** support when creating the knowledge base. This supports 100+ languages, allowing your agent to retrieve information regardless of document or query language.

<Info>
  Learn more in the [Knowledge Base documentation](/docs/getting-started/knowledge-base#multilingual-knowledge-bases).
</Info>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Agent Tab" icon="file-lines" href="/docs/agent-setup/agent-tab">
    Configure per-language prompts and handoff messages
  </Card>

  <Card title="Audio Tab" icon="waveform-lines" href="/docs/agent-setup/audio-tab">
    Set up languages, voices, and transcription
  </Card>

  <Card title="Auto-Switch Languages" icon="shuffle" href="/docs/customizations/auto-switch-multilingual-messages">
    Auto-detect and switch system messages by language
  </Card>

  <Card title="Non-English Prompts Guide" icon="language" href="/docs/guides/writing-prompts-in-non-english-languages">
    Best practices for writing multilingual prompts
  </Card>
</CardGroup>
