> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Inbound Quickstart

> Point a phone number at a Bolna agent so it answers incoming calls — list your numbers, link an agent, and test the call in a few minutes.

The [API Quickstart](/docs/quickstarts/api) covers *outbound* calls. This guide does the mirror image: make an agent **answer** calls. You'll link one of your phone numbers to an agent so every inbound call is picked up automatically.

<Info>
  You need a phone number on your account first. Buy one from the [dashboard](https://platform.bolna.ai) or via `POST /phone-numbers/buy`, or bring your own through [SIP trunking](/docs/sip-trunking/introduction). Indian numbers also require [compliance](/docs/compliance-application/introduction).
</Info>

## Prerequisites

* A Bolna API key (`export BOLNA_API_KEY="bn-xxxx"`)
* An `agent_id` to answer calls (create one via the [API Quickstart](/docs/quickstarts/api) or the dashboard)
* At least one phone number on your account

<Tip>
  For inbound, give the agent an *inbound-appropriate* welcome message — e.g. "Thanks for calling Acme, how can I help?" — rather than an outbound opener.
</Tip>

<Steps>
  <Step title="Find your phone number's ID">
    The link call needs the number's `id`, not the number itself. List your numbers:

    <CodeGroup>
      ```bash curl theme={"system"}
      curl https://api.bolna.ai/phone-numbers/all \
        -H "Authorization: Bearer $BOLNA_API_KEY"
      ```

      ```python Python theme={"system"}
      import os, urllib.request, json
      req = urllib.request.Request(
          "https://api.bolna.ai/phone-numbers/all",
          headers={"Authorization": f"Bearer {os.environ['BOLNA_API_KEY']}"},
      )
      for n in json.load(urllib.request.urlopen(req)):
          print(n["phone_number"], n["id"], n["telephony_provider"])
      ```
    </CodeGroup>

    ```json Response (array) theme={"system"}
    [
      {
        "id": "3c90c3cc0d444b5088888dd25736052a",
        "phone_number": "+19876543210",
        "telephony_provider": "twilio",
        "agent_id": null
      }
    ]
    ```

    Copy the `id` of the number you want to use.
  </Step>

  <Step title="Link the agent to the number">
    Associate your agent with the phone number. After this, inbound calls to that number are answered by the agent.

    <CodeGroup>
      ```bash curl theme={"system"}
      curl https://api.bolna.ai/inbound/setup \
        -H "Authorization: Bearer $BOLNA_API_KEY" \
        -H "Content-Type: application/json" \
        -d '{
          "agent_id": "YOUR_AGENT_ID",
          "phone_number_id": "3c90c3cc0d444b5088888dd25736052a"
        }'
      ```

      ```python Python theme={"system"}
      import os, urllib.request, json
      body = json.dumps({
          "agent_id": os.environ["BOLNA_AGENT_ID"],
          "phone_number_id": "3c90c3cc0d444b5088888dd25736052a",
      }).encode()
      req = urllib.request.Request(
          "https://api.bolna.ai/inbound/setup",
          data=body,
          headers={"Authorization": f"Bearer {os.environ['BOLNA_API_KEY']}",
                   "Content-Type": "application/json"},
      )
      print(json.load(urllib.request.urlopen(req)))
      ```
    </CodeGroup>

    ```json Response theme={"system"}
    {
      "url": "https://api.bolna.ai/inbound_call?agent_id=…&user_id=…",
      "phone_number": "+19876543210",
      "id": "3c90c3cc0d444b5088888dd25736052a"
    }
    ```
  </Step>

  <Step title="Call the number">
    Dial the number from any phone — your agent answers with its welcome message and starts the conversation. After the call, retrieve the transcript exactly like outbound: poll [`GET /executions/{id}`](/docs/api-reference/executions/get_execution) or use a [webhook](/docs/guides/post-call/polling-call-status-webhooks).
  </Step>
</Steps>

## Optional: IVR routing

For Plivo numbers you can add an `ivr_config` to the same `POST /inbound/setup` request to play a menu and route callers to different agents (by department, language, etc.). See [IVR for Inbound Calls](/docs/guides/inbound/ivr-inbound-calls).

## Unlink a number

To stop an agent from answering a number, call [`POST /inbound/unlink`](/docs/api-reference/inbound/unlink) with the phone number ID.

## Run the setup as a script

The dependency-free helper script automates listing numbers and linking the agent:

```bash theme={"system"}
export BOLNA_API_KEY="bn-xxxx"
export BOLNA_AGENT_ID="your-agent-id"
python3 bolna_inbound_setup.py          # auto-pick your first number
python3 bolna_inbound_setup.py --list   # just list numbers
python3 bolna_inbound_setup.py --dry-run
```

## Next steps

<CardGroup cols={2}>
  <Card title="Identify callers" icon="address-book" href="/docs/customizations/identify-incoming-callers">
    Match incoming numbers to your CRM and preload customer data.
  </Card>

  <Card title="Inbound settings" icon="phone-arrow-down" href="/docs/agent-setup/inbound-tab">
    Spam prevention, caller matching, and call limits.
  </Card>

  <Card title="IVR menus" icon="list-ol" href="/docs/guides/inbound/ivr-inbound-calls">
    Route callers to different agents with a keypad menu.
  </Card>

  <Card title="Bring your own SIP trunk" icon="network-wired" href="/docs/sip-trunking/introduction">
    Use your existing carrier numbers for inbound.
  </Card>
</CardGroup>
