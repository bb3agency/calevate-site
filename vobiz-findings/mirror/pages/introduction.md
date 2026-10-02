> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz – Global SIP Trunking & Voice API Platform

> Vobiz is a developer-first telephony platform with global SIP trunking and voice APIs in 130+ countries - native integrations with Vapi, Retell, ElevenLabs, and pay-per-minute pricing.

<script type="application/ld+json">
  {`{
    "@context": "https://schema.org",
    "@graph": [
      {
        "@type": "SoftwareApplication",
        "name": "Vobiz",
        "applicationCategory": "DeveloperApplication",
        "operatingSystem": "Web",
        "description": "Vobiz is a developer-first telephony platform with global SIP trunking and voice APIs in 130+ countries - native integrations with Vapi, Retell, ElevenLabs, and pay-per-minute pricing.",
        "url": "https://vobiz.ai",
        "offers": {
          "@type": "Offer",
          "priceCurrency": "INR",
          "price": "0.45",
          "priceSpecification": {
            "@type": "UnitPriceSpecification",
            "price": "0.45",
            "priceCurrency": "INR",
            "unitText": "per minute"
          },
          "availability": "https://schema.org/InStock",
          "url": "https://vobiz.ai"
        },
        "sameAs": [
          "https://x.com/Vobiz_Ai",
          "https://github.com/vobiz-ai",
          "https://linkedin.com/company/vobizai"
        ]
      },
      {
        "@type": "Organization",
        "name": "Vobiz",
        "url": "https://vobiz.ai",
        "sameAs": [
          "https://x.com/Vobiz_Ai",
          "https://github.com/vobiz-ai",
          "https://linkedin.com/company/vobizai"
        ],
        "contactPoint": {
          "@type": "ContactPoint",
          "email": "support@vobiz.ai",
          "contactType": "customer support"
        }
      },
      {
        "@type": "FAQPage",
        "mainEntity": [
          {
            "@type": "Question",
            "name": "What is Vobiz?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Vobiz is a global programmable telephony platform for developers - SIP trunking, voice APIs, real-time audio streaming, and WhatsApp Business API available in 130+ countries with pay-per-minute pricing and no monthly commitments."
            }
          },
          {
            "@type": "Question",
            "name": "How do I make my first phone call with the Vobiz API?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Sign up at console.vobiz.ai, copy your Auth ID and Auth Token, buy a phone number, then POST to https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/ with from, to, and answer_url."
            }
          },
          {
            "@type": "Question",
            "name": "Which AI voice platforms does Vobiz support?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Vobiz has native integrations with Vapi, Retell AI, ElevenLabs, LiveKit, Pipecat, Bolna, Ultravox, and OpenAI Realtime. All connect via SIP trunking or bidirectional WebSocket audio streaming."
            }
          },
          {
            "@type": "Question",
            "name": "Does Vobiz work outside India?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Yes. Vobiz is available in 130+ countries with local phone numbers, competitive per-minute rates, and low-latency infrastructure worldwide. India-specific features (TRAI compliance, INR billing, GST invoices) are available for Indian accounts."
            }
          },
          {
            "@type": "Question",
            "name": "What programming languages does Vobiz support?",
            "acceptedAnswer": {
              "@type": "Answer",
              "text": "Official SDKs are available for Python, Node.js, Ruby, Go, and C#. The REST API works with any language that can make HTTP requests."
            }
          }
        ]
      }
    ]
    }`}
</script>

## Welcome to Vobiz

Vobiz is a global programmable telephony platform built for developers. It provides SIP trunking, outbound and inbound voice calls, real-time audio streaming, WhatsApp Business API, and native integrations with AI voice platforms - available in 130+ countries with pay-per-minute pricing and no monthly commitments.

**What you can build:**

