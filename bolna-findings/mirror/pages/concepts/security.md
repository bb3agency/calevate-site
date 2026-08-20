> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Security & Data Handling

> How Bolna handles your data, where it is stored, and what controls are available for enterprise and compliance requirements.

## Data in transit

All API requests and responses use **TLS 1.2+**. Audio streams between Bolna and telephony providers are encrypted in transit. Webhook payloads are delivered over HTTPS.

***

## Data at rest

| Data type           | What is stored                                | Retention                                                           |
| ------------------- | --------------------------------------------- | ------------------------------------------------------------------- |
| Call recordings     | Audio file of the conversation                | Available in execution record; contact support for retention policy |
| Transcripts         | Full conversation text                        | Stored in execution record                                          |
| Extracted data      | Structured fields from post-call extraction   | Stored in execution record                                          |
| Agent configuration | Prompts, tool configs, provider keys          | Encrypted at rest                                                   |
| API keys            | Hashed — Bolna cannot recover a plaintext key | N/A                                                                 |

***

## Data residency

By default, Bolna processes calls on infrastructure in the US (AWS us-east-1). Indian data residency is available for deployments where data must remain in India.

When Indian data residency is enabled:

* Call processing runs on servers in `ap-south-1` (Mumbai)
* Recordings and transcripts are stored in India
* LLM inference is routed to India-region endpoints (where available)

See [Indian Server Configuration](/docs/enterprise/indian-server-configuration) for setup.

For enterprise customers requiring other regions or on-premise deployment, see [Enterprise Plans](/docs/enterprise/plan) and [On-Premise Deployments](/docs/enterprise/on-premise-deployments).

***

## Webhook security

Bolna sends webhooks from a fixed set of source IPs:

* **`13.203.39.153`**
* **`13.126.9.249`**
* **`13.202.133.53`**

To verify webhooks are genuinely from Bolna:

1. Whitelist all three IPs on your server or firewall
2. Reject webhook requests from any other IP on your webhook endpoint

There is no HMAC signature on webhook payloads in the current version. Source IP verification is the primary trust mechanism.

***

## API key security

* API keys are displayed once at creation — copy and store them securely immediately
* If a key is compromised, revoke it from the [Bolna dashboard](https://platform.bolna.ai) and issue a new one
* Never expose your API key in client-side code or public repositories
* Use environment variables (`BOLNA_API_KEY`) in application code

***

## Provider credential storage

When you configure third-party providers (OpenAI, ElevenLabs, Twilio, etc.) in Bolna, your provider API keys are stored encrypted in Bolna's infrastructure. They are used at call time to authenticate requests on your behalf.

Bolna does not log or expose provider credentials in API responses.

***

## Sub-accounts and access control

Enterprise plans support **sub-accounts** — isolated Bolna accounts under your organization's umbrella. Each sub-account has its own agents, phone numbers, wallet balance, and API keys.

Use sub-accounts to:

* Isolate different customers or business units
* Apply per-sub-account spending limits
* Restrict which agents and numbers a team can access

See [Sub-Accounts](/docs/enterprise/sub-accounts) and [Organization Management](/docs/enterprise/organization).

***

## Compliance

Bolna supports compliance application for regulated industries. Applications are reviewed on a per-account basis.

See [Compliance Introduction](/docs/compliance-application/introduction) to understand the application process.

Bolna undergoes independent security assessments, including Vulnerability Assessment and Penetration Testing (VAPT). Our latest independent VAPT assessment received an A+ rating. If you'd like a copy of the report, request it at [support@bolna.dev](mailto:support@bolna.dev) and we'll share it with you.

For HIPAA, SOC 2, GDPR, or other specific certifications, contact [support@bolna.ai](mailto:support@bolna.ai).

***

## Responsible AI

Bolna agents are subject to the [Calling Guardrails](/docs/guides/outbound/calling-guardrails) system, which lets you configure:

* Time-of-day restrictions for when calls can be placed
* Do-not-call list integration
* Maximum call duration limits

These controls help ensure Bolna is used responsibly and in compliance with telemarketing regulations.
