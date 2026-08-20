> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Prompting Guide and Best Practices for Bolna Voice AI

> Write effective prompts for Bolna Voice AI agents. Use variables, prompt modules, and best practices to build high-performing conversational agents.

This guide covers how to write effective prompts, use variables and prompt modules, and optimize your agent for performance.

***

## Variables

Variables let you inject dynamic data into your prompts. There are two types:

<CardGroup cols={2}>
  <Card title="User Variables" icon="brackets-curly">
    Defined by you. Passed via the API at call time or from CSV rows during [batch calling](/docs/guides/outbound/batch-calling). Examples: `{customer_name}`, `{order_id}`, `{city}`.
  </Card>

  <Card title="System Variables" icon="database">
    Predefined by Bolna. Available automatically in every call. Examples: `agent_id`, `call_sid`.
  </Card>
</CardGroup>

### Using Variables in the Prompt Editor

Type `{` in the prompt editor to open the variable dropdown. It shows both **User Variables** and **System Variables**.

<Frame caption="Variable dropdown showing User Variables (referrer_name, city, user_number) and System Variables (agent_id, call_sid)">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Ds5VD5sKw1pBcsQj/images/tips/variable-dropdown.png?fit=max&auto=format&n=Ds5VD5sKw1pBcsQj&q=85&s=bbe16f7aacd1e0c8a552f5d222c54983" alt="Canvas with curly brace dropdown open showing User Variables section with referrer_name, referee_name, city, user_number and System Variables section with agent_id, call_sid" width="1488" height="1162" data-path="images/tips/variable-dropdown.png" />
</Frame>

With `{`, you can:

* **Select** an existing user or system variable
* **Define a new variable** by typing a name that does not exist yet (e.g., `{appointment_date}`)

### Testing Variables

Any variable you define with `{variable_name}` in your prompt **automatically appears** as an editable input field in the testing section below the prompt. Fill in test values to preview how the prompt behaves before going live.

<Frame caption="Prompt variables auto-detected from the prompt, shown as editable input fields alongside the timezone selector">
  <img src="https://mintcdn.com/bolna-54a2d4fe/hfgmDYlY4OmNMCdc/images/getting-started/agent-setup/agent-prompt-variables.png?fit=max&auto=format&n=hfgmDYlY4OmNMCdc&q=85&s=de2f36e67706b5485cbcd986fff72410" alt="Prompt variables for testing section showing Asia Kolkata UTC plus 05 30 timezone selector and auto-detected variable fields for referrer_name, referee_name, city, and user_number" width="1952" height="292" data-path="images/getting-started/agent-setup/agent-prompt-variables.png" />
</Frame>

<Tip>
  User variables are passed via the API at call time or from CSV rows during [batch calling](/docs/guides/outbound/batch-calling). System variables like `agent_id` and `call_sid` are filled automatically by Bolna.
</Tip>

***

## Using @ to Insert Modules, Functions, and Variables

Type `@` in the prompt editor to open a dropdown that lets you select and insert:

* **Prompt Modules** - pre-built prompt blocks for common tasks
* **Custom Functions** - functions defined in the [Tools Tab](/docs/agent-setup/tools-tab)
* **Variables** - existing variables already used in your prompt

<Frame caption="Typing @ shows a list of available prompt modules like Email Collection, Number Collection, Persuasion, and Variables Reference">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Ds5VD5sKw1pBcsQj/images/tips/prompt-modules-dropdown.png?fit=max&auto=format&n=Ds5VD5sKw1pBcsQj&q=85&s=010bf1c65f121886fe70d0649ab35c71" alt="Canvas editor with at-sign dropdown open showing Prompt Modules list including Email Collection, Number Collection, Name Collection, Persuasion, and Variables Reference" width="1494" height="1146" data-path="images/tips/prompt-modules-dropdown.png" />
</Frame>

<Note>
  With `@`, you can only **select** existing items. You cannot create new variables, functions, or modules. To create a new variable, use `{variable_name}` instead.
</Note>

## Prompt Modules

Prompt modules are pre-built prompt blocks that handle common tasks like email collection, persuasion, objection handling, and more. Insert a module and customize it instead of writing from scratch.

### Browse Modules

Click the **Browse Modules** button in the top-right of the Canvas section to open the full modules library. Browse by category, read what each module does, and insert it into your prompt with one click.

<Frame caption="Browse Modules panel showing module categories (Collection, Optional, Flow) with the Email Collection module details and Insert into editor button">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Ds5VD5sKw1pBcsQj/images/tips/browse-modules.png?fit=max&auto=format&n=Ds5VD5sKw1pBcsQj&q=85&s=e913bfa238a24ddccbf4928c3405236b" alt="Browse Modules panel with left sidebar showing categories Collection, Optional, and Flow, and right panel showing Email Collection module with description, full prompt text, and Insert into editor button" width="2678" height="1650" data-path="images/tips/browse-modules.png" />
</Frame>

