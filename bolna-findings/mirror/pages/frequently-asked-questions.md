> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Frequently Asked Questions

> Find answers to common questions about Bolna Voice AI — setup, pricing, APIs, phone numbers, multilingual agents, sub-accounts, and on-premise deployment.

<AccordionGroup>
  <Accordion title="Why is my agent restricted or marked as disallowed content?">
    All agents created on Bolna undergo internal compliance and safety checks.

    If you see a message such as **“Agent is restricted due to disallowed content. Please review and update it.”**, it means your agent’s configuration or prompt may have triggered a violation of Bolna’s content safety policies.

    Disallowed content includes (but is not limited to):

    * Political campaigns
    * Illegal activities or solicitation
    * Scam or fraud-related behavior
    * Profanity or hate speech
    * NSFW, adult, or sexually explicit content
    * Harmful or misleading information

    To resolve this, please review and modify your agent’s prompt, instructions, or behavior to ensure it adheres to a valid use-case.
    Once updated, you can re-save the agent to re-trigger validation.
  </Accordion>

  <Accordion title="What type of Voice AI agents can I create on Bolna">
    Bolna supports a wide range of customizable voice agents. From free-flowing conversational assistants to structured IVR-style bots.

    You can build agents for use cases like [lead qualification](/docs/agents-library), customer support, interviews, [appointment bookings](/docs/tool-calling/book-calendar-slots), [call transfers](/docs/tool-calling/transfer-calls), and more.

    Get started with our [Agent template library](/docs/agents-library) or explore the [Playground agent setup guide](/docs/agent-setup/agent-tab).
  </Accordion>

  <Accordion title="What is the pricing for Bolna Voice AI">
    Bolna offers transparent usage-based pricing:

    * **Call pricing**: \$0.02/min platform fee (plus provider charges).

    Please refer to the [cost & pricing documentation](/docs/pricing/call-pricing) for detailed information. For high-volume usage, explore our [Enterprise Plan](/docs/enterprise/plan) with customized volume-based discounts.
  </Accordion>

  <Accordion title="Why is my bill higher than the flat per-minute rate?">
    Your flat rate only covers a specific set of **preferred ASR, LLM, and TTS models**. If your agent uses a model outside that list, that component is billed separately at variable, usage-based rates instead of being included in the flat rate.

    Check the **Add Funds** panel (click the **+** next to your wallet balance in [Agent Studio](https://platform.bolna.ai)) for the current preferred model list, or see the [Preferred models documentation](/docs/pricing/preferred-models) for the full breakdown.
  </Accordion>

  <Accordion title="How many parallel calls can I make in Bolna?">
    By default, Bolna allows up to **10 concurrent calls** for paid users. Learn more about [outbound calling concurrency](/docs/pricing/outbound-calling-concurrency) or request higher limits via the [Enterprise Plan](/docs/enterprise/plan) for large-scale deployments and [batch calling](/docs/guides/outbound/batch-calling) capabilities.
  </Accordion>

  <Accordion title="Can I purchase my own phone numbers?">
    **Yes**. You can either:

    * **Buy phone numbers directly** from the [Bolna Dashboard](/docs/guides/inbound/buying-phone-numbers).
    * **Use your own telephony account** (e.g., [Twilio](/docs/twilio-connect-provider) or [Plivo](/docs/plivo-connect-provider)) to connect and use your own manageed dedicated phone numbers.
  </Accordion>

  <Accordion title="Can the purchased phone numbers be used on other platforms">
    No - Phone numbers purchased on Bolna can only be used with Bolna Voice AI agents.
  </Accordion>

  <Accordion title="I have my own Twilio account. Can I connect and use it with Bolna Voice AI agents?">
    Absolutely. Bolna integrates seamlessly with third-party telephony providers like [Twilio](/docs/twilio-connect-provider) and [Plivo](/docs/plivo-connect-provider), allowing you to use your own account and phone numbers.
  </Accordion>

  <Accordion title="Does Bolna support multilingual Voice agents?">
    Yes. Bolna supports multiple languages and voices. You can create agents in various languages (e.g., English, Hindi) using built-in multilingual support across [speech-to-text](/docs/providers/transcriber/deepgram), [LLM](/docs/providers/llm-model/openai), and [text-to-speech](/docs/providers/voice/elevenlabs) components.

    Find the [list of all supported languages](/docs/customizations/multilingual-languages-support) and learn how to [write prompts for multilingual agents](/docs/guides/writing-prompts-in-non-english-languages).
  </Accordion>

  <Accordion title="Can I build my own application using Bolna APIs?">
    Yes, definitely. Bolna AI is an API-first platform providing a comprehensive API suite to:

    * Create, update, list, and delete voice agents via [Agent APIs](/docs/api-reference/agent/v2/overview).
    * Trigger calls via [Call APIs](/docs/api-reference/calls/overview).
    * Manage executions and logs via [Executions APIs](/docs/api-reference/executions/overview).
    * Do bulk calls using batches via [Batches APIs](/docs/api-reference/batches/overview).
    * Manage phone numbers via [Phone numbers APIs](/docs/api-reference/phone-numbers/overview).
    * Create, list and manage sub‑accounts via [Sub-Account APIs](/docs/api-reference/sub-accounts/overview).
  </Accordion>

  <Accordion title="Can I add my team members to collaborate?">
    Yes. The platform supports shared access where you can add your team (developers, operators, analysts, etc.) to collaborate within the Bolna dashboard. APIs also allow scoped access through sub‑accounts.
  </Accordion>

  <Accordion title="Can I create multiple sub-accounts?">
    Yes. Bolna supports multiple sub-accounts, designed for enterprise-level teams to isolate projects, billing, and permissions—fully manageable via the API.
  </Accordion>

  <Accordion title="Do you support on-premise deployments?">
    Yes - Bolna AI supports on-premise deployments.

    You can run the complete Bolna platform on your own infrastructure (e.g., private cloud or on-premise servers) instead of the hosted Bolna service.

    <Tip>
      On-premise is available only for enterprise customers. Please reach out to us at [enterprise@bolna.ai](mailto:enterprise@bolna.ai) or schedule a call [https://www.bolna.ai/meet](https://www.bolna.ai/meet) for more information.
    </Tip>
  </Accordion>

  <Accordion title="Does Bolna support SIP connectivity?">
    Not yet. SIP connectivity is **not currently supported** on Bolna Voice AI.

    However, native SIP integration is on our roadmap to enable direct enterprise-grade connectivity with PBX systems and VoIP infrastructure.

    You can currently use [Twilio](/docs/twilio-connect-provider), [Plivo](/docs/plivo-connect-provider) or [Exotel](/docs/exotel-connect-provider) integrations for all telephony and call-routing needs.
  </Accordion>
</AccordionGroup>
