> ## Documentation Index
> Fetch the complete documentation index at: https://www.vobiz.ai/docs/llms.txt
> Use this file to discover all available pages before exploring further.

# Create a Trunk

> Provision a new Vobiz SIP trunk with concurrent-call limits, CPS caps, TLS/SRTP, credentials, IP ACLs, and origination URIs - all in a single API call.

```http theme={null}
POST https://api.vobiz.ai/api/v1/Account/{auth_id}/trunks
```

Use this endpoint to create a new SIP trunk for handling voice traffic. Each trunk can be configured with rate limits, authentication methods (credentials and IP ACLs), and origination URIs for outbound routing.

<Info>
  **Authentication required:**

  * `X-Auth-ID` - Your account Auth ID
  * `X-Auth-Token` - Your account Auth Token
  * `Content-Type: application/json`
</Info>

<Info>
  **Auto-Generated Domain:** Upon creation, Vobiz automatically generates a unique SIP domain for your trunk in the format: `trunk_id.sip.vobiz.ai`. This domain is used for routing inbound calls to your trunk.
</Info>

## Request Parameters

Only three fields are required to create a trunk. The rest of the trunk's configuration - transport, TLS/SRTP, recording, attached credentials, IP ACLs, and origination URIs - is applied afterwards through the dedicated endpoints or the Console.

| Field | Type | Required | Description |
| - | - | - | - |
| `name` | string | Yes | Descriptive name for the trunk. Maximum 255 characters. |
| `trunk_type` | string | Yes | Trunk direction. One of `INBOUND` or `OUTBOUND` (uppercase). Determines how the trunk routes traffic. |
| `max_concurrent_calls` | integer | Yes | Maximum number of simultaneous calls. Returned on the trunk object as `concurrent_calls_limit`. |

<Note>
  **Defaults applied at creation.** New trunks come back with `cps_limit: 2`, `secure: false`, `transport: udp`, and `trunk_status: active`. The `trunk_domain` is auto-generated as `{trunk_id}.sip.vobiz.ai`. Tune limits later with [Update a Trunk](/docs/trunks/update-trunk), and attach auth and routing with [Credentials](/docs/trunks/credentials/create-credential), [IP ACLs](/docs/trunks/ip-acl/create-ip-acl), and [Origination URIs](/docs/trunks/origination-uri/create-origination-uri).
</Note>

<Tip>
  **`cps_limit` vs `concurrent_calls_limit`.** `cps_limit` caps how many new calls can be **started per second** (flood protection); `concurrent_calls_limit` caps how many calls can be **live at once** (capacity and cost control). They are independent.
</Tip>

## Examples

