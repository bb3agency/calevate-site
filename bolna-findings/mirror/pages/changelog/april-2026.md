> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for April, 2026

> Explore the latest features and improvements introduced in April 2026 for Bolna Voice AI agents.

<Update label="29th April, 2026">
  ## Conversation Rating & Feedback

  You can now rate and leave feedback on individual conversations directly from the dashboard. After reviewing a call, score it from 1 (Poor) to 4 (Excellent) and optionally add a note to capture what went well or what needs improvement.

  Scores and notes stay internal to your team, making it easy to track agent quality over time and share context during reviews.

  <img src="https://mintcdn.com/bolna-54a2d4fe/bVfXF_bNzzamm1Mi/images/changelog/29_april_2026_conversation_rating.png?fit=max&auto=format&n=bVfXF_bNzzamm1Mi&q=85&s=fdb1201dc982ca24330ef0e209f55013" alt="Conversation rating dialog" width="986" height="546" data-path="images/changelog/29_april_2026_conversation_rating.png" />
</Update>

<Update label="22nd April, 2026">
  ## Import custom functions from cURL

  You can now paste a `curl` request while creating a custom function in the **Tools** tab and use it to generate a draft configuration automatically. This makes it much faster to bring existing API requests into Bolna without rebuilding the function setup from scratch.

  Learn more in the [Custom Functions documentation](/docs/tool-calling/custom-function-calls#import-from-curl).
</Update>

<Update label="15th April, 2026">
  ## LLM reasoning in execution logs

  The [Get execution raw logs](/docs/api-reference/executions/get_execution_raw_logs) API now includes optional **`reasoning_content`** on LLM response rows when the underlying model returns traceable reasoning (for example OpenAI reasoning summaries or Gemini thinking). It appears alongside the usual **`data`** field for assistant turns.

  In the dashboard, use **Call history → Trace Data** ([Call history](/docs/agent-setup/call-history)) to inspect execution logs while debugging.
</Update>

<Update label="14th April, 2026">
  ## Extraction Confidence, Reasoning & Typed Responses

  Extraction results now include richer signal to help you trust and act on post-call data:

  * **Confidence score** — every extraction result carries a `confidence` score (0.0–1.0) and a `confidence_label` (`"High"` ≥ 0.8, `"Medium"` ≥ 0.5, `"Low"` \< 0.5). Use these to route low-confidence results for human review before pushing data downstream.
  * **Reasoning** — `reasoning_subjective` and `reasoning_objective` explain exactly why the LLM produced each answer, making it much easier to audit unexpected results.
  * **Expected Format for free text** — you can now constrain free-text responses to a specific type: `timestamp` (ISO 8601), `numeric`, `boolean`, `email`, or a **custom regex** pattern. Responses are validated post-LLM; mismatches are flagged in a `validation` field while the original answer is still preserved.

  ```json theme={"system"}
  {
    "subjective": "user@example.com",
    "objective": null,
    "confidence": 0.95,
    "confidence_label": "High",
    "reasoning_subjective": "Customer clearly provided their email address during the call.",
    "validation": { "is_valid": true, "expected_type": "email" }
  }
  ```

  Learn more in the [Using Extractions documentation](/docs/guides/prompting/using-extractions) and [Dispositions API reference](/docs/api-reference/dispositions/overview).
</Update>

<Update label="14th April, 2026">
  ## Multilingual Agent Support

  You can now launch multilingual agents with language-specific configuration across prompts, speech recognition, and text-to-speech. This makes it easier to set up agents that can operate cleanly across multiple languages from a single workflow.

  Learn more in the [Multilingual voice agents documentation](/docs/customizations/multilingual-languages-support).
</Update>

<Update label="13th April, 2026">
  ## Region-Based Indian Phone Number Search

  You can now search Indian phone numbers by region directly in the dashboard. This makes it easier to find numbers for a specific geography.

  Learn more in the [Phone Numbers API documentation](/docs/api-reference/phone-numbers/search).
</Update>

<Update label="7th April, 2026">
  ## Unified Voice Configuration in Agent Setup

  You can now configure TTS voices from a single place in agent setup with a unified selector for provider, model, and voice. This makes it easier to find and apply the right voice without jumping across multiple controls.

  The updated voice selector includes:

  * Search across available voices by name
  * Gender filters for `male`, `female`, and `neutral` voices
  * Inline voice sample playback while selecting a voice

  Learn more in the [Audio Tab documentation](/docs/agent-setup/audio-tab).
</Update>
