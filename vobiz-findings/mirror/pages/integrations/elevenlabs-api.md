> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# ElevenLabs integration (API)

> Connect ElevenLabs to Vobiz SIP trunking via API - programmatic setup for ultra-realistic AI voice agents on outbound and inbound calls in 130+ countries.

This guide shows how to integrate ElevenLabs with Vobiz programmatically to enable **outbound calling** and automate voice calls with ultra-realistic AI voices.

<Tip>
  **Prefer watching a walkthrough or using the dashboard?** See the [ElevenLabs integration overview](/docs/integrations/elevenlabs) for the video tutorial, or the [dashboard setup guide](/docs/integrations/elevenlabs-dashboard) for a visual step-by-step walkthrough.
</Tip>

**Perfect for:**

* Application integration
* Bulk calling campaigns
* Automation workflows
* Custom call triggers

```text theme={null}
Call flow: Your App → ElevenLabs API → Vobiz SIP → Phone Network → Person Answers → AI Agent Speaks
```

## Prerequisites

* **Vobiz account** with SIP trunk → [Create account](https://console.vobiz.ai/auth/signup)

* **ElevenLabs account** with API key → [Sign up](https://elevenlabs.io)

* **ElevenLabs API key** → [Get API key](https://elevenlabs.io/app/developer/api-keys)

* **Phone number** from Vobiz (for caller ID)

## Part 1: Vobiz setup

<div className="text-lg font-semibold mt-6 mb-2">Create a SIP trunk</div>

Create a SIP trunk in Vobiz to handle voice traffic.

**See:** [Vobiz SIP trunks documentation](/docs/trunks)

**Save these values from the response:**

* `sip_domain` (for example, `abc123def.sip.vobiz.ai`)
* `username`
* `password`

You'll need them for ElevenLabs configuration.

<div className="text-lg font-semibold mt-6 mb-2">Get a phone number</div>

Purchase a phone number for outbound caller ID.

**See:** [Vobiz phone numbers documentation](/docs/account-phone-number/list-account-phone-numbers)

## Part 2: ElevenLabs setup

<div className="text-lg font-semibold mt-6 mb-2">Step 1: Get your API key</div>

**Via dashboard:**

* Go to [ElevenLabs Developer → API Keys](https://elevenlabs.io/app/developer/api-keys)
* Click **Create API Key**
* Name your key (for example, "Vobiz Integration")
* Set permissions:
  * **ElevenLabs Agents:** **Write** (Required)
  * **Voices:** **Read** (Required)
  * **User:** Read (Optional)
* Click **Create** and copy the key

```text theme={null}
sk_your_elevenlabs_api_key_here
```

**Save this key securely** - you'll use it in all API requests.

<div className="text-lg font-semibold mt-6 mb-2">Step 2: List available voices</div>

```bash theme={null}
curl "https://api.elevenlabs.io/v1/voices" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here"
```

**What to extract:**

* `voice_id` - use this when creating your agent
* `name` - voice name for identification
* `category` - voice type (premade, cloned, etc.)

```json theme={null}
{
  "voices": [
    {
      "voice_id": "voice_id_here",
      "name": "Rachel",
      "category": "premade",
      "labels": {
        "accent": "american",
        "age": "young"
      }
    },
    {
      "voice_id": "another_voice_id",
      "name": "Domi",
      "category": "premade"
    }
  ]
}
```

**Copy a `voice_id`** - you'll need it in Step 3.

<div className="text-lg font-semibold mt-6 mb-2">Step 3: Create an agent</div>

```bash theme={null}
curl -X POST "https://api.elevenlabs.io/v1/convai/agents" \
  -H "Content-Type: application/json" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here" \
  -d '{
    "name": "Customer Support Bot",
    "conversation_config": {
      "agent": {
        "prompt": {
          "prompt": "You are a helpful customer support assistant. Be friendly, professional, and concise."
        },
        "first_message": "Hello! Thank you for calling. How can I help you today?",
        "language": "en"
      },
      "tts": {
        "voice_id": "voice_id_here"
      }
    }
  }'
```

**Replace:**

* `voice_id_here` → your chosen voice ID from Step 2

```json theme={null}
{
  "agent_id": "agent_your_agent_id_here",
  "name": "Customer Support Bot",
  "conversation_config": {
    "agent": {
      "first_message": "Hello! Thank you for calling. How can I help you today?",
      "language": "en"
    }
  }
}
```

**Save the `agent_id`** - you'll need it to make calls.

## Part 3: Connect Vobiz to ElevenLabs

<div className="text-lg font-semibold mt-6 mb-2">Step 1: Import your phone number</div>

Register your Vobiz phone number with ElevenLabs for outbound calling.

```bash theme={null}
curl -X POST "https://api.elevenlabs.io/v1/convai/phone-numbers" \
  -H "Content-Type: application/json" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here" \
  -d '{
    "provider": "sip_trunk",
    "phone_number": "+911234567890",
    "label": "Vobiz Main Line",
    "inbound_trunk_config": {},
    "outbound_trunk_config": {
      "address": "abc123def.sip.vobiz.ai",
      "transport": "tcp",
      "credentials": {
        "username": "your_username",
        "password": "your_password"
      }
    },
    "supports_inbound": true,
    "supports_outbound": true
  }'
```

**Replace:**

* `+911234567890` → your Vobiz phone number
* `abc123def.sip.vobiz.ai` → your Vobiz SIP domain
* `your_username` → your Vobiz username
* `your_password` → your Vobiz password

```json theme={null}
{
  "phone_number_id": "phnum_your_phone_number_id_here",
  "phone_number": "+911234567890",
  "label": "Vobiz Main Line",
  "supports_outbound": true,
  "supports_inbound": true,
  "provider": "sip_trunk"
}
```

**Save the `phone_number_id`** - you'll need it in Step 2.

**Get Vobiz credentials:**

* **Via console:** [Vobiz Console](https://console.vobiz.ai) → Trunks
* **Via API:** [Vobiz API reference](/docs/trunks)

<div className="text-lg font-semibold mt-6 mb-2">Step 2: Make an outbound call</div>

```bash theme={null}
curl -X POST "https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call" \
  -H "Content-Type: application/json" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here" \
  -d '{
    "agent_id": "agent_your_agent_id_here",
    "agent_phone_number_id": "phnum_your_phone_number_id_here",
    "to_number": "+919988776655"
  }'
```

**Replace:**

* `agent_your_agent_id_here` → your agent ID from Part 2, Step 3
* `phnum_your_phone_number_id_here` → your phone number ID from Step 1
* `+919988776655` → destination number to call

```json theme={null}
{
  "success": true,
  "message": "Outbound call initiated",
  "conversation_id": "conv_your_conversation_id_here",
  "sip_call_id": "SCL_your_sip_call_id"
}
```

**Call initiated.**

What happens next:

* The phone rings at the destination
* When answered, the agent speaks
* The conversation begins with a natural voice

## Verification

<div className="text-lg font-semibold mt-6 mb-2">List your agents</div>

```bash theme={null}
curl "https://api.elevenlabs.io/v1/convai/agents" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here"
```

```json theme={null}
[
  {
    "agent_id": "agent_your_agent_id_here",
    "name": "Customer Support Bot",
    "conversation_config": {
      "agent": {
        "first_message": "Hello! How can I help you today?",
        "language": "en"
      }
    }
  }
]
```

<div className="text-lg font-semibold mt-6 mb-2">Check call logs</div>

View your call history in [ElevenLabs Dashboard](https://elevenlabs.io/app) → **Call History**.

**Test call flow:**

1. Run Step 2 to initiate a call.
2. Wait for the destination phone to ring.
3. Answer the call.
4. The AI agent will greet and speak.
5. Check the call transcript in the ElevenLabs Dashboard.

## Troubleshooting

<div className="text-lg font-semibold mt-6 mb-2">"Unauthorized" / 401 error</div>

**Problem:** ElevenLabs API key is invalid or expired.

**Fix:**

* Verify you copied the entire key (starts with `sk_`).
* Check the API key has **ElevenLabs Agents: Write** permission.
* Generate a new key at [ElevenLabs Developer](https://elevenlabs.io/app/developer/api-keys).

<div className="text-lg font-semibold mt-6 mb-2">"Not Found" / 404 error</div>

**Problem:** Agent ID or phone number ID doesn't exist.

**Fix:**

* List your agents to verify the agent ID is correct.
* Check the phone number is configured in [ElevenLabs Dashboard](https://elevenlabs.io/app).
* Ensure you're using the correct ID format.

<div className="text-lg font-semibold mt-6 mb-2">SIP 408 request timeout</div>

**Problem:** The Vobiz trunk cannot reach ElevenLabs SIP servers.

**Fix:**

* Verify the Vobiz trunk configuration in [Vobiz Console](https://console.vobiz.ai).
* Ensure transport is set to `tcp`.
* Check the trunk status is `active`.
* See: [Vobiz SIP trunks guide](/docs/trunks).

<div className="text-lg font-semibold mt-6 mb-2">"Insufficient balance"</div>

**Problem:** Vobiz account has no credits.

**Fix:**

* Log in to [Vobiz Console](https://console.vobiz.ai) → **Billing** and add funds.

<div className="text-lg font-semibold mt-6 mb-2">Call connects but silent</div>

**Problem:** Agent configuration issue or voice not set.

**Fix:**

* Verify the agent has `first_message` configured.
* Check the agent has a valid `voice_id` in `conversation_config`.
* Test the voice in the ElevenLabs dashboard first.
* View call logs in [ElevenLabs Dashboard](https://elevenlabs.io/app).

<div className="text-lg font-semibold mt-6 mb-2">Call doesn't connect</div>

**Problem:** Wrong phone number format or trunk configuration.

**Fix:**

* Use E.164 format: `+919988776655` (with `+` and country code).
* Verify the Vobiz trunk is active.
* Check Vobiz CDR logs for call attempts at [Vobiz Console](https://console.vobiz.ai).
* Ensure the phone number is not blocked.

## Quick reference

<div className="text-lg font-semibold mt-6 mb-2">Required credentials</div>

| Credential | Where to get | Example |
| - | - | - |
| ElevenLabs API Key | ElevenLabs Developer → API Keys | `sk_your_elevenlabs_api_key_here` |
| Voice ID | Part 2, step 2 (List Voices) | `voice_id_here` |
| Agent ID | Part 2, step 3 (Create Agent) | `agent_your_agent_id_here` |
| Phone Number ID | Part 3, step 1 (Import Phone) | `phnum_your_phone_number_id_here` |
| Vobiz SIP Domain | Vobiz Console → Trunks | `abc123def.sip.vobiz.ai` |
| Vobiz Username | Vobiz Console → Trunks | `your_username` |
| Vobiz Password | Vobiz Console → Trunks | `your_password` |

<div className="text-lg font-semibold mt-6 mb-2">API endpoints</div>

**Base URL:** `https://api.elevenlabs.io` - all requests require `xi-api-key: YOUR_ELEVENLABS_API_KEY`

| Action | Method | Endpoint |
| - | - | - |
| List voices | GET | `/v1/voices` |
| Create agent | POST | `/v1/convai/agents` |
| List agents | GET | `/v1/convai/agents` |
| Import phone number | POST | `/v1/convai/phone-numbers` |
| Make outbound call | POST | `/v1/convai/sip-trunk/outbound-call` |

<div className="text-lg font-semibold mt-6 mb-2">Common errors</div>

| Error | Cause | Fix |
| - | - | - |
| 401 Unauthorized | Wrong API key | Regenerate at [ElevenLabs Developer](https://elevenlabs.io/app/developer/api-keys) |
| 404 Not Found | Wrong agent or phone ID | List agents to verify IDs |
| 408 SIP timeout | Trunk config wrong | Check Vobiz Console → Trunks |
| Insufficient balance | Low Vobiz credits | Add funds in Vobiz Console |

## Complete example

Here's a complete working example with real values:

```bash theme={null}
# 1. List voices
curl "https://api.elevenlabs.io/v1/voices" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here"
# Save a voice_id from the response

# 2. Create the agent
curl -X POST "https://api.elevenlabs.io/v1/convai/agents" \
  -H "Content-Type: application/json" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here" \
  -d '{
    "name": "Customer Support Bot",
    "conversation_config": {
      "agent": {
        "prompt": { "prompt": "You are a helpful customer support assistant." },
        "first_message": "Hello! How can I help you today?",
        "language": "en"
      },
      "tts": { "voice_id": "voice_id_here" }
    }
  }'
# Response: save agent_id

# 3. Import the phone number
curl -X POST "https://api.elevenlabs.io/v1/convai/phone-numbers" \
  -H "Content-Type: application/json" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here" \
  -d '{
    "provider": "sip_trunk",
    "phone_number": "+911234567890",
    "label": "Vobiz Main Line",
    "inbound_trunk_config": {},
    "outbound_trunk_config": {
      "address": "abc123def.sip.vobiz.ai",
      "transport": "tcp",
      "credentials": { "username": "your_username", "password": "your_password" }
    },
    "supports_inbound": true,
    "supports_outbound": true
  }'
# Response: save phone_number_id

# 4. Make a call
curl -X POST "https://api.elevenlabs.io/v1/convai/sip-trunk/outbound-call" \
  -H "Content-Type: application/json" \
  -H "xi-api-key: sk_your_elevenlabs_api_key_here" \
  -d '{
    "agent_id": "agent_your_agent_id_here",
    "agent_phone_number_id": "phnum_your_phone_number_id_here",
    "to_number": "+919988776655"
  }'
# Response: call initiated
```

## Resources

<CardGroup cols={2}>
  <Card title="Vobiz documentation" icon="book">
    * [API documentation](/docs/introduction)
    * [Vobiz Console](https://console.vobiz.ai)
    * [SIP trunks](/docs/trunks)
    * [Phone numbers](/docs/account-phone-number/list-inventory-numbers)
  </Card>

  <Card title="ElevenLabs documentation" icon="book-open">
    * [API reference](https://elevenlabs.io/docs/api-reference/introduction)
    * [Dashboard](https://elevenlabs.io/app)
    * [Agents platform](https://elevenlabs.io/docs/agents-platform)
    * [Support](mailto:support@elevenlabs.io)
  </Card>
</CardGroup>


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.