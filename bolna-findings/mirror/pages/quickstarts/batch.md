> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Batch Calling Quickstart

> Call a list of people in one campaign — upload a CSV of recipients with per-row variables, schedule the batch, and fetch every call's result.

The [API Quickstart](/docs/quickstarts/api) makes one call. This guide scales that to a **campaign**: upload a CSV of recipients (each with their own variables), schedule the batch, and pull back per-call results. It reuses the agent and execution concepts from the outbound quickstart, so start there if you haven't.

<Info>
  You'll need an `agent_id` (see the [API Quickstart](/docs/quickstarts/api)) and enough wallet balance for the number of rows in your CSV.
</Info>

## Prerequisites

* `export BOLNA_API_KEY="bn-xxxx"` and `export BOLNA_AGENT_ID="your-agent-id"`
* A CSV with a **`contact_number`** column (required). Any other columns become `{variable}` values your prompt and welcome message can use.

<Tip>
  Reference CSV columns in the [Agent Tab](/docs/agent-setup/agent-tab) with `{column_name}` — e.g. a `customer_name` column lets your welcome message say "Hi {customer_name}".
</Tip>

## The CSV

```csv batch.csv theme={"system"}
contact_number,customer_name,appointment_day
+919876543210,Asha,Friday
+919812345678,Ravi,Monday
```

Only `contact_number` is mandatory; `customer_name` and `appointment_day` are example variables.

<Steps>
  <Step title="Create the batch">
    Upload the CSV with your `agent_id` as `multipart/form-data`.

    <CodeGroup>
      ```bash curl theme={"system"}
      curl https://api.bolna.ai/batches \
        -H "Authorization: Bearer $BOLNA_API_KEY" \
        -F "agent_id=$BOLNA_AGENT_ID" \
        -F "file=@batch.csv"
      ```

      ```python Python theme={"system"}
      import os, requests   # pip install requests, or see the stdlib script below
      r = requests.post(
          "https://api.bolna.ai/batches",
          headers={"Authorization": f"Bearer {os.environ['BOLNA_API_KEY']}"},
          data={"agent_id": os.environ["BOLNA_AGENT_ID"]},
          files={"file": ("batch.csv", open("batch.csv", "rb"), "text/csv")},
      )
      print(r.status_code, r.json())
      ```
    </CodeGroup>

    ```json Response theme={"system"}
    // HTTP 201 Created
    { "batch_id": "abcdefghijklmnopqrstuvwxyz012345", "state": "created" }
    ```

    Save the `batch_id`.
  </Step>

  <Step title="Schedule the batch">
    A created batch doesn't call anyone until it's scheduled. Pass `scheduled_at` as an **ISO 8601 timestamp with a numeric UTC offset** (e.g. `+00:00`). Two API rules that aren't obvious:

    * The time must be **at least 2 minutes in the future**, or you get a `400`.
    * Use a numeric offset like `+00:00` — the `Z` suffix is **rejected** with a `500`.
    * Bolna **rounds the start up to the next 10-minute mark**, so a `12:02` request runs at `12:10`.

    <CodeGroup>
      ```bash curl theme={"system"}
      curl https://api.bolna.ai/batches/BATCH_ID/schedule \
        -H "Authorization: Bearer $BOLNA_API_KEY" \
        -F "scheduled_at=2026-06-23T18:30:00+00:00"
      ```

      ```python Python theme={"system"}
      import os, requests
      from datetime import datetime, timezone, timedelta

      # isoformat() emits the +00:00 offset the API expects; min 2 minutes out
      when = (datetime.now(timezone.utc) + timedelta(minutes=3)).replace(microsecond=0).isoformat()
      r = requests.post(
          f"https://api.bolna.ai/batches/{os.environ['BATCH_ID']}/schedule",
          headers={"Authorization": f"Bearer {os.environ['BOLNA_API_KEY']}"},
          data={"scheduled_at": when},
      )
      print(r.status_code, r.json())
      ```
    </CodeGroup>

    ```json Response theme={"system"}
    { "message": "success", "state": "scheduled at 2026-06-23T07:00:00+00:00" }
    ```

    <Warning>
      Outbound time-of-day restrictions still apply per recipient timezone. If a scheduled time falls outside the allowed window, calls are pushed to the next allowed slot. See [Calling Guardrails](/docs/guides/outbound/calling-guardrails).
    </Warning>
  </Step>

  <Step title="Track progress">
    Poll the batch for its status, then list per-call executions once it's running or done.

    <CodeGroup>
      ```bash status theme={"system"}
      curl https://api.bolna.ai/batches/BATCH_ID \
        -H "Authorization: Bearer $BOLNA_API_KEY"
      ```

      ```bash executions theme={"system"}
      curl https://api.bolna.ai/batches/BATCH_ID/executions \
        -H "Authorization: Bearer $BOLNA_API_KEY"
      ```
    </CodeGroup>

    Each execution in the list is a standard [execution object](/docs/api-reference/executions/get_execution) — `status`, `transcript`, `total_cost`, `telephony_data`, `extracted_data`, etc. — one per row in your CSV. The batch object tracks overall progress; `status` moves `created → scheduled → running → completed`.

    ```json GET /batches/{batch_id} theme={"system"}
    {
      "batch_id": "c4e37bb6…",
      "status": "running",
      "scheduled_at": "2026-06-23T07:00:00+00:00",
      "valid_contacts": 1,
      "total_contacts": 1,
      "file_name": "batch.csv",
      "execution_status": { "completed": 1 }
    }
    ```

    ```json GET /batches/{batch_id}/executions  (bare array) theme={"system"}
    [
      {
        "id": "1ae3e573-…",
        "status": "completed",
        "user_number": "+919876543210",
        "conversation_duration": 18.0,
        "total_cost": 3.26,
        "transcript": "assistant: Hi! …",
        "context_details": {
          "recipient_data": { "customer_name": "Asha", "appointment_day": "Friday" }
        },
        "telephony_data": { "recording_url": "https://api.bolna.ai/recordings/call/1ae3e573-…" }
      }
    ]
    ```

    <Note>
      The execution's `context_details.recipient_data` echoes back the CSV columns for that row — confirming your `{variables}` reached the call. Per-call `status` starts at `prepared` before the call is placed, then becomes `completed` (or `no-answer`, `busy`, `failed`).
    </Note>
  </Step>
