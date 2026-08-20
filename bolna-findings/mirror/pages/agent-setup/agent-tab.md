> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Configure Multilingual Agent Prompts and Hangup Settings

> Set up your Bolna Voice AI agent's welcome message, write per-language prompts with dynamic variables, configure language switching, and define intelligent call hangup conditions.

The Agent Tab controls your agent's welcome message, prompts, and conversation behavior. Add multiple languages, set a primary, and write a dedicated prompt for each.

<Frame caption="Agent Tab with welcome message, multilingual prompt editor, language switching instructions, and hangup configuration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/yAVu8MhlCtrBCxAy/images/getting-started/agent-setup/agent-tab-overview.png?fit=max&auto=format&n=yAVu8MhlCtrBCxAy&q=85&s=6836e405f24cd4202bade0f05556d82e" alt="Agent Tab showing welcome message, language tabs with English as primary alongside Dutch and Hindi, prompt editor with token count, language switching instructions, advanced settings, and prompt variables for testing" width="1938" height="1334" data-path="images/getting-started/agent-setup/agent-tab-overview.png" />
</Frame>

***

## Agent Welcome Message

The first thing callers hear when they connect.

<Frame caption="Welcome message field with variable syntax hint">
  <img src="https://mintcdn.com/bolna-54a2d4fe/hfgmDYlY4OmNMCdc/images/getting-started/agent-setup/agent-welcome-message.png?fit=max&auto=format&n=hfgmDYlY4OmNMCdc&q=85&s=10ec54113501899240ca3fdc4c39775c" alt="Agent Welcome Message input with sample greeting and hint showing variable_name syntax in curly braces" width="1502" height="214" data-path="images/getting-started/agent-setup/agent-welcome-message.png" />
</Frame>

<CardGroup cols={2}>
  <Card title="Keep It Short" icon="message">
    Brief greetings work best. Long announcements feel robotic.
  </Card>

  <Card title="Use Variables" icon="brackets-curly">
    Personalize with `{variable_name}`, e.g. `{customer_name}`.
  </Card>
</CardGroup>

***

## Canvas

Each language gets its own prompt. Select a language tab and write the prompt for that language. The agent activates the matching prompt when speaking in that language during a call.

<Frame caption="Prompt editor with English as primary, Hindi and Dutch as secondary tabs, personality prompt for Vidya, token counter, and variable syntax hints">
  <img src="https://mintcdn.com/bolna-54a2d4fe/hfgmDYlY4OmNMCdc/images/getting-started/agent-setup/agent-prompt.png?fit=max&auto=format&n=hfgmDYlY4OmNMCdc&q=85&s=910f9725f9d8e474c4c286798c2b2a89" alt="Canvas with English marked as Primary, Hindi and Dutch language tabs, prompt editor showing Personality and Identity sections, token counter at 14111, and hint text for variable and module syntax" width="1524" height="1340" data-path="images/getting-started/agent-setup/agent-prompt.png" />
</Frame>

### Managing Languages

Languages are **synced** between the Agent Tab and [Audio Tab](/docs/agent-setup/audio-tab). Adding or removing a language in either tab updates both. Each language can also have its own [STT and TTS providers](/docs/agent-setup/audio-tab) configured in the Audio Tab.

<Steps>
  <Step title="Add a Language">
    Click **+ Add Language** to create a new language tab.
  </Step>

  <Step title="Set the Primary">
    Click the **crown icon** next to any language to make it primary. The primary language is what the agent starts every conversation in, marked with **(Primary)** in the tab.
  </Step>

  <Step title="Write Per-Language Prompts">
    Select each language tab and write its prompt.
  </Step>

  <Step title="Remove a Language">
    Click the **x** on a tab to remove it from both tabs.
  </Step>
</Steps>

<Frame caption="Crown icon tooltip to set a language as primary">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uyz7-RHjowDG1vOL/images/getting-started/agent-setup/audio-language-primary.png?fit=max&auto=format&n=uyz7-RHjowDG1vOL&q=85&s=3de6a01c0665cd620274718c77e3d8a5" alt="Tooltip showing Make Hindi primary when clicking the crown icon next to Hindi" width="670" height="268" data-path="images/getting-started/agent-setup/audio-language-primary.png" />
</Frame>

### Prompt Structure

<Accordion title="Recommended Prompt Sections">
  | Section          | Purpose         | Example                                     |
  | ---------------- | --------------- | ------------------------------------------- |
  | **Personality**  | Tone and feel   | "warm, perceptive, and results-driven"      |
  | **Context**      | Role background | "You are calling on behalf of Acme Corp..." |
  | **Instructions** | Tasks and flow  | "Ask for their order number first..."       |
  | **Guardrails**   | Restrictions    | "Never discuss competitor products..."      |
</Accordion>

The editor shows a **token count** in the bottom-right to help you stay within LLM limits.

### Variable Syntax

| Syntax            | Purpose                                               | How to use                                                                                                     |
| ----------------- | ----------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `{variable_name}` | Insert or define variables                            | Type `{` to open the variable picker. Select an existing variable or type a new name to create one.            |
| `@`               | Insert prompt modules, custom functions, or variables | Type `@` to browse and select existing modules, functions, or variables. You cannot create new items with `@`. |

