> ## Documentation Index
> Fetch the complete documentation index at: https://www.bolna.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Register Your SIP Trunk on Bolna and Add Phone Numbers

> Register your SIP trunk with Bolna using the API, add your DID phone numbers, and verify your trunk is ready for AI-powered calls.

After creating your SIP trunk on your provider ([Plivo](/docs/tutorials/sip-trunking/plivo-trunk-setup) or [Twilio](/docs/tutorials/sip-trunking/twilio-trunk-setup)), the next step is to register that trunk with Bolna. This tells Bolna how to connect to your provider's gateway and which phone numbers belong to this trunk.

You will do two things in this guide:

1. **Create the trunk on Bolna** with your provider's gateway details and authentication credentials
2. **Add your phone numbers (DIDs)** so Bolna knows which numbers to route through this trunk

***

## Prerequisites

Before you begin, make sure you have:

1. A SIP trunk already created on your provider ([Plivo guide](/docs/tutorials/sip-trunking/plivo-trunk-setup) or [Twilio guide](/docs/tutorials/sip-trunking/twilio-trunk-setup))
2. Your **provider gateway address** (e.g., `XXXX.zt.plivo.com` for Plivo or `bolna-trunk.pstn.twilio.com` for Twilio)
3. Your **authentication credentials**: username/password for `userpass` auth, or provider IP ranges for `ip-based` auth
4. Your **Bolna API key** from the [Bolna Dashboard](https://platform.bolna.ai/)
5. Your **DID phone numbers** that you purchased from your provider

***

## Step 1: Create the Trunk on Bolna

Use the [Create SIP Trunk API](/docs/api-reference/sip-trunks/create) to register your trunk. The exact payload depends on your provider and authentication method. Choose the example that matches your setup:

<Tabs>
  <Tab title="IP-Based Authentication (e.g., Plivo, Telnyx)">
    With IP-based auth, your provider identifies Bolna by its source IP address. You provide your provider's IP ranges so Bolna can verify that incoming SIP requests are legitimate.

    <CodeGroup>
      ```bash request theme={"system"}
      curl -X POST https://api.bolna.ai/sip-trunks/trunks \
        -H "Authorization: Bearer <your-bolna-api-key>" \
        -H "Content-Type: application/json" \
        -d '{
          "name": "Plivo Trunk - Production",
          "provider": "plivo",
          "description": "Plivo Zentrunk for Bolna Voice AI",
          "auth_type": "ip-based",
          "gateways": [
            {
              "gateway_address": "XXXXXXXXXXXXXXXXXXXX.zt.plivo.com",
              "port": 5060,
              "priority": 1
            }
          ],
          "ip_identifiers": [
            { "ip_address": "15.207.90.192/31" },
            { "ip_address": "204.89.151.128/27" },
            { "ip_address": "13.52.9.0/25" }
          ],
          "allow": "ulaw,alaw",
          "disallow": "all",
          "inbound_enabled": true,
          "outbound_leading_plus_enabled": true
        }'
      ```

      ```json response theme={"system"}
      {
        "id": "01HQXYZ789GHI012JKL",
        "name": "Plivo Trunk - Production",
        "provider": "plivo",
        "auth_type": "ip-based",
        "gateways": [
          {
            "id": "01HQXYZ222BBB222CCC",
            "gateway_address": "XXXXXXXXXXXXXXXXXXXX.zt.plivo.com",
            "port": 5060,
            "priority": 1
          }
        ],
        "ip_identifiers": [
          { "ip_address": "15.207.90.192/31" },
          { "ip_address": "204.89.151.128/27" },
          { "ip_address": "13.52.9.0/25" }
        ],
        "phone_numbers": [],
        "is_active": true,
        "inbound_enabled": true,
        "created_at": "2025-01-15T10:00:00Z"
      }
      ```
    </CodeGroup>

    <Tip>
      Replace `XXXXXXXXXXXXXXXXXXXX.zt.plivo.com` with the **Termination SIP Domain** you copied from your provider's console. The `ip_identifiers` above are Plivo's IP ranges; check your provider's documentation for their specific ranges.
    </Tip>
  </Tab>

  <Tab title="Username/Password Authentication (e.g., Twilio, Zadarma, Vonage)">
    With username/password auth, Bolna sends credentials with every outbound SIP request so your provider can verify the call is authorized.

    <CodeGroup>
      ```bash request theme={"system"}
      curl -X POST https://api.bolna.ai/sip-trunks/trunks \
        -H "Authorization: Bearer <your-bolna-api-key>" \
        -H "Content-Type: application/json" \
        -d '{
          "name": "Twilio Trunk - Production",
          "provider": "twilio",
          "description": "Twilio Elastic SIP Trunk for Bolna Voice AI",
          "auth_type": "userpass",
          "auth_username": "bolna_trunk",
          "auth_password": "<your-credential-password>",
          "gateways": [
            {
              "gateway_address": "bolna-trunk.pstn.twilio.com",
              "port": 5060,
              "priority": 1
            }
          ],
          "allow": "ulaw,alaw",
          "disallow": "all",
          "inbound_enabled": true,
          "outbound_leading_plus_enabled": true
        }'
      ```

      ```json response theme={"system"}
      {
        "id": "01HQXYZ123ABC456DEF",
        "name": "Twilio Trunk - Production",
        "provider": "twilio",
        "auth_type": "userpass",
        "auth_username": "bolna_trunk",
        "gateways": [
          {
            "id": "01HQXYZ111AAA111BBB",
            "gateway_address": "bolna-trunk.pstn.twilio.com",
            "port": 5060,
            "priority": 1
          }
        ],
        "phone_numbers": [],
        "is_active": true,
        "inbound_enabled": true,
        "created_at": "2025-01-15T10:00:00Z"
      }
      ```
    </CodeGroup>

    <Tip>
      Replace `bolna-trunk.pstn.twilio.com` with the **Termination URI** you configured on your provider. Replace `bolna_trunk` and `<your-credential-password>` with the credentials you created.
    </Tip>
  </Tab>
</Tabs>

<Warning>
  **Save the `id` field from the response.** This is your **Trunk ID** and you will need it for every subsequent API call: adding phone numbers, mapping agents, and making calls.
</Warning>

***

## Step 2: Add Phone Numbers

Register the DID phone numbers you have **already purchased on your SIP provider** (from [Plivo](https://console.plivo.com/active-phone-numbers/) or [Twilio](https://www.twilio.com/console/phone-numbers)). Bolna does not provision numbers, it needs to know which of your provider numbers to route through this trunk for inbound matching and outbound caller ID.

Use the [Add Phone Number API](/docs/api-reference/sip-trunks/add_number) for each number:

<CodeGroup>
  ```bash request theme={"system"}
  curl -X POST https://api.bolna.ai/sip-trunks/trunks/<trunk-id>/numbers \
    -H "Authorization: Bearer <your-bolna-api-key>" \
    -H "Content-Type: application/json" \
    -d '{
      "phone_number": "919876543210",
      "name": "Main Support Line"
    }'
  ```

  ```json response theme={"system"}
  {
    "id": "01HQNUMBER111222333",
    "phone_number": "919876543210",
    "byot_trunk_id": "01HQXYZ123ABC456DEF",
    "telephony_provider": "sip-trunk",
    "created_at": "2025-01-15T10:05:00Z"
  }
  ```
</CodeGroup>

<Tip>
  **Save the `id` from the response.** This is the **Phone Number ID** that you will use when [mapping this number to an AI agent](/docs/tutorials/sip-trunking/inbound-calls) for inbound calls, and when specifying the `from_number` for [outbound calls](/docs/tutorials/sip-trunking/outbound-calls).
</Tip>

### Adding Multiple Numbers

Repeat the API call for each DID number you want to add. Each number receives its own unique `id`:

```bash theme={"system"}
# Example: adding a second number
curl -X POST https://api.bolna.ai/sip-trunks/trunks/<trunk-id>/numbers \
  -H "Authorization: Bearer <your-bolna-api-key>" \
  -H "Content-Type: application/json" \
  -d '{
    "phone_number": "+14158675309",
    "name": "US Sales Line"
  }'
```

<Note>
  **Phone number format:** Bolna stores the number exactly as you provide it and performs flexible matching (with and without the `+` prefix) for inbound calls. Use a consistent format across your configuration.
</Note>

***

## Step 3: Verify Your Trunk

After creating the trunk and adding numbers, verify that everything is configured correctly.

Use the [Get SIP Trunk API](/docs/api-reference/sip-trunks/get) to check your trunk:

```bash theme={"system"}
curl -X GET https://api.bolna.ai/sip-trunks/trunks/<trunk-id> \
  -H "Authorization: Bearer <your-bolna-api-key>"
```

Confirm the following fields in the response:

| Field             | Expected Value       | What It Means                       |
| ----------------- | -------------------- | ----------------------------------- |
| `is_active`       | `true`               | Trunk is active and ready for calls |
| `inbound_enabled` | `true`               | Trunk can receive inbound calls     |
| `gateways`        | Your gateway address | Gateway is correctly configured     |
| `phone_numbers`   | Your added numbers   | All DIDs are registered             |

You can also list all phone numbers on the trunk:

```bash theme={"system"}
curl -X GET https://api.bolna.ai/sip-trunks/trunks/<trunk-id>/numbers \
  -H "Authorization: Bearer <your-bolna-api-key>"
```

***

## Field Reference

Here is a complete reference of all fields you can use when creating a trunk:

| Field                           | Type    | Required    | Default       | Description                                                                                           |
| ------------------------------- | ------- | ----------- | ------------- | ----------------------------------------------------------------------------------------------------- |
| `name`                          | string  | Yes         |               | Human-readable label for the trunk. Must be unique.                                                   |
| `provider`                      | string  | Yes         |               | SIP provider: `"twilio"`, `"plivo"`, `"zadarma"`, `"telnyx"`, `"vonage"`, `"custom"`                  |
| `description`                   | string  | No          | `null`        | Optional description for your internal reference                                                      |
| `auth_type`                     | string  | Yes         |               | `"userpass"` (username/password) or `"ip-based"`                                                      |
| `auth_username`                 | string  | If userpass | `null`        | SIP username for authentication                                                                       |
| `auth_password`                 | string  | If userpass | `null`        | SIP password for authentication                                                                       |
| `gateways`                      | array   | Yes         |               | At least one gateway with `gateway_address` (required), `port` (default 5060), `priority` (default 1) |
| `ip_identifiers`                | array   | If ip-based | `[]`          | List of `{ "ip_address": "..." }` objects in CIDR notation                                            |
| `allow`                         | string  | No          | `"ulaw,alaw"` | Comma-separated codecs to allow. Always include `ulaw`.                                               |
| `disallow`                      | string  | No          | `"all"`       | Comma-separated codecs to block                                                                       |
| `inbound_enabled`               | boolean | No          | `false`       | Set to `true` to receive inbound calls                                                                |
| `outbound_leading_plus_enabled` | boolean | No          | `true`        | Prepend `+` to outbound dialed numbers (required by Twilio)                                           |
| `rtp_symmetric`                 | boolean | No          | `true`        | Symmetric RTP for NAT traversal. Keep as `true`.                                                      |
| `force_rport`                   | boolean | No          | `true`        | Force responses to source port. Keep as `true`.                                                       |
| `qualify_frequency`             | integer | No          | `60`          | SIP OPTIONS keepalive ping interval in seconds. Set to `0` to disable.                                |

***

## Next Steps

Your trunk is registered and phone numbers are added. Now configure how calls are handled:

<CardGroup cols={2}>
  <Card title="Receive Inbound Calls" icon="phone-arrow-down-left" href="/docs/tutorials/sip-trunking/inbound-calls">
    Map your phone numbers to AI agents so they answer incoming calls
  </Card>

  <Card title="Make Outbound Calls" icon="phone-arrow-up-right" href="/docs/tutorials/sip-trunking/outbound-calls">
    Place outbound calls from your trunk numbers using AI agents
  </Card>
</CardGroup>