</Steps>

## Run the whole flow as one script

The dependency-free `bolna_batch_test.py` script does all of the above — builds a sample CSV (or takes your own), creates the batch, schedules it, polls, and prints per-call results:

```bash theme={"system"}
export BOLNA_API_KEY="bn-xxxx"
export BOLNA_AGENT_ID="your-agent-id"

python3 bolna_batch_test.py --dry-run --to "+919876543210" --name "Asha"   # inspect first
python3 bolna_batch_test.py --to "+919876543210" --name "Asha"             # real campaign
python3 bolna_batch_test.py --csv my-recipients.csv                        # your own list
```

## Managing batches

| Action                        | Endpoint                             |
| ----------------------------- | ------------------------------------ |
| Stop a running batch          | `POST /batches/{batch_id}/stop`      |
| Get one batch                 | `GET /batches/{batch_id}`            |
| List a batch's calls          | `GET /batches/{batch_id}/executions` |
| List all batches for an agent | `GET /batches/{agent_id}/all`        |
| Delete a batch                | `DELETE /batches/{batch_id}`         |

## Next steps

<CardGroup cols={2}>
  <Card title="Personalize each call" icon="brackets-curly" href="/docs/guides/prompting/using-context">
    Use CSV columns as `{variables}` in your prompt and welcome message.
  </Card>

  <Card title="Receive results via webhook" icon="webhook" href="/docs/guides/post-call/polling-call-status-webhooks">
    Get each call's payload pushed to you instead of polling.
  </Card>

  <Card title="Extract structured data" icon="table-list" href="/docs/guides/prompting/using-extractions">
    Auto-capture lead quality, outcomes, and more from every call.
  </Card>

  <Card title="Single calls" icon="phone" href="/docs/quickstarts/api">
    The outbound quickstart this builds on.
  </Card>
</CardGroup>