<CardGroup cols={2}>
  <Card title="Variables with { }" icon="brackets-curly">
    Select existing variables or **create new ones** by typing a name. Values are passed via API or CSV at call time.
  </Card>

  <Card title="Modules and Functions with @" icon="code">
    Select existing [prompt modules](/docs/prompting-guide#prompt-modules), [custom functions](/docs/tool-calling/custom-function-calls), or variables. Cannot create new items.
  </Card>
</CardGroup>

### Browse Modules

Click the **Browse Modules** button in the top-right of the prompt section to open the full modules library. Browse by category (Collection, Optional, Flow, Sector, Universal), preview what each module does, and insert it directly into your prompt. See the [Prompting Guide](/docs/prompting-guide#prompt-modules) for the full list of available modules.

***

## Language Switching Instructions

A **single shared field** that applies to all languages. Describes when the agent should switch languages mid-call.

| What to include        | Example                                               |
| ---------------------- | ----------------------------------------------------- |
| **Trigger conditions** | "Switch to Hindi if the user speaks in Hindi"         |
| **Fallback behavior**  | "Fall back to English if the language is unsupported" |
| **Default rule**       | "Respond in the language the user is currently using" |

<Info>
  Write these once. They apply across all languages automatically.
</Info>

***

## Per-Language Advanced Settings

Each language tab has its own expandable **Advanced Settings** section.

<Frame caption="Advanced Settings for English showing Agent Name, Handoff Message with variables, Language Switching Instructions, and prompt variable testing">
  <img src="https://mintcdn.com/bolna-54a2d4fe/hfgmDYlY4OmNMCdc/images/getting-started/agent-setup/agent-advanced-settings.png?fit=max&auto=format&n=hfgmDYlY4OmNMCdc&q=85&s=418366552d00a6fc0e933a937c36de14" alt="Language Switching Instructions field, Advanced Settings for English expanded with Agent Name placeholder AI Assistant and Handoff Message reading Let me connect you with agent_name who speaks language" width="1952" height="724" data-path="images/getting-started/agent-setup/agent-advanced-settings.png" />
</Frame>

| Field               | Description                                                                                                         |
| ------------------- | ------------------------------------------------------------------------------------------------------------------- |
| **Agent Name**      | Name the agent uses to identify itself in this language                                                             |
| **Handoff Message** | Message spoken when switching **away from** this language. Supports variables like `{agent_name}` and `{language}`. |

### Prompt Variables for Testing

When you use `{variable_name}` in your prompt, those variables **automatically appear** as input fields in the testing section. Fill in test values to preview how the prompt behaves before going live.

<Frame caption="Prompt variables auto-detected from the prompt, shown as editable input fields alongside the timezone selector">
  <img src="https://mintcdn.com/bolna-54a2d4fe/hfgmDYlY4OmNMCdc/images/getting-started/agent-setup/agent-prompt-variables.png?fit=max&auto=format&n=hfgmDYlY4OmNMCdc&q=85&s=de2f36e67706b5485cbcd986fff72410" alt="Prompt variables for testing section showing Asia Kolkata UTC plus 05 30 timezone selector and auto-detected variable fields for referrer_name, referee_name, city, and user_number" width="1952" height="292" data-path="images/getting-started/agent-setup/agent-prompt-variables.png" />
</Frame>

The **Timezone** selector (e.g., `Asia/Kolkata UTC+05:30`) is a separate field that sets the timezone context for test calls.

<CardGroup cols={2}>
  <Card title="Per-Language Scope" icon="language">
    Settings are independent. Hindi's Agent Name and Handoff Message do not affect English.
  </Card>

  <Card title="Natural Handoffs" icon="globe">
    Always set a Handoff Message per language. Without it, transitions feel abrupt.
  </Card>
</CardGroup>

***

## Hangup Using Prompt

Let your agent decide when to end calls based on conversation context instead of silence detection or timeouts.

<Frame caption="Hangup toggle enabled with multilingual closing conditions in English and Hindi">
  <img src="https://mintcdn.com/bolna-54a2d4fe/hfgmDYlY4OmNMCdc/images/getting-started/agent-setup/agent-hangup-prompt.png?fit=max&auto=format&n=hfgmDYlY4OmNMCdc&q=85&s=fbe8a345078b217c3908afe1c244a3c1" alt="Hangup using a prompt toggle enabled with conversation completion conditions and closing lines in English and Hindi" width="1500" height="410" data-path="images/getting-started/agent-setup/agent-hangup-prompt.png" />
</Frame>

<Steps>
  <Step title="Enable the Toggle">
    Turn on **Hangup using a prompt**.
  </Step>

  <Step title="Define Completion Conditions">
    Write conditions for when a conversation is complete. For multilingual agents, include closing lines in each language.
  </Step>
</Steps>

<Accordion title="Example: Multilingual Hangup Prompt">
  ```
  A conversation is considered complete if any of the following conditions are met:
  User is not interested:
  The assistant has said the following closing line:
    Conversation Closing (English): "That is sad to hear. But no worries if you would ever want to learn more give me a cool."
    Conversation Closing (Hindi): "ये सुनकर अफ़सोस हुआ। लेकिन कोई बात नहीं, अगर आप कभी और जानना चाहें तो मुझे call कर लें।"
  The user has responded after that with any of the following phrases: "goodbye", "bye", "thank you", "thanks", "ok", "okay", or similar.
  The last message in the transcript must be from the user.
  ```
</Accordion>

<Warning>
  Without this, calls end only on silence detection or timeouts.
</Warning>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="LLM Tab" icon="brain" href="/docs/agent-setup/llm-tab">
    Configure the language model and knowledge bases
  </Card>

  <Card title="Audio Tab" icon="waveform-lines" href="/docs/agent-setup/audio-tab">
    Set up voice, transcription, and languages
  </Card>

  <Card title="Prompting Guide" icon="lightbulb" href="/docs/guides/prompting/prompting-guide">
    Best practices for writing prompts
  </Card>

  <Card title="Using Variables" icon="code" href="/docs/guides/prompting/using-context">
    Dynamic personalization with context
  </Card>
</CardGroup>
