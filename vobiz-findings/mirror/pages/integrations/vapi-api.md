> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Vapi integration (API)

> Connect Vapi to Vobiz SIP trunking via API - route inbound calls to any Vapi AI assistant and place outbound calls to 130+ countries programmatically.

<img className="block w-full rounded-xl border border-gray-200" src="https://mintcdn.com/vobizai/OZ7y9Kg025aXyvCH/images/integration-bg/VAPI.png?fit=max&auto=format&n=OZ7y9Kg025aXyvCH&q=85&s=79082396532611658b6e57e00c7dfeae" alt="Vapi API integration with Vobiz SIP trunking" width="1800" height="1080" data-path="images/integration-bg/VAPI.png" />

This guide shows how to integrate Vapi with Vobiz programmatically to enable **outbound calling** and **inbound calling**. Your AI assistants can call any phone number, and inbound calls to your Vobiz number can be routed to a Vapi assistant.

<Tip>
  **Prefer the dashboard?** Check out the [dashboard setup guide](/docs/integrations/vapi-dashboard) for a visual step-by-step walkthrough.
</Tip>

## Prerequisites

* A [Vobiz account](https://console.vobiz.ai/auth/signup) with a SIP trunk
* A [Vapi account](https://dashboard.vapi.ai/signup) with a private key
* A Vapi assistant - [create one in the dashboard](https://dashboard.vapi.ai)
* A phone number from Vobiz (for caller ID)

## Part 1: Vobiz setup

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Create a SIP trunk</div>

Create a SIP trunk in Vobiz to handle voice traffic. See the [SIP trunks documentation](/docs/trunks).

Save these values from the response:

* `sip_domain` (for example, `5f3a607b.sip.vobiz.ai`)
* `username`
* `password`

You'll need them for Vapi configuration.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Get a phone number</div>

Purchase a phone number for outbound caller ID or inbound calls. See the [phone numbers documentation](/docs/account-phone-number/list-inventory-numbers).

## Part 2: Vapi setup

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Get your Vapi private key</div>

1. Log in to the [Vapi Dashboard](https://dashboard.vapi.ai).
2. Click your profile icon (top right) and go to **Settings → API Keys**.
3. Click **Create new key** and copy the key.

```text theme={null}
c07947df-6ba2-4e58-92f5-35e92849f6c2
```

<Warning>
  Save this key securely - you'll use it in all API requests.
</Warning>

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Get your assistant ID</div>

1. In the [Vapi Dashboard](https://dashboard.vapi.ai), go to **Assistants**.
2. Select your assistant (or create one) and copy the **Assistant ID**.

```text theme={null}
9fb6d4c5-9403-49ea-afeb-9b493d63b474
```

Or list assistants via the API:

```bash theme={null}
curl "https://api.vapi.ai/assistant" \
  -H "Authorization: Bearer YOUR_VAPI_PRIVATE_KEY"
```

## Part 3: Connect Vobiz to Vapi (outbound)

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 1: Create the SIP credential in Vapi</div>

Register your Vobiz SIP trunk with Vapi for outbound calling.

```bash theme={null}
curl -X POST "https://api.vapi.ai/credential" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_VAPI_PRIVATE_KEY" \
  -d '{
    "provider": "byo-sip-trunk",
    "name": "Vobiz Trunk",
    "gateways": [{
      "ip": "bfab10fb.sip.vobiz.ai",
      "inboundEnabled": false
    }],
    "outboundLeadingPlusEnabled": true,
    "outboundAuthenticationPlan": {
      "authUsername": "Vapi_user",
      "authPassword": "Password@123"
    }
  }'
```

Replace:

* `bfab10fb.sip.vobiz.ai` → your Vobiz SIP domain
* `Vapi_user` → your Vobiz username
* `Password@123` → your Vobiz password

```json theme={null}
{
  "id": "65a79bd2-c1b9-4c83-8e55-97c22c092b48",
  "provider": "byo-sip-trunk",
  "gateways": [{
    "ip": "bfab10fb.sip.vobiz.ai",
    "inboundEnabled": false
  }]
}
```

Save the `id` - this is your **credential ID**.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 2: Register the phone number</div>

Associate your phone number with the SIP credential for caller ID.

```bash theme={null}
curl -X POST "https://api.vapi.ai/phone-number" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_VAPI_PRIVATE_KEY" \
  -d '{
    "provider": "byo-phone-number",
    "name": "Vobiz Line",
    "number": "08071387149",
    "numberE164CheckEnabled": false,
    "credentialId": "65a79bd2-c1b9-4c83-8e55-97c22c092b48"
  }'
```

```json theme={null}
{
  "id": "91122039-9644-47fd-a545-d865075a6941",
  "number": "08071387149",
  "status": "active",
  "credentialId": "65a79bd2-c1b9-4c83-8e55-97c22c092b48"
}
```

Save the `id` - this is your **phone number ID**.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 3: Make an outbound call</div>

```bash theme={null}
curl -X POST "https://api.vapi.ai/call/phone" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_VAPI_PRIVATE_KEY" \
  -d '{
    "assistantId": "9fb6d4c5-9403-49ea-afeb-9b493d63b474",
    "customer": {
      "number": "+919148223344",
      "numberE164CheckEnabled": false
    },
    "phoneNumberId": "91122039-9644-47fd-a545-d865075a6941"
  }'
```

```json theme={null}
{
  "id": "019a0bce-0cf3-7337-a253-f65f4e9c68f4",
  "status": "queued",
  "type": "outboundPhoneCall",
  "assistantId": "9fb6d4c5-9403-49ea-afeb-9b493d63b474",
  "customer": { "number": "+919148223344" },
  "phoneNumberId": "91122039-9644-47fd-a545-d865075a6941"
}
```

<Check>
  Call initiated. The phone will ring, and when answered, your AI assistant will speak.
</Check>

## Verification

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Check call status</div>

View call logs in [Vapi Dashboard](https://dashboard.vapi.ai) → **Calls**, or via API:

```bash theme={null}
curl "https://api.vapi.ai/call/019a0bce-0cf3-7337-a253-f65f4e9c68f4" \
  -H "Authorization: Bearer YOUR_VAPI_PRIVATE_KEY"
```

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Test call flow</div>

1. Run Step 3 to initiate a call.
2. Wait for the destination phone to ring.
3. Answer the call.
4. The AI assistant will greet and speak.
5. Check the call transcript in the Vapi Dashboard.

## Inbound calls

Route calls placed to your Vobiz number directly to your Vapi AI assistant using the API.

```text theme={null}
Caller dials Vobiz number → Vobiz SIP → Vapi SIP trunk → Vapi AI assistant
```

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 1: Create an inbound SIP credential in Vapi</div>

Create a SIP trunk credential configured for **inbound only** - using the Vobiz gateway IPs instead of a SIP domain. Vobiz sends inbound SIP from **any** of its signaling IPs, so add a gateway for **every** Vobiz SIP signaling IP; get the current list from [IP whitelisting → SIP signaling](/docs/concepts/ip-whitelisting#sip-signaling).

<Info>
  **RTP media firewall update:** If your network filters RTP traffic for Vapi calls, allow inbound and outbound UDP traffic on ports `5000–65535` from the complete [RTP media IP list](/docs/concepts/ip-whitelisting#rtp-media), including these new ranges:

  * `18.96.230.96/28`
  * `18.96.230.112/28`

  These ranges carry audio. Do not include them in the Vapi `gateways` array; that array uses SIP signaling IPs only.
</Info>

```bash theme={null}
curl -X POST "https://api.vapi.ai/credential" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_VAPI_PRIVATE_KEY" \
  -d '{
    "provider": "byo-sip-trunk",
    "name": "Vobiz Inbound Trunk",
    "gateways": [
      { "ip": "13.203.7.132",  "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "65.2.100.211",  "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "13.126.98.234", "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "13.235.11.131", "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "13.233.44.61",  "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "3.111.255.163", "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "3.111.128.110", "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "43.204.64.203", "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "15.207.232.91", "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false },
      { "ip": "35.154.133.28", "port": 5060, "netmask": 32, "inboundEnabled": true, "outboundEnabled": false }
    ]
  }'
```

```json theme={null}
{
  "id": "46deea29-645d-44a3-bf42-7c6ec2d4b65c",
  "provider": "byo-sip-trunk",
  "gateways": [{
    "ip": "13.233.44.61",
    "outboundEnabled": false
  }],
  "name": "Vobiz Inbound Trunk"
}
```

Save the `id` - this is your **inbound credential ID** (also called Trunk ID).

<Tip>
  Want both inbound and outbound on the same trunk? Add a second gateway entry for outbound with your Vobiz SIP domain and credentials:

  ```json theme={null}
  "gateways": [
    {
      "ip": "13.233.44.61",
      "inboundEnabled": true,
      "outboundEnabled": false
    },
    {
      "ip": "bfab10fb.sip.vobiz.ai",
      "inboundEnabled": false,
      "outboundEnabled": true
    }
  ]
  ```
</Tip>

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 2: Get the trunk ID</div>

If you didn't save the ID from Step 1, retrieve it by listing all credentials:

```bash theme={null}
curl -X GET "https://api.vapi.ai/credential" \
  -H "Authorization: Bearer YOUR_VAPI_PRIVATE_KEY"
```

Find the entry with gateway IP `13.233.44.61` and `outboundEnabled: false`. The `id` field is your trunk ID.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 3: Configure the inbound trunk in Vobiz</div>

Create an inbound trunk in the Vobiz Console that routes calls to Vapi:

1. Go to [Vobiz Console](https://console.vobiz.ai) → **SIP Trunks → Inbound Trunk**.
2. Click **Create New Trunk**.
3. Set **Name** and **Transport** to `UDP`.
4. Set **Primary URI** to `<VAPI_TRUNK_ID>.sip.vapi.ai` - for example, `46deea29-645d-44a3-bf42-7c6ec2d4b65c.sip.vapi.ai`.
5. Link your Vobiz phone number to this trunk.
6. Click **Save**.

Or use the Vobiz API to create the inbound trunk programmatically - see the [SIP trunks documentation](/docs/trunks).

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Step 4: Register the inbound phone number in Vapi</div>

Register your Vobiz number with the inbound credential and assign your assistant:

```bash theme={null}
curl -X POST "https://api.vapi.ai/phone-number" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_VAPI_PRIVATE_KEY" \
  -d '{
    "provider": "byo-phone-number",
    "name": "Vobiz Inbound Line",
    "number": "+918071387376",
    "numberE164CheckEnabled": true,
    "credentialId": "46deea29-645d-44a3-bf42-7c6ec2d4b65c",
    "assistantId": "YOUR_ASSISTANT_ID"
  }'
```

Replace:

* `+918071387376` → your Vobiz phone number
* `46deea29-...` → your inbound credential ID from Step 1
* `YOUR_ASSISTANT_ID` → your Vapi assistant ID

<Check>
  **Inbound setup complete!** Dial your Vobiz number - the call will route to your Vapi AI assistant automatically.
</Check>

## Troubleshooting

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">"Unauthorized" / "Invalid API key"</div>

Vapi private key is incorrect.

* Verify you copied the entire key.
* Generate a new key at [Vapi Dashboard](https://dashboard.vapi.ai) → **Settings → API Keys**.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">"Couldn't get assistant"</div>

Wrong assistant ID or it doesn't exist.

* Run `curl "https://api.vapi.ai/assistant" -H "Authorization: Bearer YOUR_KEY"` and use the correct `id`.
* Don't confuse credential ID with assistant ID.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">"SIP authentication failed"</div>

Vobiz credentials are incorrect.

* Verify SIP domain, username, password in [Vobiz Console](https://console.vobiz.ai).
* Use the exact `sip_domain` (for example, `bfab10fb.sip.vobiz.ai`), not a generic `sip.vobiz.ai`.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Call connects but silent</div>

Assistant configuration issue.

* Verify the assistant has a "First Message" configured.
* Check the assistant has a voice provider set up.
* View call logs in [Vapi Dashboard](https://dashboard.vapi.ai) → **Calls**.

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Call doesn't connect</div>

* Use E.164 format: `+919148223344`.
* Verify your Vobiz trunk is active in [Vobiz Console](https://console.vobiz.ai).

## Quick reference

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Required credentials</div>

| Credential | Where to get | Used in |
| - | - | - |
| Vapi private key | Vapi Dashboard → Settings → API Keys | All API requests |
| Vobiz SIP domain | Vobiz Console → Trunks → `sip_domain` | Step 1: `gateways[0].ip` |
| Vobiz username | Vobiz Console → Trunks | Step 1: `authUsername` |
| Vobiz password | Vobiz Console → Trunks | Step 1: `authPassword` |
| Phone number | Vobiz Console → Numbers | Step 2: `number` |
| Credential ID | Step 1 response `id` | Step 2: `credentialId` |
| Phone number ID | Step 2 response `id` | Step 3: `phoneNumberId` |
| Assistant ID | Vapi Dashboard → Assistants | Step 3: `assistantId` |

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">API endpoints</div>

All requests require `Authorization: Bearer YOUR_VAPI_PRIVATE_KEY`.

| Action | Method | Endpoint |
| - | - | - |
| Create SIP credential | POST | `https://api.vapi.ai/credential` |
| Register phone number | POST | `https://api.vapi.ai/phone-number` |
| Make outbound call | POST | `https://api.vapi.ai/call/phone` |
| List assistants | GET | `https://api.vapi.ai/assistant` |
| Get call details | GET | `https://api.vapi.ai/call/{callId}` |

<div className="text-xl font-bold mt-8 mb-4 text-slate-800 dark:text-slate-200">Common errors</div>

| Error | Cause | Fix |
| - | - | - |
| 401 Unauthorized | Wrong Vapi private key | Verify the key in the dashboard |
| Assistant does not exist | Wrong assistant ID | List assistants via API |
| SIP auth failed | Wrong Vobiz credentials | Check Vobiz Console → Trunks |
| Insufficient balance | Low Vobiz credits | Add funds in the Vobiz Console |
| Phone format error | Missing `+` or country code | Use `+919148223344` or `09148223344` |

## Resources

**Vobiz**

* [SIP trunks](/docs/trunks)
* [Phone numbers](/docs/account-phone-number/list-inventory-numbers)
* [Vobiz Console](https://console.vobiz.ai)
* Support: [support@vobiz.ai](mailto:support@vobiz.ai)

**Vapi**

* [API reference](https://docs.vapi.ai/api-reference)
* [Assistants guide](https://docs.vapi.ai/assistants)
* [Phone calling](https://docs.vapi.ai/phone)
* [Vapi Dashboard](https://dashboard.vapi.ai)
* Support: [Vapi Discord](https://discord.gg/vapi) or [support@vapi.ai](mailto:support@vapi.ai)


This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.