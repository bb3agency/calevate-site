> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vobiz FAQ – Billing, API Limits, SIP Trunking & Integrations

> Quick answers on Vobiz accounts, billing, concurrency limits, SIP trunking, AI voice integrations, and global compliance. Expand any question for the full answer.

Quick answers to common questions. Click any question to expand the answer, or follow the link to the full article for more detail.

## Account & Billing

<AccordionGroup>
  <Accordion title="Can I connect my trial number for inbound calls?">
    **No.** Trial numbers are sandboxed for outbound testing only - no inbound routing until you complete KYC verification and purchase a dedicated DID. To unlock inbound calls, complete KYC in your dashboard (GST for organizations, Aadhaar/PAN for individuals), then purchase a dedicated incoming trunk.

    [Read full article](/docs/faq/trial-inbound)
  </Accordion>

  <Accordion title="Can I purchase additional Concurrency or CPS?">
    Yes. Log in to the [console](https://console.vobiz.ai), go to Account Settings → Limits, and purchase a higher concurrency or CPS ceiling directly through the billing portal. Changes take effect immediately.

    [Read full article](/docs/faq/purchase-concurrency-cps)
  </Accordion>

  <Accordion title="Do you provide 140, 160, and 92 series numbers?">
    Yes - 140, 160, and 92-series numbers are available. These require additional KYC and carrier approval. Contact support with your use case to initiate provisioning.

    [Read full article](/docs/faq/number-series)
  </Accordion>
</AccordionGroup>

## API & Limits

<AccordionGroup>
  <Accordion title="Why am I receiving a 429 error?">
    You've hit either your **Concurrency limit** (too many simultaneous active calls) or your **CPS limit** (initiating calls too fast). Check your current limits in the console under Account Settings. Fix by throttling your dialer or purchasing a higher limit.

    [Read full article](/docs/faq/error-429)
  </Accordion>

  <Accordion title="What is Concurrency?">
    Concurrency is the maximum number of **simultaneous active calls** on your account at any moment. If your limit is 10 and 10 calls are live, an 11th attempt returns a 429 or SIP 503 immediately. Calculate your needs based on average call duration × calls per hour.

    [Read full article](/docs/faq/concurrency)
  </Accordion>

  <Accordion title="What is CPS (Calls Per Second)?">
    CPS governs how fast you can **initiate** calls - independent of concurrency. CPS of 1 means one new call per second. Even with free concurrency slots, blasting 5 calls in the same second with CPS=1 fails 4 of them. Use a pacing queue in your dialer to stay under the limit.

    [Read full article](/docs/faq/cps)
  </Accordion>

  <Accordion title="Why am I receiving SIP response codes 480 or 486?">
    **486 Busy Here** - the callee is on another call or rejected the call. **480 Temporarily Unavailable** - the device is off, out of range, or in airplane mode. If you see these repeatedly across many numbers on one carrier, that carrier's spam filter may have blocked your caller ID - pause dialing and contact support.

    [Read full article](/docs/faq/sip-codes-480-486)
  </Accordion>
</AccordionGroup>

## Features & Integration

<AccordionGroup>
  <Accordion title="What integrations do you support?">
    Vapi, Retell AI, LiveKit, ElevenLabs, Pipecat, Bolna, Ultravox, and OpenAI Realtime - all via SIP trunk or WebSocket streaming. Standard SIP interoperability with Asterisk, FreeSWITCH, Teams, and Cisco PBX systems. See the [Integrations](/docs/integrations) section for step-by-step guides.

    [Read full article](/docs/faq/integrations)
  </Accordion>

  <Accordion title="Is call transfer supported?">
    Yes - three methods: (1) [`<Dial>`](/docs/xml/dial) XML tag for warm/cold bridge transfers; (2) [REST API transfer](/docs/call/transfer-call) to redirect a live call to a new XML application mid-call; (3) SIP REFER (RFC 3515) for PBX-native blind or attended transfers.

    [Read full article](/docs/faq/call-transfer)
  </Accordion>

  <Accordion title="Do you support IVR?">
    Yes. Build IVR flows using [`<Gather>`](/docs/xml/gather) for DTMF and speech input, [`<Speak>`](/docs/xml/speak) for TTS prompts, and [`<Play>`](/docs/xml/play) for pre-recorded audio. Your backend returns XML from a webhook - no drag-and-drop constraints.

    [Read full article](/docs/faq/ivr)
  </Accordion>
</AccordionGroup>

## Trust & Support

<AccordionGroup>
  <Accordion title="What documents are required for verification?">
    **Organizations:** valid GST certificate (+ authorized signatory in some cases). **Individuals:** Aadhaar card + PAN card. Documents are encrypted at rest and only used for telecom regulatory compliance - not for any secondary purpose.

    [Read full article](/docs/faq/verification-docs)
  </Accordion>

  <Accordion title="How can I contact support?">
    Open the support chat in the [console](https://console.vobiz.ai), or email [support@vobiz.ai](mailto:support@vobiz.ai). For production incidents include your `requestId` from the error response to speed up diagnosis.

    [Read full article](/docs/faq/contact-support)
  </Accordion>
</AccordionGroup>

## Browse all topics

<CardGroup cols={2}>
  <Card title="Trial number inbound" icon="phone-arrow-down-left" href="/docs/faq/trial-inbound">
    Why trial numbers can't receive inbound calls and how to unlock them.
  </Card>

  <Card title="Purchase Concurrency / CPS" icon="credit-card" href="/docs/faq/purchase-concurrency-cps">
    How to scale up concurrent channels and calls-per-second limits.
  </Card>

  <Card title="140 / 160 / 92 numbers" icon="phone" href="/docs/faq/number-series">
    Premium and short-code number provisioning availability.
  </Card>

  <Card title="429 errors" icon="triangle-exclamation" href="/docs/faq/error-429">
    Diagnosing rate-limit and concurrency rejections.
  </Card>

  <Card title="Concurrency" icon="chart-bar" href="/docs/faq/concurrency">
    Simultaneous-call limits and how to size them.
  </Card>

  <Card title="CPS" icon="bolt" href="/docs/faq/cps">
    Calls-per-second pacing and queue strategies.
  </Card>

  <Card title="SIP 480 / 486" icon="shield-check" href="/docs/faq/sip-codes-480-486">
    Distinguishing busy / unavailable / spam-blocked calls.
  </Card>

  <Card title="Integrations" icon="microchip" href="/docs/faq/integrations">
    Supported AI agents, SIP providers, and PBX bridges.
  </Card>

  <Card title="Call transfer" icon="arrow-right-arrow-left" href="/docs/faq/call-transfer">
    Dial XML, REST transfer, and SIP REFER methods.
  </Card>

  <Card title="IVR support" icon="comment" href="/docs/faq/ivr">
    Build branching menus with Gather, Speak, and Play.
  </Card>

  <Card title="Verification documents" icon="file-lines" href="/docs/faq/verification-docs">
    KYC requirements for organizations and individuals.
  </Card>

  <Card title="Contact support" icon="envelope" href="/docs/faq/contact-support">
    How to reach our team and what to include in tickets.
  </Card>

  <Card title="Domestic calling in India" icon="globe" href="/docs/faq/domestic-calling-india">
    Caller-ID, media anchoring, and KYC requirements.
  </Card>
</CardGroup>

## Still have questions?

Our support team is here to help with anything not covered above. [Contact support](/docs/faq/contact-support).


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.