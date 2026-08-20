> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for March, 2026

> Explore the latest features, improvements, and API updates introduced in March 2026 for Bolna Voice AI agents.

<Update label="26th March, 2026">
  ## Custom Ambient Noise Tracks

  You can now upload your own **custom ambient noise tracks** in addition to the existing presets. This gives you full control over the background soundscape of your calls.

  **What's new:**

  * **Upload custom tracks** via `POST /ambient-sounds/custom` — supports `wav` and `mp3` formats, up to **10 MB**
  * **Delete custom tracks** via `DELETE /ambient-sounds/{sound_id}`
  * **List all tracks** via `GET /ambient-sounds` — returns both presets and your custom tracks, each with a `type` field (`preset` or `custom`)

  **What's changed:**

  * `ambient_noise_track` now accepts the **id** of an ambient sound record instead of a preset name enum
  * The three preset tracks remain available with the same IDs: `coffee-shop`, `office-ambience`, `call-center`

  Ambient noise continues to be supported with **Plivo** and **Vobiz** telephony providers.

  Read more in the [Call Tab documentation](/docs/agent-setup/call-tab#ambient-noise).
</Update>

<Update label="24th March, 2026">
  ## Extractions - Capture Structured Data from Call Transcripts

  We've added **Extractions** to automatically pull structured data from your call transcripts. Instead of manually reviewing conversations, you can set up categories and questions to extract things like lead quality, appointment details, or customer sentiment.

  Here's what you can do:

  * **Organize by category** - Group related extractions together (like "Visit Details" or "Lead Qualification")
  * **Choose your answer format** - Use free text for open-ended responses or pre-defined options with conditional logic
  * **Use variables** - Reference call data like `{name}`, `{email}`, or `{candidate_name}` in your extraction prompts
  * **Test before deploying** - Try out your extractions on sample transcripts or paste in custom ones
  * **Multiple access methods** - Available via Dashboard, Executions API, Webhooks, and Batch Executions

  Extractions return data in this format:

  ```json theme={"system"}
  {
    "extracted_data": {
      "Category Name": {
        "Extraction Name": {
          "subjective": "Free text response from LLM",
          "objective": "Pre-defined value or null"
        }
      }
    }
  }
  ```

  Use it for lead scoring, syncing appointments, preventing churn, compliance auditing, or general call intelligence.

  Learn more in the [Using Extractions documentation](/docs/guides/prompting/using-extractions) and [Dispositions API reference](/docs/api-reference/dispositions/overview).
</Update>

<Update label="18th March, 2026">
  ## Prompt Variables for Date, Time & Timezone

  You can now use `{current_date}`, `{current_time}`, and `{timezone}` as variables directly in your agent prompts for more control over placement and formatting of date/time information.

  | Variable         | Description                         | Example Value               |
  | ---------------- | ----------------------------------- | --------------------------- |
  | `{current_date}` | Current date in the user's timezone | `Wednesday, March 18, 2026` |
  | `{current_time}` | Current time in the user's timezone | `02:30:15 PM`               |
  | `{timezone}`     | Timezone name per tz database       | `Asia/Kolkata`              |

  Read more in the [Using Context documentation](/docs/using-context#date-time--timezone).
</Update>

<Update label="16th March, 2026">
  ## Ambient Noise for Calls

  You can now add background ambient noise to your calls for a more natural, human-like experience. Use the `ambient_noise_track` parameter to select a preset track.

  Available tracks:

  * **`coffee-shop`** — Background sounds of a coffee shop environment
  * **`office-ambience`** — Subtle office background noise
  * **`call-center`** — Call center ambient sounds

  Set `ambient_noise_track` to `None` to disable ambient noise (default).

  Ambient noise is supported with **Plivo** and **Vobiz** telephony providers.

  ***

  ## In-Call Reschedule Validation

  When a user asks to reschedule a call to a specific time during a conversation, the system now validates the requested time against the agent's allowed calling window before scheduling it.

  **Priority order for validation:**

  1. **`calling_guardrails`** — explicit `call_start_hour` / `call_end_hour` config always takes precedence
  2. **Agent prompt** — if no explicit guardrails are set, the LLM reads the agent's system prompt for any mentioned time restrictions
  3. **Default window (9 AM – 9 PM)** — fallback if neither of the above is configured

  If the requested reschedule time falls outside the allowed window, the request is rejected entirely.

  Read more in the [Calling Guardrails documentation](/docs/calling-guardrails#in-call-reschedule-validation).

  ***

  ## Vobiz Telephony Number Buying

  You can now search and purchase phone numbers from **Vobiz** directly via the API and the dashboard UI. The `provider` parameter has been added to phone number search and purchase endpoints, supporting `twilio`, `plivo`, and `vobiz`.

  Read more in the [Phone Numbers API documentation](/docs/api-reference/phone-numbers/search).
</Update>

<Update label="14th March, 2026">
  ## Google Gemini Flash Models Support

  Bolna now supports **Google Gemini** Flash models as LLM providers for voice AI agents. The following models are available:

  * **gemini-2.5-flash** — Production-ready, best speed and quality balance. 1M token context window.
  * **gemini-2.5-flash-lite** — Most cost-effective in the Gemini 2.5 family, optimized for low latency.
  * **gemini-3-flash-preview** — Next-generation Gemini model with improved reasoning (released Dec 2025).
  * **gemini-3.1-flash-lite-preview** — Fastest throughput at 363 tokens/sec, ideal for high-volume workloads (released Mar 2026).

  All models support **English, Hindi, Gujarati, French, Italian, and Spanish**.

  Learn more in the [Google Gemini documentation](/docs/providers/llm-model/gemini).
</Update>

<Update label="9th March, 2026">
  ## Multilingual Knowledge Base Support

  Knowledge bases now support **multilingual** language mode. When creating a knowledge base, set `language_support` to `multilingual` to enable cross-lingual retrieval across 100+ languages.

  This enables:

  * Uploading documents in any language (Hindi, Spanish, French, etc.)
  * Cross-lingual retrieval — query in one language, retrieve from documents in another

  Set the `language_support` parameter via the [Create Knowledgebase API](/docs/api-reference/knowledgebase/create) or through the dashboard when adding a new knowledge base.

  Read more in the [Knowledge Base documentation](/docs/getting-started/knowledge-base#multilingual-knowledge-bases).
</Update>

<Update label="3rd March, 2026">
  ## Provision to purchase 140 & 160 series phone numbers

  Bolna agents can now be triggered with 140 & 160 series phone numbers to comply with TRAI regulations.

  Read about procuring these phone numbers on [Purchase special phone numbers documentation](/docs/guides/inbound/obtaining-regulated-phone-numbers).
</Update>
