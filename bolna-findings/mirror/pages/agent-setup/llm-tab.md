> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Choose and Configure LLM Models for Voice AI

> Select and configure the language model for your Bolna Voice AI agent. Choose from OpenAI, Azure, Anthropic, and connect knowledge bases.

## What is the LLM Tab?

The LLM Tab is where you select and configure the intelligence behind your voice AI agent. Choose your language model provider, adjust response parameters, and connect knowledge bases for enhanced conversations.

<Frame caption="LLM Tab on Bolna Playground">
  <img src="https://mintcdn.com/bolna-54a2d4fe/xje3IUNKzO7g_x01/images/getting-started/agent-setup/llm-tab.png?fit=max&auto=format&n=xje3IUNKzO7g_x01&q=85&s=fc538f5b437afe484caf794e5d5ffeea" alt="LLM Tab showing model selection, parameters, and knowledge base options" width="1436" height="894" data-path="images/getting-started/agent-setup/llm-tab.png" />
</Frame>

***

## Configuration Options

### Choose LLM Model

Select your AI provider and model for conversation intelligence.

<Frame caption="LLM Model Selection">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/agent-setup/llm-model.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=5bf9a8c4fcc6554923efe1df72af24eb" alt="Choose LLM model with Azure provider and gpt-4.1-mini cluster selected" width="1024" height="143" data-path="images/getting-started/agent-setup/llm-model.png" />
</Frame>

<CardGroup cols={2}>
  <Card title="Provider Selection" icon="plug">
    Choose from Azure, OpenAI, Anthropic, Groq, and more
  </Card>

  <Card title="Model Selection" icon="microchip">
    Pick the specific model (e.g., `gpt-4.1-mini cluster`)
  </Card>
</CardGroup>

<Tip>
  Connect your own provider keys in [Providers](/docs/getting-started/providers) to reduce costs and access more models.
</Tip>

***

### Model Parameters

Fine-tune how your agent generates responses.

<Frame caption="Model Parameters Configuration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/agent-setup/llm-parameters.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=558d3ac6db8db9fb521410c684f404f4" alt="Model Parameters section showing Tokens and Temperature sliders with Knowledge Base dropdown" width="1024" height="346" data-path="images/getting-started/agent-setup/llm-parameters.png" />
</Frame>

| Parameter            | Description                                                                   | Recommended                        |
| -------------------- | ----------------------------------------------------------------------------- | ---------------------------------- |
| **Tokens Generated** | Max tokens per LLM output                                                     | 300-500 for concise responses      |
| **Temperature**      | Controls creativity/randomness                                                | 0.3-0.5 for balanced responses     |
| **Reasoning effort** | How much the model reasons before answering. Shown for models that support it | Lowest available setting for voice |

<Warning>
  **Keep temperature low** (0.3-0.5) if you want consistent, controlled responses. Higher temperature increases creativity but may cause deviation from your prompt instructions.

  GPT-5 models are the exception: they accept only `1`, so the temperature control has no effect on them. Constrain those agents through the prompt instead.
</Warning>

<Note>
  On GPT-5 models, reasoning tokens are drawn from the same budget as **Tokens Generated**, so raise the cap whenever you raise reasoning effort. The effort control lists only the values the selected model accepts, and the options change when you switch models. See [OpenAI](/docs/providers/llm-model/openai#reasoning-effort) for the per-model values.
</Note>

***

### Add Knowledge Base

Connect your knowledge bases to give your agent accurate, contextual information.

<Frame caption="Knowledge Base Multi-Select">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uH9lQxF0tYMrhiL9/images/getting-started/agent-setup/llm-knowledge-base.png?fit=max&auto=format&n=uH9lQxF0tYMrhiL9&q=85&s=c8489689cf946ce1dcaf9101ac88fe21" alt="Knowledge base dropdown showing connected URLs and PDFs with Add new knowledgebase option" width="1024" height="583" data-path="images/getting-started/agent-setup/llm-knowledge-base.png" />
</Frame>

<Steps>
  <Step title="Click the Dropdown">
    Open the **"Select knowledge bases"** multi-select dropdown.
  </Step>

  <Step title="Select Knowledge Bases">
    Check one or more knowledge bases (PDFs, URLs) to connect.
  </Step>

  <Step title="Create New (Optional)">
    Click **"Add new knowledgebase"** to create and upload new content.
  </Step>
</Steps>

<Info>
  Knowledge bases enable your agent to answer questions with accurate, up-to-date information from your documents and URLs. Connect multiple knowledge bases for comprehensive coverage.
</Info>

<Tip>
  Create knowledge bases in the [Knowledge Base](/docs/getting-started/knowledge-base) section by uploading PDFs or adding URLs.
</Tip>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Knowledge Base" icon="book" href="/docs/getting-started/knowledge-base">
    Create and manage knowledge bases
  </Card>

  <Card title="Agent Tab" icon="file-lines" href="/docs/agent-setup/agent-tab">
    Configure prompts and welcome message
  </Card>

  <Card title="Audio Tab" icon="language" href="/docs/agent-setup/audio-tab">
    Set up voice, transcription, and languages
  </Card>

  <Card title="LLM Providers" icon="plug" href="/docs/getting-started/providers">
    Connect your own LLM provider
  </Card>
</CardGroup>
