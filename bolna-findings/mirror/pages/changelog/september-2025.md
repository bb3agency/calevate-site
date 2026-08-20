> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for September, 2025

> Explore the latest features, improvements, and API updates introduced in September 2025 for Bolna Voice AI agents.

<Update label="29th Sep, 2025">
  ## Phone Number Compliance Application Requirement

  * Introduced mandatory compliance application process for purchasing phone numbers on Bolna platform
  * Users must now submit business verification documents before purchasing dedicated phone numbers:
    * CIN (Corporate Identification Number) certificate
    * GST registration details and certificate
  * One-time application with 12-24 hour review process
  * Enhanced security and regulatory compliance for telecommunications services
  * Learn more:
    * [Compliance Requirements Overview](/docs/compliance-application/introduction) - Understand why compliance is required and what documents you need
    * [Step-by-Step Submission Guide](/docs/compliance-application/how-to-submit-guide) - Complete walkthrough of the application process
</Update>

<Update label="27th Sep, 2025">
  ## Added Anthropic support for LLM

  * Support for the following [Anthropic](/docs/providers/llm-model/anthropic) models. Learn more about Anthropic models from their [official website](https://www.anthropic.com).
    1. `claude-sonnet-4`

  ## Added Sarvam and AssemblyAI transcriber support

  * [Sarvam](/docs/providers/transcriber/sarvam) transcriber for Speech to Text (STT) capabilities with 11 Indian languages including English, Hindi, Bengali, Tamil, Telugu, Kannada, Malayalam, Marathi, Gujarati, Punjabi, and Odia.
  * [AssemblyAI](/docs/providers/transcriber/assemblyai) transcriber for Speech to Text (STT) capabilities with real-time English streaming capabilities
</Update>

<Update label="24th Sep, 2025">
  ## Concurrency model at sub-account scope

  * Concurrency limits can now be configured at the sub-account level, allowing multiple calls or batches to run in parallel instead of being queued one after another. See how to configure concurrency when creating a sub-account in the ([API doc](/docs/api-reference/sub-accounts/create))

  ## Batch Webhook Notifications

  * Users can now attach a webhook URL to a batch at upload time. When the batch status changes —  `processed`, `scheduled`, `queued`, `running`, `completed` or `stopped`,  webhook updates will be sent automatically to track the progress of batches in real time.

  <Frame>
    <img src="https://mintcdn.com/bolna-54a2d4fe/cpIUeODcZQK1jwMr/images/batch_webhook_field.png?fit=max&auto=format&n=cpIUeODcZQK1jwMr&q=85&s=0b1a2a968fb50ee9d0fad57a43efe72a" alt="Voice Lab clone voices feature interface in Bolna showing one-click voice cloning with audio sample upload" width="774" height="825" data-path="images/batch_webhook_field.png" />
  </Frame>
</Update>

<Update label="15th Sep, 2025">
  ## Voice AI Agents Template Library

  The Voice AI Agents library now includes the following pre-built template agents to help you get started quickly with Bolna Voice AI:

  * [Recruitment Voice AI agent](/docs/voice-agents/recruitment-agent)
  * [Customer Support Voice AI agent](/docs/voice-agents/customer-support-agent)
  * [Cart Abandonment Voice AI agent](/docs/voice-agents/cart-abandonment-agent)
  * [Lead Qualification Voice AI agent](/docs/voice-agents/lead-qualification-agent)
  * [Onboarding Voice AI agent](/docs/voice-agents/onboarding-agent)
  * [Front Desk Voice AI agent](/docs/voice-agents/front-desk-agent)
  * [COD Confirmation Voice AI agent](/docs/voice-agents/cod-confirmation-agent)
  * [Announcements Voice AI agent](/docs/voice-agents/announcements-agent)
  * [Reminders Voice AI agent](/docs/voice-agents/reminders-agent)
  * [Surveys Voice AI agent](/docs/voice-agents/surveys-agent)
  * [Property Tech Voice AI agent](/docs/voice-agents/property-tech-agent)
  * [Dentist Appointment Voice AI agent](/docs/voice-agents/dentist-appointment-agent)
  * [Salon Booking Voice AI agent](/docs/voice-agents/salon-booking-agent)
  * [Weekend Planner Voice AI agent](/docs/voice-agents/weekend-planner-agent)
  * [Sales Credit Card Voice AI agent](/docs/voice-agents/sales-credit-card-agent)
  * [Sales Loans Voice AI agent](/docs/voice-agents/sales-loans-agent)
</Update>

<Update label="11th Sep, 2025">
  ## API Updates

  * Cumulative view of all sub-account usage ([API doc](/docs/api-reference/sub-accounts/all_usage))
</Update>

<Update label="9th Sep, 2025">
  ## API Updates

  * Outbound calls in `queued` or `scheduled` state can be stopped before executions ([API doc](/docs/api-reference/calls/stop_call))
</Update>

<Update label="8th Sep, 2025">
  ## Passing headers in Custom Function tools

  * Passing custom `headers` is now supported on [function tooling](/docs/tool-calling/custom-function-calls).

  <Frame caption="Function tool example with headers">
    <img src="https://mintcdn.com/bolna-54a2d4fe/dqQQbSWEk--ocwH1/images/tool-calling/custom_function.png?fit=max&auto=format&n=dqQQbSWEk--ocwH1&q=85&s=a251dacf2050f973513c2621d378d12e" alt="Passing custom headers in your custom functions" width="1248" height="1542" data-path="images/tool-calling/custom_function.png" />
  </Frame>
</Update>
