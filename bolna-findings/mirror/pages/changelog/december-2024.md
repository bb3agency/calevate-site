> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for December, 2024

> Explore the latest features, improvements, and API updates introduced in December 2024 for Bolna Voice AI agents.

<Update label="24th December, 2024">
  ## Batch Management Enhancements

  * Download batches that have been uploaded
  * Display batch call status breakdown for better tracking

  ## API Updates

  * Batches APIs - Added breakdown for batches executions ([API doc](/docs/api-reference/batches/get_batch))
</Update>

<Update label="18th December, 2024">
  ## New Features

  * Added Cartesia TTS support for voice synthesis
  * Implemented voicemail detection for Twilio & Plivo calls
  * Enabled call hangup using prompts (see [hangup live calls on Bolna](/docs/guides/outbound/hangup-calls))
  * Introduced multi-agent prompt building (see [multi-agent prompt](/docs/multi-agent-prompt))
</Update>

<Update label="10th December, 2024">
  ## Major Platform Updates

  * Added support for over 40+ languages (see [supported languages](/docs/customizations/multilingual-languages-support))
  * Knowledgebases are now functional in all supported languages and work together with LLM-driven context (see [ingesting and using KBs](/docs/getting-started/knowledge-base))
  * Revamped batches for simpler processing and management (see [using batches](/docs/guides/outbound/batch-calling))
  * Added call hangup information for all calls

  ## Improvements & Migrations

  * Changed `execution_id` notation from `{agent_id}#{timestamp}` to a unique `{uuid}` format.
  * The execution ID overhaul addresses previous scaling issues and product complications.

  ## API Updates

  #### New APIs

  * Get call details using only `execution_id` ([API doc](/docs/api-reference/executions/get_execution))
  * Set inbound agent programmatically ([API doc](/docs/api-reference/inbound/agent))
  * Get a list of all added voices for your account ([API doc](/docs/api-reference/voice/get_all))

  #### API changes

  * Call APIs - Outbound calls will now return the unique `execution_id` ([API doc](/docs/api-reference/calls/make))
  * Batches APIs - removed redundant need of `agent_id` wherever applicable ([API doc](/docs/api-reference/batches/overview))
  * Execution APIs - removed redundant need of `agent_id` wherever applicable ([API doc](/docs/api-reference/executions/overview))
</Update>
