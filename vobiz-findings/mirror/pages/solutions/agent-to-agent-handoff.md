> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Agent-to-Agent Handoff

> Transfer calls from AI to human agents without losing context - Vobiz carries full transcripts and call metadata through warm handoffs across 130+ countries. Zero re-explanation, seamless escalation.

## What is Agent-to-Agent Handoff?

Agent-to-agent handoff is the transfer of an active call from one AI or human agent to another, carrying the full conversation context so the receiving agent does not have to start from scratch. In modern voice AI, this specifically means the handoff between an AI voice agent and a human agent - the moment where automation reaches its limit and a real person needs to step in.

This is one of the most technically and experientially challenging problems in voice AI. Done badly, the customer hears a click, gets transferred to a hold queue, has to re-explain everything they just told the bot, and wonders why they bothered talking to the AI at all. Done well, the human agent picks up mid-sentence with full awareness of what was discussed, and the customer barely notices the transition.

## The Problem It Solves

Most voice AI deployments fail at the handoff moment. The AI handles the opening of the call beautifully, but the moment it encounters something outside its competency - a complex complaint, an emotional customer, a nuanced request - it either loops awkwardly, gives a wrong answer, or transfers blindly to a human agent with zero context. The human agent then starts from zero, which wastes time and destroys the experience.

Vobiz solves this by providing real-time audio streaming and a Transfer API that work together. The AI agent has access to the full call audio stream throughout the conversation. When it decides to hand off, it can pass structured context to your application, which then uses the Vobiz Transfer API to move the call to a human agent alongside all accumulated context.

## How Vobiz Powers Agent-to-Agent Handoff

Vobiz's WebSocket audio streaming capability is the foundation for AI agent-to-agent handoff. When a call comes in, the audio is streamed in real time to your AI application - whether that is a VAPI agent, a Retell AI agent, a LiveKit agent, an ElevenLabs voice bot, or a custom solution using OpenAI Realtime, Pipecat, Ultravox, or Bolna. The AI processes the audio, generates responses, and sends audio back through the bidirectional stream.

When the AI determines that a handoff is needed - based on its own logic, a keyword trigger, a confidence threshold, or an explicit user request like "I want to talk to a person" - it signals your application. Your application then calls the Vobiz Transfer API on the active call UUID, redirecting the call to a human agent queue or a specific agent's number. The human agent receives the call along with a summary, the full conversation transcript, and any structured data the AI extracted - customer intent, sentiment, name, account number, and issue type.

Because the handoff is an API operation, it is instantaneous. The caller does not hear a transfer tone or a queue. They hear "Let me connect you with one of our specialists now" from the AI, followed immediately by a human picking up - with full context.

## Use Cases & Scenarios

* A fintech lending company deploys a Vobiz-powered AI voice agent to handle the initial qualification of loan applicants. The AI collects basic information - income, loan amount, tenure preference - and runs a preliminary eligibility check. If the applicant qualifies, the AI hands off to a human relationship manager with a full summary of the conversation and the eligibility data already populated in the CRM. The manager receives a warm lead, not a cold call.
* A healthcare appointment system uses an AI agent to handle appointment booking, rescheduling, and general FAQs. When a patient mentions a symptom that the AI is not equipped to advise on, it immediately hands off to a triage nurse, passing the transcript and the specific symptom mentioned so the nurse can start the clinical conversation without asking the patient to repeat themselves.
* An e-commerce platform's AI voice agent handles order status, return requests, and delivery exceptions. When a customer has an escalated complaint that involves a refund above a threshold amount, the AI flags this and handoffs to a senior customer care agent. The agent sees the full order history, the AI conversation, and the reason for escalation on their screen before they even say hello.

## Why Choose Vobiz?

Vobiz is natively integrated with the major AI voice agent platforms - VAPI, Retell AI, LiveKit, ElevenLabs, Pipecat, OpenAI Realtime, Ultravox, and Bolna. This means you are not building a custom bridge between a telephony API and an AI platform. The integrations are documented and tested. You can have an AI agent fielding real calls with a working handoff mechanism in a day, not a month.

***


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.