Each module shows:

* **What Prompt Does** - a short description of the module's purpose
* **Prompt** - the full prompt text that will be inserted
* **Insert into editor** - click to add it to your current prompt

<Frame caption="Module detail view for Interview Reminder showing categories, prompt description, and full prompt content">
  <img src="https://mintcdn.com/bolna-54a2d4fe/Ds5VD5sKw1pBcsQj/images/tips/module-detail.png?fit=max&auto=format&n=Ds5VD5sKw1pBcsQj&q=85&s=f85f18eee5e2eb4700ac8d67befaa8c1" alt="Modules panel showing Interview Reminder module with categories Collection, Optional, Flow, Sector, Universal on the left, and prompt content with call flow instructions on the right" width="1084" height="1652" data-path="images/tips/module-detail.png" />
</Frame>

### Available Module Categories

| Category       | What it contains                                                                                                                                                                                                                                 |
| -------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **Collection** | Email Collection, Number Collection, Name Collection                                                                                                                                                                                             |
| **Optional**   | Persuasion, Variables Reference, Pricing and Plans, Objection Handling, Knowledge Base, Hang Up Prompt, Handover and Escalation, FAQ Block, Extraction Schema, Eligibility Criteria, Compliance Healthcare, Compliance Finance, Closing Branches |
| **Flow**       | Outbound Survey, Outbound Lead, Inbound Verification                                                                                                                                                                                             |
| **Sector**     | Industry-specific modules                                                                                                                                                                                                                        |
| **Universal**  | General-purpose modules that work across use cases                                                                                                                                                                                               |

<Tip>
  Modules are a great starting point. Insert one, then customize the prompt text to fit your specific use case and tone.
</Tip>

***

## Writing Effective Prompts

<CardGroup cols={2}>
  <Card title="Start Short" icon="file-lines">
    Begin with a clear, concise prompt. Add details incrementally as you test and refine.
  </Card>

  <Card title="Limit Response Length" icon="message">
    Start with: "You will not speak more than 2 sentences at a time." This keeps responses fast and natural.
  </Card>
</CardGroup>

<Accordion title="Recommended Prompt Structure">
  | Section          | Purpose         | Example                                     |
  | ---------------- | --------------- | ------------------------------------------- |
  | **Personality**  | Tone and feel   | "warm, perceptive, and results-driven"      |
  | **Context**      | Role background | "You are calling on behalf of Acme Corp..." |
  | **Instructions** | Tasks and flow  | "Ask for their order number first..."       |
  | **Guardrails**   | Restrictions    | "Never discuss competitor products..."      |
</Accordion>

<Warning>
  Prompt engineering takes iteration. If your agent does not follow instructions as expected, refine the prompt step by step rather than rewriting everything at once.
</Warning>

***

## Choosing the Right Agent Type

<CardGroup cols={2}>
  <Card title="Free Flowing" icon="comments">
    Natural conversations from a plain-English prompt. Creative and flexible, but requires fine-tuning and costs more.
  </Card>

  <Card title="IVR" icon="list-ol">
    Full control over exact sentences. Cheaper with no hallucination risk, but conversations are limited to the defined tree.
  </Card>
</CardGroup>

|                        | Free Flowing   | IVR                       |
| ---------------------- | -------------- | ------------------------- |
| **Setup**              | Write a prompt | Build a conversation tree |
| **Flexibility**        | High           | Low                       |
| **Hallucination risk** | Possible       | None                      |
| **Cost**               | Higher         | Lower                     |

<Tip>
  Start with an [agent template](/docs/agents-library) and customize it. Templates are built to run on default settings.
</Tip>

***

## Optimizing for Performance

For low-latency, high-quality conversations:

| Component       | Recommended                  |
| --------------- | ---------------------------- |
| **LLM**         | Azure / gpt-4.1-mini cluster |
| **Voice**       | ElevenLabs                   |
| **Transcriber** | Deepgram                     |
| **Telephony**   | Plivo                        |

<CardGroup cols={2}>
  <Card title="Match Voice to Language" icon="microphone">
    Make sure the voice you choose supports the language you have configured.
  </Card>

  <Card title="Test Before Deploying" icon="flask">
    Use the [Playground](/docs/agent-setup/agent-tab) to test your agent thoroughly before making live calls. Telephone calling burns credits quickly.
  </Card>
</CardGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Agent Tab" icon="file-lines" href="/docs/agent-setup/agent-tab">
    Configure prompts, languages, and advanced settings
  </Card>

  <Card title="Agent Templates" icon="book" href="/docs/agents-library">
    Start from a pre-built template
  </Card>

  <Card title="Using Variables" icon="brackets-curly" href="/docs/guides/prompting/using-context">
    Pass dynamic data into calls with context variables
  </Card>

  <Card title="Non-English Prompts" icon="language" href="/docs/guides/writing-prompts-in-non-english-languages">
    Writing prompts in native scripts
  </Card>
</CardGroup>
