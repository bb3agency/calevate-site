> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Configure Voice AI Agents in Bolna

> Complete guide to configuring Bolna Voice AI agents. Customize prompts, test conversations, and deploy agents for inbound and outbound calls.

## What is Agent Setup?

Agent Setup is where you configure and fine-tune your Voice AI agents. Access it from the [Bolna Platform](https://platform.bolna.ai/) after creating or selecting an agent.

<Frame caption="Agent Setup on Bolna Platform">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/agent-setup/overview-full.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=8597428834579349ef66389ebad00017" alt="Bolna Platform Agent Setup interface showing Your Agents sidebar, configuration tabs, prompts, and testing options" width="1024" height="535" data-path="images/getting-started/agent-setup/overview-full.png" />
</Frame>

***

## Your Agents Sidebar

The left sidebar shows all your agents and provides quick access to create or import agents.

<Frame caption="Your Agents Sidebar">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/agent-setup/overview-sidebar.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=5476c8544adc1b7be153032bc29a9711" alt="Agent Setup sidebar showing Import and New Agent buttons with searchable agent list" style={{ maxWidth: '50%' }} width="586" height="916" data-path="images/getting-started/agent-setup/overview-sidebar.png" />
</Frame>

| Action          | Description                                                                                |
| --------------- | ------------------------------------------------------------------------------------------ |
| **+ New Agent** | Create a new agent using Auto Build, Pre-built templates, or from scratch                  |
| **Import**      | Import an existing agent configuration using an [agent ID](/docs/agent-setup/copy-import-agent) |
| **Search**      | Quickly find agents by name                                                                |
| **Agent List**  | Click any agent to open its configuration                                                  |

<Info>
  New agents are created in **draft** status until you save them.
</Info>

***

## Agent Header

The header bar displays key information and quick actions for your selected agent.

<Frame caption="Agent Header with Status and Actions">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/agent-setup/overview-header.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=882fe81c6feac5ab5fbfe3bd514d86d4" alt="Agent header showing name, Agent ID, Share button, cost per minute, routing region, and provider status indicators" width="1024" height="181" data-path="images/getting-started/agent-setup/overview-header.png" />
</Frame>

| Element             | Description                                              |
| ------------------- | -------------------------------------------------------- |
| **Agent Name**      | Your agent's display name                                |
| **Agent ID**        | Copy for API integrations                                |
| **Share**           | Generate a shareable link for team collaboration         |
| **Cost per min**    | Estimated cost breakdown per minute                      |
| **Routing**         | Active routing region (e.g., India routing)              |
| **Provider Status** | Status indicators for Transcriber, LLM, Voice, Telephony |

<CardGroup cols={2}>
  <Card title="Get call from agent" icon="phone">
    Receive a test call on your phone number
  </Card>

  <Card title="Set inbound agent" icon="phone-arrow-down">
    Configure this agent for inbound calls
  </Card>
</CardGroup>

***

## Configuration Tabs

Configure every aspect of your agent using the **8 specialized tabs**.

<Frame caption="Agent Configuration Tabs">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/agent-setup/overview-tabs.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=9867f02b3b72eee91565b3d7a229a571" alt="Eight configuration tabs: Agent, LLM, Audio, Engine, Call, Tools, Analytics, Inbound" width="1024" height="95" data-path="images/getting-started/agent-setup/overview-tabs.png" />
</Frame>

<CardGroup cols={4}>
  <Card title="Agent" icon="file-lines" href="/docs/agent-setup/agent-tab">
    Prompts & welcome message
  </Card>

  <Card title="LLM" icon="brain" href="/docs/agent-setup/llm-tab">
    Model & knowledge base
  </Card>

  <Card title="Audio" icon="language" href="/docs/agent-setup/audio-tab">
    Voice & transcription
  </Card>

  <Card title="Engine" icon="gear" href="/docs/agent-setup/engine-tab">
    Latency & interruptions
  </Card>

  <Card title="Call" icon="phone" href="/docs/agent-setup/call-tab">
    Telephony & voicemail
  </Card>

  <Card title="Tools" icon="function" href="/docs/agent-setup/tools-tab">
    Functions & APIs
  </Card>

  <Card title="Extractions" icon="chart-line" href="/docs/agent-setup/analytics-tab">
    Webhooks & extraction
  </Card>

  <Card title="Inbound" icon="phone-arrow-down" href="/docs/agent-setup/inbound-tab">
    Caller matching
  </Card>
</CardGroup>

***

## Testing & Saving

Test your agent before deploying and save your changes.

<Frame caption="Testing and Save Actions">
  <img src="https://mintcdn.com/bolna-54a2d4fe/nkJ9nAjMGNa34kLN/images/getting-started/agent-setup/overview-actions.png?fit=max&auto=format&n=nkJ9nAjMGNa34kLN&q=85&s=0a2495bb7b877306d5093484989ed718" alt="Action panel showing See all call logs, Save agent button, Chat with agent, and Test via browser options" style={{ maxWidth: '50%' }} width="474" height="758" data-path="images/getting-started/agent-setup/overview-actions.png" />
</Frame>

### Testing Options

| Method                  | Description                           | Best For                             |
| ----------------------- | ------------------------------------- | ------------------------------------ |
| **Chat with agent**     | Text-based conversation testing       | Quick prompt iteration and debugging |
| **Get call from agent** | Receive a test call on your phone     | Real-world voice experience          |
| **Test via browser**    | Make calls directly from your browser | Testing without using phone minutes  |

<Tip>
  **Pro tip:** Use "Chat with agent" for quick iterations, then validate with a real phone call before deploying!
</Tip>

### Save & Manage

| Action                | Description                                                                 |
| --------------------- | --------------------------------------------------------------------------- |
| **Save agent**        | Save your configuration — changes only take effect after saving!            |
| **See all call logs** | View [call history](/docs/agent-setup/call-history), recordings, and transcripts |
| **Delete**            | Remove the agent (use with caution)                                         |

<Warning>
  **Remember to save!** Your changes won't apply until you click **Save agent**.
</Warning>

***

## Quick Links

<CardGroup cols={2}>
  <Card title="Create an Agent" icon="plus" href="/docs/getting-started/agent-creation">
    Step-by-step guide to creating your first agent
  </Card>

  <Card title="Import an Agent" icon="download" href="/docs/agent-setup/copy-import-agent">
    Import existing agent configurations
  </Card>

  <Card title="Buy Phone Numbers" icon="hashtag" href="/docs/guides/inbound/buying-phone-numbers">
    Purchase phone numbers for inbound calls
  </Card>

  <Card title="Call History" icon="clock-rotate-left" href="/docs/agent-setup/call-history">
    View call logs, recordings, and transcripts
  </Card>
</CardGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Agent Tab" icon="file-lines" href="/docs/agent-setup/agent-tab">
    Configure prompts and welcome message
  </Card>

  <Card title="LLM Tab" icon="brain" href="/docs/agent-setup/llm-tab">
    Choose your language model and knowledge base
  </Card>

  <Card title="Audio Tab" icon="language" href="/docs/agent-setup/audio-tab">
    Set up voice and transcription
  </Card>

  <Card title="Knowledge Base" icon="book" href="/docs/getting-started/knowledge-base">
    Upload documents for context-aware responses
  </Card>
</CardGroup>
