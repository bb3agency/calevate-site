> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Voice AI Platform Architecture & Concepts

> Understand how Bolna Voice AI works including voice pipeline, agent configuration, real-time capabilities, and multilingual conversational AI agents.

## What is Bolna?

Bolna is a platform for building **conversational Voice AI agents** that can handle phone calls naturally, just like a human. Whether you're automating customer support, qualifying leads, or scheduling appointments, Bolna provides the infrastructure to create, deploy, and scale voice agents.

<CardGroup cols={3}>
  <Card title="Build" icon="hammer">
    Configure agents with prompts, voice, and tools
  </Card>

  <Card title="Deploy" icon="rocket">
    Connect to phone numbers for inbound/outbound calls
  </Card>

  <Card title="Scale" icon="chart-line">
    Handle thousands of concurrent conversations
  </Card>
</CardGroup>

***

## How Voice AI Works

Every conversation flows through a **three-step pipeline** that happens in real-time:

<Steps>
  <Step title="Listen" icon="ear-listen">
    **Speech-to-Text (ASR)** converts the caller's voice into text that your AI can understand.

    Bolna supports [Deepgram](/docs/providers/transcriber/deepgram), [Azure](/docs/providers/transcriber/azure), [ElevenLabs](/docs/providers/transcriber/elevenlabs), and more.
  </Step>

  <Step title="Think" icon="brain">
    **Large Language Model (LLM)** processes the text, understands context, and generates an intelligent response.

    Connect [OpenAI](/docs/providers/llm-model/openai), [Anthropic](/docs/providers/llm-model/anthropic), [Azure OpenAI](/docs/providers/llm-model/azure-openai), or your own LLM.
  </Step>

  <Step title="Speak" icon="volume-high">
    **Text-to-Speech (TTS)** converts the response into natural-sounding speech played back to the caller.

    Choose voices from [ElevenLabs](/docs/providers/voice/elevenlabs), [Cartesia](/docs/providers/voice/cartesia), [Azure](/docs/providers/voice/azure), and more.
  </Step>
</Steps>

<Info>
  Bolna orchestrates this entire pipeline in **under 600ms**, enabling natural, real-time conversations with minimal latency.
</Info>

***

## Key Terms Explained

New to Voice AI? Here's what the technical terms mean in plain English:

<AccordionGroup>
  <Accordion title="LLM (Large Language Model)" icon="brain">
    **Think of it as**: The brain of your AI agent.

    An LLM is an AI system (like ChatGPT) that understands language and generates human-like responses. When someone speaks to your agent, the LLM reads the transcribed text, understands what the person wants, and writes a response, just like a customer service rep would.

    **Examples**: OpenAI GPT-4, Anthropic Claude, Google Gemini
  </Accordion>

  <Accordion title="Transcriber / ASR (Speech-to-Text)" icon="ear-listen">
    **Think of it as**: The ears of your AI agent.

    ASR (Automatic Speech Recognition) listens to what someone says on a call and converts their spoken words into written text. This text is then sent to the LLM so it can understand and respond.

    **Examples**: Deepgram, Azure Speech, Google STT
  </Accordion>

  <Accordion title="Synthesizer / TTS (Text-to-Speech)" icon="volume-high">
    **Think of it as**: The voice of your AI agent.

    TTS (Text-to-Speech) takes the written response from the LLM and speaks it out loud in a natural-sounding voice. You can choose different voices, accents, and speaking styles to match your brand.

    **Examples**: ElevenLabs, Cartesia, Azure TTS
  </Accordion>

  <Accordion title="Telephony Provider" icon="phone">
    **Think of it as**: The phone company that connects your calls.

    A telephony provider handles the actual phone infrastructure for buying phone numbers, connecting calls, and ensuring audio quality. Bolna integrates with providers so your AI agent can make and receive real phone calls.

    **Examples**: Twilio, Plivo, Exotel, Vobiz
  </Accordion>

  <Accordion title="Agent" icon="robot">
    **Think of it as**: Your virtual employee.

    An agent is a complete Voice AI system configured with a personality, instructions, voice, and capabilities. It's like hiring a virtual employee; you tell it what to say, how to act, and what tasks to perform.
  </Accordion>

  <Accordion title="Prompt" icon="file-lines">
    **Think of it as**: The training manual for your agent.

    A prompt is a set of instructions you write to tell the agent how to behave. It includes the agent's personality, what information to collect, how to handle different situations, and what NOT to say.
  </Accordion>

  <Accordion title="Latency" icon="stopwatch">
    **Think of it as**: Response time, how fast the agent replies.

    Latency is the delay between when someone finishes speaking and when the agent starts responding. Lower latency (under 1 second) feels more natural, like a real conversation. Bolna optimizes for sub-600ms latency.
  </Accordion>

  <Accordion title="Knowledge Base / RAG" icon="book">
    **Think of it as**: Reference documents your agent can read.

    A knowledge base is a collection of documents (PDFs, websites, FAQs) that your agent can search during conversations. RAG (Retrieval-Augmented Generation) is the technology that lets the agent find relevant information and use it in responses.
  </Accordion>
</AccordionGroup>

***

## What Can Bolna Agents Do?

### Handle Phone Calls

