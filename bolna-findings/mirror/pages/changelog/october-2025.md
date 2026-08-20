> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Bolna AI Updates for October, 2025

> Explore the latest features, improvements, and API updates introduced in October 2025 for Bolna Voice AI agents.

<Update label="29th Oct, 2025">
  ## Stop Agent Queued Calls API

  * Introducing a new API endpoint to stop all queued calls for a specific agent
  * Prevents any pending calls from being executed, giving you better control over agent call management
  * Use this endpoint to cancel all calls currently in the queue waiting to be executed
  * Useful for scenarios where you need to immediately halt all pending operations for an agent
  * Learn more in the [Stop Agent Queued Calls API documentation](/docs/api-reference/agent/v2/stop)
</Update>

<Update label="28th Oct, 2025">
  ## Unsiloed Document Parser Integration

  * Integrated [Unsiloed](https://unsiloed.ai) as the parsing engine for knowledgebase PDFs, alongwith [LlamaParse](https://www.llamaindex.ai/llamaparse) as fallback.
  * Significantly improved accuracy for documents with complex tables, forms, and structured data
  * Uses UnsiloedHawk OCR engine with semantic layout detection for better text extraction
  * High-resolution processing ensures accurate capture of details from charts, diagrams, and small text
  * Learn more in the [Knowledgebases documentation](/docs/getting-started/knowledge-base)
</Update>

<Update label="20th Oct, 2025">
  ## Cartesia Sonic-3-Preview Model Support for Indian multilingual voices

  * Added support for Cartesia's latest `sonic-3-preview` text-to-speech model including support for the following languages:
    | Language  | Language code | BCP Format |
    | --------- | ------------- | ---------- |
    | English   | en            | bn-IN      |
    | Bengali   | bn            | bn-IN      |
    | Gujarati  | gu            | gu-IN      |
    | Hindi     | hi            | hi-IN      |
    | Kannada   | kn            | kn-IN      |
    | Malayalam | ml            | ml-IN      |
    | Marathi   | mr            | mr-IN      |
    | Punjabi   | pa            | pa-IN      |
    | Tamil     | ta            | ta-IN      |
    | Telugu    | te            | te-IN      |

  * Enhanced voice quality and naturalness for AI voice agents using Cartesia TTS

  * The `sonic-3-preview` model delivers improved expressiveness and prosody for conversational AI applications

  * Available for all Cartesia TTS integrations in Bolna voice agents

  * Learn more in the [Cartesia TTS documentation](/docs/providers/voice/cartesia)
</Update>

<Update label="15th Oct, 2025">
  ## Exotel Telephony Integration

  * Introducing native Exotel integration for Voice AI calling in India and global markets
  * Connect your existing Exotel account securely to Bolna for complete control over your telephony infrastructure
  * Make outbound AI calls and receive inbound calls using your own Exotel phone numbers
  * Support for both dashboard-based calling and programmatic API integration
  * Learn more in the [Exotel integration documentation](/docs/exotel)
</Update>

<Update label="7th Oct, 2025">
  ## Remove Inbound Agent API

  * Introducing the ability to programmatically remove and unlink Bolna Voice AI agents from phone numbers
  * Use this API to remove the association between an agent and a phone number when the agent is no longer needed for handling inbound calls
  * Learn more in the [Remove Inbound Agent API documentation](/docs/api-reference/inbound/unlink)
</Update>

<Update label="5th Oct, 2025">
  ## RAG Performance & Accuracy Improvements

  * **ONNX-optimized reranking**: Sub-second query times with parallel execution for faster, more accurate document retrieval
  * **MPNet embeddings**: Switched to `all-mpnet-base-v2` model for better semantic understanding of user queries
  * **Table extraction**: Specialized processor preserves table structure, numeric data, and formatting from PDFs
  * **Multi-collection queries**: Agents can now search across multiple knowledgebases simultaneously for comprehensive context
  * Learn more in the [Knowledgebases documentation](/docs/getting-started/knowledge-base)
</Update>

<Update label="2nd Oct, 2025">
  ## Sub-account Deletion API

  * Introducing the ability to programmatically delete sub-accounts and all their associated data through the API
  * The Sub-account Deletion API enables better account lifecycle management by allowing you to:
    * Remove test or development sub-accounts that are no longer needed
    * Clean up sub-accounts for clients who have churned or ended their service
    * Maintain a clean organizational structure by removing inactive sub-accounts
  * When a sub-account is deleted, **ALL** associated data is permanently removed, including:
    * All agents configured under that sub-account
    * All batch calling data and records
    * All execution history and call logs
    * All configurations and settings
  * Learn more in the [Sub-account Deletion API documentation](/docs/api-reference/sub-accounts/delete)
</Update>