<CodeGroup>
  ```bash cURL theme={null}
  curl -X POST https://api.vobiz.ai/api/v1/Account/AUTH_ID/trunks \
    -H "X-Auth-ID: AUTH_ID" \
    -H "X-Auth-Token: AUTH_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
      "name": "My SIP Trunk",
      "trunk_type": "OUTBOUND",
      "max_concurrent_calls": 10
    }'
  ```

  ```javascript Node.js theme={null}
  const response = await fetch(
    'https://api.vobiz.ai/api/v1/Account/AUTH_ID/trunks',
    {
      method: 'POST',
      headers: {
        'X-Auth-ID': 'AUTH_ID',
        'X-Auth-Token': 'AUTH_TOKEN',
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        name: 'My SIP Trunk',
        trunk_type: 'OUTBOUND',
        max_concurrent_calls: 10,
      }),
    }
  );
  const trunk = await response.json();
  console.log(trunk.trunk_id);
  ```

  ```python Python theme={null}
  import requests

  response = requests.post(
      "https://api.vobiz.ai/api/v1/Account/AUTH_ID/trunks",
      headers={
          "X-Auth-ID": "AUTH_ID",
          "X-Auth-Token": "AUTH_TOKEN",
          "Content-Type": "application/json",
      },
      json={
          "name": "My SIP Trunk",
          "trunk_type": "OUTBOUND",
          "max_concurrent_calls": 10,
      },
  )
  trunk = response.json()
  print(trunk["trunk_id"])
  ```

  ```go Go theme={null}
  package main

  import (
      "bytes"
      "encoding/json"
      "fmt"
      "net/http"
  )

  func main() {
      body, _ := json.Marshal(map[string]any{
          "name":                 "My SIP Trunk",
          "trunk_type":           "OUTBOUND",
          "max_concurrent_calls": 10,
      })
      req, _ := http.NewRequest("POST",
          "https://api.vobiz.ai/api/v1/Account/AUTH_ID/trunks",
  bytes.NewBuffer(body))
      req.Header.Set("X-Auth-ID", "AUTH_ID")
      req.Header.Set("X-Auth-Token", "AUTH_TOKEN")
      req.Header.Set("Content-Type", "application/json")

      resp, _ := (&http.Client{}).Do(req)
      defer resp.Body.Close()
      var trunk map[string]any
      json.NewDecoder(resp.Body).Decode(&trunk)
      fmt.Println(trunk["trunk_id"])
  }
  ```

  ```ruby Ruby theme={null}
  require 'net/http'
  require 'uri'
  require 'json'

  uri = URI('https://api.vobiz.ai/api/v1/Account/AUTH_ID/trunks')
  req = Net::HTTP::Post.new(uri)
  req['X-Auth-ID'] = 'AUTH_ID'
  req['X-Auth-Token'] = 'AUTH_TOKEN'
  req['Content-Type'] = 'application/json'
  req.body = {
    name: 'My SIP Trunk',
    trunk_type: 'OUTBOUND',
    max_concurrent_calls: 10
  }.to_json

  res = Net::HTTP.start(uri.host, uri.port, use_ssl: true) { |h| h.request(req) }
  puts JSON.parse(res.body)['trunk_id']
  ```

  ```csharp C# theme={null}
  using var client = new HttpClient();
  client.DefaultRequestHeaders.Add("X-Auth-ID", "AUTH_ID");
  client.DefaultRequestHeaders.Add("X-Auth-Token", "AUTH_TOKEN");

  var payload = new StringContent(
      System.Text.Json.JsonSerializer.Serialize(new {
  name = "My SIP Trunk",
  trunk_type = "OUTBOUND",
  max_concurrent_calls = 10
      }),
      System.Text.Encoding.UTF8,
      "application/json");

  var res = await client.PostAsync(
      "https://api.vobiz.ai/api/v1/Account/AUTH_ID/trunks", payload);
  Console.WriteLine(await res.Content.ReadAsStringAsync());
  ```
</CodeGroup>

## Response

Returns the complete trunk object, including the auto-generated `trunk_id` UUID and timestamps.

```json Response - 201 Created theme={null}
{
  "trunk_id": "aabbccdd-1234-5678-90ab-cdef12345678",
  "account_id": "MA_XXXXXXXX",
  "name": "My Outbound Trunk",
  "trunk_domain": "aabbccdd-1234-5678-90ab-cdef12345678.sip.vobiz.ai",
  "trunk_status": "active",
  "secure": false,
  "trunk_direction": "both",
  "concurrent_calls_limit": 10,
  "cps_limit": 2,
  "description": "",
  "transport": "udp",
  "recording": false,
  "enable_transcription": false,
  "pii_redaction": false,
  "webhook_method": "POST",
  "recording_webhook_enabled": false,
  "created_at": "2026-05-12T05:11:52.054462Z",
  "updated_at": "2026-05-12T05:11:52.054462Z"
}
```

<Tip>
  **Next Steps:**

  * Save the `trunk_id` for all future operations
  * Add credentials or IP ACLs for authentication
  * Configure origination URIs for outbound call routing
  * Test the trunk with a sample call before production use
</Tip>


## OpenAPI