* **AI voice agents** - connect Vapi, Retell AI, ElevenLabs, LiveKit, Pipecat, Bolna, or Ultravox to real phone numbers over SIP trunking
* **Outbound dialers** - make bulk calls to up to 1000 destinations in one API request across any country
* **IVR systems** - build interactive menus using Voice XML with DTMF and speech recognition
* **Contact centres** - inbound routing, call recording, CDR analytics, and conferencing
* **WhatsApp campaigns** - send template, media, and interactive messages via the WhatsApp Business API

**Base API URL:** `https://api.vobiz.ai/api/v1`\
**Authentication:** `X-Auth-ID` + `X-Auth-Token` headers on every request - see [Authentication](/docs/api-reference/authentication) for where to find your credentials and common 401 causes.

<CardGroup cols={2}>
  <Card title="Quick Start" icon="bolt" href="/docs/quick-start">
    Make your first call in under 5 minutes.
  </Card>

  <Card title="Build an AI Voice Agent" icon="robot" href="/docs/guides/ai-voice-agent">
    Connect SIP to Vapi, Retell AI, ElevenLabs, or Pipecat.
  </Card>

  <Card title="Vobiz API Reference" icon="code" href="/docs/api-reference">
    Browse the complete REST API reference for voice, SIP, numbers, WhatsApp, and account management.
  </Card>

  <Card title="Error Handling" icon="triangle-exclamation" href="/docs/errors">
    Understand error codes and how to handle them gracefully.
  </Card>
</CardGroup>

## Developer resources

Use these resources to build with Vobiz, inspect the API contract, or connect an AI coding tool to the live documentation.

<CardGroup cols={3}>
  <Card title="Developer hub" icon="code-branch" href="https://vobiz.ai/developers">
    Find the API docs, OpenAPI specification, SDKs, Agent Skills, MCP server, and developer console in one place.
  </Card>

  <Card title="OpenAPI specification" icon="file-code" href="https://vobiz.ai/openapi.json">
    Download the machine-readable API specification.
  </Card>

  <Card title="Vobiz Docs MCP server" icon="server" href="https://vobiz.ai/docs/mcp">
    Connect an MCP client over Streamable HTTP to search current voice, SIP, messaging, and AI-agent documentation.
  </Card>

  <Card title="Vobiz Docs MCP setup guide" icon="book-open" href="/docs/resources/mcp">
    Configure Claude, Cursor, VS Code, and other MCP clients, then verify the server tools and discovery metadata.
  </Card>

  <Card title="Developer Console" icon="terminal" href="https://console.vobiz.ai">
    Create an account and manage your API credentials.
  </Card>

  <Card title="llms.txt" icon="file-lines" href="https://vobiz.ai/llms.txt">
    Read the machine-oriented index of Vobiz developer resources.
  </Card>

  <Card title="agents.md" icon="robot" href="https://vobiz.ai/agents.md">
    Give coding agents the recommended Vobiz entry points.
  </Card>

  <Card title="GitHub" icon="github" href="https://github.com/vobiz-ai">
    Browse official SDKs, examples, and reference applications.
  </Card>

  <Card title="Agent Skills" icon="brain" href="https://github.com/vobiz-ai/Agent-Skills">
    Install reusable Vobiz skills for supported coding agents.
  </Card>

  <Card title="Agent Skills guide" icon="book" href="/docs/resources/skills">
    Install the 13 Vobiz skills in Claude, Codex, and other supported coding agents.
  </Card>

  <Card title="Integrations" icon="plug" href="/docs/integrations">
    Connect Vobiz to supported voice AI platforms and SDKs.
  </Card>

  <Card title="API status" icon="signal" href="https://status.vobiz.ai">
    Check current service availability and incident history.
  </Card>
</CardGroup>

## Core APIs

