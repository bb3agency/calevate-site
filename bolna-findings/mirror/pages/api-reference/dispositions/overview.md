> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Dispositions API Overview

> Create and manage dispositions — the individual extraction units that power the Extractions feature in Bolna.

## What are Dispositions?

**Extractions** is the Bolna feature that automatically captures structured data from call transcripts after every call. Each extraction is configured as one or more **dispositions** — individual questions posed to an LLM against the transcript — grouped under named **categories**.

So the hierarchy is:

```
Agent
└── Extractions (feature)
    └── Category  (e.g. "Lead Quality")
        └── Disposition  (e.g. "Call Outcome")
```

Each disposition asks a single question and returns a **Free Text** response (`subjective`), a **Pre-defined** value selected from options you configure (`objective`), or both.

## Key Features

* **Organized by category**: Dispositions are grouped under categories, which appear as sections in the extraction results
* **Two answer types**: Free Text (`is_subjective`) and Pre-defined (`is_objective`), configurable independently or together
* **Typed free-text responses**: Constrain free-text answers to a specific format — `timestamp`, `numeric`, `boolean`, `email`, or a custom `regex` pattern — with automatic post-LLM validation
* **Confidence & reasoning**: Every result includes a confidence score (0.0–1.0) and an explanation of why the LLM produced that answer
* **Bulk creation**: Create and link multiple dispositions to an agent atomically in a single request
* **Copy-on-write updates**: Editing a shared disposition via a scoped agent automatically creates a private copy, keeping other agents unaffected
* **Model selection**: Choose the LLM model used for evaluation per disposition

## Endpoints

```
GET    /dispositions/                           List dispositions
GET    /dispositions/{disposition_id}           Get a single disposition
POST   /dispositions/                           Create a disposition
POST   /dispositions/bulk                       Bulk-create dispositions for an agent
PUT    /dispositions/{disposition_id}           Update a disposition (copy-on-write aware)
DELETE /dispositions/{disposition_id}           Delete a disposition
POST   /v2/agent/{agent_id}/dispositions/test   Test all dispositions for an agent against a transcript
```

## Disposition Object

```json theme={"system"}
{
  "id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "name": "Call Outcome",
  "question": "What was the outcome of the call?",
  "system_prompt": "You are analyzing a sales call transcript.",
  "category": "Lead Quality",
  "model": "gpt-4.1-mini",
  "is_subjective": true,
  "is_objective": true,
  "subjective_type": "text",
  "subjective_type_config": null,
  "objective_options": [
    { "value": "interested", "condition": "Customer expressed genuine interest and agreed to a next step" },
    { "value": "not_interested", "condition": "Customer declined all proposals" },
    { "value": "follow_up", "condition": "Customer asked to be contacted again later" }
  ],
  "agent_ids": ["agt_abc123"],
  "created_by": "user_abc123",
  "created_at": "2026-03-01T10:00:00Z",
  "updated_at": "2026-03-15T14:30:00Z"
}
```

### Field Reference

| Field                    | Type           | Description                                                                                                         |
| ------------------------ | -------------- | ------------------------------------------------------------------------------------------------------------------- |
| `id`                     | UUID           | Unique identifier                                                                                                   |
| `name`                   | string         | Display name shown in extraction results                                                                            |
| `question`               | string         | The prompt sent to the LLM to evaluate the transcript                                                               |
| `system_prompt`          | string         | System context for the LLM (optional)                                                                               |
| `category`               | string         | Category this disposition belongs to (default: `"General"`)                                                         |
| `model`                  | string         | LLM used for evaluation (default: `"gpt-4.1-mini"`)                                                                 |
| `is_subjective`          | bool           | Enable Free Text response                                                                                           |
| `is_objective`           | bool           | Enable Pre-defined value selection                                                                                  |
| `subjective_type`        | string         | Format constraint for free-text responses: `text` (default), `timestamp`, `numeric`, `boolean`, `email`, or `regex` |
| `subjective_type_config` | object \| null | Configuration for `regex` subjective type. Must include `pattern` (required) and optionally `description`           |
| `objective_options`      | array \| null  | Required when `is_objective` is `true`                                                                              |
| `agent_ids`              | array          | Agent IDs this disposition is linked to                                                                             |
| `created_by`             | string         | ID of the user who created this disposition                                                                         |
| `created_at`             | string         | ISO 8601 timestamp when the disposition was created                                                                 |
| `updated_at`             | string         | ISO 8601 timestamp of the last update                                                                               |

### ObjectiveOption Schema

```json theme={"system"}
{
  "value": "interested",
  "condition": "Customer expressed genuine interest and agreed to a next step",
  "sub_options": []
}
```

`sub_options` is optional and supports the same recursive `ObjectiveOption` structure for hierarchical classifications.

<Note>
  For a full walkthrough of the Extractions feature, answer types, output format, and best practices, see the [Using Extractions](/docs/guides/prompting/using-extractions) guide.
</Note>