<CardGroup cols={2}>
  <Card title="Inbound Calls" icon="phone-arrow-down" href="/docs/guides/inbound/receiving-incoming-calls">
    Answer customer calls 24/7 with AI-powered responses
  </Card>

  <Card title="Outbound Calls" icon="phone-arrow-up-right" href="/docs/guides/outbound/making-outgoing-calls">
    Proactively reach customers for sales, reminders, and follow-ups
  </Card>

  <Card title="Batch Calling" icon="list-check" href="/docs/guides/outbound/batch-calling">
    Launch campaigns with thousands of concurrent calls
  </Card>

  <Card title="Call Transfer" icon="phone-arrow-right" href="/docs/tool-calling/transfer-calls">
    Route to human agents when AI assistance isn't enough
  </Card>
</CardGroup>

***

### Execute Actions During Calls

Agents can perform **real-time actions** by calling external APIs and tools:

<Accordion title="Built-in Function Tools">
  | Tool                     | What It Does                                  |
  | ------------------------ | --------------------------------------------- |
  | **Check Calendar Slots** | Query available appointment slots via Cal.com |
  | **Book Appointments**    | Schedule meetings directly during the call    |
  | **Transfer Calls**       | Route to human agents or other numbers        |
  | **Custom Functions**     | Call any API endpoint based on conversation   |
</Accordion>

<Tip>
  Configure function tools in the [Tools Tab](/docs/agent-setup/tools-tab). Your agent can access CRMs, databases, payment systems, and more, all while on the call.
</Tip>

***

### Extract Insights After Calls

Every conversation generates valuable data:

<CardGroup cols={3}>
  <Card title="Transcripts" icon="file-lines">
    Full conversation text with speaker labels
  </Card>

  <Card title="Recordings" icon="microphone">
    Audio recordings for review and training
  </Card>

  <Card title="Summaries" icon="sparkles">
    AI-generated call summaries
  </Card>
</CardGroup>

Configure **post-call extractions** in the [Extractions Tab](/docs/agent-setup/analytics-tab) to automatically extract:

* Customer intent and sentiment
* Key data points (name, email, order ID)
* Custom fields you define

***

## Agent Configuration

Every Bolna agent is customized through **8 configuration tabs**:

<Tabs>
  <Tab title="Core Settings">
    <CardGroup cols={2}>
      <Card title="Agent Tab" icon="file-lines" href="/docs/agent-setup/agent-tab">
        **Prompts & Personality**

        Define your agent's welcome message, instructions, and conversation behavior.
      </Card>

      <Card title="LLM Tab" icon="brain" href="/docs/agent-setup/llm-tab">
        **Intelligence & Knowledge**

        Choose your language model and connect knowledge bases for context-aware responses.
      </Card>

      <Card title="Audio Tab" icon="waveform-lines" href="/docs/agent-setup/audio-tab">
        **Voice & Transcription**

        Select voice provider, language, and transcription settings.
      </Card>

      <Card title="Engine Tab" icon="gauge-high" href="/docs/agent-setup/engine-tab">
        **Latency & Behavior**

        Fine-tune response timing, interruption handling, and user detection.
      </Card>
    </CardGroup>
  </Tab>

  <Tab title="Call Settings">
    <CardGroup cols={2}>
      <Card title="Call Tab" icon="phone" href="/docs/agent-setup/call-tab">
        **Telephony & Features**

        Configure voicemail detection, DTMF input, and call timeouts.
      </Card>

      <Card title="Tools Tab" icon="function" href="/docs/agent-setup/tools-tab">
        **API Integrations**

        Connect Cal.com, CRMs, and custom function tools.
      </Card>

      <Card title="Extractions Tab" icon="chart-line" href="/docs/agent-setup/analytics-tab">
        **Webhooks & Extraction**

        Set up post-call summaries, data extraction, and webhooks.
      </Card>

      <Card title="Inbound Tab" icon="phone-arrow-down" href="/docs/agent-setup/inbound-tab">
        **Caller Matching**

        Match callers to your database and prevent spam.
      </Card>
    </CardGroup>
  </Tab>
</Tabs>

***

## Use Cases

<CardGroup cols={2}>
  <Card title="Customer Support" icon="headset" href="/docs/voice-agents/customer-support-agent">
    Handle FAQs, troubleshoot issues, and escalate complex cases
  </Card>

  <Card title="Lead Qualification" icon="filter" href="/docs/voice-agents/lead-qualification-agent">
    Qualify inbound leads and schedule meetings with sales reps
  </Card>

  <Card title="Appointment Booking" icon="calendar-check" href="/docs/voice-agents/front-desk-agent">
    Book, reschedule, and confirm appointments automatically
  </Card>

  <Card title="Recruitment" icon="users" href="/docs/voice-agents/recruitment-agent">
    Screen candidates and schedule interviews at scale
  </Card>
</CardGroup>

***

## Get Started

<CardGroup cols={2}>
  <Card title="Create Your First Agent" icon="plus" href="/docs/getting-started/agent-creation">
    Build an agent in under 5 minutes
  </Card>

  <Card title="Agent Setup Guide" icon="compass" href="/docs/agent-setup/overview">
    Explore all configuration options
  </Card>

  <Card title="Connect Providers" icon="plug" href="/docs/getting-started/providers">
    Set up voice, LLM, and telephony providers
  </Card>

  <Card title="Agents Library" icon="grid" href="/docs/agents-library">
    Start from pre-built templates
  </Card>
</CardGroup>
