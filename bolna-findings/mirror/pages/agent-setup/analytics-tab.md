> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Set Up Webhooks and Post-Call Extractions

> Configure webhooks, call summarization, and data extraction for Bolna Voice AI. Push data to your CRM from every call.

## What is the Extractions Tab?

The Extractions Tab is where you configure webhooks for real-time data and post-call processing tasks. Automatically summarize conversations, extract structured data, and push execution data to your systems.

<Frame caption="Extractions Tab on Bolna Playground">
  <img src="https://mintcdn.com/bolna-54a2d4fe/uerR6qR-mPhGkJD9/images/extractions/extractions-tab.png?fit=max&auto=format&n=uerR6qR-mPhGkJD9&q=85&s=c7994cf421e3f434442bbc247a977815" alt="Extractions Tab showing webhook configuration and post-call tasks" width="1896" height="1036" data-path="images/extractions/extractions-tab.png" />
</Frame>

***

## Configuration Options

### Push Execution Data to Webhook

<Warning>
  **Don't miss real-time updates!** Configure a webhook to receive all execution data as calls happen — essential for CRM integrations and live dashboards.
</Warning>

Enter your webhook URL to automatically receive all execution data for this agent.

<Tip>
  Click **[See all events](/docs/guides/post-call/polling-call-status-webhooks)** to view the complete list of webhook event types you can receive.
</Tip>

***

### Post Call Tasks

Choose tasks to execute after the agent conversation is complete.

<Frame caption="Post Call Tasks Configuration">
  <img src="https://mintcdn.com/bolna-54a2d4fe/67-XP-1exGIsTFDr/images/extractions/new-extraction.png?fit=max&auto=format&n=67-XP-1exGIsTFDr&q=85&s=f6c4cb4d1a558257fa98404b0ed978f6" alt="Post Call Tasks showing extraction configuration form" width="1420" height="1020" data-path="images/extractions/new-extraction.png" />
</Frame>

<Tabs>
  <Tab title="Summarization">
    <Info>
      Automatically generate a summary of every conversation. Great for quick review and logging.
    </Info>

    Toggle on to enable automatic conversation summarization.
  </Tab>

  <Tab title="Extractions">
    Create custom extraction templates organized by categories to automatically capture structured data from call transcripts.

    <Frame caption="Extractions section in Extractions Tab">
      <img src="https://mintcdn.com/bolna-54a2d4fe/67-XP-1exGIsTFDr/images/extractions/analytics-tab-extractions.png?fit=max&auto=format&n=67-XP-1exGIsTFDr&q=85&s=33e5267371e44f1aaa746f1c859de8ca" alt="Extractions interface showing categories and extraction templates" width="1498" height="1140" data-path="images/extractions/analytics-tab-extractions.png" />
    </Frame>

    **Extractions** allow you to automatically capture structured data from call transcripts. Organize extractions into categories and define custom questions to extract specific information like lead quality, appointment details, customer sentiment, and more.

    ### Key Features

    **Categories** - Organize related extractions together (e.g., "Agent Handover", "Visit Details", "Lead Qualification")

    **Extraction Templates** - Define what data to capture with:

    * **Name** - Descriptive identifier (e.g., "Call Outcome", "Customer Sentiment")
    * **Extraction Prompt** - Instructions guiding the LLM on what to extract
    * **Answer Type** - Choose between Free Text (open-ended) or Pre-defined (categorical options)
    * **Model** - Select LLM for extraction processing (default: gpt-4.1-mini)

    **Testing** - Validate extractions against sample or real transcripts before production deployment

    <Frame caption="Test Extractions interface">
      <img src="https://mintcdn.com/bolna-54a2d4fe/67-XP-1exGIsTFDr/images/extractions/test-extractions.png?fit=max&auto=format&n=67-XP-1exGIsTFDr&q=85&s=8346ca557dfe5cdcf044edd71acca7d2" alt="Test Extractions modal showing sample transcripts and extraction results" width="2038" height="1666" data-path="images/extractions/test-extractions.png" />
    </Frame>

    ### Common Extraction Categories

    <CardGroup cols={2}>
      <Card title="Agent Handover" icon="headset">
        Detect when calls need human intervention
      </Card>

      <Card title="Lead Qualification" icon="star">
        Extract budget, timeline, decision-maker info
      </Card>

      <Card title="Visit Details" icon="calendar">
        Capture appointment times, dates, confirmation status
      </Card>

      <Card title="Customer Sentiment" icon="face-smile">
        Analyze satisfaction levels and feedback
      </Card>
    </CardGroup>

    <Info>
      Learn how to create and manage extraction templates, configure answer types, and test extractions in the [Using Extractions](/docs/guides/prompting/using-extractions) guide.
    </Info>
  </Tab>
</Tabs>

***

## Use Cases

<CardGroup cols={2}>
  <Card title="CRM Updates" icon="database">
    Automatically update customer records after calls
  </Card>

  <Card title="Lead Scoring" icon="star">
    Extract qualification data from sales calls
  </Card>

  <Card title="Compliance Logging" icon="shield">
    Capture required data points for regulations
  </Card>

  <Card title="Performance Tracking" icon="chart-line">
    Analyze conversation outcomes and metrics
  </Card>
</CardGroup>

***

## Next Steps

<CardGroup cols={2}>
  <Card title="Inbound Tab" icon="phone-arrow-down" href="/docs/agent-setup/inbound-tab">
    Configure inbound call settings
  </Card>

  <Card title="Tools Tab" icon="function" href="/docs/agent-setup/tools-tab">
    Add function tools and APIs
  </Card>

  <Card title="Call History" icon="clock-rotate-left" href="/docs/agent-setup/call-history">
    View call logs and transcripts
  </Card>

  <Card title="Webhooks Guide" icon="webhook" href="/docs/guides/post-call/polling-call-status-webhooks">
    Learn about webhook events
  </Card>
</CardGroup>
