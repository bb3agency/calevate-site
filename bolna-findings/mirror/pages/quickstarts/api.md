> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# API Quickstart

> Make your first Voice AI call with the Bolna API — verify your key, get an agent, place a call, and fetch the transcript in about five minutes.

Go from an API key to a real phone call (with a transcript and recording) in four steps. Every request below uses the production base URL `https://api.bolna.ai` and Bearer authentication.

<Info>
  Don't have a key yet? Follow [Generate an API key](/docs/api-reference/introduction) first, then come back here. Telephone calls consume wallet credits, so keep a test number handy.
</Info>

## Prerequisites

* A Bolna API key (`Authorization: Bearer <key>`)
* A recipient phone number in [E.164](https://en.wikipedia.org/wiki/E.164) format, e.g. `+919876543210`
* `curl`, or Python 3, or Node 18+

Set your key as an environment variable so it's not pasted into every command:

```bash theme={"system"}
export BOLNA_API_KEY="bn-xxxxxxxxxxxxxxxx"
```

<Steps>
  <Step title="Verify your API key">
    A quick read-only call confirms the key works and shows your wallet balance and concurrency limit before you spend any credits.

    <CodeGroup>
      ```bash curl theme={"system"}
      curl https://api.bolna.ai/user/me \
        -H "Authorization: Bearer $BOLNA_API_KEY"
      ```

      ```python Python theme={"system"}
      import os, urllib.request, json

      key = os.environ["BOLNA_API_KEY"]
      req = urllib.request.Request(
          "https://api.bolna.ai/user/me",
          headers={"Authorization": f"Bearer {key}"},
      )
      print(json.load(urllib.request.urlopen(req)))
      ```

      ```javascript Node theme={"system"}
      const res = await fetch("https://api.bolna.ai/user/me", {
        headers: { Authorization: `Bearer ${process.env.BOLNA_API_KEY}` },
      });
      console.log(await res.json());
      ```
    </CodeGroup>

    A successful response returns your account details:

    ```json theme={"system"}
    {
      "id": "…",
      "name": "Bruce Wayne",
      "email": "bruce@example.com",
      "wallet": 42.42,
      "concurrency": { "max": 10, "current": 0 }
    }
    ```

    <Tip>
      A `401 Access denied` means the key is wrong or missing the `Bearer ` prefix.
    </Tip>
  </Step>

  <Step title="Get an agent ID">
    You need an `agent_id` to make a call. Pick one path:

    <Tabs>
      <Tab title="Use an existing agent (fastest)">
        Create an agent once in the [dashboard](https://platform.bolna.ai) (Auto Build is quickest), open it, and copy the agent ID from the URL or the agent settings. Then:

        ```bash theme={"system"}
        export BOLNA_AGENT_ID="your-agent-id"
        ```

        This is the most reliable way to finish the quickstart, because the full agent configuration is large.
      </Tab>

      <Tab title="Create an agent via API">
        Create a minimal English conversation agent programmatically. This body is intentionally complete so it works on default providers — adjust providers, voice, and language as needed.

        <CodeGroup>
          ```bash curl theme={"system"}
          curl https://api.bolna.ai/v2/agent \
            -H "Authorization: Bearer $BOLNA_API_KEY" \
            -H "Content-Type: application/json" \
            -d '{
              "agent_config": {
                "agent_name": "Quickstart Agent",
                "agent_welcome_message": "Hi! This is a quick test call from Bolna. How is your day going?",
                "tasks": [{
                  "task_type": "conversation",
                  "toolchain": { "execution": "sequential", "pipelines": [["transcriber","llm","synthesizer"]] },
                  "tools_config": {
                    "llm_agent": {
                      "agent_type": "simple_llm_agent",
                      "agent_flow_type": "streaming",
                      "llm_config": { "provider": "openai", "model": "gpt-4.1-mini", "max_tokens": 150, "temperature": 0.2 }
                    },
                    "synthesizer": {
                      "provider": "elevenlabs",
                      "provider_config": { "voice": "Nila", "voice_id": "V9LCAAi4tTlqe9JadbCo", "model": "eleven_turbo_v2_5" },
                      "stream": true, "buffer_size": 250, "audio_format": "wav"
                    },
                    "transcriber": { "provider": "deepgram", "model": "nova-3", "language": "en", "stream": true, "encoding": "linear16", "sampling_rate": 16000, "endpointing": 250 },
                    "input": { "provider": "plivo", "format": "wav" },
                    "output": { "provider": "plivo", "format": "wav" }
                  },
                  "task_config": { "call_terminate": 90, "hangup_after_silence": 10 }
                }]
              },
              "agent_prompts": {
                "task_1": { "system_prompt": "You are a friendly assistant making a short test call. Keep every reply under two sentences. Greet the person, ask how their day is going, thank them, then end the call politely." }
              }
            }'
          ```

          ```json Response theme={"system"}
          // HTTP 201 Created
          { "agent_id": "123e4567-e89b-12d3-a456-426655440000", "state": "created" }
          ```
        </CodeGroup>

        Save the returned `agent_id` for the next step.
      </Tab>
    </Tabs>
  </Step>

  <Step title="Place the call">
    Pass your `agent_id` and the recipient's number. Omit `from_phone_number` to use Bolna's default number, or set it to one of your purchased numbers.

    <CodeGroup>
      ```bash curl theme={"system"}
      curl https://api.bolna.ai/call \
        -H "Authorization: Bearer $BOLNA_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{
          "agent_id": "'"$BOLNA_AGENT_ID"'",
          "recipient_phone_number": "+919876543210"
        }'
      ```

      ```python Python theme={"system"}
      import os, urllib.request, json

      body = json.dumps({
          "agent_id": os.environ["BOLNA_AGENT_ID"],
          "recipient_phone_number": "+919876543210",
      }).encode()
      req = urllib.request.Request(
          "https://api.bolna.ai/call",
          data=body,
          headers={"Authorization": f"Bearer {os.environ['BOLNA_API_KEY']}",
                   "Content-Type": "application/json"},
      )
      print(json.load(urllib.request.urlopen(req)))
      ```

      ```javascript Node theme={"system"}
      const res = await fetch("https://api.bolna.ai/call", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${process.env.BOLNA_API_KEY}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          agent_id: process.env.BOLNA_AGENT_ID,
          recipient_phone_number: "+919876543210",
        }),
      });
      console.log(await res.json());
      ```
    </CodeGroup>

    The response returns an `execution_id` you'll use to track the call:

    ```json theme={"system"}
    { "message": "done", "status": "queued", "execution_id": "123e4567-e89b-12d3-a456-426614174000" }
    ```

    Your phone should ring within a few seconds.
  </Step>

  <Step title="Fetch the result">
    Poll the execution until it finishes. Bolna fires a `call-disconnected` event the instant the line drops, then a final `completed` event a few seconds later once duration, cost, recording, and the AI call summary are finalized — so **wait for `completed`** (or a hard-failure status like `no-answer`, `busy`, `failed`) rather than stopping at `call-disconnected`, or you'll read a half-populated payload with `conversation_duration: 0`. The completed execution includes the full transcript, recording URL, duration, cost breakdown, and `extracted_data`.

    <CodeGroup>
      ```bash curl theme={"system"}
      curl https://api.bolna.ai/executions/EXECUTION_ID \
        -H "Authorization: Bearer $BOLNA_API_KEY"
      ```

      ```python Python theme={"system"}
      import os, time, urllib.request, json

      key = os.environ["BOLNA_API_KEY"]
      exec_id = "EXECUTION_ID"
      final = {"completed","no-answer","busy","failed","canceled","stopped","error","balance-low"}

      while True:
          req = urllib.request.Request(
              f"https://api.bolna.ai/executions/{exec_id}",
              headers={"Authorization": f"Bearer {key}"},
          )
          data = json.load(urllib.request.urlopen(req))
          print("status:", data["status"])
          if data["status"] in final:          # wait for 'completed', not 'call-disconnected'
              print(data.get("transcript"))
              break
          time.sleep(5)
      ```

      ```javascript Node theme={"system"}
      const key = process.env.BOLNA_API_KEY;
      const execId = "EXECUTION_ID";
      const final = new Set(["completed","no-answer","busy","failed","canceled","stopped","error","balance-low"]);

      while (true) {
        const res = await fetch(`https://api.bolna.ai/executions/${execId}`, {
          headers: { Authorization: `Bearer ${key}` },
        });
        const data = await res.json();
        console.log("status:", data.status);
        if (final.has(data.status)) { console.log(data.transcript); break; }  // not call-disconnected
        await new Promise(r => setTimeout(r, 5000));
      }
      ```
    </CodeGroup>

    ```json Completed execution (truncated) theme={"system"}
    {
      "id": "b7140255-af33-4608-8e97-04dd944b8e48",
      "agent_id": "5bc97541-e320-4d95-a3a5-242cfe45621d",
      "status": "completed",
      "conversation_duration": 16,
      "total_cost": 3.23,
      "transcript": "assistant: Hi! How is your day going?\nuser: …",
      "user_number": "+919876543210",
      "agent_number": "+918035739222",
      "extracted_data": { "General": { "Call Summary": { "subjective": "…", "confidence_label": "High" } } },
      "telephony_data": {
        "duration": 16,
        "recording_url": "https://api.bolna.ai/recordings/call/b7140255-af33-4608-8e97-04dd944b8e48",
        "call_type": "outbound",
        "provider": "plivo",
        "hangup_by": "Plivo",
        "hangup_reason": "inactivity_timeout",
        "to_number_carrier": "Bharat Sanchar Nigam Ltd (BSNL)"
      },
      "cost_breakdown": { "platform": 2, "network": 1, "transcriber": 0.23, "llm": 0, "synthesizer": 0 },
      "latency_data": { "time_to_first_audio": 189.69 }
    }
    ```

    <Tip>
      For production, don't poll — register a [webhook](/docs/guides/post-call/polling-call-status-webhooks) to receive the execution payload automatically when the call ends.
    </Tip>
  </Step>
</Steps>

## Alternative: receive results via webhook

Polling is fine for a quickstart, but in production you don't want to hammer the API. Instead, give your agent a `webhook_url` and Bolna will **POST the execution payload to your server** as the call progresses — same JSON shape as Step 4.

<Steps>
  <Step title="Stand up a public endpoint">
    Your endpoint must be publicly reachable over HTTPS and return `200` quickly. For local testing, run a small receiver and expose it with a tunnel:

    ```bash theme={"system"}
    python3 bolna_webhook_server.py          # listens on :8080, prints every payload
    ngrok http 8080                          # gives you https://<id>.ngrok.app
    ```

    <Warning>
      Bolna sends webhooks from a fixed set of IPs — **whitelist `13.203.39.153`, `13.126.9.249` and `13.202.133.53`** on your server or firewall so events aren't dropped.
    </Warning>
  </Step>

  <Step title="Attach the webhook to your agent">
    Set `webhook_url` inside `agent_config` when creating (or updating) the agent. With the test harness:

    ```bash theme={"system"}
    python3 bolna_quickstart_test.py --to "+919876543210" \
      --webhook-url "https://<id>.ngrok.app/webhook"
    ```

    Or set it in the dashboard under the [Extractions Tab](/docs/agent-setup/analytics-tab) — "Push all execution data to webhook".
  </Step>

  <Step title="Place the call and watch the events arrive">
    Make the call as in Step 3. Your endpoint receives a POST each time the status changes (`queued → in-progress → completed/call-disconnected`), with the full transcript on the final event.
  </Step>
</Steps>

<Note>
  Bolna sends **several POSTs per call** as the status changes. Two land near the end: `call-disconnected` fires the instant the line drops (with `conversation_duration: 0`, no recording, no summary), then `completed` arrives a few seconds later with the finalized duration, cost, `recording_url`, and `extracted_data`. **Treat `completed` as "call is done"** — along with hard-failure statuses (`no-answer`, `busy`, `failed`). The same URL may also receive in-progress / pre-call webhooks; tell them apart by `status`. See [Webhooks](/docs/guides/post-call/polling-call-status-webhooks).
</Note>

## Run the whole flow as one script

The complete, dependency-free Python script runs all four steps end to end:

```bash theme={"system"}
export BOLNA_API_KEY="bn-xxxx"
# optional: export BOLNA_AGENT_ID="..."  to reuse a dashboard agent
python3 bolna_quickstart_test.py --to "+919876543210"
```

Add `--dry-run` to print the exact request bodies without making any network calls.

## Next steps

<CardGroup cols={2}>
  <Card title="Personalize calls" icon="brackets-curly" href="/docs/guides/prompting/using-context">
    Pass `user_data` variables like `{customer_name}` into the call body.
  </Card>

  <Card title="Call many people" icon="list-check" href="/docs/guides/outbound/batch-calling">
    Upload a CSV and run a batch campaign instead of single calls.
  </Card>

  <Card title="Receive results via webhook" icon="webhook" href="/docs/guides/post-call/polling-call-status-webhooks">
    Get the execution payload pushed to your server when a call ends.
  </Card>

  <Card title="Full agent schema" icon="code" href="/docs/api-reference/agent/v2/create">
    Every field you can set when creating an agent.
  </Card>
</CardGroup>