<CardGroup cols={3}>
  <Card title="Account & Balance" icon="user" href="/docs/account">
    Manage your Vobiz account, check balance, and retrieve credentials.
  </Card>

  <Card title="Phone Numbers" icon="phone" href="/docs/account-phone-number">
    List, purchase, and manage DID numbers.
  </Card>

  <Card title="Sub-Accounts" icon="sitemap" href="/docs/sub-accounts">
    Isolate usage and billing per customer or environment.
  </Card>

  <Card title="Call Management" icon="phone-arrow-up-right" href="/docs/call/overview">
    Make, transfer, and control live calls via REST API.
  </Card>

  <Card title="SIP Trunking" icon="server" href="/docs/trunks">
    Provision trunks, credentials, IP ACLs, and origination URIs.
  </Card>

  <Card title="Voice XML" icon="file-code" href="/docs/xml/overview/how-it-works">
    Script call flows with Vobiz XML elements.
  </Card>
</CardGroup>

## Voice AI Integrations

Connect Vobiz SIP trunking with leading AI voice platforms.

<CardGroup cols={4}>
  <Card title="VAPI" icon="plug" href="/docs/integrations/vapi-dashboard">
    Dashboard and API setup for VAPI.
  </Card>

  <Card title="Retell AI" icon="plug" href="/docs/integrations/retellai-dashboard">
    Dashboard and API setup for Retell AI.
  </Card>

  <Card title="ElevenLabs" icon="plug" href="/docs/integrations/elevenlabs-dashboard">
    Dashboard and API setup for ElevenLabs.
  </Card>

  <Card title="LiveKit" icon="plug" href="/docs/integrations/livekit">
    Real-time audio streaming with LiveKit.
  </Card>

  <Card title="Pipecat" icon="plug" href="/docs/integrations/pipecat">
    Python voice AI pipelines with Pipecat.
  </Card>

  <Card title="Bolna.ai" icon="plug" href="/docs/integrations/bolna">
    Conversational AI with Bolna.
  </Card>

  <Card title="Ultravox" icon="plug" href="/docs/integrations/ultravox">
    Low-latency voice AI with Ultravox.
  </Card>

  <Card title="OpenAI Realtime" icon="plug" href="/docs/integrations/openai-realtime">
    OpenAI Realtime API over WebSockets.
  </Card>
</CardGroup>

## Resources

<CardGroup cols={3}>
  <Card title="Core Concepts" icon="book-open" href="/docs/concepts">
    SIP trunking, WebSockets, callbacks, and more.
  </Card>

  <Card title="Best Practices" icon="star" href="/docs/best-practices">
    Number utilization, DLT registration, and capacity planning.
  </Card>

  <Card title="FAQ" icon="circle-question" href="/docs/faq">
    Common questions about concurrency, CPS, integrations, and more.
  </Card>
</CardGroup>

## Frequently Asked Questions

<AccordionGroup>
  <Accordion title="What is Vobiz?">
    Vobiz is a global programmable telephony platform for developers - SIP trunking, voice APIs, real-time audio streaming, and WhatsApp Business API available in 130+ countries with pay-per-minute pricing and no monthly commitments.
  </Accordion>

  <Accordion title="How do I make my first phone call with the Vobiz API?">
    Sign up at console.vobiz.ai, copy your Auth ID and Auth Token, buy a phone number, then POST to `https://api.vobiz.ai/api/v1/Account/{auth_id}/Call/` with `from`, `to`, and `answer_url`. Full steps are in the [Quick Start](/docs/quick-start).
  </Accordion>

  <Accordion title="Which AI voice platforms does Vobiz support?">
    Vobiz has native integrations with Vapi, Retell AI, ElevenLabs, LiveKit, Pipecat, Bolna, Ultravox, and OpenAI Realtime. All connect via SIP trunking or bidirectional WebSocket audio streaming.
  </Accordion>

  <Accordion title="Does Vobiz work outside India?">
    Yes. Vobiz is available in 130+ countries with local phone numbers, competitive per-minute rates, and low-latency infrastructure worldwide. India-specific features (TRAI compliance, INR billing, GST invoices) are available for Indian accounts.
  </Accordion>

  <Accordion title="What programming languages does Vobiz support?">
    Official SDKs are available for Python, Node.js, Ruby, Go, and C#. The REST API works with any language that can make HTTP requests.
  </Accordion>
</AccordionGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.