````yaml POST /api/v1/Account/{auth_id}/trunks
openapi: 3.0.3
info:
  title: Vobiz API
  description: >
    The Vobiz API lets you make calls, manage phone numbers, configure SIP
    trunks, 

    and access account data programmatically.


    **Base URL:** `https://api.vobiz.ai`


    **Authentication:** Most requests require `X-Auth-ID` and `X-Auth-Token`
    headers.

    Selected account endpoints also accept an account access token as a Bearer
    token.

    Obtain account credentials from your [Vobiz
    Console](https://console.vobiz.ai).
  version: '1.0'
  contact:
    email: support@vobiz.ai
    url: https://vobiz.ai
servers:
  - url: https://api.vobiz.ai
    description: Production
security:
  - AuthID: []
    AuthToken: []
tags:
  - name: Account
    description: Manage your account details and credentials
  - name: Balance
    description: Retrieve balance and transaction history
  - name: Calls
    description: Make and manage outbound calls
  - name: Live Calls
    description: Retrieve and control in-progress calls
  - name: CDR
    description: Call detail records and history
  - name: Sub-Accounts
    description: Create and manage sub-accounts
  - name: Phone Numbers
    description: Manage phone numbers on your account
  - name: Trunks
    description: Configure SIP trunks for inbound and outbound calling
  - name: Conference
    description: Manage conference calls and members
  - name: Applications
    description: Manage voice and messaging applications with webhook URLs
  - name: Endpoints
    description: Manage SIP endpoints for IP phones, softphones, and SIP clients
  - name: Partner API
    description: >-
      Reseller and white-label endpoints for managing customer sub-accounts,
      balance transfers, transactions, CDRs, and DIDs across your partner
      ecosystem
  - name: Sub-Account KYC
    description: >-
      Per-sub-account KYC verification (PAN, GST, CIN, Aadhaar, DigiLocker) and
      hosted email/redirect KYC sessions. Authenticated as the parent main
      account.
  - name: Sub-Account KYC (Test Mode)
    description: >-
      Mock KYC endpoints that never call the upstream provider. Drive verified /
      failed / pending / error outcomes with magic inputs for integration
      testing.
  - name: Bulk Operations
    description: >-
      Endpoints that act on many records in one request. These accept the
      request, process it in the background, and deliver the result by email.
paths:
  /api/v1/Account/{auth_id}/trunks:
    post:
      tags:
        - Trunks
      summary: Create a trunk
      description: Create a new SIP trunk for inbound or outbound calling.
      operationId: create-trunk
      parameters:
        - $ref: '#/components/parameters/AuthId'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                name:
                  type: string
                  maxLength: 100
                  description: Trunk name.
                trunk_direction:
                  type: string
                  enum:
                    - inbound
                    - outbound
                  description: >-
                    Direction of the trunk - **`inbound` or `outbound` only** (a
                    trunk is one direction, not both).
                trunk_status:
                  type: string
                  enum:
                    - enabled
                    - disabled
                  description: 'Trunk status - `enabled` or `disabled` (note: not `active`).'
                secure:
                  type: boolean
                trunk_domain:
                  type: string
                  maxLength: 255
                  description: >-
                    SIP domain. Auto-generated as `{first8ofUUID}.sip.vobiz.ai`
                    if omitted.
                transport:
                  type: string
                  enum:
                    - udp
                    - tcp
                    - tls
                inbound_destination:
                  type: string
                  maxLength: 255
                description:
                  type: string
                  maxLength: 500
                concurrent_calls_limit:
                  type: integer
                  minimum: 0
                  maximum: 1000
                  description: >-
                    Stored on the trunk. The **enforced** concurrency limit is
                    account-level (account base + channel subscriptions), not
                    this field.
                cps_limit:
                  type: integer
                  minimum: 0
                  maximum: 100
                  description: >-
                    Stored on the trunk. The **enforced** CPS is account-level,
                    not this field.
                credential_uuid:
                  type: string
                  description: >-
                    Attach an existing SIP credential (username / password /
                    realm) by UUID.
                ipacl_uuid:
                  type: string
                  description: >-
                    Attach an existing IP access-control list (IP-based auth) by
                    UUID.
                primary_uri_uuid:
                  type: string
                  description: Primary origination URI UUID.
                fallback_uri_uuid:
                  type: string
                  description: Fallback origination URI UUID.
                recording:
                  type: boolean
                  default: false
                  description: Enable call recording.
                enable_transcription:
                  type: boolean
                  default: false
                  description: Auto-transcribe recordings when `recording=true`.
                pii_redaction:
                  type: boolean
                  default: false
                  description: Redact PII from transcriptions.
                pii_entity_types:
                  type: string
                  description: Comma-separated list of entity types to redact.
                webhook_url:
                  type: string
                  maxLength: 500
                  description: >
                    Customer webhook for call-admission events (`CallInitiated`
                    / `Hangup`).

                    Must be a valid **public** http/https URL. SSRF-validated -
                    localhost,

                    private (RFC1918), and cloud-metadata (`169.254.169.254`)
                    URLs are

                    rejected with `invalid webhook_url`. See [Trunk
                    Webhooks](/trunks/webhook).
                  example: https://example.com/vobiz/webhook
                webhook_method:
                  type: string
                  enum:
                    - POST
                    - GET
                  default: POST
                  description: HTTP method for the webhook callback.
                recording_webhook_enabled:
                  type: boolean
                  default: false
                  description: >-
                    Fire a `recording.completed` webhook to `webhook_url` after
                    a recording is saved.
                username:
                  type: string
                  maxLength: 100
                  deprecated: true
                  description: Deprecated - use `credential_uuid`.
                password:
                  type: string
                  maxLength: 100
                  deprecated: true
                  description: Deprecated - use `credential_uuid`.
                ip_whitelist:
                  type: array
                  items:
                    type: string
                  deprecated: true
                  description: Deprecated - use `ipacl_uuid`.
              required:
                - name
            example:
              name: Retell AI SIP
              trunk_direction: outbound
              transport: udp
              webhook_url: https://example.com/vobiz/webhook
              webhook_method: POST
              recording: true
              enable_transcription: true
              concurrent_calls_limit: 50
              cps_limit: 15
              credential_uuid: b1e2...
              ipacl_uuid: c3d4...
      responses:
        '200':
          description: Success
          content:
            application/json:
              schema:
                type: object
                properties:
                  trunk_id:
                    type: string
                  account_id:
                    type: string
                  name:
                    type: string
                  trunk_domain:
                    type: string
                  trunk_status:
                    type: string
                  secure:
                    type: boolean
                  trunk_direction:
                    type: string
                  concurrent_calls_limit:
                    type: integer
                  cps_limit:
                    type: integer
                  description:
                    type: string
                  transport:
                    type: string
                  recording:
                    type: boolean
                  enable_transcription:
                    type: boolean
                  pii_redaction:
                    type: boolean
                  webhook_method:
                    type: string
                  recording_webhook_enabled:
                    type: boolean
                  created_at:
                    type: string
                  updated_at:
                    type: string
                required:
                  - trunk_id
                  - account_id
                  - name
                  - trunk_domain
                  - trunk_status
                  - secure
                  - trunk_direction
                  - concurrent_calls_limit
                  - cps_limit
                  - description
                  - transport
                  - recording
                  - enable_transcription
                  - pii_redaction
                  - webhook_method
                  - recording_webhook_enabled
                  - created_at
                  - updated_at
        '201':
          description: Trunk created
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Trunk'
              example:
                trunk_id: aabbccdd-1234-5678-90ab-cdef12345678
                account_id: MA_XXXXXXXX
                name: My Outbound Trunk
                trunk_domain: aabbccdd-1234-5678-90ab-cdef12345678.sip.vobiz.ai
                trunk_status: active
                secure: false
                trunk_direction: outbound
                concurrent_calls_limit: 10
                cps_limit: 2
                description: ''
                transport: udp
                recording: false
                enable_transcription: false
                pii_redaction: false
                webhook_method: POST
                recording_webhook_enabled: false
                created_at: '2026-03-25T05:11:52.054462Z'
                updated_at: '2026-03-25T05:11:52.054462Z'
components:
  parameters:
    AuthId:
      name: auth_id
      in: path
      required: true
      description: Your account Auth ID
      schema:
        type: string
        example: MA_XXXXXX
  schemas:
    Trunk:
      type: object
      properties:
        id:
          type: string
        name:
          type: string
        trunk_type:
          type: string
          enum:
            - INBOUND
            - OUTBOUND
        sip_domain:
          type: string
          example: abc123.sip.vobiz.ai
        enabled:
          type: boolean
        created_at:
          type: string
          format: date-time
  securitySchemes:
    AuthID:
      type: apiKey
      in: header
      name: X-Auth-ID
      description: Your Vobiz account Auth ID
    AuthToken:
      type: apiKey
      in: header
      name: X-Auth-Token
      description: Your Vobiz account Auth Token

````

This documentation is built and hosted on [Mintlify](https://mintlify.com), a developer documentation platform.