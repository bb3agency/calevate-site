> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Fetch Agent Executions using APIs

> Sample Python guide demonstrating how to query and paginate through agent executions, with support for filters, logging, and best practices.

## API Endpoint Overview

### Endpoint

[Agent Executions API](/docs/api-reference/executions/get_executions) - Fetches executions for a specified `agent_id`.

### Request Details

* **Path Parameters**
  * `agent_id` (UUID, required): The ID of your agent.
* **Query Parameters** (all optional unless noted):
  * `page_number` (integer, default 1): Page index, starting at 1. Must be ≥ 1.
  * `page_size` (integer, default 20, max 50): Results per request.
  * **Filters**:
    * `status` (enum): Filter by execution status (`scheduled`, `queued`, `in-progress`, `completed`, `failed`, etc.)
    * `call_type` (enum): `inbound` or `outbound`
    * `provider` (enum): e.g., `twilio`, `plivo`, `websocket`, `web-call`
    * `answered_by_voice_mail` (boolean): Filter calls answered by voicemail
    * `batch_id` (string): Narrow results by batch
    * `from` (string, date-time): Filter by starting timestamp
    * `to` (string, date-time): Filter by ending timestamp

### Authorization

Include your API key as a Bearer token in the header:

```http theme={"system"}
Authorization: Bearer <api_key>
```

***

## Example Python Code

```python theme={"system"}
import aiohttp
import time

all_executions = []
page_number = 1
agent_id = "<your_agent_id>" # your agent_id
api_key = "<your_api_key>"  # your Bolna API key

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json"
}

async with aiohttp.ClientSession(headers=headers) as session:
    while True:
        ts_start = time.time() * 1000
        print(f"Starting fetch for page {page_number} at {ts_start:.0f} ms")

        url = f"https://api.bolna.ai/v2/agent/{agent_id}/executions?page_size=50&page_number={page_number}"
        async with session.get(url) as resp:
            status_code = resp.status
            res = await resp.json()

        ts_end = time.time() * 1000
        print(f"Fetched page {page_number} in {ts_end - ts_start:.2f} ms")

        if status_code != 200:
            logger.error(f"Error fetching page {page_number}: status {status_code}")
            break

        page = res.get("data", [])
        all_executions.extend(page)

        if res.get("has_more", False):
            page_number += 1
        else:
            print("Completed fetching all executions")
            break
```

***

## Why This Matters

| Benefit                    | Description                                                                 |
| -------------------------- | --------------------------------------------------------------------------- |
| **Complete History**       | Retrieve full call/execution logs for audits, analytics, or dashboards.     |
| **Filtering & Efficiency** | Use filters to slice data by status, provider, call type, date, batch, etc. |

***

## Quick FAQs

### How do I fetch all executions for a Bolna agent?

Use the endpoint `/v2/agent/{agent_id}/executions` with pagination and keep fetching while `has_more == true`.

### Can I filter executions by provider or call type?

Yes, you can use query parameters like `provider=twilio`, `call_type=inbound`, `status=completed` and more.

### What is the max page size?

`50` results per page is the maximum allowed. Default is `20`.

### How are extracted fields returned?

In your response under `extracted_data`, with your custom JSON fields—based on your Extraction prompt setup.

***
