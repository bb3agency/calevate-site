> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for February, 2026

> Explore the latest features, improvements, and API updates introduced in February 2026 for Bolna Voice AI agents.

<Update label="15th Feb, 2026">
  ## Override Agent Config in /call API

  The `/call` API now supports an `agent_data` parameter that lets you override agent configuration properties at call time. Currently, overriding the `voice_id` (for the same provider) is supported.

  This allows you to dynamically change the voice used for a specific call without modifying the agent's default configuration.

  ```json Example theme={"system"}
  {
    "agent_id": "123e4567-e89b-12d3-a456-426655440000",
    "recipient_phone_number": "+919876543210",
    "agent_data": {
      "voice_id": "Sam"
    }
  }
  ```

  Learn more in the [Make a Phone Call API documentation](/docs/api-reference/calls/make).
</Update>

<Update label="13th Feb, 2026">
  ## Sarvam v3 Models Support

  Bolna now supports **Sarvam v3** models:

  * **saaras:v3** — New transcriber model configured for direct transcription in the original spoken language. Supports all 11 Indian languages.
  * **bulbul:v3** — New Sarvam TTS voice model for improved Indian language speech synthesis.

  Learn more about Sarvam transcriber models in the [Sarvam STT documentation](/docs/providers/transcriber/sarvam) and voice models in the [Sarvam TTS documentation](/docs/providers/voice/sarvam).
</Update>

<Update label="9th Feb, 2026">
  ## Deepgram: New Indian Languages Added

  Bolna now supports additional **Deepgram** Indian languages for speech recognition:

  * **bn** — Bengali
  * **kn** — Kannada
  * **mr** — Marathi
  * **te** — Telugu
</Update>

<Update label="7th Feb, 2026">
  ## API Rate Limiting

  Bolna APIs now enforce rate limits to ensure fair usage and platform stability. Rate limits are applied per **organization** (if the user belongs to one) or per **user** otherwise.

  **Endpoint-specific limits:**

  | Endpoint                          | Rate Limit          |
  | --------------------------------- | ------------------- |
  | `/v2/agent/{agent_id}/executions` | 500 requests/minute |
  | `/v2/agent/{agent_id}`            | 500 requests/minute |
  | `/call`                           | 500 requests/minute |

  All other API endpoints are subject to a default rate limit of **1000 requests per minute**.

  Requests exceeding the limit will receive an HTTP 429 response. Learn more in the [rate limiting documentation](/docs/api-reference/rate-limiting).
</Update>

<Update label="3rd Feb, 2026">
  ## Truecaller Verification

  Bolna now supports **Truecaller Verification** — users can get their phone numbers **verified on Truecaller**, so your calls show a verified identity to recipients. This helps build trust and can improve answer rates by making it clearer who’s calling.

  Learn more in the [Truecaller Verification documentation](https://www.bolna.ai/docs/truecaller-verification).
</Update>
