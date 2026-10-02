> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Retell AI integration (API)

> Connect Retell AI to Vobiz SIP trunking via API - programmatic outbound and inbound call routing for AI voice agents across 130+ countries.

This guide shows how to integrate Retell AI with Vobiz using the API for **automated outbound calling** - ideal for developers building applications that trigger AI calls programmatically.

<Tip>
  **Prefer a visual dashboard?** Check out the [dashboard setup guide](/docs/integrations/retellai-dashboard) for a no-code integration method.
</Tip>

## Prerequisites

* **Retell AI account** → [Sign up](https://dashboard.retellai.com)
* **Vobiz account** with SIP trunk → [Create account](https://console.vobiz.ai/auth/signup)
* **Retell AI agent** created → [Create in dashboard](https://dashboard.retellai.com/agents)
* **Phone number** from Vobiz (for caller ID)

**Get Vobiz credentials:**

* **Console:** [Vobiz Console → Trunks](https://console.vobiz.ai)
* **API:** [Vobiz API reference](/docs/trunks)

## Step 1: Get your API key

1. Go to [Retell Dashboard → Settings → API Keys](https://dashboard.retellai.com/settings/api-keys).
2. Click **Create API Key**.
3. Copy the key (it starts with `key_`).

<Warning>
  Keep this key secret - never commit it to git or share publicly. Store it securely in environment variables.
</Warning>

## Step 2: List available agents

Retrieve all agents to get the `agent_id` you'll use for calls:

```bash theme={null}
curl "https://api.retellai.com/list-agents" \
  -H "Authorization: Bearer key_abc123xyz789example"
```

Example response:

```json theme={null}
[
  {
    "agent_id": "agent_abc123example",
    "agent_name": "Customer Support Agent",
    "voice_id": "11labs-Rachel",
    "language": "en-US"
  }
]
```

What to extract:

* `agent_id` - use this when making calls
* `agent_name` - human-readable label
* `voice_id` - the voice the agent uses

Copy the `agent_id` for the agent you want to use.

## Step 3: Configure phone number with SIP trunk

Add your Vobiz phone number and SIP trunk configuration to Retell:

```bash theme={null}
curl "https://api.retellai.com/create-phone-number" \
  -X POST \
  -H "Authorization: Bearer key_abc123xyz789example" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+1234567890",
    "phone_number_type": "custom",
    "nickname": "Vobiz Main Line",
    "outbound_agent_id": "agent_abc123example",
    "sip_outbound_trunk_config": {
      "termination_uri": "abc123.sip.vobiz.ai",
      "transport": "TCP",
      "auth_username": "your_username",
      "auth_password": "your_password"
    }
  }'
```

Required fields:

| Field | Description |
| - | - |
| `phone_number` | Your Vobiz number in E.164 format |
| `phone_number_type` | Must be `"custom"` for SIP trunks |
| `outbound_agent_id` | Agent ID from Step 2 |
| `sip_outbound_trunk_config.termination_uri` | Vobiz SIP domain (without the `sip:` prefix) |
| `sip_outbound_trunk_config.transport` | `"TCP"` (recommended) |
| `sip_outbound_trunk_config.auth_username` | Vobiz trunk username |
| `sip_outbound_trunk_config.auth_password` | Vobiz trunk password |

<Note>
  Get your Vobiz credentials from [Vobiz Console](https://console.vobiz.ai) → **Trunks** → your trunk.
</Note>

## Step 4: Make an outbound call

Trigger an outbound AI call programmatically:

```bash theme={null}
curl "https://api.retellai.com/v2/create-phone-call" \
  -X POST \
  -H "Authorization: Bearer key_abc123xyz789example" \
  -H "Content-Type: application/json" \
  -d '{
    "from_number": "+1234567890",
    "to_number": "+10987654321",
    "agent_id": "agent_abc123example"
  }'
```

Required parameters:

| Field | Description |
| - | - |
| `from_number` | Your configured Vobiz number (caller ID) |
| `to_number` | Destination number to call (E.164 format) |
| `agent_id` | Which agent to use for the call |

Example response:

```json theme={null}
{
  "call_id": "call_abc123xyz789",
  "call_status": "registered",
  "from_number": "+1234567890",
  "to_number": "+10987654321",
  "direction": "outbound"
}
```

Call status values:

* `registered` - call initiated
* `ringing` - phone is ringing
* `ongoing` - call connected
* `ended` - call finished

<Check>
  **Call initiated!** The destination phone will ring, and when answered, the AI agent will speak.
</Check>

## Step 5: Configure inbound calls

Steps 1-4 cover outbound. Inbound needs a second, separate Vobiz trunk pointing at Retell's SIP address, with your number assigned to it. It is pure trunk-based routing — no Vobiz [application](/docs/applications) or answer webhook is involved.

<Steps>
  <Step title="Create the origination URI">
    Point a URI at Retell's inbound SIP host with [Create Origination URI](/docs/trunks/origination-uri/create-origination-uri).

    ```bash theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/Account/$VOBIZ_AUTH_ID/origination-uris" \
      -H "X-Auth-ID: $VOBIZ_AUTH_ID" \
      -H "X-Auth-Token: $VOBIZ_AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "name": "retell",
        "sip_uri": "sip:sip.retellai.com",
        "priority": 1
      }'
    ```

    Keep the `id` from the response — it is the URI's UUID.

    <Warning>
      **The API and the Console want different spellings of the same host.** `sip_uri` here must include the `sip:` scheme, so `sip:sip.retellai.com`. The Console's URI field takes a bare host instead — `sip.retellai.com`. A port is optional; `5060` is assumed.
    </Warning>

    <Note>
      **Transport is not settable at creation.** A new URI gets an inferred transport, and [Update Origination URI](/docs/trunks/origination-uri/update-origination-uri) accepts only `name` and `priority`. To pin **UDP** or **TCP** explicitly, set it on the URI in the Console — see the [dashboard guide](/docs/integrations/retellai-dashboard#part-2-inbound-calls).
    </Note>
  </Step>

  <Step title="Create the inbound trunk with that URI as primary">
    Create an inbound trunk and attach the URI from the previous step as its primary. See [Create a Trunk](/docs/trunks/create-trunk) for the full field list.

    A trunk created without a primary URI has nowhere to send the call, so set it at creation or update the trunk afterwards with [Update a Trunk](/docs/trunks/update-trunk).

    Keep the returned `trunk_id`.
  </Step>

  <Step title="Assign your number to the trunk">
    Route the number to the inbound trunk with [Assign Number to Trunk](/docs/trunks/assign-number). The phone number is **URL-encoded** in the path, so `+` becomes `%2B`.

    ```bash theme={null}
    curl -X POST "https://api.vobiz.ai/api/v1/Account/$VOBIZ_AUTH_ID/numbers/%2B1234567890/assign" \
      -H "X-Auth-ID: $VOBIZ_AUTH_ID" \
      -H "X-Auth-Token: $VOBIZ_AUTH_TOKEN" \
      -H "Content-Type: application/json" \
      -d '{
        "trunk_group_id": "<the trunk_id from step 2>"
      }'
    ```

    Use the same number you configured for outbound.
  </Step>

  <Step title="Assign the inbound agent in Retell">
    Attach the agent that should answer, with the Retell API:

    ```bash theme={null}
    curl -X PATCH "https://api.retellai.com/update-phone-number/+1234567890" \
      -H "Authorization: Bearer key_abc123xyz789example" \
      -H "Content-Type: application/json" \
      -d '{
        "inbound_agent_id": "agent_abc123example"
      }'
    ```

    `inbound_agent_id` and `outbound_agent_id` are separate fields on the same number, so one number can answer with one agent and dial out with another.
  </Step>
</Steps>

<Check>
  **Inbound is live.** Call your Vobiz number from any phone — the Retell agent should answer.
</Check>

## Troubleshooting

### 401 Unauthorized

Invalid API key.

* Verify the API key in [Retell Dashboard → Settings](https://dashboard.retellai.com/settings/api-keys).
* Ensure it starts with `key_`.

### "Phone number not found"

Phone number not configured in Retell.

* Run Step 3 to add the phone number with the SIP trunk.
* Verify the number format is E.164.

### Call fails immediately

Possible causes:

1. **Wrong SIP credentials** - verify Vobiz username/password at [Vobiz Console](https://console.vobiz.ai).
2. **Wrong transport type** - try `"UDP"` instead of `"TCP"` in the trunk config.
3. **Incorrect SIP domain** - must be the exact Vobiz domain (for example, `abc123.sip.vobiz.ai`); do not include the `sip:` prefix.
4. **Insufficient balance** - check your Vobiz account has credits at [Vobiz Console](https://console.vobiz.ai). See [account balance](/docs/account/balance).

### Agent doesn't speak

Agent not configured or not published.

* Ensure the agent is published in [Retell Dashboard → Agents](https://dashboard.retellai.com/agents).
* Check the agent has a voice configured.
* Verify the agent ID matches the phone number config.

## Quick reference

### API endpoints

**Base URL:** `https://api.retellai.com`
**Authentication:** `Authorization: Bearer YOUR_API_KEY`

| Endpoint | Method | Purpose |
| - | - | - |
| `/list-agents` | GET | List all agents |
| `/list-phone-numbers` | GET | List configured numbers |
| `/create-phone-number` | POST | Add phone number with SIP trunk |
| `/v2/create-phone-call` | POST | Make outbound call |
| `/update-phone-number/{number}` | PATCH | Set the inbound or outbound agent on a number |
| `/get-call/{call_id}` | GET | Get call details |

**Vobiz endpoints used for inbound routing** — base `https://api.vobiz.ai`, auth `X-Auth-ID` / `X-Auth-Token`:

| Endpoint | Method | Purpose |
| - | - | - |
| [`/api/v1/Account/{auth_id}/origination-uris`](/docs/trunks/origination-uri/create-origination-uri) | POST | Point a URI at `sip:sip.retellai.com` |
| [`/api/v1/Account/{auth_id}/trunks`](/docs/trunks/create-trunk) | POST | Create the inbound trunk with that URI as primary |
| [`/api/v1/Account/{auth_id}/numbers/{number}/assign`](/docs/trunks/assign-number) | POST | Route the number to the trunk |

### Complete call flow

```bash theme={null}
# 1. List agents
curl "https://api.retellai.com/list-agents" \
  -H "Authorization: Bearer key_YOUR_KEY_HERE"

# 2. Configure phone number (one-time)
curl "https://api.retellai.com/create-phone-number" \
  -X POST \
  -H "Authorization: Bearer key_YOUR_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+1234567890",
    "phone_number_type": "custom",
    "outbound_agent_id": "agent_YOUR_AGENT_ID",
    "sip_outbound_trunk_config": {
      "termination_uri": "abc123.sip.vobiz.ai",
      "transport": "TCP",
      "auth_username": "your_username",
      "auth_password": "your_password"
    }
  }'

# 3. Make a call
curl "https://api.retellai.com/v2/create-phone-call" \
  -X POST \
  -H "Authorization: Bearer key_YOUR_KEY_HERE" \
  -H "Content-Type: application/json" \
  -d '{
    "from_number": "+1234567890",
    "to_number": "+10987654321",
    "agent_id": "agent_YOUR_AGENT_ID"
  }'
```

## Resources

* [Retell AI documentation](https://docs.retellai.com)
* [Retell AI dashboard](https://dashboard.retellai.com)
* [Vobiz documentation](/docs/introduction)
* [Vobiz Console](https://console.vobiz.ai)

<Check>
  Your Retell AI agents can now make outbound calls through Vobiz programmatically - perfect for automated campaigns and application integrations.
</Check>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.