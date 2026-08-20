> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for March, 2025

> Explore the latest features, improvements, and API updates introduced in March 2025 for Bolna Voice AI agents.

<Update label="31st March, 2025">
  ## Improvements

  * Enabling `strict` mode for custom tools to ensure function calls reliably adhere to the function schema, instead of being best effort.
  * Updating the UI for the custom tools and improving the [documentation with examples](/docs/tool-calling/custom-function-calls).
</Update>

<Update label="22nd March, 2025">
  ## Dynamic Caller Identification

  * Bolna Voice AI agents can now dynamically identify incoming callers in real time via:
    1. using [your internal APIs](/docs/customizations/identify-incoming-callers#1-internal-api-integration-real-time-lookup) which returns records mapped to a phone number,
    2. using uploaded [CSV files](/docs/customizations/identify-incoming-callers#2-csv-uploads) or
    3. using publicly linked [Google Sheets](/docs/customizations/identify-incoming-callers#3-google-sheets-integration).
</Update>

<Update label="18th March, 2025">
  ## Azure Transcriber Support

  * Added Azure's transcriber models for speech to text.
</Update>

<Update label="14th March, 2025">
  ## Improvements

  * Infrastructure changes & updates to improve initial conversational latencies.
</Update>

<Update label="9th March, 2025">
  ## Bolna Status Page Launch

  * Launched the [Bolna Status page](https://status.bolna.ai) where you can track real-time system updates, maintenance notices, and any ongoing outage updates.
</Update>

<Update label="7th March, 2025">
  ## Bug fixes

  * Bolna Voice AI agents will now have the context about current `timestamp` & `timezone` automatically by default which can be used. This helps the agent compute times accurately based on your local setting.
  * This can be [overridden](/docs/using-context#injecting-current-time) by passing the `timezone` as well.
</Update>
