> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Agent Studio

> Go from a brief description to a production-grade, call-ready voice AI agent in 5 to 8 minutes — no prompt writing required.

## What is Agent Studio?

Agent Studio turns a short description of your use case into a production-grade, call-ready voice AI agent — in 5 to 8 minutes. No prompt engineering, no guesswork. Just fill in a form and get a fully structured agent prompt, auto-selected voice, and a published version ready to make calls.

***

## How to Use It

Click **+ New Agent** in the sidebar and choose **Auto Build Agent** to open Agent Studio.

The form has **3 steps**:

<Steps>
  <Step title="Step 1 — Identity & Goal">
    Tell the builder who the agent is and what the call is for.
  </Step>

  <Step title="Step 2 — Conversation">
    Define the welcome message, guardrails, and conversation flow.
  </Step>

  <Step title="Step 3 — Closing">
    Set the final line the agent says before hanging up.
  </Step>
</Steps>

Once submitted, your agent is production-ready in **5 to 8 minutes**. You can navigate away — the agent will appear in your dashboard when ready.

***

## Step 1 — Identity & Goal

There are two ways to provide context — and the more context you give, the better your agent will be.

<CardGroup cols={2}>
  <Card title="Upload a document" icon="file-arrow-up">
    Upload a PDF, DOCX, TXT, or CSV — a call script, SOP, FAQ sheet, or any business document. The builder reads it and pre-fills the fields automatically.
  </Card>

  <Card title="Fill in manually" icon="pen-to-square">
    Fill in the fields yourself. Be as detailed as possible — specific goals, flows, and guardrails produce a far better agent than vague inputs.
  </Card>
</CardGroup>

<Info>
  You can also do both — upload a document **and** add extra details in the fields. More context always means a better agent.
</Info>

### Fields

| Field                              | Required | What to enter                                                                                           |
| ---------------------------------- | -------- | ------------------------------------------------------------------------------------------------------- |
| **Agent Name**                     | ✅        | The name the agent introduces itself with. E.g. *Saanvi*                                                |
| **Industry**                       | ✅        | Select from the list or choose "Other" to type your own                                                 |
| **Agent Designation**              | ✅        | The agent's role. E.g. *Recruitment Specialist*                                                         |
| **Company Name**                   | ✅        | The organisation the agent represents                                                                   |
| **Company Description**            | Optional | A short description of the company                                                                      |
| **Languages**                      | ✅        | One or more languages the agent should speak. Set one as Primary                                        |
| **Gender**                         | ✅        | Male or Female — used to auto-select the best matching voice                                            |
| **Tone**                           | ✅        | Pick one or more: *Warm & professional, Formal, Casual, Assertive, Empathetic*                          |
| **What Should This Call Achieve?** | ✅        | The call goal in 1–2 sentences. E.g. *Screen candidates and book a technical interview if they qualify* |

<Tip>
  Blended tones work well — e.g. **Warm & professional + Empathetic** for support calls, **Warm + Assertive** for collections. Avoid picking all of them.
</Tip>

***

## Step 2 — Conversation

| Field                     | Required | What to enter                                                                                                          |
| ------------------------- | -------- | ---------------------------------------------------------------------------------------------------------------------- |
| **Agent Welcome Message** | ✅        | The first thing the agent says when the call connects. Use `{variable_name}` for dynamic values                        |
| **Guardrails**            | ✅        | Hard rules the agent must follow — topics to avoid, things it must never say, when to hand off to a human              |
| **Conversation Flow**     | ✅        | The steps the agent follows in order. Numbered steps work best. E.g. *1. Greet → 2. Ask about experience → 3. Qualify* |

<Tip>
  Click **"See default guardrails"** on the Guardrails field for a pre-filled set of sensible defaults you can copy and customise.
</Tip>

***

## Step 3 — Closing

| Field             | Required | What to enter                                                                                                |
| ----------------- | -------- | ------------------------------------------------------------------------------------------------------------ |
| **Closing Line**  | ✅        | The last message the agent says before disconnecting. E.g. *Thanks for your time. We'll follow up by email.* |
| **Hangup Prompt** | Optional | Toggle on to give the agent a custom instruction for when to end the call — useful for complex call flows    |

***

## After Generation

Once the prompt is ready, it is automatically saved to your agent. You can:

* **Review and edit** the prompt in the [Agent Tab](/docs/agent-setup/agent-tab)
* **Adjust the voice** in the [Audio Tab](/docs/agent-setup/audio-tab) — a voice is auto-selected based on your language and gender settings
* **Test the agent** via browser or by receiving a test call

***

## Frequently Asked Questions

<AccordionGroup>
  <Accordion title="How long does generation take?">
    **5 to 8 minutes**. You can navigate away; the agent status updates automatically when it's done.
  </Accordion>

  <Accordion title="Can I edit the generated prompt afterwards?">
    Yes. The generated prompt is fully editable in the Agent tab. Agent Studio gives you a strong starting point you can fine-tune from there.
  </Accordion>

  <Accordion title="What file types can I upload?">
    PDF, DOCX, TXT, and CSV files are supported. Upload call scripts, SOPs, FAQ sheets, or any business document relevant to the agent's role.
  </Accordion>
</AccordionGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Agent Tab" icon="file-lines" href="/docs/agent-setup/agent-tab">
    Review and edit the generated prompt
  </Card>

  <Card title="Audio Tab" icon="language" href="/docs/agent-setup/audio-tab">
    Adjust the auto-selected voice if needed
  </Card>

  <Card title="Make a Call" icon="phone" href="/docs/guides/outbound/making-outgoing-calls">
    Start making calls with your new agent
  </Card>

  <Card title="Tips & Tricks" icon="lightbulb" href="/docs/tips-and-tricks">
    Best practices for prompting voice agents
  </Card>
</CardGroup>
